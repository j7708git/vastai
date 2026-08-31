# Vast.ai ComfyUI provisioning

## S3 objects expected by `provisioning.sh`

```text
models/diffusion_models/lustifyNSFWCheckpoint_v10Krea2.safetensors
models/text_encoders/qwen3vl_4b_fp8_scaled.safetensors
models/vae/qwen_image_vae.safetensors
```

These three objects are confirmed present in the bucket. The provisioning
script will fail early if any one is missing.

## Host the script

Vast fetches `PROVISIONING_SCRIPT` over HTTP. Put this file in a public Gist
or a public GitHub repository and use the raw URL, for example:

```text
https://raw.githubusercontent.com/<user>/<repo>/main/provisioning.sh
```

## Vast template environment variables

Set these in the template:

```text
PROVISIONING_SCRIPT=https://raw.githubusercontent.com/<user>/<repo>/main/provisioning.sh
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
