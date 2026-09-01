#!/usr/bin/env bash
set -eo pipefail

log() { echo "[provision] $*"; }
die() { echo "[provision][error] $*" >&2; exit 1; }

WORKSPACE="${WORKSPACE:-/workspace}"

# ai-dock interactive images expose these helpers; serverless images do not.
if [ -f /opt/ai-dock/etc/environment.sh ]; then
  # shellcheck source=/dev/null
  . /opt/ai-dock/etc/environment.sh
fi
if [ -f /opt/ai-dock/bin/venv-set.sh ]; then
  # shellcheck source=/dev/null
  . /opt/ai-dock/bin/venv-set.sh comfyui
fi

if [ -f /opt/supervisor-scripts/comfyui.sh ]; then
  # Vast official ComfyUI base image: ComfyUI runs from ${WORKSPACE}/ComfyUI
  COMFYUI_ROOT="${COMFYUI_PATH:-${WORKSPACE}/ComfyUI}"
  MODEL_DIR="${MODEL_DIR:-$COMFYUI_ROOT/models/diffusion_models}"
  CLIP_DIR="${CLIP_DIR:-$COMFYUI_ROOT/models/text_encoders}"
  VAE_DIR="${VAE_DIR:-$COMFYUI_ROOT/models/vae}"
elif [ "${SERVERLESS,,}" = "true" ]; then
  COMFYUI_ROOT="${COMFYUI_PATH:-${WORKSPACE}/ComfyUI}"
  MODEL_DIR="${MODEL_DIR:-$COMFYUI_ROOT/models/diffusion_models}"
  CLIP_DIR="${CLIP_DIR:-$COMFYUI_ROOT/models/text_encoders}"
  VAE_DIR="${VAE_DIR:-$COMFYUI_ROOT/models/vae}"
else
  COMFYUI_ROOT="${COMFYUI_PATH:-/opt/ComfyUI}"
  if [ -d "$WORKSPACE/storage/stable_diffusion/models" ]; then
    MODEL_DIR="${MODEL_DIR:-$WORKSPACE/storage/stable_diffusion/models/unet}"
    CLIP_DIR="${CLIP_DIR:-$WORKSPACE/storage/stable_diffusion/models/clip}"
    VAE_DIR="${VAE_DIR:-$WORKSPACE/storage/stable_diffusion/models/vae}"
  else
    MODEL_DIR="${MODEL_DIR:-$COMFYUI_ROOT/models/diffusion_models}"
    CLIP_DIR="${CLIP_DIR:-$COMFYUI_ROOT/models/text_encoders}"
    VAE_DIR="${VAE_DIR:-$COMFYUI_ROOT/models/vae}"
  fi
fi

LORA_DIR="${LORA_DIR:-$COMFYUI_ROOT/models/krea2/loras}"

VENV_PYTHON="${VENV_PYTHON:-}"
if [ -z "$VENV_PYTHON" ] && [ -n "${COMFYUI_VENV_PYTHON:-}" ] && [ -x "$COMFYUI_VENV_PYTHON" ]; then
  VENV_PYTHON="$COMFYUI_VENV_PYTHON"
fi
if [ -z "$VENV_PYTHON" ] && [ -x "$COMFYUI_ROOT/venv/bin/python" ]; then
  VENV_PYTHON="$COMFYUI_ROOT/venv/bin/python"
fi
if [ -z "$VENV_PYTHON" ] && [ -x /opt/ai-dock/venv/comfyui/bin/python ]; then
  VENV_PYTHON=/opt/ai-dock/venv/comfyui/bin/python
fi
if [ -z "$VENV_PYTHON" ] && [ -x /venv/main/bin/python ]; then
  VENV_PYTHON=/venv/main/bin/python
fi
if [ -z "$VENV_PYTHON" ]; then
  VENV_PYTHON="$(command -v python3 || command -v python || true)"
fi
[ -n "$VENV_PYTHON" ] || die "python3 not found"

MODEL_S3_KEY="${MODEL_S3_KEY:-models/diffusion_models/lustifyNSFWCheckpoint_v10Krea2.safetensors}"
MODEL_FILENAME="${MODEL_FILENAME:-lustifyNSFWCheckpoint_v10Krea2.safetensors}"
CLIP_S3_KEY="${CLIP_S3_KEY:-models/text_encoders/qwen3vl_4b_fp8_scaled.safetensors}"
CLIP_FILENAME="${CLIP_FILENAME:-qwen3vl_4b_fp8_scaled.safetensors}"
VAE_S3_KEY="${VAE_S3_KEY:-models/vae/qwen_image_vae.safetensors}"
VAE_FILENAME="${VAE_FILENAME:-qwen_image_vae.safetensors}"
LORA_S3_KEY="${LORA_S3_KEY:-models/krea2/loras/penis_size_krea2_v2_loraholic.safetensors}"
LORA_FILENAME="${LORA_FILENAME:-penis_size_krea2_v2_loraholic.safetensors}"
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
  "$MODEL_DIR/$MODEL_FILENAME" \
  required
download_s3_object \
  "$CLIP_S3_KEY" \
  "$CLIP_DIR/$CLIP_FILENAME" \
  required
download_s3_object \
  "$VAE_S3_KEY" \
  "$VAE_DIR/$VAE_FILENAME" \
  required
download_s3_object \
  "$LORA_S3_KEY" \
  "$LORA_DIR/$LORA_FILENAME" \
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
