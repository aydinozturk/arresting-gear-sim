# Uçak gemisi yakalama sistemi — gerçek zamanlı simülasyon

*[English](README.md) · Türkçe*

Saf Python (standart kütüphane, **bağımlılık yok**) ile yazılmış, sabit adımlı,
tohumlu ve tekrar üretilebilir bir yakalama sistemi (arresting gear) simülasyonu.

**Amaç simülasyon değil.** Amaç, kontrol döngüsünü gerçek zamanlı kodun çalışacağı
şekilde (ayrık görevler, yürütme gecikmesi, jitter, overrun, ağ gecikmesi/kaybı)
koşturup **gerçek zamanlı yazılım tarafında yapılacak işleri ölçülmüş sayılara
dayandırmak**: `docs/rt-work-items.md`.

> ⚠️ Modeldeki **tüm sayısal parametreler varsayımdır** (`aag/params.py`).
> Kaynak materyalde su türbini enerji payının ≈%70 olduğu dışında sayı yok.
> Sonuçlar AAG doğrulaması değil, **duyarlılık analizidir**.

## Çalıştırma

Nominal arrest + metin raporu + `out/arrest_nominal.csv`:

```bash
python3 run_arrest.py
```

Model öz-kontrolleri (enerji dengesi, adım yakınsaması, determinizm):

```bash
python3 tests/selfcheck.py
```

Tüm zamanlama / ağ / güç taramaları (~15 dk, `out/*.csv` üretir):

```bash
python3 sweeps/sweep_timing.py
```

Watchdog eşiği × ağ gecikmesi ızgarası + ileri besleme model hatası (~2 dk):

```bash
python3 sweeps/sweep_watchdog.py
```

Adlandırılmış arıza senaryolarının yan yana karşılaştırması:

```bash
python3 run_scenarios.py
```

Nominal koşunun terminalde ASCII grafiği:

```bash
python3 plot_ascii.py
```

Su türbini katsayısını %70 enerji payına göre yeniden ayarlamak:

```bash
python3 tune_twister.py
```

## Görsel arayüz

`ui/simulator.html` — tek dosya, bağımlılıksız etkileşimli tezgâh: güverte görünümü,
canlı telemetri, kabul ölçütleri, gerçek zamanlı olay şeridi (bozulmuş mod, watchdog
tripleri, kaybolan paketler), dört grafik ve enerji paylaşımı. Her ayar değişiminde
arrest yeniden hesaplanır (~25 ms).

Motor `ui/engine.js`, Python modelinin birebir portudur ve dokuz durumda Python
çıktısıyla karşılaştırılmıştır:

```bash
node ui/verify.mjs
```

Sayfayı yeniden üretmek (app.html + engine.js → simulator.html):

```bash
python3 ui/build.py
```

## Dosyalar

| Yol | İçerik |
|---|---|
| `aag/params.py` | Bütün parametreler, hepsi `VARSAYIM` etiketli |
| `aag/plant.py` | Fizik: uçak, halat geometrisi, şok sönümleyici, tambur, su türbini, motor, PCS |
| `aag/control.py` | Dört ayrık kontrol görevi + kazanç bin'leri + bozulmuş mod |
| `aag/rt.py` | **RT zamanlayıcı ve ağ katmanı** — gecikme, jitter, overrun, paket kaybı |
| `aag/sim.py` | Orkestratör + metrikler + enerji muhasebesi |
| `docs/design.md` | Tasarım dokümanı |
| `sweeps/sweep_watchdog.py` | Watchdog × gecikme ızgarası, model hatası duyarlılığı |
| `run_scenarios.py` | Adlandırılmış arıza senaryoları tablosu |
| `tests/selfcheck.py` | Enerji dengesi, adım yakınsaması, determinizm |
| `ui/engine.js` | Modelin JavaScript portu (tarayıcı motoru) |
| `ui/app.html` · `ui/build.py` | Arayüz şablonu ve tek dosyaya paketleyen betik |
| `ui/simulator.html` | Üretilen tek dosyalık arayüz |
| `docs/rt-work-items.md` | **Asıl çıktı**: gerçek zamanlı yazılım iş listesi |

## Model özeti

```
uçak (m, v) ── halat geometrisi s(x)=2(√(x²+B²)−B) ── elastik halat
   └─ ağırlığa göre değişken şok sönümleyici ── tambur (J)
        ├─ su türbini   T = k·ω|ω|      (enerjinin ≈%70'i)
        └─ endüksiyon motoru            (ince kontrol, son durdurma)
              └─ paylaşımlı PCS: DC bara + kondansatör bankası + fren çoperi
```

Kontrol: `supervisor 100 Hz` · `trajectory 500 Hz` · `outer 1 kHz` · `inner 10 kHz`.
Görev çıkışları `serbest bırakma + yürütme süresi` anında uygulanır; görev içi
durum (integratörler) serbest bırakma anında işlenir. Bir iş periyodu aşarsa
`overrun_policy` belirleyicidir: `skip` (varsayılan, gecikme WCET ile sınırlı)
veya `queue` (gecikme sınırsız büyür). Bozulmuş modda güverte verisi yerine
tambur enkoderinden kestirim kullanılabilir (`fallback_estimator`).
