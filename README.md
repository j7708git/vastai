# Vast.ai ComfyUI Krea 2 + SillyTavern

這個目錄是「Vast.ai 上的 ComfyUI 呼叫 Krea 2 文生圖工作流，並讓 SillyTavern
直接用 ComfyUI API 生圖」的專案檔案。

GitHub repository:

```text
https://github.com/j7708git/vastai
```

## 推薦方案：官方互動式 Template 直連

如果你不想再處理 Serverless，請改用 Vast.ai 官方 ComfyUI template。它內建
Cloudflare quick tunnel，SillyTavern 可以直接連 ComfyUI API，不需要本機
bridge，也不需要 Vast API key。

完整設定步驟：

```text
vast-interactive-comfyui-template.md
```

重點只有三件事：

```text
COMFYUI_ARGS=--disable-auto-launch --port 18188 --enable-cors-header
ENABLE_AUTH=false
WEB_ENABLE_AUTH=false
PROVISIONING_SCRIPT=https://raw.githubusercontent.com/j7708git/vastai/main/provisioning.sh
```

SillyTavern 的 ComfyUI URL 填 Instance Portal 裡拿到的
`https://xxxx.trycloudflare.com`，Workflow 選
`sillytavern-krea2-workflow.json`。

原本的 Serverless + 本地 bridge 方案仍保留在下方，作為備援。

## 租機自動化（rent_gpu.py）

`rent_gpu.py` 是「一鍵租機」腳本，把搜尋、篩選、租用、等待開機、模型下載、
抓取 tunnel URL 全部自動化：

```bash
# 用 ComfyUI_codex 模板租最便宜的合格消費級 RTX
python3 rent_gpu.py

# 指定 GPU 型號（逗號分隔）
python3 rent_gpu.py --gpu RTX_4080S,RTX_4090

# 放寬流量費到 $2/TB
python3 rent_gpu.py --max-cost 2

# 接受伺服器卡（A10/A100/PRO 等，預設只選消費級 RTX）
python3 rent_gpu.py --server-gpu

# 只掃描不租（看市場現況）
python3 rent_gpu.py --dry-run

# 刪除實例（停止計費）
python3 rent_gpu.py --destroy INSTANCE_ID
```

### 篩選條件（Jason 的五條標準）

| 條件 | 參數/門檻 |
| --- | --- |
| VRAM ≥ 16G | `gpu_ram >= 16000` (MiB) |
| 算力 TFLOPS > 25 | `total_flops >= 25` 或 `dlperf >= 25` |
| 下載 ≥ 800 Mbps | `inet_down >= 800` |
| 流量費 ≤ $1/TB | `inet_down_cost/up <= 0.001 $/GB`（可用 `--max-cost` 調整） |
| PCIe 沒被閹割 | `pcie_bw >= 16 GB/s` |

`find_gpu.py` 是只做「掃描+篩選+排序」的輕量版，適合快速查看市場：

```bash
python3 find_gpu.py                        # 預設條件
python3 find_gpu.py --max-cost 2           # 放寬流量費
python3 find_gpu.py --gpu RTX_4080S        # 指定型號
```

### 注意：CLI 分頁上限

`vastai search offers` 預設只回傳前 64 筆（舊版 CLI），會漏掉 95% 市場！
兩個腳本都已加 `--limit 2000` 抓全量。若自行使用 CLI 記得加這個參數。

## 目前功能

- S3 已存放 Krea 2 UNet、text encoder 和 VAE。
- `provisioning.sh` 會在 Vast worker 啟動時下載模型，並安裝
  `ComfyUI-Image-Compressor` custom node。
- LoRA 會下載到 `models/krea2/loras/`。
- `vast-krea2-t2i.json` 是 Vast-ready 的 ComfyUI API-format workflow。
- `vast_krea2_client.py` 是本機測試 client，會把 prompt 替換進 workflow，
  再透過 Vast `/generate/sync` 呼叫。
- `vast_krea2_bridge.py` 可作為 Serverless 橋接，或作為真實 ComfyUI 的
  proxy 備援。
- `rent_gpu.py` 一鍵租機（見上方說明）。

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

## 舊方案：SillyTavern Bridge（Serverless）

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

SillyTavern 的內建 ComfyUI source 不能直接連 Vast Serverless，但 bridge 現在
已加入 ComfyUI-compatible endpoints，可以讓內建 Image Generation 使用。

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

## SillyTavern 原生 Image Generation

如果只用 SillyTavern 內建的 **Image Generation**，不需要 QIG。請在內建「圖片生成設定」填：

```text
Source        = ComfyUI
Server Type   = Standard Server
ComfyUI URL   = http://192.168.0.39:8765
```

URL 建議使用 bridge 根位址，也就是**不要加上 `/v1`**。bridge 也支援 `/v1`
路徑，但原生 ComfyUI 的根位址比較直覺。

Workflow 請在 `Image Generation -> ComfyUI Workflow` 中新增或替換成：

```text
sillytavern-krea2-workflow.json
```

這個 workflow 使用 `%prompt%`、`%seed%`、`%width%`、`%height%`、`%steps%`、
`%scale%`、`%sampler%`、`%scheduler%` 和 `%denoise%` placeholders，輸出節點是
原生的 `SaveImage`，沒有 `ImageCompressor` custom node。

設定好 workflow 後，按 `Connect`；bridge 會回傳 `/system_stats`，產生時會把
workflow 送到 Vast，再以 `/history` 和 `/view` 把圖片回給 SillyTavern。

## 重要安全提醒

`vast-comfyui-s3-credentials.env` 已加入 `.gitignore`，不會上傳。請不要把
AWS secret key 或 Vast API key 放進任何 GitHub 檔案。