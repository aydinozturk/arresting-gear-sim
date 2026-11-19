#!/usr/bin/env python3
"""Gercek zamanli zamanlama / ag / guc taramalari.

Her tarama bir parametreyi buyuturken kabul olcutlerinin NEREDE kirildigini
bulur. Cikan esikler dogrudan gercek zamanli yazilim is maddelerine donusur
(docs/rt-work-items.md).

Her nokta coklu tohumla kosulur; raporlanan deger EN KOTU durumdur.
Zamanlama (us mertebesi) taramalari 20 kHz taban adimli "detailed" modda,
ag (ms mertebesi) taramalari 5 kHz taban adimli "bandwidth" modunda kosar.
"""

import os
import sys
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aag.params import default_config
from aag import sim

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")


def fast_cfg():
    """Ideal akim cevrimi, 5 kHz taban adim (selfcheck ile dogrulandi)."""
    cfg = default_config()
    cfg.rt = replace(cfg.rt, inner_mode="bandwidth", base_dt=2.0e-4)
    return cfg


def detail_cfg():
    """Tam akim cevrimi, 20 kHz taban adim — us mertebesi zamanlama icin."""
    return default_config()


def set_link(cfg, name, **kw):
    links = dict(cfg.rt.links)
    links[name] = replace(links[name], **kw)
    cfg.rt = replace(cfg.rt, links=links)
    return cfg


def set_task(cfg, name, **kw):
    tasks = dict(cfg.rt.tasks)
    tasks[name] = replace(tasks[name], **kw)
    cfg.rt = replace(cfg.rt, tasks=tasks)
    return cfg


def set_rt(cfg, **kw):
    cfg.rt = replace(cfg.rt, **kw)
    return cfg


def set_motor(cfg, **kw):
    cfg.motor = replace(cfg.motor, **kw)
    return cfg


def set_faults(cfg, **kw):
    cfg.faults = replace(cfg.faults, **kw)
    return cfg


def evaluate(make_cfg, value, mutate, seeds):
    worst = {"peak_g": 0.0, "peak_hook_load": 0.0, "runout": 0.0,
             "track_rms": 0.0, "vbus_max": 0.0, "fails": 0,
             "watchdog_events": 0, "deadline_misses": 0, "not_stopped": 0}
    for s in seeds:
        cfg = mutate(make_cfg(), value)
        cfg.rt = replace(cfg.rt, seed=cfg.rt.seed + 7919 * s)
        r = sim.run(cfg)
        m = r.metrics
        for k in ("peak_g", "peak_hook_load", "runout", "track_rms", "vbus_max"):
            if m[k] > worst[k]:
                worst[k] = m[k]
        worst["watchdog_events"] = max(worst["watchdog_events"], m["watchdog_events"])
        worst["deadline_misses"] = max(worst["deadline_misses"], m["deadline_misses"])
        if not m["stopped"]:
            worst["not_stopped"] += 1
        if not r.ok(cfg.limits):
            worst["fails"] += 1
    return worst


def run_sweep(title, unit, values, mutate, make_cfg=fast_cfg, fname=None,
              seeds=None, signed=False):
    if seeds is None:
        seeds = (0, 1, 2, 3, 4) if make_cfg is fast_cfg else (0, 1, 2)
    print()
    print("=" * 80)
    print(f"  {title}")
    print("=" * 80)
    print(f"  {unit:>14} {'runout':>8} {'tepe g':>7} {'hook kN':>8} {'RMS':>6} "
          f"{'vbus':>6} {'wd':>3} {'dl':>5} {'durmadi':>8} {'kalan':>6}")
    rows, threshold = [], None
    for v in values:
        w = evaluate(make_cfg, v, mutate, seeds)
        rows.append((v, w))
        if w["fails"] and threshold is None:
            threshold = v
        flag = "" if w["fails"] == 0 else f"<-- {w['fails']}/{len(seeds)} KALDI"
        nst = f"{w['not_stopped']}/{len(seeds)}" if w['not_stopped'] else "-"
        print(f"  {v:14.4g} {w['runout']:8.1f} {w['peak_g']:7.2f} "
              f"{w['peak_hook_load']/1e3:8.0f} {w['track_rms']:6.2f} "
              f"{w['vbus_max']:6.0f} {w['watchdog_events']:3d} "
              f"{w['deadline_misses']:5d} {nst:>8} {w['fails']:6d}  {flag}")
    if signed:
        neg = [v for v, w in rows if v < 0 and w["fails"]]
        pos = [v for v, w in rows if v > 0 and w["fails"]]
        lo = max(neg) if neg else None
        hi = min(pos) if pos else None
        print(f"  --> sifira EN YAKIN ihlal: negatif tarafta "
              f"{'yok' if lo is None else f'{lo:g}'}, pozitif tarafta "
              f"{'yok' if hi is None else f'{hi:g}'}")
        threshold = (lo, hi)
    else:
        print(f"  --> {'test edilen araligin tamaminda GECTI' if threshold is None else f'ILK IHLAL: {threshold:g}'}")
    if any(w["not_stopped"] for _, w in rows):
        print("      DIKKAT: bazi kosularda ucak t_max icinde HIC DURMADI; "
              "'runout' degeri kesilmis (censored) bir degerdir.")
    if fname:
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, fname), "w") as fh:
            fh.write("value,runout,peak_g,peak_hook_N,track_rms,vbus_max,"
                     "watchdog,deadline_misses,fails\n")
            for v, w in rows:
                fh.write(f"{v:g},{w['runout']:.4f},{w['peak_g']:.4f},"
                         f"{w['peak_hook_load']:.1f},{w['track_rms']:.4f},"
                         f"{w['vbus_max']:.1f},{w['watchdog_events']},"
                         f"{w['deadline_misses']},{w['fails']}\n")
    return threshold


# ---------------------------------------------------------------- bin izgarasi
def bin_grid():
    print()
    print("=" * 80)
    print("  12. KAZANC BIN IZGARASI (agirlik x hiz) — nominal zamanlama")
    print("=" * 80)
    print(f"  {'kutle':>6} {'hiz':>5} {'bin':>7} {'runout':>7} {'g':>5} "
          f"{'hookkN':>7} {'RMS':>6} {'turb%':>6} {'sonuc':>6}")
    rows = []
    for mass in (12000, 16000, 20000, 24000):
        for v0 in (52, 60, 68, 76):
            cfg = default_config()
            cfg.ac = replace(cfg.ac, mass=mass, entry_speed=v0)
            r = sim.run(cfg)
            m = r.metrics
            ok = r.ok(cfg.limits)
            rows.append((mass, v0, m, r.energy["twister_share"], ok))
            print(f"  {mass:6d} {v0:5d} {str(m['bin']):>7} {m['runout']:7.1f} "
                  f"{m['peak_g']:5.2f} {m['peak_hook_load']/1e3:7.0f} "
                  f"{m['track_rms']:6.2f} {100*r.energy['twister_share']:6.1f} "
                  f"{'GECTI' if ok else 'KALDI':>6}")
    bad = [(a, b) for a, b, m, s, ok in rows if not ok]
    print(f"  --> {len(rows)-len(bad)}/{len(rows)} bin kabul olcutlerini saglıyor; "
          f"saglamayanlar: {bad}")
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "bin_grid.csv"), "w") as fh:
        fh.write("mass,v0,bin_w,bin_v,runout,peak_g,peak_hook_N,track_rms,twister_share,ok\n")
        for mass, v0, m, sh, ok in rows:
            fh.write(f"{mass},{v0},{m['bin'][0]},{m['bin'][1]},{m['runout']:.3f},"
                     f"{m['peak_g']:.3f},{m['peak_hook_load']:.1f},"
                     f"{m['track_rms']:.3f},{sh:.4f},{int(ok)}\n")
    return bad


# ------------------------------------------------- degisken sok sonumleme etkisi
def shock_study():
    print()
    print("=" * 80)
    print("  13. DEGISKEN SOK SONUMLEME (cizelgeli vs sabit) — ilk carpma sicramasi")
    print("=" * 80)
    print(f"  {'kutle':>6} {'cizelgeli hook kN':>18} {'sabit hook kN':>14} "
          f"{'cizelgeli g':>12} {'sabit g':>9}")
    rows = []
    for mass in (12000, 16000, 20000, 24000):
        out = {}
        for mode in ("scheduled", "fixed"):
            cfg = default_config()
            cfg.ac = replace(cfg.ac, mass=mass)
            cfg.cable = replace(cfg.cable, scheduling=mode)
            r = sim.run(cfg)
            out[mode] = r.metrics
        rows.append((mass, out))
        print(f"  {mass:6d} {out['scheduled']['peak_hook_load']/1e3:18.0f} "
              f"{out['fixed']['peak_hook_load']/1e3:14.0f} "
              f"{out['scheduled']['peak_g']:12.2f} {out['fixed']['peak_g']:9.2f}")
    with open(os.path.join(OUT, "shock_study.csv"), "w") as fh:
        fh.write("mass,sched_hook_N,fixed_hook_N,sched_peak_g,fixed_peak_g\n")
        for mass, o in rows:
            fh.write(f"{mass},{o['scheduled']['peak_hook_load']:.1f},"
                     f"{o['fixed']['peak_hook_load']:.1f},"
                     f"{o['scheduled']['peak_g']:.3f},{o['fixed']['peak_g']:.3f}\n")
    return rows


def main():
    res = {}

    res["deck_latency"] = run_sweep(
        "1. GUVERTE SENSOR -> KONTROLCU AG GECIKMESI", "gecikme [ms]",
        [0, 1, 2, 4, 6, 8, 10, 14, 18, 24, 30, 40],
        lambda c, v: set_link(c, "deck", latency=v * 1e-3),
        fname="sweep_deck_latency.csv")

    res["deck_jitter"] = run_sweep(
        "2. AG GECIKME JITTER'I (deterministik olmayan davranis)", "jitter +-[ms]",
        [0, 0.5, 1, 2, 3, 4, 6, 8, 10, 14, 20],
        lambda c, v: set_link(c, "deck", latency=2e-3, jitter=v * 1e-3),
        fname="sweep_deck_jitter.csv")

    res["dropout"] = run_sweep(
        "3. PAKET KAYBI", "kayip [%]",
        [0, 1, 2, 5, 10, 20, 30, 50, 70, 85],
        lambda c, v: set_link(c, "deck", latency=2e-3, dropout=v / 100.0),
        fname="sweep_dropout.csv")

    res["congestion"] = run_sweep(
        "4. KRITIK OLMAYAN TRAFIKTEN TIKANIKLIK (kontrol dongusu AYRILMAMIS)",
        "patlama [ms]",
        [0, 2, 5, 10, 15, 20, 30, 40, 60, 90],
        lambda c, v: set_link(c, "deck", latency=1e-3, burst_prob=0.10,
                              burst_extra=v * 1e-3),
        fname="sweep_congestion.csv")

    res["outage"] = run_sweep(
        "5. TAM AG KOPMASI SURESI (watchdog / bozulmus mod)", "kopma [ms]",
        [0, 10, 20, 40, 60, 100, 150, 250, 400, 600],
        lambda c, v: set_faults(c, net_outage_start=0.9, net_outage_dur=v * 1e-3),
        fname="sweep_outage.csv")

    # ---- gorev zamanlamasi (us mertebesi) -> detailed mod
    res["outer_exec"] = run_sweep(
        "6. DIS CEVRIM YURUTME SURESI (sensor->tork yolu gecikmesi)", "WCET [us]",
        [50, 150, 300, 500, 700, 900, 1500, 2500, 4000],
        lambda c, v: set_task(c, "outer", exec_mean=v * 1e-6, exec_jitter=0.1 * v * 1e-6),
        make_cfg=detail_cfg, fname="sweep_outer_exec.csv")

    res["outer_overrun"] = run_sweep(
        "7. DIS CEVRIM OVERRUN OLASILIGI (8x WCET patlamasi)", "overrun [%]",
        [0, 1, 5, 10, 20, 40, 60, 80, 100],
        lambda c, v: set_task(c, "outer", overrun_prob=v / 100.0, overrun_factor=8.0),
        make_cfg=detail_cfg, fname="sweep_outer_overrun.csv")

    res["outer_period"] = run_sweep(
        "8. DIS CEVRIM PERIYODU", "periyot [ms]",
        [0.5, 1, 2, 4, 6, 8, 12, 16, 24, 32],
        lambda c, v: set_task(c, "outer", period=v * 1e-3),
        make_cfg=detail_cfg, fname="sweep_outer_period.csv")

    res["inner_exec"] = run_sweep(
        "9. AKIM CEVRIMI YURUTME SURESI", "WCET [us]",
        [10, 25, 40, 60, 80, 95, 120, 200, 400],
        lambda c, v: set_task(c, "inner", exec_mean=v * 1e-6, exec_jitter=0.2 * v * 1e-6),
        make_cfg=detail_cfg, fname="sweep_inner_exec.csv")

    res["inner_period"] = run_sweep(
        "10. AKIM CEVRIMI PERIYODU", "periyot [us]",
        [50, 100, 200, 400, 600, 1000, 1500, 2500, 4000],
        lambda c, v: set_task(c, "inner", period=v * 1e-6),
        make_cfg=detail_cfg, fname="sweep_inner_period.csv")

    res["torque_link"] = run_sweep(
        "11. DIS CEVRIM -> AKIM CEVRIMI BAGLANTI GECIKMESI (dugum ici/arasi)",
        "gecikme [us]",
        [0, 100, 250, 500, 750, 1000, 1500, 2500, 4000],
        lambda c, v: set_link(c, "torque", latency=v * 1e-6, jitter=0.2 * v * 1e-6),
        make_cfg=detail_cfg, fname="sweep_torque_link.csv")

    res["deck_rate"] = run_sweep(
        "12. GUVERTE SENSOR ORNEKLEME HIZI", "hiz [Hz]",
        [2000, 1000, 500, 250, 125, 100, 50, 25],
        lambda c, v: set_rt(c, deck_rate=v),
        make_cfg=detail_cfg, fname="sweep_deck_rate.csv")

    res["ripple"] = run_sweep(
        "13. TORK DALGALANMASI (faz dengesizligi / uzun guc kablosu)", "dalgalanma [%]",
        [0, 2, 5, 10, 15, 20, 30, 40, 60],
        lambda c, v: set_motor(c, ripple_amp=v / 100.0),
        make_cfg=detail_cfg, fname="sweep_ripple.csv")

    res["pcs_loss"] = run_sweep(
        "14. PCS KONDANSATOR BANKASI KAYBI ANI (tek nokta arizasi)", "ariza t [s]",
        [-1, 0.2, 0.5, 0.8, 1.2, 1.6, 2.0, 2.4],
        lambda c, v: set_faults(c, pcs_loss_time=v),
        fname="sweep_pcs.csv")

    res["weight_err"] = run_sweep(
        "15. AGIRLIK KESTIRIM HATASI (yanlis kazanc bin'i + yanlis sok sonumu)",
        "hata [kg]",
        [-8000, -6000, -4000, -2000, 0, 2000, 4000, 6000, 8000],
        lambda c, v: set_faults(c, weight_est_error=v),
        fname="sweep_weight.csv", signed=True)

    # ---- OVERRUN POLITIKASI: kuyruk vs atla
    for pol in ("queue", "skip"):
        res[f"inner_exec_{pol}"] = run_sweep(
            f"16{'a' if pol == 'queue' else 'b'}. AKIM CEVRIMI WCET — overrun politikasi = {pol}",
            "WCET [us]", [25, 60, 95, 120, 200, 400, 800],
            lambda c, v, _p=pol: set_task(set_rt(c, overrun_policy=_p), "inner",
                                          exec_mean=v * 1e-6, exec_jitter=0.2 * v * 1e-6),
            make_cfg=detail_cfg, fname=f"sweep_inner_exec_{pol}.csv")

    # ---- BOZULMUS MOD: tork rampasi vs enkoder kestirimi
    for fb in (False, True):
        res[f"latency_fb_{int(fb)}"] = run_sweep(
            f"17{'b' if fb else 'a'}. AG GECIKMESI — bozulmus modda "
            f"{'ENKODER KESTIRIMI' if fb else 'tork rampasi'}",
            "gecikme [ms]", [0, 10, 20, 30, 50, 80, 120, 200],
            lambda c, v, _f=fb: set_link(set_rt(c, fallback_estimator=_f), "deck",
                                         latency=v * 1e-3),
            fname=f"sweep_latency_fallback_{int(fb)}.csv")

    # ---- TAM AG KOPMASI x bozulmus mod
    for fb in (False, True):
        res[f"outage_fb_{int(fb)}"] = run_sweep(
            f"18{'b' if fb else 'a'}. TAM AG KOPMASI — bozulmus modda "
            f"{'ENKODER KESTIRIMI' if fb else 'tork rampasi'}",
            "kopma [ms]", [0, 100, 250, 400, 600, 1000, 1500],
            lambda c, v, _f=fb: set_faults(set_rt(c, fallback_estimator=_f),
                                           net_outage_start=0.9,
                                           net_outage_dur=v * 1e-3),
            fname=f"sweep_outage_fallback_{int(fb)}.csv")

    bad_bins = bin_grid()
    shock_study()

    print()
    print("=" * 80)
    print("  OZET: ILK IHLAL ESIKLERI")
    print("=" * 80)
    for k, thr in res.items():
        print(f"    {k:14s} : {'GECTI (aralik sonuna kadar)' if thr is None else thr}")
    print(f"    bin izgarasi   : kalan bin sayisi = {len(bad_bins)}")
    return res


if __name__ == "__main__":
    main()
