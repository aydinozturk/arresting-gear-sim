#!/usr/bin/env python3
"""Tek bir arrest olayini kosar, metin raporu + CSV uretir."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aag.params import default_config
from aag import sim


def report(res, cfg, title="NOMINAL"):
    m, e = res.metrics, res.energy
    L = cfg.limits
    def mark(v, lim, less=True):
        ok = (v <= lim) if less else (v >= lim)
        return "OK " if ok else "IHLAL"
    lines = []
    lines.append("=" * 68)
    lines.append(f"  {title}")
    lines.append("=" * 68)
    lines.append(f"  durdu                 : {m['stopped']}   (t = {m['t_stop']:.2f} s)")
    lines.append(f"  runout                : {m['runout']:7.1f} m     "
                 f"[<= {L.max_runout:.0f}]  {mark(m['runout'], L.max_runout)}")
    lines.append(f"  tepe kanca yuku       : {m['peak_hook_load']/1e3:7.1f} kN    "
                 f"[<= {L.peak_hook_load/1e3:.0f}] {mark(m['peak_hook_load'], L.peak_hook_load)}")
    lines.append(f"  tepe yavaslama        : {m['peak_g']:7.2f} g     "
                 f"[<= {L.peak_g:.1f}]   {mark(m['peak_g'], L.peak_g)}")
    lines.append(f"  hiz izleme RMS        : {m['track_rms']:7.2f} m/s   "
                 f"[<= {L.track_rms:.1f}]   {mark(m['track_rms'], L.track_rms)}")
    lines.append(f"  DC bara tepe/dip      : {m['vbus_max']:7.0f} / {m['vbus_min']:.0f} V "
                 f"[<= {L.v_bus_max:.0f}] {mark(m['vbus_max'], L.v_bus_max)}")
    lines.append(f"  akim izleme RMS       : {m['i_rms']:7.1f} A     "
                 f"(tepe {m['i_err_max']:.0f} A)")
    lines.append("")
    lines.append(f"  kazanc bin'i          : {m['bin']}  (hedef runout {m['runout_target']:.0f} m)")
    lines.append(f"  guverte max bayatlik  : {m['deck_max_stale_ms']:7.2f} ms  "
                 f"(kayip {m['deck_drops']}/{m['deck_sent']})")
    lines.append(f"  watchdog olaylari     : {m['watchdog_events']}")
    lines.append(f"  deadline kacirma      : {m['deadline_misses']}")
    lines.append("")
    lines.append("  ENERJI PAYLASIMI")
    lines.append(f"    giris KE            : {e['ke0']/1e6:7.2f} MJ  (+ itki {e['E_thrust']/1e6:.2f} MJ)")
    lines.append(f"    su turbini          : {e['E_wt']/1e6:7.2f} MJ   %{100*e['twister_share']:.1f}")
    lines.append(f"    motor (mekanik)     : {e['E_mot_mech']/1e6:7.2f} MJ   %{100*e['motor_share']:.1f}")
    lines.append(f"      -> fren coperi    : {e['E_chop']/1e6:7.2f} MJ")
    lines.append(f"      -> bakir kaybi    : {e['E_rloss']/1e6:7.2f} MJ")
    lines.append(f"      -> kondansator    : {e['cap_delta']/1e6:7.2f} MJ")
    lines.append(f"    halat/sok sonumu    : {e['E_damp']/1e6:7.2f} MJ")
    lines.append(f"    enerji denge hatasi : {100*e['balance_err']:7.3f} %")
    lines.append("")
    lines.append("  GOREV ZAMANLAMASI")
    for name, v in res.tasks.items():
        lines.append(f"    {name:11s} rel={v['releases']:6d}  "
                     f"ort={v['mean_latency_us']:6.1f} us  "
                     f"max={v['max_latency_us']:6.1f} us  "
                     f"kacirma={v['deadline_misses']}")
    lines.append(f"  SONUC: {'GECTI' if res.ok(L) else 'KALDI'}")
    return "\n".join(lines)


def write_csv(res, path):
    with open(path, "w") as fh:
        fh.write("t,x,v,v_ref,hook_N,omega,T_twister,T_motor,vbus,i\n")
        for row in res.trace:
            fh.write(",".join(f"{c:.6g}" for c in row) + "\n")


if __name__ == "__main__":
    cfg = default_config()
    res = sim.run(cfg, trace_every=20)
    print(report(res, cfg))
    os.makedirs("out", exist_ok=True)
    write_csv(res, "out/arrest_nominal.csv")
    print("\n  -> out/arrest_nominal.csv")
