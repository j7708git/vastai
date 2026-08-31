#!/usr/bin/env bash
set -eo pipefail

log() { echo "[provision] $*"; }
die() { echo "[provision][error] $*" >&2; exit 1; }

WORKSPACE="${WORKSPACE:-/workspace}"
COMFYUI_ROOT="${COMFYUI_PATH:-${WORKSPACE}/ComfyUI}"
VENV_PYTHON="${VENV_PYTHON:-/venv/main/bin/python}"
if [ ! -x "$VENV_PYTHON" ]; then
  VENV_PYTHON="$(command -v python3 || command -v python || true)"
fi
[ -n "$VENV_PYTHON" ] || die "python3 not found"

MODEL_S3_KEY="${MODEL_S3_KEY:-models/diffusion_models/lustifyNSFWCheckpoint_v10Krea2.safetensors}"
MODEL_FILENAME="${MODEL_FILENAME:-lustifyNSFWCheckpoint_v10Krea2.safetensors}"
CLIP_S3_KEY="${CLIP_S3_KEY:-models/text_encoders/qwen3vl_4b_fp8_scaled.safetensors}"
CLIP_FILENAME="${CLIP_FILENAME:-qwen3vl_4b_fp8_scaled.safetensors}"
VAE_S3_KEY="${VAE_S3_KEY:-models/vae/qwen_image_vae.safetensors}"
VAE_FILENAME="${VAE_FILENAME:-qwen_image_vae.safetensors}"
IMAGE_COMPRESSOR_REPO="${IMAGE_COMPRESSOR_REPO:-https://github.com/liuqianhonga/ComfyUI-Image-Compressor.git}"

export S3_REGION="${S3_REGION:-ap-southeast-2}"
export S3_ENDPOINT_URL="${S3_ENDPOINT_URL:-https://s3.ap-southeast-2.amazonaws.com}"

[ -n "${S3_BUCKET_NAME:-}" ] || die "S3_BUCKET_NAME is required"
[ -n "${S3_ACCESS_KEY_ID:-}" ] || die "S3_ACCESS_KEY_ID is required"
[ -n "${S3_SECRET_ACCESS_KEY:-}" ] || die "S3_SECRET_ACCESS_KEY is required"

if ! "$VENV_PYTHON" -c 'import boto3' >/dev/null 2>&1; then
  log "installing boto3"
  "$VENV_PYTHON" -m pip install --no-cache-dir boto3 || die "failed to install boto3"
fi

download_s3_object() {
  local key="$1"
  local dest="$2"
  local required="${3:-optional}"
  local tmp="${dest}.part"
  local rc

  mkdir -p "$(dirname "$dest")"
  if [ -s "$dest" ]; then
    log "already present, skip: $dest"
    return 0
  fi
  if [ -f "$tmp" ]; then
    rm -f "$tmp"
  fi

  cat > /tmp/vast_s3_download.py <<'PY'
import os
import sys

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError

key, dest = sys.argv[1], sys.argv[2]
tmp = dest + ".part"
os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)

client = boto3.client(
    "s3",
    endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None,
    region_name=os.environ.get("S3_REGION") or None,
    aws_access_key_id=os.environ.get("S3_ACCESS_KEY_ID"),
    aws_secret_access_key=os.environ.get("S3_SECRET_ACCESS_KEY"),
)

try:
    client.download_file(
        os.environ["S3_BUCKET_NAME"],
        key,
        tmp,
        Config=TransferConfig(
            multipart_threshold=64 * 1024 * 1024,
            max_concurrency=10,
            use_threads=True,
        ),
    )
    os.replace(tmp, dest)
except ClientError as exc:
    code = exc.response.get("Error", {}).get("Code", "")
    if code == "NoSuchKey":
        if os.path.exists(tmp):
            os.remove(tmp)
        sys.exit(3)
    raise
PY

  set +e
  "$VENV_PYTHON" /tmp/vast_s3_download.py "$key" "$dest"
  rc=$?
  set -e

  if [ "$rc" -eq 3 ]; then
    if [ "$required" = "required" ]; then
      die "required S3 object not found: $key"
    fi
    log "warning: optional object missing, skip: $key"
    return 0
  fi
  if [ "$rc" -ne 0 ]; then
    die "failed to download $key (rc=$rc)"
  fi
  log "downloaded: $dest"
}

log "ComfyUI root: $COMFYUI_ROOT"

download_s3_object \
  "$MODEL_S3_KEY" \
  "$COMFYUI_ROOT/models/diffusion_models/$MODEL_FILENAME" \
  required
download_s3_object \
  "$CLIP_S3_KEY" \
  "$COMFYUI_ROOT/models/text_encoders/$CLIP_FILENAME" \
  required
download_s3_object \
  "$VAE_S3_KEY" \
  "$COMFYUI_ROOT/models/vae/$VAE_FILENAME" \
  required

NODE_DIR="$COMFYUI_ROOT/custom_nodes/comfyui-image-compressor"
if [ ! -d "$NODE_DIR" ]; then
  command -v git >/dev/null 2>&1 || die "git not found"
  log "cloning ComfyUI-Image-Compressor"
  git clone --depth 1 "$IMAGE_COMPRESSOR_REPO" "$NODE_DIR" \
    || die "failed to clone ComfyUI-Image-Compressor"
else
  log "custom node already present: $NODE_DIR"
fi

if [ -f "$NODE_DIR/requirements.txt" ]; then
  "$VENV_PYTHON" -m pip install --no-cache-dir -r "$NODE_DIR/requirements.txt" \
    || log "warning: pip install failed for custom node requirements"
fi

log "provisioning complete"
