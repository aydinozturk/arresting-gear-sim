#!/usr/bin/env python3
"""Adlandirilmis senaryolarin yan yana karsilastirmasi.

Taramalar esikleri bulur; bu dosya "gercekci" birkac bozulma noktasini
tek tabloda gosterir.
"""
import os
import sys
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aag.params import default_config
from aag import sim


def base():
    return default_config()


def link(cfg, name, **kw):
    links = dict(cfg.rt.links)
    links[name] = replace(links[name], **kw)
    cfg.rt = replace(cfg.rt, links=links)
    return cfg


def task(cfg, name, **kw):
    ts = dict(cfg.rt.tasks)
    ts[name] = replace(ts[name], **kw)
    cfg.rt = replace(cfg.rt, tasks=ts)
    return cfg


SCENARIOS = [
    ("nominal", lambda c: c),
    ("ag gecikmesi 10 ms", lambda c: link(c, "deck", latency=10e-3)),
    ("jitter +-5 ms", lambda c: link(c, "deck", latency=2e-3, jitter=5e-3)),
    ("paket kaybi %20", lambda c: link(c, "deck", latency=2e-3, dropout=0.20)),
    ("tikaniklik 30 ms (%10)",
     lambda c: link(c, "deck", latency=1e-3, burst_prob=0.10, burst_extra=30e-3)),
    ("dis cevrim overrun %20",
     lambda c: task(c, "outer", overrun_prob=0.20, overrun_factor=8.0)),
    ("tork dalgalanmasi %20",
     lambda c: setattr_(c, "motor", replace(c.motor, ripple_amp=0.20))),
    ("ag kopmasi 150 ms",
     lambda c: setattr_(c, "faults", replace(c.faults, net_outage_start=0.9,
                                             net_outage_dur=0.150))),
    ("PCS kaybi t=1.2 s",
     lambda c: setattr_(c, "faults", replace(c.faults, pcs_loss_time=1.2))),
    ("agirlik hatasi +6000 kg",
     lambda c: setattr_(c, "faults", replace(c.faults, weight_est_error=6000))),
]


def setattr_(obj, k, v):
    setattr(obj, k, v)
    return obj


def main():
    L = default_config().limits
    print("  Not: 'DURMADI' = ucak 6 s simulasyon penceresinde hic durmadi;\n"
          "       bu satirlarda runout degeri kesilmis (censored) bir degerdir.\n")
    print(f"{'senaryo':>26} {'runout':>7} {'tepe g':>7} {'hook kN':>8} {'RMS':>6} "
          f"{'vbus':>6} {'wd':>3} {'dl':>4} {'turb%':>6} {'sonuc':>6}")
    print("-" * 94)
    rows = []
    for name, mut in SCENARIOS:
        cfg = mut(base())
        r = sim.run(cfg)
        m = r.metrics
        ok = r.ok(L)
        rows.append((name, m, r.energy, ok))
        ro = f"{m['runout']:.1f}" if m['stopped'] else "DURMADI"
        print(f"{name:>26} {ro:>7} {m['peak_g']:7.2f} "
              f"{m['peak_hook_load']/1e3:8.0f} {m['track_rms']:6.2f} "
              f"{m['vbus_max']:6.0f} {m['watchdog_events']:3d} "
              f"{m['deadline_misses']:4d} {100*r.energy['twister_share']:6.1f} "
              f"{'GECTI' if ok else 'KALDI':>6}")
    os.makedirs("out", exist_ok=True)
    with open("out/scenarios.csv", "w") as fh:
        fh.write("scenario,stopped,runout,peak_g,peak_hook_N,track_rms,vbus_max,"
                 "watchdog,deadline_misses,twister_share,ok\n")
        for n, m, e, ok in rows:
            fh.write(f'"{n}",{int(m["stopped"])},{m["runout"]:.3f},{m["peak_g"]:.3f},'
                     f'{m["peak_hook_load"]:.1f},{m["track_rms"]:.3f},'
                     f'{m["vbus_max"]:.1f},{m["watchdog_events"]},'
                     f'{m["deadline_misses"]},{e["twister_share"]:.4f},{int(ok)}\n')
    print("\n  -> out/scenarios.csv")


if __name__ == "__main__":
    main()
