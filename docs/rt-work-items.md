# Gerçek Zamanlı Yazılım İş Listesi — AAG-Clone

Bu dosya projenin **asıl çıktısıdır**. Her madde, simülasyonda ölçülmüş bir
tarama sonucuna bağlıdır; sonucun hangi koşudan geldiği madde içinde yazılıdır.

> ⚠️ **Tüm sayılar varsayım parametreli bir modelden gelir** (`aag/params.py`).
> Kaynakta ≈%70 su türbini enerji payı dışında sayı yok. Bunlar mutlak eşik
> değil, **modele göreli duyarlılıklardır**: "bu mimaride hangi zamanlama
> özelliği önemli, hangisi değil" sorusunu yanıtlarlar. Bütçeleri marjla
> kullanın; mutlak değer olarak alıntılamayın.

> ℹ️ **"Durmadı" notu:** bazı arızalarda uçak 6 s'lik simülasyon penceresinde
> hiç durmuyor. Bu satırlarda yazan runout **kesilmiş (censored)** bir değerdir,
> gerçek runout daha büyüktür. (PCS kaybı senaryosunda `t_max = 20 s` ile
> 409 m ölçüldü ve uçak hâlâ hareket hâlindeydi.) Bu sonuç, arrest boyunca
> **itkinin tam gazda kaldığı** varsayımına bağlıdır.

---

## 0. Nominal referans noktası

`python3 run_arrest.py` — 22 t, 65 m/s, bin (2,2):

| Metrik | Değer | Sınır |
|---|---|---|
| Runout | 97.7 m | ≤ 103 |
| Tepe kanca yükü | 804 kN | ≤ 1100 |
| Tepe yavaşlama | 3.29 g | ≤ 4.5 |
| Hız izleme RMS | 2.19 m/s | ≤ 3.0 |
| DC bara tepe | 7076 V | ≤ 7500 |
| Su türbini enerji payı | **%70.2** | hedef ≈%70 |
| Enerji denge hatası | %0.000 | < %1 |

Görev yükü (modellenen yürütme süreleri): supervisor 100 Hz / 120 µs,
trajectory 500 Hz / 80 µs, outer 1 kHz / 150 µs, inner 10 kHz / 25 µs.
Overrun politikası `skip`, bozulmuş mod `tork rampası`.

---

## 1. İki baş bulgu

### 1.1 WCET değil, **overrun politikası** belirleyici

`sweeps/sweep_timing.py` #16a/#16b — akım çevrimi WCET'i, periyot 100 µs sabit:

| WCET | `queue` (kuyruk) | `skip` (atla) |
|---|---|---|
| 25 µs | 97.7 m · 3.29 g · 804 kN | 97.7 m · 3.29 g · 804 kN |
| 95 µs | 97.7 m · 3.29 g (14 641 kaçırma) | 97.7 m · 3.29 g (14 870 kaçırma) |
| **120 µs** | **durmadı · 8.42 g · 1910 kN** | 97.7 m · 3.29 g · 804 kN |
| 200 µs | 128.5 m · 7.31 g · 1672 kN | 97.7 m · 3.29 g · 804 kN |
| 400 µs | 137.1 m · 5.97 g · 1381 kN | 97.7 m · 3.30 g · 806 kN |
| 800 µs | durmadı · 6.47 g · 1491 kN | 98.6 m · 3.37 g · 822 kN (RMS 3.88 → KALDI) |

`queue` politikasında `WCET > periyot` olur olmaz işler birikiyor, giriş-çıkış
gecikmesi her işte 20 µs büyüyor ve sonuç **mekanik hasar seviyesine** çıkıyor.
`skip` politikasında (önceki iş bitmeden gelen serbest bırakma atlanır) aynı
WCET'te hiçbir metrik değişmiyor; 4× aşım bile zararsız.

**Yani 8.42 g bir zamanlama hassasiyeti değil, sınırsız kuyruk artefaktıdır.**
Tasarım kararı "WCET'i küçült" değil, **"overrun politikasını tanımla"**dır.

**Uyarı — arrest metrikleri akım çevrimini gizliyor.** `skip` politikasında
arrest metrikleri nominal kalsa da akım çevrimi izleme hatası büyüyor:

| WCET (periyot 100 µs) | akım hatası RMS | runout | hız RMS |
|---|---|---|---|
| 25 µs | 19.8 A | 97.7 m | 2.19 |
| 120 µs | 26.2 A | 97.7 m | 2.19 |
| 200 µs | 34.8 A | 97.7 m | 2.20 |
| 400 µs | **1160 A** | 97.7 m | 2.23 |
| 800 µs | **3672 A** | 98.6 m | 3.83 |

400 µs'de arrest hâlâ nominal görünüyor ama akım çevrimi **çökmüş durumda**
(i_max = 7500 A). Kabul kriterleri yalnızca arrest metriklerine bakmamalı;
akım izleme hatası ayrı bir sağlık göstergesi olmalı.

### 1.2 Kritik yol, güverte ağı **değil** — ama bozulmuş mod güvenli değil

`sweeps/sweep_watchdog.py` — watchdog eşiği × ağ gecikmesi, hücre = runout [m]:

```
  wd / lat        0        5       10       20       30       50       80      120   [ms]
         5      98      98* DURMADI* DURMADI* DURMADI* DURMADI* DURMADI* DURMADI*
        10      98      98      98* DURMADI* DURMADI* DURMADI* DURMADI* DURMADI*
        20      98      98      98      98* DURMADI* DURMADI* DURMADI* DURMADI*
        40      98      98      98      98      98 DURMADI* DURMADI* DURMADI*
        80      98      98      98      98      98      98      98* DURMADI*
       160      98      98      98      98      98      98      98      98
      1000      98      98      98      98      98      98      98      98
```
(hücre: runout [m]; `DURMADI` = uçak 6 s içinde hiç durmadı; `*` = KALDI)

İhlal sınırı tam köşegen: sorun gecikmenin kendisi değil,
**`gecikme ≥ watchdog eşiği`** olması. Watchdog 160 ms'e çekildiğinde 120 ms
saf gecikme bile runout'u değiştirmiyor.

Nedeni mimaride: dış çevrim ileri besleme ağırlıklı ve su türbini `T = k·ω|ω|`
ile güçlü **pasif geri besleme** sağlıyor; uçak dinamiği saniyeler mertebesinde.

**Ama köşegenin asıl sebebi watchdog değil, tripten sonra ne yapıldığı.**
Varsayılan bozulmuş mod motor torkunu sıfıra rampalıyor; geriye yalnızca su
türbini kalıyor ve o, düşük hızda sabit itkiyi yenemiyor — uçak **hiç durmuyor**.

#17a / #17b — **kalıcı gecikme**, iki farklı bozulmuş mod:

| Gecikme | tork rampası (#17a) | tambur enkoderinden kestirim (#17b) |
|---|---|---|
| 10 ms | 97.7 m · GEÇTİ | 97.7 m · GEÇTİ |
| 20 ms | 156.9 m · 4.15 g · RMS 17.4 | 99.1 m · 3.36 g · RMS 3.05 (5 tohumun 1'i KALDI) |
| 30 ms | **DURMADI** · RMS 18.1 | 99.2 m · 3.43 g · RMS 3.31 |
| 50 ms | **DURMADI** | 99.2 m · 3.43 g · RMS 3.31 |
| 120 ms | **DURMADI** | 99.2 m · 3.53 g · RMS 3.38 |
| 200 ms | **DURMADI** | 99.2 m · 3.30 g · RMS 3.18 |

#18a / #18b — **tam ağ kopması** (t = 0.9 s'de başlıyor):

| Kopma | tork rampası (#18a) | enkoder kestirimi (#18b) |
|---|---|---|
| 250 ms | 97.6 m · RMS 2.40 · GEÇTİ | 97.7 m · RMS 2.23 · GEÇTİ |
| 400 ms | 97.6 m · RMS **3.08** · KALDI | 97.7 m · RMS 2.29 · **GEÇTİ** |
| 600 ms | 98.5 m · **4.54 g · 1074 kN** · KALDI | 97.8 m · 3.29 g · RMS 2.41 · **GEÇTİ** |
| 1000 ms | 107.8 m · 4.60 g · RMS 11.24 · KALDI | 98.4 m · 3.43 g · RMS 2.90 · **GEÇTİ** |
| 1500 ms | 119.7 m · 4.41 g · RMS 12.84 · KALDI | 98.9 m · 3.29 g · RMS 2.78 · **GEÇTİ** |

Enkoder kestirimi (`s_d = 2(√(x²+B²) − B)` tersine çevrilir, `v ≈ ω·r/(ds/dx)`;
referans `v_ref` de aynı kestirimden üretilir) güverte ağına **hiç bağlı değil**.
Kalıcı gecikmede uçak her zaman 99.2 m'de duruyor — ihlal yalnızca hız izleme
RMS'inde (3.18–3.38 vs limit 3.0), runout ve tepe g sınırların içinde.
**Tam kopmada ise 1.5 saniyelik kesinti bile hiçbir ölçütü ihlal etmiyor.**

**Sonuç: güverte ağını emniyet yolundan çıkar.** Bu, "watchdog eşiğini ayarla"
maddesinden daha güçlü bir gerekliliktir.

---

## 2. Zamanlama ve ağ eşikleri

`python3 sweeps/sweep_timing.py` — her nokta çoklu tohumla (ağ taramaları 5,
zamanlama taramaları 3), raporlanan değer **en kötü durum**.

| # | Bozulan yol | Sorunsuz | İlk ihlal | Ne kırılıyor |
|---|---|---|---|---|
| 1 | Güverte → kontrolcü ağ gecikmesi | 18 ms | **24 ms** | watchdog tripi → **uçak durmuyor** |
| 2 | Aynı yolda jitter (taban 2 ms) | ±20 ms | geçti | — |
| 3 | Aynı yolda paket kaybı | %85 | geçti | %85'te 18 watchdog olayı |
| 4 | Kritik olmayan trafikten tıkanıklık (%10 olasılık) | 90 ms | geçti | — |
| 5 | Tam ağ kopması (tork rampası) | 250 ms | **400 ms** | RMS 3.08; 600 ms'de 4.54 g / 1074 kN |
| 6 | Dış çevrim WCET (periyot 1 ms, `skip`) | 4000 µs | geçti | — |
| 7 | Dış çevrim overrun olasılığı (8× patlama) | %100 | geçti | — |
| 8 | Dış çevrim periyodu | 32 ms | geçti | — |
| 9 | Akım çevrimi WCET (periyot 100 µs, `skip`) | 400 µs | **800 µs** | RMS 3.88 |
| 9q | Akım çevrimi WCET (`queue`) | 95 µs | **120 µs** | 8.42 g, 1910 kN, durmuyor |
| 10 | **Akım çevrimi periyodu** (400 Hz bant genişliğinde) | **600 µs** | **1000 µs** | RMS 4.35 — eşik bant genişliğiyle ölçekleniyor, bkz. WI-2 |
| 11 | Dış çevrim → akım çevrimi komut gecikmesi | 4000 µs | geçti | — |
| 12 | Güverte sensör örnekleme hızı | 25 Hz'e kadar | geçti | 50 Hz'de 49 yanlış watchdog tripi |
| 13 | Tork dalgalanması (faz dengesizliği / uzun kablo) | %60 | geçti | %60'ta tepe 3.53 g |
| 14 | PCS kondansatör bankası kaybı | — | **her an** | **uçak durmuyor** |
| 15 | Ağırlık kestirim hatası — düşük tahmin | −2000 kg | **−4000 kg** | RMS 3.18 |
| 15b | Ağırlık kestirim hatası — yüksek tahmin | +8000 kg | geçti | — |
| 17 | Kalıcı gecikme, bozulmuş mod = enkoder kestirimi | 10 ms | 20 ms | yalnızca RMS; uçak her zaman ≤99.2 m'de duruyor |
| 18 | Tam ağ kopması, bozulmuş mod = enkoder kestirimi | **1500 ms** | geçti | — |

### Okuma notları

**Deadline kaçırmak tek başına kötü değil.** Akım çevrimi WCET 95 µs iken
14 870 kaçırma sayıldı ve hiçbir metrik değişmedi. `skip` politikasıyla 400 µs'de
27 407 kaçırmaya rağmen sonuç hâlâ nominal. Kabul kriteri **"sıfır kaçırma"
olarak yazılmamalı**; anlamlı olan etkin periyot ve overrun politikasıdır.

**Dış çevrim ve ağ yolları olağanüstü toleranslı.** Jitter, paket kaybı,
tıkanıklık, overrun, periyot — hiçbiri tek başına kabul ölçütünü kırmıyor.
Hepsi yalnızca **watchdog üzerinden** zarar veriyor (bkz. §1.2).

**Senaryo karşılaştırması** (`python3 run_scenarios.py`, varsayılan politika):

| Senaryo | runout | tepe g | RMS | wd | sonuç |
|---|---|---|---|---|---|
| nominal | 97.7 | 3.29 | 2.19 | 0 | GEÇTİ |
| ağ gecikmesi 10 ms | 97.7 | 3.24 | 2.11 | 0 | GEÇTİ |
| jitter ±5 ms | 97.7 | 3.29 | 2.19 | 0 | GEÇTİ |
| paket kaybı %20 | 97.7 | 3.28 | 2.18 | 0 | GEÇTİ |
| tıkanıklık 30 ms (%10) | 97.7 | 3.29 | 2.19 | 0 | GEÇTİ |
| dış çevrim overrun %20 | 97.7 | 3.29 | 2.19 | 0 | GEÇTİ |
| tork dalgalanması %20 | 97.7 | 3.29 | 2.19 | 0 | GEÇTİ |
| ağ kopması 150 ms | 97.6 | 3.29 | 2.21 | 1 | GEÇTİ |
| **PCS kaybı t=1.2 s** | **durmadı** | 3.29 | 18.85 | 0 | **KALDI** |
| ağırlık hatası +6000 kg | 97.4 | 3.33 | 2.11 | 0 | GEÇTİ |

---

## 3. İş maddeleri

### Görev tablosu (hedef)

| Görev | Periyot | WCET bütçesi | Kritiklik | Deadline kaçırınca | Kaynak |
|---|---|---|---|---|---|
| `inner` (akım kontrolü) | 100 µs | **hedef ≤ 90 µs** (ölçülen sınır değil: `skip` ile 400 µs bile arrest metriklerini bozmuyor, ama akım hatası 1160 A'e çıkıyor) | **sert** | `skip` ile zararsız; `queue` ile felaket | #9, #9q, #10 |
| `outer` (tork komutu) | 1 ms (≤ 20 ms'e gevşetilebilir) | ≤ 900 µs | yumuşak | zararsız | #6, #7, #8 |
| `trajectory` (v_ref) | 2 ms | ≤ 1 ms *(ölçülmedi — tahmin)* | yumuşak | zararsız | ayrı taranmadı |
| `supervisor` (bin, watchdog) | 10 ms | ≤ 5 ms *(ölçülmedi — tahmin)* | yumuşak ama **güvenlik ilgili** | watchdog gecikmesi | ayrı taranmadı |
| güverte sensör yayını | 4–10 ms (100–250 Hz) | — | yumuşak | 25 Hz'e kadar sorunsuz | #12 |

> Bu tablodaki WCET değerleri simülasyonda **girdi**dir, ölçüm değildir.
> Hedef donanımda ölçülecek WCET'in bu bütçelerin altında kaldığı
> gösterilmelidir (bkz. §4).

---

### WI-1 — Her periyodik görev için overrun politikasını tanımla · **kritik**

**Kanıt:** #16a vs #16b — akım çevrimi WCET 120 µs'de `queue` politikası
tepe yavaşlamayı 3.29 g → **8.42 g**, kanca yükünü 804 → **1910 kN** çıkarıyor
ve uçak durmuyor; aynı noktada `skip` politikası nominalden **ayırt edilemez**.

**Yapılacak:**
- Her periyodik görev için overrun davranışı **açıkça** belirtilsin:
  önceki iş bitmemişse yeni serbest bırakma **atlanır** (skip), kuyruğa alınmaz.
- Atlanan serbest bırakmalar sayılsın ve telemetriye verilsin; sayaç
  eşiği aşınca sağlık uyarısı.
- Kabul kriteri **"WCET < periyot"** + **"skip oranı < %X"** şeklinde yazılsın;
  "sıfır deadline kaçırma" kriteri bu mimaride yanıltıcıdır.
- Kuyruk davranışı (klasik "tetiklenen iş mutlaka koşar" yaklaşımı) bu sistemde
  **yasaklanmalı** — en kötü durum sınırsız gecikmedir.

### WI-2 — Akım çevriminin etkin periyodunu sınırla · **kritik**

**Kanıt:** #10 — periyot 600 µs'e kadar sorunsuz, 1000 µs'de KALDI (RMS 4.35).
#16b — `skip` ile WCET 400 µs sorunsuz, 800 µs'de KALDI (RMS 3.88).

Eşik **mutlak değil, akım çevrimi bant genişliğine oranlı**. Periyot × bant
genişliği taraması (hız izleme RMS, `*` = KALDI):

| bant gen. | 200 µs | 400 | 600 | 800 | 1000 | 1500 | 2500 |
|---|---|---|---|---|---|---|---|
| 200 Hz | 2.19 | 2.19 | 2.19 | 2.19 | 2.20 | 2.20 | 13.56* |
| 400 Hz | 2.19 | 2.19 | 2.19 | 2.19 | 4.34* | 7.09* | 8.91* |
| 800 Hz | 2.19 | 2.19 | 3.07* | 4.29* | 5.14* | 6.56* | 6.92* |

Geçiş sınırı her üç bant genişliğinde `T·ω_c ≈ 1.5–2` civarında.
Yani kural: **periyot ≤ 1.5/(2π·f_bw) ≈ 0.24/f_bw**.

**Yapılacak:**
- Kabul kriteri mutlak mikrosaniye değil, **`T·ω_c ≤ 1.5`** olarak yazılsın.
  400 Hz bant genişliğinde bu ≈600 µs demektir.
- Nominal periyot 100 µs seç, **6× marj** bırak (model belirsizliği parametre
  varsayımlarından geliyor).
- Bu görevin kod yolunda: dinamik bellek ayırma yok, kilit/blokaj yok,
  sınırsız döngü yok, çöp toplayıcı yok, sayfa hatası yok.
- Etkin periyot (periyot × (1 + atlama oranı)) çalışma zamanında ölçülsün.

### WI-3 — Güverte ağını emniyet yolundan çıkar: enkoder tabanlı yedek kestirim · **kritik**

**Kanıt:** #17a vs #17b — tork rampalı bozulmuş modda 30 ms ve üzeri kalıcı
gecikmede uçak **hiç durmuyor**; enkoder kestirimiyle aynı koşullarda her zaman
**99.2 m'de duruyor** (runout ve tepe g sınırların içinde, ihlal yalnızca izleme
RMS'inde: 3.18–3.38 vs 3.0).
#18a vs #18b — tam ağ kopmasında tork rampası 400 ms'de kalıyor, 600 ms'de
4.54 g / 1074 kN üretiyor; enkoder kestirimi **1500 ms kesintide bile hiçbir
ölçütü ihlal etmiyor** (98.9 m · 3.29 g · RMS 2.78).

**Yapılacak:**
- Bozulmuş modda konum/hız, güverte ağından bağımsız olarak **yerel tambur
  enkoderinden** kestirilsin (`s_d` tersine çevrilerek) ve çevrim kapalı tutulsun.
- Referans (`v_ref`) de aynı kestirimden üretilsin; yalnızca geri beslemeyi
  değiştirip referansı güverte verisine bırakmak işe yaramaz (ilk denemede
  kopma sırasında `v_ref` donduğu için enkoder modu daha kötü sonuç vermişti).
- Kestirimin sistematik hatası (halat esnemesi nedeniyle tambur tarafı hep
  geride) modellenip telafi edilsin; kalan hata RMS'te görülüyor.
- "Motor torkunu sıfıra rampala" davranışı **güvenli durum değildir** ve
  yalnızca enkoder de güvenilmezse son çare olarak kullanılmalıdır.
- Emniyet analizi, güverte ağını **emniyet dışı** (non-safety) sınıfa
  koyabilecek şekilde yeniden yazılsın.

### WI-4 — Watchdog eşiğini en kötü durum gecikmesinden türet · **yüksek**

**Kanıt:** watchdog × gecikme ızgarası tam köşegen; watchdog 160 ms iken
120 ms saf gecikme zararsız. #1 — 20 ms watchdog ile gecikme eşiği 24 ms.
#12 — 50 Hz örneklemede 20 ms eşik 49 yanlış trip üretiyor.

**Yapılacak:**
- `watchdog_timeout ≥ 2 × (taban gecikme + jitter + tıkanıklık patlaması +
  örnekleme periyodu)` ve ayrıca `≥ 3 × örnekleme periyodu`.
  Bu toplam **gerçek veri yolunda ölçülmeli**, tahmin edilmemeli.
- "Küçük watchdog güvenlidir" sezgisi burada **yanlış**: WI-3 uygulanana kadar
  yanlış trip, gerçek arızadan pahalıdır.
- Ara durum: `bayat ama kullanılabilir` (1–3 örnek kayıp) ile `geçersiz`
  ayrı ele alınsın.

### WI-5 — Bozulmuş mod ve geri dönüş davranışını tanımla ve test et · **yüksek**

**Kanıt:** #5 / #18a — 250 ms kopmaya kadar geçiyor; 400 ms'de hız izleme RMS
3.08 ile (limit 3.0) kalıyor, 600 ms'de tepe yavaşlama 4.54 g ve kanca yükü
1074 kN'a çıkıyor. #3 — %85 paket kaybında 18 watchdog olayı yaşanıyor ama
sistem geçiyor.

**Yapılacak:**
- Tutma süresi (`watchdog_hold`) ve rampa süresi tasarım parametresidir;
  belgelenmeli ve test edilmeli (şu an 50 ms / 50 ms).
- Geri dönüş yolu tanımlı olsun: veri döndüğünde integratör sıfırlanacak mı,
  hangi koşulda normal moda dönülür, bir arrest içinde kaç kez girilebilir?
- Her bozulmuş mod girişi/çıkışı zaman damgalı loglansın.

### WI-6 — Kontrol döngüsünü kritik olmayan trafikten ayır · **yüksek**

**Kanıt:** #2, #3, #4 — çevrimin kendisi ±20 ms jitter'a, %85 paket kaybına ve
90 ms tıkanıklık patlamalarına dayanıyor. **Ama** bunların hepsi watchdog'u
besliyor: 20 ms watchdog'lu sistemde 90 ms'lik bir patlama tripe yol açar.

**Yapılacak:**
- Ayrımın gerekçesi "çevrim kararsızlaşır" değil, **"en kötü durum
  sınırlandırılabilsin ki watchdog gerçek arızayı yakalayacak kadar sıkı
  ayarlanabilsin"** olarak yazılsın.
- Kontrol trafiği ayrı VLAN/port/zamanlama sınıfında; telemetri, bakım ve video
  aynı yolu paylaşmasın.
- En kötü durum gecikmesi ölçülüp WI-4'e girdi olarak yayımlansın.

### WI-7 — PCS tek nokta arızası: yazılım kurtaramaz, erken tespit etmeli · **kritik**

**Kanıt:** #14 — kondansatör bankası kaybı **hangi anda olursa olsun** uçak
6 s içinde durmuyor (t_max = 20 s ile 409 m ve hâlâ hareket hâlinde).
Senaryo tablosunda tek KALDI satırı budur.

**Yapılacak:**
- Bu bir **mimari** sorundur; yazılımla telafi edilemez. Motor torku kaybolunca
  geriye yalnızca su türbini kalıyor ve `T ∝ ω²` olduğu için düşük hızda
  sabit itkiyi yenemiyor.
- Yazılım tarafı: bara gerilimi/akımı üzerinden hızlı tespit, anında güvenli
  komut, olay kaydı ve **iniş öncesi hazırlık kontrolü** — bozulmuş PCS ile
  iniş kabul edilmemeli.
- Kaynaktaki "bir kondansatör bankası arızası 3 motoru 7 gün devre dışı
  bıraktı" durumu bu maddenin filo seviyesindeki karşılığıdır.

### WI-8 — Ağırlık kestiriminde hata yönü asimetrik · **orta**

**Kanıt:** #15 — düşük tahmin tarafında −4000 kg'da ihlal (RMS 3.18);
yüksek tahmin tarafında +8000 kg'da bile sorun yok.

**Yapılacak:**
- Ağırlık kestirimi **yukarı yönlü taraflı** (conservative) olsun.
- Uçak tipi + yakıt durumu ile çapraz kontrol; temas sonrası ilk yavaşlamadan
  çevrimiçi kestirim ve ±2000 kg sapmada uyarı.

### WI-9 — İleri besleme model hatası sessizce kötüleşiyor · **orta**

**Kanıt:** `sweeps/sweep_watchdog.py` B bölümü — su türbini katsayısı
kestiriminde ±%10 sorunsuz; −%30'da RMS 3.24, −%80'de RMS 4.57 ve tepe 3.69 g.
**Runout neredeyse hiç değişmiyor** — metriklerin çoğu normal görünürken
izleme kalitesi bozuluyor.

**Yapılacak:**
- Ölçülen mil torku ile model tahmini sürekli karşılaştırılsın; sapma alarmı
  kurulsun. Aksi halde bozulma hiçbir sinyal üretmeden ilerler.
- Su türbini karakteristiği sıcaklık/su seviyesine bağlı değişiyorsa sabit
  katsayı yetmez; **çalışma zamanı kestirimi** gerekir.

### WI-10 — Tork dalgalanması kontrol bütçesinde değil, makine sağlığında · **orta**

**Kanıt:** #13 — %60 tepe tork dalgalanmasında runout değişmiyor (97.7 m),
tepe yavaşlama 3.29 → 3.53 g.

**Yapılacak:**
- Faz dengesizliği / uzun güç kablosu kaynaklı dalgalanma arrest sonucunu
  bozmuyor; kontrol çevrimi bütçesinde **öncelik verilmesin**.
- Yine de izlensin: termal yük, yatak/dişli yorulması ve akustik imza için
  ayrı bir sağlık izleme görevi (düşük periyot, kritik olmayan ağda).

### WI-11 — Sensör hızı ile watchdog birbirine bağlı · **orta**

**Kanıt:** #12 — 25 Hz'e kadar kabul ölçütleri sağlanıyor, ama 50 Hz'de 49,
25 Hz'de 69 watchdog tripi sayılıyor (20 ms eşikle).

**Yapılacak:**
- 100–250 Hz yeterli; daha hızlı örnekleme performans getirmiyor.
- Örnekleme periyodu ve watchdog eşiği **tek bir tasarım kararı** olarak ele
  alınsın, ayrı ayrı değil.

### WI-12 — Zarf köşeleri yazılımla kapatılamıyor · **orta**

**Kanıt:** bin ızgarası (`out/bin_grid.csv`) — 16 kombinasyondan **8'i** kabul
ölçütlerini sağlamıyor:

```
   kutle   hiz     bin  runout     g  hookkN    RMS  turb%  sonuc
   12000    52  (0, 0)    67.6  3.74     534   3.84   59.6  KALDI
   12000    76  (0, 3)   102.3  7.49     975   6.90  104.8  KALDI
   16000    68  (1, 2)    97.9  4.73     836   3.46   90.8  KALDI
   20000    68  (2, 2)    97.8  3.92     864   2.50   77.1  GECTI
   24000    76  (3, 3)   105.3  4.30    1105   5.39   69.8  KALDI
```

İki ayrı neden:
1. **Hafif uçak (12 t):** tepe yük, temas anında tamburun 0'dan ~130 rad/s'ye
   hızlanması için gereken `J·dω/dt` torkundan geliyor ve bu **uçak ağırlığından
   bağımsız**. Aynı kuvvet hafif uçakta çok daha yüksek g demek.
2. **Yüksek hız (76 m/s):** 103 m runout sınırı ile ≤4.5 g hedefi aynı anda
   sağlanamıyor. *(Kaba hesap — koşu değil: `v²/2a` ile ≈115 m gerekiyor.)*

**Yapılacak:**
- Bu bir **boyutlandırma** sorunudur, kazanç çizelgeleme ile çözülmez. Çözüm ya
  dönen atalet / sönümleyici tarafında ya da limitlerin revizyonundadır.
- Yazılım iş maddesi: kazanç bin tablosu **formülle üretilmesin**, her bin ayrı
  tasarlanıp doğrulansın; sistem **zarf dışı** bir engajmanı (ağırlık × hız)
  tanıyıp reddedebilsin.

### WI-13 — Değişken şok sönümleme bu parametre bölgesinde etkisiz · **düşük**

**Kanıt:** `out/shock_study.csv` — çizelgeli vs sabit sönüm, 12 t'de
736 kN / 5.45 g vs 742 kN / 5.50 g; diğer ağırlıklarda fark < %1.

**Olası neden** *(analiz, koşu değil)*: temas geçişinin frekansında
sönümleyicinin empedansı (`c·ω`) yay katsayısını bastırıyor; sönümleyici
neredeyse **rijit** davranıyor. Ayrıca tepe yük esas olarak `J·dω/dt`
teriminden geliyor (bkz. WI-12).

**Yapılacak:**
- Değişken sönümlemenin amacı ilk çarpma sıçramasını sınırlamaksa, bu parametre
  bölgesinde amacına hizmet etmiyor: model/parametreler gözden geçirilsin.
  Aksi halde çizelgeleme mantığı **ölü koddur** ve kaldırılmalıdır.

### WI-14 — Determinizm ve tekrar üretilebilirlik · **yüksek**

**Kanıt:** Model öz-kontrolü gerçek bir hata yakaladı: tohumlama
`hash((seed, name))` ile yapılıyordu; Python'da string hash'i **süreçten sürece
değişir**, dolayısıyla "deterministik" koşular aslında tekrar üretilemiyordu.
Aynı süreç içindeki test bunu göremiyordu.

**Yapılacak:**
- Gerçek zamanlı kodda kontrol yolunda hash sırasına bağlı iterasyon olmasın.
- Her test **ayrı süreçte ve ayrı makinede** aynı sonucu versin; bu bir kabul
  kriteri olarak CI'ya girsin.
- Loglama zaman damgalı ve deterministik olsun; "yeniden üretilemeyen arıza"
  savunma sistemlerinde kabul edilemez.

---

## 4. Simülasyonun cevaplayamadıkları

Bu maddeler simülasyondan **türetilemez**; hedef donanımda ölçülmeli veya
mimari kararla çözülmelidir. Modelde CPU çekişmesi yoktur (görevler birbirinin
işlemcisini çalmaz), RTOS/işlemci/veri yolu modellenmemiştir.

1. **WCET ölçümü.** Modelde yürütme süreleri *girdi*dir. Gerçek WCET hedef
   işlemcide, en kötü giriş verisiyle, önbellek ve kesme etkileri dahil
   ölçülmelidir. Buradaki eşikler "ölçülen WCET şu değerin altında kalmalı"
   şeklinde kullanılır.
2. **RTOS, işlemci ve veri yolu seçimi.** Kaynak materyal AAG'nin kullandığı
   RTOS'u, donanım platformunu ve haberleşme protokolünü belirtmiyor; bu
   simülasyon da belirtemez. Seçim, buradaki periyot/jitter bütçelerinin
   karşılanabilirliğine göre yapılmalı.
3. **Görevler arası CPU çekişmesi ve öncelik ataması.** Modelde her görev kendi
   zaman çizelgesinde bağımsız koşuyor. Öncelik ters çevrilmesi, kesme yükü ve
   çekirdek paylaşımı gerçek hedefte analiz edilmeli (RMA / response-time).
4. **Paylaşımlı PCS'in birden fazla motoru etkilemesi.** Model tek bir yakalama
   motoru içeriyor; filo seviyesindeki kullanılabilirlik etkisini göstermez.
5. **İtki varsayımı.** "Uçak durmuyor" sonuçları, arrest boyunca itkinin tam
   gazda kaldığı varsayımına dayanır. Pilot prosedürü farklıysa bu sonuçlar
   değişir — ama bozulmuş modun **pasif su türbinine güvenemeyeceği** sonucu
   değişmez.
6. **Halat/pandant yorulması, gemi hareketi, pilot davranışı, aerodinamik.**
   Kapsam dışı.
