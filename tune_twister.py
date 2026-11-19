#!/usr/bin/env python3
"""k_wt'yi su turbini enerji payi ~%70 olacak sekilde ayarlar.

Kaynakta verilen TEK sayisal hedef budur; model baska hicbir sayi ile
dogrulanamaz, bu yuzden k_wt bir AYAR parametresi olarak kullanilir.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dataclasses import replace
from aag.params import default_config
from aag import sim

TARGET = 0.70

def share(k):
    cfg = default_config()
    cfg.wt = replace(cfg.wt, k_wt=k)
    r = sim.run(cfg)
    return r.energy["twister_share"], r

lo, hi = 1.0, 12.0
print(f"{'k_wt':>7} {'turbin%':>8} {'runout':>7} {'tepe g':>7} {'hook kN':>8} {'RMS':>6} {'sonuc':>6}")
for k in (2.0, 4.0, 6.0, 8.0, 10.0, 12.0):
    sh, r = share(k)
    m = r.metrics
    print(f"{k:7.2f} {100*sh:8.1f} {m['runout']:7.1f} {m['peak_g']:7.2f} "
          f"{m['peak_hook_load']/1e3:8.1f} {m['track_rms']:6.2f} "
          f"{'GECTI' if r.ok(default_config().limits) else 'KALDI':>6}")

for _ in range(18):
    mid = 0.5 * (lo + hi)
    sh, _ = share(mid)
    if sh < TARGET:
        lo = mid
    else:
        hi = mid
k = 0.5 * (lo + hi)
sh, r = share(k)
m = r.metrics
print(f"\n==> k_wt = {k:.3f}  -> turbin payi %{100*sh:.1f}")
print(f"    runout {m['runout']:.1f} m, tepe {m['peak_g']:.2f} g, "
      f"hook {m['peak_hook_load']/1e3:.0f} kN, RMS {m['track_rms']:.2f} m/s, "
      f"{'GECTI' if r.ok(default_config().limits) else 'KALDI'}")
