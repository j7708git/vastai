#!/usr/bin/env python3
"""對比 on-demand vs bid 模式價格"""
import json, subprocess

VASTAI = "/home/jason/.venvs/vastai/bin/vastai"

def search(q, bid=False):
    args = [VASTAI, "search", "offers", q, "--raw", "-o", "dph_total", "--limit", "2000"]
    if bid:
        args.insert(4, "-t")
        args.insert(5, "bid")
    out = subprocess.run(args, capture_output=True, text=True, timeout=180)
    return json.loads(out.stdout or "[]")

def ptb(x): return (x or 0) * 1000

# on-demand 4090
ond = [o for o in search('rentable=true gpu_name=RTX_4090') if o.get('dph_total',0) > 0]
# bid 4090
bid = [o for o in search('rentable=true gpu_name=RTX_4090', bid=True) if o.get('dph_total',0) > 0]

ond.sort(key=lambda x: x.get('dph_total', 0))
bid.sort(key=lambda x: x.get('dph_total', 0))

print("=== RTX 4090 on-demand (前5) ===")
for o in ond[:5]:
    print(f"  ${o.get('dph_total',0):.3f}/hr id={o['id']}")
print(f"  最低: ${ond[0].get('dph_total',0):.3f}/hr (共{len(ond)}台)")
print()
print("=== RTX 4090 bid/interruptible (前5) ===")
for o in bid[:5]:
    print(f"  ${o.get('dph_total',0):.3f}/hr (min_bid=${o.get('min_bid',0):.3f}) id={o['id']}")
print(f"  最低: ${bid[0].get('dph_total',0):.3f}/hr (共{len(bid)}台)")
if ond and bid:
    ratio = (1 - bid[0].get('dph_total',0)/ond[0].get('dph_total',0)) * 100
    print(f"\n  省錢幅度: {ratio:.0f}%")