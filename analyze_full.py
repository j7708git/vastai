#!/usr/bin/env python3
import json

offers = json.load(open('/tmp/vast_lim2000.json'))
print(f'全量市場: {len(offers)} 台\n')

def ptb(x): return (x or 0) * 1000  # $/GB -> $/TB

hits = []
for o in offers:
    if not o.get('rentable'):
        continue
    if o.get('gpu_ram', 0) < 16000:  # VRAM >= 16G (MiB; 16GB卡回報~16300)
        continue
    flops = o.get('total_flops', 0) or 0
    dlperf = o.get('dlperf', 0) or 0
    if flops < 25 and dlperf < 25:
        continue
    if o.get('inet_down', 0) < 800:
        continue
    if ptb(o.get('inet_down_cost')) > 1 or ptb(o.get('inet_up_cost')) > 1:
        continue
    if o.get('pcie_bw', 0) < 16:
        continue
    hits.append(o)

hits.sort(key=lambda x: x.get('dph_total', 0))
print(f'符合全部條件: {len(hits)} 台\n')
print(f'{"GPU":<13}{"$/hr":<8}{"TFLOPS":<7}{"PCIe":<7}{"下載Mb":<8}{"流量$/TB":<10}{"VRAM":<6}id')
print('-' * 70)
for o in hits[:25]:
    print(f"{o.get('gpu_name','?'):<13}${o.get('dph_total',0):<7.3f}"
          f"{o.get('total_flops',0):<7.0f}{o.get('pcie_bw',0):<7.1f}"
          f"{o.get('inet_down',0):<8.0f}${ptb(o.get('inet_down_cost')):<9.2f}"
          f"{o.get('gpu_ram',0):<6.0f}{o['id']}")
