#!/usr/bin/env python3
"""
vast.ai 一鍵租機腳本（Jason 專用）
流程: 掃市場 → 依條件篩選 → 用 ComfyUI_codex 模板租下 → 等開機 → 等模型下載完 → 抓 tunnel URL → 回報

用法:
  python3 rent_gpu.py                     # 自動租最便宜且符合條件的機器
  python3 rent_gpu.py --gpu RTX_4080S     # 指定 GPU 型號
  python3 rent_gpu.py --gpu RTX_4090,RTX_4080  # 指定多型號
  python3 rent_gpu.py --max-cost 2        # 放寬流量費至 $2/TB
  python3 rent_gpu.py --dry-run           # 只掃描不租
  python3 rent_gpu.py --destroy 49693360  # 刪除實例(停止計費)
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

VASTAI = "/home/jason/.venvs/vastai/bin/vastai"
SSH_KEY = "/home/jason/.ssh/id_ed25519"
TEMPLATE_HASH = "bbd9795a48e23b767f1f6adcc67fa6a3"  # ComfyUI_codex (最新)
DEFAULT_DISK = 120  # GB

LOG = print


def run_vastai(args_list, timeout=120):
    """執行 vastai CLI，回傳 (exit_code, stdout, stderr)"""
    out = subprocess.run([VASTAI] + args_list,
                         capture_output=True, text=True, timeout=timeout)
    return out.returncode, out.stdout, out.stderr


def search_offers(extra_query=""):
    """抓全量可租+verified 的 offers"""
    q = f"rentable=true verified=true {extra_query}".strip()
    rc, out, err = run_vastai(["search", "offers", q, "--raw", "-o", "dph_total",
                               "--limit", "2000"], timeout=180)
    if rc != 0:
        LOG(f"⚠️ search offers 失敗: {err}")
        return []
    return json.loads(out or "[]")


def ptb(x):
    """$/GB -> $/TB"""
    return (x or 0) * 1000


def filter_offers(offers, max_cost, min_down, gpu_names=None, server_gpu=False):
    """依 Jason 的 5 條條件篩選"""
    cost_per_gb = max_cost / 1000
    hits = []
    for o in offers:
        if gpu_names and o.get("gpu_name") not in gpu_names:
            continue
        if not server_gpu and not (o.get("gpu_name") or "").startswith("RTX "):
            continue  # 預設只要消費級 RTX 卡
        if o.get("gpu_ram", 0) < 16000:          # 1. VRAM >= 16G (MiB)
            continue
        flops = o.get("total_flops", 0) or 0
        dlperf = o.get("dlperf", 0) or 0
        if flops < 25 and dlperf < 25:           # 2. 算力 > 25
            continue
        if o.get("inet_down", 0) < min_down:     # 3. 下載 >= 800Mb/s
            continue
        if ptb(o.get("inet_down_cost")) > max_cost:   # 4. 流量費
            continue
        if ptb(o.get("inet_up_cost")) > max_cost:
            continue
        if o.get("pcie_bw", 0) < 16:             # 5. PCIe 沒閹割
            continue
        hits.append(o)
    hits.sort(key=lambda x: x.get("dph_total", 0))
    # 消費級 GPU 優先（RTX 40/50 系列），工作站卡( RTX PRO/PRO )排中間，伺服器卡排最後
    def gpu_rank(o):
        n = (o.get("gpu_name") or "")
        if n.startswith("RTX ") and "PRO" not in n:
            return 0
        if "PRO" in n:
            return 1
        return 2
    hits.sort(key=lambda x: (gpu_rank(x), x.get("dph_total", 0)))
    return hits


def create_instance(offer_id, disk):
    """用 ComfyUI_codex 模板建立實例"""
    LOG(f"🚀 建立實例: offer={offer_id} disk={disk}GB template={TEMPLATE_HASH[:8]}...")
    rc, out, err = run_vastai(
        ["create", "instance", str(offer_id), "--template_hash", TEMPLATE_HASH,
         "--disk", str(disk)], timeout=120)
    if rc != 0:
        LOG(f"❌ 建立失敗: {err}")
        return None
    LOG(f"  原始回應: {out.strip()[:200]}")
    m = re.search(r"new_contract['\"]?\s*[:=]\s*['\"]?(\d+)", out)
    if m:
        return int(m.group(1))
    # 嘗試 JSON 解析
    try:
        return json.loads(out).get("new_contract")
    except Exception:
        return None


def wait_running(instance_id, timeout=600):
    """等待實例 running"""
    LOG("⏳ 等待實例啟動...")
    start = time.time()
    while time.time() - start < timeout:
        rc, out, err = run_vastai(["show", "instance", str(instance_id), "--raw"], timeout=60)
        if rc == 0:
            try:
                d = json.loads(out)
                if isinstance(d, list):
                    d = d[0] if d else {}
                status = d.get("actual_status") or d.get("cur_state") or ""
                gpu = d.get("gpu_name", "?")
                dph = d.get("dph_total", 0)
                if status == "running":
                    LOG(f"✅ running! GPU={gpu} ${dph:.3f}/hr")
                    return d
                if status in ("exited", "offline", "unknown", "failed"):
                    LOG(f"❌ 狀態異常: {status}")
                    return None
                LOG(f"  [{int(time.time()-start)}s] status={status}")
            except Exception:
                pass
        time.sleep(15)
    LOG("❌ 等待超時")
    return None


def wait_models_ready(instance_id, info, timeout=900):
    """SSH 進去等模型下載完成 + ComfyUI 就緒，回傳 (ssh_cmd, tunnel_url)"""
    ssh_host = info.get("ssh_host") or info.get("public_ipaddr")
    ssh_port = info.get("ssh_port")
    if not ssh_host or not ssh_port:
        LOG("⚠️ 無法取得 SSH 資訊")
        return None, None

    ssh_cmd = (f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=20 "
               f"-i {SSH_KEY} -p {ssh_port} root@{ssh_host}")

    LOG(f"🔑 附加上本機 SSH key")
    rc, out, err = run_vastai(["attach", "ssh", str(instance_id), f"{SSH_KEY}.pub"], timeout=60)
    time.sleep(5)

    LOG("⏳ 等模型從 S3 下載 + ComfyUI 啟動 (可達 10 分鐘)...")
    start = time.time()
    model_ok = False
    tunnel_url = None

    while time.time() - start < timeout:
        # 1. 檢查模型是否下載完
        check = (f"{ssh_cmd} 'find /workspace/ComfyUI/models -name \"*.part*\" 2>/dev/null | wc -l; "
                 f"ls /workspace/ComfyUI/models/diffusion_models/*.safetensors 2>/dev/null | wc -l'")
        try:
            r = subprocess.run(check, shell=True, capture_output=True, text=True, timeout=60)
            lines = [l.strip() for l in r.stdout.splitlines() if l.strip().isdigit()]
            if len(lines) >= 2:
                parts, models = int(lines[-2]), int(lines[-1])
                if parts == 0 and models >= 1:
                    model_ok = True
                    LOG(f"✅ 模型下載完成 ({models} 個主模型)")
                    break
                LOG(f"  [{int(time.time()-start)}s] 下載中... (.part={parts}, models={models})")
        except Exception:
            pass
        time.sleep(25)

    # 2. 抓 tunnel URL（comfyui 那條）
    LOG("🔍 抓取 Cloudflare tunnel URL...")
    for attempt in range(10):
        try:
            r = subprocess.run(
                f"{ssh_cmd} 'grep -ohE \"https://[a-zA-Z0-9-]+\\.trycloudflare\\.com\" /var/log/portal/tunnel_manager.log 2>/dev/null | sort -u'",
                shell=True, capture_output=True, text=True, timeout=60)
            candidates = r.stdout.split()
            for url in candidates:
                # 測試哪個是 ComfyUI
                try:
                    r2 = subprocess.run(
                        f"curl -s --max-time 15 {url}/system_stats",
                        shell=True, capture_output=True, text=True, timeout=30)
                    if "comfyui" in r2.stdout.lower() or "ram_total" in r2.stdout:
                        tunnel_url = url
                        break
                except Exception:
                    continue
            if tunnel_url:
                break
        except Exception:
            pass
        time.sleep(10)

    return ssh_cmd, tunnel_url


def show_summary(instance_id, info, ssh_cmd, tunnel_url):
    gpu = info.get("gpu_name", "?")
    dph = info.get("dph_total", 0)
    print("\n" + "=" * 56)
    print("🎉 租機完成！")
    print("=" * 56)
    print(f"  實例 ID    : {instance_id}")
    print(f"  GPU        : {gpu}")
    print(f"  費率       : ${dph:.3f}/hr ≈ NT${dph*32:.0f}/hr")
    print(f"  SSH        : {ssh_cmd}")
    if tunnel_url:
        print(f"  ComfyUI URL: {tunnel_url}")
        print(f"    → SillyTavern 填這個 URL（Source=ComfyUI, Standard Server）")
    print(f"  用完刪除   : {VASTAI} destroy instance {instance_id}")
    print("=" * 56)


def main():
    ap = argparse.ArgumentParser(description="vast.ai 一鍵租機")
    ap.add_argument("--gpu", default=None, help="指定 GPU 型號, 逗號分隔 (ex: RTX_4080S,RTX_4090)")
    ap.add_argument("--max-cost", type=float, default=1.0, help="流量費上限 $/TB (預設 1.0)")
    ap.add_argument("--min-down", type=int, default=800, help="最低下載 Mb/s (預設 800)")
    ap.add_argument("--disk", type=int, default=DEFAULT_DISK, help="磁碟 GB (預設 120)")
    ap.add_argument("--server-gpu", action="store_true", help="允許伺服器卡(A10/A100/PRO等)，預設只選消費級 RTX")
    ap.add_argument("--dry-run", action="store_true", help="只掃描不租")
    ap.add_argument("--destroy", metavar="INSTANCE_ID", help="刪除指定實例(停止計費)")
    args = ap.parse_args()

    if args.destroy:
        rc, out, err = run_vastai(["destroy", "instance", str(args.destroy), "-y"], timeout=120)
        if rc == 0:
            print(f"✅ 實例 {args.destroy} 已刪除，停止計費")
            print(out.strip()[:300] if out.strip() else "")
        else:
            print(f"❌ 刪除失敗: {err}")
        return

    gpu_names = None
    gpu_q = ""
    if args.gpu:
        gpu_names = [g.replace("_", " ") for g in args.gpu.split(",")]
        gpu_q = "gpu_name in [" + ",".join(gpu_names) + "] "

    LOG(f"🔍 掃描市場 (GPU={gpu_names or '全部'}, 流量費<=${args.max_cost}/TB)...")
    offers = search_offers(gpu_q)
    if not offers:
        LOG("❌ 查無可租機器")
        return

    hits = filter_offers(offers, args.max_cost, args.min_down, gpu_names, args.server_gpu)
    if not hits:
        LOG("❌ 目前沒有符合全部條件的消費級機器！")
        LOG("   可試: --gpu 指定型號 / --max-cost 2 放寬流量費 / --server-gpu 接受伺服器卡")
        # 顯示最接近的
        near = sorted(offers, key=lambda x: x.get("dph_total", 0))[:5]
        LOG("\n   最便宜的未過濾機器:")
        for o in near:
            LOG(f"     {o.get('gpu_name','?'):<12} ${o.get('dph_total',0):.3f}/hr "
                f"pcie={o.get('pcie_bw',0):.1f} down={o.get('inet_down',0):.0f} "
                f"流量${ptb(o.get('inet_down_cost')):.2f}/TB id={o['id']}")
        return

    LOG(f"\n📋 符合條件的候選 ({len(hits)} 台):")
    for i, o in enumerate(hits[:8]):
        LOG(f"  [{i+1}] {o.get('gpu_name','?'):<12} ${o.get('dph_total',0):.3f}/hr "
            f"TFLOPS={o.get('total_flops',0):.0f} pcie={o.get('pcie_bw',0):.1f} "
            f"down={o.get('inet_down',0):.0f}Mb/s 流量${ptb(o.get('inet_down_cost')):.2f}/TB "
            f"VRAM={o.get('gpu_ram',0)/1024:.0f}G id={o['id']}")

    if args.dry_run:
        LOG("\n(dry-run 模式，不建立實例)")
        return

    # 依序嘗試前 5 台（市場流動快，失敗就試下一台）
    created = None
    for o in hits[:5]:
        created = create_instance(o["id"], args.disk)
        if created:
            LOG(f"✅ 實例建立成功! ID={created}")
            break
        LOG("  該機已被租走，試下一台...")

    if not created:
        LOG("❌ 全部候選都被搶走了，稍後再試")
        return

    info = wait_running(created)
    if not info:
        LOG("❌ 實例未能 running")
        return

    ssh_cmd, tunnel_url = wait_models_ready(created, info)
    show_summary(created, info, ssh_cmd, tunnel_url)


if __name__ == "__main__":
    main()
