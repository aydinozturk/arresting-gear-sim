#!/usr/bin/env python3
"""Watchdog esigi x ag gecikmesi izgarasi + ileri besleme model hatasi.

Ana tarama, gecikme esiginin kontrol DINAMIGINDEN degil WATCHDOG
AYARINDAN geldigini gosterdi. Bu dosya o iki boyutu ayirir.
"""
import os
import sys
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aag.params import default_config
from aag import sim

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")
LAT = [0, 5, 10, 20, 30, 50, 80, 120]
WD = [5, 10, 20, 40, 80, 160, 1000]


def run(lat_ms, wd_ms, kerr=0.0, disable_wd=False):
    c = default_config()
    links = dict(c.rt.links)
    links["deck"] = replace(links["deck"], latency=lat_ms * 1e-3, jitter=0.2e-3)
    c.rt = replace(c.rt, links=links, watchdog_timeout=wd_ms * 1e-3)
    c.wt = replace(c.wt, k_wt_model_err=kerr)
    return sim.run(c)


def main():
    L = default_config().limits
    print("=" * 80)
    print("  A. WATCHDOG ESIGI x AG GECIKMESI")
    print("     hucre: runout [m] veya DURMADI (6 s icinde hic durmadi), * = KALDI")
    print("=" * 80)
    hdr = "wd / lat"
    print(f"  {hdr:>8}" + "".join(f"{l:>9}" for l in LAT) + "   [ms]")
    rows = []
    for wd in WD:
        line = f"  {wd:>8}"
        for lat in LAT:
            r = run(lat, wd)
            ok = r.ok(L)
            rows.append((wd, lat, r.metrics, ok))
            cell = f"{r.metrics['runout']:.0f}" if r.metrics["stopped"] else "DURMADI"
            line += f"{cell:>8}{'' if ok else '*'}"
        print(line)
    print("  Not: hucreler tek tohum, jitter +-0.2 ms, nominal diger parametreler.")
    print("  Okuma: watchdog esigi en kotu gecikmenin ALTINDA kalirsa, saglam veri")
    print("         geldigi halde sistem kalici bozulmus moda duser. Varsayilan")
    print("         bozulmus mod (tork rampasi) ile ucak HIC DURMUYOR; enkoder")
    print("         kestirimi (rt.fallback_estimator) ile duruyor (bkz. WI-3).")

    print()
    print("=" * 80)
    print("  B. ILERI BESLEME MODEL HATASI (su turbini katsayisi kestirimi)")
    print("=" * 80)
    print(f"  {'k_wt hatasi':>12} {'runout':>8} {'tepe g':>7} {'hook kN':>8} "
          f"{'RMS':>7} {'sonuc':>6}")
    rows2 = []
    for kerr in (-0.8, -0.5, -0.3, -0.1, 0.0, 0.1, 0.3, 0.5, 0.8):
        r = run(1, 20, kerr=kerr)
        m = r.metrics
        ok = r.ok(L)
        rows2.append((kerr, m, ok))
        print(f"  {100*kerr:11.0f}% {m['runout']:8.1f} {m['peak_g']:7.2f} "
              f"{m['peak_hook_load']/1e3:8.0f} {m['track_rms']:7.2f} "
              f"{'GECTI' if ok else 'KALDI':>6}")

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "sweep_watchdog_grid.csv"), "w") as fh:
        fh.write("watchdog_ms,latency_ms,stopped,runout,peak_g,track_rms,ok\n")
        for wd, lat, m, ok in rows:
            fh.write(f"{wd},{lat},{int(m['stopped'])},{m['runout']:.3f},"
                     f"{m['peak_g']:.3f},{m['track_rms']:.3f},{int(ok)}\n")
    with open(os.path.join(OUT, "sweep_model_error.csv"), "w") as fh:
        fh.write("k_wt_err,runout,peak_g,peak_hook_N,track_rms,ok\n")
        for k, m, ok in rows2:
            fh.write(f"{k},{m['runout']:.3f},{m['peak_g']:.3f},"
                     f"{m['peak_hook_load']:.1f},{m['track_rms']:.3f},{int(ok)}\n")


if __name__ == "__main__":
    main()
