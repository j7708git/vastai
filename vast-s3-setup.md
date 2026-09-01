# Vast.ai S3 configuration

## Non-secret values

```text
S3_BUCKET_NAME=vast-comfyui-730116069170-ap-southeast-2-an
S3_ENDPOINT_URL=https://s3.ap-southeast-2.amazonaws.com
S3_REGION=ap-southeast-2
```

## Credentials

The Vast-only credentials are stored in the local Git-ignored file:

```text
vast-comfyui-s3-credentials.env
```

The file contains both `S3_ACCESS_KEY_ID` and `S3_SECRET_ACCESS_KEY`.

## AWS resources

```text
IAM user: vast-comfyui-s3
IAM policy: vast-comfyui-s3-object-access
Policy file: vast-comfyui-s3-policy.json
```

The policy allows only HTTPS `s3:GetObject` and `s3:PutObject` on the
dedicated bucket. It does not grant bucket listing, deletion, or permission
management.

## Output layout

Vast's API wrapper uploads each ComfyUI request under its request ID. To keep
user-visible images together, the local bridge copies them into:

```text
krea2/<timestamp>_<filename>.png
```

The bridge deletes the original `<request_id>/<filename>.png` object by default.
Vast benchmark objects starting with `test-` are removed by an S3 lifecycle rule
after one day.

The S3 lifecycle rule is:

```text
ID: ExpireBenchmarkOutputs
Prefix: test-
Expiration: 1 day
```
