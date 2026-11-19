"""AAG-Clone parametreleri.

!!! UYARI !!!
Bu dosyadaki TÜM sayısal degerler VARSAYIMDIR. Kaynak materyalde su turbini enerji
payinin ~%70 oldugu disinda hicbir sayisal parametre verilmemistir. Buradaki degerler
acik literaturden ve buyukluk mertebesi akil yurutmesinden turetilmis, modeli makul
bir calisma noktasina oturtmak icin ayarlanmistir.

=> Sonuclari "AAG dogrulamasi" olarak degil, DUYARLILIK ANALIZI olarak okuyun.
"""

from dataclasses import dataclass, field, replace
from typing import Dict, Tuple


# --------------------------------------------------------------------------
# Ucak ve guverte geometrisi
# --------------------------------------------------------------------------
@dataclass
class Aircraft:
    mass: float = 22000.0          # VARSAYIM: kanca agirligi [kg]
    entry_speed: float = 65.0      # VARSAYIM: temas hizi [m/s] (~126 kt)
    thrust: float = 100.0e3        # VARSAYIM: tam gaz itki (bolter emniyeti) [N]
    roll_resist: float = 6.0e3     # VARSAYIM: yuvarlanma + aero surtunme [N]


@dataclass
class Geometry:
    half_span: float = 15.0        # VARSAYIM: guverte makarasi yanal mesafesi B [m]
    max_runout: float = 103.0      # VARSAYIM: izin verilen azami runout [m]
    # payout: s(x) = 2*(sqrt(x^2+B^2) - B)   -> travel'a gore DOGRUSAL DEGIL


# --------------------------------------------------------------------------
# Halat + degisken sok sonumleyici
# --------------------------------------------------------------------------
@dataclass
class Cable:
    k_cable: float = 4.0e5         # VARSAYIM: etkin halat yay katsayisi [N/m]
    c_cable: float = 1.0e4         # VARSAYIM: halat ic sonumu [N.s/m]
    k_shock: float = 3.0e5         # VARSAYIM: sok sonumleyici yay [N/m]
    c_shock_ref: float = 6.0e4     # VARSAYIM: referans agirlikta sonum [N.s/m]
    w_ref: float = 18000.0         # VARSAYIM: referans ucak agirligi [kg]
    shock_exp: float = 1.0         # VARSAYIM: c_shock = c_ref*(W/W_ref)^exp
    shock_k_exp: float = 1.0       # VARSAYIM: k_shock = k_ref*(W/W_ref)^k_exp
    scheduling: str = "scheduled"  # "scheduled" (agirliga gore) | "fixed" (sabit)
    # => "degisken sok sonumleme": ilk carpma sicramasini ucagin agirligina gore karsilar

    def c_shock(self, mass: float) -> float:
        return self.c_shock_ref * (mass / self.w_ref) ** self.shock_exp

    def k_shock_of(self, mass: float) -> float:
        """Sok sonumleyici YAY katsayisi da agirliga gore cizelgelenir.

        Ilk carpma sicramasinin buyuklugunu belirleyen sey tambur hizlanma
        torkudur (J*dw/dt) ve bu ucak agirligindan BAGIMSIZDIR. Ayni kuvvet
        hafif ucakta cok daha yuksek g demektir; bu yuzden hafif ucakta
        sonumleyici YUMUSATILIR.
        """
        return self.k_shock * (mass / self.w_ref) ** self.shock_k_exp


# --------------------------------------------------------------------------
# Tambur mili: su turbini + endüksiyon motoru (PAYLASIMLI MIL)
# --------------------------------------------------------------------------
@dataclass
class Drum:
    radius: float = 0.55           # VARSAYIM: tambur yaricapi [m]
    inertia: float = 300.0         # VARSAYIM: mil + turbin rotoru ataleti [kg.m^2]
    friction: float = 120.0        # VARSAYIM: viskoz surtunme [N.m.s/rad]


@dataclass
class WaterTwister:
    """Hidrodinamik fren. T = k * w * |w|  (enerjinin ~%70'i burada)."""
    k_wt: float = 5.90             # VARSAYIM/AYARLI (tune_twister.py: %70 turbin enerji payi)
    k_wt_model_err: float = 0.0    # kontrolcunun model hatasi (ileri beslemede)


@dataclass
class Motor:
    """Toplulastirilmis endüksiyon makinesi (4 motorun esdegeri). Ince kontrol."""
    kt: float = 30.0               # VARSAYIM: mil-referansli tork sabiti [N.m/A] (= ke)
    r_ph: float = 0.004            # VARSAYIM: esdeger direnc [ohm]
    l_ph: float = 0.4e-3           # VARSAYIM: esdeger endüktans [H]
    i_max: float = 7500.0          # VARSAYIM: akim limiti [A]
    t_max: float = 220.0e3         # VARSAYIM: tork limiti [N.m]
    # Faz dengesizligi + uzun guc kablosundan tork dalgalanmasi
    ripple_amp: float = 0.0        # 0.08 => %8 tepe dalgalanma
    ripple_order: float = 6.0      # mekanik devir basina harmonik mertebe


@dataclass
class PCS:
    """Paylasimli Guc Kosullandirma Sistemi — TEK NOKTA ARIZASI noktasi."""
    v_nom: float = 6500.0          # VARSAYIM: DC bara nominal [V]
    v_max: float = 7500.0          # VARSAYIM: bara ust sinir [V]
    v_chop: float = 7000.0         # VARSAYIM: fren coperi esigi [V]
    r_chop: float = 0.05           # VARSAYIM: coper direnci [ohm]
    c_bank: float = 1.5            # VARSAYIM: kondansator bankasi [F]


# --------------------------------------------------------------------------
# Kontrol: kazanc cizelgeleme ("bin" yapisi)
# --------------------------------------------------------------------------
@dataclass
class GainBins:
    """Kazanclar ucagin AGIRLIGINA ve HIZINA gore cizelgelenir."""
    weight_edges: Tuple[float, ...] = (14000.0, 18000.0, 22000.0)   # kg
    speed_edges: Tuple[float, ...] = (56.0, 64.0, 72.0)             # m/s
    # Hedef runout YALNIZCA hiz bin'ine bagli: durma mesafesini belirleyen
    # sey enerji/hiz; ucak agirligi degil. (Ilk surumde agirliga da baglanmisti
    # ve hafif ucak + yuksek hiz koselerinde tepe g limitini asiyordu.)
    runout_by_speed: Tuple[float, ...] = (66.0, 82.0, 97.0, 101.0)   # [m]

    # (w_bin, v_bin) -> (Kp, Ki, runout_hedefi [m])
    table: Dict[Tuple[int, int], Tuple[float, float, float]] = field(default_factory=lambda: {
        (i, j): (
            6.0e3 + 4.0e3 * i + 1.5e3 * j,       # Kp [N.m / (m/s)] — kutle ile olcekli
            9.0e3 + 6.0e3 * i + 2.0e3 * j,       # Ki [N.m / m]
            (66.0, 82.0, 97.0, 101.0)[j],        # hedef runout [m] — hiz ile olcekli
        )
        for i in range(4) for j in range(4)
    })

    def bin_of(self, mass: float, speed: float) -> Tuple[int, int]:
        i = sum(1 for e in self.weight_edges if mass > e)
        j = sum(1 for e in self.speed_edges if speed > e)
        return i, j

    def gains(self, mass: float, speed: float):
        return self.table[self.bin_of(mass, speed)]


# --------------------------------------------------------------------------
# Gercek zamanli gorev / ag parametreleri  (ASIL ILGI ALANI)
# --------------------------------------------------------------------------
@dataclass
class TaskSpec:
    name: str
    period: float            # [s]
    exec_mean: float         # ortalama yurutme suresi [s]
    exec_jitter: float = 0.0 # +- uniform jitter [s]
    overrun_prob: float = 0.0
    overrun_factor: float = 3.0


@dataclass
class LinkSpec:
    name: str
    latency: float = 0.0      # taban gecikme [s]
    jitter: float = 0.0       # +- uniform [s]
    dropout: float = 0.0      # paket kaybi olasiligi [0..1]
    burst_prob: float = 0.0   # kritik olmayan trafikten tikaniklik patlamasi
    burst_extra: float = 0.0  # patlamada eklenen gecikme [s]


@dataclass
class RTConfig:
    base_dt: float = 5.0e-5                 # taban adim [s] (20 kHz)
    deck_rate: float = 1000.0               # guverte sensor dugumu ornekleme [Hz]
    inner_mode: str = "detailed"            # "detailed" | "bandwidth"
    inner_bandwidth: float = 400.0          # bandwidth modunda akim cevrimi BW [Hz]
    watchdog_timeout: float = 0.020         # bayatlik esigi [s]
    watchdog_hold: float = 0.050            # bozulmus modda tutma suresi [s]
    # Bir is periyodu asarsa ne olur?
    #   "skip"  : onceki is bitmeden yeni serbest birakma ATLANIR (gecikme sinirli)
    #   "queue" : isler kuyruga girer (gecikme sinirsiz buyur) — karsilastirma icin
    overrun_policy: str = "skip"
    # Bozulmus modda guverte verisi yerine TAMBUR ENKODERINDEN kestirim kullan.
    # VARSAYILAN False = "tasarlandigi hali" (motor torku sifira rampalanir).
    # DIKKAT: bu GUVENLI DURUM DEGIL — 30 ms ve uzeri kalici gecikmede ucak
    # hic durmuyor. True yapmak bunu duzeltiyor (bkz. docs/rt-work-items.md,
    # WI-3). Varsayilan, taramalarin referans noktasini korumak icin False
    # birakildi; tasarim onerisi True'dur.
    fallback_estimator: bool = False
    seed: int = 20261118

    tasks: Dict[str, TaskSpec] = field(default_factory=lambda: {
        "supervisor":  TaskSpec("supervisor", 1.0 / 100.0,   120e-6, 20e-6),
        "trajectory":  TaskSpec("trajectory", 1.0 / 500.0,    80e-6, 15e-6),
        "outer":       TaskSpec("outer",      1.0 / 1000.0,  150e-6, 30e-6),
        "inner":       TaskSpec("inner",      1.0 / 10000.0,  25e-6,  5e-6),
    })
    links: Dict[str, LinkSpec] = field(default_factory=lambda: {
        # guverte sensor dugumu -> kontrol dugumu (AG UZERINDEN)
        "deck":  LinkSpec("deck", latency=1.0e-3, jitter=0.2e-3),
        # kontrol dugumu ici: tork komutu -> akim cevrimi
        "torque": LinkSpec("torque", latency=0.0, jitter=0.0),
    })


# --------------------------------------------------------------------------
# Hata enjeksiyonu
# --------------------------------------------------------------------------
@dataclass
class Faults:
    pcs_loss_time: float = -1.0     # <0 => yok. >=0 => bu anda kondansator bankasi kaybi
    pcs_c_after: float = 0.02       # ariza sonrasi etkin kapasite [F]
    pcs_disable_motor: bool = True  # ariza motoru devre disi birakir mi
    net_outage_start: float = -1.0  # tam ag kopmasi baslangici [s]
    net_outage_dur: float = 0.0     # suresi [s]
    weight_est_error: float = 0.0   # kazanc bin'i icin agirlik kestirim hatasi [kg]


# --------------------------------------------------------------------------
# Limitler (kabul olcutleri)
# --------------------------------------------------------------------------
@dataclass
class Limits:
    peak_g: float = 4.5
    peak_hook_load: float = 1.10e6     # [N]
    max_runout: float = 103.0          # [m]
    track_rms: float = 3.0             # [m/s]
    v_bus_max: float = 7500.0          # [V]


@dataclass
class Config:
    ac: Aircraft = field(default_factory=Aircraft)
    geom: Geometry = field(default_factory=Geometry)
    cable: Cable = field(default_factory=Cable)
    drum: Drum = field(default_factory=Drum)
    wt: WaterTwister = field(default_factory=WaterTwister)
    motor: Motor = field(default_factory=Motor)
    pcs: PCS = field(default_factory=PCS)
    gains: GainBins = field(default_factory=GainBins)
    rt: RTConfig = field(default_factory=RTConfig)
    faults: Faults = field(default_factory=Faults)
    limits: Limits = field(default_factory=Limits)
    t_max: float = 6.0               # azami simulasyon suresi [s]


def default_config() -> Config:
    return Config()


def tweak(cfg: Config, **kw) -> Config:
    """Siglice kopyalayip ust duzey alanlari degistirir (tarama icin)."""
    return replace(cfg, **kw)
