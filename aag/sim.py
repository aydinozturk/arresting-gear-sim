"""Simulasyon orkestratoru: plant + RT zamanlayici + ag + hatalar + metrikler."""

import math
import random

from .plant import (Plant, PlantInputs, payout, dpayout,
                    IX, IV, ISD, IW, IZ, II, IVB)
from .control import Controller, X_ENGAGE
from .rt import DelayLink, Measurements, Scheduler


class Result:
    def __init__(self):
        self.metrics = {}
        self.tasks = {}
        self.energy = {}
        self.trace = []
        self.events = []

    def ok(self, limits):
        m = self.metrics
        return (m["peak_g"] <= limits.peak_g
                and m["peak_hook_load"] <= limits.peak_hook_load
                and m["runout"] <= limits.max_runout
                and m["track_rms"] <= limits.track_rms
                and m["vbus_max"] <= limits.v_bus_max
                and m["stopped"])


def run(cfg, trace_every=0):
    rt = cfg.rt
    seed = rt.seed

    def rngf(name):
        # DIKKAT: hash() string'lerde surecten surece degisir (PYTHONHASHSEED).
        # Tohum SUREÇLER ARASI tekrar uretilebilir olmali -> metin tohum.
        return random.Random("%d:%s" % (seed, name))

    plant = Plant(cfg)
    ctrl = Controller(cfg)
    deck = DelayLink(rt.links["deck"], rngf("link_deck"))
    torque = DelayLink(rt.links["torque"], rngf("link_torque"))
    ctrl.torque_link = torque
    meas = Measurements(plant, deck, torque)
    sched = Scheduler(cfg, ctrl, meas, rngf)
    u = PlantInputs()

    dt = rt.base_dt
    t = 0.0
    deck_period = 1.0 / rt.deck_rate
    next_deck = 0.0

    res = Result()
    peak_hook = 0.0
    peak_a = 0.0
    sq = 0.0
    nsq = 0
    isq = 0.0
    ierr_max = 0.0
    vbus_max = cfg.pcs.v_nom
    vbus_min = cfg.pcs.v_nom
    pcs_tripped = False
    n = 0
    f = cfg.faults

    while t < cfg.t_max:
        y = plant.y
        if y[IV] <= 0.0:
            break

        # --- guverte sensor dugumu ornekleme (AG uzerinden gonderim)
        if t + 1e-12 >= next_deck:
            outage = (f.net_outage_start >= 0.0
                      and f.net_outage_start <= t < f.net_outage_start + f.net_outage_dur)
            deck.send(t, (y[IX], y[IV]), blocked=outage)
            next_deck += deck_period

        # --- PCS / kondansator bankasi arizasi (TEK NOKTA ARIZASI)
        if (not pcs_tripped) and f.pcs_loss_time >= 0.0 and t >= f.pcs_loss_time:
            plant.c_eff = f.pcs_c_after
            pcs_tripped = True
            res.events.append((t, "PCS_CAP_BANK_LOSS"))

        # --- gercek zamanli gorevler
        sched.step(t)

        u.u_volt = ctrl.u_volt
        u.i_cmd = ctrl.i_cmd
        u.motor_enabled = ctrl.motor_enabled

        plant.step(dt, u, t)
        t += dt
        n += 1

        y = plant.y
        hook = plant.last_hook_force
        if hook > peak_hook:
            peak_hook = hook
        a = (hook + (cfg.ac.roll_resist if y[IV] > 0 else 0.0) - cfg.ac.thrust) / cfg.ac.mass
        if a > peak_a:
            peak_a = a
        if y[IX] > X_ENGAGE:
            e = y[IV] - ctrl.v_ref
            sq += e * e
            nsq += 1
            ie = ctrl.i_cmd - y[II]       # akim cevrimi izleme hatasi
            isq += ie * ie
            if abs(ie) > ierr_max:
                ierr_max = abs(ie)
        if y[IVB] > vbus_max:
            vbus_max = y[IVB]
        if y[IVB] < vbus_min:
            vbus_min = y[IVB]

        if trace_every and n % trace_every == 0:
            res.trace.append((t, y[IX], y[IV], ctrl.v_ref, hook, y[IW],
                              plant.last_t_wt, plant.last_t_mot, y[IVB], y[II]))

    y = plant.y
    en = plant.energy_report()
    diss = en["E_wt"] + en["E_mot_mech"] + en["E_damp"] + en["E_roll"] + en["E_fric"]
    res.energy = en
    res.energy["twister_share"] = en["E_wt"] / diss if diss > 0 else 0.0
    res.energy["motor_share"] = en["E_mot_mech"] / diss if diss > 0 else 0.0
    res.energy["balance_err"] = (
        (en["ke0"] + en["E_thrust"]) - (en["ke"] + en["rot"] + en["spring"] + diss)
    ) / max(1.0, en["ke0"])

    res.metrics = {
        "stopped": y[IV] <= 0.0,
        "runout": y[IX],
        "t_stop": t,
        "peak_hook_load": peak_hook,
        "peak_g": peak_a / 9.81,
        "track_rms": math.sqrt(sq / nsq) if nsq else 0.0,
        "i_rms": math.sqrt(isq / nsq) if nsq else 0.0,
        "i_err_max": ierr_max,
        "vbus_max": y[IVB] if y[IVB] > vbus_max else vbus_max,
        "vbus_min": vbus_min,
        "deck_max_stale_ms": deck.max_stale * 1e3,
        "deck_drops": deck.drops,
        "deck_sent": deck.sent,
        "watchdog_events": ctrl.watchdog_events,
        "bin": ctrl.bin,
        "runout_target": ctrl.runout_target,
    }
    res.metrics["vbus_max"] = vbus_max
    res.tasks = sched.report()
    res.metrics["deadline_misses"] = sum(v["deadline_misses"] for v in res.tasks.values())
    return res
