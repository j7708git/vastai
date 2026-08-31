#!/usr/bin/env python3
import argparse
import asyncio
import copy
import json
import os
import sys
import uuid
from pathlib import Path

from vastai import Serverless


DEFAULT_WORKFLOW = "vast-krea2-t2i.json"
DEFAULT_ENDPOINT = "my-comfyui-endpoint"


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


def build_payload(args) -> dict:
    workflow = copy.deepcopy(load_workflow(args.workflow))
    if args.prompt:
        workflow = replace_strings(workflow, "%prompt%", args.prompt)
    if args.seed is not None:
        workflow = replace_strings(workflow, "__RANDOM_INT__", str(args.seed))
    if args.width is not None:
        update_node_input(workflow, "EmptyLatentImage", "width", args.width)
    if args.height is not None:
        update_node_input(workflow, "EmptyLatentImage", "height", args.height)
    if args.steps is not None:
        update_node_input(workflow, "KSampler", "steps", args.steps)

    return {
        "input": {
            "request_id": str(uuid.uuid4()),
            "workflow_json": workflow,
        }
    }


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send the Krea2 text-to-image workflow to Vast Serverless."
    )
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--steps", type=int)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()

    load_local_env(Path(__file__).resolve().parent / "vast-api-key.env")
    api_key = os.environ.get("VAST_API_KEY")
    if not api_key:
        print("VAST_API_KEY is required", file=sys.stderr)
        return 1

    payload = build_payload(args)
    async with Serverless(api_key=api_key) as client:
        endpoint = await client.get_endpoint(name=args.endpoint)
        response = await endpoint.request("/generate/sync", payload)

    print(json.dumps(response, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
