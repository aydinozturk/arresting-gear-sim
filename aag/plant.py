"""Fiziksel model (plant) — surekli zaman, SABIT adimli RK4.

Adaptif adimli cozucu BILEREK kullanilmiyor: kontrolcu gecikmesi/jitter'i
enjekte edildiginde adaptif adim deneyleri anlamsiz kilar.

Durum vektoru:
  0 x        ucak konumu [m]
  1 v        ucak hizi [m/s]
  2 s_d      tambur tarafi halat bosaltimi [m]  (= r*theta)
  3 w        tambur acisal hizi [rad/s]
  4 z        sok sonumleyici deformasyonu [m]
  5 i        motor akimi [A]
  6 vbus     DC bara gerilimi [V]
  7 E_wt     su turbini enerjisi [J]
  8 E_mot    motorun aldigi mekanik enerji [J]
  9 E_chop   fren coperinde yakilan enerji [J]
 10 E_rloss  motor bakir kaybi [J]
 11 E_damp   halat + sok sonumleyici kaybi [J]
 12 E_thr    itkinin yaptigi is [J]
 13 E_roll   yuvarlanma/aero kaybi [J]
 14 theta    tambur acisi [rad] (tork dalgalanmasi fazi)
 15 E_fric   mil surtunme kaybi [J]
"""

import math

NSTATE = 16
IX, IV, ISD, IW, IZ, II, IVB, IEWT, IEMOT, IECH, IERL, IEDMP, IETHR, IEROLL, ITH, IEFR = range(16)


def payout(x: float, b: float) -> float:
    """Guverte pandantinin toplam bosaltimi. Travel'a gore DOGRUSAL DEGIL."""
    return 2.0 * (math.sqrt(x * x + b * b) - b)


def dpayout(x: float, b: float) -> float:
    """ds/dx — ayni zamanda kanca kuvveti / halat gerilimi orani."""
    return 2.0 * x / math.sqrt(x * x + b * b)


class PlantInputs:
    """Kontrolcuden plant'a gecen tutulmus (zero-order hold) girisler."""
    __slots__ = ("u_volt", "i_cmd", "motor_enabled")

    def __init__(self):
        self.u_volt = 0.0        # detailed modda: geri-EMK ayrilmis gerilim komutu
        self.i_cmd = 0.0         # bandwidth modda: akim komutu
        self.motor_enabled = True


class Plant:
    def __init__(self, cfg):
        self.cfg = cfg
        g, ac, cb = cfg.geom, cfg.ac, cfg.cable
        self.b = g.half_span
        self.m = ac.mass
        # Sok sonumleyici KESTIRILEN agirliga gore ayarlanir (ucak tipi verisi);
        # agirlik kestirim hatasi hem kazanc bin'ini hem sonumu etkiler.
        if cb.scheduling == "fixed":
            self.c_shock = cb.c_shock_ref
            self.k_shock = cb.k_shock
        else:
            m_est = ac.mass + cfg.faults.weight_est_error
            self.c_shock = cb.c_shock(m_est)
            self.k_shock = cb.k_shock_of(m_est)
        self.c_eff = None          # ariza sonrasi kapasite
        self.k_wt_eff = cfg.wt.k_wt
        self.reset()

    def reset(self):
        cfg = self.cfg
        y = [0.0] * NSTATE
        y[IX] = 0.0
        y[IV] = cfg.ac.entry_speed
        y[IVB] = cfg.pcs.v_nom
        self.y = y
        self.c_eff = cfg.pcs.c_bank
        self.last_tension = 0.0
        self.last_hook_force = 0.0
        self.last_t_mot = 0.0
        self.last_t_wt = 0.0

    # ---------------------------------------------------------------- tension
    def tension(self, y):
        """Halat gerilimi — seri (halat yayi) + (sok sonumleyici) cozumu.

        Cebirsel dongu kapali formda cozuluyor:
          T = k_c*d + c_c*(rel - zdot),   zdot = (T - k_sa*z)/c_sa
        """
        cb = self.cfg.cable
        b = self.b
        x, v = y[IX], y[IV]
        s = payout(x, b)
        sdot = dpayout(x, b) * v
        d = s - y[ISD] - y[IZ]
        rel = sdot - self.cfg.drum.radius * y[IW]
        cs = self.c_shock
        num = cb.k_cable * d + cb.c_cable * rel + (cb.c_cable * self.k_shock / cs) * y[IZ]
        t = num / (1.0 + cb.c_cable / cs)
        if t < 0.0:
            t = 0.0                      # halat itemez (gevsek)
        zdot = (t - self.k_shock * y[IZ]) / cs
        return t, zdot, rel, sdot

    # ------------------------------------------------------------ derivatives
    def deriv(self, y, u: PlantInputs, t_now: float):
        cfg = self.cfg
        ac, cb, dr, wt, mo, pc = cfg.ac, cfg.cable, cfg.drum, cfg.wt, cfg.motor, cfg.pcs
        dy = [0.0] * NSTATE

        tens, zdot, rel, _ = self.tension(y)
        dsdx = dpayout(y[IX], self.b)
        f_hook = tens * dsdx

        # --- ucak
        v = y[IV]
        f_roll = ac.roll_resist if v > 0.0 else 0.0
        dy[IX] = v
        dy[IV] = (ac.thrust - f_hook - f_roll) / self.m

        # --- sok sonumleyici
        dy[IZ] = zdot

        # --- motor akimi
        i = y[II]
        emf = mo.kt * y[IW]
        if not u.motor_enabled:
            dy[II] = -i / 2.0e-3          # hizli sonumleme (converter kapali)
            v_app = 0.0
        elif cfg.rt.inner_mode == "bandwidth":
            wc = 2.0 * math.pi * cfg.rt.inner_bandwidth
            icmd = max(-mo.i_max, min(mo.i_max, u.i_cmd))
            dy[II] = wc * (icmd - i)
            v_app = emf - (mo.l_ph * dy[II] + mo.r_ph * i)
            v_app = max(0.0, min(y[IVB], v_app))
        else:
            v_app = max(0.0, min(y[IVB], emf - u.u_volt))
            u_eff = emf - v_app
            dy[II] = (u_eff - mo.r_ph * i) / mo.l_ph

        # --- tork dalgalanmasi (faz dengesizligi + uzun guc kablosu)
        ripple = 1.0
        if mo.ripple_amp != 0.0:
            ripple = 1.0 + mo.ripple_amp * math.sin(mo.ripple_order * y[ITH])
        t_mot = mo.kt * i * ripple
        t_wt = self.k_wt_eff * y[IW] * abs(y[IW])
        t_fric = dr.friction * y[IW]

        dy[ITH] = y[IW]
        dy[ISD] = dr.radius * y[IW]
        dy[IW] = (tens * dr.radius - t_wt - t_mot - t_fric) / dr.inertia

        # --- DC bara / kondansator bankasi (PAYLASIMLI PCS)
        vb = max(50.0, y[IVB])
        p_in = v_app * i if u.motor_enabled else 0.0
        p_chop = (vb - pc.v_chop) * vb / pc.r_chop if vb > pc.v_chop else 0.0
        dy[IVB] = (p_in - p_chop) / (self.c_eff * vb)

        # --- enerji muhasebesi
        dy[IEWT] = t_wt * y[IW]
        dy[IEMOT] = emf * i if u.motor_enabled else 0.0
        dy[IECH] = p_chop
        dy[IERL] = mo.r_ph * i * i
        dy[IEDMP] = cb.c_cable * (rel - zdot) ** 2 + self.c_shock * zdot * zdot
        dy[IETHR] = ac.thrust * v
        dy[IEROLL] = f_roll * v
        dy[IEFR] = t_fric * y[IW]

        self.last_tension = tens
        self.last_hook_force = f_hook
        self.last_t_mot = t_mot
        self.last_t_wt = t_wt
        return dy

    # --------------------------------------------------------------- stepping
    def step(self, dt: float, u: PlantInputs, t_now: float):
        """Sabit adimli RK4. Kontrolcu cikisi adim boyunca sabit tutulur."""
        y = self.y
        k1 = self.deriv(y, u, t_now)
        y2 = [y[j] + 0.5 * dt * k1[j] for j in range(NSTATE)]
        k2 = self.deriv(y2, u, t_now + 0.5 * dt)
        y3 = [y[j] + 0.5 * dt * k2[j] for j in range(NSTATE)]
        k3 = self.deriv(y3, u, t_now + 0.5 * dt)
        y4 = [y[j] + dt * k3[j] for j in range(NSTATE)]
        k4 = self.deriv(y4, u, t_now + dt)
        s6 = dt / 6.0
        for j in range(NSTATE):
            y[j] += s6 * (k1[j] + 2.0 * k2[j] + 2.0 * k3[j] + k4[j])

        im = self.cfg.motor.i_max
        if y[II] > im:
            y[II] = im
        elif y[II] < -im:
            y[II] = -im
        if y[IVB] < 50.0:
            y[IVB] = 50.0
        # deriv'i son durumda bir kez daha cagirip rapor degerlerini tazele
        self.deriv(y, u, t_now + dt)

    # ------------------------------------------------------------- yardimcilar
    def energy_report(self):
        y = self.y
        cfg = self.cfg
        ke0 = 0.5 * self.m * cfg.ac.entry_speed ** 2
        ke = 0.5 * self.m * y[IV] ** 2
        rot = 0.5 * cfg.drum.inertia * y[IW] ** 2
        d = payout(y[IX], self.b) - y[ISD] - y[IZ]
        spring = 0.5 * cfg.cable.k_cable * max(0.0, d) ** 2 + 0.5 * self.k_shock * y[IZ] ** 2
        cap0 = 0.5 * cfg.pcs.c_bank * cfg.pcs.v_nom ** 2
        cap = 0.5 * self.c_eff * y[IVB] ** 2
        return {
            "ke0": ke0, "ke": ke, "rot": rot, "spring": spring,
            "E_wt": y[IEWT], "E_mot_mech": y[IEMOT], "E_chop": y[IECH],
            "E_rloss": y[IERL], "E_damp": y[IEDMP], "E_thrust": y[IETHR],
            "E_roll": y[IEROLL], "E_fric": y[IEFR],
            "cap_delta": cap - cap0,
        }
