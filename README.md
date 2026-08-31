# Vast.ai Serverless ComfyUI Krea 2 + SillyTavern

這個目錄是「Vast.ai Serverless ComfyUI 呼叫 Krea 2 文生圖工作流，並透過本地
bridge 接回 SillyTavern」的專案檔案。

GitHub repository:

```text
https://github.com/j7708git/vastai
```

## 目前功能

- S3 已存放 Krea 2 UNet、text encoder 和 VAE。
- `provisioning.sh` 會在 Vast worker 啟動時下載模型，並安裝
  `ComfyUI-Image-Compressor` custom node。
- `vast-krea2-t2i.json` 是 Vast-ready 的 ComfyUI API-format workflow。
- `vast_krea2_client.py` 是本機測試 client，會把 prompt 替換進 workflow，
  再透過 Vast `/generate/sync` 呼叫。

## 快速使用

```powershell
pip install vastai
$env:VAST_API_KEY = "your-vast-api-key"

python vast_krea2_client.py `
  --endpoint my-comfyui-endpoint `
  --prompt "a cinematic portrait, dramatic lighting, detailed"
```

Vast worker 需要讀取 S3 與 provisioning script。非機密設定與下一步請看
[`vast-sillytavern-comfyui-progress.md`](vast-sillytavern-comfyui-progress.md)。

## 重要安全提醒

`vast-comfyui-s3-credentials.env` 已加入 `.gitignore`，不會上傳。請不要把
AWS secret key 或 Vast API key 放進任何 GitHub 檔案。
