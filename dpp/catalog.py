"""Sektör ve belge türü katalogları."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .util import gtip_temizle, metin, tr_norm


@dataclass(frozen=True)
class Sektor:
    kod: str
    ad: str
    gtip_onekleri: tuple[str, ...]
    anahtarlar: tuple[str, ...]
    tuketici_varsayilan: bool


# GTİP önekleri sektör ÖNERİSİ içindir; kesin sınıflandırma kullanıcı tarafından seçilir.
SEKTORLER: list[Sektor] = [
    Sektor("batarya", "Batarya ve akü", ("8506", "8507"), ("batarya", "aku", "pil", "battery"), False),
    Sektor("lastik", "Lastik", ("4011", "4012", "4013"), ("lastik", "tyre", "tire"), True),
    Sektor("otomotiv", "Otomotiv yan sanayi", ("8708", "8409", "8511", "8512", "6813"), ("otomotiv", "yan sanayi", "arac parca", "balata"), False),
    Sektor("beyaz_esya", "Beyaz eşya ve ev aletleri", ("8418", "8422", "8450", "8451", "8508", "8509", "8516", "8415"),
           ("beyaz esya", "ev aleti", "klima", "buzdolabi", "camasir", "bulasik"), True),
    Sektor("elektronik", "Elektrik ve elektronik", ("84", "85", "9405"), ("elektronik", "elektrik", "aydinlatma", "kablo", "led"), True),
    Sektor("tekstil", "Tekstil ve hazır giyim", tuple(str(i) for i in range(50, 64)),
           ("tekstil", "giyim", "konfeksiyon", "kumas", "iplik", "ev tekstili", "hali", "tisort", "pantolon"), True),
    Sektor("deri_ayakkabi", "Deri ve ayakkabı", ("41", "42", "43", "64"), ("ayakkabi", "deri", "canta"), True),
    Sektor("demir_celik", "Demir-çelik", ("72", "73"), ("demir", "celik", "steel", "profil", "boru"), False),
    Sektor("aluminyum", "Alüminyum", ("76",), ("aluminyum", "aluminium", "aluminum"), False),
    Sektor("mobilya", "Mobilya ve şilte", ("9401", "9403", "9404"), ("mobilya", "silte", "yatak", "kanepe", "masa", "sandalye"), True),
    Sektor("oyuncak", "Oyuncak", ("9503", "9504"), ("oyuncak", "toy"), True),
    Sektor("deterjan", "Deterjan ve kimyasal ürünler", ("3401", "3402", "3405", "38"), ("deterjan", "temizlik", "kimyasal"), True),
    Sektor("insaat", "Yapı malzemeleri", ("25", "68", "69", "7010", "3925"), ("insaat", "yapi malzeme", "cimento", "seramik", "yalitim"), False),
    Sektor("diger", "Diğer", (), (), True),
]
SEKTOR = {s.kod: s for s in SEKTORLER}
SEKTOR_ADLARI = {s.kod: s.ad for s in SEKTORLER}


def sektor_oner(gtip=None, metin_ipucu=None) -> str:
    """GTİP koduna (en uzun önek eşleşmesi), yoksa metne göre sektör önerir."""
    g = gtip_temizle(gtip)
    if g:
        en_iyi, uzunluk = None, 0
        for s in SEKTORLER:
            for onek in s.gtip_onekleri:
                if g.startswith(onek) and len(onek) > uzunluk:
                    en_iyi, uzunluk = s.kod, len(onek)
        if en_iyi:
            return en_iyi
    n = tr_norm(metin_ipucu)
    if n:
        for s in SEKTORLER:
            if s.kod == tr_norm(n).replace(" ", "_") or tr_norm(s.ad) == n:
                return s.kod
        for s in SEKTORLER:
            if any(a in n for a in s.anahtarlar):
                return s.kod
    return "diger"


# ---------------------------------------------------------------------------
# Belge türleri
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BelgeTuru:
    kod: str
    ad: str
    kategori: str
    aciklama: str
    anahtarlar: tuple[str, ...]


KATEGORI_URUN_SERTIFIKA = "Ürün sertifikası / etiketi"
KATEGORI_MEVZUAT = "Mevzuat uygunluk belgesi"
KATEGORI_TEST = "Test / analiz raporu"
KATEGORI_YONETIM = "Yönetim sistemi belgesi"
KATEGORI_CEVRE = "Çevresel performans"
KATEGORI_GUMRUK = "Gümrük / menşe"
KATEGORI_KAYIT = "Mevzuat kaydı"
KATEGORI_DIGER = "Diğer"

BELGE_TURLERI: list[BelgeTuru] = [
    BelgeTuru("CE_DOC", "AB Uygunluk Beyanı (CE)", KATEGORI_MEVZUAT, "CE işaretinin dayanağı olan beyan", ("CE", "DOC", "UYGUNLUKBEYANI", "DECLARATIONOFCONFORMITY")),
    BelgeTuru("DOP", "Performans Beyanı (DoP)", KATEGORI_MEVZUAT, "Yapı Malzemeleri Tüzüğü", ("DOP", "PERFORMANSBEYANI")),
    BelgeTuru("ROHS", "RoHS beyanı / test raporu", KATEGORI_MEVZUAT, "2011/65/AB tehlikeli madde sınırlaması", ("ROHS",)),
    BelgeTuru("REACH", "REACH / SVHC beyanı", KATEGORI_MEVZUAT, "1907/2006 REACH md. 33 bilgi beyanı", ("REACH", "SVHC")),
    BelgeTuru("REACH_TEST", "REACH Ek XVII test raporu", KATEGORI_TEST, "Kısıtlı maddeler testi", ("EKXVII", "ANNEXXVII")),
    BelgeTuru("EN71", "EN 71 oyuncak test raporu", KATEGORI_TEST, "Oyuncak güvenliği", ("EN71",)),
    BelgeTuru("TEST", "Laboratuvar test raporu", KATEGORI_TEST, "Akredite laboratuvar raporu", ("TEST", "ANALIZ", "LAB", "RAPOR")),
    BelgeTuru("SDS", "Güvenlik Bilgi Formu (SDS)", KATEGORI_MEVZUAT, "Kimyasal karışımlar", ("SDS", "GBF", "MSDS", "GUVENLIKBILGIFORMU")),
    BelgeTuru("WEEE", "WEEE üretici kaydı", KATEGORI_KAYIT, "AEEE üretici sorumluluğu kaydı", ("WEEE", "AEEE")),
    BelgeTuru("EPREL", "EPREL kaydı", KATEGORI_KAYIT, "Enerji / lastik etiketi veritabanı", ("EPREL",)),
    BelgeTuru("IMDS", "IMDS kaydı", KATEGORI_KAYIT, "Otomotiv malzeme veri sistemi", ("IMDS",)),
    BelgeTuru("EUDR", "EUDR durum tespit beyanı", KATEGORI_MEVZUAT, "Ormansızlaşma Tüzüğü, hasat yeri verisi", ("EUDR", "DDS", "DUEDILIGENCE")),
    BelgeTuru("CBAM", "CBAM emisyon raporu", KATEGORI_MEVZUAT, "Gömülü emisyon verisi", ("CBAM", "SKDM", "GOMULUEMISYON")),
    BelgeTuru("MENSE", "Menşe / dolaşım belgesi", KATEGORI_GUMRUK, "A.TR, EUR.1, menşe şahadetnamesi", ("ATR", "EUR1", "MENSE", "MENSEI")),
    BelgeTuru("GOTS", "GOTS", KATEGORI_URUN_SERTIFIKA, "Organik tekstil standardı", ("GOTS",)),
    BelgeTuru("OCS", "OCS", KATEGORI_URUN_SERTIFIKA, "Organik içerik standardı", ("OCS", "ORGANICCONTENT")),
    BelgeTuru("GRS", "GRS", KATEGORI_URUN_SERTIFIKA, "Geri dönüştürülmüş içerik + sosyal/çevresel kriterler", ("GRS", "GLOBALRECYCLED")),
    BelgeTuru("RCS", "RCS", KATEGORI_URUN_SERTIFIKA, "Geri dönüştürülmüş içerik iddiası", ("RCS", "RECYCLEDCLAIM")),
    BelgeTuru("OEKOTEX", "OEKO-TEX", KATEGORI_URUN_SERTIFIKA, "Zararlı madde testi etiketi", ("OEKOTEX", "OEKO")),
    BelgeTuru("ZDHC", "ZDHC uyum belgesi", KATEGORI_URUN_SERTIFIKA, "Kimyasal yönetimi", ("ZDHC",)),
    BelgeTuru("BLUESIGN", "bluesign", KATEGORI_URUN_SERTIFIKA, "Kimyasal ve süreç yönetimi", ("BLUESIGN",)),
    BelgeTuru("FSC", "FSC", KATEGORI_URUN_SERTIFIKA, "Sorumlu ormancılık", ("FSC",)),
    BelgeTuru("PEFC", "PEFC", KATEGORI_URUN_SERTIFIKA, "Sorumlu ormancılık", ("PEFC",)),
    BelgeTuru("ECOLABEL", "AB Ecolabel", KATEGORI_URUN_SERTIFIKA, "AB resmi çevre etiketi", ("ECOLABEL",)),
    BelgeTuru("EPD", "Çevresel Ürün Beyanı (EPD)", KATEGORI_CEVRE, "ISO 14025 / EN 15804", ("EPD",)),
    BelgeTuru("KARBON", "Karbon ayak izi çalışması", KATEGORI_CEVRE, "ISO 14067 / PEF", ("ISO14067", "PEF", "KARBONAYAKIZI", "CARBONFOOTPRINT")),
    BelgeTuru("ISO9001", "ISO 9001", KATEGORI_YONETIM, "Kalite yönetim sistemi (kuruluş düzeyi)", ("ISO9001",)),
    BelgeTuru("ISO14001", "ISO 14001", KATEGORI_YONETIM, "Çevre yönetim sistemi (kuruluş düzeyi)", ("ISO14001",)),
    BelgeTuru("ISO50001", "ISO 50001", KATEGORI_YONETIM, "Enerji yönetim sistemi (kuruluş düzeyi)", ("ISO50001",)),
    BelgeTuru("ISO45001", "ISO 45001", KATEGORI_YONETIM, "İSG yönetim sistemi (kuruluş düzeyi)", ("ISO45001",)),
    BelgeTuru("IATF", "IATF 16949", KATEGORI_YONETIM, "Otomotiv kalite yönetimi (kuruluş düzeyi)", ("IATF",)),
    BelgeTuru("DIGER", "Diğer belge", KATEGORI_DIGER, "Katalogda olmayan belge", ()),
]
BELGE = {b.kod: b for b in BELGE_TURLERI}
YONETIM_SISTEMI_KODLARI = {b.kod for b in BELGE_TURLERI if b.kategori == KATEGORI_YONETIM}


def belge_turu_tahmin(serbest_metin) -> str:
    """İçe aktarımda serbest metin belge türünü katalog koduna eşler."""
    ham = metin(serbest_metin)
    if not ham:
        return "DIGER"
    buyuk = ham.upper().translate(str.maketrans("ÇĞİÖŞÜ", "CGIOSU"))
    tokenler = [t for t in re.split(r"[^A-Z0-9]+", buyuk) if t]
    bitisik = "".join(tokenler)
    # Önce uzun / özgül anahtarlar, en son genel "TEST/RAPOR" eşleşmesi
    oncelik = {"REACH_TEST": 0, "EN71": 0, "TEST": 2}
    sirali = sorted([b for b in BELGE_TURLERI if b.anahtarlar], key=lambda b: oncelik.get(b.kod, 1))
    for b in sirali:
        for a in b.anahtarlar:
            if a in tokenler or (len(a) >= 4 and a in bitisik):
                return b.kod
    return "DIGER"


def belge_adi(kod: str, serbest: str = "") -> str:
    if kod == "DIGER" and serbest:
        return serbest
    return BELGE.get(kod, BELGE["DIGER"]).ad
