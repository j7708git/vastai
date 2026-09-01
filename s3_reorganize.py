#!/usr/bin/env python3
import argparse
import datetime as dt
from pathlib import Path

import boto3


DEFAULT_BUCKET = "vast-comfyui-730116069170-ap-southeast-2-an"
DEFAULT_PREFIX = "krea2"


def s3_client(profile_name: str):
    session = boto3.Session(profile_name=profile_name)
    return session.client(
        "s3",
        region_name="ap-southeast-2",
        endpoint_url="https://s3.ap-southeast-2.amazonaws.com",
    )


def target_key(source_key: str, prefix: str) -> str:
    filename = Path(source_key).name
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if source_key.startswith("test-"):
        return f"{prefix}/{timestamp}_benchmark_{filename}"
    return f"{prefix}/{timestamp}_{filename}"


def reorganize(profile_name: str, bucket: str, prefix: str, apply: bool) -> int:
    client = s3_client(profile_name)
    paginator = client.get_paginator("list_objects_v2")
    moved = 0
    skipped = 0

    for page in paginator.paginate(Bucket=bucket):
        for item in page.get("Contents", []):
            source = item["Key"]
            if source.endswith("/") or source.startswith("models/") or source.startswith(f"{prefix}/"):
                skipped += 1
                continue

            destination = target_key(source, prefix)
            if not apply:
                print(f"would move {source} -> {destination}")
            else:
                client.copy_object(
                    Bucket=bucket,
                    Key=destination,
                    CopySource={"Bucket": bucket, "Key": source},
                )
                client.delete_object(Bucket=bucket, Key=source)
                print(f"moved {source} -> {destination}")
            moved += 1

    print(f"summary: moved={moved} skipped={skipped}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Move Vast output objects under a stable S3 prefix."
    )
    parser.add_argument("--profile", default="agent-toolkit")
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Copy and delete source objects. Without this, only show a dry run.",
    )
    args = parser.parse_args()
    return reorganize(args.profile, args.bucket, args.prefix, args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
