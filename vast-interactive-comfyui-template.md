# Vast.ai 官方 ComfyUI Template 直連 SillyTavern

這個方案不再依賴 `vast_krea2_bridge.py`，改用 Vast.ai 官方互動式
ComfyUI template 的 Cloudflare tunnel 直接把 ComfyUI API 給
SillyTavern 用。模型仍然由 `provisioning.sh` 自動從 S3 下載。

## 為什麼可以直連

Vast.ai 官方 ComfyUI template 以 ai-dock ComfyUI 為基底，預設啟動：

- Caddy 反向代理：內層 ComfyUI 跑在 `18188`，對外服務 port 是 `8188`
- Cloudflare quick tunnel：`CF_QUICK_TUNNELS=true` 時會產生
  `https://xxxx.trycloudflare.com` 的公開 HTTPS URL

只要把 `COMFYUI_ARGS` 加上 `--enable-cors-header`，並讓 SillyTavern
連到 tunnel URL，SillyTavern 的原生 ComfyUI Image Generation 就可以直接用
`/system_stats`、`/object_info`、`/prompt`、`/history`、`/view`。

## 1. Template 設定

在 Vast.ai 的 Templates 頁面搜尋 `ComfyUI`，建立一份私有的 template copy，
然後加入以下環境變數：

```text
COMFYUI_ARGS=--disable-auto-launch --port 18188 --enable-cors-header
WEB_ENABLE_AUTH=false
WEB_ENABLE_HTTPS=false
CF_QUICK_TUNNELS=true
PROVISIONING_SCRIPT=https://raw.githubusercontent.com/j7708git/vastai/main/provisioning.sh
OPEN_BUTTON_PORT=8188
```

`OPEN_BUTTON_PORT` 如果原本就已經存在（例如 `OPEN_BUTTON_PORT="1111"`），
只要把值改成 `8188` 就好，不要新增第二行。

確認 template 已開放對外 port `8188`；如果沒有，在 docker options 加入：

```text
-p 8188:8188
```

`S3_BUCKET_NAME`、`S3_ACCESS_KEY_ID`、`S3_SECRET_ACCESS_KEY`、
`S3_ENDPOINT_URL`、`S3_REGION` 沿用 Vast Account Settings 的環境變數，
不需要在 template 重貼 secret。

租用實例時，建議至少：

- VRAM：24 GB 以上（Krea2 UNet 約 13 GB，text encoder 約 5 GB）
- Disk：100 GB 以上

## 2. 為什麼要關 WEB_ENABLE_AUTH

SillyTavern 的標準 ComfyUI source 在 `/system_stats`、`/object_info`、
`/prompt`、`/history`、`/view` 這些 request 上不會送出 Bearer 或 Basic auth
header。ai-dock 的 Caddy 雖然支援 `?token=` 與 `Authorization: Bearer`，
但 SillyTavern 不會幫我們帶，所以直連時要把 `WEB_ENABLE_AUTH` 設為 `false`。

代價是 tunnel URL 等同沒有密碼的公開 ComfyUI。請只把這個 URL 貼給自己的
SillyTavern，用完立刻刪除實例，不要公開 URL。

## 3. 取得 ComfyUI URL

實例變成 ready 後：

1. 點實例的 `OPEN`。
2. 在 Instance Portal 或 ComfyUI 的 connection links 找
   `https://xxxx.trycloudflare.com`。
3. 也可以用 SSH 看 quick tunnel log：

   ```bash
   cat /var/log/supervisor/quicktunnel-*.log
   ```

URL 每次開新實例都會變；如果 SillyTavern 連不上，先檢查是不是換了 URL。

## 4. SillyTavern 設定

打開 SillyTavern 的 `Extensions -> Image Generation`：

```text
Source        = ComfyUI
Server Type   = Standard Server
ComfyUI URL   = https://xxxx.trycloudflare.com
Workflow      = sillytavern-krea2-workflow.json
```

不要加 `/`、`/v1` 或 `?token=...`，只填 tunnel 根 URL。

把 `sillytavern-krea2-workflow.json` 放進 SillyTavern 的
`data/default-user/workflows/`（實際路徑依使用者和設定可能不同），
然後在 Workflow 下拉選單選它。

按 `Connect` 成功後，Model 下拉選單會出現 S3 下載進去的 UNet：

```text
lustifyNSFWCheckpoint_v10Krea2.safetensors
moodyKrea2Mix_v70.safetensors
```

## 5. Provisioning Script

`provisioning.sh` 已改成自動偵測：

- `SERVERLESS=true`：維持原本 Vast Serverless 的下載路徑
- ai-dock interactive image：下載到
  `${WORKSPACE}/storage/stable_diffusion/models/{unet,clip,vae}`
  或 `/opt/ComfyUI/models/...`

它仍會下載預設的 Krea2 UNet、Qwen text encoder、VAE，並嘗試安裝
`ComfyUI-Image-Compressor`。目前 Krea2 workflow 只使用原生 `SaveImage`，
所以 custom node 失敗不會擋住生圖。

## 6. 結束後清理

生完圖之後直接在 Vast.ai 刪除實例，避免按小時計費繼續跑。模型不需要手動
上傳或設定，下一次租新實例時 template 會再自動下載。

## 7. 可選：固定 tunnel URL

Quick tunnel 每次重開都會換 URL。如果想要固定網址，可以在 Cloudflare
Zero Trust 建立 named tunnel，並把 token 填入：

```text
CF_TUNNEL_TOKEN=your-cloudflare-zero-trust-token
```

注意同一個 token 同時只能用在一台實例，而且 named tunnel 不等於可以開
`WEB_ENABLE_AUTH=true`；SillyTavern 直連仍然建議關 auth，或用 bridge 補 auth。

## 8. 備援：bridge proxy 模式

如果之後想回到固定 LAN URL 或需要 auth，`vast_krea2_bridge.py` 已支援
proxy 模式，直接指向真實 ComfyUI：

```powershell
python vast_krea2_bridge.py --comfy-url https://xxxx.trycloudflare.com
```

SillyTavern 再連 `http://192.168.0.39:8765`。這個模式只做 HTTP proxy，
不需要 Vast API key，也不做 S3 整理。
