# DPP Hazırlık Platformu

AB'ye ihracat yapan **tüm sektörlerdeki** firmalar için Dijital Ürün Pasaportu (DPP) hazırlık ve ön kontrol aracı.
ESPR (AB) 2024/1781 ve ilgili ürün mevzuatına (GPSR, REACH, CBAM, Batarya Tüzüğü, RoHS/WEEE, EUDR, yapı malzemeleri vb.)
göre ürün verisini kontrol eder, eksikleri gerekçesi ve çözüm adımlarıyla gösterir, pasaport taslağı üretir.

> Bu program bir **hazırlık ve ön kontrol** aracıdır. Gümrük, piyasa gözetimi veya onaylanmış kuruluş kararı yerine
> geçmez. Mevzuat hükümleri ve tarihleri resmi kaynaklardan doğrulanmalıdır.

## Neler yapar?

| Sekme | İşlev |
| --- | --- |
| Genel Bakış | Hazır / Eksikleri var / Yüksek risk dağılımı, sektör grafiği, en sık eksikler, Excel ön kontrol raporu |
| Eksikler ve Çözüm | Her ürün için eksik kurallar, mevzuat dayanağı ve adım adım yapılacaklar |
| Pasaport Taslağı | GS1 Digital Link QR, Kamu / Alıcı / Otorite görünümleri, JSON-LD çıktısı ve içerik özeti (SHA-256) |
| Belge Kasası | Sertifika, beyan ve test raporlarının sınıflandırılması; süresi dolan ve 30/60 gün içinde dolacak belgeler |
| Veri Düzenleme | Tabloları ekranda düzeltme, değişikliklerin denetim izine yazılması, düzenlenmiş veriyi Excel olarak indirme |
| Kural Seti | Tüm kuralların seviye, ağırlık, kapsam ve dayanakları (skor tamamen şeffaf) |
| Uyum Asistanı | Yerel (veri dışarı gitmez) veya isteğe bağlı Gemini destekli soru-cevap |
| Mevzuat Rehberi | Sektörlere göre mevzuat ve tarih özeti |
| Denetim İzi | Yükleme, düzenleme, indirme ve yapay zekâ sorgularının kaydı |

**Kapsanan sektörler:** Tekstil ve hazır giyim, deri ve ayakkabı, elektrik-elektronik, beyaz eşya, batarya, demir-çelik,
alüminyum, mobilya, otomotiv yan sanayi, lastik, oyuncak, deterjan ve kimyasal, yapı malzemeleri ve diğerleri.

## Dosyalar

| Dosya | Açıklama |
| --- | --- |
| `app.py` | Streamlit arayüzü |
| `dpp_core.py` | Kural motoru, doğrulamalar, belge kasası, pasaport ve rapor üretimi |
| `requirements.txt` | Gerekli Python paketleri |
| `ornek_ihracat_verisi.xlsx` | 8 farklı sektörden örnek veri (bilerek eksikler içerir) |
| `dpp_veri_sablonu.xlsx` | Boş yükleme şablonu ve sütun açıklamaları |
| `.streamlit/secrets.toml.example` | Gemini anahtarı için örnek ayar dosyası |

`app.py` ile `dpp_core.py` deponun **ana klasöründe yan yana** durmalıdır.

## Excel dosyasının yapısı

Bir dosyada üç sayfa olabilir (yalnızca `Urunler` zorunludur):

- **Urunler** — her satır bir ürün. Zorunlu sütunlar: `Urun_Kodu`, `Urun_Adi`, `Sektor`.
- **Belgeler** — her satır bir belge: `Urun_Kodu` (firmanın tüm ürünleri için `*`), `Belge_Turu`, `Belge_No`, `Duzenleyen`, `Gecerlilik_Bitis`.
- **Tedarik_Zinciri** — her satır bir üretim aşaması: `Urun_Kodu`, `Asama_Sira`, `Asama`, `Tedarikci`, `Ulke`.

Tüm sütunların açıklaması uygulamadaki **Boş şablonu indir** düğmesiyle gelen dosyanın `Aciklama` sayfasındadır.
Önceki sürümün tek sayfalık dosyaları (`Cevre_Sertifikasi`, `Sertifika_Bitis_Tarihi` sütunlu) da okunur ve belge
kasasına aktarılır.

İpucu: `GTIN` ve `GTIP` sütunlarını Excel'de **metin** biçiminde tutun; aksi halde baştaki sıfırlar kaybolur.

## Hazırlık skoru nasıl hesaplanır?

Her ürüne yalnızca sektörüne ve özelliklerine uygun kurallar uygulanır:

```
Hazırlık skoru = 100 × (karşılanan kuralların ağırlıkları) / (uygulanan kuralların ağırlıkları)
```

- **Yüksek risk:** en az bir *Kritik* kural karşılanmıyor (skordan bağımsız)
- **Eksikleri var:** kritik eksik yok, skor 85'in altında
- **Hazır:** kritik eksik yok, skor 85 ve üzeri

Kurallar, ağırlıklar ve çözüm adımları `dpp_core.py` içindeki `KURALLAR` listesinden değiştirilebilir.

## Streamlit Community Cloud'a yükleme (GitHub üzerinden)

1. GitHub'daki `dpp-portali` deposunda **Add file → Upload files** ile bu klasördeki dosyaları yükleyin
   (`app.py`, `dpp_core.py`, `requirements.txt`, `README.md`, `.gitignore`, Excel dosyaları). Aynı adlı eski dosyaların
   üzerine yazılır. **Commit changes** deyin.
2. `.streamlit/secrets.toml.example` dosyasını yüklemek zorunlu değildir; **gerçek anahtar içeren `secrets.toml`
   dosyasını asla GitHub'a yüklemeyin.**
3. Streamlit uygulamanız depodaki değişikliği görüp kendiliğinden yeniden başlar. Başlamazsa uygulama sayfasında sağ
   alttaki **Manage app → ⋮ → Reboot app** deyin.
4. Paket kurulumu ilk açılışta 1–2 dakika sürebilir.

### Gemini asistanını açmak (isteğe bağlı)

1. Google AI Studio'dan bir API anahtarı alın.
2. Streamlit'te **Manage app → Settings → Secrets** bölümüne şunu yazıp kaydedin:
   ```toml
   GEMINI_API_KEY = "anahtarınız"
   ```
3. Uyum Asistanı sekmesinde **Yapay zekâ (Gemini) ile yanıtla** anahtarını açın ve veri gönderim onayını işaretleyin.

Gemini'ye ham Excel verisi değil, değerlendirme **özeti** gönderilir; ürün kodları ve adları varsayılan olarak
maskelenir. Anahtar girilmezse asistan yerel modda çalışır ve hiçbir veri dışarı gönderilmez.

## Kendi bilgisayarında çalıştırma

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Sınırlamalar ve sonraki adımlar

- Veriler ve denetim izi yalnızca oturum boyunca tutulur; kalıcılık için **Düzenlenmiş veriyi indir** düğmesini kullanın.
- Belgelerin içeriği doğrulanmaz; türü ve geçerlilik tarihi kontrol edilir.
- JSON-LD çıktısı EN 18216/18223 yaklaşımına göre düzenlenmiş bir **taslaktır**; resmi veri şeması her ürün grubu
  için yetki tüzüğüyle belirlenecektir.
- Planlanan sonraki aşama: kullanıcı girişi, kalıcı veritabanı (PostgreSQL), tedarikçi portalı, EN 18222 uyumlu API ve
  AB DPP Registry test ortamı bağlantısı.
