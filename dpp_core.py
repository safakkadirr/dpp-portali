"""
dpp_core.py — DPP Hazırlık Platformu çekirdek modülü

Arayüzden (Streamlit) bağımsızdır. Burada:
  - Excel verisinin okunması ve sütun adlarının standartlaştırılması
  - Eski (tek sayfalı) dosya formatının yeni yapıya dönüştürülmesi
  - GTIN, GTİP, malzeme bileşimi doğrulamaları
  - Belge kasası (sertifika / beyan / test raporu sınıflandırması ve geçerlilik)
  - Şeffaf kural motoru ve hazırlık skoru
  - Pasaport taslağı, GS1 Digital Link ve JSON-LD çıktısı
  - Excel rapor ve boş şablon üretimi
yer alır.

ÖNEMLİ: Bu modüldeki kurallar bir HAZIRLIK ve ÖN KONTROL aracıdır. Gümrük,
piyasa gözetimi veya onaylanmış kuruluş kararı yerine geçmez. Mevzuat
hükümleri ve tarihleri resmi kaynaklardan doğrulanmalıdır.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable, Optional
from urllib.parse import quote

import pandas as pd

SURUM = "2.0.0"
MEVZUAT_GOZDEN_GECIRME = "Kasım 2026"

# ---------------------------------------------------------------------------
# 1. Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------

_TR_MAP = str.maketrans("çğıöşüÇĞİÖŞÜâîû", "cgiosucgiosuaiu")
_BOS_DEGERLER = {"", "nan", "none", "null", "yok", "-", "—", "n/a", "na", "nat", "belirtilmemis"}


def tr_norm(deger) -> str:
    """Türkçe karakterleri sadeleştirip küçük harfe çevirir (eşleştirme için)."""
    s = "" if deger is None else str(deger)
    s = s.replace("İ", "i").replace("I", "ı")
    s = s.lower().translate(_TR_MAP).replace("̇", "")
    return s.strip()


def bos_mu(deger, yok_bos: bool = True) -> bool:
    """Boş değer kontrolü. yok_bos=False ise 'Yok' anlamlı bir cevap sayılır (ör. SVHC beyanı)."""
    if deger is None:
        return True
    try:
        if pd.isna(deger):
            return True
    except (TypeError, ValueError):
        pass
    n = tr_norm(deger)
    if not yok_bos and n == "yok":
        return False
    return n in _BOS_DEGERLER


def metin(deger, varsayilan: str = "", yok_bos: bool = True) -> str:
    if bos_mu(deger, yok_bos):
        return varsayilan
    if isinstance(deger, float) and deger.is_integer():
        return str(int(deger))
    if isinstance(deger, (pd.Timestamp, datetime)):
        return deger.strftime("%Y-%m-%d")
    return str(deger).strip()


def sayi(deger) -> Optional[float]:
    if bos_mu(deger):
        return None
    if isinstance(deger, (int, float)):
        return float(deger)
    s = str(deger).replace("%", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def tarih(deger) -> Optional[date]:
    if bos_mu(deger):
        return None
    try:
        ts = pd.to_datetime(deger, errors="coerce", dayfirst=isinstance(deger, str) and "." in deger)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    return ts.date()


def evet_mi(deger) -> Optional[bool]:
    n = tr_norm(deger)
    if n in {"evet", "e", "yes", "y", "true", "1", "var"}:
        return True
    if n in {"hayir", "h", "no", "n", "false", "0"}:
        return False
    return None


# ---------------------------------------------------------------------------
# 2. GTIN / GTİP / malzeme doğrulama
# ---------------------------------------------------------------------------

def gtin_temizle(deger) -> str:
    s = metin(deger)
    return re.sub(r"\D", "", s)


def gtin_kontrol_hanesi(govde: str) -> int:
    """Kontrol hanesi hariç rakamlardan GS1 kontrol hanesini hesaplar."""
    toplam = 0
    for i, rakam in enumerate(reversed(govde)):
        toplam += int(rakam) * (3 if i % 2 == 0 else 1)
    return (10 - toplam % 10) % 10


def gtin_dogrula(deger) -> tuple[bool, str]:
    g = gtin_temizle(deger)
    if not g:
        return False, "GTIN girilmemiş"
    if len(g) not in (8, 12, 13, 14):
        return False, f"GTIN {len(g)} hane; 8, 12, 13 veya 14 hane olmalı"
    if len(set(g)) == 1:
        return False, "GTIN tek rakamın tekrarından oluşuyor (örnek/yer tutucu değer)"
    if g in {"0123456789012", "1234567890123", "01234567890128"}:
        return False, "GTIN örnek/yer tutucu bir değer"
    beklenen = gtin_kontrol_hanesi(g[:-1])
    if int(g[-1]) != beklenen:
        return False, f"GTIN kontrol hanesi hatalı (son hane {beklenen} olmalı)"
    return True, "GTIN geçerli"


def gtin14(deger) -> str:
    g = gtin_temizle(deger)
    return g.zfill(14) if g else ""


def gtip_dogrula(deger) -> tuple[bool, str]:
    g = re.sub(r"\D", "", metin(deger))
    if not g:
        return False, "GTİP kodu girilmemiş"
    if len(g) < 6:
        return False, f"GTİP kodu {len(g)} hane; en az 6 hane (HS) olmalı"
    return True, "GTİP kodu biçimi uygun"


def malzeme_ayristir(deger) -> tuple[list[tuple[str, float]], float]:
    """'Pamuk:95;Elastan:5' veya '%95 Pamuk, %5 Elastan' biçimlerini okur."""
    s = metin(deger)
    if not s:
        return [], 0.0
    parcalar = [p for p in re.split(r"[;,\n/]+", s) if p.strip()]
    sonuc = []
    for p in parcalar:
        m = re.search(r"(\d+(?:[.,]\d+)?)", p)
        if not m:
            continue
        oran = float(m.group(1).replace(",", "."))
        ad = (p[: m.start()] + p[m.end():]).replace("%", "").replace(":", "").strip(" -=")
        sonuc.append((ad or "Belirtilmemiş", oran))
    return sonuc, round(sum(o for _, o in sonuc), 2)


# ---------------------------------------------------------------------------
# 3. Sektör kataloğu
# ---------------------------------------------------------------------------

@dataclass
class Sektor:
    kod: str
    ad: str
    anahtarlar: list[str]
    tuketici_varsayilan: bool


SEKTORLER: list[Sektor] = [
    Sektor("beyaz_esya", "Beyaz Eşya ve Ev Aletleri", ["beyaz esya", "ev aleti", "klima", "buzdolabi", "camasir"], True),
    Sektor("batarya", "Batarya ve Akü", ["batarya", "aku", "pil", "battery"], False),
    Sektor("elektronik", "Elektrik ve Elektronik", ["elektronik", "elektrik", "eee", "aydinlatma", "kablo"], True),
    Sektor("tekstil", "Tekstil ve Hazır Giyim", ["tekstil", "giyim", "konfeksiyon", "kumas", "iplik", "ev tekstili", "hali"], True),
    Sektor("deri_ayakkabi", "Deri ve Ayakkabı", ["ayakkabi", "deri", "canta"], True),
    Sektor("demir_celik", "Demir-Çelik", ["demir", "celik", "steel", "profil", "boru", "inşaat demiri"], False),
    Sektor("aluminyum", "Alüminyum", ["aluminyum", "aluminium", "aluminum"], False),
    Sektor("mobilya", "Mobilya ve Şilte", ["mobilya", "silte", "yatak", "kanepe", "ahsap urun"], True),
    Sektor("otomotiv", "Otomotiv Yan Sanayi", ["otomotiv", "yan sanayi", "arac parca", "oto"], False),
    Sektor("lastik", "Lastik", ["lastik", "tyre", "tire"], True),
    Sektor("oyuncak", "Oyuncak", ["oyuncak", "toy"], True),
    Sektor("deterjan", "Deterjan ve Temizlik Ürünleri", ["deterjan", "temizlik", "kimyasal"], True),
    Sektor("insaat", "Yapı Malzemeleri", ["insaat", "yapi malzeme", "cimento", "seramik", "yalitim"], False),
    Sektor("diger", "Diğer", [], True),
]
SEKTOR_SOZLUK = {s.kod: s for s in SEKTORLER}


def sektor_bul(deger) -> Sektor:
    n = tr_norm(deger)
    for s in SEKTORLER:
        if any(a in n for a in s.anahtarlar):
            return s
    return SEKTOR_SOZLUK["diger"]


# ---------------------------------------------------------------------------
# 4. Belge kataloğu (sertifika / beyan / test raporu ayrımı)
# ---------------------------------------------------------------------------

# (eşleşme anahtarları, kanonik ad, kategori, açıklama)
BELGE_KATALOG: list[tuple[list[str], str, str, str]] = [
    (["GOTS"], "GOTS", "Gönüllü ürün sertifikası", "Organik lif içeriği ve üretim süreci"),
    (["OCS", "ORGANICCONTENT"], "OCS", "Gönüllü ürün sertifikası", "Organik içerik iddiası"),
    (["GRS", "GLOBALRECYCLED"], "GRS", "Gönüllü ürün sertifikası", "Geri dönüştürülmüş içerik + sosyal/çevresel kriterler"),
    (["RCS", "RECYCLEDCLAIM"], "RCS", "Gönüllü ürün sertifikası", "Geri dönüştürülmüş içerik iddiası"),
    (["OEKOTEX", "OEKO"], "OEKO-TEX", "Gönüllü ürün etiketi (kimyasal test)", "Zararlı madde testi"),
    (["ZDHC"], "ZDHC", "Gönüllü kimyasal yönetim programı", "Atık su ve kimyasal yönetimi"),
    (["BLUESIGN"], "bluesign", "Gönüllü kimyasal yönetim sertifikası", "Kimyasal ve süreç yönetimi"),
    (["FSC"], "FSC", "Gönüllü orman sertifikası", "Sorumlu ormancılık / ahşap izlenebilirliği"),
    (["PEFC"], "PEFC", "Gönüllü orman sertifikası", "Sorumlu ormancılık / ahşap izlenebilirliği"),
    (["ECOLABEL"], "AB Ecolabel", "Gönüllü çevre etiketi", "AB resmi çevre etiketi"),
    (["ISO14001"], "ISO 14001", "Yönetim sistemi (çevre)", "Kuruluş düzeyi; ürün sertifikası değildir"),
    (["ISO9001"], "ISO 9001", "Yönetim sistemi (kalite)", "Kuruluş düzeyi; çevre veya ürün sertifikası değildir"),
    (["ISO50001"], "ISO 50001", "Yönetim sistemi (enerji)", "Kuruluş düzeyi"),
    (["ISO45001"], "ISO 45001", "Yönetim sistemi (İSG)", "Kuruluş düzeyi"),
    (["IATF"], "IATF 16949", "Yönetim sistemi (otomotiv kalite)", "Kuruluş düzeyi; mevzuat belgesi değildir"),
    (["ISO14067", "PEF", "KARBONAYAKIZI", "CARBONFOOTPRINT"], "Karbon ayak izi çalışması", "Çevresel performans kanıtı", "Ürün karbon ayak izi hesabı"),
    (["EPD"], "EPD", "Çevresel ürün beyanı", "ISO 14025 / EN 15804"),
    (["ROHS"], "RoHS", "Mevzuat uygunluk kanıtı", "2011/65/AB tehlikeli madde sınırlaması (beyan/test)"),
    (["REACH", "SVHC"], "REACH/SVHC", "Mevzuat uygunluk kanıtı", "1907/2006 REACH beyanı veya test raporu"),
    (["WEEE", "AEEE"], "WEEE kaydı", "Mevzuat kaydı", "Üretici sorumluluğu kaydı"),
    (["DOP", "PERFORMANSBEYANI"], "Performans Beyanı (DoP)", "Mevzuat uygunluk beyanı", "Yapı Malzemeleri Tüzüğü"),
    (["CE", "DOC", "UYGUNLUKBEYANI", "DECLARATIONOFCONFORMITY"], "AB Uygunluk Beyanı (CE)", "Mevzuat uygunluk beyanı", "CE işaretine dayanak beyan"),
    (["EN71"], "EN 71 test raporu", "Test raporu", "Oyuncak güvenliği testleri"),
    (["SDS", "GBF", "GUVENLIKBILGIFORMU", "MSDS"], "Güvenlik Bilgi Formu (SDS)", "Mevzuat belgesi", "Kimyasal karışımlar için"),
    (["IMDS"], "IMDS kaydı", "Sektör veri sistemi", "Otomotiv malzeme veri sistemi"),
    (["EPREL"], "EPREL kaydı", "Mevzuat kaydı", "Enerji / lastik etiketi veritabanı"),
    (["EUDR", "DUEDILIGENCE", "DDS"], "EUDR durum tespit beyanı", "Mevzuat beyanı", "Ormansızlaşma Tüzüğü"),
    (["ATR", "EUR1", "MENSE", "MENSEI"], "Menşe / dolaşım belgesi", "Gümrük belgesi", "A.TR, EUR.1 veya menşe şahadetnamesi"),
    (["CBAM", "SEG", "GOMULUEMISYON"], "CBAM emisyon raporu", "Mevzuat veri raporu", "Gömülü emisyon verisi"),
    (["TEST", "ANALIZ", "LAB", "RAPOR"], "Test raporu", "Test raporu", "Laboratuvar analiz/test raporu"),
]

YONETIM_SISTEMLERI = {"ISO 9001", "ISO 14001", "ISO 50001", "ISO 45001", "IATF 16949"}


def belge_sinifla(tur) -> tuple[str, str, str]:
    ham = metin(tur)
    if not ham:
        return "", "", ""
    buyuk = ham.upper().translate(str.maketrans("ÇĞİÖŞÜ", "CGIOSU"))
    tokenler = [t for t in re.split(r"[^A-Z0-9]+", buyuk) if t]
    bitisik = "".join(tokenler)
    for anahtarlar, kanonik, kategori, aciklama in BELGE_KATALOG:
        for a in anahtarlar:
            if a in tokenler or (len(a) >= 4 and a in bitisik):
                return kanonik, kategori, aciklama
    return ham, "Tanımlanamayan belge", "Belge türü katalogda yok; elle kontrol edin"


# ---------------------------------------------------------------------------
# 5. Sütun şeması, eş adlar, şablon açıklamaları
# ---------------------------------------------------------------------------

URUN_KOLONLARI: list[tuple[str, str, str, str]] = [
    # (kolon, zorunluluk, açıklama, örnek)
    ("Urun_Kodu", "Zorunlu", "Firma içi ürün / model kodu", "TK-1001"),
    ("Urun_Adi", "Zorunlu", "Ürün adı", "Organik Pamuk Tişört"),
    ("Sektor", "Zorunlu", "Tekstil, Elektronik, Beyaz Eşya, Batarya, Demir-Çelik, Alüminyum, Mobilya, Otomotiv, Lastik, Oyuncak, Deterjan, Yapı Malzemesi, Diğer", "Tekstil"),
    ("Tuketici_Urunu", "Önerilen", "Evet/Hayır — son tüketiciye satılıyor mu (Genel Ürün Güvenliği Tüzüğü)", "Evet"),
    ("GTIN", "Önerilen", "GS1 barkod numarası (8/12/13/14 hane). Excel'de METİN olarak girin", "8690000000017"),
    ("GTIP", "Önerilen", "Gümrük tarife (HS/GTİP) kodu, en az 6 hane", "6109.10"),
    ("Parti_No", "Önerilen", "Parti / lot numarası", "LOT-2026-001"),
    ("Uretim_Tarihi", "İsteğe bağlı", "Üretim tarihi", "2026-09-15"),
    ("Ihracatci_Unvan", "Önerilen", "İhracatçı / üretici unvanı", "Örnek Tekstil A.Ş."),
    ("Uretim_Tesisi", "Önerilen", "Üretim tesisinin adı ve adresi", "Bursa OSB, 1. Cad. No:5"),
    ("Tesis_ID", "İsteğe bağlı", "Tesis GLN numarası veya sicil no", "8690000000108"),
    ("AB_Sorumlu_Operator", "Tüketici ürünlerinde zorunlu", "AB'de yerleşik sorumlu ekonomik operatör: unvan, adres, e-posta", "Example GmbH, Berlin, info@example.de"),
    ("Uretim_Ulkesi", "Önerilen", "Nihai üretimin yapıldığı ülke", "Türkiye"),
    ("Hammadde_Mensei", "Önerilen", "Ana hammaddenin menşe ülkesi", "Türkiye"),
    ("Malzeme_Bilesimi", "Önerilen", "Malzeme:yüzde; biçiminde, toplam 100", "Pamuk:95;Elastan:5"),
    ("Geri_Donusturulmus_Icerik_Yuzde", "İsteğe bağlı", "Geri dönüştürülmüş içerik oranı (%)", "0"),
    ("SVHC_Beyani", "Önerilen", "Yok / Var / Bilinmiyor — %0,1 üzeri yüksek önem arz eden madde", "Yok"),
    ("SVHC_Maddeler", "SVHC Var ise", "Madde adı ve CAS numarası", ""),
    ("Cevresel_Iddia", "İsteğe bağlı", "Etikette / katalogda kullanılan çevre iddiası", "Organik pamuk"),
    ("Karbon_Ayak_Izi_kgCO2e", "İsteğe bağlı", "Birim ürün başına karbon ayak izi (kg CO2e)", "4.2"),
    ("Karbon_Yontemi", "Karbon girildiyse", "Hesaplama yöntemi: ISO 14067, PEF, EPD vb.", "ISO 14067"),
    ("Gomulu_Emisyon_tCO2e_t", "Demir-çelik / alüminyum", "CBAM gömülü emisyon (ton CO2e / ton ürün)", ""),
    ("EPREL_No", "Enerji / lastik etiketli ürünler", "EPREL kayıt numarası", ""),
    ("IMDS_ID", "Otomotiv", "IMDS kayıt numarası", ""),
    ("Batarya_Kategorisi", "Batarya", "EV / LMT / Endüstriyel / Taşınabilir", ""),
    ("Batarya_Kimyasi", "Batarya", "ör. LFP, NMC", ""),
    ("Batarya_Kapasite_kWh", "Batarya", "Kapasite (kWh)", ""),
    ("Bakim_Onarim_Bilgisi", "Önerilen", "Bakım, onarım, yedek parça bilgisi", "30°C'de yıkayın"),
    ("Omur_Sonu_Talimati", "Önerilen", "Geri dönüşüm / bertaraf talimatı", "Tekstil geri dönüşüm kutusuna atınız"),
]

BELGE_KOLONLARI: list[tuple[str, str, str, str]] = [
    ("Urun_Kodu", "Zorunlu", "Belgenin ait olduğu ürün kodu. Firmadaki tüm ürünler için geçerliyse * yazın", "TK-1001"),
    ("Belge_Turu", "Zorunlu", "GOTS, OEKO-TEX, CE Uygunluk Beyanı, RoHS, REACH beyanı, test raporu, ISO 14001 ...", "GOTS"),
    ("Belge_No", "Önerilen", "Belge / sertifika numarası", "CU-123456"),
    ("Duzenleyen", "Önerilen", "Belgeyi düzenleyen kuruluş", "Control Union"),
    ("Gecerlilik_Bitis", "Önerilen", "Geçerlilik bitiş tarihi (süresizse boş)", "2027-08-31"),
    ("Kapsam", "İsteğe bağlı", "Belgenin kapsamı", "Örme tişört üretimi"),
    ("Dosya_Baglantisi", "İsteğe bağlı", "Belgenin bulunduğu link / klasör yolu", ""),
]

TEDARIK_KOLONLARI: list[tuple[str, str, str, str]] = [
    ("Urun_Kodu", "Zorunlu", "Ürün kodu", "TK-1001"),
    ("Asama_Sira", "Önerilen", "Aşama sırası (1, 2, 3 ...)", "1"),
    ("Asama", "Zorunlu", "İplik, Kumaş, Boya, Konfeksiyon, Döküm, Montaj ...", "İplik"),
    ("Tedarikci", "Önerilen", "Tedarikçi unvanı", "Örnek İplik Ltd."),
    ("Ulke", "Zorunlu", "Aşamanın gerçekleştiği ülke", "Türkiye"),
    ("Belge_No", "İsteğe bağlı", "Bu aşamayı destekleyen belge no", "TC-0001"),
]

# Eski formatlardaki ya da farklı yazımlardaki sütun adlarının karşılıkları
KOLON_ES_ADLARI: dict[str, str] = {
    "urun_kodu": "Urun_Kodu", "urunkodu": "Urun_Kodu", "kod": "Urun_Kodu", "stok_kodu": "Urun_Kodu", "model_kodu": "Urun_Kodu", "sku": "Urun_Kodu",
    "urun_adi": "Urun_Adi", "urunadi": "Urun_Adi", "urun": "Urun_Adi", "aciklama": "Urun_Adi",
    "sektor": "Sektor", "sector": "Sektor",
    "tuketici_urunu": "Tuketici_Urunu",
    "gtin": "GTIN", "barkod": "GTIN", "ean": "GTIN", "barcode": "GTIN",
    "gtip": "GTIP", "hs_kodu": "GTIP", "hs_code": "GTIP", "gtip_kodu": "GTIP",
    "parti_no": "Parti_No", "lot": "Parti_No", "lot_no": "Parti_No",
    "uretim_tarihi": "Uretim_Tarihi",
    "ihracatci_unvan": "Ihracatci_Unvan", "ihracatci": "Ihracatci_Unvan", "uretici": "Ihracatci_Unvan", "firma": "Ihracatci_Unvan",
    "uretim_tesisi": "Uretim_Tesisi", "tesis": "Uretim_Tesisi",
    "tesis_id": "Tesis_ID", "gln": "Tesis_ID",
    "ab_sorumlu_operator": "AB_Sorumlu_Operator", "ab_temsilci": "AB_Sorumlu_Operator", "ab_ithalatci": "AB_Sorumlu_Operator",
    "uretim_ulkesi": "Uretim_Ulkesi", "mense_ulke": "Uretim_Ulkesi", "uretim_yeri": "Uretim_Ulkesi",
    "hammadde_mensei": "Hammadde_Mensei", "hammadde_mense": "Hammadde_Mensei",
    "malzeme_bilesimi": "Malzeme_Bilesimi", "malzeme": "Malzeme_Bilesimi", "bilesim": "Malzeme_Bilesimi", "lif_bilesimi": "Malzeme_Bilesimi",
    "geri_donusturulmus_icerik_yuzde": "Geri_Donusturulmus_Icerik_Yuzde", "geri_donusturulmus_icerik": "Geri_Donusturulmus_Icerik_Yuzde",
    "svhc_beyani": "SVHC_Beyani", "svhc": "SVHC_Beyani",
    "svhc_maddeler": "SVHC_Maddeler",
    "cevresel_iddia": "Cevresel_Iddia",
    "karbon_ayak_izi_kgco2e": "Karbon_Ayak_Izi_kgCO2e", "karbon_ayak_izi_kg": "Karbon_Ayak_Izi_kgCO2e", "karbon_ayak_izi": "Karbon_Ayak_Izi_kgCO2e",
    "karbon_yontemi": "Karbon_Yontemi",
    "gomulu_emisyon_tco2e_t": "Gomulu_Emisyon_tCO2e_t", "gomulu_emisyon": "Gomulu_Emisyon_tCO2e_t", "cbam_emisyon": "Gomulu_Emisyon_tCO2e_t",
    "eprel_no": "EPREL_No", "eprel": "EPREL_No",
    "imds_id": "IMDS_ID", "imds": "IMDS_ID",
    "batarya_kategorisi": "Batarya_Kategorisi", "batarya_kimyasi": "Batarya_Kimyasi", "batarya_kapasite_kwh": "Batarya_Kapasite_kWh",
    "bakim_onarim_bilgisi": "Bakim_Onarim_Bilgisi", "bakim_talimati": "Bakim_Onarim_Bilgisi",
    "omur_sonu_talimati": "Omur_Sonu_Talimati", "omur_sonu": "Omur_Sonu_Talimati",
    # belge sayfası
    "belge_turu": "Belge_Turu", "belge": "Belge_Turu", "sertifika": "Belge_Turu", "sertifika_turu": "Belge_Turu",
    "belge_no": "Belge_No", "sertifika_no": "Belge_No",
    "duzenleyen": "Duzenleyen", "kurulus": "Duzenleyen",
    "gecerlilik_bitis": "Gecerlilik_Bitis", "bitis_tarihi": "Gecerlilik_Bitis", "gecerlilik": "Gecerlilik_Bitis",
    "kapsam": "Kapsam", "dosya_baglantisi": "Dosya_Baglantisi", "link": "Dosya_Baglantisi",
    # tedarik sayfası
    "asama_sira": "Asama_Sira", "sira": "Asama_Sira", "asama": "Asama", "tedarikci": "Tedarikci", "ulke": "Ulke",
    # eski format (v1) — dönüştürülecek
    "cevre_sertifikasi": "_ESKI_Cevre_Sertifikasi",
    "sertifika_bitis_tarihi": "_ESKI_Sertifika_Bitis_Tarihi",
    "geri_donusturulebilirlik_orani": "_ESKI_Geri_Donusturulebilirlik",
}


def _kolon_anahtari(ad) -> str:
    return re.sub(r"[^a-z0-9]+", "_", tr_norm(ad)).strip("_")


def kolonlari_standartlastir(df: pd.DataFrame) -> pd.DataFrame:
    yeni = {}
    for k in df.columns:
        anahtar = _kolon_anahtari(k)
        yeni[k] = KOLON_ES_ADLARI.get(anahtar, str(k).strip())
    df = df.rename(columns=yeni)
    return df.loc[:, ~df.columns.duplicated()]


def _kolonlari_tamamla(df: pd.DataFrame, sema) -> pd.DataFrame:
    for kolon, *_ in sema:
        if kolon not in df.columns:
            df[kolon] = None
    on = [k for k, *_ in sema]
    return df[on + [c for c in df.columns if c not in on]]


# ---------------------------------------------------------------------------
# 6. Veri yükleme
# ---------------------------------------------------------------------------

@dataclass
class VeriSeti:
    urunler: pd.DataFrame
    belgeler: pd.DataFrame
    tedarik: pd.DataFrame
    uyarilar: list[str] = field(default_factory=list)


def bos_veri_seti() -> VeriSeti:
    return VeriSeti(
        urunler=_kolonlari_tamamla(pd.DataFrame(), URUN_KOLONLARI + [("Kaynak_Dosya", "", "", "")]),
        belgeler=_kolonlari_tamamla(pd.DataFrame(), BELGE_KOLONLARI + [("Kaynak_Dosya", "", "", "")]),
        tedarik=_kolonlari_tamamla(pd.DataFrame(), TEDARIK_KOLONLARI + [("Kaynak_Dosya", "", "", "")]),
    )


def _sayfa_turu(sayfa_adi: str, df: pd.DataFrame) -> str:
    n = tr_norm(sayfa_adi)
    if "belge" in n or "sertifika" in n:
        return "belge"
    if "tedarik" in n or "zincir" in n or "asama" in n:
        return "tedarik"
    if "aciklama" in n or "talimat" in n or "okubeni" in n:
        return "atla"
    kolonlar = set(df.columns)
    if "Belge_Turu" in kolonlar and "Urun_Adi" not in kolonlar:
        return "belge"
    if "Asama" in kolonlar and "Urun_Adi" not in kolonlar:
        return "tedarik"
    return "urun"


def excel_oku(dosya, dosya_adi: str) -> VeriSeti:
    """Bir Excel dosyasındaki tüm sayfaları okur ve türüne göre ayırır."""
    uyarilar: list[str] = []
    sayfalar = pd.read_excel(dosya, sheet_name=None, dtype=object)
    urun_parcalari, belge_parcalari, tedarik_parcalari = [], [], []

    for sayfa_adi, ham in sayfalar.items():
        if ham is None or ham.dropna(how="all").empty:
            continue
        df = kolonlari_standartlastir(ham.dropna(how="all"))
        tur = _sayfa_turu(str(sayfa_adi), df)
        df["Kaynak_Dosya"] = f"{dosya_adi} / {sayfa_adi}"
        if tur == "urun":
            if "Urun_Kodu" not in df.columns:
                uyarilar.append(f"{dosya_adi} / {sayfa_adi}: 'Urun_Kodu' sütunu bulunamadı, sayfa atlandı.")
                continue
            urun_parcalari.append(df)
        elif tur == "belge":
            belge_parcalari.append(df)
        elif tur == "tedarik":
            tedarik_parcalari.append(df)

    urunler = pd.concat(urun_parcalari, ignore_index=True) if urun_parcalari else pd.DataFrame()
    belgeler = pd.concat(belge_parcalari, ignore_index=True) if belge_parcalari else pd.DataFrame()
    tedarik = pd.concat(tedarik_parcalari, ignore_index=True) if tedarik_parcalari else pd.DataFrame()

    # --- Eski (v1) format dönüşümü ---
    if not urunler.empty and "_ESKI_Cevre_Sertifikasi" in urunler.columns:
        eski_belgeler = []
        for _, r in urunler.iterrows():
            tur = r.get("_ESKI_Cevre_Sertifikasi")
            if bos_mu(tur):
                continue
            eski_belgeler.append({
                "Urun_Kodu": r.get("Urun_Kodu"),
                "Belge_Turu": tur,
                "Gecerlilik_Bitis": r.get("_ESKI_Sertifika_Bitis_Tarihi"),
                "Kaynak_Dosya": r.get("Kaynak_Dosya"),
            })
        if eski_belgeler:
            belgeler = pd.concat([belgeler, pd.DataFrame(eski_belgeler)], ignore_index=True)
        uyarilar.append(
            f"{dosya_adi}: eski format algılandı. 'Cevre_Sertifikasi' sütunu belge kasasına aktarıldı. "
            "Daha doğru sonuç için yeni şablonu kullanmanız önerilir."
        )
    if not urunler.empty and "_ESKI_Geri_Donusturulebilirlik" in urunler.columns:
        uyarilar.append(
            f"{dosya_adi}: 'Geri_Donusturulebilirlik_Orani' bir geri dönüştürülmüş İÇERİK oranı değildir; "
            "değerlendirmeye alınmadı. Geri dönüştürülmüş içerik için 'Geri_Donusturulmus_Icerik_Yuzde' sütununu kullanın."
        )
    urunler = urunler.drop(columns=[c for c in urunler.columns if str(c).startswith("_ESKI_")], errors="ignore")

    return VeriSeti(urunler, belgeler, tedarik, uyarilar)


def veri_birlestir(setler: list[VeriSeti]) -> VeriSeti:
    if not setler:
        return bos_veri_seti()
    urunler = pd.concat([s.urunler for s in setler if not s.urunler.empty] or [pd.DataFrame()], ignore_index=True)
    belgeler = pd.concat([s.belgeler for s in setler if not s.belgeler.empty] or [pd.DataFrame()], ignore_index=True)
    tedarik = pd.concat([s.tedarik for s in setler if not s.tedarik.empty] or [pd.DataFrame()], ignore_index=True)
    uyarilar = [u for s in setler for u in s.uyarilar]

    urunler = _kolonlari_tamamla(urunler, URUN_KOLONLARI + [("Kaynak_Dosya", "", "", "")])
    belgeler = _kolonlari_tamamla(belgeler, BELGE_KOLONLARI + [("Kaynak_Dosya", "", "", "")])
    tedarik = _kolonlari_tamamla(tedarik, TEDARIK_KOLONLARI + [("Kaynak_Dosya", "", "", "")])

    # Kod biçimini sadeleştir
    for df in (urunler, belgeler, tedarik):
        df["Urun_Kodu"] = df["Urun_Kodu"].map(lambda v: metin(v))
    urunler = urunler[urunler["Urun_Kodu"] != ""].reset_index(drop=True)
    for kolon in ("GTIN", "GTIP", "Tesis_ID", "EPREL_No", "IMDS_ID"):
        urunler[kolon] = urunler[kolon].map(lambda v: metin(v) or None)

    tekrar = urunler["Urun_Kodu"][urunler["Urun_Kodu"].duplicated()].unique().tolist()
    if tekrar:
        uyarilar.append(
            f"{len(tekrar)} ürün kodu birden fazla satırda/dosyada geçiyor (ör. {', '.join(tekrar[:5])}). "
            "Her kod için ilk kayıt esas alındı; diğerleri 'Yinelenen kayıtlar' tablosunda gösteriliyor."
        )
    return VeriSeti(urunler, belgeler, tedarik, uyarilar)


def yinelenenler(urunler: pd.DataFrame) -> pd.DataFrame:
    return urunler[urunler["Urun_Kodu"].duplicated(keep=False)].sort_values("Urun_Kodu")


def tekil_urunler(urunler: pd.DataFrame) -> pd.DataFrame:
    return urunler.drop_duplicates("Urun_Kodu", keep="first").reset_index(drop=True)


# ---------------------------------------------------------------------------
# 7. Belge kasası
# ---------------------------------------------------------------------------

def belge_kasasi(belgeler: pd.DataFrame, bugun: Optional[date] = None) -> pd.DataFrame:
    bugun = bugun or date.today()
    if belgeler is None or belgeler.empty:
        return pd.DataFrame(columns=[k for k, *_ in BELGE_KOLONLARI] + ["Kanonik_Tur", "Kategori", "Not", "Kalan_Gun", "Durum"])
    df = belgeler.copy()
    df = df[~df["Belge_Turu"].map(bos_mu)].reset_index(drop=True)
    siniflar = df["Belge_Turu"].map(belge_sinifla)
    df["Kanonik_Tur"] = siniflar.map(lambda t: t[0])
    df["Kategori"] = siniflar.map(lambda t: t[1])
    df["Not"] = siniflar.map(lambda t: t[2])
    bitisler = df["Gecerlilik_Bitis"].map(tarih)
    df["Gecerlilik_Bitis"] = bitisler
    df["Kalan_Gun"] = pd.array([(d - bugun).days if d else None for d in bitisler], dtype="Int64")

    def durum(g):
        if g is None or g is pd.NA or pd.isna(g):
            return "Bitiş tarihi yok"
        if g < 0:
            return "Süresi dolmuş"
        if g <= 30:
            return "30 gün içinde doluyor"
        if g <= 60:
            return "60 gün içinde doluyor"
        return "Geçerli"

    df["Durum"] = df["Kalan_Gun"].map(durum)
    return df


def urun_belgeleri(kasa: pd.DataFrame, urun_kodu: str) -> pd.DataFrame:
    if kasa.empty:
        return kasa
    return kasa[(kasa["Urun_Kodu"] == urun_kodu) | (kasa["Urun_Kodu"] == "*")]


# ---------------------------------------------------------------------------
# 8. Kural motoru
# ---------------------------------------------------------------------------

SEVIYE_SIRASI = {"Kritik": 0, "Yüksek": 1, "Orta": 2, "Bilgi": 3}


@dataclass
class Baglam:
    satir: pd.Series
    sektor: Sektor
    tuketici: bool
    belgeler: pd.DataFrame
    tedarik: pd.DataFrame
    gtin_tekrarlari: set
    bugun: date

    def deger(self, kolon):
        return self.satir.get(kolon)

    def var(self, kolon) -> bool:
        return not bos_mu(self.satir.get(kolon))

    def gecerli_belge(self, *kanonikler) -> bool:
        if self.belgeler.empty:
            return False
        uygun = self.belgeler[self.belgeler["Kanonik_Tur"].isin(kanonikler)]
        return bool((uygun["Durum"] != "Süresi dolmuş").any())

    def belge_var(self, *kanonikler) -> bool:
        if self.belgeler.empty:
            return False
        return bool(self.belgeler["Kanonik_Tur"].isin(kanonikler).any())


@dataclass
class Kural:
    kod: str
    ad: str
    seviye: str
    agirlik: int
    dayanak: str
    durum: str  # "Yürürlükte" / "Beklenen DPP verisi" / "İyi uygulama"
    kapsam: str
    uygulanir: Callable[[Baglam], bool]
    kontrol: Callable[[Baglam], tuple[bool, str]]
    recete: list[str]


def _her_zaman(_b: Baglam) -> bool:
    return True


def _sektor(*kodlar):
    return lambda b: b.sektor.kod in kodlar


def _iddia_metni(b: Baglam) -> str:
    return tr_norm(" ".join([metin(b.deger("Cevresel_Iddia")), metin(b.deger("Urun_Adi"))]))


_IDDIA_KELIMELERI = {
    "organik": ("GOTS", "OCS"),
    "organic": ("GOTS", "OCS"),
    "geri donusturulmus": ("GRS", "RCS"),
    "recycled": ("GRS", "RCS"),
    "surdurulebilir": None,
    "cevre dostu": None,
    "eko": None,
    "dogal": None,
    "karbon notr": None,
    "iklim dostu": None,
}


_IDDIA_ETIKET = {"organik": "organik", "geri donusturulmus": "geri dönüştürülmüş", "surdurulebilir": "sürdürülebilir",
                 "cevre dostu": "çevre dostu", "dogal": "doğal", "karbon notr": "karbon nötr", "iklim dostu": "iklim dostu"}


# --- kontrol fonksiyonları ---

def _k_gtin(b):
    return gtin_dogrula(b.deger("GTIN"))


def _k_gtin_tekil(b):
    g = gtin_temizle(b.deger("GTIN"))
    if g and g in b.gtin_tekrarlari:
        return False, f"{g} numaralı GTIN başka ürün kodlarında da kullanılmış"
    return True, "GTIN bu ürüne özgü"


def _k_gtip(b):
    return gtip_dogrula(b.deger("GTIP"))


def _k_aktor(b):
    eksik = [ad for k, ad in (("Ihracatci_Unvan", "ihracatçı/üretici unvanı"), ("Uretim_Tesisi", "üretim tesisi")) if not b.var(k)]
    return (not eksik), ("Aktör bilgileri tam" if not eksik else "Eksik: " + ", ".join(eksik))


def _k_mense(b):
    eksik = [ad for k, ad in (("Uretim_Ulkesi", "üretim ülkesi"), ("Hammadde_Mensei", "hammadde menşei")) if not b.var(k)]
    return (not eksik), ("Menşe bilgileri tam" if not eksik else "Eksik: " + ", ".join(eksik))


def _k_malzeme(b):
    liste, toplam = malzeme_ayristir(b.deger("Malzeme_Bilesimi"))
    if not liste:
        return False, "Malzeme bileşimi girilmemiş veya okunamadı (biçim: Malzeme:yüzde;...)"
    if abs(toplam - 100) > 1:
        return False, f"Malzeme oranları toplamı %{toplam:g}; %100 olmalı"
    return True, "Bileşim: " + ", ".join(f"{a} %{o:g}" for a, o in liste)


def _k_svhc(b):
    beyan = tr_norm(b.deger("SVHC_Beyani"))
    if beyan in ("", "nan", "none", "bilinmiyor", "belirsiz"):
        return False, "SVHC (yüksek önem arz eden madde) beyanı yok veya 'Bilinmiyor'"
    if beyan in ("var", "evet", "yes"):
        if not b.var("SVHC_Maddeler"):
            return False, "SVHC 'Var' denmiş ama madde adı / CAS no girilmemiş"
        return True, f"SVHC beyanı: Var — {metin(b.deger('SVHC_Maddeler'))}"
    if beyan in ("yok", "hayir", "no"):
        return True, "SVHC beyanı: Yok"
    return False, f"SVHC beyanı anlaşılamadı: '{metin(b.deger('SVHC_Beyani'))}' (Yok / Var / Bilinmiyor yazın)"


def _k_svhc_kanit(b):
    if b.gecerli_belge("REACH/SVHC", "Test raporu", "OEKO-TEX", "RoHS"):
        return True, "Kimyasal uygunluk için destekleyici belge mevcut"
    return False, "SVHC/REACH beyanını destekleyen tedarikçi beyanı veya test raporu belge kasasında yok"


def _k_belge_suresi(b):
    if b.belgeler.empty:
        return True, "Bu ürüne bağlı belge yok (süre kontrolü yapılamadı)"
    dolmus = b.belgeler[b.belgeler["Durum"] == "Süresi dolmuş"]
    if not dolmus.empty:
        return False, "Süresi dolmuş: " + ", ".join(f"{r.Kanonik_Tur} ({r.Gecerlilik_Bitis})" for r in dolmus.itertuples())
    return True, "Belgelerin süresi dolmamış"


def _k_belge_yaklasan(b):
    if b.belgeler.empty:
        return True, "—"
    yakin = b.belgeler[b.belgeler["Durum"].isin(["30 gün içinde doluyor", "60 gün içinde doluyor"])]
    if not yakin.empty:
        return False, "Yenileme zamanı yaklaşan: " + ", ".join(f"{r.Kanonik_Tur} ({int(r.Kalan_Gun)} gün)" for r in yakin.itertuples())
    return True, "60 gün içinde süresi dolacak belge yok"


def _k_belge_sinif(b):
    if b.belgeler.empty:
        return True, "—"
    yonetim = b.belgeler[b.belgeler["Kanonik_Tur"].isin(YONETIM_SISTEMLERI)]
    urun_sertifikasi_yok = not b.belgeler["Kategori"].str.contains("ürün|uygunluk|test|etiket|orman", case=False, regex=True).any()
    if not yonetim.empty and urun_sertifikasi_yok:
        turler = ", ".join(sorted(set(yonetim["Kanonik_Tur"])))
        return False, f"{turler} kuruluş düzeyinde yönetim sistemi belgesidir; ürünün çevre veya mevzuat uygunluğunu tek başına kanıtlamaz"
    tanimsiz = b.belgeler[b.belgeler["Kategori"] == "Tanımlanamayan belge"]
    if not tanimsiz.empty:
        return False, "Türü tanımlanamayan belge: " + ", ".join(tanimsiz["Belge_Turu"].astype(str))
    return True, "Belge türleri doğru sınıflandırılmış"


def _k_iddia(b):
    m = _iddia_metni(b)
    bulunan = [k for k in _IDDIA_KELIMELERI if k in m]
    if not bulunan:
        return True, "Ürün adında / iddia alanında çevre iddiası yok"
    eksik = []
    for k in bulunan:
        gereken = _IDDIA_KELIMELERI[k]
        if gereken is None:
            if not b.gecerli_belge("AB Ecolabel", "EPD", "Karbon ayak izi çalışması", "GOTS", "GRS", "OCS", "RCS", "FSC", "PEFC"):
                eksik.append(f"'{_IDDIA_ETIKET.get(k, k)}' (genel çevre iddiası; tanınmış etiket veya doğrulanmış veri gerekir)")
        elif not b.gecerli_belge(*gereken):
            eksik.append(f"'{_IDDIA_ETIKET.get(k, k)}' ({' / '.join(gereken)} gerekir)")
    if eksik:
        return False, "Kanıtsız çevre iddiası: " + "; ".join(eksik)
    return True, "Çevre iddiaları geçerli belgelerle destekleniyor"


def _k_geri_donusum_kanit(b):
    oran = sayi(b.deger("Geri_Donusturulmus_Icerik_Yuzde"))
    if not oran:
        return True, "Geri dönüştürülmüş içerik beyanı yok"
    if b.gecerli_belge("GRS", "RCS"):
        return True, f"%{oran:g} geri dönüştürülmüş içerik GRS/RCS ile destekleniyor"
    if b.sektor.kod in ("demir_celik", "aluminyum") and b.gecerli_belge("EPD", "Test raporu"):
        return True, f"%{oran:g} geri dönüştürülmüş içerik EPD / rapor ile destekleniyor"
    return False, f"%{oran:g} geri dönüştürülmüş içerik beyan edilmiş ancak destekleyici belge yok"


def _k_bakim(b):
    eksik = [ad for k, ad in (("Bakim_Onarim_Bilgisi", "bakım/onarım bilgisi"), ("Omur_Sonu_Talimati", "ömür sonu talimatı")) if not b.var(k)]
    return (not eksik), ("Kullanım ve ömür sonu bilgileri tam" if not eksik else "Eksik: " + ", ".join(eksik))


def _k_karbon(b):
    if not b.var("Karbon_Ayak_Izi_kgCO2e"):
        return False, "Karbon ayak izi verisi yok (bugün zorunlu değil; alıcılar giderek talep ediyor)"
    if not b.var("Karbon_Yontemi"):
        return False, "Karbon ayak izi girilmiş ama hesaplama yöntemi belirtilmemiş"
    return True, f"{metin(b.deger('Karbon_Ayak_Izi_kgCO2e'))} kg CO2e ({metin(b.deger('Karbon_Yontemi'))})"


def _k_gpsr(b):
    if b.var("AB_Sorumlu_Operator"):
        return True, f"AB sorumlu operatör: {metin(b.deger('AB_Sorumlu_Operator'))}"
    return False, "AB'de yerleşik sorumlu ekonomik operatör bilgisi yok"


def _k_tedarik(b):
    if b.tedarik.empty:
        return False, "Tedarik zinciri aşaması girilmemiş"
    ulkeli = b.tedarik[~b.tedarik["Ulke"].map(bos_mu)]
    if len(ulkeli) < 2:
        return False, f"{len(ulkeli)} aşama ülke bilgisiyle girilmiş; en az 2 aşama (hammadde → nihai üretim) önerilir"
    return True, f"{len(ulkeli)} aşama kayıtlı"


def _k_tekstil_lif(b):
    liste, toplam = malzeme_ayristir(b.deger("Malzeme_Bilesimi"))
    if not liste:
        return False, "Lif bileşimi girilmemiş; tekstil etiketinde lif adı ve yüzdesi zorunludur"
    if abs(toplam - 100) > 1:
        return False, f"Lif oranları toplamı %{toplam:g}; %100 olmalı"
    return True, "Lif bileşimi: " + ", ".join(f"{a} %{o:g}" for a, o in liste)


def _k_tekstil_kimyasal(b):
    if b.gecerli_belge("OEKO-TEX", "Test raporu", "REACH/SVHC", "ZDHC", "bluesign"):
        return True, "Kimyasal uygunluk kanıtı mevcut"
    return False, "REACH Ek XVII kısıtlamaları (azo boyar maddeler, ağır metaller vb.) için test raporu veya tanınmış etiket yok"


def _k_ce(b):
    if b.gecerli_belge("AB Uygunluk Beyanı (CE)"):
        return True, "AB Uygunluk Beyanı mevcut"
    return False, "AB Uygunluk Beyanı (CE) belge kasasında yok"


def _k_rohs(b):
    if b.gecerli_belge("RoHS"):
        return True, "RoHS uygunluk kanıtı mevcut"
    return False, "RoHS beyanı veya test raporu yok"


def _k_weee(b):
    if b.gecerli_belge("WEEE kaydı"):
        return True, "WEEE kaydı mevcut"
    return False, "Satış yapılan AB ülkesinde WEEE üretici kaydı bilgisi yok (genellikle AB'li ithalatçı/yetkili temsilci yapar)"


def _k_eprel(b):
    if b.var("EPREL_No") or b.gecerli_belge("EPREL kaydı"):
        return True, f"EPREL: {metin(b.deger('EPREL_No')) or 'belge kasasında'}"
    return False, "EPREL kayıt numarası yok"


def _batarya_pasaport_kapsaminda(b) -> bool:
    if b.sektor.kod != "batarya":
        return False
    kat = tr_norm(b.deger("Batarya_Kategorisi"))
    kap = sayi(b.deger("Batarya_Kapasite_kWh")) or 0
    return ("ev" in kat.split() or "elektrikli arac" in kat or "lmt" in kat or "hafif" in kat
            or (("endustriyel" in kat or "industrial" in kat) and kap > 2))


def _k_batarya(b):
    eksik = [ad for k, ad in (("Batarya_Kimyasi", "batarya kimyası"), ("Batarya_Kapasite_kWh", "kapasite"),
                               ("Karbon_Ayak_Izi_kgCO2e", "karbon ayak izi"), ("GTIN", "benzersiz tanımlayıcı")) if not b.var(k)]
    if eksik:
        return False, "Batarya pasaportu için eksik veri: " + ", ".join(eksik)
    return True, "Temel batarya pasaportu verileri mevcut"


def _k_batarya_kategori(b):
    if b.var("Batarya_Kategorisi"):
        return True, f"Kategori: {metin(b.deger('Batarya_Kategorisi'))}"
    return False, "Batarya kategorisi (EV / LMT / Endüstriyel / Taşınabilir) girilmemiş; pasaport kapsamı belirlenemiyor"


def _k_cbam(b):
    eksik = [ad for k, ad in (("Gomulu_Emisyon_tCO2e_t", "gömülü emisyon"), ("Tesis_ID", "tesis tanımlayıcısı")) if not b.var(k)]
    if eksik:
        return False, "CBAM verisi eksik: " + ", ".join(eksik)
    return True, f"Gömülü emisyon: {metin(b.deger('Gomulu_Emisyon_tCO2e_t'))} tCO2e/t"


def _ahsap_iceriyor(b) -> bool:
    m = tr_norm(b.deger("Malzeme_Bilesimi")) + " " + tr_norm(b.deger("Urun_Adi"))
    return any(k in m for k in ("ahsap", "mdf", "suntalam", "kontrplak", "kereste", "wood", "mese", "ceviz", "kayin", "cam agaci", "kagit", "karton"))


def _k_eudr(b):
    if b.gecerli_belge("EUDR durum tespit beyanı"):
        return True, "EUDR durum tespit beyanı mevcut"
    if b.gecerli_belge("FSC", "PEFC"):
        return False, "FSC/PEFC mevcut ancak EUDR durum tespit beyanının yerine geçmez; hasat yeri (coğrafi konum) verisi gerekir"
    return False, "Ahşap içeren ürün için EUDR durum tespiti / hasat yeri bilgisi yok"


def _k_imds(b):
    if b.var("IMDS_ID") or b.belge_var("IMDS kaydı"):
        return True, "IMDS kaydı mevcut"
    return False, "IMDS kayıt numarası yok (OEM müşteriler talep eder; ELV ve REACH uyumunun dayanağı)"


def _k_oyuncak(b):
    eksik = []
    if not b.gecerli_belge("AB Uygunluk Beyanı (CE)"):
        eksik.append("AB Uygunluk Beyanı (CE)")
    if not b.gecerli_belge("EN 71 test raporu", "Test raporu"):
        eksik.append("EN 71 test raporu")
    return (not eksik), ("CE ve test raporu mevcut" if not eksik else "Eksik: " + ", ".join(eksik))


def _k_sds(b):
    if b.gecerli_belge("Güvenlik Bilgi Formu (SDS)"):
        return True, "Güvenlik Bilgi Formu mevcut"
    return False, "Güvenlik Bilgi Formu (SDS) yok"


def _k_dop(b):
    eksik = []
    if not b.gecerli_belge("Performans Beyanı (DoP)"):
        eksik.append("Performans Beyanı (DoP)")
    if not b.gecerli_belge("AB Uygunluk Beyanı (CE)"):
        eksik.append("CE işareti dayanağı")
    return (not eksik), ("DoP ve CE mevcut" if not eksik else "Eksik: " + ", ".join(eksik))


KURALLAR: list[Kural] = [
    # --- Genel kurallar (tüm sektörler) ---
    Kural("G01", "Benzersiz ürün tanımlayıcısı (GTIN)", "Yüksek", 10,
          "ESPR (AB) 2024/1781 md. 9–12; EN 18219:2026 benzersiz tanımlayıcılar", "Beklenen DPP verisi", "Tüm sektörler",
          _her_zaman, _k_gtin,
          ["GS1 Türkiye üyeliği ile firmanıza ait barkod numara bloğu alın.",
           "Her model (gerekirse her parti) için ayrı GTIN tanımlayın; örnek/yer tutucu numara kullanmayın.",
           "GTIN'i Excel'de METİN olarak girin, aksi halde baştaki sıfırlar kaybolur."]),
    Kural("G02", "GTIN tekilliği", "Yüksek", 5,
          "GS1 Genel Spesifikasyonları; ESPR benzersiz tanımlayıcı ilkesi", "İyi uygulama", "Tüm sektörler",
          lambda b: bool(gtin_temizle(b.deger("GTIN"))), _k_gtin_tekil,
          ["Aynı GTIN'in farklı ürün kodlarında kullanıldığı satırları düzeltin.",
           "Renk/beden gibi varyantlar ayrı GTIN gerektirir."]),
    Kural("G03", "Gümrük tarife (GTİP/HS) kodu", "Orta", 5,
          "Uygulama Tüzüğü (AB) 2026/1778 (DPP Registry, serbest dolaşım için emtia kodu)", "Yürürlükte", "Tüm sektörler",
          _her_zaman, _k_gtip,
          ["Gümrük beyannamesindeki GTİP kodunu (en az 6 hane) ürün kartına işleyin.",
           "Emin değilseniz gümrük müşavirinizden bağlayıcı tarife bilgisi alın."]),
    Kural("G04", "Üretici / ihracatçı ve tesis bilgisi", "Yüksek", 8,
          "ESPR Ek III — iktisadi işletmeci ve tesis tanımlayıcıları", "Beklenen DPP verisi", "Tüm sektörler",
          _her_zaman, _k_aktor,
          ["İhracatçı unvanını ve üretimin yapıldığı tesisin açık adresini girin.",
           "Tesisin GS1 GLN numarası varsa 'Tesis_ID' alanına ekleyin."]),
    Kural("G05", "Menşe bilgisi", "Kritik", 10,
          "Gümrük mevzuatı (menşe kuralları); ESPR Ek III", "Yürürlükte", "Tüm sektörler",
          _her_zaman, _k_mense,
          ["Nihai üretim ülkesini ve ana hammaddenin menşeini girin.",
           "Hammadde ithal ise tedarikçinin menşe belgesini (EUR.1, A.TR, menşe şahadetnamesi) belge kasasına ekleyin."]),
    Kural("G06", "Malzeme bileşimi", "Yüksek", 8,
          "ESPR md. 7 ve Ek I — malzeme ve geri dönüştürülmüş içerik bilgisi", "Beklenen DPP verisi", "Tekstil dışındaki sektörler",
          lambda b: b.sektor.kod != "tekstil", _k_malzeme,
          ["Ürünü oluşturan ana malzemeleri ağırlıkça yüzdeleriyle girin (ör. Çelik:80;Plastik:15;Bakır:5).",
           "Toplamın %100 olduğundan emin olun."]),
    Kural("G07", "Endişe verici madde (SVHC) beyanı", "Kritik", 10,
          "REACH (AT) 1907/2006 md. 33 — %0,1 üzeri SVHC bilgi verme yükümlülüğü; ESPR md. 7(5)", "Yürürlükte", "Tüm sektörler",
          _her_zaman, _k_svhc,
          ["Tedarikçilerinizden güncel ECHA aday listesine göre SVHC beyanı isteyin.",
           "Ürün %0,1 (ağırlıkça) üzeri SVHC içeriyorsa madde adını ve CAS numarasını girin.",
           "'Bilinmiyor' durumunda akredite laboratuvarda tarama testi yaptırın."]),
    Kural("G08", "SVHC beyanının belgeyle desteklenmesi", "Orta", 4,
          "REACH md. 33; durum tespiti iyi uygulaması", "İyi uygulama", "Tüm sektörler",
          _her_zaman, _k_svhc_kanit,
          ["Tedarikçi REACH/SVHC beyanını veya test raporunu belge kasasına ekleyin."]),
    Kural("G09", "Belgelerin geçerliliği", "Kritik", 10,
          "İlgili sertifika / beyan şartları", "Yürürlükte", "Tüm sektörler",
          _her_zaman, _k_belge_suresi,
          ["Süresi dolan belgeyi düzenleyen kuruluşla yenileme sürecini başlatın.",
           "Yenilenen belgenin yeni bitiş tarihini belge kasasına girin."]),
    Kural("G10", "Yenileme zamanı yaklaşan belgeler", "Orta", 2,
          "İç kontrol", "İyi uygulama", "Tüm sektörler",
          _her_zaman, _k_belge_yaklasan,
          ["60 gün içinde süresi dolacak belgeler için denetim tarihini planlayın."]),
    Kural("G11", "Belge türlerinin doğru sınıflandırılması", "Orta", 3,
          "ESPR — doğrulanabilir bilgi ilkesi", "İyi uygulama", "Tüm sektörler",
          _her_zaman, _k_belge_sinif,
          ["ISO 9001 / ISO 14001 / IATF gibi kuruluş belgelerini ürün sertifikası olarak göstermeyin.",
           "Ürüne özgü uygunluğu gösteren sertifika, beyan veya test raporu ekleyin."]),
    Kural("G12", "Çevre iddialarının kanıtı", "Yüksek", 8,
          "Direktif (AB) 2024/825 (yeşil dönüşüm için tüketicinin güçlendirilmesi); Haksız Ticari Uygulamalar Direktifi", "Yürürlükte", "Tüm sektörler",
          _her_zaman, _k_iddia,
          ["'Organik', 'geri dönüştürülmüş', 'çevre dostu' gibi ifadeleri yalnızca belgeyle destekleyebiliyorsanız kullanın.",
           "Organik için GOTS/OCS, geri dönüştürülmüş için GRS/RCS gibi tanınmış bir sertifika ekleyin.",
           "Genel ifadeler ('çevre dostu', 'sürdürülebilir') yerine ölçülebilir ve doğrulanmış bilgi verin."]),
    Kural("G13", "Geri dönüştürülmüş içerik kanıtı", "Yüksek", 6,
          "ESPR Ek I; Direktif (AB) 2024/825", "Beklenen DPP verisi", "Tüm sektörler",
          _her_zaman, _k_geri_donusum_kanit,
          ["Geri dönüştürülmüş içerik oranını destekleyen GRS/RCS (tekstil) veya EPD/üretici beyanı (metal) ekleyin."]),
    Kural("G14", "Bakım, onarım ve ömür sonu bilgisi", "Orta", 5,
          "ESPR md. 5 ve Ek I — dayanıklılık, onarılabilirlik, geri dönüşüm", "Beklenen DPP verisi", "Tüm sektörler",
          _her_zaman, _k_bakim,
          ["Kullanıcıya yönelik bakım/onarım bilgisini ve ürünün ömür sonunda nasıl bertaraf edileceğini yazın."]),
    Kural("G15", "Karbon / çevresel ayak izi verisi", "Bilgi", 3,
          "ESPR Ek I (yetki tüzükleriyle zorunlu hale gelebilir); alıcı talepleri", "Beklenen DPP verisi", "Tüm sektörler",
          lambda b: b.sektor.kod not in ("demir_celik", "aluminyum"), _k_karbon,
          ["Bugün zorunlu değil; ancak AB'li alıcılar giderek talep ediyor.",
           "Hesaplamayı ISO 14067 veya PEF yöntemiyle yaptırın ve yöntemi belirtin."]),
    Kural("G16", "AB'de sorumlu ekonomik operatör", "Kritik", 10,
          "Genel Ürün Güvenliği Tüzüğü (AB) 2023/988 md. 16 (13.12.2024'ten beri uygulanıyor)", "Yürürlükte", "Tüketici ürünleri",
          lambda b: b.tuketici, _k_gpsr,
          ["AB pazarına doğrudan satış yapıyorsanız AB'de yerleşik bir sorumlu kişi (ithalatçı, yetkili temsilci veya hizmet sağlayıcı) belirleyin.",
           "Unvan, posta adresi ve e-posta bilgisi ürün, ambalaj veya beraberindeki belgede yer almalıdır."]),
    Kural("G17", "Tedarik zinciri aşamaları", "Orta", 5,
          "ESPR Ek III — izlenebilirlik; durum tespiti iyi uygulaması", "Beklenen DPP verisi", "Tüm sektörler",
          _her_zaman, _k_tedarik,
          ["'Tedarik_Zinciri' sayfasına ürünün en az hammadde ve nihai üretim aşamalarını, tedarikçi ve ülke bilgisiyle girin."]),

    # --- Tekstil ---
    Kural("T01", "Tekstil lif bileşimi", "Kritik", 10,
          "Tekstil Etiketleme Tüzüğü (AB) 1007/2011", "Yürürlükte", "Tekstil",
          _sektor("tekstil"), _k_tekstil_lif,
          ["Lif adlarını Tüzük Ek I'deki adlarla ve ağırlıkça yüzdeleriyle girin (ör. Pamuk:95;Elastan:5).",
           "Etiketteki bileşimle sistemdeki bileşimin aynı olduğunu kontrol edin."]),
    Kural("T02", "Tekstilde kimyasal uygunluk kanıtı", "Yüksek", 8,
          "REACH Ek XVII (azo boyar maddeler, ağır metaller, PFAS kısıtlamaları vb.)", "Yürürlükte", "Tekstil",
          _sektor("tekstil", "deri_ayakkabi"), _k_tekstil_kimyasal,
          ["Akredite laboratuvardan REACH Ek XVII test raporu alın veya OEKO-TEX gibi tanınmış etiket kullanın.",
           "Boyahane ve kimyasal tedarikçilerinden ZDHC uyum beyanı isteyin."]),

    # --- Elektrik-elektronik ve beyaz eşya ---
    Kural("E01", "AB Uygunluk Beyanı (CE)", "Kritik", 10,
          "Alçak Gerilim Direktifi 2014/35/AB; EMC Direktifi 2014/30/AB; Telsiz Ekipmanı Direktifi 2014/53/AB", "Yürürlükte", "Elektronik, beyaz eşya",
          _sektor("elektronik", "beyaz_esya"), _k_ce,
          ["Ürüne uygulanan direktifleri belirleyin, teknik dosyayı hazırlayın.",
           "Gerekli testleri yaptırıp AB Uygunluk Beyanını düzenleyin ve belge kasasına ekleyin."]),
    Kural("E02", "RoHS uygunluğu", "Kritik", 8,
          "RoHS Direktifi 2011/65/AB", "Yürürlükte", "Elektronik, beyaz eşya",
          _sektor("elektronik", "beyaz_esya"), _k_rohs,
          ["Komponent tedarikçilerinden RoHS beyanı toplayın; riskli parçalar için XRF / laboratuvar testi yaptırın."]),
    Kural("E03", "WEEE üretici kaydı", "Yüksek", 5,
          "AEEE (WEEE) Direktifi 2012/19/AB", "Yürürlükte", "Elektronik, beyaz eşya",
          _sektor("elektronik", "beyaz_esya"), _k_weee,
          ["Satış yapılan her AB ülkesinde WEEE kaydının kim tarafından yapıldığını (ithalatçı / yetkili temsilci) netleştirin.",
           "Kayıt numarasını belge kasasına ekleyin."]),
    Kural("E04", "Enerji etiketi (EPREL)", "Yüksek", 5,
          "Enerji Etiketleme Tüzüğü (AB) 2017/1369", "Yürürlükte", "Beyaz eşya",
          _sektor("beyaz_esya"), _k_eprel,
          ["Enerji etiketi gerektiren ürünleri EPREL veritabanına kaydedin ve kayıt numarasını girin."]),

    # --- Batarya ---
    Kural("B01", "Batarya kategorisi", "Yüksek", 5,
          "Batarya Tüzüğü (AB) 2023/1542 md. 3 tanımlar", "Yürürlükte", "Batarya",
          _sektor("batarya"), _k_batarya_kategori,
          ["Bataryanın EV, LMT (hafif ulaşım aracı), endüstriyel veya taşınabilir olduğunu belirtin."]),
    Kural("B02", "Batarya pasaportu verileri", "Kritik", 10,
          "Batarya Tüzüğü (AB) 2023/1542 md. 77 — 18 Şubat 2027'den itibaren zorunlu", "Yürürlükte (18.02.2027)", "EV, LMT ve 2 kWh üzeri endüstriyel bataryalar",
          _batarya_pasaport_kapsaminda, _k_batarya,
          ["Batarya kimyası, kapasite, karbon ayak izi ve benzersiz tanımlayıcıyı tamamlayın.",
           "Pasaport verisini barındıracak sistemi ve QR kod yerleşimini 18.02.2027 öncesi hazırlayın."]),
    Kural("B03", "Bataryada CE / uygunluk beyanı", "Kritik", 8,
          "Batarya Tüzüğü (AB) 2023/1542 md. 18 ve 20", "Yürürlükte", "Batarya",
          _sektor("batarya"), _k_ce,
          ["Batarya için AB Uygunluk Beyanı düzenleyin ve belge kasasına ekleyin."]),

    # --- Demir-çelik, alüminyum ---
    Kural("M01", "CBAM gömülü emisyon verisi", "Kritik", 10,
          "SKDM (CBAM) Tüzüğü (AB) 2023/956 — kesin dönem 1 Ocak 2026'dan itibaren", "Yürürlükte", "Demir-çelik, alüminyum",
          _sektor("demir_celik", "aluminyum"), _k_cbam,
          ["Tesis bazında doğrudan ve dolaylı emisyonları AB yöntemine göre hesaplayın.",
           "Ton ürün başına gömülü emisyonu ve tesis tanımlayıcısını AB'li ithalatçınızla paylaşın.",
           "Mümkünse verileri akredite doğrulayıcıya doğrulatın."]),
    Kural("M02", "Metalde geri dönüştürülmüş içerik", "Orta", 4,
          "ESPR demir-çelik / alüminyum yetki tüzükleri (hazırlık aşamasında)", "Beklenen DPP verisi", "Demir-çelik, alüminyum",
          _sektor("demir_celik", "aluminyum"),
          lambda b: (b.var("Geri_Donusturulmus_Icerik_Yuzde"), "Geri dönüştürülmüş içerik oranı " + ("girilmiş" if b.var("Geri_Donusturulmus_Icerik_Yuzde") else "girilmemiş")),
          ["Hurda girdi oranından geri dönüştürülmüş içerik yüzdesini hesaplayıp girin."]),

    # --- Mobilya / ahşap ---
    Kural("W01", "Ahşap için EUDR durum tespiti", "Kritik", 10,
          "Ormansızlaşma Tüzüğü (AB) 2023/1115 (EUDR) — uygulama takvimi güncel duyurulardan teyit edilmeli", "Yürürlükte / takvim teyit edilmeli", "Ahşap/kâğıt içeren ürünler",
          _ahsap_iceriyor, _k_eudr,
          ["Ahşabın hasat edildiği arazinin coğrafi konumunu tedarikçiden alın.",
           "AB'li ithalatçınızın durum tespit beyanı (DDS) için ihtiyaç duyduğu verileri hazırlayın."]),

    # --- Otomotiv ---
    Kural("A01", "IMDS malzeme kaydı", "Yüksek", 6,
          "Araç Ömrünü Tamamlamış Araçlar mevzuatı; REACH; OEM tedarikçi şartnameleri", "Yürürlükte (müşteri şartı)", "Otomotiv yan sanayi",
          _sektor("otomotiv"), _k_imds,
          ["Parçanın malzeme verisini IMDS'ye girip OEM müşterinize gönderin ve kayıt numarasını ekleyin."]),

    # --- Lastik ---
    Kural("L01", "Lastik etiketi (EPREL)", "Yüksek", 6,
          "Lastik Etiketleme Tüzüğü (AB) 2020/740", "Yürürlükte", "Lastik",
          _sektor("lastik"), _k_eprel,
          ["Lastiği EPREL'e kaydedip kayıt numarasını girin."]),

    # --- Oyuncak ---
    Kural("O01", "Oyuncak güvenliği", "Kritik", 10,
          "Oyuncak Güvenliği mevzuatı ((AB) 2025/2509 ile DPP öngörülmektedir); EN 71", "Yürürlükte", "Oyuncak",
          _sektor("oyuncak"), _k_oyuncak,
          ["EN 71 testlerini yaptırın, AB Uygunluk Beyanını düzenleyin ve belge kasasına ekleyin."]),

    # --- Deterjan / kimyasal ---
    Kural("K01", "Güvenlik Bilgi Formu", "Kritik", 8,
          "REACH md. 31; CLP Tüzüğü (AT) 1272/2008; Deterjan mevzuatı", "Yürürlükte", "Deterjan ve kimyasal",
          _sektor("deterjan"), _k_sds,
          ["Ürün için hedef ülke dilinde güncel Güvenlik Bilgi Formu hazırlayın."]),

    # --- Yapı malzemeleri ---
    Kural("Y01", "Performans beyanı ve CE", "Kritik", 10,
          "Yapı Malzemeleri Tüzüğü (AB) 2024/3110", "Yürürlükte", "Yapı malzemeleri",
          _sektor("insaat"), _k_dop,
          ["Uyumlaştırılmış standarda göre performans beyanı (DoP) düzenleyin, CE işaretinin dayanağını belge kasasına ekleyin."]),
]
KURAL_SOZLUK = {k.kod: k for k in KURALLAR}


def kural_tablosu() -> pd.DataFrame:
    return pd.DataFrame([{
        "Kod": k.kod, "Kural": k.ad, "Seviye": k.seviye, "Ağırlık": k.agirlik,
        "Kapsam": k.kapsam, "Durum": k.durum, "Dayanak": k.dayanak,
    } for k in KURALLAR])


def _durum_etiketi(skor: float, kritik_eksik: int) -> str:
    if kritik_eksik > 0:
        return "Yüksek risk"
    if skor >= 85:
        return "Hazır"
    return "Eksikleri var"


DURUM_SIMGE = {"Hazır": "🟢", "Eksikleri var": "🟡", "Yüksek risk": "🔴"}


def degerlendir(veri: VeriSeti, bugun: Optional[date] = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Döner:
      ozet     — ürün başına skor ve durum
      bulgular — ürün x kural değerlendirmeleri (Uygun / Eksik)
      kasa     — sınıflandırılmış belge kasası
    """
    bugun = bugun or date.today()
    urunler = tekil_urunler(veri.urunler)
    kasa = belge_kasasi(veri.belgeler, bugun)

    gtinler = urunler["GTIN"].map(gtin_temizle)
    sayim = gtinler[gtinler != ""].value_counts()
    gtin_tekrar = set(sayim[sayim > 1].index)

    tedarik_grup = {k: g for k, g in veri.tedarik.groupby("Urun_Kodu")} if not veri.tedarik.empty else {}
    bos_tedarik = veri.tedarik.iloc[0:0]

    ozet_satirlari, bulgu_satirlari = [], []
    for _, satir in urunler.iterrows():
        sektor = sektor_bul(satir.get("Sektor"))
        tuketici = evet_mi(satir.get("Tuketici_Urunu"))
        if tuketici is None:
            tuketici = sektor.tuketici_varsayilan
        b = Baglam(
            satir=satir, sektor=sektor, tuketici=tuketici,
            belgeler=urun_belgeleri(kasa, satir["Urun_Kodu"]),
            tedarik=tedarik_grup.get(satir["Urun_Kodu"], bos_tedarik),
            gtin_tekrarlari=gtin_tekrar, bugun=bugun,
        )
        toplam_agirlik = kazanilan = 0
        kritik_eksik = eksik_sayisi = 0
        for k in KURALLAR:
            try:
                if not k.uygulanir(b):
                    continue
                gecti, detay = k.kontrol(b)
            except Exception as hata:  # bir kuraldaki hata tüm değerlendirmeyi durdurmasın
                gecti, detay = False, f"Kural çalıştırılamadı: {hata}"
            toplam_agirlik += k.agirlik
            if gecti:
                kazanilan += k.agirlik
            else:
                eksik_sayisi += 1
                if k.seviye == "Kritik":
                    kritik_eksik += 1
            bulgu_satirlari.append({
                "Urun_Kodu": satir["Urun_Kodu"], "Urun_Adi": satir.get("Urun_Adi"), "Sektor": sektor.ad,
                "Kural_Kodu": k.kod, "Kural": k.ad, "Seviye": k.seviye, "Ağırlık": k.agirlik,
                "Sonuc": "Uygun" if gecti else "Eksik", "Detay": detay,
                "Dayanak": k.dayanak, "Mevzuat_Durumu": k.durum,
            })
        skor = round(100 * kazanilan / toplam_agirlik, 1) if toplam_agirlik else 0.0
        durum = _durum_etiketi(skor, kritik_eksik)
        ozet_satirlari.append({
            "Urun_Kodu": satir["Urun_Kodu"], "Urun_Adi": satir.get("Urun_Adi"),
            "Sektor": sektor.ad, "Sektor_Kodu": sektor.kod, "Tuketici_Urunu": "Evet" if tuketici else "Hayır",
            "Hazirlik_Skoru": skor, "Durum": durum,
            "Kritik_Eksik": kritik_eksik, "Eksik_Sayisi": eksik_sayisi,
            "Uygulanan_Kural": int(sum(1 for r in bulgu_satirlari if r["Urun_Kodu"] == satir["Urun_Kodu"])),
            "Kaynak_Dosya": satir.get("Kaynak_Dosya"),
        })

    ozet = pd.DataFrame(ozet_satirlari)
    bulgular = pd.DataFrame(bulgu_satirlari)
    if not bulgular.empty:
        bulgular["_s"] = bulgular["Seviye"].map(SEVIYE_SIRASI)
        bulgular = bulgular.sort_values(["Urun_Kodu", "Sonuc", "_s"], ascending=[True, True, True]).drop(columns="_s").reset_index(drop=True)
    return ozet, bulgular, kasa


# ---------------------------------------------------------------------------
# 9. Pasaport taslağı, erişim seviyeleri, GS1 Digital Link, JSON-LD
# ---------------------------------------------------------------------------

ERISIM_SEVIYELERI = ["Kamu", "Alıcı (B2B)", "Otorite"]
_SEVIYE_NO = {s: i for i, s in enumerate(ERISIM_SEVIYELERI)}

# (bölüm, etiket, kolon, erişim)
PASAPORT_ALANLARI: list[tuple[str, str, str, str]] = [
    ("Kimlik", "Ürün adı", "Urun_Adi", "Kamu"),
    ("Kimlik", "Ürün kodu", "Urun_Kodu", "Kamu"),
    ("Kimlik", "GTIN", "GTIN", "Kamu"),
    ("Kimlik", "Sektör", "Sektor", "Kamu"),
    ("Kimlik", "Parti / lot", "Parti_No", "Alıcı (B2B)"),
    ("Kimlik", "Üretim tarihi", "Uretim_Tarihi", "Alıcı (B2B)"),
    ("Kimlik", "GTİP (HS) kodu", "GTIP", "Alıcı (B2B)"),
    ("Aktörler", "İhracatçı / üretici", "Ihracatci_Unvan", "Kamu"),
    ("Aktörler", "AB sorumlu ekonomik operatör", "AB_Sorumlu_Operator", "Kamu"),
    ("Aktörler", "Üretim tesisi", "Uretim_Tesisi", "Alıcı (B2B)"),
    ("Aktörler", "Tesis tanımlayıcısı", "Tesis_ID", "Otorite"),
    ("Menşe ve malzeme", "Üretim ülkesi", "Uretim_Ulkesi", "Kamu"),
    ("Menşe ve malzeme", "Hammadde menşei", "Hammadde_Mensei", "Kamu"),
    ("Menşe ve malzeme", "Malzeme bileşimi", "Malzeme_Bilesimi", "Kamu"),
    ("Menşe ve malzeme", "Geri dönüştürülmüş içerik (%)", "Geri_Donusturulmus_Icerik_Yuzde", "Kamu"),
    ("Kimyasallar", "SVHC beyanı", "SVHC_Beyani", "Kamu"),
    ("Kimyasallar", "SVHC maddeler", "SVHC_Maddeler", "Kamu"),
    ("Çevre", "Çevresel iddia", "Cevresel_Iddia", "Kamu"),
    ("Çevre", "Karbon ayak izi (kg CO2e/birim)", "Karbon_Ayak_Izi_kgCO2e", "Kamu"),
    ("Çevre", "Karbon hesaplama yöntemi", "Karbon_Yontemi", "Kamu"),
    ("Çevre", "Gömülü emisyon (tCO2e/t)", "Gomulu_Emisyon_tCO2e_t", "Alıcı (B2B)"),
    ("Sektörel kayıtlar", "EPREL no", "EPREL_No", "Kamu"),
    ("Sektörel kayıtlar", "IMDS no", "IMDS_ID", "Alıcı (B2B)"),
    ("Sektörel kayıtlar", "Batarya kategorisi", "Batarya_Kategorisi", "Kamu"),
    ("Sektörel kayıtlar", "Batarya kimyası", "Batarya_Kimyasi", "Kamu"),
    ("Sektörel kayıtlar", "Batarya kapasitesi (kWh)", "Batarya_Kapasite_kWh", "Kamu"),
    ("Kullanım ve ömür sonu", "Bakım / onarım", "Bakim_Onarim_Bilgisi", "Kamu"),
    ("Kullanım ve ömür sonu", "Ömür sonu talimatı", "Omur_Sonu_Talimati", "Kamu"),
]


def gorunur_mu(alan_erisim: str, secilen: str) -> bool:
    return _SEVIYE_NO[alan_erisim] <= _SEVIYE_NO[secilen]


def digital_link(satir, cozumleyici: str) -> str:
    alan = (cozumleyici or "https://dpp.ornek.com.tr").rstrip("/")
    gecerli, _ = gtin_dogrula(satir.get("GTIN"))
    if gecerli:
        url = f"{alan}/01/{gtin14(satir.get('GTIN'))}"
        lot = metin(satir.get("Parti_No"))
        if lot:
            url += f"/10/{quote(lot, safe='')}"
        return url
    return f"{alan}/urun/{quote(metin(satir.get('Urun_Kodu')), safe='')}"


def pasaport_kimligi(satir) -> str:
    gecerli, _ = gtin_dogrula(satir.get("GTIN"))
    temel = gtin14(satir.get("GTIN")) if gecerli else metin(satir.get("Urun_Kodu"))
    lot = metin(satir.get("Parti_No")) or "MODEL"
    return f"DPP-{temel}-{lot}"


def icerik_ozeti(veri: dict) -> str:
    kopya = {k: v for k, v in veri.items() if k != "dpp:icerikOzeti"}
    ham = json.dumps(kopya, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(ham).hexdigest()


def pasaport_jsonld(satir, belgeler: pd.DataFrame, tedarik: pd.DataFrame, ozet_satir, cozumleyici: str,
                    erisim: str = "Kamu", hazirlayan: str = "") -> dict:
    """
    JSON-LD biçiminde pasaport TASLAĞI üretir.
    Not: Bu yapı EN 18216/18223 yaklaşımıyla uyumlu olacak şekilde düzenlenmiş bir örnektir;
    resmi şema ilgili yetki tüzüğü ile belirlenecektir.
    """
    def al(kolon):
        return metin(satir.get(kolon)) or None

    def g(seviye):
        return gorunur_mu(seviye, erisim)

    malzemeler, _ = malzeme_ayristir(satir.get("Malzeme_Bilesimi"))
    veri: dict = {
        "@context": {"@vocab": "https://schema.org/", "dpp": f"{(cozumleyici or 'https://dpp.ornek.com.tr').rstrip('/')}/vocab#"},
        "@type": "Product",
        "@id": digital_link(satir, cozumleyici),
        "dpp:pasaportKimligi": pasaport_kimligi(satir),
        "dpp:semaSurumu": f"taslak-{SURUM}",
        "dpp:erisimSeviyesi": erisim,
        "name": al("Urun_Adi"),
        "sku": al("Urun_Kodu"),
        "gtin": gtin_temizle(satir.get("GTIN")) or None,
        "category": metin(satir.get("Sektor")),
        "manufacturer": {"@type": "Organization", "name": al("Ihracatci_Unvan")},
        "dpp:abSorumluOperator": al("AB_Sorumlu_Operator"),
        "countryOfOrigin": al("Uretim_Ulkesi"),
        "dpp:hammaddeMensei": al("Hammadde_Mensei"),
        "material": [{"name": a, "dpp:oranYuzde": o} for a, o in malzemeler] or None,
        "dpp:geriDonusturulmusIcerikYuzde": sayi(satir.get("Geri_Donusturulmus_Icerik_Yuzde")),
        "dpp:svhc": {"beyan": metin(satir.get("SVHC_Beyani"), yok_bos=False) or None, "maddeler": al("SVHC_Maddeler")},
        "dpp:cevre": {
            "iddia": al("Cevresel_Iddia"),
            "karbonAyakIziKgCO2e": sayi(satir.get("Karbon_Ayak_Izi_kgCO2e")),
            "yontem": al("Karbon_Yontemi"),
        },
        "dpp:kullanim": {"bakimOnarim": al("Bakim_Onarim_Bilgisi"), "omurSonu": al("Omur_Sonu_Talimati")},
    }
    if g("Alıcı (B2B)"):
        veri["dpp:partiNo"] = al("Parti_No")
        veri["dpp:gtip"] = al("GTIP")
        veri["dpp:uretimTarihi"] = al("Uretim_Tarihi")
        veri["dpp:uretimTesisi"] = al("Uretim_Tesisi")
        veri["dpp:cevre"]["gomuluEmisyonTCO2eT"] = sayi(satir.get("Gomulu_Emisyon_tCO2e_t"))
        veri["dpp:imds"] = al("IMDS_ID")
        veri["dpp:tedarikZinciri"] = [
            {"sira": metin(r.get("Asama_Sira")), "asama": metin(r.get("Asama")),
             "tedarikci": metin(r.get("Tedarikci")), "ulke": metin(r.get("Ulke"))}
            for _, r in tedarik.iterrows()
        ]
    if g("Otorite"):
        veri["dpp:tesisKimligi"] = al("Tesis_ID")
    veri["dpp:belgeler"] = [
        {"tur": r.get("Kanonik_Tur"), "kategori": r.get("Kategori"),
         **({"no": metin(r.get("Belge_No")), "duzenleyen": metin(r.get("Duzenleyen"))} if g("Alıcı (B2B)") else {}),
         "gecerlilikBitis": metin(r.get("Gecerlilik_Bitis")) or None, "durum": r.get("Durum")}
        for _, r in belgeler.iterrows()
    ]
    if ozet_satir is not None:
        veri["dpp:hazirlik"] = {
            "skor": float(ozet_satir["Hazirlik_Skoru"]),
            "durum": ozet_satir["Durum"],
            "not": "Hazırlık skoru bir ön kontrol göstergesidir; resmi uygunluk kararı değildir.",
        }
    veri["dpp:olusturulma"] = datetime.now().isoformat(timespec="seconds")
    if hazirlayan:
        veri["dpp:hazirlayan"] = hazirlayan

    def temizle(o):
        if isinstance(o, dict):
            return {k: temizle(v) for k, v in o.items() if v not in (None, "", [], {})}
        if isinstance(o, list):
            return [temizle(v) for v in o]
        return o

    veri = temizle(veri)
    veri["dpp:icerikOzeti"] = icerik_ozeti(veri)
    return veri


# ---------------------------------------------------------------------------
# 10. Mevzuat rehberi (bilgi amaçlı)
# ---------------------------------------------------------------------------

MEVZUAT_REHBERI: list[dict] = [
    {"Kapsam": "Tüm sektörler", "Mevzuat": "ESPR — Sürdürülebilir Ürünler için Ekotasarım Tüzüğü (AB) 2024/1781",
     "Ne getiriyor": "DPP'nin çerçevesi; ürün grubu bazında yetki tüzükleriyle zorunlu hale gelir", "Durum / tarih": "Yürürlükte (18.07.2024); ürün bazlı zorunluluklar yetki tüzükleriyle"},
    {"Kapsam": "Tüm sektörler", "Mevzuat": "DPP Registry — Uygulama Tüzüğü (AB) 2026/1778",
     "Ne getiriyor": "Pasaportların merkezi kaydı; gümrükte elektronik kontrol imkânı", "Durum / tarih": "Registry 20.07.2026'da açıldı; kayıt yükümlülüğü ilgili yetki tüzüğü uygulanınca doğar"},
    {"Kapsam": "Tüm sektörler", "Mevzuat": "EN 18216, 18219, 18220, 18221, 18222, 18223 (CEN/CENELEC JTC 24)",
     "Ne getiriyor": "Tanımlayıcı, veri taşıyıcı, API, saklama ve birlikte çalışabilirlik standartları", "Durum / tarih": "Mayıs 2026'da yayımlandı"},
    {"Kapsam": "Tüketici ürünleri", "Mevzuat": "Genel Ürün Güvenliği Tüzüğü (AB) 2023/988 (GPSR)",
     "Ne getiriyor": "AB'de sorumlu ekonomik operatör, izlenebilirlik ve iletişim bilgisi", "Durum / tarih": "13.12.2024'ten beri uygulanıyor"},
    {"Kapsam": "Tüm sektörler", "Mevzuat": "REACH (AT) 1907/2006",
     "Ne getiriyor": "SVHC bilgi yükümlülüğü (md. 33), Ek XVII kısıtlamaları", "Durum / tarih": "Yürürlükte"},
    {"Kapsam": "Çevre iddiası kullananlar", "Mevzuat": "Direktif (AB) 2024/825",
     "Ne getiriyor": "Kanıtsız genel çevre iddiaları ve tanınmamış etiketlerin yasaklanması", "Durum / tarih": "Üye devlet uygulaması 27.09.2026"},
    {"Kapsam": "Ambalajlı tüm ürünler", "Mevzuat": "Ambalaj ve Ambalaj Atıkları Tüzüğü (AB) 2025/40 (PPWR)",
     "Ne getiriyor": "Ambalaj tasarım, etiket ve geri dönüştürülebilirlik şartları", "Durum / tarih": "Genel uygulama 12.08.2026; şartlar kademeli"},
    {"Kapsam": "Tekstil", "Mevzuat": "Tekstil Etiketleme Tüzüğü (AB) 1007/2011",
     "Ne getiriyor": "Lif bileşimi etiketi", "Durum / tarih": "Yürürlükte"},
    {"Kapsam": "Tekstil", "Mevzuat": "ESPR tekstil yetki tüzüğü",
     "Ne getiriyor": "Tekstil DPP veri alanları", "Durum / tarih": "Beklenen kabul 2027; uygulama en az 18 ay sonra (~2028–2029)"},
    {"Kapsam": "Tekstil / giyim", "Mevzuat": "ESPR md. 25 — satılmayan ürünlerin imhası yasağı",
     "Ne getiriyor": "Satılmayan giyim ve ayakkabının imha yasağı (büyük işletmeler)", "Durum / tarih": "19.07.2026'dan itibaren"},
    {"Kapsam": "Elektronik, beyaz eşya", "Mevzuat": "LVD 2014/35, EMC 2014/30, RoHS 2011/65, WEEE 2012/19",
     "Ne getiriyor": "CE, tehlikeli madde sınırları, üretici sorumluluğu", "Durum / tarih": "Yürürlükte"},
    {"Kapsam": "Beyaz eşya, lastik", "Mevzuat": "Enerji Etiketleme (AB) 2017/1369; Lastik Etiketleme (AB) 2020/740",
     "Ne getiriyor": "EPREL kaydı ve etiket", "Durum / tarih": "Yürürlükte"},
    {"Kapsam": "Batarya", "Mevzuat": "Batarya Tüzüğü (AB) 2023/1542",
     "Ne getiriyor": "EV, LMT ve 2 kWh üzeri endüstriyel bataryalar için batarya pasaportu", "Durum / tarih": "Pasaport 18.02.2027'den itibaren zorunlu"},
    {"Kapsam": "Demir-çelik, alüminyum", "Mevzuat": "SKDM / CBAM (AB) 2023/956",
     "Ne getiriyor": "Gömülü emisyon verisi; AB'li ithalatçı beyan eder", "Durum / tarih": "Kesin dönem 01.01.2026'dan itibaren"},
    {"Kapsam": "Demir-çelik, alüminyum", "Mevzuat": "ESPR demir-çelik ve alüminyum yetki tüzükleri",
     "Ne getiriyor": "DPP veri alanları, geri dönüştürülmüş içerik", "Durum / tarih": "Demir-çelik 2026 sonu, alüminyum 2027 (gösterge)"},
    {"Kapsam": "Ahşap, mobilya, kâğıt", "Mevzuat": "Ormansızlaşma Tüzüğü (AB) 2023/1115 (EUDR)",
     "Ne getiriyor": "Hasat yeri ve durum tespiti beyanı", "Durum / tarih": "Uygulama takvimi ertelendi; güncel tarihi teyit edin"},
    {"Kapsam": "Mobilya, şilte, lastik", "Mevzuat": "ESPR yetki tüzükleri",
     "Ne getiriyor": "DPP veri alanları", "Durum / tarih": "Lastik 2027, mobilya 2028 (gösterge)"},
    {"Kapsam": "Oyuncak", "Mevzuat": "Oyuncak Güvenliği Tüzüğü (AB) 2025/2509",
     "Ne getiriyor": "Oyuncaklar için DPP ve sıkılaştırılmış kimyasal kurallar", "Durum / tarih": "Geçiş süreli; tarihleri teyit edin"},
    {"Kapsam": "Yapı malzemeleri", "Mevzuat": "Yapı Malzemeleri Tüzüğü (AB) 2024/3110",
     "Ne getiriyor": "DoP, CE ve ileride dijital pasaport", "Durum / tarih": "Kademeli uygulama"},
]


def mevzuat_tablosu() -> pd.DataFrame:
    return pd.DataFrame(MEVZUAT_REHBERI)


# ---------------------------------------------------------------------------
# 11. Kural tabanlı asistan (API anahtarı gerektirmez)
# ---------------------------------------------------------------------------

def asistan_yaniti(soru: str, ozet: pd.DataFrame, bulgular: pd.DataFrame, kasa: pd.DataFrame) -> str:
    s = tr_norm(soru)
    if ozet.empty:
        return "Henüz değerlendirilmiş ürün yok. Sol menüden Excel dosyası yükleyin veya örnek veriyi açın."

    # Belirli bir ürün kodu geçiyorsa reçete ver
    for kod in ozet["Urun_Kodu"]:
        if tr_norm(kod) and tr_norm(kod) in s:
            return urun_recetesi_metni(kod, ozet, bulgular)

    if any(k in s for k in ("merhaba", "selam", "yardim", "ne yapabilirsin")):
        return ("Şunları sorabilirsiniz:\n\n- *Hangi ürünlerde yüksek risk var?*\n- *Süresi dolan belgeler hangileri?*\n"
                "- *En sık eksik ne?*\n- *Tekstil / elektronik / batarya için ne gerekiyor?*\n- *TK-1001 için ne yapmalıyım?* (ürün kodu yazın)\n"
                "- *Takvim nedir, ne zaman zorunlu?*")

    if any(k in s for k in ("belge", "sertifika", "sure", "dolan", "yenile")):
        if kasa.empty:
            return "Belge kasasında kayıt yok. 'Belgeler' sayfası ekleyin veya belge türlerini girin."
        riskli = kasa[kasa["Durum"].isin(["Süresi dolmuş", "30 gün içinde doluyor", "60 gün içinde doluyor"])]
        if riskli.empty:
            return f"Belge kasasındaki {len(kasa)} belgenin hiçbirinin süresi 60 gün içinde dolmuyor."
        satirlar = [f"- **{r.Urun_Kodu}** — {r.Kanonik_Tur}: {r.Durum} ({r.Gecerlilik_Bitis})" for r in riskli.head(15).itertuples()]
        return f"Dikkat gerektiren {len(riskli)} belge var:\n\n" + "\n".join(satirlar)

    if any(k in s for k in ("en sik", "en cok", "genel", "ozet", "durum")):
        eksik = bulgular[bulgular["Sonuc"] == "Eksik"]
        if eksik.empty:
            return "Tüm kurallar tüm ürünlerde karşılanıyor."
        sik = eksik.groupby(["Kural_Kodu", "Kural", "Seviye"]).size().sort_values(ascending=False).head(5)
        satirlar = [f"- **{kural}** ({seviye}) — {n} üründe" for (kod, kural, seviye), n in sik.items()]
        dagilim = ozet["Durum"].value_counts().to_dict()
        return (f"{len(ozet)} ürünün durumu: " + ", ".join(f"{k}: {v}" for k, v in dagilim.items())
                + "\n\nEn sık görülen eksikler:\n\n" + "\n".join(satirlar))

    if any(k in s for k in ("risk", "hata", "sorun", "hangi", "eksik", "kritik")):
        riskli = ozet[ozet["Durum"] == "Yüksek risk"].sort_values("Hazirlik_Skoru")
        if riskli.empty:
            return "Kritik eksiği olan ürün yok. Orta ve düşük seviyeli eksikler için 'Bulgular' sekmesine bakabilirsiniz."
        satirlar = [f"- **{r.Urun_Kodu}** {r.Urun_Adi} — skor {r.Hazirlik_Skoru:g}, {r.Kritik_Eksik} kritik eksik" for r in riskli.head(10).itertuples()]
        return (f"{len(riskli)} ürün yüksek riskli (en az bir kritik eksik):\n\n" + "\n".join(satirlar)
                + "\n\nBir ürünün çözüm adımları için ürün kodunu yazın.")

    if any(k in s for k in ("takvim", "ne zaman", "tarih", "zorunlu")):
        t = mevzuat_tablosu()
        return "Öne çıkan tarihler (gösterge niteliğinde, resmi kaynaktan teyit edin):\n\n" + "\n".join(
            f"- **{r['Mevzuat']}** — {r['Durum / tarih']}" for _, r in t.iterrows())

    for sek in SEKTORLER:
        if sek.kod != "diger" and (any(a in s for a in sek.anahtarlar) or tr_norm(sek.ad) in s):
            kurallar = [k for k in KURALLAR if k.kapsam == "Tüm sektörler" or sek.kod in k.kapsam.lower()
                        or tr_norm(sek.ad).split()[0] in tr_norm(k.kapsam)]
            ozel = [k for k in kurallar if k.kapsam != "Tüm sektörler"]
            satirlar = [f"- **{k.ad}** ({k.seviye}) — {k.dayanak}" for k in ozel] or ["- Bu sektör için genel kurallar uygulanıyor."]
            return f"**{sek.ad}** için programdaki sektöre özel kontroller:\n\n" + "\n".join(satirlar) + \
                "\n\nBunlara ek olarak GTIN, menşe, SVHC beyanı, belge geçerliliği gibi genel kurallar da uygulanır."

    return ("Sorunuzu tam eşleştiremedim. Örneğin *'hangi ürünlerde yüksek risk var'*, *'süresi dolan belgeler'*, "
            "*'en sık eksik'* veya bir ürün kodu yazabilirsiniz.")


def urun_recetesi_metni(kod: str, ozet: pd.DataFrame, bulgular: pd.DataFrame) -> str:
    o = ozet[ozet["Urun_Kodu"] == kod]
    if o.empty:
        return f"{kod} kodlu ürün bulunamadı."
    o = o.iloc[0]
    eksik = bulgular[(bulgular["Urun_Kodu"] == kod) & (bulgular["Sonuc"] == "Eksik")]
    if eksik.empty:
        return f"**{kod}** ({o['Urun_Adi']}) için eksik bulunmadı. Hazırlık skoru {o['Hazirlik_Skoru']:g}."
    parcalar = [f"**{kod} — {o['Urun_Adi']}** · {o['Durum']} · skor {o['Hazirlik_Skoru']:g}\n"]
    for i, r in enumerate(eksik.itertuples(), 1):
        k = KURAL_SOZLUK[r.Kural_Kodu]
        adimlar = "\n".join(f"    - {a}" for a in k.recete)
        parcalar.append(f"{i}. **{k.ad}** ({k.seviye}) — {r.Detay}\n{adimlar}")
    return "\n".join(parcalar)


def yapay_zeka_baglami(ozet: pd.DataFrame, bulgular: pd.DataFrame, kasa: pd.DataFrame, maskele: bool) -> str:
    """Dış yapay zekâ servisine gönderilecek ÖZET bağlamı hazırlar (ham veri gönderilmez)."""
    if ozet.empty:
        return "Veri yok."
    eslesme = {}
    if maskele:
        eslesme = {k: f"URUN-{i + 1:03d}" for i, k in enumerate(ozet["Urun_Kodu"])}
    m = lambda k: eslesme.get(k, k)
    satirlar = [f"Toplam ürün: {len(ozet)}. Durum dağılımı: {ozet['Durum'].value_counts().to_dict()}.",
                f"Sektör dağılımı: {ozet['Sektor'].value_counts().to_dict()}."]
    eksik = bulgular[bulgular["Sonuc"] == "Eksik"]
    for r in ozet.sort_values("Hazirlik_Skoru").head(25).itertuples():
        e = eksik[eksik["Urun_Kodu"] == r.Urun_Kodu]
        ad = "" if maskele else f" {r.Urun_Adi}"
        satirlar.append(f"- {m(r.Urun_Kodu)}{ad} [{r.Sektor}] skor {r.Hazirlik_Skoru:g} ({r.Durum}); eksikler: "
                        + "; ".join(f"{x.Kural_Kodu} {x.Kural}: {x.Detay}" for x in e.itertuples()))
    if not kasa.empty:
        satirlar.append("Belge durumları: " + str(kasa["Durum"].value_counts().to_dict()))
    return "\n".join(satirlar)


# ---------------------------------------------------------------------------
# 12. Excel çıktıları
# ---------------------------------------------------------------------------

def _sayfa_yaz(yazici, df: pd.DataFrame, ad: str):
    df.to_excel(yazici, index=False, sheet_name=ad[:31])
    ws = yazici.sheets[ad[:31]]
    for i, kolon in enumerate(df.columns, 1):
        uzunluk = max([len(str(kolon))] + [len(str(v)) for v in df[kolon].head(200).tolist()])
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(max(10, uzunluk + 2), 60)
    ws.freeze_panes = "A2"


def rapor_excel(ozet, bulgular, kasa, denetim_izi: list[dict], firma: str = "", hazirlayan: str = "") -> bytes:
    cikti = io.BytesIO()
    with pd.ExcelWriter(cikti, engine="openpyxl") as yazici:
        bilgi = pd.DataFrame([
            {"Alan": "Rapor", "Değer": "DPP Hazırlık Ön Kontrol Raporu"},
            {"Alan": "Firma", "Değer": firma},
            {"Alan": "Hazırlayan", "Değer": hazirlayan},
            {"Alan": "Oluşturulma", "Değer": datetime.now().strftime("%Y-%m-%d %H:%M")},
            {"Alan": "Program sürümü", "Değer": SURUM},
            {"Alan": "Mevzuat gözden geçirme", "Değer": MEVZUAT_GOZDEN_GECIRME},
            {"Alan": "Not", "Değer": "Bu rapor bir hazırlık ve ön kontrol çalışmasıdır; gümrük, piyasa gözetimi "
                                     "veya onaylanmış kuruluş kararı yerine geçmez."},
        ])
        _sayfa_yaz(yazici, bilgi, "Bilgi")
        _sayfa_yaz(yazici, ozet.drop(columns=["Sektor_Kodu"], errors="ignore"), "Ozet")
        eksik = bulgular[bulgular["Sonuc"] == "Eksik"].copy() if not bulgular.empty else bulgular
        if not eksik.empty:
            eksik["Cozum_Adimlari"] = eksik["Kural_Kodu"].map(lambda k: " | ".join(KURAL_SOZLUK[k].recete))
        _sayfa_yaz(yazici, eksik, "Eksikler_ve_Cozum")
        _sayfa_yaz(yazici, bulgular, "Tum_Kontroller")
        _sayfa_yaz(yazici, kasa, "Belge_Kasasi")
        _sayfa_yaz(yazici, kural_tablosu(), "Kural_Seti")
        _sayfa_yaz(yazici, pd.DataFrame(denetim_izi or [{"Zaman": "", "Kullanici": "", "Islem": "", "Detay": ""}]), "Denetim_Izi")
    return cikti.getvalue()


def veri_excel(veri: VeriSeti) -> bytes:
    """Düzenlenmiş veriyi yeniden yüklenebilir şablon biçiminde dışa aktarır."""
    cikti = io.BytesIO()
    with pd.ExcelWriter(cikti, engine="openpyxl") as yazici:
        _sayfa_yaz(yazici, veri.urunler.drop(columns=["Kaynak_Dosya"], errors="ignore"), "Urunler")
        _sayfa_yaz(yazici, veri.belgeler.drop(columns=["Kaynak_Dosya"], errors="ignore"), "Belgeler")
        _sayfa_yaz(yazici, veri.tedarik.drop(columns=["Kaynak_Dosya"], errors="ignore"), "Tedarik_Zinciri")
    return cikti.getvalue()


def _gecerli_gtin(govde12: str) -> str:
    return govde12 + str(gtin_kontrol_hanesi(govde12))


def ornek_veri() -> VeriSeti:
    """Farklı sektörlerden, bilerek eksikler içeren örnek veri seti."""
    u = [
        dict(Urun_Kodu="TK-1001", Urun_Adi="Organik Pamuk Tişört", Sektor="Tekstil", Tuketici_Urunu="Evet",
             GTIN=_gecerli_gtin("869000000001"), GTIP="6109.10", Parti_No="LOT-2026-101", Uretim_Tarihi="2026-09-15",
             Ihracatci_Unvan="Örnek Tekstil A.Ş.", Uretim_Tesisi="Bursa OSB", Tesis_ID=_gecerli_gtin("869000000901"),
             AB_Sorumlu_Operator="Beispiel Mode GmbH, Köln, info@beispiel.de", Uretim_Ulkesi="Türkiye", Hammadde_Mensei="Türkiye",
             Malzeme_Bilesimi="Pamuk:95;Elastan:5", Geri_Donusturulmus_Icerik_Yuzde=0, SVHC_Beyani="Yok",
             Cevresel_Iddia="Organik pamuk", Karbon_Ayak_Izi_kgCO2e=4.1, Karbon_Yontemi="ISO 14067",
             Bakim_Onarim_Bilgisi="30°C'de ters yıkayın", Omur_Sonu_Talimati="Tekstil geri dönüşüm noktasına bırakınız"),
        dict(Urun_Kodu="TK-1002", Urun_Adi="Geri Dönüştürülmüş Denim Pantolon", Sektor="Tekstil", Tuketici_Urunu="Evet",
             GTIN="0123456789012", GTIP="6203.42", Ihracatci_Unvan="Örnek Tekstil A.Ş.", Uretim_Ulkesi="Türkiye",
             Hammadde_Mensei="Pakistan", Malzeme_Bilesimi="Pamuk:70;Geri dönüştürülmüş pamuk:28", Geri_Donusturulmus_Icerik_Yuzde=28,
             SVHC_Beyani="Bilinmiyor"),
        dict(Urun_Kodu="EL-2001", Urun_Adi="LED Panel Armatür 40W", Sektor="Elektronik", Tuketici_Urunu="Evet",
             GTIN=_gecerli_gtin("869000000002"), GTIP="9405.11", Parti_No="EL-26-07", Ihracatci_Unvan="Örnek Aydınlatma Ltd.",
             Uretim_Tesisi="İstanbul İkitelli OSB", AB_Sorumlu_Operator="Lumen Import BV, Rotterdam, sales@lumen.nl",
             Uretim_Ulkesi="Türkiye", Hammadde_Mensei="Çin", Malzeme_Bilesimi="Alüminyum:55;Polikarbonat:30;Elektronik kart:15",
             SVHC_Beyani="Yok", Bakim_Onarim_Bilgisi="LED sürücü değiştirilebilir", Omur_Sonu_Talimati="WEEE toplama noktasına bırakınız"),
        dict(Urun_Kodu="BE-3001", Urun_Adi="Çamaşır Makinesi 9 kg", Sektor="Beyaz Eşya", Tuketici_Urunu="Evet",
             GTIN=_gecerli_gtin("869000000003"), GTIP="8450.11", Ihracatci_Unvan="Örnek Ev Aletleri A.Ş.", Uretim_Tesisi="Manisa OSB",
             Uretim_Ulkesi="Türkiye", Hammadde_Mensei="Türkiye", Malzeme_Bilesimi="Çelik:60;Plastik:30;Bakır:5;Diğer:5",
             SVHC_Beyani="Yok", EPREL_No="1234567", Bakim_Onarim_Bilgisi="Yedek parça 10 yıl", Omur_Sonu_Talimati="WEEE"),
        dict(Urun_Kodu="DC-4001", Urun_Adi="İnşaat Demiri B500C", Sektor="Demir-Çelik", Tuketici_Urunu="Hayır",
             GTIN=_gecerli_gtin("869000000004"), GTIP="7214.20", Ihracatci_Unvan="Örnek Çelik A.Ş.", Uretim_Tesisi="İskenderun",
             Tesis_ID=_gecerli_gtin("869000000904"), Uretim_Ulkesi="Türkiye", Hammadde_Mensei="Türkiye",
             Malzeme_Bilesimi="Çelik:100", Geri_Donusturulmus_Icerik_Yuzde=85, SVHC_Beyani="Yok", Gomulu_Emisyon_tCO2e_t=0.48,
             Omur_Sonu_Talimati="Hurda olarak geri kazanılır", Bakim_Onarim_Bilgisi="—"),
        dict(Urun_Kodu="MB-5001", Urun_Adi="Meşe Masa (doğal ahşap)", Sektor="Mobilya", Tuketici_Urunu="Evet",
             GTIN=_gecerli_gtin("869000000005"), GTIP="9403.60", Ihracatci_Unvan="Örnek Mobilya Ltd.", Uretim_Tesisi="Kayseri OSB",
             Uretim_Ulkesi="Türkiye", Hammadde_Mensei="Ukrayna", Malzeme_Bilesimi="Meşe:90;Çelik:10", SVHC_Beyani="Yok",
             Cevresel_Iddia="Doğal ahşap"),
        dict(Urun_Kodu="BT-6001", Urun_Adi="E-Bisiklet Bataryası 0,5 kWh", Sektor="Batarya", Tuketici_Urunu="Evet",
             GTIN=_gecerli_gtin("869000000006"), GTIP="8507.60", Ihracatci_Unvan="Örnek Enerji A.Ş.", Uretim_Tesisi="Ankara OSTİM",
             AB_Sorumlu_Operator="EBike Parts SAS, Lyon, contact@ebp.fr", Uretim_Ulkesi="Türkiye", Hammadde_Mensei="Çin",
             Malzeme_Bilesimi="Hücre:70;Kasa:20;BMS:10", SVHC_Beyani="Yok", Batarya_Kategorisi="LMT", Batarya_Kimyasi="NMC",
             Batarya_Kapasite_kWh=0.5),
        dict(Urun_Kodu="OT-7001", Urun_Adi="Fren Balatası", Sektor="Otomotiv", Tuketici_Urunu="Hayır",
             GTIN=_gecerli_gtin("869000000007"), GTIP="6813.81", Ihracatci_Unvan="Örnek Otomotiv San. A.Ş.", Uretim_Tesisi="Bursa",
             Uretim_Ulkesi="Türkiye", Hammadde_Mensei="Türkiye", Malzeme_Bilesimi="Çelik:45;Reçine:20;Lif:20;Dolgu:15",
             SVHC_Beyani="Yok", IMDS_ID="123456789", Bakim_Onarim_Bilgisi="Aşınma göstergesine göre değiştirin",
             Omur_Sonu_Talimati="Yetkili atık firmasına"),
    ]
    b = [
        dict(Urun_Kodu="TK-1001", Belge_Turu="GOTS", Belge_No="CU-889911", Duzenleyen="Control Union", Gecerlilik_Bitis="2027-08-31", Kapsam="Örme ürün"),
        dict(Urun_Kodu="TK-1001", Belge_Turu="OEKO-TEX Standard 100", Belge_No="OT-55621", Duzenleyen="Hohenstein", Gecerlilik_Bitis=(date.today() + timedelta(days=40)).isoformat()),
        dict(Urun_Kodu="TK-1002", Belge_Turu="ISO-9001", Belge_No="Q-1200", Duzenleyen="TSE", Gecerlilik_Bitis="2028-01-01"),
        dict(Urun_Kodu="TK-1002", Belge_Turu="GRS", Belge_No="GRS-778", Duzenleyen="Control Union", Gecerlilik_Bitis="2025-12-31"),
        dict(Urun_Kodu="EL-2001", Belge_Turu="CE Uygunluk Beyanı", Belge_No="DoC-2026-14"),
        dict(Urun_Kodu="EL-2001", Belge_Turu="RoHS test raporu", Belge_No="SGS-RH-22", Duzenleyen="SGS", Gecerlilik_Bitis="2027-03-01"),
        dict(Urun_Kodu="BE-3001", Belge_Turu="CE Uygunluk Beyanı", Belge_No="DoC-BE-9"),
        dict(Urun_Kodu="BE-3001", Belge_Turu="RoHS beyanı", Belge_No="RH-BE-9"),
        dict(Urun_Kodu="BE-3001", Belge_Turu="WEEE kaydı (Almanya)", Belge_No="DE 12345678"),
        dict(Urun_Kodu="DC-4001", Belge_Turu="EPD", Belge_No="EPD-TR-2026-01", Duzenleyen="EPD Türkiye", Gecerlilik_Bitis="2031-01-01"),
        dict(Urun_Kodu="MB-5001", Belge_Turu="FSC", Belge_No="FSC-C123456", Duzenleyen="SGS", Gecerlilik_Bitis="2028-05-01"),
        dict(Urun_Kodu="BT-6001", Belge_Turu="CE Uygunluk Beyanı", Belge_No="DoC-BT-1"),
        dict(Urun_Kodu="OT-7001", Belge_Turu="IATF 16949", Belge_No="IATF-0091", Duzenleyen="TÜV", Gecerlilik_Bitis="2027-11-01"),
        dict(Urun_Kodu="*", Belge_Turu="ISO 14001", Belge_No="EMS-001", Duzenleyen="TSE", Gecerlilik_Bitis="2028-06-30", Kapsam="Firma geneli"),
    ]
    t = [
        dict(Urun_Kodu="TK-1001", Asama_Sira=1, Asama="Pamuk / iplik", Tedarikci="Örnek İplik Ltd.", Ulke="Türkiye"),
        dict(Urun_Kodu="TK-1001", Asama_Sira=2, Asama="Örme kumaş", Tedarikci="Örnek Örme A.Ş.", Ulke="Türkiye"),
        dict(Urun_Kodu="TK-1001", Asama_Sira=3, Asama="Boya-terbiye", Tedarikci="Örnek Boya Ltd.", Ulke="Türkiye"),
        dict(Urun_Kodu="TK-1001", Asama_Sira=4, Asama="Konfeksiyon", Tedarikci="Örnek Tekstil A.Ş.", Ulke="Türkiye"),
        dict(Urun_Kodu="EL-2001", Asama_Sira=1, Asama="LED çip ve sürücü", Tedarikci="Shenzhen Example Co.", Ulke="Çin"),
        dict(Urun_Kodu="EL-2001", Asama_Sira=2, Asama="Montaj", Tedarikci="Örnek Aydınlatma Ltd.", Ulke="Türkiye"),
        dict(Urun_Kodu="DC-4001", Asama_Sira=1, Asama="Hurda toplama", Tedarikci="Çeşitli", Ulke="Türkiye"),
        dict(Urun_Kodu="DC-4001", Asama_Sira=2, Asama="Ark ocağı ve haddeleme", Tedarikci="Örnek Çelik A.Ş.", Ulke="Türkiye"),
    ]
    tek = VeriSeti(pd.DataFrame(u), pd.DataFrame(b), pd.DataFrame(t))
    for df in (tek.urunler, tek.belgeler, tek.tedarik):
        df["Kaynak_Dosya"] = "Örnek veri"
    return veri_birlestir([tek])


def sablon_excel() -> bytes:
    """Boş yükleme şablonu + sütun açıklamaları + örnek satırlar."""
    cikti = io.BytesIO()
    with pd.ExcelWriter(cikti, engine="openpyxl") as yazici:
        aciklama = []
        for sayfa, sema in (("Urunler", URUN_KOLONLARI), ("Belgeler", BELGE_KOLONLARI), ("Tedarik_Zinciri", TEDARIK_KOLONLARI)):
            for kolon, zorunluluk, acik, ornek in sema:
                aciklama.append({"Sayfa": sayfa, "Sütun": kolon, "Zorunluluk": zorunluluk, "Açıklama": acik, "Örnek": ornek})
        _sayfa_yaz(yazici, pd.DataFrame(aciklama), "Aciklama")
        for sayfa, sema in (("Urunler", URUN_KOLONLARI), ("Belgeler", BELGE_KOLONLARI), ("Tedarik_Zinciri", TEDARIK_KOLONLARI)):
            df = pd.DataFrame([{k: ornek for k, _, _, ornek in sema}])
            _sayfa_yaz(yazici, df, sayfa)
        # GTIN sütununu metin biçimine al
        ws = yazici.sheets["Urunler"]
        for kolon_adi in ("GTIN", "GTIP", "Tesis_ID"):
            idx = [k for k, *_ in URUN_KOLONLARI].index(kolon_adi) + 1
            harf = ws.cell(row=1, column=idx).column_letter
            for hucre in ws[harf][1:200]:
                hucre.number_format = "@"
    return cikti.getvalue()


# ---------------------------------------------------------------------------
# 13. Denetim izi yardımcıları
# ---------------------------------------------------------------------------

def denetim_kaydi(kullanici: str, islem: str, detay: str) -> dict:
    return {"Zaman": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "Kullanici": kullanici or "Belirtilmedi",
            "Islem": islem, "Detay": detay}


def tablo_farki(eski: pd.DataFrame, yeni: pd.DataFrame, anahtar: str = "Urun_Kodu", sinir: int = 200) -> list[str]:
    """İki tablo arasındaki hücre değişikliklerini okunur satırlar halinde döndürür."""
    degisiklikler: list[str] = []
    eski = eski.reset_index(drop=True)
    yeni = yeni.reset_index(drop=True)
    if len(yeni) > len(eski):
        degisiklikler.append(f"{len(yeni) - len(eski)} satır eklendi")
    elif len(yeni) < len(eski):
        degisiklikler.append(f"{len(eski) - len(yeni)} satır silindi")
    ortak = min(len(eski), len(yeni))
    for i in range(ortak):
        for kolon in yeni.columns:
            if kolon not in eski.columns:
                continue
            a, b = eski.at[i, kolon], yeni.at[i, kolon]
            if bos_mu(a) and bos_mu(b):
                continue
            if metin(a) != metin(b):
                kimlik = metin(yeni.at[i, anahtar]) if anahtar in yeni.columns else f"satır {i + 1}"
                degisiklikler.append(f"{kimlik} · {kolon}: '{metin(a)}' → '{metin(b)}'")
                if len(degisiklikler) >= sinir:
                    degisiklikler.append("… (liste kısaltıldı)")
                    return degisiklikler
    return degisiklikler
