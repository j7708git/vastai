#!/usr/bin/env python3
import argparse
import asyncio
import copy
import datetime as dt
import json
import os
import random
import sys
import time
import uuid
from pathlib import Path
import urllib.request

import boto3
from aiohttp import web
from vastai import Serverless


DEFAULT_WORKFLOW = "vast-krea2-t2i.json"
DEFAULT_ENDPOINT = "vast-comfyui-krea2"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765
DEFAULT_S3_PROFILE = "agent-toolkit"
DEFAULT_S3_BUCKET = "vast-comfyui-730116069170-ap-southeast-2-an"
DEFAULT_S3_PREFIX = "krea2"

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}

_COMFY_JOBS: dict[str, dict] = {}
_COMFY_IMAGES: dict[str, bytes] = {}


def load_local_env(path: Path) -> None:
    if not path.is_file():
        return

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def load_workflow(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def replace_strings(value, old: str, new: str):
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [replace_strings(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: replace_strings(item, old, new) for key, item in value.items()}
    return value


def update_node_input(workflow: dict, class_type: str, field: str, value):
    for node in workflow.values():
        if node.get("class_type") == class_type:
            node["inputs"][field] = value


def parse_size(value):
    if not value:
        return None, None
    if isinstance(value, str) and "x" in value.lower():
        width, height = value.lower().split("x", 1)
        return int(width), int(height)
    if isinstance(value, dict):
        return value.get("width"), value.get("height")
    return None, None


def adapt_workflow(
    workflow: dict,
    prompt: str,
    width: int,
    height: int,
    steps: int,
    seed,
    cfg_scale,
    sampler,
    scheduler,
    batch_size: int,
) -> dict:
    workflow = copy.deepcopy(workflow)
    workflow = replace_strings(workflow, "%prompt%", prompt)
    if seed is not None:
        workflow = replace_strings(workflow, "__RANDOM_INT__", str(seed))

    update_node_input(workflow, "EmptyLatentImage", "width", width)
    update_node_input(workflow, "EmptyLatentImage", "height", height)
    update_node_input(workflow, "EmptyLatentImage", "batch_size", batch_size)
    update_node_input(workflow, "KSampler", "steps", steps)
    if cfg_scale is not None:
        update_node_input(workflow, "KSampler", "cfg", cfg_scale)
    if sampler:
        update_node_input(workflow, "KSampler", "sampler_name", sampler)
    if scheduler:
        update_node_input(workflow, "KSampler", "scheduler", scheduler)

    return workflow


def build_payload(args) -> dict:
    workflow = adapt_workflow(
        load_workflow(args.workflow),
        prompt=args.prompt,
        width=args.width,
        height=args.height,
        steps=args.steps,
        seed=args.seed,
        cfg_scale=args.cfg_scale,
        sampler=args.sampler,
        scheduler=args.scheduler,
        batch_size=args.batch_size,
    )
    return {
        "input": {
            "request_id": str(uuid.uuid4()),
            "workflow_json": workflow,
        }
    }


async def generate_with_vast(payload: dict, endpoint_name: str, api_key: str):
    async with Serverless(api_key=api_key) as client:
        endpoint = await client.get_endpoint(name=endpoint_name)
        return await endpoint.request("/generate/sync", payload, cost=100)


def s3_client(profile_name: str, bucket: str):
    session = boto3.Session(profile_name=profile_name)
    return session.client(
        "s3",
        region_name="ap-southeast-2",
        endpoint_url="https://s3.ap-southeast-2.amazonaws.com",
    )


def normalize_vast_output(raw: dict, profile_name: str, bucket: str, prefix: str, clean: bool):
    if not profile_name or not bucket:
        return raw

    response = raw.get("response", raw)
    request_id = response.get("id")
    outputs = response.get("output") or []
    if not request_id or not outputs:
        return raw

    client = s3_client(profile_name, bucket)
    for item in outputs:
        filename = item.get("filename")
        if not filename:
            continue
        source_key = f"{request_id}/{filename}"
        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target_key = f"{prefix}/{timestamp}_{filename}"
        client.copy_object(
            Bucket=bucket,
            Key=target_key,
            CopySource={"Bucket": bucket, "Key": source_key},
        )
        if clean:
            client.delete_object(Bucket=bucket, Key=source_key)
        item["url"] = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": target_key},
            ExpiresIn=604800,
        )
        item["subfolder"] = prefix

    return raw


def response_payload(payload: dict) -> dict:
    response = payload.get("response", payload)
    outputs = response.get("output") or []
    if not outputs or not outputs[0].get("url"):
        raise ValueError("Vast completed without an S3 image URL.")
    return {
        "created": int(time.time()),
        "data": [
            {
                "url": outputs[0]["url"],
                "filename": outputs[0].get("filename"),
                "request_id": response.get("id"),
            }
        ],
    }


def extract_workflow(data: dict) -> dict:
    workflow = data.get("prompt", data)
    if isinstance(workflow, str):
        workflow = json.loads(workflow)
    if isinstance(workflow, dict) and "prompt" in workflow:
        inner = workflow["prompt"]
        if isinstance(inner, (str, dict)):
            workflow = inner
    if isinstance(workflow, str):
        workflow = json.loads(workflow)
    if not isinstance(workflow, dict):
        raise ValueError("ComfyUI workflow must be a JSON object.")
    return workflow


def download_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def object_info_data() -> dict:
    return {
        "CheckpointLoaderSimple": {
            "input": {
                "required": {
                    "ckpt_name": [
                        [
                            "lustifyNSFWCheckpoint_v10Krea2.safetensors",
                            "moodyKrea2Mix_v70.safetensors",
                        ]
                    ]
                }
            }
        },
        "UnetLoaderGGUF": {
            "input": {
                "required": {
                    "unet_name": [[""]]
                }
            }
        },
        "KSampler": {
            "input": {
                "required": {
                    "sampler_name": [["euler", "dpmpp_2m", "dpmpp_sde"]],
                    "scheduler": [["simple", "normal", "karras"]],
                    "steps": [[8]],
                    "cfg": [[1.0]],
                    "denoise": [[1.0]],
                }
            }
        },
        "UNETLoader": {
            "input": {
                "required": {
                    "unet_name": [
                        [
                            "lustifyNSFWCheckpoint_v10Krea2.safetensors",
                            "moodyKrea2Mix_v70.safetensors",
                        ]
                    ]
                }
            }
        },
        "CLIPLoader": {
            "input": {
                "required": {
                    "clip_name": [["qwen3vl_4b_fp8_scaled.safetensors"]]
                }
            }
        },
        "VAELoader": {
            "input": {
                "required": {
                    "vae_name": [["qwen_image_vae.safetensors"]]
                }
            }
        },
        "SaveImage": {"input": {"required": {"filename_prefix": [["vast/krea2"]]}}},
        "CLIPTextEncode": {
            "input": {"required": {"text": [[], {"default": ""}], "clip": [["56", 0]]}}
        },
        "ConditioningZeroOut": {
            "input": {"required": {"conditioning": [["51", 0]]}}
        },
        "PrimitiveStringMultiline": {
            "input": {"required": {"value": [[], {"default": ""}]}}
        },
        "EmptyLatentImage": {
            "input": {
                "required": {
                    "width": [[768]],
                    "height": [[768]],
                    "batch_size": [[1]],
                }
            }
        },
        "VAEDecode": {"input": {"required": {"samples": [["53", 0]], "vae": [["57", 0]]}}},
        "ImageCompressor": {
            "input": {
                "required": {
                    "images": [["54", 0]],
                    "format": [["PNG"]],
                }
            }
        },
    }


async def run_comfy_job(prompt_id: str, workflow: dict, app: web.Application):
    job = _COMFY_JOBS[prompt_id]
    try:
        if "__RANDOM_INT__" in json.dumps(workflow):
            workflow = replace_strings(
                workflow,
                "__RANDOM_INT__",
                str(random.randint(0, 2**31 - 1)),
            )
        payload = {
            "input": {
                "request_id": prompt_id,
                "workflow_json": workflow,
            }
        }
        raw = await generate_with_vast(payload, app["endpoint_name"], app["api_key"])
        raw = normalize_vast_output(
            raw,
            app["s3_profile"],
            app["s3_bucket"],
            app["s3_prefix"],
            app["clean_s3"],
        )
        response = raw.get("response", raw)
        output_map = {}
        for item in response.get("output") or []:
            filename = item.get("filename")
            url = item.get("url")
            if not filename or not url:
                continue
            data = await asyncio.to_thread(download_bytes, url)
            _COMFY_IMAGES[filename] = data
            node_id = str(item.get("node_id") or "78")
            output_map.setdefault(node_id, {"images": []})["images"].append(
                {
                    "filename": filename,
                    "subfolder": item.get("subfolder", ""),
                    "type": item.get("output_type", "output"),
                }
            )
        if not output_map:
            raise ValueError("Vast completed without a ComfyUI image output.")
        job["outputs"] = output_map
        job["status"] = "success"
    except Exception as exc:
        job["status"] = "error"
        job["messages"] = [
            [
                "execution_error",
                {
                    "node_type": "Bridge",
                    "node_id": "0",
                    "exception_message": str(exc),
                },
            ]
        ]
    finally:
        job["completed"] = True


def json_response(payload: dict, status: int = 200):
    return web.json_response(payload, status=status, headers=CORS_HEADERS)


def parse_request_body(body: dict, workflow_path: str) -> dict:
    prompt = body.get("prompt") or body.get("instruction") or ""
    if not prompt.strip():
        raise ValueError("prompt is required")

    width = body.get("width")
    height = body.get("height")
    fallback_width, fallback_height = parse_size(body.get("size"))
    if width is None:
        width = fallback_width
    if height is None:
        height = fallback_height

    seed = body.get("seed")
    if seed is not None:
        seed = int(seed)

    batch_size = body.get("n", body.get("batch_size"))
    if batch_size is None:
        batch_size = 1
    batch_size = max(1, min(int(batch_size), 4))

    steps = body.get("steps", 8)
    cfg_scale = body.get("cfg_scale", body.get("cfg"))
    sampler = body.get("sampler") or body.get("sampler_name")
    scheduler = body.get("scheduler")

    workflow = adapt_workflow(
        load_workflow(workflow_path),
        prompt=prompt,
        width=int(width or 768),
        height=int(height or 768),
        steps=int(steps),
        seed=seed,
        cfg_scale=float(cfg_scale) if cfg_scale is not None else None,
        sampler=sampler,
        scheduler=scheduler,
        batch_size=batch_size,
    )
    return {
        "input": {
            "request_id": str(uuid.uuid4()),
            "workflow_json": workflow,
        }
    }


async def handle_generate(request: web.Request):
    api_token = request.app.get("api_token")
    if api_token:
        authorization = request.headers.get("Authorization", "")
        if authorization != f"Bearer {api_token}":
            return json_response({"error": "Unauthorized"}, status=401)

    try:
        body = await request.json()
    except Exception:
        return json_response({"error": "Invalid JSON body"}, status=400)

    try:
        payload = parse_request_body(body, request.app["workflow_path"])
        raw = await generate_with_vast(
            payload,
            request.app["endpoint_name"],
            request.app["api_key"],
        )
        raw = normalize_vast_output(
            raw,
            request.app["s3_profile"],
            request.app["s3_bucket"],
            request.app["s3_prefix"],
            request.app["clean_s3"],
        )
        return json_response(response_payload(raw))
    except Exception as exc:
        return json_response({"error": str(exc)}, status=502)


async def handle_health(request: web.Request):
    return json_response(
        {
            "ok": True,
            "endpoint": request.app["endpoint_name"],
        }
    )


async def handle_comfy_prompt(request: web.Request):
    try:
        raw = await request.json()
        workflow = extract_workflow(raw)
    except Exception:
        return json_response({"error": "Invalid ComfyUI workflow"}, status=400)

    prompt_id = uuid.uuid4().hex
    _COMFY_JOBS[prompt_id] = {
        "id": prompt_id,
        "workflow": workflow,
        "status": "pending",
        "completed": False,
        "outputs": {},
        "messages": [],
    }
    asyncio.create_task(run_comfy_job(prompt_id, workflow, request.app))
    return json_response(
        {
            "prompt_id": prompt_id,
            "number": 1,
            "node_errors": {},
        }
    )


def comfy_history_item(job: dict) -> dict:
    return {
        "prompt": job["workflow"],
        "outputs": job["outputs"],
        "status": {
            "status_str": job["status"],
            "completed": job["completed"],
            "messages": job["messages"],
        },
    }


async def handle_comfy_history(request: web.Request):
    prompt_id = request.match_info.get("prompt_id")
    history = {
        job_id: comfy_history_item(job)
        for job_id, job in _COMFY_JOBS.items()
        if job["completed"]
    }
    if prompt_id:
        return json_response(history.get(prompt_id, {}))
    return json_response(history)


async def handle_comfy_view(request: web.Request):
    filename = request.query.get("filename", "")
    image = _COMFY_IMAGES.get(filename)
    if image is None:
        return json_response({"error": "Image not found"}, status=404)
    return web.Response(body=image, content_type="image/png", headers=CORS_HEADERS)


async def handle_system_stats(request: web.Request):
    return json_response(
        {
            "system": {
                "comfyui_version": "vast-bridge",
                "python_version": "3.13",
            },
            "devices": [],
        }
    )


async def handle_object_info(request: web.Request):
    data = object_info_data()
    class_type = request.match_info.get("class_type")
    if class_type:
        if class_type not in data:
            return json_response({})
        return json_response({class_type: data[class_type]})
    return json_response(data)


async def handle_interrupt(request: web.Request):
    return json_response({"ok": True})


async def handle_options(request: web.Request):
    return web.Response(status=204, headers=CORS_HEADERS)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OpenAI-compatible bridge for Vast Serverless ComfyUI."
    )
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--s3-profile", default=DEFAULT_S3_PROFILE)
    parser.add_argument("--s3-bucket", default=DEFAULT_S3_BUCKET)
    parser.add_argument("--s3-prefix", default=DEFAULT_S3_PREFIX)
    parser.add_argument("--api-token", default=os.environ.get("BRIDGE_TOKEN"))
    parser.add_argument(
        "--keep-s3",
        action="store_true",
        help="Keep Vast's original request-id S3 objects after copying to krea2.",
    )
    parser.add_argument("--prompt", help="Prompt for a one-off local test.")
    parser.add_argument("--width", type=int, default=768)
    parser.add_argument("--height", type=int, default=768)
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--cfg-scale", type=float)
    parser.add_argument("--sampler")
    parser.add_argument("--scheduler")
    parser.add_argument("--batch-size", type=int, default=1)
    args = parser.parse_args()

    local_env = Path(__file__).resolve().parent / "vast-api-key.env"
    load_local_env(local_env)
    api_key = os.environ.get("VAST_API_KEY")
    if not api_key:
        print("VAST_API_KEY is required in vast-api-key.env", file=sys.stderr)
        return 1
    api_token = os.environ.get("BRIDGE_TOKEN") or args.api_token

    app = web.Application()
    app["api_key"] = api_key
    app["api_token"] = api_token
    app["endpoint_name"] = args.endpoint
    app["workflow_path"] = args.workflow
    app["s3_profile"] = args.s3_profile
    app["s3_bucket"] = args.s3_bucket
    app["s3_prefix"] = args.s3_prefix
    app["clean_s3"] = not args.keep_s3
    app.router.add_post("/v1/images/generations", handle_generate)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/system_stats", handle_system_stats)
    app.router.add_get("/object_info", handle_object_info)
    app.router.add_get("/object_info/{class_type}", handle_object_info)
    app.router.add_post("/prompt", handle_comfy_prompt)
    app.router.add_get("/history", handle_comfy_history)
    app.router.add_get("/history/{prompt_id}", handle_comfy_history)
    app.router.add_get("/view", handle_comfy_view)
    app.router.add_post("/interrupt", handle_interrupt)
    app.router.add_get("/v1/system_stats", handle_system_stats)
    app.router.add_get("/v1/object_info", handle_object_info)
    app.router.add_get("/v1/object_info/{class_type}", handle_object_info)
    app.router.add_post("/v1/prompt", handle_comfy_prompt)
    app.router.add_get("/v1/history", handle_comfy_history)
    app.router.add_get("/v1/history/{prompt_id}", handle_comfy_history)
    app.router.add_get("/v1/view", handle_comfy_view)
    app.router.add_post("/v1/interrupt", handle_interrupt)
    app.router.add_route("OPTIONS", "/{tail:.*}", handle_options)

    if args.prompt:
        payload = build_payload(args)
        raw = asyncio.run(generate_with_vast(payload, args.endpoint, api_key))
        raw = normalize_vast_output(
            raw,
            args.s3_profile,
            args.s3_bucket,
            args.s3_prefix,
            not args.keep_s3,
        )
        print(json.dumps(raw, indent=2, ensure_ascii=False))
        return 0

    web.run_app(app, host=args.host, port=args.port, print=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
