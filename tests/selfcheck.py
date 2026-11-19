#!/usr/bin/env python3
"""Model oz-kontrolleri. Bunlar gecmeden hicbir tarama sonucuna guvenilmez."""

import os
import sys
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aag.params import default_config
from aag import sim

FAILED = []


def check(name, cond, detail=""):
    print(f"  [{'OK ' if cond else 'HATA'}] {name}  {detail}")
    if not cond:
        FAILED.append(name)


def main():
    print("AAG-Clone oz-kontrolleri")
    print("-" * 60)

    # 1) Enerji dengesi
    cfg = default_config()
    r = sim.run(cfg)
    err = abs(r.energy["balance_err"])
    check("enerji dengesi < %1", err < 0.01, f"hata = %{100*err:.4f}")

    # 2) Adim yakinsamasi: taban adim yariya inince metrikler degismemeli
    cfg2 = default_config()
    cfg2.rt = replace(cfg2.rt, base_dt=cfg2.rt.base_dt / 2.0)
    r2 = sim.run(cfg2)
    for k in ("runout", "peak_g", "peak_hook_load", "track_rms"):
        a, b = r.metrics[k], r2.metrics[k]
        rel = abs(a - b) / max(1e-9, abs(a))
        check(f"adim yakinsamasi: {k} < %1", rel < 0.01,
              f"{a:.4g} -> {b:.4g}  (%{100*rel:.3f})")

    # 3) Determinizm: ayni tohum -> ayni sonuc
    cfg3 = default_config()
    cfg3.rt = replace(cfg3.rt, links={
        "deck": replace(cfg3.rt.links["deck"], jitter=1.0e-3, dropout=0.05),
        "torque": cfg3.rt.links["torque"]})
    a = sim.run(cfg3).metrics
    b = sim.run(cfg3).metrics
    check("determinizm (ayni tohum)", a["runout"] == b["runout"],
          f"{a['runout']:.6f} / {b['runout']:.6f}")

    # 4) Farkli tohum -> farkli sonuc (rastgelelik gercekten etkili mi)
    cfg4 = replace(cfg3, rt=replace(cfg3.rt, seed=cfg3.rt.seed + 1))
    c = sim.run(cfg4).metrics
    check("tohum degisimi sonucu degistiriyor", a["runout"] != c["runout"],
          f"{a['runout']:.4f} vs {c['runout']:.4f}")

    # 4b) Tohumlama SUREÇLER ARASI tekrar uretilebilir mi?
    import subprocess, json
    code = ("import sys;sys.path.insert(0,'.');from dataclasses import replace;"
            "from aag.params import default_config;from aag import sim;"
            "c=default_config();"
            "c.rt=replace(c.rt,links={'deck':replace(c.rt.links['deck'],jitter=1e-3,"
            "dropout=0.05),'torque':c.rt.links['torque']});"
            "print(repr(sim.run(c).metrics['runout']))")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    o1 = subprocess.run([sys.executable, "-c", code], capture_output=True,
                        text=True, cwd=root).stdout.strip()
    o2 = subprocess.run([sys.executable, "-c", code], capture_output=True,
                        text=True, cwd=root).stdout.strip()
    check("determinizm (ayri surecler)", o1 == o2 and o1 != "", f"{o1} / {o2}")

    # 5) Hizli mod (bandwidth) nominal ile tutarli mi
    cfg5 = default_config()
    cfg5.rt = replace(cfg5.rt, inner_mode="bandwidth", base_dt=2.0e-4)
    r5 = sim.run(cfg5)
    rel = abs(r5.metrics["runout"] - r.metrics["runout"]) / r.metrics["runout"]
    check("bandwidth modu nominal ile %3 icinde", rel < 0.03,
          f"{r.metrics['runout']:.2f} -> {r5.metrics['runout']:.2f} (%{100*rel:.2f})")

    # 6) Su turbini enerji payi ~ %70 (kaynaktaki tek sayisal hedef)
    sh = r.energy["twister_share"]
    check("su turbini payi %65-75", 0.65 <= sh <= 0.75, f"%{100*sh:.1f}")

    print("-" * 60)
    if FAILED:
        print(f"BASARISIZ: {len(FAILED)} kontrol -> {FAILED}")
        return 1
    print("TUM KONTROLLER GECTI")
    return 0


if __name__ == "__main__":
    sys.exit(main())
