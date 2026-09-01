#!/usr/bin/env python3
import argparse
import asyncio
import copy
import datetime as dt
import json
import os
import sys
import time
import uuid
from pathlib import Path

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
