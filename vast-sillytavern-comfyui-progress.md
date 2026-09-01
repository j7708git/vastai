# Vast.ai ComfyUI + SillyTavern 專案進度

## 1. 最新決定

改用 Vast.ai 官方互動式 ComfyUI template 直連 SillyTavern，不再依賴
Serverless + bridge。官方 template 內建 ai-dock ComfyUI 與 Cloudflare
quick tunnel，SillyTavern 可以直接連 ComfyUI API。

```text
SillyTavern
    |
    | HTTPS
    v
https://xxxx.trycloudflare.com（Cloudflare quick tunnel）
    |
    v
Caddy（port 8188）-> ComfyUI（port 18188）
```

模型下載仍由 `provisioning.sh` 自動完成。完整步驟見
`vast-interactive-comfyui-template.md`。

原先的 Serverless 方案記錄保留在下方；若之後想回去用 Serverless，bridge
仍然可用。

### 1.1 互動實例直連進度

- [x] 確認官方 template 的 Cloudflare quick tunnel 設定
- [x] 確認 SillyTavern 原生 ComfyUI 不帶 auth header，需設
  `ENABLE_AUTH=false`（Vast base image 讀這個變數）
- [x] `provisioning.sh` 支援 ai-dock interactive image
- [x] 目前實例已關 `ENABLE_AUTH`，外部 tunnel `/system_stats` 回 200
- [ ] 在 Vast template 設定環境變數
- [ ] 租一台 24 GB VRAM 實例
- [ ] 從 Instance Portal 複製 tunnel URL
- [ ] 在 SillyTavern 選 `sillytavern-krea2-workflow.json` 實測生圖

## 2. 已完成項目

| 項目 | 狀態 | 說明 |
| --- | --- | --- |
| AWS S3 bucket | 已完成 | `vast-comfyui-730116069170-ap-southeast-2-an` |
| S3 加密 | 已完成 | 使用 AWS 預設的 SSE-S3 bucket 加密 |
| S3 限制存取 | 已完成 | Block Public Access 已啟用 |
| S3 versioning | 已完成 | 已啟用 |
| AWS 權限 | 已完成 | 只能對專用 bucket 的物件執行 `GetObject` 和 `PutObject` |
| AWS 存取憑證 | 已完成 | 已存放在本機 Git-ignored 檔案 |
| 模型上傳 | 已完成 | UNet、text encoder、VAE 均已上傳 |
| Krea 2 workflow JSON | 已完成 | `vast-krea2-t2i.json` 已準備 |
| provisioning script | 已完成 | `provisioning.sh` 已在 Vast worker 成功下載模型 |
| Vast 測試 client | 已完成初版 | `vast_krea2_client.py` 已準備 |
| GitHub repository | 已完成 | `https://github.com/j7708git/vastai` |
| Vast Krea 2 實測 | 已完成 | `vast-comfyui-krea2` 已成功產生並回傳 S3 URL |
| Vast endpoint | 已完成 | `vast-comfyui-krea2` 已建立並 Ready |
| Vast provisioning public URL | 已完成 | `https://raw.githubusercontent.com/j7708git/vastai/main/provisioning.sh` |
| SillyTavern bridge | 初版已完成 | `vast_krea2_bridge.py` 已建立 |
| S3 輸出資料夾 | 已完成 | 正式圖片統一放在 `krea2/`，臨時 UUID 目錄會刪除 |
| S3 benchmark 清理 | 已完成 | `test-*` 物件設定 1 天 lifecycle expiration |
| Native ComfyUI adapter | 已完成 | bridge 已模擬 ST 需要的 ComfyUI endpoints |
| Native SillyTavern workflow | 已完成 | `sillytavern-krea2-workflow.json` 已準備 |
| SillyTavern 接線 | 未完成 | 尚未在另一台電腦的 ST 實際送出圖片 |

## 3. AWS / S3 目前設定

### 3.1 非機密設定

```text
AWS selected Region = ap-southeast-2
S3_BUCKET_NAME     = vast-comfyui-730116069170-ap-southeast-2-an
S3_ENDPOINT_URL    = https://s3.ap-southeast-2.amazonaws.com
S3_REGION          = ap-southeast-2
```

### 3.2 存取憑證

目前使用本機的 Vast 專用憑證檔案：

```text
vast-comfyui-s3-credentials.env
```

這個檔案已加入 `.gitignore`，不會提交到 Git。文件內不應、也不會包含
`S3_ACCESS_KEY_ID` 或 `S3_SECRET_ACCESS_KEY` 的內容。

### 3.3 AWS 權限

目前的權限策略只允許：

```text
s3:GetObject
s3:PutObject
```

限制範圍：

```text
arn:aws:s3:::vast-comfyui-730116069170-ap-southeast-2-an/*
```

此外要求使用 HTTPS。此策略不包含 `ListBucket`、`DeleteObject` 或其他管理權限。
權限策略檔案為：

```text
vast-comfyui-s3-policy.json
```

### 3.4 S3 檔案結構

目前 S3 的正式檔案結構：

```text
models/
  diffusion_models/
  text_encoders/
  vae/

krea2/
  <timestamp>_<filename>.png
```

Bridge 預設使用 AWS profile `agent-toolkit`，在 Vast 回傳圖片後：

1. 把物件複製到 `krea2/<timestamp>_<filename>.png`。
2. 刪除 Vast 的 `<request_id>/<filename>.png` 臨時物件。
3. 回傳固定 `krea2/` 資料夾的 presigned URL。

如要保留原始臨時物件，加 `--keep-s3`。

Vast benchmark 產生的 `test-*` 物件會由 S3 lifecycle rule
`ExpireBenchmarkOutputs` 在 1 天後刪除。此規則不影響 `models/` 與 `krea2/`。

## 4. S3 已上傳的模型

| 用途 | S3 Object Key | 大小 |
| --- | --- | --- |
| UNet / 主模型 | `models/diffusion_models/lustifyNSFWCheckpoint_v10Krea2.safetensors` | 約 13.1 GB |
| 另一支 Krea 2 UNet | `models/diffusion_models/moodyKrea2Mix_v70.safetensors` | 約 14.1 GB |
| Flux 2.9B UNet | `models/diffusion_models/Flux2_9b/snofsSexNudesAndOtherFunStuff_v14Distilled.safetensors` | 約 9.1 GB |
| Text encoder | `models/text_encoders/qwen3vl_4b_fp8_scaled.safetensors` | 約 5.2 GB |
| VAE | `models/vae/qwen_image_vae.safetensors` | 約 254 MB |

目前 `provisioning.sh` 預設下載：

```text
lustifyNSFWCheckpoint_v10Krea2.safetensors
qwen3vl_4b_fp8_scaled.safetensors
qwen_image_vae.safetensors
```

如果之後想改用另一支 Krea 2 主模型，可以透過 Vast template 的 environment
variables 切換，不需要改 workflow，只需要改下載路徑和檔案名稱。

## 5. Provisioning Script

### 5.1 檔案

```text
provisioning.sh
```

### 5.2 用途

在 Vast worker 第一次啟動時：

1. 確認 `boto3` 可用，必要時安裝。
2. 從 S3 下載 UNet 到：

   ```text
   /workspace/ComfyUI/models/diffusion_models/
   ```

3. 從 S3 下載 text encoder 到：

   ```text
   /workspace/ComfyUI/models/text_encoders/
   ```

4. 從 S3 下載 VAE 到：

   ```text
   /workspace/ComfyUI/models/vae/
   ```

5. Clone 這個 workflow 使用的 custom node：

   ```text
   https://github.com/liuqianhonga/ComfyUI-Image-Compressor.git
   ```

6. 安裝該 custom node 的 `requirements.txt`。

### 5.3 需要的環境變數

```text
S3_BUCKET_NAME
S3_ACCESS_KEY_ID
S3_SECRET_ACCESS_KEY
S3_ENDPOINT_URL
S3_REGION
```

這些值可以放在 Vast Account Settings 的 Environment Variables 中，Vast worker
啟動時會取得。公開的 `provisioning.sh` 內不含任何 AWS 憑證。

可選 override：

```text
MODEL_S3_KEY
MODEL_FILENAME
CLIP_S3_KEY
CLIP_FILENAME
VAE_S3_KEY
VAE_FILENAME
IMAGE_COMPRESSOR_REPO
```

### 5.4 目前進度

- [x] `bash -n provisioning.sh` 語法檢查通過。
- [x] 內嵌的 Python 下載邏輯語法檢查通過。
- [x] hosting 到 public GitHub repository。
- [x] 取得 raw URL：https://raw.githubusercontent.com/j7708git/vastai/main/provisioning.sh
- [ ] 在 Vast template 設定 `PROVISIONING_SCRIPT`。
- [ ] 在 Vast worker 實際執行一次。

## 6. Krea 2 文生圖工作流

### 6.1 檔案

```text
vast-krea2-t2i.json
```

這是 ComfyUI API-format workflow，可以直接放入 Vast 的 `workflow_json`。

目前的預設設定：

```text
width         = 768
height        = 768
batch_size    = 1
steps         = 8
cfg           = 1
sampler_name  = euler
scheduler     = simple
denoise       = 1
uNet          = lustifyNSFWCheckpoint_v10Krea2.safetensors
clip          = qwen3vl_4b_fp8_scaled.safetensors
vae           = qwen_image_vae.safetensors
```

### 6.2 佔位符

```text
%prompt%          文字 prompt，由 client / bridge 替換
__RANDOM_INT__    seed，由 Vast 或 client / bridge 替換
```

目前的 client 已支援：

```text
--prompt
--width
--height
--steps
--seed
```

### 6.3 注意事項

工作流目前使用原生的 `SaveImage` 輸出節點，避免 custom node 尚未載入時阻擋
Krea 2 主流程測試。provisioning script 仍會嘗試安裝 `ImageCompressor`，但
目前 workflow 不依賴它。

正式測試時需要確認：

1. Krea 2 模型、text encoder 和 VAE 都能成功載入。
2. workflow 通過 Vast 的 validation。
3. 回傳的 `output` 包含可下載的 S3 presigned URL。
4. 可以在 S3 中看到 `vast/krea2/` 下的輸出圖片。

## 7. Vast 測試 Client

### 7.1 檔案

```text
vast_krea2_client.py
```

### 7.2 使用方式

先安裝 Vast SDK：

```powershell
pip install vastai
```

設定 Vast API key：

```powershell
$env:VAST_API_KEY = "your-vast-api-key"
```

執行：

```powershell
python vast_krea2_client.py `
  --endpoint my-comfyui-endpoint `
  --prompt "a cinematic portrait, dramatic lighting, detailed"
```

可選參數：

```powershell
--width 1024
--height 1024
--steps 12
--seed 12345
```

client 會：

1. 讀取 `vast-krea2-t2i.json`。
2. 把 `%prompt%` 替換成使用者輸入的 prompt。
3. 如果提供 seed，把 `__RANDOM_INT__` 替換成指定 seed。
4. 透過 Vast SDK 取得 endpoint。
5. 呼叫 `/generate/sync`。
6. 印出 JSON response。

## 8. SillyTavern 接線方案

### 8.1 為什麼需要 bridge

SillyTavern 的 ComfyUI source 通常適用於一般的 ComfyUI HTTP API，而 Vast
Serverless 不是 standard ComfyUI server。Vast 的路由、worker 選擇、簽名和
`/generate/sync` payload 由 `vastai` SDK 處理，因此 SillyTavern 不能直接指向
Vast worker 的標準 ComfyUI endpoint。

### 8.2 建議的 bridge

在 SillyTavern 所在電腦上跑 `vast_krea2_bridge.py`：

```text
POST /v1/images/generations
```

Bridge 的責任：

1. 接收 SillyTavern 送來的 prompt。
2. 載入 Krea 2 workflow。
3. 替換 prompt、尺寸、steps、seed。
4. 使用 `vastai` SDK 呼叫 Vast `/generate/sync`。
5. 解析 response 中的 S3 presigned URL。
6. 回傳 OpenAI-compatible responses：

```json
{
  "data": [
    {
      "url": "https://.../generated_image.png"
    }
  ]
}
```

只有 bridge 需要安裝 `vastai`。SillyTavern 本身不需要安裝，也不需要在
SillyTavern 中直接使用 Vast SDK。

啟動：

```powershell
pip install -r requirements.txt
python vast_krea2_bridge.py --endpoint vast-comfyui-krea2
```

QIG 設定（從另一台同網段電腦連線）：

```text
Provider        = Reverse Proxy (OpenAI-compatible)
Base URL        = http://<這台主機的LAN IP>:8765/v1
Endpoint mode   = images_generations
Payload mode    = extended
```

### 8.3 原生 SillyTavern Image Generation

SillyTavern 內建 `Image Generation -> ComfyUI` 的設定：

```text
Source        = ComfyUI
Server Type   = Standard Server
ComfyUI URL   = http://192.168.0.39:8765
```

bridge 已加入原生 ComfyUI 需要的 endpoints：

```text
/system_stats
/object_info
/prompt
/history
/view
```

內建 ST 工作流請使用：

```text
sillytavern-krea2-workflow.json
```

它只有原生 `SaveImage`，不依賴 `ImageCompressor`。

### 8.4 安全與執行建議

- bridge 預設綁定 `0.0.0.0`，只開放 Windows firewall 的 `8765` port。
- firewall 規則使用 `LocalSubnet`，讓同一個 Wi-Fi 子網路的電腦可以連線。
- QIG 的 Base URL 要使用啟動 bridge 的主機 LAN IP，不是另一台電腦自己的 IP。
- 可在 `vast-api-key.env` 加入 `BRIDGE_TOKEN=...`，QIG 的 API Key 填同一個值。

如果 Windows 沒有自動放行 `8765`，請在管理員 PowerShell 執行：

```powershell
New-NetFirewallRule -DisplayName "Vast ComfyUI Bridge 8765" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -RemoteAddress LocalSubnet
```
- 不要公開 Vast API key。
- 不要公開 AWS S3 的 secret key。
- 如果必須遠端存取，只建議透過本機反向代理並加上鑑權。
- 如果 SillyTavern 與 Vast 不在同一台機器，bridge 可以放在另一台小主機上，
  但該主機仍需要 `vastai` 與 Vast API key。

## 9. 下一步

### 9.1 部署前置

- [x] 把 `provisioning.sh` 上傳到 public GitHub repository。
- [x] 使用 raw URL：

  ```text
  https://raw.githubusercontent.com/j7708git/vastai/main/provisioning.sh
  ```

- [x] 在 Vast Account Settings 確認 `S3_*` 環境變數。
- [x] 在 Vast template 設定 `PROVISIONING_SCRIPT`。
- [x] 建立 Serverless endpoint / workergroup。
- [x] 確認 GPU VRAM 和 endpoint 名稱。
- [x] 等待 worker 完成 provisioning、benchmark 和 ready 狀態。

### 9.2 驗證 Krea 2 workflow

- [x] 使用 `vast_krea2_client.py` 送一筆 request。
- [x] 確認 response 的 `status` 是 `completed`。
- [x] 確認 response 的 `output` 包含 S3 URL。
- [x] 打開圖片確認模型、VAE、prompt 都正確。
- [ ] 確認冷啟動、第一次下載模型和 benchmark 時間是否可接受。

### 9.3 完成 SillyTavern 接線

- [x] 確認 SillyTavern 使用的 image generation extension 或 QIG 的 API 格式。
- [x] 確認原生 Image Generation 使用 ComfyUI `/prompt`、`/history`、`/view`。
- [x] 實作本地 bridge API。
- [x] 在 bridge 中設定 Vast endpoint name。
- [x] 用 curl / 本機 HTTP client 測試 bridge 的 ComfyUI-compatible 流程。
- [ ] 在另一台 SillyTavern 設定 Source = ComfyUI、URL = bridge LAN IP。
- [ ] 從 SillyTavern 送出一張圖，確認圖片 URL 可下載。

## 10. 已知尚未確認事項

1. Vast Serverless endpoint 名稱為 `vast-comfyui-krea2`。
2. Vast API key 已存放在本機 Git-ignored 的 `vast-api-key.env`。
3. `provisioning.sh` 已從 GitHub raw URL 在 Vast worker 實際執行。
4. Krea 2 workflow 已在 Vast worker 上成功產生圖片。
5. `ImageCompressor` custom node 尚未在 Vast worker 成功載入；目前 workflow
   已改用原生 `SaveImage`，壓縮節點可之後再修。
6. SillyTavern 原生 ComfyUI adapter 已測試，但尚未從另一台電腦的 ST UI 送出圖片。
7. 是否使用 `lustifyNSFWCheckpoint_v10Krea2.safetensors` 或
   `moodyKrea2Mix_v70.safetensors` 尚未做最終選擇。
8. Bridge 已在本地模擬原生 ComfyUI 流程測試，尚未在另一台電腦的 ST UI 實測。

## 11. 目前檔案清單

| 檔案 | 用途 | 狀態 |
| --- | --- | --- |
| `vast-sillytavern-comfyui-progress.md` | 本專案進度文件 | 新增 |
| `provisioning.sh` | 下載模型與 custom node | 初版完成 |
| `vast-krea2-t2i.json` | Krea 2 API-format workflow | 初版完成 |
| `vast_krea2_client.py` | 本機 Vast 測試 client | 初版完成 |
| `vast_krea2_bridge.py` | SillyTavern OpenAI-compatible bridge | 初版完成 |
| `s3_reorganize.py` | S3 圖片歸檔與臨時物件清理工具 | 初版完成 |
| `sillytavern-krea2-workflow.json` | SillyTavern 原生 Image Generation workflow | 初版完成 |
| `requirements.txt` | bridge 與 client 依賴 | 初版完成 |
| `vast-provisioning.md` | Provisioning 設定摘要 | 完成 |
| `vast-s3-setup.md` | S3 非機密設定摘要 | 完成 |
| `vast-comfyui-s3-policy.json` | S3 物件權限策略 | 完成 |
| `vast-comfyui-s3-credentials.env` | AWS 憑證，本機限定 | 已完成，不提交 |
| `.gitignore` | 忽略憑證檔案 | 完成 |
