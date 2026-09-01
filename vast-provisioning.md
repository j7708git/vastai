# Vast.ai ComfyUI provisioning

## Official interactive template

`provisioning.sh` 同時支援 Vast.ai 官方互動式 ComfyUI template 與原本的
Serverless template。

互動式 template 需要設定：

```text
PROVISIONING_SCRIPT=https://raw.githubusercontent.com/j7708git/vastai/main/provisioning.sh
COMFYUI_ARGS=--disable-auto-launch --port 18188 --enable-cors-header
WEB_ENABLE_AUTH=false
WEB_ENABLE_HTTPS=false
CF_QUICK_TUNNELS=true
OPEN_BUTTON_PORT=8188
```

如果 template 原本已有 `OPEN_BUTTON_PORT`，直接把值改成 `8188` 就好，不要
重複新增。

互動式 image 會優先下載到 ai-dock 的 workspace storage：

```text
${WORKSPACE}/storage/stable_diffusion/models/unet/
${WORKSPACE}/storage/stable_diffusion/models/clip/
${WORKSPACE}/storage/stable_diffusion/models/vae/
```

如果 workspace storage 不存在，會改寫到 `/opt/ComfyUI/models/...`。
完整的 SillyTavern 設定步驟見 `vast-interactive-comfyui-template.md`。

## S3 objects expected by `provisioning.sh`

```text
models/diffusion_models/lustifyNSFWCheckpoint_v10Krea2.safetensors
models/text_encoders/qwen3vl_4b_fp8_scaled.safetensors
models/vae/qwen_image_vae.safetensors
```

These three objects are confirmed present in the bucket. The provisioning
script will fail early if any one is missing.

## Hosted script

Vast fetches `PROVISIONING_SCRIPT` over HTTP. This repository is public and the
raw URL is:

```text
https://raw.githubusercontent.com/j7708git/vastai/main/provisioning.sh
```

## Vast template environment variables

Set these in the template:

```text
PROVISIONING_SCRIPT=https://raw.githubusercontent.com/j7708git/vastai/main/provisioning.sh
```

The existing account-level `S3_*` variables are reused:

```text
S3_BUCKET_NAME
S3_ACCESS_KEY_ID
S3_SECRET_ACCESS_KEY
S3_ENDPOINT_URL
S3_REGION
```

Optional overrides:

```text
MODEL_S3_KEY=models/diffusion_models/lustifyNSFWCheckpoint_v10Krea2.safetensors
MODEL_FILENAME=lustifyNSFWCheckpoint_v10Krea2.safetensors
CLIP_S3_KEY=models/text_encoders/qwen3vl_4b_fp8_scaled.safetensors
CLIP_FILENAME=qwen3vl_4b_fp8_scaled.safetensors
VAE_S3_KEY=models/vae/qwen_image_vae.safetensors
VAE_FILENAME=qwen_image_vae.safetensors
```

## Note on the local workflow

The workspace now also contains:

```text
vast-krea2-t2i.json          Vast-ready Krea2 text-to-image workflow
vast_krea2_client.py         Local client that substitutes %prompt%
```

The ready workflow uses:

```text
unet_name = lustifyNSFWCheckpoint_v10Krea2.safetensors
clip_name = qwen3vl_4b_fp8_scaled.safetensors
vae_name  = qwen_image_vae.safetensors
```

To switch to the other Krea2 model, set the overlay variables in the Vast
template:

```text
MODEL_S3_KEY=models/diffusion_models/moodyKrea2Mix_v70.safetensors
MODEL_FILENAME=moodyKrea2Mix_v70.safetensors
```

The Flux 2.9B model is also in the bucket but is not used by this Krea2
workflow and is not downloaded by the current provisioning script.

## Send a request

Install the Vast client dependency:

```bash
pip install vastai
```

Set the Vast API key:

```bash
export VAST_API_KEY=your-vast-api-key
```

Run the included client:

```bash
python vast_krea2_client.py \
  --endpoint my-comfyui-endpoint \
  --prompt "a cinematic portrait, dramatic lighting, detailed"
```

Optional arguments:

```text
--width 768
--height 768
--steps 8
--seed 12345
```

The client replaces `%prompt%` in the workflow before sending it. If a seed
is supplied, it also replaces `__RANDOM_INT__`; otherwise Vast generates a
random seed. Generated assets are uploaded to S3 by the Serverless worker.
