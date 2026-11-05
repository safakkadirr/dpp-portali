"""
Excel içe / dışa aktarım.

Şablon sayfaları: Urunler, Malzemeler, Partiler, Tedarik_Zinciri, Belgeler, Tedarikciler, Tesisler.
Önceki sürümlerin dosyaları (tek sayfa, Malzeme_Bilesimi metni, Cevre_Sertifikasi sütunu) da okunur.

İçe aktarım iki adımlıdır: önizleme (hiçbir şey yazılmaz) → onay (tek işlemde yazılır).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import pandas as pd

from . import audit, repo
from .catalog import BELGE, SEKTOR, SEKTOR_ADLARI, belge_turu_tahmin, sektor_oner
from .db import Veritabani
from .util import bos_mu, evet_mi, gtin_dogrula, gtin_temizle, malzeme_ayristir, metin, sayi, tarih_metni, tr_norm

# (sütun, zorunluluk, açıklama, örnek)
SABLON: dict[str, list[tuple[str, str, str, str]]] = {
    "Urunler": [
        ("Urun_Kodu", "Zorunlu", "Firma içi ürün / model kodu (benzersiz)", "TK-1001"),
        ("Urun_Adi", "Zorunlu", "Ürün adı", "Organik Pamuk Tişört"),
        ("Sektor", "Önerilen", "Boş bırakılırsa GTİP kodundan önerilir. Seçenekler: " + ", ".join(s.ad for s in SEKTOR.values()), "Tekstil ve hazır giyim"),
        ("GTIP", "Önerilen", "Gümrük tarife kodu (en az 6 hane)", "6109.10"),
        ("GTIN", "Önerilen", "GS1 barkod numarası. Excel'de METİN olarak girin", "8690000000012"),
        ("Marka", "İsteğe bağlı", "Marka", "Örnek"),
        ("Tuketici_Urunu", "Önerilen", "Evet / Hayır — son tüketiciye satılıyor mu", "Evet"),
        ("Uretim_Tesisi", "Önerilen", "Tesis adı (Tesisler sayfasında yoksa otomatik açılır)", "Bursa OSB Tesisi"),
        ("AB_Sorumlu_Operator", "Tüketici ürünlerinde zorunlu", "AB'deki sorumlu ekonomik operatör: unvan, adres, e-posta", "Beispiel GmbH, Köln, info@beispiel.de"),
        ("Uretim_Ulkesi", "Zorunlu", "Nihai üretim (menşe) ülkesi", "Türkiye"),
        ("Hammadde_Mensei", "Önerilen", "Ana hammaddenin menşei", "Türkiye"),
        ("Geri_Donusturulmus_Icerik_Yuzde", "İsteğe bağlı", "Geri dönüştürülmüş içerik (%)", "0"),
        ("SVHC_Beyani", "Zorunlu", "Yok / Var / Bilinmiyor", "Yok"),
        ("SVHC_Maddeler", "SVHC Var ise", "Madde adı ve CAS no", ""),
        ("Cevresel_Iddia", "İsteğe bağlı", "Etikette / katalogda kullanılan çevre iddiası", "Organik pamuk"),
        ("Karbon_Ayak_Izi_kgCO2e", "İsteğe bağlı", "Birim başına kg CO2e", "4.2"),
        ("Karbon_Yontemi", "Karbon girildiyse", "ISO 14067, PEF, EPD", "ISO 14067"),
        ("Gomulu_Emisyon_tCO2e_t", "Demir-çelik / alüminyum", "CBAM gömülü emisyon (tCO2e / ton)", ""),
        ("EPREL_No", "Enerji / lastik etiketli ürünler", "EPREL kayıt numarası", ""),
        ("IMDS_ID", "Otomotiv", "IMDS kayıt numarası", ""),
        ("Batarya_Kategorisi", "Batarya", "EV / LMT / Endüstriyel / Taşınabilir", ""),
        ("Batarya_Kimyasi", "Batarya", "ör. LFP, NMC", ""),
        ("Batarya_Kapasite_kWh", "Batarya", "Kapasite (kWh)", ""),
        ("Bakim_Onarim_Bilgisi", "Önerilen", "Bakım, onarım, yedek parça bilgisi", "30°C'de ters yıkayın"),
        ("Omur_Sonu_Talimati", "Önerilen", "Geri dönüşüm / bertaraf talimatı", "Tekstil geri dönüşüm noktasına"),
    ],
    "Malzemeler": [
        ("Urun_Kodu", "Zorunlu", "Ürün kodu", "TK-1001"),
        ("Malzeme", "Zorunlu", "Malzeme / lif adı", "Pamuk"),
        ("Oran_Yuzde", "Zorunlu", "Ağırlıkça yüzde (ürün toplamı 100)", "95"),
        ("Mense", "Önerilen", "Malzemenin menşe ülkesi", "Türkiye"),
        ("Geri_Donusturulmus", "İsteğe bağlı", "Evet / Hayır", "Hayır"),
        ("Tedarikci", "İsteğe bağlı", "Tedarikçi unvanı", "Örnek İplik Ltd."),
    ],
    "Partiler": [
        ("Urun_Kodu", "Zorunlu", "Ürün kodu", "TK-1001"),
        ("Parti_No", "Zorunlu", "Parti / lot numarası", "LOT-2026-101"),
        ("Uretim_Tarihi", "Önerilen", "Üretim tarihi", "2026-09-15"),
        ("Miktar", "İsteğe bağlı", "Adet / kg", "5000"),
        ("Tesis", "İsteğe bağlı", "Üretim tesisi adı", "Bursa OSB Tesisi"),
    ],
    "Tedarik_Zinciri": [
        ("Urun_Kodu", "Zorunlu", "Ürün kodu", "TK-1001"),
        ("Sira", "Önerilen", "Aşama sırası", "1"),
        ("Asama", "Zorunlu", "İplik, kumaş, boya, montaj ...", "İplik"),
        ("Tedarikci", "Önerilen", "Tedarikçi unvanı", "Örnek İplik Ltd."),
        ("Ulke", "Zorunlu", "Aşamanın gerçekleştiği ülke", "Türkiye"),
        ("Belge_No", "İsteğe bağlı", "Aşamayı destekleyen belge no", ""),
    ],
    "Belgeler": [
        ("Baglanti", "Zorunlu", "Ürün kodu; tüm firma için *; tesis için TESIS:ad; tedarikçi için TEDARIKCI:unvan. Birden fazlası ; ile", "TK-1001"),
        ("Belge_Turu", "Zorunlu", "Seçenekler: " + ", ".join(b.ad for b in BELGE.values()), "GOTS"),
        ("Belge_No", "Önerilen", "Belge / sertifika no", "CU-889911"),
        ("Duzenleyen", "Önerilen", "Düzenleyen kuruluş", "Control Union"),
        ("Gecerlilik_Baslangic", "İsteğe bağlı", "Başlangıç tarihi", "2025-09-01"),
        ("Gecerlilik_Bitis", "Önerilen", "Bitiş tarihi (süresizse boş)", "2027-08-31"),
        ("Kapsam", "İsteğe bağlı", "Belgenin kapsamı", "Örme ürünler"),
    ],
    "Tedarikciler": [
        ("Unvan", "Zorunlu", "Tedarikçi unvanı", "Örnek İplik Ltd."),
        ("Ulke", "Önerilen", "Ülke", "Türkiye"),
        ("Eposta", "Önerilen", "Veri talebi gönderilecek e-posta", "kalite@ornekiplik.com"),
        ("Yetkili", "İsteğe bağlı", "Yetkili kişi", "Ayşe Yılmaz"),
        ("Kimlik_No", "İsteğe bağlı", "Vergi no / GLN", ""),
    ],
    "Tesisler": [
        ("Ad", "Zorunlu", "Tesis adı", "Bursa OSB Tesisi"),
        ("Adres", "Önerilen", "Açık adres", "Bursa OSB 1. Cad. No:5"),
        ("Ulke", "Önerilen", "Ülke", "Türkiye"),
        ("GLN", "İsteğe bağlı", "GS1 GLN numarası", ""),
        ("Tur", "İsteğe bağlı", "Üretim / Depo", "Üretim"),
    ],
}

# Sütun adı eşleştirme (normalleştirilmiş ad -> şablon adı)
ES_AD = {
    "urun_kodu": "Urun_Kodu", "urunkodu": "Urun_Kodu", "kod": "Urun_Kodu", "stok_kodu": "Urun_Kodu", "sku": "Urun_Kodu", "model_kodu": "Urun_Kodu",
    "urun_adi": "Urun_Adi", "urunadi": "Urun_Adi", "urun": "Urun_Adi",
    "sektor": "Sektor", "gtip": "GTIP", "gtip_kodu": "GTIP", "hs_kodu": "GTIP", "hs_code": "GTIP",
    "gtin": "GTIN", "barkod": "GTIN", "ean": "GTIN", "marka": "Marka", "brand": "Marka",
    "tuketici_urunu": "Tuketici_Urunu", "uretim_tesisi": "Uretim_Tesisi", "tesis": "Tesis",
    "ab_sorumlu_operator": "AB_Sorumlu_Operator", "uretim_ulkesi": "Uretim_Ulkesi", "hammadde_mensei": "Hammadde_Mensei",
    "geri_donusturulmus_icerik_yuzde": "Geri_Donusturulmus_Icerik_Yuzde", "svhc_beyani": "SVHC_Beyani", "svhc": "SVHC_Beyani",
    "svhc_maddeler": "SVHC_Maddeler", "cevresel_iddia": "Cevresel_Iddia",
    "karbon_ayak_izi_kgco2e": "Karbon_Ayak_Izi_kgCO2e", "karbon_ayak_izi_kg": "Karbon_Ayak_Izi_kgCO2e", "karbon_ayak_izi": "Karbon_Ayak_Izi_kgCO2e",
    "karbon_yontemi": "Karbon_Yontemi", "gomulu_emisyon_tco2e_t": "Gomulu_Emisyon_tCO2e_t", "gomulu_emisyon": "Gomulu_Emisyon_tCO2e_t",
    "eprel_no": "EPREL_No", "imds_id": "IMDS_ID", "batarya_kategorisi": "Batarya_Kategorisi", "batarya_kimyasi": "Batarya_Kimyasi",
    "batarya_kapasite_kwh": "Batarya_Kapasite_kWh", "bakim_onarim_bilgisi": "Bakim_Onarim_Bilgisi",
    "omur_sonu_talimati": "Omur_Sonu_Talimati",
    "malzeme": "Malzeme", "oran_yuzde": "Oran_Yuzde", "oran": "Oran_Yuzde", "mense": "Mense", "geri_donusturulmus": "Geri_Donusturulmus",
    "tedarikci": "Tedarikci", "parti_no": "Parti_No", "lot": "Parti_No", "lot_no": "Parti_No", "uretim_tarihi": "Uretim_Tarihi", "miktar": "Miktar",
    "sira": "Sira", "asama_sira": "Sira", "asama": "Asama", "ulke": "Ulke", "belge_no": "Belge_No", "sertifika_no": "Belge_No",
    "baglanti": "Baglanti", "belge_turu": "Belge_Turu", "sertifika": "Belge_Turu", "duzenleyen": "Duzenleyen",
    "gecerlilik_baslangic": "Gecerlilik_Baslangic", "gecerlilik_bitis": "Gecerlilik_Bitis", "bitis_tarihi": "Gecerlilik_Bitis",
    "kapsam": "Kapsam", "unvan": "Unvan", "eposta": "Eposta", "e_posta": "Eposta", "yetkili": "Yetkili", "kimlik_no": "Kimlik_No",
    "ad": "Ad", "adres": "Adres", "gln": "GLN", "tur": "Tur",
    # eski sürümler
    "malzeme_bilesimi": "_Malzeme_Bilesimi", "cevre_sertifikasi": "_Cevre_Sertifikasi",
    "sertifika_bitis_tarihi": "_Sertifika_Bitis", "ihracatci_unvan": "_Ihracatci", "tesis_id": "_Tesis_ID",
    "geri_donusturulebilirlik_orani": "_Geri_Donusturulebilirlik",
}


def _anahtar(ad) -> str:
    return re.sub(r"[^a-z0-9]+", "_", tr_norm(ad)).strip("_")


def _standart(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={k: ES_AD.get(_anahtar(k), str(k).strip()) for k in df.columns})
    df = df.loc[:, ~df.columns.duplicated()]
    return df.dropna(how="all")


def _sayfa_turu(ad: str, df: pd.DataFrame) -> str | None:
    n = _anahtar(ad)
    for sayfa in SABLON:
        if _anahtar(sayfa) == n:
            return sayfa
    if "aciklama" in n or "okubeni" in n:
        return None
    if "belge" in n or "sertifika" in n:
        return "Belgeler"
    if "malzeme" in n or "bilesim" in n:
        return "Malzemeler"
    if "parti" in n or "lot" in n:
        return "Partiler"
    if "tedarik_zinciri" in n or "asama" in n or "zincir" in n:
        return "Tedarik_Zinciri"
    if "tedarikci" in n:
        return "Tedarikciler"
    if "tesis" in n:
        return "Tesisler"
    k = set(df.columns)
    if "Urun_Adi" in k and "Urun_Kodu" in k:
        return "Urunler"
    if "Belge_Turu" in k:
        return "Belgeler"
    if "Malzeme" in k:
        return "Malzemeler"
    if "Asama" in k:
        return "Tedarik_Zinciri"
    return None


@dataclass
class Onizleme:
    sayfalar: dict[str, pd.DataFrame] = field(default_factory=dict)
    hatalar: list[str] = field(default_factory=list)
    uyarilar: list[str] = field(default_factory=list)
    yeni_urun: int = 0
    guncel_urun: int = 0

    @property
    def gecerli(self) -> bool:
        return not self.hatalar and any(not d.empty for d in self.sayfalar.values())


def oku(dosyalar: list[tuple[str, bytes]], db: Veritabani, firma_id: int) -> Onizleme:
    o = Onizleme()
    parcalar: dict[str, list[pd.DataFrame]] = {k: [] for k in SABLON}
    for ad, icerik in dosyalar:
        try:
            sayfalar = pd.read_excel(io.BytesIO(icerik), sheet_name=None, dtype=object)
        except Exception as hata:
            o.hatalar.append(f"{ad}: dosya okunamadı ({hata})")
            continue
        for sayfa_adi, ham in sayfalar.items():
            if ham is None or ham.dropna(how="all").empty:
                continue
            df = _standart(ham)
            tur = _sayfa_turu(str(sayfa_adi), df)
            if not tur:
                continue
            df["_kaynak"] = f"{ad} / {sayfa_adi}"
            df["_satir"] = range(2, len(df) + 2)
            parcalar[tur].append(df)

    for tur, liste in parcalar.items():
        o.sayfalar[tur] = pd.concat(liste, ignore_index=True) if liste else pd.DataFrame()

    u = o.sayfalar["Urunler"]
    if not u.empty:
        if "Urun_Kodu" not in u.columns:
            o.hatalar.append("Ürün sayfasında 'Urun_Kodu' sütunu yok.")
            return o
        u["Urun_Kodu"] = u["Urun_Kodu"].map(metin)
        if "Urun_Adi" not in u.columns:
            u["Urun_Adi"] = None
        bos_kod = u[u["Urun_Kodu"] == ""]
        if not bos_kod.empty:
            o.uyarilar.append(f"{len(bos_kod)} satırda ürün kodu boş; bu satırlar atlanacak.")
        u = u[u["Urun_Kodu"] != ""].copy()
        tekrar = u[u["Urun_Kodu"].duplicated()]["Urun_Kodu"].unique().tolist()
        if tekrar:
            o.uyarilar.append(f"{len(tekrar)} ürün kodu birden fazla satırda var (ör. {', '.join(tekrar[:5])}); son satır esas alınacak.")
            u = u.drop_duplicates("Urun_Kodu", keep="last")
        mevcut = {r["urun_kodu"] for r in db.tumu("SELECT urun_kodu FROM urunler WHERE firma_id = ?", (firma_id,))}
        adsiz = u[(u["Urun_Adi"].map(bos_mu)) & (~u["Urun_Kodu"].isin(mevcut))]
        for r in adsiz.itertuples():
            o.hatalar.append(f"{r._kaynak} satır {r._satir}: yeni ürün '{r.Urun_Kodu}' için Urun_Adi zorunlu.")
        if "GTIN" in u.columns:
            for r in u.itertuples():
                g = getattr(r, "GTIN")
                if not bos_mu(g) and not gtin_dogrula(g)[0]:
                    o.uyarilar.append(f"{r.Urun_Kodu}: {gtin_dogrula(g)[1]} — kaydedilecek, değerlendirmede eksik görünecek.")
        o.yeni_urun = int((~u["Urun_Kodu"].isin(mevcut)).sum())
        o.guncel_urun = int(u["Urun_Kodu"].isin(mevcut).sum())
        if "_Cevre_Sertifikasi" in u.columns:
            o.uyarilar.append("Eski format algılandı: 'Cevre_Sertifikasi' sütunu belge kasasına aktarılacak (bitiş tarihiyle).")
        if "_Geri_Donusturulebilirlik" in u.columns:
            o.uyarilar.append("'Geri_Donusturulebilirlik_Orani' geri dönüştürülmüş İÇERİK oranı olmadığı için aktarılmayacak.")
        o.sayfalar["Urunler"] = u

    tum_kodlar = set(o.sayfalar["Urunler"]["Urun_Kodu"]) if not o.sayfalar["Urunler"].empty else set()
    tum_kodlar |= {r["urun_kodu"] for r in db.tumu("SELECT urun_kodu FROM urunler WHERE firma_id = ?", (firma_id,))}
    for tur in ("Malzemeler", "Partiler", "Tedarik_Zinciri"):
        df = o.sayfalar[tur]
        if df.empty:
            continue
        if "Urun_Kodu" not in df.columns:
            o.hatalar.append(f"{tur} sayfasında 'Urun_Kodu' sütunu yok.")
            continue
        df["Urun_Kodu"] = df["Urun_Kodu"].map(metin)
        bilinmeyen = sorted(set(df["Urun_Kodu"]) - tum_kodlar - {""})
        if bilinmeyen:
            o.uyarilar.append(f"{tur}: {len(bilinmeyen)} satırdaki ürün kodu bulunamadı ve atlanacak (ör. {', '.join(bilinmeyen[:5])}).")
    m = o.sayfalar["Malzemeler"]
    if not m.empty and "Oran_Yuzde" in m.columns:
        toplam = m.assign(_o=m["Oran_Yuzde"].map(lambda v: sayi(v) or 0)).groupby("Urun_Kodu")["_o"].sum()
        yanlis = toplam[(toplam - 100).abs() > 1]
        if len(yanlis):
            o.uyarilar.append(f"{len(yanlis)} ürünün malzeme toplamı %100 değil (ör. {', '.join(f'{k}: %{v:g}' for k, v in yanlis.head(3).items())}).")
    b = o.sayfalar["Belgeler"]
    if not b.empty and "Belge_Turu" in b.columns:
        tahmin = b["Belge_Turu"].map(belge_turu_tahmin)
        diger = b[tahmin == "DIGER"]["Belge_Turu"].dropna().astype(str).unique().tolist()
        if diger:
            o.uyarilar.append(f"Türü tanınamayan belgeler 'Diğer' olarak kaydedilecek: {', '.join(diger[:5])}")
    return o


def _s(r: dict, k: str):
    v = r.get(k)
    return None if bos_mu(v) else v


def uygula(db: Veritabani, firma_id: int, o: Onizleme, kullanici: str) -> dict:
    """Önizlenen veriyi tek işlemde veritabanına yazar."""
    sayac = {"urun_yeni": 0, "urun_guncel": 0, "malzeme": 0, "parti": 0, "asama": 0, "belge": 0, "tedarikci": 0, "tesis": 0}
    with db.islem():
        for r in o.sayfalar.get("Tesisler", pd.DataFrame()).to_dict("records"):
            if _s(r, "Ad"):
                tid = repo.tesis_bul_veya_ekle(db, firma_id, r["Ad"])
                db.guncelle("tesisler", tid, {k2: metin(_s(r, k1)) or None for k1, k2 in
                                               (("Adres", "adres"), ("Ulke", "ulke"), ("GLN", "gln"), ("Tur", "tur")) if _s(r, k1)}, firma_id)
                sayac["tesis"] += 1
        for r in o.sayfalar.get("Tedarikciler", pd.DataFrame()).to_dict("records"):
            if _s(r, "Unvan"):
                tid = repo.tedarikci_bul_veya_ekle(db, firma_id, r["Unvan"])
                db.guncelle("tedarikciler", tid, {k2: metin(_s(r, k1)) or None for k1, k2 in
                                                   (("Ulke", "ulke"), ("Eposta", "eposta"), ("Yetkili", "yetkili"),
                                                    ("Kimlik_No", "kimlik_no")) if _s(r, k1)}, firma_id)
                sayac["tedarikci"] += 1

        urun_id: dict[str, int] = {r["urun_kodu"]: r["id"] for r in db.tumu("SELECT id, urun_kodu FROM urunler WHERE firma_id = ?", (firma_id,))}
        eski_malzeme: dict[str, list] = {}
        eski_belge: list[dict] = []
        for r in o.sayfalar.get("Urunler", pd.DataFrame()).to_dict("records"):
            kod = metin(r["Urun_Kodu"])
            sektor = _s(r, "Sektor")
            veri = {
                "urun_kodu": kod, "ad": metin(_s(r, "Urun_Adi")) or None,
                "gtip": metin(_s(r, "GTIP")) or None, "gtin": gtin_temizle(_s(r, "GTIN")) or None,
                "marka": metin(_s(r, "Marka")) or None,
                "ab_sorumlu_operator": _s(r, "AB_Sorumlu_Operator"), "uretim_ulkesi": _s(r, "Uretim_Ulkesi"),
                "hammadde_mensei": _s(r, "Hammadde_Mensei"),
                "geri_donusturulmus_yuzde": sayi(_s(r, "Geri_Donusturulmus_Icerik_Yuzde")),
                "svhc_beyani": _s(r, "SVHC_Beyani"), "svhc_maddeler": _s(r, "SVHC_Maddeler"),
                "cevresel_iddia": _s(r, "Cevresel_Iddia"), "karbon_kg": sayi(_s(r, "Karbon_Ayak_Izi_kgCO2e")),
                "karbon_yontemi": _s(r, "Karbon_Yontemi"), "gomulu_emisyon": sayi(_s(r, "Gomulu_Emisyon_tCO2e_t")),
                "eprel_no": metin(_s(r, "EPREL_No")) or None, "imds_id": metin(_s(r, "IMDS_ID")) or None,
                "batarya_kategori": _s(r, "Batarya_Kategorisi"), "batarya_kimya": _s(r, "Batarya_Kimyasi"),
                "batarya_kwh": sayi(_s(r, "Batarya_Kapasite_kWh")),
                "bakim_onarim": _s(r, "Bakim_Onarim_Bilgisi"), "omur_sonu": _s(r, "Omur_Sonu_Talimati"),
            }
            if "Tuketici_Urunu" in r:
                e = evet_mi(r.get("Tuketici_Urunu"))
                veri["tuketici_urunu"] = None if e is None else int(e)
            if _s(r, "Uretim_Tesisi"):
                veri["tesis_id"] = repo.tesis_bul_veya_ekle(db, firma_id, r["Uretim_Tesisi"])
            if sektor or kod not in urun_id:
                veri["sektor_kodu"] = sektor_oner(None, sektor) if sektor else sektor_oner(_s(r, "GTIP"), _s(r, "Urun_Adi"))
                if sektor and veri["sektor_kodu"] == "diger" and _s(r, "GTIP"):
                    veri["sektor_kodu"] = sektor_oner(_s(r, "GTIP"), sektor)
            # Dosyada olmayan sütunlar mevcut veriyi silmesin
            veri = {k: v for k, v in veri.items() if k in ("urun_kodu", "sektor_kodu", "tesis_id", "tuketici_urunu") or v is not None}
            if kod in urun_id:
                repo.urun_kaydet(db, firma_id, veri, kullanici, urun_id[kod])
                sayac["urun_guncel"] += 1
            else:
                urun_id[kod] = repo.urun_kaydet(db, firma_id, veri, kullanici)
                sayac["urun_yeni"] += 1
            if _s(r, "_Malzeme_Bilesimi"):
                eski_malzeme[kod] = [{"malzeme": a, "oran": o_} for a, o_ in malzeme_ayristir(r["_Malzeme_Bilesimi"])]
            if _s(r, "_Cevre_Sertifikasi"):
                eski_belge.append({"Baglanti": kod, "Belge_Turu": r["_Cevre_Sertifikasi"], "Gecerlilik_Bitis": r.get("_Sertifika_Bitis")})
            if _s(r, "Parti_No"):
                o.sayfalar.setdefault("Partiler", pd.DataFrame())
                o.sayfalar["Partiler"] = pd.concat([o.sayfalar["Partiler"], pd.DataFrame([{"Urun_Kodu": kod, "Parti_No": r["Parti_No"],
                                                    "Uretim_Tarihi": r.get("Uretim_Tarihi")}])], ignore_index=True)

        def grupla(tur):
            df = o.sayfalar.get(tur, pd.DataFrame())
            if df.empty or "Urun_Kodu" not in df.columns:
                return {}
            return {k: g.to_dict("records") for k, g in df.groupby(df["Urun_Kodu"].map(metin))}

        malzeme_gruplari = grupla("Malzemeler")
        for kod, liste in eski_malzeme.items():
            malzeme_gruplari.setdefault(kod, liste)
        for kod, satirlar in malzeme_gruplari.items():
            if kod not in urun_id:
                continue
            temiz = []
            for s in satirlar:
                if "malzeme" in s:  # eski format
                    temiz.append(s)
                    continue
                temiz.append({"malzeme": _s(s, "Malzeme"), "oran": sayi(_s(s, "Oran_Yuzde")), "mense": _s(s, "Mense"),
                              "geri_donusturulmus": 1 if evet_mi(s.get("Geri_Donusturulmus")) else 0,
                              "tedarikci_id": repo.tedarikci_bul_veya_ekle(db, firma_id, _s(s, "Tedarikci")) if _s(s, "Tedarikci") else None})
            sayac["malzeme"] += repo.alt_degistir(db, "malzemeler", firma_id, urun_id[kod], temiz, kullanici, denetle=False)

        for kod, satirlar in grupla("Partiler").items():
            if kod not in urun_id:
                continue
            mevcut = {p["parti_no"]: p for p in repo.alt_liste(db, "partiler", firma_id, urun_id[kod])}
            for s in satirlar:
                no = metin(_s(s, "Parti_No"))
                if not no:
                    continue
                mevcut[no] = {"parti_no": no, "uretim_tarihi": tarih_metni(_s(s, "Uretim_Tarihi")) or mevcut.get(no, {}).get("uretim_tarihi"),
                              "miktar": sayi(_s(s, "Miktar")),
                              "tesis_id": repo.tesis_bul_veya_ekle(db, firma_id, _s(s, "Tesis")) if _s(s, "Tesis") else mevcut.get(no, {}).get("tesis_id")}
            sayac["parti"] += repo.alt_degistir(db, "partiler", firma_id, urun_id[kod], list(mevcut.values()), kullanici, denetle=False)

        for kod, satirlar in grupla("Tedarik_Zinciri").items():
            if kod not in urun_id:
                continue
            temiz = [{"sira": int(sayi(_s(s, "Sira")) or i + 1), "asama": _s(s, "Asama"), "ulke": _s(s, "Ulke"),
                      "belge_no": metin(_s(s, "Belge_No")) or None,
                      "tedarikci_id": repo.tedarikci_bul_veya_ekle(db, firma_id, _s(s, "Tedarikci")) if _s(s, "Tedarikci") else None}
                     for i, s in enumerate(satirlar)]
            sayac["asama"] += repo.alt_degistir(db, "tedarik_asamalari", firma_id, urun_id[kod], temiz, kullanici, denetle=False)

        belgeler = o.sayfalar.get("Belgeler", pd.DataFrame()).to_dict("records") + eski_belge
        for r in belgeler:
            tur_ham = _s(r, "Belge_Turu")
            if not tur_ham:
                continue
            baglanti_metni = metin(_s(r, "Baglanti") or _s(r, "Urun_Kodu")) or "*"
            baglar = []
            for parca in [p.strip() for p in baglanti_metni.split(";") if p.strip()]:
                if parca == "*":
                    baglar.append(("firma", None))
                elif tr_norm(parca).startswith("tesis:"):
                    baglar.append(("tesis", repo.tesis_bul_veya_ekle(db, firma_id, parca.split(":", 1)[1])))
                elif tr_norm(parca).startswith("tedarikci:"):
                    baglar.append(("tedarikci", repo.tedarikci_bul_veya_ekle(db, firma_id, parca.split(":", 1)[1])))
                elif parca in urun_id:
                    baglar.append(("urun", urun_id[parca]))
            if not baglar:
                continue
            kod = belge_turu_tahmin(tur_ham)
            veri = {"tur_kodu": kod, "tur_serbest": metin(tur_ham), "belge_no": metin(_s(r, "Belge_No")) or None,
                    "duzenleyen": _s(r, "Duzenleyen"), "baslangic": tarih_metni(_s(r, "Gecerlilik_Baslangic")),
                    "bitis": tarih_metni(_s(r, "Gecerlilik_Bitis")), "kapsam": _s(r, "Kapsam")}
            ayni = None
            if veri["belge_no"]:
                ayni = db.bir("SELECT id FROM belgeler WHERE firma_id = ? AND tur_kodu = ? AND belge_no = ?",
                              (firma_id, kod, veri["belge_no"]))
            if ayni:
                db.guncelle("belgeler", ayni["id"], {k: v for k, v in veri.items() if v is not None}, firma_id)
                mevcut_bag = [(x["hedef_tur"], x["hedef_id"]) for x in
                              db.tumu("SELECT hedef_tur, hedef_id FROM belge_baglantilari WHERE belge_id = ?", (ayni["id"],))]
                repo.belge_baglantilari_ayarla(db, firma_id, ayni["id"], mevcut_bag + baglar)
            else:
                repo.belge_ekle(db, firma_id, veri, baglar, kullanici, kaynak="Excel içe aktarım")
            sayac["belge"] += 1
        audit.kaydet(db, firma_id, kullanici, "Excel içe aktarım", "firma", firma_id,
                     ", ".join(f"{k}: {v}" for k, v in sayac.items() if v))
    return sayac


# ---------------------------------------------------------------------------
# Şablon ve dışa aktarım
# ---------------------------------------------------------------------------

def _yaz(yazici, df: pd.DataFrame, ad: str, metin_sutunlari=()):
    df.to_excel(yazici, index=False, sheet_name=ad[:31])
    ws = yazici.sheets[ad[:31]]
    from openpyxl.styles import Font, PatternFill
    for i, kolon in enumerate(df.columns, 1):
        hucre = ws.cell(row=1, column=i)
        hucre.font = Font(bold=True, color="FFFFFF")
        hucre.fill = PatternFill("solid", fgColor="1F3A5F")
        uzunluk = max([len(str(kolon))] + [len(str(v)) for v in df[kolon].head(200).tolist()])
        ws.column_dimensions[hucre.column_letter].width = min(max(10, uzunluk + 2), 60)
        if kolon in metin_sutunlari:
            for h in ws[hucre.column_letter][1:max(len(df) + 1, 500)]:
                h.number_format = "@"
    ws.freeze_panes = "A2"


def sablon() -> bytes:
    cikti = io.BytesIO()
    with pd.ExcelWriter(cikti, engine="openpyxl") as y:
        aciklama = [{"Sayfa": s, "Sütun": k, "Zorunluluk": z, "Açıklama": a, "Örnek": o}
                    for s, liste in SABLON.items() for k, z, a, o in liste]
        _yaz(y, pd.DataFrame(aciklama), "Aciklama")
        for s, liste in SABLON.items():
            _yaz(y, pd.DataFrame([{k: o for k, _, _, o in liste}]), s, ("GTIN", "GTIP", "GLN", "Belge_No", "Parti_No"))
    return cikti.getvalue()


def disa_aktar(db: Veritabani, firma_id: int) -> bytes:
    """Firmanın tüm verisini şablon biçiminde dışa aktarır (yeniden yüklenebilir)."""
    tesis = {t["id"]: t["ad"] for t in repo.tesisler(db, firma_id)}
    ted = {t["id"]: t["unvan"] for t in repo.tedarikciler(db, firma_id)}
    urunler = repo.urunler(db, firma_id)
    kod = {u["id"]: u["urun_kodu"] for u in urunler}
    sayfalar = {
        "Urunler": [{"Urun_Kodu": u["urun_kodu"], "Urun_Adi": u["ad"], "Sektor": SEKTOR_ADLARI.get(u["sektor_kodu"]),
                     "GTIP": u["gtip"], "GTIN": u["gtin"], "Marka": u["marka"],
                     "Tuketici_Urunu": None if u["tuketici_urunu"] is None else ("Evet" if u["tuketici_urunu"] else "Hayır"),
                     "Uretim_Tesisi": tesis.get(u["tesis_id"]), "AB_Sorumlu_Operator": u["ab_sorumlu_operator"],
                     "Uretim_Ulkesi": u["uretim_ulkesi"], "Hammadde_Mensei": u["hammadde_mensei"],
                     "Geri_Donusturulmus_Icerik_Yuzde": u["geri_donusturulmus_yuzde"], "SVHC_Beyani": u["svhc_beyani"],
                     "SVHC_Maddeler": u["svhc_maddeler"], "Cevresel_Iddia": u["cevresel_iddia"],
                     "Karbon_Ayak_Izi_kgCO2e": u["karbon_kg"], "Karbon_Yontemi": u["karbon_yontemi"],
                     "Gomulu_Emisyon_tCO2e_t": u["gomulu_emisyon"], "EPREL_No": u["eprel_no"], "IMDS_ID": u["imds_id"],
                     "Batarya_Kategorisi": u["batarya_kategori"], "Batarya_Kimyasi": u["batarya_kimya"],
                     "Batarya_Kapasite_kWh": u["batarya_kwh"], "Bakim_Onarim_Bilgisi": u["bakim_onarim"],
                     "Omur_Sonu_Talimati": u["omur_sonu"]} for u in urunler],
        "Malzemeler": [], "Partiler": [], "Tedarik_Zinciri": [], "Belgeler": [],
        "Tedarikciler": [{"Unvan": t["unvan"], "Ulke": t["ulke"], "Eposta": t["eposta"], "Yetkili": t["yetkili"],
                          "Kimlik_No": t["kimlik_no"]} for t in repo.tedarikciler(db, firma_id)],
        "Tesisler": [{"Ad": t["ad"], "Adres": t["adres"], "Ulke": t["ulke"], "GLN": t["gln"], "Tur": t["tur"]}
                     for t in repo.tesisler(db, firma_id)],
    }
    for u in urunler:
        for m in repo.alt_liste(db, "malzemeler", firma_id, u["id"]):
            sayfalar["Malzemeler"].append({"Urun_Kodu": u["urun_kodu"], "Malzeme": m["malzeme"], "Oran_Yuzde": m["oran"],
                                           "Mense": m["mense"], "Geri_Donusturulmus": "Evet" if m["geri_donusturulmus"] else "Hayır",
                                           "Tedarikci": ted.get(m["tedarikci_id"])})
        for p in repo.alt_liste(db, "partiler", firma_id, u["id"]):
            sayfalar["Partiler"].append({"Urun_Kodu": u["urun_kodu"], "Parti_No": p["parti_no"], "Uretim_Tarihi": p["uretim_tarihi"],
                                         "Miktar": p["miktar"], "Tesis": tesis.get(p["tesis_id"])})
        for a in repo.alt_liste(db, "tedarik_asamalari", firma_id, u["id"]):
            sayfalar["Tedarik_Zinciri"].append({"Urun_Kodu": u["urun_kodu"], "Sira": a["sira"], "Asama": a["asama"],
                                                "Tedarikci": ted.get(a["tedarikci_id"]), "Ulke": a["ulke"], "Belge_No": a["belge_no"]})
    for b in repo.belgeler(db, firma_id):
        baglar = []
        for x in b["baglantilar"]:
            if x["hedef_tur"] == "firma":
                baglar.append("*")
            elif x["hedef_tur"] == "urun" and x["hedef_id"] in kod:
                baglar.append(kod[x["hedef_id"]])
            elif x["hedef_tur"] == "tesis":
                baglar.append(f"TESIS:{tesis.get(x['hedef_id'], '')}")
            elif x["hedef_tur"] == "tedarikci":
                baglar.append(f"TEDARIKCI:{ted.get(x['hedef_id'], '')}")
        sayfalar["Belgeler"].append({"Baglanti": ";".join(baglar), "Belge_Turu": BELGE.get(b["tur_kodu"], BELGE["DIGER"]).ad
                                     if b["tur_kodu"] != "DIGER" else (b["tur_serbest"] or "Diğer"),
                                     "Belge_No": b["belge_no"], "Duzenleyen": b["duzenleyen"],
                                     "Gecerlilik_Baslangic": b["baslangic"], "Gecerlilik_Bitis": b["bitis"], "Kapsam": b["kapsam"]})
    cikti = io.BytesIO()
    with pd.ExcelWriter(cikti, engine="openpyxl") as y:
        for ad, satirlar in sayfalar.items():
            kolonlar = [k for k, *_ in SABLON[ad]]
            _yaz(y, pd.DataFrame(satirlar, columns=kolonlar), ad, ("GTIN", "GTIP", "GLN", "Belge_No", "Parti_No"))
    return cikti.getvalue()
