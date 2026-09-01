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

目前 workflow 使用原生的 `SaveImage` 輸出，先確認 Krea 2 主流程可正常生成；
`ImageCompressor` custom node 會由 provisioning script 嘗試安裝，但不阻擋測試。

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

## SillyTavern Bridge

本機提供一個 OpenAI-compatible bridge，讓 SillyTavern 的 QIG
（`sillytavern-image-gen`）可以透過 `vastai` SDK 呼叫 Vast Serverless：

```powershell
pip install -r requirements.txt
python vast_krea2_bridge.py --endpoint vast-comfyui-krea2
```

Bridge 預設監聽：

```text
http://<這台主機的LAN IP>:8765/v1
```

在 QIG 的 `Reverse Proxy (OpenAI-compatible)` 設定中：

```text
Base URL        = http://<這台主機的LAN IP>:8765/v1
Endpoint mode   = images_generations
Payload mode    = extended
```

例如目前這台主機的 LAN IP 是 `192.168.0.39`，SillyTavern 那台電腦就要填：

```text
http://192.168.0.39:8765/v1
```

如果 IP 會變，請在啟動 bridge 的主機上執行 `ipconfig`，查 `IPv4 Address` 後更新。

如果 Windows 沒有自動放行，請在「管理員 PowerShell」執行：

```powershell
New-NetFirewallRule -DisplayName "Vast ComfyUI Bridge 8765" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -RemoteAddress LocalSubnet
```

這條規則只允許同一個 Wi-Fi 子網路連入，不會開放公網。

SillyTavern 的內建 ComfyUI source 不支援 Vast Serverless 的 `/generate/sync`
與 worker route/auth，因此不要用內建 ComfyUI source；改用上面這個 bridge。

目前 bridge 支援 `prompt`、`width`、`height`、`steps`、`seed`、CFG、
sampler、scheduler 和最多 4 張批次。負面 prompt 尚未接到 workflow。

Bridge 預設會使用本機 AWS profile `agent-toolkit`，把 Vast 回傳的圖片複製到：

```text
krea2/<timestamp>_<filename>.png
```

然後刪除 Vast 原本的 `<request_id>/` 臨時物件。如果暫時想保留原始目錄，加：

```powershell
--keep-s3
```

需要手動整理現有 S3 物件時：

```powershell
python s3_reorganize.py --profile agent-toolkit
python s3_reorganize.py --profile agent-toolkit --apply
```

乾跑只會列出要搬移的物件；`--apply` 會把非模型物件搬進 `krea2/`，並刪除原始
臨時物件。`test-*` benchmark 物件另外受 S3 lifecycle rule 保護，會在 1 天後刪除。

如果要限制同網段的其他設備無法呼叫 bridge，可以在 `vast-api-key.env` 加入：

```text
BRIDGE_TOKEN=你的本機bridge密碼
```

然後在 QIG 的 API Key 欄位填入同一個 token。沒有設定 token 時，firewall
仍應限制為 `LocalSubnet`。

## 重要安全提醒

`vast-comfyui-s3-credentials.env` 已加入 `.gitignore`，不會上傳。請不要把
AWS secret key 或 Vast API key 放進任何 GitHub 檔案。
