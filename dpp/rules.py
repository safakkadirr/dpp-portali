"""
Sürümlü kural motoru.

Her ürün için iki AYRI gösterge üretilir:
  1. Yasal uyum   — bugün yürürlükte olan şartlar (geçti / eksik)
  2. DPP hazırlığı — ileride zorunlu olacak veya iyi uygulama sayılan veriler (yüzde)

Kural sınıfları:
  "Yasal"         — yürürlükteki mevzuat. zorunlu_tarih gelecekteyse o tarihe kadar
                    "Yaklaşan yükümlülük" olarak hazırlık skoruna sayılır, tarih gelince
                    kendiliğinden yasal uyuma geçer.
  "DPP"           — DPP / yetki tüzükleriyle beklenen veri
  "İyi uygulama"  — mevzuat şartı değil; denetim ve alıcı beklentisi

Kurallar kodda tanımlıdır; ağırlık ve aktiflik platform yöneticisi tarafından
veritabanından değiştirilebilir. Her değerlendirme, kullanılan kural seti
sürümünü kaydeder.

ÖNEMLİ: Bu kurallar hazırlık ve ön kontrol amaçlıdır; resmi uygunluk kararı değildir.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Optional

from .catalog import BELGE, SEKTOR, YONETIM_SISTEMI_KODLARI, Sektor
from .util import bos_mu, gtin_dogrula, gtin_temizle, gtip_dogrula, metin, sayi, tr_norm

KURAL_SETI_TEMEL = "2026.11"
MEVZUAT_GOZDEN_GECIRME = "Kasım 2026"

SEVIYELER = ["Kritik", "Yüksek", "Orta", "Bilgi"]
SEVIYE_SIRA = {s: i for i, s in enumerate(SEVIYELER)}

DURUM_KRITIK = "Kritik eksik"
DURUM_YASAL = "Yasal eksik"
DURUM_SURUYOR = "Hazırlık sürüyor"
DURUM_HAZIR = "Hazır"
DURUMLAR = [DURUM_KRITIK, DURUM_YASAL, DURUM_SURUYOR, DURUM_HAZIR]
HAZIR_ESIGI = 80.0

_EURLEX = "https://eur-lex.europa.eu/eli/"
KAYNAK = {
    "ESPR": _EURLEX + "reg/2024/1781/oj",
    "GPSR": _EURLEX + "reg/2023/988/oj",
    "REACH": _EURLEX + "reg/2006/1907/oj",
    "YESIL": _EURLEX + "dir/2024/825/oj",
    "TEKSTIL": _EURLEX + "reg/2011/1007/oj",
    "ROHS": _EURLEX + "dir/2011/65/oj",
    "WEEE": _EURLEX + "dir/2012/19/oj",
    "LVD": _EURLEX + "dir/2014/35/oj",
    "ENERJI": _EURLEX + "reg/2017/1369/oj",
    "BATARYA": _EURLEX + "reg/2023/1542/oj",
    "CBAM": _EURLEX + "reg/2023/956/oj",
    "EUDR": _EURLEX + "reg/2023/1115/oj",
    "LASTIK": _EURLEX + "reg/2020/740/oj",
    "YAPI": _EURLEX + "reg/2024/3110/oj",
    "OYUNCAK": _EURLEX + "reg/2025/2509/oj",
    "CLP": _EURLEX + "reg/2008/1272/oj",
    "GUMRUK": _EURLEX + "reg/2013/952/oj",
}


# ---------------------------------------------------------------------------
# Belge durumu
# ---------------------------------------------------------------------------

BELGE_GECERLI = "Geçerli"
BELGE_60 = "60 gün içinde doluyor"
BELGE_30 = "30 gün içinde doluyor"
BELGE_DOLMUS = "Süresi dolmuş"
BELGE_TARIHSIZ = "Bitiş tarihi yok"


def belge_durumu(bitis: Optional[str], bugun: date) -> tuple[str, Optional[int]]:
    if not bitis:
        return BELGE_TARIHSIZ, None
    try:
        kalan = (date.fromisoformat(str(bitis)[:10]) - bugun).days
    except ValueError:
        return BELGE_TARIHSIZ, None
    if kalan < 0:
        return BELGE_DOLMUS, kalan
    if kalan <= 30:
        return BELGE_30, kalan
    if kalan <= 60:
        return BELGE_60, kalan
    return BELGE_GECERLI, kalan


# ---------------------------------------------------------------------------
# Bağlam
# ---------------------------------------------------------------------------

@dataclass
class Baglam:
    urun: dict
    sektor: Sektor
    tuketici: bool
    malzemeler: list[dict] = field(default_factory=list)
    asamalar: list[dict] = field(default_factory=list)
    belgeler: list[dict] = field(default_factory=list)   # her birinde 'durum', 'kalan' eklenmiş
    partiler: list[dict] = field(default_factory=list)
    gtin_tekrarlari: set = field(default_factory=set)
    bugun: date = field(default_factory=date.today)

    def d(self, alan):
        return self.urun.get(alan)

    def var(self, alan) -> bool:
        return not bos_mu(self.urun.get(alan))

    def kanit(self, *kodlar) -> bool:
        """Belirtilen türlerde süresi dolmamış ve reddedilmemiş bir belge var mı?"""
        return any(b["tur_kodu"] in kodlar and b["durum"] != BELGE_DOLMUS and b.get("dogrulama_durumu") != "Reddedildi"
                   for b in self.belgeler)

    def belge_turleri(self) -> set:
        return {b["tur_kodu"] for b in self.belgeler}


@dataclass
class Kural:
    kod: str
    ad: str
    sinif: str
    seviye: str
    agirlik: int
    dayanak: str
    kaynak: str
    kapsam: str
    uygulanir: Callable[[Baglam], bool]
    kontrol: Callable[[Baglam], tuple[bool, str]]
    recete: list[str]
    zorunlu_tarih: Optional[date] = None

    def etkin_sinif(self, bugun: date) -> str:
        if self.sinif == "Yasal" and self.zorunlu_tarih and bugun < self.zorunlu_tarih:
            return "Yaklaşan yükümlülük"
        return self.sinif


def _hep(_b):
    return True


def _sektor(*kodlar):
    return lambda b: b.sektor.kod in kodlar


# ---------------------------------------------------------------------------
# Kontroller
# ---------------------------------------------------------------------------

def _eksik(b: Baglam, alanlar: list[tuple[str, str]], basari: str) -> tuple[bool, str]:
    eksik = [ad for alan, ad in alanlar if not b.var(alan)]
    return (not eksik), (basari if not eksik else "Eksik: " + ", ".join(eksik))


def _bilesim(b: Baglam) -> tuple[list[tuple[str, float]], float]:
    liste = [(metin(m.get("malzeme")), sayi(m.get("oran")) or 0.0) for m in b.malzemeler if not bos_mu(m.get("malzeme"))]
    return liste, round(sum(o for _, o in liste), 2)


def k_gtin(b):
    return gtin_dogrula(b.d("gtin"))


def k_gtin_tekil(b):
    g = gtin_temizle(b.d("gtin"))
    if g and g in b.gtin_tekrarlari:
        return False, f"{g} numaralı GTIN başka ürünlerde de kullanılmış"
    return True, "GTIN bu ürüne özgü"


def k_gtip(b):
    return gtip_dogrula(b.d("gtip"))


def k_aktor(b):
    ok, detay = _eksik(b, [("tesis_id", "üretim tesisi")], "Üretim tesisi tanımlı")
    return ok, detay


def k_uretim_ulkesi(b):
    return _eksik(b, [("uretim_ulkesi", "üretim (menşe) ülkesi")], f"Üretim ülkesi: {metin(b.d('uretim_ulkesi'))}")


def k_hammadde(b):
    if b.var("hammadde_mensei"):
        return True, f"Hammadde menşei: {metin(b.d('hammadde_mensei'))}"
    if b.malzemeler and all(not bos_mu(m.get("mense")) for m in b.malzemeler):
        return True, "Malzeme satırlarında menşe bilgisi tam"
    return False, "Hammadde menşei girilmemiş (ürün kartında veya malzeme satırlarında)"


def k_malzeme(b):
    liste, toplam = _bilesim(b)
    if not liste:
        return False, "Malzeme bileşimi girilmemiş"
    if abs(toplam - 100) > 1:
        return False, f"Malzeme oranları toplamı %{toplam:g}; %100 olmalı"
    return True, "Bileşim: " + ", ".join(f"{a} %{o:g}" for a, o in liste)


def k_svhc(b):
    beyan = tr_norm(b.d("svhc_beyani"))
    if beyan in ("", "bilinmiyor", "belirsiz", "none"):
        return False, "SVHC (yüksek önem arz eden madde) beyanı yok veya 'Bilinmiyor'"
    if beyan in ("var", "evet"):
        if not b.var("svhc_maddeler"):
            return False, "SVHC 'Var' denmiş ama madde adı / CAS no girilmemiş"
        return True, f"SVHC: Var — {metin(b.d('svhc_maddeler'))}"
    if beyan in ("yok", "hayir"):
        return True, "SVHC: Yok (%0,1 eşiği altında)"
    return False, f"SVHC beyanı anlaşılamadı: '{metin(b.d('svhc_beyani'))}'"


def k_svhc_kanit(b):
    if b.kanit("REACH", "REACH_TEST", "TEST", "OEKOTEX", "ROHS"):
        return True, "Kimyasal beyanı destekleyen belge mevcut"
    return False, "SVHC/REACH beyanını destekleyen tedarikçi beyanı veya test raporu yok"


def k_belge_suresi(b):
    dolmus = [x for x in b.belgeler if x["durum"] == BELGE_DOLMUS]
    if dolmus:
        return False, "Süresi dolmuş: " + ", ".join(f"{BELGE[x['tur_kodu']].ad if x['tur_kodu'] in BELGE else x['tur_kodu']} ({x.get('bitis')})" for x in dolmus)
    return True, "Süresi dolmuş belge yok"


def k_belge_yaklasan(b):
    yakin = [x for x in b.belgeler if x["durum"] in (BELGE_30, BELGE_60)]
    if yakin:
        return False, "Yenileme zamanı yaklaşan: " + ", ".join(f"{BELGE.get(x['tur_kodu'], BELGE['DIGER']).ad} ({x['kalan']} gün)" for x in yakin)
    return True, "60 gün içinde süresi dolacak belge yok"


def k_belge_sinif(b):
    if not b.belgeler:
        return True, "—"
    turler = b.belge_turleri()
    yonetim = turler & YONETIM_SISTEMI_KODLARI
    urune_ozgu = turler - YONETIM_SISTEMI_KODLARI - {"DIGER"}
    if yonetim and not urune_ozgu:
        return False, (", ".join(BELGE[k].ad for k in sorted(yonetim))
                       + " kuruluş düzeyinde yönetim sistemi belgesidir; ürün uygunluğunu tek başına kanıtlamaz")
    return True, "Ürüne özgü belge mevcut"


_IDDIALAR = {
    "organik": ("organik", ("GOTS", "OCS")), "organic": ("organik", ("GOTS", "OCS")),
    "geri donusturulmus": ("geri dönüştürülmüş", ("GRS", "RCS", "EPD")), "recycled": ("geri dönüştürülmüş", ("GRS", "RCS", "EPD")),
    "surdurulebilir": ("sürdürülebilir", None), "cevre dostu": ("çevre dostu", None), "eko ": ("eko", None),
    "dogal": ("doğal", None), "karbon notr": ("karbon nötr", None), "iklim dostu": ("iklim dostu", None),
    "yesil": ("yeşil", None),
}
_GENEL_KANIT = ("ECOLABEL", "EPD", "KARBON", "GOTS", "GRS", "OCS", "RCS", "FSC", "PEFC")


def k_iddia(b):
    m = " " + tr_norm(" ".join([metin(b.d("cevresel_iddia")), metin(b.d("ad"))])) + " "
    eksik = []
    for anahtar, (etiket, gereken) in _IDDIALAR.items():
        if anahtar in m:
            if gereken is None:
                if not b.kanit(*_GENEL_KANIT):
                    eksik.append(f"'{etiket}' (genel iddia; tanınmış etiket veya doğrulanmış veri gerekir)")
            elif not b.kanit(*gereken):
                eksik.append(f"'{etiket}' ({' / '.join(gereken)} gerekir)")
    eksik = list(dict.fromkeys(eksik))
    if eksik:
        return False, "Kanıtsız çevre iddiası: " + "; ".join(eksik)
    return True, "Çevre iddiası yok veya belgeyle destekleniyor"


def k_geri_donusum(b):
    oran = sayi(b.d("geri_donusturulmus_yuzde"))
    if not oran:
        return True, "Geri dönüştürülmüş içerik beyanı yok"
    if b.kanit("GRS", "RCS", "EPD", "TEST"):
        return True, f"%{oran:g} geri dönüştürülmüş içerik belgeyle destekleniyor"
    return False, f"%{oran:g} geri dönüştürülmüş içerik beyan edilmiş ancak destekleyici belge yok"


def k_bakim(b):
    return _eksik(b, [("bakim_onarim", "bakım/onarım bilgisi"), ("omur_sonu", "ömür sonu talimatı")],
                  "Kullanım ve ömür sonu bilgileri tam")


def k_karbon(b):
    if not b.var("karbon_kg"):
        return False, "Karbon ayak izi verisi yok"
    if not b.var("karbon_yontemi"):
        return False, "Karbon ayak izi girilmiş, hesaplama yöntemi belirtilmemiş"
    return True, f"{metin(b.d('karbon_kg'))} kg CO2e ({metin(b.d('karbon_yontemi'))})"


def k_gpsr(b):
    if b.var("ab_sorumlu_operator"):
        return True, f"AB sorumlu operatör: {metin(b.d('ab_sorumlu_operator'))}"
    return False, "AB'de yerleşik sorumlu ekonomik operatör bilgisi yok"


def k_tedarik(b):
    ulkeli = [a for a in b.asamalar if not bos_mu(a.get("ulke"))]
    if len(ulkeli) < 2:
        return False, f"{len(ulkeli)} aşama ülke bilgisiyle kayıtlı; en az 2 aşama (hammadde → nihai üretim) önerilir"
    return True, f"{len(ulkeli)} aşama kayıtlı"


def k_parti(b):
    if b.partiler:
        return True, f"{len(b.partiler)} parti kayıtlı"
    return False, "Parti / lot kaydı yok"


def k_dogrulama(b):
    ilgili = [x for x in b.belgeler if x["tur_kodu"] not in YONETIM_SISTEMI_KODLARI]
    if not ilgili:
        return True, "—"
    dogrulanan = [x for x in ilgili if x.get("dogrulama_durumu") == "Doğrulandı"]
    if len(dogrulanan) == len(ilgili):
        return True, f"{len(ilgili)} belgenin tamamı bağımsız doğrulamadan geçti"
    return False, f"{len(ilgili)} belgeden {len(dogrulanan)} tanesi doğrulandı"


def k_lif(b):
    liste, toplam = _bilesim(b)
    if not liste:
        return False, "Lif bileşimi girilmemiş; tekstil etiketinde lif adı ve yüzdesi zorunludur"
    if abs(toplam - 100) > 1:
        return False, f"Lif oranları toplamı %{toplam:g}; %100 olmalı"
    return True, "Lif bileşimi: " + ", ".join(f"{a} %{o:g}" for a, o in liste)


def k_tekstil_kimyasal(b):
    if b.kanit("OEKOTEX", "REACH_TEST", "TEST", "ZDHC", "BLUESIGN"):
        return True, "Kimyasal uygunluk kanıtı mevcut"
    return False, "REACH Ek XVII kısıtlamaları için test raporu veya tanınmış etiket yok"


def _belge_kontrol(*kodlar, ad: str):
    def f(b):
        if b.kanit(*kodlar):
            return True, f"{ad} mevcut"
        return False, f"{ad} yok veya süresi dolmuş / reddedilmiş"
    return f


def k_eprel(b):
    if b.var("eprel_no") or b.kanit("EPREL"):
        return True, f"EPREL: {metin(b.d('eprel_no')) or 'belgede'}"
    return False, "EPREL kayıt numarası yok"


def _batarya_pasaportlu(b):
    if b.sektor.kod != "batarya":
        return False
    kat = tr_norm(b.d("batarya_kategori"))
    kap = sayi(b.d("batarya_kwh")) or 0
    return (kat in ("ev", "lmt") or "elektrikli arac" in kat or "hafif" in kat
            or (("endustriyel" in kat or "industrial" in kat) and kap > 2))


def k_batarya(b):
    return _eksik(b, [("batarya_kimya", "batarya kimyası"), ("batarya_kwh", "kapasite"),
                      ("karbon_kg", "karbon ayak izi"), ("gtin", "benzersiz tanımlayıcı")],
                  "Temel batarya pasaportu verileri mevcut")


def k_batarya_kategori(b):
    if b.var("batarya_kategori"):
        return True, f"Kategori: {metin(b.d('batarya_kategori'))}"
    return False, "Batarya kategorisi (EV / LMT / Endüstriyel / Taşınabilir) girilmemiş"


def k_cbam(b):
    eksik = []
    if not b.var("gomulu_emisyon"):
        eksik.append("gömülü emisyon (tCO2e/t)")
    if not b.var("tesis_id"):
        eksik.append("üretim tesisi")
    if eksik:
        return False, "CBAM verisi eksik: " + ", ".join(eksik)
    return True, f"Gömülü emisyon: {metin(b.d('gomulu_emisyon'))} tCO2e/t"


_AHSAP = ("ahsap", "mdf", "suntalam", "kontrplak", "kereste", "wood", "mese", "ceviz", "kayin", "cam agaci", "kagit", "karton")


def _ahsapli(b):
    m = " ".join(tr_norm(x.get("malzeme")) for x in b.malzemeler) + " " + tr_norm(b.d("ad"))
    return any(k in m for k in _AHSAP)


def k_eudr(b):
    if b.kanit("EUDR"):
        return True, "EUDR durum tespit beyanı / hasat yeri verisi mevcut"
    if b.kanit("FSC", "PEFC"):
        return False, "FSC/PEFC var ancak EUDR durum tespitinin yerine geçmez; hasat yeri koordinatları gerekir"
    return False, "Ahşap içeren ürün için EUDR durum tespiti / hasat yeri bilgisi yok"


def k_imds(b):
    if b.var("imds_id") or b.kanit("IMDS"):
        return True, "IMDS kaydı mevcut"
    return False, "IMDS kayıt numarası yok"


def k_oyuncak(b):
    eksik = [ad for kodlar, ad in ((("CE_DOC",), "AB Uygunluk Beyanı"), (("EN71", "TEST"), "EN 71 test raporu")) if not b.kanit(*kodlar)]
    return (not eksik), ("CE ve test raporu mevcut" if not eksik else "Eksik: " + ", ".join(eksik))


def k_dop(b):
    eksik = [ad for kodlar, ad in ((("DOP",), "Performans Beyanı (DoP)"), (("CE_DOC",), "CE dayanağı")) if not b.kanit(*kodlar)]
    return (not eksik), ("DoP ve CE mevcut" if not eksik else "Eksik: " + ", ".join(eksik))


def k_metal_geri(b):
    return (b.var("geri_donusturulmus_yuzde"),
            "Geri dönüştürülmüş içerik oranı " + ("girilmiş" if b.var("geri_donusturulmus_yuzde") else "girilmemiş"))


# ---------------------------------------------------------------------------
# Kural listesi
# ---------------------------------------------------------------------------

KURALLAR: list[Kural] = [
    # --- Genel ---
    Kural("G01", "Benzersiz ürün tanımlayıcısı (GTIN)", "DPP", "Yüksek", 10,
          "ESPR md. 9–12 ve Ek III; EN 18219:2026", KAYNAK["ESPR"], "Tüm sektörler", _hep, k_gtin,
          ["GS1 Türkiye'den firmanıza ait barkod numara bloğu alın.",
           "Her model ve varyant (renk, beden) için ayrı GTIN tanımlayın; örnek numara kullanmayın.",
           "GTIN'i Excel'de METİN olarak girin; baştaki sıfırlar kaybolmasın."]),
    Kural("G02", "GTIN tekilliği", "İyi uygulama", "Orta", 4,
          "GS1 Genel Spesifikasyonları", "https://www.gs1.org/standards/barcodes-epcrfid-id-keys/gs1-general-specifications",
          "Tüm sektörler", lambda b: bool(gtin_temizle(b.d("gtin"))), k_gtin_tekil,
          ["Aynı GTIN'in farklı ürün kodlarında kullanıldığı kayıtları düzeltin."]),
    Kural("G03", "Gümrük tarife (GTİP) kodu", "DPP", "Orta", 5,
          "Uygulama Tüzüğü (AB) 2026/1778 — DPP Registry emtia kodu", _EURLEX + "reg_impl/2026/1778/oj",
          "Tüm sektörler", _hep, k_gtip,
          ["Gümrük beyannamesindeki GTİP kodunu (en az 6 hane) ürün kartına girin.",
           "Emin değilseniz gümrük müşavirinizden bağlayıcı tarife bilgisi alın."]),
    Kural("G04", "Üretim tesisi", "DPP", "Yüksek", 8,
          "ESPR Ek III — iktisadi işletmeci ve tesis tanımlayıcıları", KAYNAK["ESPR"], "Tüm sektörler", _hep, k_aktor,
          ["Tesisler ekranında üretim tesisini (adres, ülke, varsa GLN) tanımlayın ve ürüne bağlayın."]),
    Kural("G05", "Üretim (menşe) ülkesi", "Yasal", "Kritik", 10,
          "Birlik Gümrük Kodu (AB) 952/2013 md. 59–61 menşe kuralları", KAYNAK["GUMRUK"], "Tüm sektörler", _hep, k_uretim_ulkesi,
          ["Nihai üretimin (son esaslı işçiliğin) yapıldığı ülkeyi girin.",
           "Menşe ispatı için A.TR / EUR.1 / menşe şahadetnamesini belge kasasına ekleyin."]),
    Kural("G06", "Hammadde menşei", "DPP", "Orta", 5,
          "ESPR Ek III — tedarik zinciri bilgisi", KAYNAK["ESPR"], "Tüm sektörler", _hep, k_hammadde,
          ["Ana hammaddenin menşeini ürün kartına veya her malzeme satırına girin.",
           "İthal hammaddede tedarikçinin menşe belgesini isteyin."]),
    Kural("G07", "Malzeme bileşimi", "DPP", "Yüksek", 8,
          "ESPR md. 7 ve Ek I — malzeme bilgisi", KAYNAK["ESPR"], "Tekstil dışındaki sektörler",
          lambda b: b.sektor.kod != "tekstil", k_malzeme,
          ["Ürünü oluşturan malzemeleri ağırlıkça yüzdeleriyle girin; toplam %100 olmalı."]),
    Kural("G08", "Endişe verici madde (SVHC) beyanı", "Yasal", "Kritik", 10,
          "REACH (AT) 1907/2006 md. 33 — %0,1 üzeri SVHC bilgi verme yükümlülüğü", KAYNAK["REACH"], "Tüm sektörler", _hep, k_svhc,
          ["Tedarikçilerden güncel ECHA aday listesine göre SVHC beyanı isteyin (Tedarikçi Talepleri ekranı).",
           "%0,1 üzeri SVHC varsa madde adını ve CAS numarasını girin.",
           "Bilgi yoksa akredite laboratuvarda tarama testi yaptırın."]),
    Kural("G09", "SVHC beyanının belgeyle desteklenmesi", "İyi uygulama", "Orta", 4,
          "REACH md. 33; durum tespiti iyi uygulaması", KAYNAK["REACH"], "Tüm sektörler", _hep, k_svhc_kanit,
          ["Tedarikçi REACH/SVHC beyanını veya test raporunu belge kasasına ekleyin."]),
    Kural("G10", "Süresi dolmuş belge", "İyi uygulama", "Yüksek", 6,
          "İlgili sertifika ve beyan şartları", "", "Tüm sektörler", _hep, k_belge_suresi,
          ["Süresi dolan belgeyi yenileyin ve yeni bitiş tarihini girin.",
           "Yenilenene kadar bu belgeye dayanan iddiaları kullanmayın."]),
    Kural("G11", "Yenileme zamanı yaklaşan belge", "İyi uygulama", "Bilgi", 2,
          "İç kontrol", "", "Tüm sektörler", _hep, k_belge_yaklasan,
          ["60 gün içinde süresi dolacak belgeler için yenileme denetimini planlayın."]),
    Kural("G12", "Belge türlerinin doğru kullanımı", "İyi uygulama", "Orta", 3,
          "ESPR — doğrulanabilir bilgi ilkesi", KAYNAK["ESPR"], "Tüm sektörler", lambda b: bool(b.belgeler), k_belge_sinif,
          ["ISO 9001 / ISO 14001 / IATF gibi kuruluş belgelerini ürün sertifikası olarak sunmayın.",
           "Ürüne özgü sertifika, uygunluk beyanı veya test raporu ekleyin."]),
    Kural("G13", "Çevre iddialarının kanıtı", "Yasal", "Yüksek", 8,
          "Direktif (AB) 2024/825 — kanıtsız genel çevre iddiası yasağı (27.09.2026'dan itibaren)", KAYNAK["YESIL"],
          "Tüm sektörler", _hep, k_iddia,
          ["'Organik', 'geri dönüştürülmüş', 'çevre dostu' gibi ifadeleri yalnızca belgeyle destekleyebiliyorsanız kullanın.",
           "Organik için GOTS/OCS, geri dönüştürülmüş için GRS/RCS gibi tanınmış sertifika ekleyin.",
           "Genel ifadeler yerine ölçülebilir ve doğrulanmış bilgi verin."],
          zorunlu_tarih=date(2026, 9, 27)),
    Kural("G14", "Geri dönüştürülmüş içerik kanıtı", "DPP", "Yüksek", 6,
          "ESPR Ek I — geri dönüştürülmüş içerik", KAYNAK["ESPR"], "Tüm sektörler", _hep, k_geri_donusum,
          ["Geri dönüştürülmüş içerik oranını destekleyen GRS/RCS, EPD veya üretici beyanı ekleyin."]),
    Kural("G15", "Bakım, onarım ve ömür sonu bilgisi", "DPP", "Orta", 5,
          "ESPR md. 5 ve Ek I — dayanıklılık, onarılabilirlik, geri dönüşüm", KAYNAK["ESPR"], "Tüm sektörler", _hep, k_bakim,
          ["Kullanıcıya yönelik bakım/onarım bilgisini ve ömür sonu bertaraf talimatını yazın."]),
    Kural("G16", "Karbon / çevresel ayak izi", "DPP", "Bilgi", 3,
          "ESPR Ek I (yetki tüzükleriyle zorunlu hale gelebilir); alıcı talepleri", KAYNAK["ESPR"], "Tüm sektörler",
          lambda b: b.sektor.kod not in ("demir_celik", "aluminyum"), k_karbon,
          ["Hesaplamayı ISO 14067 veya PEF yöntemiyle yaptırın ve yöntemi belirtin."]),
    Kural("G17", "AB'de sorumlu ekonomik operatör", "Yasal", "Kritik", 10,
          "Genel Ürün Güvenliği Tüzüğü (AB) 2023/988 md. 16", KAYNAK["GPSR"], "Tüketici ürünleri",
          lambda b: b.tuketici, k_gpsr,
          ["AB'de yerleşik bir sorumlu kişi (ithalatçı, yetkili temsilci veya hizmet sağlayıcı) belirleyin.",
           "Unvan, posta adresi ve e-posta ürün, ambalaj veya beraberindeki belgede yer almalı."]),
    Kural("G18", "Tedarik zinciri aşamaları", "DPP", "Orta", 5,
          "ESPR Ek III — izlenebilirlik", KAYNAK["ESPR"], "Tüm sektörler", _hep, k_tedarik,
          ["Ürünün en az hammadde ve nihai üretim aşamalarını tedarikçi ve ülke bilgisiyle girin."]),
    Kural("G19", "Parti / lot izlenebilirliği", "DPP", "Orta", 4,
          "ESPR md. 10 — model, parti veya ürün düzeyinde pasaport", KAYNAK["ESPR"], "Tüm sektörler", _hep, k_parti,
          ["Üretim partilerini (lot no, üretim tarihi, tesis) ürün kartında tanımlayın."]),
    Kural("G20", "Belgelerin bağımsız doğrulaması", "İyi uygulama", "Bilgi", 3,
          "Güvence iyi uygulaması (ISAE 3000 yaklaşımı)", "", "Tüm sektörler",
          lambda b: any(x["tur_kodu"] not in YONETIM_SISTEMI_KODLARI for x in b.belgeler), k_dogrulama,
          ["Belgeleri bağımsız doğrulayıcının incelemesine gönderin (Doğrulama ekranı)."]),

    # --- Tekstil ve deri ---
    Kural("T01", "Tekstil lif bileşimi", "Yasal", "Kritik", 10,
          "Tekstil Etiketleme Tüzüğü (AB) 1007/2011", KAYNAK["TEKSTIL"], "Tekstil", _sektor("tekstil"), k_lif,
          ["Lif adlarını Tüzük Ek I'deki adlarla ve ağırlıkça yüzdeleriyle girin.",
           "Etiketteki bileşimle sistemdeki bileşimin aynı olduğunu kontrol edin."]),
    Kural("T02", "Kimyasal kısıtlamalara uyum kanıtı", "Yasal", "Yüksek", 8,
          "REACH Ek XVII (azo boyar maddeler, krom VI, ağır metaller, PFAS vb.)", KAYNAK["REACH"], "Tekstil, deri ve ayakkabı",
          _sektor("tekstil", "deri_ayakkabi"), k_tekstil_kimyasal,
          ["Akredite laboratuvardan REACH Ek XVII test raporu alın veya OEKO-TEX gibi tanınmış etiket kullanın.",
           "Boyahane ve kimyasal tedarikçilerinden ZDHC uyum beyanı isteyin."]),

    # --- Elektrik-elektronik ---
    Kural("E01", "AB Uygunluk Beyanı (CE)", "Yasal", "Kritik", 10,
          "Alçak Gerilim 2014/35/AB, EMC 2014/30/AB, Telsiz 2014/53/AB direktifleri", KAYNAK["LVD"], "Elektronik, beyaz eşya",
          _sektor("elektronik", "beyaz_esya"), _belge_kontrol("CE_DOC", ad="AB Uygunluk Beyanı"),
          ["Uygulanan direktifleri belirleyin, teknik dosyayı hazırlayın, testleri yaptırıp AB Uygunluk Beyanını düzenleyin."]),
    Kural("E02", "RoHS uygunluğu", "Yasal", "Kritik", 8,
          "RoHS Direktifi 2011/65/AB", KAYNAK["ROHS"], "Elektronik, beyaz eşya",
          _sektor("elektronik", "beyaz_esya"), _belge_kontrol("ROHS", ad="RoHS beyanı / testi"),
          ["Komponent tedarikçilerinden RoHS beyanı toplayın; riskli parçalar için XRF / laboratuvar testi yaptırın."]),
    Kural("E03", "WEEE üretici kaydı", "Yasal", "Yüksek", 5,
          "AEEE (WEEE) Direktifi 2012/19/AB", KAYNAK["WEEE"], "Elektronik, beyaz eşya",
          _sektor("elektronik", "beyaz_esya"), _belge_kontrol("WEEE", ad="WEEE kaydı"),
          ["Satış yapılan her AB ülkesinde WEEE kaydını kimin yaptığını (ithalatçı / yetkili temsilci) netleştirin ve kayıt numarasını ekleyin."]),
    Kural("E04", "Enerji etiketi (EPREL)", "Yasal", "Yüksek", 5,
          "Enerji Etiketleme Tüzüğü (AB) 2017/1369", KAYNAK["ENERJI"], "Beyaz eşya", _sektor("beyaz_esya"), k_eprel,
          ["Enerji etiketi gerektiren ürünü EPREL'e kaydedin ve kayıt numarasını girin."]),

    # --- Batarya ---
    Kural("B01", "Batarya kategorisi", "Yasal", "Yüksek", 5,
          "Batarya Tüzüğü (AB) 2023/1542 md. 3", KAYNAK["BATARYA"], "Batarya", _sektor("batarya"), k_batarya_kategori,
          ["Bataryanın EV, LMT, endüstriyel veya taşınabilir olduğunu belirtin."]),
    Kural("B02", "Batarya pasaportu verileri", "Yasal", "Kritik", 10,
          "Batarya Tüzüğü (AB) 2023/1542 md. 77", KAYNAK["BATARYA"], "EV, LMT ve 2 kWh üzeri endüstriyel bataryalar",
          _batarya_pasaportlu, k_batarya,
          ["Batarya kimyası, kapasite, karbon ayak izi ve benzersiz tanımlayıcıyı tamamlayın.",
           "Pasaportu ve QR kod yerleşimini 18.02.2027 öncesinde hazır edin."],
          zorunlu_tarih=date(2027, 2, 18)),
    Kural("B03", "Bataryada AB Uygunluk Beyanı", "Yasal", "Kritik", 8,
          "Batarya Tüzüğü (AB) 2023/1542 md. 18 ve 20", KAYNAK["BATARYA"], "Batarya", _sektor("batarya"),
          _belge_kontrol("CE_DOC", ad="AB Uygunluk Beyanı"),
          ["Batarya için AB Uygunluk Beyanı düzenleyin ve belge kasasına ekleyin."]),

    # --- Metaller ---
    Kural("M01", "CBAM gömülü emisyon verisi", "Yasal", "Kritik", 10,
          "SKDM (CBAM) Tüzüğü (AB) 2023/956 — beyan AB'li ithalatçıda, veri ihracatçıdan", KAYNAK["CBAM"], "Demir-çelik, alüminyum",
          _sektor("demir_celik", "aluminyum"), k_cbam,
          ["Tesis bazında doğrudan ve dolaylı emisyonları AB yöntemine göre hesaplayın.",
           "Ton ürün başına gömülü emisyonu AB'li ithalatçınızla paylaşın; mümkünse akredite doğrulayıcıya doğrulatın."]),
    Kural("M02", "Metalde geri dönüştürülmüş içerik", "DPP", "Orta", 4,
          "ESPR demir-çelik / alüminyum yetki tüzükleri (hazırlık aşamasında)", KAYNAK["ESPR"], "Demir-çelik, alüminyum",
          _sektor("demir_celik", "aluminyum"), k_metal_geri,
          ["Hurda girdi oranından geri dönüştürülmüş içerik yüzdesini hesaplayıp girin."]),

    # --- Ahşap ---
    Kural("W01", "Ahşap için EUDR durum tespiti", "Yasal", "Kritik", 10,
          "Ormansızlaşma Tüzüğü (AB) 2023/1115 — büyük işletmeler için 30.12.2026 (takvimi teyit edin)", KAYNAK["EUDR"],
          "Ahşap / kâğıt içeren ürünler", _ahsapli, k_eudr,
          ["Ahşabın hasat edildiği arazinin coğrafi konumunu tedarikçiden alın.",
           "AB'li ithalatçınızın durum tespit beyanı için ihtiyaç duyduğu verileri hazırlayın."],
          zorunlu_tarih=date(2026, 12, 30)),

    # --- Diğer sektörler ---
    Kural("A01", "IMDS malzeme kaydı", "İyi uygulama", "Yüksek", 6,
          "OEM tedarikçi şartnameleri; ELV ve REACH uyumunun dayanağı", "https://www.mdsystem.com", "Otomotiv yan sanayi",
          _sektor("otomotiv"), k_imds,
          ["Parçanın malzeme verisini IMDS'ye girip OEM müşterinize gönderin ve kayıt numarasını ekleyin."]),
    Kural("L01", "Lastik etiketi (EPREL)", "Yasal", "Yüksek", 6,
          "Lastik Etiketleme Tüzüğü (AB) 2020/740", KAYNAK["LASTIK"], "Lastik", _sektor("lastik"), k_eprel,
          ["Lastiği EPREL'e kaydedip kayıt numarasını girin."]),
    Kural("O01", "Oyuncak güvenliği", "Yasal", "Kritik", 10,
          "Oyuncak Güvenliği Tüzüğü (AB) 2025/2509; EN 71", KAYNAK["OYUNCAK"], "Oyuncak", _sektor("oyuncak"), k_oyuncak,
          ["EN 71 testlerini yaptırın, AB Uygunluk Beyanını düzenleyin ve belge kasasına ekleyin."]),
    Kural("K01", "Güvenlik Bilgi Formu", "Yasal", "Kritik", 8,
          "REACH md. 31; CLP Tüzüğü (AT) 1272/2008", KAYNAK["CLP"], "Deterjan ve kimyasal", _sektor("deterjan"),
          _belge_kontrol("SDS", ad="Güvenlik Bilgi Formu"),
          ["Ürün için hedef ülke dilinde güncel Güvenlik Bilgi Formu hazırlayın."]),
    Kural("Y01", "Performans beyanı ve CE", "Yasal", "Kritik", 10,
          "Yapı Malzemeleri Tüzüğü (AB) 2024/3110", KAYNAK["YAPI"], "Yapı malzemeleri", _sektor("insaat"), k_dop,
          ["Uyumlaştırılmış standarda göre performans beyanı (DoP) düzenleyin, CE dayanağını belge kasasına ekleyin."]),
]
KURAL = {k.kod: k for k in KURALLAR}


# ---------------------------------------------------------------------------
# Kural ayarları ve sürüm
# ---------------------------------------------------------------------------

def kural_seti_surumu(ayarlar: dict[str, dict]) -> str:
    """Kural seti temel sürümü + (varsa) yönetici ayarlarının kısa özeti."""
    if not ayarlar:
        return KURAL_SETI_TEMEL
    govde = json.dumps({k: {"aktif": v.get("aktif"), "agirlik": v.get("agirlik")} for k, v in sorted(ayarlar.items())},
                       sort_keys=True)
    return f"{KURAL_SETI_TEMEL}+{hashlib.sha256(govde.encode()).hexdigest()[:8]}"


def etkin_kural(kural: Kural, ayarlar: dict[str, dict]) -> tuple[bool, int]:
    a = ayarlar.get(kural.kod) or {}
    aktif = a.get("aktif", 1)
    agirlik = a.get("agirlik") or kural.agirlik
    return bool(aktif), int(agirlik)


# ---------------------------------------------------------------------------
# Değerlendirme
# ---------------------------------------------------------------------------

@dataclass
class Sonuc:
    yasal_durum: str
    yasal_eksik: int
    kritik_eksik: int
    hazirlik_skoru: float
    genel_durum: str
    uygulanan: int
    bulgular: list[dict]


def degerlendir(b: Baglam, ayarlar: Optional[dict] = None) -> Sonuc:
    ayarlar = ayarlar or {}
    bulgular: list[dict] = []
    hz_toplam = hz_kazanilan = 0
    yasal_eksik = kritik_eksik = 0
    for k in KURALLAR:
        aktif, agirlik = etkin_kural(k, ayarlar)
        if not aktif:
            continue
        try:
            if not k.uygulanir(b):
                continue
            gecti, detay = k.kontrol(b)
        except Exception as hata:
            gecti, detay = False, f"Kural çalıştırılamadı: {hata}"
        sinif = k.etkin_sinif(b.bugun)
        if sinif == "Yasal":
            if not gecti:
                yasal_eksik += 1
                if k.seviye == "Kritik":
                    kritik_eksik += 1
        else:
            hz_toplam += agirlik
            hz_kazanilan += agirlik if gecti else 0
        bulgular.append({"kural_kodu": k.kod, "sinif": sinif, "seviye": k.seviye, "agirlik": agirlik,
                         "sonuc": "Uygun" if gecti else "Eksik", "detay": detay})
    skor = round(100 * hz_kazanilan / hz_toplam, 1) if hz_toplam else 100.0
    if kritik_eksik:
        genel = DURUM_KRITIK
    elif yasal_eksik:
        genel = DURUM_YASAL
    elif skor < HAZIR_ESIGI:
        genel = DURUM_SURUYOR
    else:
        genel = DURUM_HAZIR
    bulgular.sort(key=lambda r: (r["sonuc"] != "Eksik", r["sinif"] != "Yasal", SEVIYE_SIRA[r["seviye"]], r["kural_kodu"]))
    return Sonuc("Uygun" if yasal_eksik == 0 else "Eksik", yasal_eksik, kritik_eksik, skor, genel, len(bulgular), bulgular)


def yaklasan_yukumlulukler(bugun: Optional[date] = None, gun: int = 365) -> list[Kural]:
    bugun = bugun or date.today()
    return sorted([k for k in KURALLAR if k.zorunlu_tarih and bugun <= k.zorunlu_tarih <= bugun + timedelta(days=gun)],
                  key=lambda k: k.zorunlu_tarih)
