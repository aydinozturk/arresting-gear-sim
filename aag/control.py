"""Kontrol katmani — AYRIK gorevler halinde, gercek zamanli kod yapisinda.

Dort gorev, dort ayri periyot:
  supervisor  100 Hz  — agirlik/hiz bin secimi, watchdog, bozulmus mod
  trajectory  500 Hz  — v_ref(x) referansi
  outer      1000 Hz  — tork komutu (ileri besleme + PI)
  inner     10000 Hz  — akim kontrolu (PI)

Her gorev (state, out) dondurur:
  * state : gorevin KENDI ic durumu (integratorler). Serbest birakma aninda
            islenir — aksi halde ust uste binen isler ayni bayat integratoru
            okur ve overrun deneyleri yanlis sonuc verir.
  * out   : AKTUATORE giden cikti. release + yurutme_suresi aninda uygulanir.
"""

import math
from .plant import dpayout

X_ENGAGE = 6.0          # VARSAYIM: kontrolun devreye girdigi travel [m]
X_RAMP = 28.0           # VARSAYIM: yavaslamanin tam degere ciktigi travel [m]
DSDX_FLOOR = 0.15       # ileri beslemede 1/dsdx patlamasini onler
INTEG_CLAMP = 2.0       # dis cevrim integrator siniri [m]

STATE_KEYS = ("integ_o", "integ_i", "last_good_t_cmd", "degrade_t0",
              "watchdog_events")


def estimate_from_encoder(meas, t, b, radius):
    """Guverte verisi yokken TAMBUR ENKODERINDEN konum/hiz kestirimi.

    s_d = 2*(sqrt(x^2+b^2) - b)  tersine cevrilir. Halat esnemesi kadar
    sistematik hata icerir (tambur tarafi her zaman geride kalir) ama
    guverte agina hic bagli degildir.
    """
    sd = meas.drum_payout(t)
    w = meas.omega(t)
    r = 0.5 * sd + b
    x = math.sqrt(max(0.0, r * r - b * b))
    dsdx = dpayout(x, b)
    v = (w * radius / dsdx) if dsdx > 0.05 else 0.0
    return x, v


def ref_profile(x, v0, xf):
    """Yavaslama X_ENGAGE..X_RAMP arasinda rampalanir, sonra sabit kalir.

    Sabit yavaslamayi temastan itibaren dayatmak fiziksel degil: x kucukken
    ds/dx kucuk oldugu icin ayni kanca kuvveti ASIRI halat gerilimi gerektirir.
    """
    a_nom = v0 * v0 / (2.0 * max(1.0, xf - 0.5 * (X_ENGAGE + X_RAMP)))
    if x < X_ENGAGE:
        return v0, 0.0
    if x < X_RAMP:
        f = (x - X_ENGAGE) / (X_RAMP - X_ENGAGE)
        v2 = v0 * v0 - a_nom * (x - X_ENGAGE) ** 2 / (X_RAMP - X_ENGAGE)
        return math.sqrt(max(0.0, v2)), a_nom * f
    v2 = v0 * v0 - a_nom * (X_RAMP - X_ENGAGE) - 2.0 * a_nom * (x - X_RAMP)
    return math.sqrt(max(0.0, v2)), a_nom


class Controller:
    def __init__(self, cfg, torque_link=None):
        self.cfg = cfg
        self.torque_link = torque_link
        m = cfg.motor
        wc = 2.0 * math.pi * cfg.rt.inner_bandwidth
        self.kp_i = m.l_ph * wc          # akim cevrimi PI (kutup-sifir sadelestirme)
        self.ki_i = m.r_ph * wc
        self.reset()

    def reset(self):
        cfg = self.cfg
        self.v0_latch = cfg.ac.entry_speed
        self.mass_est = cfg.ac.mass + cfg.faults.weight_est_error
        kp, ki, runout = cfg.gains.gains(self.mass_est, self.v0_latch)
        self.kp, self.ki, self.runout_target = kp, ki, runout
        self.bin = cfg.gains.bin_of(self.mass_est, self.v0_latch)
        self.k_wt_set = cfg.wt.k_wt

        # --- aktuatore giden ciktilar (gecikmeli uygulanir)
        self.v_ref = cfg.ac.entry_speed
        self.t_mot_cmd = 0.0
        self.i_cmd = 0.0
        self.u_volt = 0.0
        self.motor_enabled = True
        self.degraded = False
        self.degrade_t0 = -1.0

        # --- gorev ic durumlari (serbest birakmada islenir)
        self.integ_o = 0.0
        self.integ_i = 0.0
        self.last_good_t_cmd = 0.0
        self.watchdog_events = 0
        self.bin_changes = 0

    # ------------------------------------------------------------- supervisor
    def task_supervisor(self, t, meas):
        cfg = self.cfg
        (x, v), stale = meas.deck(t)
        out, state = {}, {}

        # kazanc cizelgeleme: agirlik x hiz "bin" yapisi
        b = cfg.gains.bin_of(self.mass_est, self.v0_latch)
        if b != self.bin:
            self.bin_changes += 1
        kp, ki, runout = cfg.gains.table[b]
        out["bin"], out["kp"], out["ki"], out["runout_target"] = b, kp, ki, runout

        # watchdog: guverte verisi bayatladi mi?
        if stale > cfg.rt.watchdog_timeout:
            out["degraded"] = True
            if not self.degraded and self.degrade_t0 < 0.0:
                state["watchdog_events"] = self.watchdog_events + 1
                state["degrade_t0"] = t
        else:
            out["degraded"] = False
            state["degrade_t0"] = -1.0

        # PCS / kondansator bankasi arizasi -> motor devre disi (tek nokta arizasi)
        f = cfg.faults
        out["motor_enabled"] = not (0.0 <= f.pcs_loss_time <= t and f.pcs_disable_motor)
        return state, out

    # ------------------------------------------------------------- trajectory
    def task_trajectory(self, t, meas):
        cfg = self.cfg
        if self.degraded and cfg.rt.fallback_estimator:
            # Bozulmus modda referans da ENKODER kestiriminden uretilir;
            # aksi halde v_ref donar ve "guverte agindan bagimsiz" olmaz.
            x, _ = estimate_from_encoder(meas, t, cfg.geom.half_span,
                                         cfg.drum.radius)
        else:
            (x, v), stale = meas.deck(t)
        vr, _ = ref_profile(x, self.v0_latch, self.runout_target)
        return {}, {"v_ref": vr}

    # ------------------------------------------------------------ outer loop
    def task_outer(self, t, meas):
        cfg = self.cfg
        (x, v), stale = meas.deck(t)
        w = meas.omega(t)
        mo = cfg.motor
        dt = cfg.rt.tasks["outer"].period

        if self.degraded and not cfg.rt.fallback_estimator:
            # BOZULMUS MOD (varsayilan): once son iyi torku tut, sonra sifira
            # rampala; geriye yalnizca su turbini kalir.
            # DIKKAT: bu GUVENLI BIR DURUM DEGIL — bkz. WI-3. Sabit itki
            # varsayimi altinda ucak hic durmuyor.
            held = t - self.degrade_t0 if self.degrade_t0 >= 0 else 0.0
            hold = cfg.rt.watchdog_hold
            if held <= hold:
                tc = self.last_good_t_cmd
            else:
                tc = self.last_good_t_cmd * max(0.0, 1.0 - (held - hold) / hold)
            return {}, {"t_mot_cmd": tc, "i_cmd": tc / mo.kt}

        if self.degraded:
            # BOZULMUS MOD (alternatif): guverte agini TAMAMEN devre disi birak,
            # tambur enkoderinden kestirimle cevrimi KAPALI tut.
            x, v = estimate_from_encoder(meas, t, cfg.geom.half_span,
                                         cfg.drum.radius)

        if x < X_ENGAGE:
            return ({"integ_o": 0.0, "last_good_t_cmd": 0.0},
                    {"t_mot_cmd": 0.0, "i_cmd": 0.0})

        # ileri besleme: profilin o noktadaki yavaslamasi icin gereken mil torku
        _, a_ref = ref_profile(x, self.v0_latch, self.runout_target)
        f_req = self.mass_est * a_ref + cfg.ac.thrust
        dsdx = max(DSDX_FLOOR, dpayout(x, cfg.geom.half_span))
        t_shaft = (f_req / dsdx) * cfg.drum.radius
        k_est = self.k_wt_set * (1.0 + cfg.wt.k_wt_model_err)
        t_wt_est = k_est * w * abs(w)

        e = v - self.v_ref
        raw = t_shaft - t_wt_est + self.kp * e + self.ki * self.integ_o
        cmd = max(-mo.t_max, min(mo.t_max, raw))

        # Integratoru temas gecisi (tambur hizlanmasi) boyunca DONDUR:
        # snatch sirasindaki asiri yavaslama aksi halde integrali negatife
        # doldurur ve kontrolcu arrest'in geri kalaninda yetersiz frenler.
        integ = self.integ_o
        if x >= X_RAMP and (abs(raw - cmd) < 1e-9 or (raw - cmd) * e < 0.0):
            integ = max(-INTEG_CLAMP, min(INTEG_CLAMP, self.integ_o + e * dt))
        return ({"integ_o": integ, "last_good_t_cmd": cmd},
                {"t_mot_cmd": cmd, "i_cmd": cmd / mo.kt})

    # ------------------------------------------------------------ inner loop
    def task_inner(self, t, meas):
        cfg = self.cfg
        mo = cfg.motor
        dt = cfg.rt.tasks["inner"].period
        i = meas.current(t)
        w = meas.omega(t)
        emf = mo.kt * w
        icmd, _ = meas.torque_cmd(t)
        icmd = max(-mo.i_max, min(mo.i_max, icmd))
        e = icmd - i
        raw = self.kp_i * e + self.ki_i * self.integ_i
        # v_app = emf - u  ve  0 <= v_app <= vbus   =>  emf-vbus <= u <= emf
        vb = meas.vbus(t)
        u = max(emf - vb, min(emf, raw))
        integ = self.integ_i
        if abs(raw - u) < 1e-9 or (raw - u) * e < 0.0:
            integ = self.integ_i + e * dt
        return {"integ_i": integ}, {"u_volt": u}

    # --------------------------------------------------------------- uygulama
    def apply_state(self, state):
        """Serbest birakma aninda — gorevin kendi ic durumu."""
        for k, val in state.items():
            setattr(self, k, val)

    def apply_output(self, out, t):
        """release + yurutme_suresi aninda — aktuatore/paylasilan alana yazim."""
        for k, val in out.items():
            setattr(self, k, val)
            if k == "i_cmd" and self.torque_link is not None:
                self.torque_link.send(t, val)
