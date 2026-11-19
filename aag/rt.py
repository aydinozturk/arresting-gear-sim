"""Gercek zamanli gorev ve ag katmani — SIMULASYONUN ASIL AMACI BURASI.

Her kontrol gorevi:
  * kendi periyodunda serbest birakilir,
  * girisini SERBEST BIRAKMA aninda okur,
  * cikisini  release + yurutme_suresi  aninda uygular  (giris-cikis gecikmesi),
  * yurutme suresi periyodu asarsa DEADLINE KACIRMA sayilir.

Her ag baglantisi: taban gecikme + jitter + paket kaybi + kritik olmayan
trafikten gelen tikaniklik patlamasi. Alici kayipta son degeri tutar;
bayatlik (staleness) olculur ve watchdog bunu kullanir.

NOT: gecikmeler taban adima yuvarlanir (base_dt = 50 us), incelenen
gecikmeler ms mertebesinde oldugu icin bu kabul edilebilir.
"""


class DelayLink:
    __slots__ = ("spec", "rng", "q", "last", "max_stale", "drops", "sent")

    def __init__(self, spec, rng):
        self.spec = spec
        self.rng = rng
        self.q = []
        self.last = None
        self.max_stale = 0.0
        self.drops = 0
        self.sent = 0

    def send(self, t, value, blocked=False):
        s = self.spec
        self.sent += 1
        if blocked:
            self.drops += 1
            return
        if s.dropout > 0.0 and self.rng.random() < s.dropout:
            self.drops += 1
            return
        lat = s.latency
        if s.jitter > 0.0:
            lat += self.rng.uniform(-s.jitter, s.jitter)
        if s.burst_prob > 0.0 and self.rng.random() < s.burst_prob:
            lat += s.burst_extra          # kritik olmayan trafik tikanikligi
        if lat < 0.0:
            lat = 0.0
        self.q.append((t + lat, t, value))

    def recv(self, t):
        if self.q:
            keep = []
            for a, st, v in self.q:
                if a <= t + 1e-12:
                    if self.last is None or st >= self.last[0]:
                        self.last = (st, v)
                else:
                    keep.append((a, st, v))
            self.q = keep
        if self.last is None:
            return None, 0.0
        st, v = self.last
        stale = t - st
        if stale > self.max_stale:
            self.max_stale = stale
        return v, stale


class Measurements:
    """Gorevlerin olcum erisimi. Guverte verisi AG uzerinden, gerisi yerel."""

    def __init__(self, plant, deck_link, torque_link):
        self.plant = plant
        self.deck_link = deck_link
        self.torque_link = torque_link

    def deck(self, t):
        v, stale = self.deck_link.recv(t)
        if v is None:
            y = self.plant.y
            return (y[0], y[1]), 0.0
        return v, stale

    def torque_cmd(self, t):
        """Dis cevrimden akim cevrimine giden komut (dugum ici baglanti)."""
        v, stale = self.torque_link.recv(t)
        return (0.0 if v is None else v), stale

    def drum_payout(self, t):
        return self.plant.y[2]        # yerel enkoder (tambur acisi -> bosaltim)

    def omega(self, t):
        return self.plant.y[3]        # yerel enkoder

    def current(self, t):
        return self.plant.y[5]        # yerel akim olcumu

    def vbus(self, t):
        return self.plant.y[6]


class Task:
    __slots__ = ("spec", "fn", "rng", "next_release", "pending", "prev_finish",
                 "misses", "releases", "max_latency", "sum_latency", "skipped")

    def __init__(self, spec, fn, rng):
        self.spec = spec
        self.fn = fn
        self.rng = rng
        self.next_release = 0.0
        self.pending = []
        self.prev_finish = 0.0      # ayni gorev isleri SIRAYLA kosar
        self.misses = 0
        self.releases = 0
        self.max_latency = 0.0
        self.sum_latency = 0.0
        self.skipped = 0

    def exec_time(self):
        s = self.spec
        e = s.exec_mean
        if s.exec_jitter > 0.0:
            e += self.rng.uniform(-s.exec_jitter, s.exec_jitter)
        if s.overrun_prob > 0.0 and self.rng.random() < s.overrun_prob:
            e *= s.overrun_factor
        return max(0.0, e)


class Scheduler:
    def __init__(self, cfg, ctrl, meas, rng_factory):
        self.cfg = cfg
        self.ctrl = ctrl
        self.meas = meas
        ts = cfg.rt.tasks
        self.skip_overrun = (cfg.rt.overrun_policy == "skip")
        self.tasks = [
            Task(ts["supervisor"], ctrl.task_supervisor, rng_factory("supervisor")),
            Task(ts["trajectory"], ctrl.task_trajectory, rng_factory("trajectory")),
            Task(ts["outer"], ctrl.task_outer, rng_factory("outer")),
        ]
        # bandwidth modunda akim cevrimi ideal kabul edilir -> gorev kosulmaz
        if cfg.rt.inner_mode != "bandwidth":
            self.tasks.append(Task(ts["inner"], ctrl.task_inner, rng_factory("inner")))

    def step(self, t):
        # 1) tamamlanan islerin ciktilarini uygula (giris-cikis gecikmesi).
        #    Isler gorev basina SIRALI oldugu icin pending listesi bitis
        #    zamanina gore artan; eski bir is yenisini EZEMEZ.
        for tk in self.tasks:
            if tk.pending:
                still = []
                for at, out in tk.pending:
                    if at <= t + 1e-12:
                        self.ctrl.apply_output(out, at)
                    else:
                        still.append((at, out))
                tk.pending = still
        # 2) periyodu gelen gorevleri serbest birak
        for tk in self.tasks:
            while t + 1e-12 >= tk.next_release:
                rel = tk.next_release
                if self.skip_overrun and tk.prev_finish > rel + 1e-12:
                    # onceki is hala kosuyor -> bu serbest birakmayi ATLA
                    tk.skipped += 1
                    tk.misses += 1
                    tk.next_release += tk.spec.period
                    continue
                state, out = tk.fn(rel, self.meas)
                # ic durum SERBEST BIRAKMADA islenir (bayat integrator olmaz)
                if state:
                    self.ctrl.apply_state(state)
                d = tk.exec_time()
                start = rel if rel > tk.prev_finish else tk.prev_finish
                finish = start + d
                tk.prev_finish = finish
                lat = finish - rel            # giris-cikis gecikmesi
                if lat > tk.spec.period:
                    tk.misses += 1
                tk.releases += 1
                tk.sum_latency += lat
                if lat > tk.max_latency:
                    tk.max_latency = lat
                tk.pending.append((finish, out))
                tk.next_release += tk.spec.period

    def report(self):
        return {tk.spec.name: {
            "releases": tk.releases,
            "deadline_misses": tk.misses,
            "skipped": tk.skipped,
            "max_latency_us": tk.max_latency * 1e6,
            "mean_latency_us": (tk.sum_latency / tk.releases * 1e6) if tk.releases else 0.0,
        } for tk in self.tasks}
