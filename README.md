# DPP Hazırlık Platformu — Kurumsal Sürüm 3.0

AB'ye ihracat yapan **tüm sektörlerdeki** firmalar için Dijital Ürün Pasaportu (DPP) hazırlık, uyum yönetimi ve pasaport yayım platformu.

> Bu platform bir **hazırlık ve ön kontrol** aracıdır. Gümrük, piyasa gözetimi veya onaylanmış kuruluş kararı yerine geçmez.
> Mevzuat hükümleri ve tarihleri resmi kaynaklardan doğrulanmalıdır.

## Neler var?

| Alan | Özellik |
| --- | --- |
| Giriş ve güvenlik | Kullanıcı girişi, scrypt ile şifrelenmiş parolalar, 5 hatalı denemede 15 dk kilit, 8 saat oturum süresi, ilk girişte zorunlu parola değişikliği |
| Çok firmalı yapı | Her firmanın verisi ayrıdır; platform yöneticisi tüm firmaları yönetir |
| Roller | Platform yöneticisi, Firma yöneticisi, Veri sorumlusu, Bağımsız doğrulayıcı, İzleyici. **Görevler ayrılığı:** veriyi giren doğrulayamaz, doğrulayan veriyi değiştiremez |
| Ürün kartı | Kimlik, menşe, kimyasallar, çevre, sektörel alanlar (CBAM, EPREL, IMDS, batarya); malzeme satırları, tedarik zinciri aşamaları, partiler |
| İki ayrı gösterge | **Yasal uyum** (bugün yürürlükteki şartlar) ve **DPP hazırlık skoru** (ileride zorunlu olacak veriler) |
| Yaklaşan yükümlülükler | EUDR (30.12.2026), Batarya pasaportu (18.02.2027) gibi tarihi gelmemiş şartlar ayrı izlenir, tarihi gelince kendiliğinden yasal uyuma geçer |
| Kural seti | 35 kural, 14 sektör. Her kuralın dayanağı, EUR-Lex bağlantısı ve adım adım çözüm reçetesi var. Sürümlüdür; her değerlendirme hangi kural setiyle yapıldığını kaydeder |
| Belge kasası | Dosya yükleme (SHA-256 parmak izi), sabit belge türü listesi, ürün/tesis/tedarikçi/firma geneline bağlama, 30/60 gün süre uyarısı |
| Bağımsız doğrulama | Belgelerin doğrulanması / reddi, ürün doğrulama beyanı. Veri sonradan değişirse pasaportta "doğrulamadan sonra güncellendi" notu çıkar |
| Pasaport | Sürümlü yayım, kritik eksikte yayım engeli, değişmeyen QR adresi, Kamu / Alıcı (B2B) / Otorite görünümleri, geri çekme, JSON-LD, PDF pasaport sayfası |
| Herkese açık sayfa | QR okutulunca giriş gerektirmeden açılan pasaport sayfası; alıcı erişim koduyla B2B görünümü; içerik bütünlük kontrolü |
| Tedarikçi portalı | Tedarikçiye hesap açmadan tek kullanımlık bağlantı; SVHC beyanı, malzeme bileşimi, menşe, karbon ve belge toplama; onayla ürüne aktarma |
| Excel | Şablon, önizlemeli toplu içe aktarım (hata varsa hiçbir şey yazılmaz), tüm veriyi dışa aktarma. Önceki sürümlerin dosyaları da okunur |
| Raporlar | Kapaklı, Roma rakamlı bölümlü PDF "DPP Hazırlık ve Ön Kontrol Raporu"; ayrıntılı Excel raporu |
| Asistan | Yerel mod (veri dışarı gitmez) veya onaylı ve maskeli Gemini modu |
| Denetim izi | Tüm işlemler zincirleme özetle kaydedilir; sonradan değiştirilen kayıt tespit edilir |

## Dosya yapısı

```
app.py                  Giriş noktası (yönlendirme, menü)
dpp/                    Çekirdek (Streamlit'ten bağımsız; ileride FastAPI'ye taşınabilir)
  db.py                 SQLite / PostgreSQL katmanı ve şema
  security.py           Parola, roller, yetkiler
  audit.py              Zincirleme denetim izi
  catalog.py            Sektör ve belge türü katalogları
  rules.py              Kural seti ve değerlendirme motoru
  repo.py               Veri erişimi (firma ayrımlı)
  evaluation.py         Değerlendirme kayıtları, doğrulama beyanları
  passport.py           Pasaport içeriği, yayım, erişim seviyeleri
  suppliers.py          Tedarikçi veri talepleri
  importer.py           Excel içe / dışa aktarım
  reports.py            PDF ve Excel raporlar, QR
  assistant.py          Uyum asistanı
  regulations.py        Mevzuat bilgi tabanı
  demo.py               Demo firma verisi
ui/                     Ekranlar
assets/fonts/           PDF için Türkçe karakter destekli yazı tipi (DejaVu, serbest lisans)
tests/                  Birim testleri
.streamlit/             Tema ve örnek gizli ayar dosyası
```

## Kurulum (GitHub + Streamlit Community Cloud)

### 1. Kalıcı veritabanı (zorunlu önerilir)

Streamlit Community Cloud yeniden başladığında yerel dosyalar silinir. Verilerin kalıcı olması için ücretsiz bir PostgreSQL açın:

1. [neon.tech](https://neon.tech) veya [supabase.com](https://supabase.com) üzerinde hesap açın, yeni bir proje / veritabanı oluşturun.
   Bölge olarak **Frankfurt (eu-central)** seçin (veriler AB'de kalır).
2. Bağlantı adresini kopyalayın. Şuna benzer: `postgresql://kullanici:parola@sunucu/veritabani?sslmode=require`
3. Tabloları program ilk açılışta kendisi oluşturur.

### 2. Dosyaları GitHub'a yükleyin

Mevcut `dpp-portali` deposunda eski dosyaları (`app.py`, `dpp_core.py`, `requirements.txt`, `README.md`) silin, bu klasördeki
**her şeyi** klasör yapısını koruyarak yükleyin (`dpp/`, `ui/`, `assets/`, `.streamlit/config.toml` dahil).
GitHub web arayüzünde: **Add file → Upload files** → klasörleri sürükleyip bırakın → **Commit changes**.

> `.streamlit/secrets.toml` adında gerçek bilgiler içeren bir dosyayı **asla** GitHub'a yüklemeyin.

### 3. Streamlit gizli ayarları

Streamlit'te uygulamanızın sağ altındaki **Manage app → ⋮ → Settings → Secrets** bölümüne şunu yazın:

```toml
KURULUM_ANAHTARI = "uzun-ve-tahmin-edilemez-bir-metin"
APP_URL = "https://uygulama-adiniz.streamlit.app"
DATABASE_URL = "postgresql://...neon.tech/...?sslmode=require"
PLATFORM_UNVANI = "DPP Hazırlık Platformu"
# GEMINI_API_KEY = "..."   (isteğe bağlı)
```

Kaydedin; uygulama yeniden başlar (ilk açılışta paket kurulumu 2–3 dakika sürebilir).

### 4. İlk kullanım

1. Uygulama açılınca **İlk kurulum** ekranı gelir. Kurulum anahtarını ve kendi bilgilerinizi girerek **platform yöneticisi** hesabını oluşturun.
2. **Firmalar** ekranından müşteri firmayı oluşturun (veya denemek için **Demo firma oluştur**).
3. **Kullanıcılar** ekranından firmaya bir **Firma yöneticisi** ekleyin. Ekranda gösterilen geçici parolayı kendisine iletin.
4. Firma kullanıcıları **Excel Aktarım** ile verilerini yükler; eksikleri **Eksikler ve Çözüm** ekranından giderir.
5. Bağımsız doğrulayıcı belgeleri ve ürünleri doğrular; firma yöneticisi pasaportu yayımlar.
6. **Pasaportlar** ekranından QR kodu ve PDF etiketi indirilir. QR okutulunca herkese açık pasaport sayfası açılır.

## Kendi bilgisayarında çalıştırma

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # içini düzenleyin, DATABASE_URL satırını silerseniz SQLite kullanılır
streamlit run app.py
python -m pytest -q                                           # testler
```

## Hazırlık skoru

```
DPP hazırlık = 100 × (karşılanan hazırlık kurallarının ağırlıkları) / (uygulanan hazırlık kurallarının ağırlıkları)
```

| Durum | Anlamı |
| --- | --- |
| 🔴 Kritik eksik | Yürürlükteki mevzuatta kritik eksik var; pasaport yayımlanamaz |
| 🟠 Yasal eksik | Kritik olmayan yasal eksik var |
| 🟡 Hazırlık sürüyor | Yasal olarak uygun, DPP hazırlığı %80'in altında |
| 🟢 Hazır | Yasal olarak uygun, DPP hazırlığı %80 ve üzeri |

Kural ağırlıkları ve aktifliği platform yöneticisi tarafından **Kural Seti** ekranından değiştirilebilir. Kuralların kendisi
`dpp/rules.py` dosyasındadır.

## Bilinen sınırlar

- Belge içerikleri program tarafından okunmaz; türü, süresi ve doğrulama durumu izlenir.
- JSON-LD yapısı EN 18216/18223 yaklaşımına göre hazırlanmış bir **taslaktır**; resmi şema her ürün grubu için yetki
  tüzüğüyle belirlenecektir. AB DPP Registry'ye otomatik kayıt bu sürümde yoktur.
- E-posta gönderimi yoktur; tedarikçi bağlantısı ve geçici parolalar kullanıcı tarafından iletilir.
- Streamlit tek sunuculu çalışır; yüzlerce eşzamanlı kullanıcı için FastAPI + ayrı ön yüz mimarisine geçilmelidir
  (çekirdek `dpp/` paketi buna hazırdır).
