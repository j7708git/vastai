#!/usr/bin/env python3
"""
vast.ai GPU 租用篩選器（依 Jason 的自訂條件）
用法:
  python3 find_gpu.py                 # 用預設條件搜尋+排序
  python3 find_gpu.py --max-cost 2    # 放寬流量費至 $2/TB
  python3 find_gpu.py --gpu RTX_4080S # 指定 GPU 型號
  python3 find_gpu.py --gpu RTX_4080S,RTX_5070_Ti --max-cost 1
"""
import json, subprocess, sys, argparse

VASTAI = "/home/jason/.venvs/vastai/bin/vastai"

def search(extra_query=""):
    q = f"rentable=true verified=true {extra_query}".strip()
    out = subprocess.run([VASTAI, "search", "offers", q, "--raw", "-o", "dph_total",
                          "--limit", "2000"],
                         capture_output=True, text=True, timeout=180)
    if out.returncode != 0:
        print("vastai search 失敗:", out.stderr, file=sys.stderr)
        sys.exit(1)
    return json.loads(out.stdout)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-cost", type=float, default=1.0,
                    help="流量費上限 ($/TB)，預設 1.0 = $1/TB 以下")
    ap.add_argument("--gpu", default=None,
                    help="指定 GPU 型號，逗號分隔，空格用底線 (ex: RTX_5070_Ti,RTX_4080S)")
    ap.add_argument("--min-down", type=int, default=800, help="最低下載速度 Mb/s，預設 800")
    ap.add_argument("--limit", type=int, default=15, help="顯示前 N 台")
    args = ap.parse_args()

    gpu_q = ""
    if args.gpu:
        gpus = ",".join(gpu.replace("_", " ") for gpu in args.gpu.split(","))
        gpu_q = f"gpu_name in [{gpus}] "

    offers = search(gpu_q)
    if not offers:
        print("查無可租機器，試著放寬條件或稍後再試")
        sys.exit(0)

    cost_per_gb = args.max_cost / 1000  # $/TB -> $/GB
    hits = []
    for o in offers:
        if o.get("gpu_ram", 0) < 16000:                     # 1. VRAM >= 16G (MiB; 16GB卡回報~16300)
            continue
        flops = o.get("total_flops", 0) or 0
        dlperf = o.get("dlperf", 0) or 0
        if flops < 25 and dlperf < 25:                      # 2. 算力 > 25
            continue
        if o.get("inet_down", 0) < args.min_down:           # 3. 下載 >= 800Mb/s
            continue
        if (o.get("inet_down_cost", 0) or 0) > cost_per_gb: # 4. 流量費
            continue
        if (o.get("inet_up_cost", 0) or 0) > cost_per_gb:
            continue
        if o.get("pcie_bw", 0) < 16:                        # 5. PCIe 沒閹割
            continue
        hits.append(o)

    hits.sort(key=lambda x: x.get("dph_total", 0))
    print(f"符合條件 {len(hits)} 台（流量費<=${args.max_cost}/TB、下載>={args.min_down}Mb/s、PCIe>=16GB/s）\n")
    print(f"{'GPU':<14}{'$/hr':<8}{'TFLOPS':<7}{'PCIe':<7}{'下載Mb':<8}{'流量$/TB':<10}{'VRAM':<7}id")
    print("-" * 72)
    for o in hits[:args.limit]:
        down_cost = (o.get("inet_down_cost", 0) or 0) * 1000
        vram_gb = (o.get("gpu_ram", 0) or 0) / 1024
        print(f"{o.get('gpu_name','?'):<14}${o.get('dph_total',0):<7.3f}"
              f"{o.get('total_flops',0):<7.0f}{o.get('pcie_bw',0):<7.1f}"
              f"{o.get('inet_down',0):<8.0f}${down_cost:<9.2f}"
              f"{vram_gb:<7.1f}{o['id']}")

if __name__ == "__main__":
    main()
