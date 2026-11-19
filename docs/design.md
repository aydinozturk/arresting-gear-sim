# AAG-Clone — Tasarım Dokümanı

Tarih: 2026-11-18 · Durum: **yaklaşım onaylandı** (saf Python, RT görev yapısında kontrolcü).
Dokümanın kendisi onaya sunulmadı; kullanıcı yaklaşımı seçip "başla" dedi.

## 1. Niyet ve neden

Uçak gemisi gelişmiş yakalama sisteminin (AAG benzeri) kapalı çevrim davranışını simüle etmek.
**Asıl amaç simülasyon değil**: gerçek zamanlı yazılım tarafında yapılacak işleri (görev periyotları,
deadline'lar, jitter bütçeleri, watchdog davranışı, bozulmuş modlar, ağ ayrıştırma kuralları)
**ölçülmüş sayılara dayanarak** tanımlamak.

Bu yüzden simülasyonun merkezinde fizik değil, **kontrolcünün gerçek zamanlı kod gibi çalışması** var:
ayrık görevler, yürütme gecikmesi, jitter, overrun, ağ gecikmesi ve paket kaybı enjekte edilebilir
olmalı. Düz bir fizik simülasyonu bu iş listesini üretemez.

## 2. Hedefler / hedef olmayanlar / anti-hedefler

**Hedefler**
- Tek bir arrest olayını uçtan uca simüle etmek: temas → halat gerilimi → kontrollü yavaşlama → duruş.
- Kontrolü 4 ayrı periyotlu görev olarak çalıştırmak ve her görevin zamanlama bütçesini bozabilmek.
- Gecikme / jitter / paket kaybı / tork dalgalanması / kondansatör bankası kaybı taraması yapıp
  metriklerin **nerede kırıldığını** bulmak.
- Her gerçek zamanlı iş maddesini bir tarama sonucuna bağlamak.

**Hedef olmayanlar**
- Gerçek AAG'nin doğrulanması. Kaynakta ≈%70 su türbini enerji payı dışında sayısal parametre yok.
- 3 boyutlu halat dinamiği, dalga/gemi hareketi, pilot modeli, aerodinamik ayrıntı.
- Motor faz-seviyesi (abc/dq) modellemesi; toplulaştırılmış makine yeterli.

**Anti-hedefler** (teknik olarak çalışsa bile başarısızlık sayılır)
- Parametreleri "gerçek AAG değeri" gibi sunmak.
- Zamanlamayı ideal kabul eden, gecikme enjekte edilemeyen bir kontrolcü.
- Adaptif adımlı çözücü kullanmak — gecikme/jitter deneylerini anlamsız kılar.

## 3. Kısıtlar

- Saf Python standart kütüphane. Bağımlılık yok (numpy kurulu değil, kurulmayacak).
- Sabit taban adımı; görev periyotları taban adımının tam katı.
- Tüm rastgelelik tohumlu → "deterministik olmayan" koşular tekrar üretilebilir.
- Tüm sayısal parametreler tek dosyada (`aag/params.py`) ve `VARSAYIM` etiketli.

## 4. Değerlendirilen yaklaşımlar

| Yaklaşım | Artı | Eksi | Karar |
|---|---|---|---|
| **A. Python plant + Python kontrolcü, RT görev yapısında** | Tek dil, hızlı iterasyon, zamanlama modeli enjekte edilebilir, C'ye taşımak mekanik | Gerçek OS jitter'ı ölçülmez, modellenir | **Seçildi** (kullanıcı onayı) |
| B. Python plant + baştan C kontrolcü | Gerçek yürütme süresi ölçülür | Her deney döngüsü yavaş, IPC karmaşası, tarama yapmak pahalı | Elendi — amaç önce *hangi* bütçenin gerektiğini bulmak |
| C. Sürekli zamanlı ideal kontrolcü (klasik `solve_ivp` tarzı) | En basit | Gecikme/jitter anlamsızlaşır → amacı doğrudan baltalar | Elendi |

## 5. Mimari

```
                 ┌──────────── DECK SENSOR NODE ───────────┐
                 │  x, v  (ağ üzerinden, gecikmeli/kayıplı) │
                 └──────────────────┬──────────────────────┘
                                    │  DelayLink(latency, jitter, dropout, congestion)
   ┌────────────────────────────────▼──────────────────────────────────┐
   │ RT SCHEDULER (sabit taban adımı, görev başına periyot+WCET+jitter)│
   │  T1 supervisor   100 Hz  → ağırlık/hız bin seçimi, watchdog       │
   │  T2 trajectory   500 Hz  → v_ref(x)                               │
   │  T3 outer loop  1000 Hz  → tork komutu (PI + ileri besleme)       │
   │  T4 inner loop 10000 Hz  → akım kontrolü (PI)                     │
   └────────────────────────────────┬──────────────────────────────────┘
                                    │ v_app
   ┌────────────────────────────────▼──────────────────────────────────┐
   │ PLANT (sürekli, RK4, sabit adım)                                  │
   │  uçak(m,v) ─ halat geometrisi s(x)=2(√(x²+B²)−B) ─ elastik halat  │
   │  ─ ağırlığa göre değişken şok sönümleyici ─ tambur(J)             │
   │  tambur mili → su türbini T=k·ω|ω|   (hedef ≈%70 enerji)          │
   │                → endüksiyon motoru  (ince kontrol)                │
   │  motor ↔ PCS (DC bara, kondansatör bankası, fren çoperi)          │
   └───────────────────────────────────────────────────────────────────┘
```

**Görev–çıkış gecikmesi**: her görev serbest bırakıldığında girişini okur, çıkışını
`release + exec_time(jitter'lı)` anında uygular. `exec_time > period` ise deadline kaçırma sayılır.

**Ağ**: her sinyal için `DelayLink` — gecikme + jitter + kayıp olasılığı + kritik olmayan trafikten
gelen tıkanıklık patlaması. Alıcı kayıpta son değeri tutar ve bayatlık (staleness) sayacını artırır.
`staleness > watchdog_timeout` → bozulmuş moda geçiş.

## 6. Enjekte edilebilen hatalar

1. Kontrol döngüsü gecikmesi (sabit) ve jitter (rastgele, tohumlu)
2. Görev overrun (olasılıksal, uzun yürütme)
3. Ağ paket kaybı ve tıkanıklık patlaması (kritik olmayan trafik)
4. Faz dengesizliği + uzun güç kablosundan tork dalgalanması (ω'ya bağlı salınım)
5. Kondansatör bankası / PCS kaybı (arrest ortasında, tek nokta arızası)
6. Ağırlık kestirim hatası → yanlış kazanç bin'i

## 7. Metrikler ve kabul ölçütleri

| Metrik | Sınır (varsayım) |
|---|---|
| Tepe yavaşlama | ≤ 4.5 g |
| Tepe kanca yükü | ≤ 1.10 MN |
| Runout mesafesi | ≤ 103 m |
| Hız izleme RMS hatası | ≤ 3.0 m/s |
| DC bara tepe gerilimi | ≤ 7.5 kV |

Ek izlenenler: enerji paylaşımı (türbin/motor/çoper/halat), deadline kaçırma sayısı,
maksimum kontrol gecikmesi, maksimum bayatlık, watchdog olayları.

## 8. Öz-kontroller

- **Enerji dengesi** %1 içinde kapanmalı (KE + itki işi = türbin + motor + sönüm + yay + yuvarlanma).
- **Adım yakınsaması**: taban adımı yarıya indiğinde metrikler %1'den az değişmeli.
- **Determinizm**: aynı tohum aynı sonucu vermeli — **ayrı süreçlerde de**
  (`hash()` string'lerde süreçten sürece değişir; tohumlama metin tabanlı).
- **Hızlı mod tutarlılığı**: ideal akım çevrimi (`bandwidth`, 5 kHz taban adım)
  nominal ile %3 içinde olmalı; ms mertebesi ağ taramaları bu modda koşar.

## 9. Teslimatlar

1. `aag/` paketi — plant, kontrol, RT zamanlayıcı, ağ, hatalar, metrikler
2. `run_arrest.py` — tek arrest koşusu, metin raporu + CSV
3. `sweeps/sweep_timing.py` — gecikme/jitter/kayıp/tork dalgalanması taramaları
4. `tests/selfcheck.py` — enerji dengesi ve adım yakınsaması
5. `docs/rt-work-items.md` — **asıl çıktı**: her maddesi bir tarama sonucuna bağlı
   gerçek zamanlı yazılım iş listesi

## 10. Builder'a bırakılanlar

Sayısal parametre değerleri (hepsi varsayım, tek dosyada), PI kazançlarının ilk ayarı,
tarama ızgarası çözünürlüğü, rapor formatı.

**Ayarlanan tek sayı**: `k_wt` (su türbini katsayısı), kaynaktaki ≈%70 enerji payı
hedefine göre `tune_twister.py` ile ayarlanmıştır (sonuç: 5.90). Başka hiçbir
parametre bir ölçüme göre kalibre edilemez.
