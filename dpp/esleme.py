"""
Akıllı sütun eşleme.

Ham Excel dosyalarındaki sütun başlıklarını platform alanlarına eşler:
  - büyük/küçük harf, boşluk, noktalama ve Türkçe karakter farkı gözetilmez
  - eş anlamlı ve İngilizce başlıklar tanınır ('Model Kodu', 'Artikel', 'SKU', 'Item code' → Ürün kodu)
  - başlık birkaç satır aşağıdaysa (rapor başlığı, boş satır) otomatik bulunur
  - sayfanın türü (ürün, malzeme, belge ...) sütunlarına bakılarak anlaşılır
  - DPP ile ilgisi olmayan bilinen sütunlar (maliyet, fiyat, stok ...) ayrıca raporlanır
  - kullanıcı her eşlemeyi ekrandan düzeltebilir
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

import pandas as pd

from .util import tr_norm

YOK_SAY = "__yok_say__"        # kullanıcının "aktarma" dediği sütunlar
DPP_DISI = "__dpp_disi__"      # tanınan ama DPP'de kullanılmayan sütunlar

# ---------------------------------------------------------------------------
# Alan kataloğu: sayfa türü → [(kanonik ad, ekran etiketi, eş anlamlılar)]
# ---------------------------------------------------------------------------

_KOD = ["urun kodu", "kod", "model", "model kodu", "model no", "stok kodu", "stok no", "sku", "urun no", "urun numarasi",
        "artikel", "artikel no", "article", "article no", "item code", "item no", "product code", "style", "style no",
        "referans", "referans no", "ref no", "parca no", "part no", "part number", "mal kodu", "urun ref"]
_TEDARIKCI = ["tedarikci", "tedarikci adi", "tedarikci unvani", "supplier", "vendor", "satici firma", "fason", "fasoncu"]
_ULKE = ["ulke", "country", "mense ulke"]

ALANLAR: dict[str, list[tuple[str, str, list[str]]]] = {
    "Urunler": [
        ("Urun_Kodu", "Ürün kodu", _KOD),
        ("Urun_Adi", "Ürün adı", ["urun adi", "urun", "urun ismi", "urun tanimi", "aciklama", "tanim", "product name", "product",
                                  "description", "item name", "model adi", "mal adi", "mal tanimi", "malin cinsi", "urun aciklamasi"]),
        ("Sektor", "Sektör", ["sektor", "sector", "kategori", "urun grubu", "grup", "category", "product group", "urun kategorisi"]),
        ("GTIP", "GTİP kodu", ["gtip", "gtip kodu", "gtip no", "hs", "hs kodu", "hs code", "hs no", "tarife kodu", "gumruk tarife",
                               "gumruk tarife kodu", "cn code", "taric", "tarife pozisyonu"]),
        ("GTIN", "GTIN / barkod", ["gtin", "barkod", "barkod no", "ean", "ean13", "ean 13", "barcode", "upc", "gtin no"]),
        ("Marka", "Marka", ["marka", "brand", "marka adi"]),
        ("Tuketici_Urunu", "Tüketici ürünü mü", ["tuketici urunu", "tuketici", "b2c", "consumer", "consumer product"]),
        ("Uretim_Tesisi", "Üretim tesisi", ["uretim tesisi", "tesis", "fabrika", "factory", "plant", "facility", "uretim tesisi adi"]),
        ("AB_Sorumlu_Operator", "AB sorumlu operatör", ["ab sorumlu operator", "ab sorumlu", "sorumlu operator", "ab ithalatci",
                                                        "ithalatci", "ab temsilci", "yetkili temsilci", "eu responsible person",
                                                        "eu responsible", "importer", "responsible person", "eu importer"]),
        ("Uretim_Ulkesi", "Üretim (menşe) ülkesi", ["uretim ulkesi", "mense", "mense ulke", "mense ulkesi", "mensei", "uretim yeri", "ulke", "country",
                                                    "country of origin", "origin", "made in", "uretildigi ulke"]),
        ("Hammadde_Mensei", "Hammadde menşei", ["hammadde mensei", "hammadde mense", "hammadde ulkesi", "raw material origin",
                                                "ham madde mensei", "hammadde mense ulkesi"]),
        ("Geri_Donusturulmus_Icerik_Yuzde", "Geri dönüştürülmüş içerik (%)",
         ["geri donusturulmus icerik", "geri donusturulmus icerik yuzde", "geri donusturulmus oran", "geri donusturulmus orani",
          "recycled content", "recycled", "geri donusum icerigi", "geri kazanilmis icerik"]),
        ("SVHC_Beyani", "SVHC beyanı", ["svhc", "svhc beyani", "reach beyani", "reach svhc", "svhc durumu", "reach", "reach durumu"]),
        ("SVHC_Maddeler", "SVHC maddeleri", ["svhc maddeler", "svhc madde", "svhc maddeleri", "cas", "cas no", "svhc cas"]),
        ("Cevresel_Iddia", "Çevresel iddia", ["cevresel iddia", "cevre iddiasi", "iddia", "green claim", "eco claim", "etiket iddiasi",
                                              "pazarlama iddiasi"]),
        ("Karbon_Ayak_Izi_kgCO2e", "Karbon ayak izi (kg CO2e)", ["karbon ayak izi", "karbon ayak izi kg", "karbon ayak izi kgco2e",
                                                                 "karbon", "co2", "co2e", "carbon footprint", "pcf", "karbon kg",
                                                                 "karbon salinimi", "emisyon kg"]),
        ("Karbon_Yontemi", "Karbon yöntemi", ["karbon yontemi", "hesaplama yontemi", "lca yontemi", "karbon hesaplama yontemi"]),
        ("Gomulu_Emisyon_tCO2e_t", "Gömülü emisyon (CBAM)", ["gomulu emisyon", "gomulu emisyon tco2e t", "cbam", "cbam emisyon",
                                                             "embedded emissions", "spesifik emisyon"]),
        ("EPREL_No", "EPREL no", ["eprel", "eprel no", "eprel kayit no", "enerji etiketi no"]),
        ("IMDS_ID", "IMDS no", ["imds", "imds no", "imds id"]),
        ("Batarya_Kategorisi", "Batarya kategorisi", ["batarya kategorisi", "batarya kategori", "batarya tipi", "battery category"]),
        ("Batarya_Kimyasi", "Batarya kimyası", ["batarya kimyasi", "batarya kimya", "kimya", "battery chemistry", "hucre kimyasi"]),
        ("Batarya_Kapasite_kWh", "Batarya kapasitesi (kWh)", ["batarya kapasite kwh", "batarya kapasitesi", "kapasite", "kwh", "capacity"]),
        ("Bakim_Onarim_Bilgisi", "Bakım / onarım", ["bakim onarim bilgisi", "bakim", "bakim talimati", "yikama talimati", "care",
                                                    "care instructions", "onarim", "kullanim talimati", "bakim bilgisi"]),
        ("Omur_Sonu_Talimati", "Ömür sonu talimatı", ["omur sonu talimati", "omur sonu", "geri donusum talimati", "bertaraf",
                                                      "end of life", "disposal", "atik talimati"]),
        ("Parti_No", "Parti / lot no", ["parti no", "parti", "lot", "lot no", "batch", "batch no", "uretim partisi", "parti numarasi"]),
        ("Uretim_Tarihi", "Üretim tarihi", ["uretim tarihi", "production date", "imal tarihi", "uretim tarih"]),
        ("_Malzeme_Bilesimi", "Malzeme bileşimi (tek hücre)",
         ["malzeme bilesimi", "bilesim", "bilesen", "bilesenler", "kompozisyon", "icerik", "lif bilesimi", "lif orani", "hammadde",
          "malzeme", "malzemeler", "composition", "material", "materials", "fabric content", "kumas icerigi", "kumas", "lif"]),
        ("_Cevre_Sertifikasi", "Sertifika / belge türü", ["sertifika", "sertifikalar", "cevre sertifikasi", "belge", "belgeler",
                                                          "certificate", "certificates", "certification", "sertifika turu",
                                                          "standart", "standartlar"]),
        ("_Sertifika_No", "Sertifika no", ["sertifika no", "belge no", "certificate no", "sertifika numarasi"]),
        ("_Sertifika_Bitis", "Sertifika bitiş tarihi", ["sertifika bitis", "sertifika bitis tarihi", "gecerlilik", "gecerlilik tarihi",
                                                        "son gecerlilik", "bitis tarihi", "expiry", "expiry date", "valid until",
                                                        "gecerlilik bitis"]),
        ("_Tedarikci", "Ana tedarikçi", _TEDARIKCI),
        ("_Geri_Donusturulebilirlik", "Geri dönüştürülebilirlik oranı (aktarılmaz)",
         ["geri donusturulebilirlik orani", "geri donusturulebilirlik", "recyclability", "geri donusum orani"]),
        ("_Tedarikci_Ulke", "Tedarikçi ülkesi", ["tedarikci ulkesi", "tedarikci ulke", "supplier country"]),
    ],
    "Malzemeler": [
        ("Urun_Kodu", "Ürün kodu", _KOD),
        ("Malzeme", "Malzeme", ["malzeme", "malzeme adi", "bilesen", "bilesen adi", "lif", "lif turu", "hammadde", "material",
                                "component", "fiber", "kumas"]),
        ("Oran_Yuzde", "Oran (%)", ["oran yuzde", "oran", "yuzde", "yuzde oran", "percentage", "percent", "pay", "agirlik orani",
                                    "agirlikca yuzde", "oran %"]),
        ("Mense", "Menşe", ["mense", "mensei", "malzeme mensei"] + _ULKE + ["origin"]),
        ("Geri_Donusturulmus", "Geri dönüştürülmüş mü", ["geri donusturulmus", "recycled", "geri donusum"]),
        ("Tedarikci", "Tedarikçi", _TEDARIKCI),
    ],
    "Partiler": [
        ("Urun_Kodu", "Ürün kodu", _KOD),
        ("Parti_No", "Parti / lot no", ["parti no", "parti", "lot", "lot no", "batch", "batch no"]),
        ("Uretim_Tarihi", "Üretim tarihi", ["uretim tarihi", "production date", "imal tarihi", "tarih"]),
        ("Miktar", "Miktar", ["miktar", "adet", "quantity", "qty"]),
        ("Tesis", "Tesis", ["tesis", "uretim tesisi", "fabrika", "factory", "plant"]),
    ],
    "Tedarik_Zinciri": [
        ("Urun_Kodu", "Ürün kodu", _KOD),
        ("Sira", "Sıra", ["sira", "asama sira", "asama no", "adim", "step", "sira no"]),
        ("Asama", "Aşama", ["asama", "surec", "proses", "islem", "process", "stage", "uretim asamasi"]),
        ("Tedarikci", "Tedarikçi", _TEDARIKCI),
        ("Ulke", "Ülke", _ULKE + ["mense"]),
        ("Belge_No", "Belge no", ["belge no", "sertifika no", "tc no", "transaction certificate"]),
    ],
    "Belgeler": [
        ("Baglanti", "Bağlı ürün / kayıt", ["baglanti", "urun kodu", "urun", "model", "model kodu", "kod", "sku", "artikel"]),
        ("Belge_Turu", "Belge türü", ["belge turu", "sertifika", "belge", "sertifika turu", "certificate type", "certificate",
                                      "standart", "belge adi", "sertifika adi"]),
        ("Belge_No", "Belge no", ["belge no", "sertifika no", "certificate no", "lisans no", "numara", "no"]),
        ("Duzenleyen", "Düzenleyen", ["duzenleyen", "kurulus", "sertifika kurulusu", "issuer", "certification body", "belgelendirme kurulusu",
                                      "akredite kurulus", "veren kurum"]),
        ("Gecerlilik_Baslangic", "Geçerlilik başlangıcı", ["gecerlilik baslangic", "baslangic", "baslangic tarihi", "duzenleme tarihi",
                                                           "issue date", "verilis tarihi"]),
        ("Gecerlilik_Bitis", "Geçerlilik bitişi", ["gecerlilik bitis", "bitis", "bitis tarihi", "gecerlilik", "son gecerlilik",
                                                   "expiry", "expiry date", "valid until", "gecerlilik tarihi"]),
        ("Kapsam", "Kapsam", ["kapsam", "scope", "aciklama"]),
    ],
    "Tedarikciler": [
        ("Unvan", "Unvan", ["unvan", "tedarikci", "tedarikci adi", "tedarikci unvani", "firma", "firma adi", "supplier", "company"]),
        ("Ulke", "Ülke", _ULKE),
        ("Eposta", "E-posta", ["eposta", "e posta", "email", "e mail", "mail"]),
        ("Yetkili", "Yetkili", ["yetkili", "ilgili kisi", "contact", "contact person"]),
        ("Kimlik_No", "Vergi no / GLN", ["kimlik no", "vergi no", "vergi numarasi", "vkn", "gln", "tax id"]),
    ],
    "Tesisler": [
        ("Ad", "Tesis adı", ["ad", "tesis adi", "tesis", "fabrika", "fabrika adi", "factory", "plant"]),
        ("Adres", "Adres", ["adres", "address", "acik adres"]),
        ("Ulke", "Ülke", _ULKE),
        ("GLN", "GLN", ["gln", "gln no"]),
        ("Tur", "Tür", ["tur", "tesis turu", "type"]),
    ],
}

# DPP ile ilgisi olmayan, bilinçli olarak aktarılmayan sütunlar
DPP_DISI_ANAHTARLAR = ["maliyet", "birim maliyet", "fiyat", "birim fiyat", "satis fiyati", "alis fiyati", "tutar", "kdv", "doviz",
                       "para birimi", "stok", "stok miktari", "iskonto", "kar", "kar marji", "cost", "price", "unit price", "amount",
                       "currency", "margin", "toplam", "fatura", "fatura no", "siparis no", "order no", "musteri", "customer"]

SAYFA_ADI_IPUCU = {
    "Urunler": ["urun", "product", "portfoy", "katalog", "liste", "item"],
    "Malzemeler": ["malzeme", "bilesim", "bilesen", "material", "composition"],
    "Partiler": ["parti", "lot", "batch"],
    "Tedarik_Zinciri": ["tedarik zinciri", "zincir", "asama", "surec", "supply chain"],
    "Belgeler": ["belge", "sertifika", "certificate", "document"],
    "Tedarikciler": ["tedarikci", "supplier", "vendor"],
    "Tesisler": ["tesis", "fabrika", "factory", "plant"],
}
ANAHTAR_ALANLAR = {
    "Urunler": {"Urun_Kodu", "Urun_Adi", "GTIN"},
    "Malzemeler": {"Malzeme"},
    "Partiler": {"Parti_No"},
    "Tedarik_Zinciri": {"Asama"},
    "Belgeler": {"Belge_Turu"},
    "Tedarikciler": {"Unvan"},
    "Tesisler": {"Ad"},
}


def etiket(sayfa: str, kanonik: str) -> str:
    for k, e, _ in ALANLAR.get(sayfa, []):
        if k == kanonik:
            return e
    return kanonik


# ---------------------------------------------------------------------------
# Puanlama
# ---------------------------------------------------------------------------

def normal(baslik) -> str:
    """'Ürün Kodu (SKU)' → 'urun kodu sku'"""
    s = tr_norm(baslik)
    s = s.replace("%", " yuzde ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _kanonik_normal(k: str) -> str:
    return normal(k.strip("_").replace("_", " "))


def puan(baslik: str, kanonik: str, esler: list[str]) -> tuple[int, str]:
    """(0-100 puan, yöntem)"""
    h = normal(baslik)
    if not h:
        return 0, ""
    hb = h.replace(" ", "")
    adaylar = [_kanonik_normal(kanonik)] + [normal(e) for e in esler]
    en_iyi, yontem = 0, ""
    htok = set(h.split())
    for a in adaylar:
        if not a:
            continue
        ab = a.replace(" ", "")
        if h == a or hb == ab:
            return 100, "tam eşleşme"
        atok = a.split()
        if len(atok) > 1 and set(atok) <= htok:
            p = 85 - max(0, len(htok) - len(atok)) * 3
            if p > en_iyi:
                en_iyi, yontem = p, "anahtar kelime"
        elif len(atok) == 1 and atok[0] in htok and len(atok[0]) >= 3:
            p = 75 - max(0, len(htok) - 1) * 4
            if p > en_iyi:
                en_iyi, yontem = p, "anahtar kelime"
        if len(ab) >= 5 and ab in hb and en_iyi < 70:
            en_iyi, yontem = 70, "kısmi eşleşme"
        if len(ab) >= 4:
            r = SequenceMatcher(None, hb, ab).ratio()
            if r >= 0.86 and r * 80 > en_iyi:
                en_iyi, yontem = int(r * 80), "benzer yazım"
    return en_iyi, yontem


def dpp_disi_mi(baslik: str) -> bool:
    h = normal(baslik)
    return any(h == normal(a) or (normal(a) in h.split() and len(a) > 3) for a in DPP_DISI_ANAHTARLAR)


ESIK = 60


@dataclass
class SayfaEslemesi:
    tur: Optional[str]
    eslesme: dict[str, tuple[str, int, str]] = field(default_factory=dict)   # başlık → (kanonik, puan, yöntem)
    dpp_disi: list[str] = field(default_factory=list)
    taninmayan: list[str] = field(default_factory=list)
    toplam_puan: float = 0.0


def sutunlari_esle(basliklar: list[str], tur: str, elle: Optional[dict[str, str]] = None) -> SayfaEslemesi:
    """Başlıkları verilen sayfa türünün alanlarına eşler (her alan en fazla bir sütuna)."""
    elle = elle or {}
    sonuc = SayfaEslemesi(tur)
    adaylar = []
    for b in basliklar:
        if b in elle:
            continue
        for kanonik, _, esler in ALANLAR[tur]:
            p, y = puan(b, kanonik, esler)
            if p >= ESIK:
                adaylar.append((p, b, kanonik, y))
    kullanilan_alan, kullanilan_baslik = set(), set()
    for b, hedef in elle.items():
        if b in basliklar and hedef not in (YOK_SAY, DPP_DISI, ""):
            sonuc.eslesme[b] = (hedef, 100, "elle")
            kullanilan_alan.add(hedef)
            kullanilan_baslik.add(b)
        elif b in basliklar:
            kullanilan_baslik.add(b)
            (sonuc.dpp_disi if hedef == DPP_DISI else sonuc.taninmayan).append(b)
    for p, b, kanonik, y in sorted(adaylar, key=lambda x: (-x[0], basliklar.index(x[1]))):
        if b in kullanilan_baslik or kanonik in kullanilan_alan:
            continue
        sonuc.eslesme[b] = (kanonik, p, y)
        kullanilan_alan.add(kanonik)
        kullanilan_baslik.add(b)
    for b in basliklar:
        if b in kullanilan_baslik:
            continue
        (sonuc.dpp_disi if dpp_disi_mi(b) else sonuc.taninmayan).append(b)
    sonuc.toplam_puan = sum(p for _, p, _ in sonuc.eslesme.values())
    return sonuc


def sayfa_turu_bul(sayfa_adi: str, basliklar: list[str], elle_tur: Optional[str] = None,
                   elle: Optional[dict[str, str]] = None) -> SayfaEslemesi:
    """Sayfanın türünü (Urunler, Malzemeler ...) sütunlarına ve adına bakarak bulur."""
    if elle_tur in ALANLAR:
        return sutunlari_esle(basliklar, elle_tur, elle)
    ad = normal(sayfa_adi)
    if any(k in ad for k in ("aciklama", "okubeni", "readme", "talimat")):
        return SayfaEslemesi(None)
    en_iyi = SayfaEslemesi(None)
    en_iyi_skor = 0.0
    for tur in ALANLAR:
        e = sutunlari_esle(basliklar, tur, elle)
        anahtar = ANAHTAR_ALANLAR[tur] & {k for k, _, _ in e.eslesme.values()}
        if not anahtar:
            continue
        skor = e.toplam_puan + 40 * len(anahtar)
        if any(i in ad for i in SAYFA_ADI_IPUCU[tur]):
            skor += 150
        if tur == "Malzemeler" and "Oran_Yuzde" not in {k for k, _, _ in e.eslesme.values()}:
            skor -= 200
        if skor > en_iyi_skor:
            en_iyi, en_iyi_skor = e, skor
    return en_iyi


def baslik_satiri_bul(ham: pd.DataFrame, en_fazla: int = 15) -> int:
    """Başlık satırını bulur: tanınan alan sayısı en yüksek olan satır (rapor başlığı, boş satır atlanır)."""
    en_iyi, en_iyi_sayi = 0, -1
    tum = [(k, e) for liste in ALANLAR.values() for k, _, e in liste]
    for i in range(min(en_fazla, len(ham))):
        hucreler = [str(v) for v in ham.iloc[i].tolist() if isinstance(v, str) and v.strip()]
        sayi = 0
        for h in hucreler:
            if len(h) > 60:
                continue
            if max((puan(h, k, e)[0] for k, e in tum), default=0) >= 75:
                sayi += 1
        if sayi > en_iyi_sayi:
            en_iyi, en_iyi_sayi = i, sayi
    return en_iyi if en_iyi_sayi >= 2 else 0
