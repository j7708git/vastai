#!/usr/bin/env python3
import json

offers = json.load(open('/tmp/vast_now.json'))

def ptb(x): return (x or 0) * 1000

print('=== 今天焦點機型（rentable）===')
for gpu in ['RTX 4080S', 'RTX 4080', 'RTX 5070 Ti', 'RTX 5070', 'RTX 4090', 'RTX 5090']:
    sub = [o for o in offers if o.get('gpu_name') == gpu and o.get('rentable')]
    sub.sort(key=lambda x: x.get('dph_total', 0))
    print(f'\n{gpu}: {len(sub)} 台可租')
    for o in sub[:8]:
        pcie = o.get('pcie_bw', 0)
        down = o.get('inet_down', 0)
        dc = ptb(o.get('inet_down_cost'))
        uc = ptb(o.get('inet_up_cost'))
        vram = o.get('gpu_ram', 0)
        ok = '✓' if (vram >= 16000 and (o.get('total_flops', 0) or 0) >= 25 and down >= 800 and dc <= 1 and uc <= 1 and pcie >= 16) else '✗'
        print(f"  [{ok}] ${o.get('dph_total',0):<7.3f}/hr flops={o.get('total_flops',0):<5.0f} "
              f"pcie={pcie:<5.1f} down={down:<6.0f} 流量${dc:<5.2f}/${uc:<5.2f} vram={vram/1024:<5.1f}G id={o['id']}")
