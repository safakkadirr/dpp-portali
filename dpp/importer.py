"""
Excel içe / dışa aktarım.

Şablon sayfaları: Urunler, Malzemeler, Partiler, Tedarik_Zinciri, Belgeler, Tedarikciler, Tesisler.
Önceki sürümlerin dosyaları (tek sayfa, Malzeme_Bilesimi metni, Cevre_Sertifikasi sütunu) da okunur.

Şablona uyma zorunluluğu yoktur: ham Excel / CSV dosyalarındaki sütunlar akıllı eşleme ile (dpp/esleme.py)
tanınır. İçe aktarım iki adımlıdır: önizleme (hiçbir şey yazılmaz) → onay. Onayda hatalı satırlar yalnızca
kendilerini etkiler; diğer satırlar aktarılır ve atlananlar nedenleriyle raporlanır.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from . import audit, esleme, repo
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

# ---------------------------------------------------------------------------
# Okuma ve akıllı eşleme
# ---------------------------------------------------------------------------

ILGILI_SAYFALAR = list(SABLON)


@dataclass
class Onizleme:
    sayfalar: dict[str, pd.DataFrame] = field(default_factory=dict)
    hatalar: list[str] = field(default_factory=list)
    uyarilar: list[str] = field(default_factory=list)
    varsayilanlar: list[str] = field(default_factory=list)
    esleme_raporu: list[dict] = field(default_factory=list)      # sütun bazında eşleme
    sayfa_raporu: list[dict] = field(default_factory=list)       # sayfa bazında tür ve satır sayısı
    yeni_urun: int = 0
    guncel_urun: int = 0
    atlanacak: list[dict] = field(default_factory=list)          # okunamayan / kimliksiz satırlar

    @property
    def gecerli(self) -> bool:
        return not self.hatalar and any(not d.empty for d in self.sayfalar.values())


def _benzersiz(basliklar: list) -> list[str]:
    sonuc, sayac = [], {}
    for i, b in enumerate(basliklar):
        ad = metin(b) or f"Sütun {i + 1}"
        if isinstance(b, float) and b.is_integer():
            ad = str(int(b))
        sayac[ad] = sayac.get(ad, 0) + 1
        sonuc.append(ad if sayac[ad] == 1 else f"{ad} ({sayac[ad]})")
    return sonuc


def _ham_sayfalar(ad: str, icerik: bytes) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Excel (xlsx/xls) veya CSV dosyasını başlıksız ham tablolar olarak okur. (sayfalar, uyarılar)"""
    if ad.lower().endswith((".csv", ".txt")):
        for kodlama in ("utf-8-sig", "cp1254", "latin-1"):
            try:
                metin_ = icerik.decode(kodlama)
            except UnicodeDecodeError:
                continue
            ayirac = max([";", ",", "\t", "|"], key=lambda a: metin_.splitlines()[0].count(a) if metin_ else 0)
            try:
                return {"CSV": pd.read_csv(io.StringIO(metin_), sep=ayirac, header=None, dtype=object)}, []
            except pd.errors.ParserError:
                df = pd.read_csv(io.StringIO(metin_), sep=ayirac, header=None, dtype=object, on_bad_lines="skip", engine="python")
                return {"CSV": df}, [f"{ad}: sütun sayısı başlıkla uyuşmayan satırlar atlandı (ör. hücre içinde '{ayirac}' "
                                     "karakteri). Bu satırları tırnak içine alın veya Excel olarak kaydedin."]
        raise ValueError("CSV dosyasının karakter kodlaması çözülemedi")
    return pd.read_excel(io.BytesIO(icerik), sheet_name=None, header=None, dtype=object), []


_BILESEN_SUTUNLARI = ["Uretim_Ulkesi", "Hammadde_Mensei", "_Tedarikci", "_Tedarikci_Ulke"]
_OZET_KELIMELERI = ("toplam", "ortalama", "genel toplam", "ara toplam", "total", "average", "sum", "subtotal")


def _ozet_satiri(deger) -> bool:
    n = tr_norm(deger)
    return bool(n) and any(n == k or n.startswith(k + " ") or n.startswith(k + ":") for k in _OZET_KELIMELERI)


def _sertifika_no(tur_metni, ayri_no=None):
    """'GOTS-TR-8821' gibi tür ve numaranın birlikte yazıldığı hücrelerden numarayı ayırır."""
    if not bos_mu(ayri_no):
        return metin(ayri_no)
    t = metin(tur_metni)
    return t if re.search(r"\d{3,}", t) else None


def _karbon_bileseni_mi(baslik) -> bool:
    n = esleme.normal(baslik)
    return ("emisyon" in n or "co2" in n or "karbon" in n) and not esleme.finansal_mi(baslik)


def _testleri_belgeye_cevir(t: pd.DataFrame) -> pd.DataFrame:
    """Laboratuvar test satırlarını belge kayıtlarına çevirir (test başına bir rapor)."""
    satirlar = []
    for r in t.to_dict("records"):
        madde = metin(r.get("_Test_Madde"))
        kimyasal = any(k in tr_norm(madde) for k in ("azo", "amin", "ftalat", "formaldehit", "metal", "kursun", "kadmiyum", "krom",
                                                     "pfas", "flor", "parafin", "sccp", "nikel", "apeo", "nonilfenol", "reach",
                                                     "svhc", "dmf", "pah", "organotin"))
        parcalar = [p for p in [metin(r.get("_Test_Bilesen")), madde] if p]
        olcum = ""
        if not bos_mu(r.get("_Test_Olculen")):
            olcum = f"ölçülen {metin(r.get('_Test_Olculen'))}" + (f" / limit {metin(r.get('_Test_Limit'))}" if not bos_mu(r.get("_Test_Limit")) else "")
        kapsam = " — ".join(p for p in [", ".join(parcalar), olcum, metin(r.get("_Test_Sonuc")), metin(r.get("_Test_Aksiyon"))] if p)
        satirlar.append({"Baglanti": metin(r.get("Urun_Kodu")) or "*",
                         "Belge_Turu": "REACH Ek XVII test raporu" if kimyasal else "Laboratuvar test raporu",
                         "Belge_No": metin(r.get("Belge_No")) or None, "Duzenleyen": r.get("Duzenleyen"),
                         "Gecerlilik_Baslangic": r.get("Gecerlilik_Baslangic"), "Kapsam": kapsam[:500],
                         "_Test_Sonuc": metin(r.get("_Test_Sonuc")), "_Test_Ozet": olcum,
                         "_kaynak": r.get("_kaynak"), "_satir": r.get("_satir")})
    return pd.DataFrame(satirlar)


def _test_sonucu(metin_) -> str:
    n = tr_norm(metin_)
    if any(k in n for k in ("uyumsuz", "uygun degil", "red", "fail", "basarisiz", "olumsuz", "kaldi")):
        return "olumsuz"
    if any(k in n for k in ("sartli", "kosullu", "conditional")):
        return "sartli"
    if any(k in n for k in ("uyumlu", "uygun", "gecti", "pass", "olumlu", "basarili")):
        return "olumlu"
    return ""


def _slug(metin_) -> str:
    s = re.sub(r"[^A-Z0-9]+", "-", tr_norm(metin_).upper()).strip("-")
    return s[:40] or "URUN"


def oku(dosyalar: list[tuple[str, bytes]], db: Veritabani, firma_id: int,
        elle: Optional[dict[str, str]] = None, elle_tur: Optional[dict[str, str]] = None) -> Onizleme:
    """
    Dosyaları okur, sütunları akıllı eşler, kontrol eder. Veritabanına HİÇBİR ŞEY yazmaz.

    elle      : {"dosya|sayfa|başlık": kanonik_alan | YOK_SAY}  — kullanıcının eşleme düzeltmeleri
    elle_tur  : {"dosya|sayfa": sayfa_türü | YOK_SAY}           — kullanıcının sayfa türü düzeltmeleri
    """
    elle, elle_tur = elle or {}, elle_tur or {}
    o = Onizleme()
    parcalar: dict[str, list[pd.DataFrame]] = {k: [] for k in ILGILI_SAYFALAR + ["Testler"]}

    for ad, icerik in dosyalar:
        try:
            sayfalar, okuma_uyarilari = _ham_sayfalar(ad, icerik)
            o.uyarilar.extend(okuma_uyarilari)
        except Exception as hata:
            o.hatalar.append(f"{ad}: dosya okunamadı ({hata}). Dosyanın bozuk veya parola korumalı olmadığını kontrol edin.")
            continue
        for sayfa_adi, ham in sayfalar.items():
            anahtar = f"{ad}|{sayfa_adi}"
            if ham is None:
                continue
            ham = ham.dropna(how="all").dropna(axis=1, how="all")   # dizin = Excel satırı - 1
            if ham.empty or len(ham) < 2:
                continue
            konum = esleme.baslik_satiri_bul(ham.reset_index(drop=True))
            satir = int(ham.index[konum])
            basliklar = _benzersiz(ham.iloc[konum].tolist())
            df = ham.iloc[konum + 1:].copy()
            df.columns = basliklar
            df = df.dropna(how="all")
            if df.empty:
                continue
            yerel_elle = {k.split("|", 2)[2]: v for k, v in elle.items() if k.startswith(anahtar + "|")}
            if elle_tur.get(anahtar) == esleme.YOK_SAY:
                o.sayfa_raporu.append({"anahtar": anahtar, "Dosya": ad, "Sayfa": sayfa_adi, "Tür": None, "Satır": len(df),
                                       "Başlık satırı": satir + 1, "Not": "Kullanıcı tarafından atlandı"})
                continue
            e = esleme.sayfa_turu_bul(str(sayfa_adi), basliklar, elle_tur.get(anahtar), yerel_elle)
            o.sayfa_raporu.append({"anahtar": anahtar, "Dosya": ad, "Sayfa": sayfa_adi, "Tür": e.tur, "Satır": len(df),
                                   "Başlık satırı": satir + 1,
                                   "Not": "" if e.tur else "Tanınan veri sütunu bulunamadı; sayfa atlanacak"})
            if not e.tur:
                continue
            ornek = {b: next((metin(v) for v in df[b].tolist() if not bos_mu(v)), "") for b in basliklar}
            for b in basliklar:
                if b in e.eslesme:
                    k, p, y = e.eslesme[b]
                    o.esleme_raporu.append({"anahtar": f"{anahtar}|{b}", "Dosya": ad, "Sayfa": sayfa_adi, "Tür": e.tur,
                                            "Excel sütunu": b, "Örnek değer": ornek[b][:40], "Alan": k,
                                            "Eşlenen alan": esleme.etiket(e.tur, k), "Güven": p, "Yöntem": y})
                else:
                    durum = "DPP dışı (maliyet, fiyat vb.)" if b in e.dpp_disi else "Tanınmadı"
                    if yerel_elle.get(b) == esleme.YOK_SAY:
                        durum = "Aktarılmayacak (kullanıcı)"
                    o.esleme_raporu.append({"anahtar": f"{anahtar}|{b}", "Dosya": ad, "Sayfa": sayfa_adi, "Tür": e.tur,
                                            "Excel sütunu": b, "Örnek değer": ornek[b][:40], "Alan": None,
                                            "Eşlenen alan": f"— {durum}", "Güven": 0, "Yöntem": ""})
            yeniden = {b: k for b, (k, _, _) in e.eslesme.items()}
            kalan = [b for b in basliklar if b not in yeniden and b not in e.dpp_disi and yerel_elle.get(b) != esleme.YOK_SAY]
            saklanan = kalan if e.tur in ("Urunler", "Tedarikciler") else []
            df = df[list(yeniden) + saklanan].rename(columns=yeniden)
            if e.tur == "Urunler":
                # Karbon bileşenleri (ör. 'Hammadde Emisyonu (kg CO2e)'): toplam karbon boşsa toplanır
                for b in list(saklanan):
                    if _karbon_bileseni_mi(b) and yerel_elle.get(b) is None:
                        df = df.rename(columns={b: f"_KB_{b}"})
                        saklanan.remove(b)
                        for r in o.esleme_raporu:
                            if r["anahtar"] == f"{anahtar}|{b}":
                                r["Eşlenen alan"] = "— Karbon bileşeni (toplam boşsa toplanır)"
            df = df.rename(columns={b: f"~{b}" for b in saklanan})
            df["_kaynak"] = f"{ad} / {sayfa_adi}"
            df["_satir"] = [int(i) + 1 for i in df.index]
            if e.tur == "Belgeler" and "Baglanti" not in df.columns:
                df["Baglanti"] = "*"
                o.varsayilanlar.append(f"{ad} / {sayfa_adi}: belgelerin bağlı olduğu ürün belirtilmemiş; belgeler tüm firmaya bağlanacak.")
            parcalar[e.tur].append(df.reset_index(drop=True))

    if parcalar["Testler"]:
        testler = _testleri_belgeye_cevir(pd.concat(parcalar.pop("Testler"), ignore_index=True))
        parcalar["Belgeler"].append(testler)
        olumsuz = [f"{r['Baglanti']} ({r['_Test_Ozet'] or r['_Test_Sonuc']})" for r in testler.to_dict("records")
                   if _test_sonucu(r["_Test_Sonuc"]) == "olumsuz"]
        o.varsayilanlar.append(f"{len(testler)} laboratuvar testi, test raporu belgesi olarak kaydedilecek. Olumlu sonuçlu raporlar "
                               "doğrulama bekleyecek; olumsuz sonuçlular kanıt sayılmaz.")
        if olumsuz:
            o.uyarilar.append(f"{len(olumsuz)} test sonucu UYUMSUZ: {'; '.join(olumsuz[:5])}. Bu raporlar 'Reddedildi' durumunda "
                              "kaydedilecek ve ilgili ürünlerde kimyasal uygunluk eksik görünecek.")
    else:
        parcalar.pop("Testler", None)
    for tur, liste in parcalar.items():
        o.sayfalar[tur] = pd.concat(liste, ignore_index=True) if liste else pd.DataFrame()

    if not any(not d.empty for d in o.sayfalar.values()) and not o.hatalar:
        o.hatalar.append("Dosyalarda tanınan bir veri sayfası bulunamadı. Ürün kodu / ürün adı gibi bir sütun başlığı olduğundan "
                         "emin olun veya aşağıdaki eşleme tablosundan sütunları elle eşleyin.")
        return o

    mevcut_kodlar = {r["urun_kodu"] for r in db.tumu("SELECT urun_kodu FROM urunler WHERE firma_id = ?", (firma_id,))}
    u = o.sayfalar["Urunler"]
    if not u.empty:
        for k in ("Urun_Kodu", "Urun_Adi", "GTIN"):
            if k not in u.columns:
                u[k] = None
        u["Urun_Kodu"] = u["Urun_Kodu"].map(metin)
        # Toplam / ortalama gibi özet satırlarını ayıkla
        ozet_mi = u.apply(lambda r: r["Urun_Kodu"] == "" and _ozet_satiri(r.get("Urun_Adi")), axis=1) | \
            u["Urun_Kodu"].map(_ozet_satiri)
        if ozet_mi.sum():
            o.varsayilanlar.append(f"{int(ozet_mi.sum())} özet satırı (toplam, ortalama vb.) ürün olarak alınmadı.")
            u = u[~ozet_mi].copy()
        # Ürün kodu yoksa: önce GTIN, sonra ürün adından türetilmiş kod
        kodsuz = u["Urun_Kodu"] == ""
        gtinli = kodsuz & u["GTIN"].map(lambda v: bool(gtin_temizle(v)))
        u.loc[gtinli, "Urun_Kodu"] = u.loc[gtinli, "GTIN"].map(gtin_temizle)
        adli = (u["Urun_Kodu"] == "") & ~u["Urun_Adi"].map(bos_mu)
        u.loc[adli, "Urun_Kodu"] = u.loc[adli, "Urun_Adi"].map(lambda a: "URN-" + _slug(a))
        if gtinli.sum():
            o.varsayilanlar.append(f"{int(gtinli.sum())} üründe ürün kodu yoktu; barkod (GTIN) ürün kodu olarak kullanıldı.")
        if adli.sum():
            o.varsayilanlar.append(f"{int(adli.sum())} üründe ürün kodu ve barkod yoktu; ürün adından kod üretildi (URN-...). "
                                   "Sonraki yüklemelerde aynı kod üretileceği için ürünler çoğalmaz.")
        kimliksiz = u[u["Urun_Kodu"] == ""]
        for r in kimliksiz.to_dict("records"):
            o.atlanacak.append({"Kaynak": r["_kaynak"], "Satır": r["_satir"], "Ürün": "—", "Neden": "Ürün kodu, adı veya barkodu yok"})
        u = u[u["Urun_Kodu"] != ""].copy()
        # Ürün ağacı (BOM) biçimi: her satır bir bileşen → bileşen satırları ayrı tutulur
        if "_Bilesen" in u.columns:
            bom = u[~u["_Bilesen"].map(bos_mu)].copy()
            if not bom.empty:
                o.sayfalar["_BOM"] = bom
                o.varsayilanlar.append(f"Ürün ağacı biçimi algılandı: {bom['Urun_Kodu'].nunique()} ürün için {len(bom)} bileşen satırı "
                                       "okundu. Her bileşen malzeme satırı olarak; bileşenin tedarikçisi, menşei ve sertifikası da "
                                       "ilgili kayıtlara aktarılacak. Bileşenlerin ağırlık oranları dosyada olmadığı için boş kalacak.")
                # Bileşen satırındaki menşe, bileşenin menşeidir; ürünün hammadde menşei olarak ülkeleri özetlenir
                if "Uretim_Ulkesi" in bom.columns and "Hammadde_Mensei" not in bom.columns:
                    ulkeler = bom.groupby("Urun_Kodu")["Uretim_Ulkesi"].agg(
                        lambda x: ", ".join(dict.fromkeys(re.sub(r"\s*\(.*?\)", "", metin(v)).strip() for v in x if not bos_mu(v))))
                    u["Hammadde_Mensei"] = u["Urun_Kodu"].map(ulkeler)
                    u["Uretim_Ulkesi"] = None
                    o.sayfalar["_BOM"] = bom
                    o.varsayilanlar.append("Ürün ağacındaki 'Menşei' sütunu bileşenlerin menşei olarak alındı; ürünün hammadde menşei "
                                           "bu ülkelerden oluşturuldu. Ürünün kendi üretim (menşe) ülkesi dosyada olmadığı için boş kalacak.")
                # bileşene ait sütunlar ürün düzeyine yalnızca tüm satırlarda aynıysa taşınır
                for k in [c for c in u.columns if (c in _BILESEN_SUTUNLARI and c != "Hammadde_Mensei") or str(c).startswith("~")]:
                    tekil = bom.groupby("Urun_Kodu")[k].agg(lambda x: x.dropna().astype(str).unique().tolist())
                    farkli = tekil[tekil.map(len) > 1].index
                    u.loc[u["Urun_Kodu"].isin(farkli), k] = None
                u = u.drop(columns=[c for c in ("_Malzeme_Bilesimi", "_Cevre_Sertifikasi", "_Sertifika_No", "_Sertifika_Bitis")
                                    if c in u.columns])
        # Aynı ürün birden fazla satırda / sayfada geçiyorsa bilgiler birleştirilir (boş olmayan son değer geçerli)
        tekrar = u[u["Urun_Kodu"].duplicated()]["Urun_Kodu"].unique().tolist()
        if tekrar:
            celiski = []
            for kolon in [c for c in u.columns if not str(c).startswith(("_", "~")) and c != "Urun_Kodu"]:
                farkli = u.dropna(subset=[kolon]).groupby("Urun_Kodu")[kolon].nunique()
                if (farkli > 1).any():
                    celiski.append(kolon)
            kaynaklar = u.groupby("Urun_Kodu")["_kaynak"].agg(lambda x: " + ".join(dict.fromkeys(x)))
            satirlar = u.groupby("Urun_Kodu")["_satir"].first()
            u = u.replace({"": None}).groupby("Urun_Kodu", sort=False).last().reset_index()
            u["_kaynak"] = u["Urun_Kodu"].map(kaynaklar)
            u["_satir"] = u["Urun_Kodu"].map(satirlar)
            if "_BOM" not in o.sayfalar:
                o.varsayilanlar.append(f"{len(tekrar)} ürün birden fazla satırda veya sayfada geçiyor (ör. {', '.join(tekrar[:5])}); "
                                       "bilgileri tek üründe birleştirildi.")
            if celiski:
                o.uyarilar.append(f"Aynı ürün için farklı sayfalarda farklı değer girilmiş sütunlar var ({', '.join(celiski[:5])}); "
                                  "dosyadaki en son değer kullanılacak.")
        kb = [c for c in u.columns if str(c).startswith("_KB_")]
        if kb:
            if "Karbon_Ayak_Izi_kgCO2e" not in u.columns:
                u["Karbon_Ayak_Izi_kgCO2e"] = None
            toplam = u[kb].apply(lambda r: sum(sayi(v) or 0 for v in r) if any(sayi(v) is not None for v in r) else None, axis=1)
            bos = u["Karbon_Ayak_Izi_kgCO2e"].map(lambda v: sayi(v) is None) & toplam.notna()
            if bos.sum():
                u.loc[bos, "Karbon_Ayak_Izi_kgCO2e"] = toplam[bos].round(4)
                o.varsayilanlar.append(f"{int(bos.sum())} üründe toplam karbon ayak izi boştu; "
                                       f"{', '.join(c[4:] for c in kb)} sütunları toplanarak hesaplandı. (Excel'deki formüllerin "
                                       "sonucu dosyaya kaydedilmemişse bu sütunlar boş görünür.)")
            u = u.drop(columns=kb)
        adsiz = u["Urun_Adi"].map(bos_mu) & ~u["Urun_Kodu"].isin(mevcut_kodlar)
        if adsiz.sum():
            u.loc[adsiz, "Urun_Adi"] = u.loc[adsiz, "Urun_Kodu"]
            o.varsayilanlar.append(f"{int(adsiz.sum())} yeni üründe ürün adı yoktu; ürün kodu ad olarak kullanıldı.")
        if "GTIN" in u.columns:
            hatali = [f"{r['Urun_Kodu']} ({gtin_dogrula(r['GTIN'])[1]})" for r in u.to_dict("records")
                      if not bos_mu(r["GTIN"]) and not gtin_dogrula(r["GTIN"])[0]]
            if hatali:
                o.uyarilar.append(f"{len(hatali)} üründe barkod hatalı; kaydedilecek, değerlendirmede eksik görünecek "
                                  f"(ör. {', '.join(hatali[:3])}).")
        sektor_yok = (~u["Urun_Kodu"].isin(mevcut_kodlar)) & (u["Sektor"].map(bos_mu) if "Sektor" in u.columns else True)
        if int(pd.Series(sektor_yok).sum()):
            o.varsayilanlar.append(f"{int(pd.Series(sektor_yok).sum())} yeni üründe sektör belirtilmemiş; GTİP kodundan veya ürün adından "
                                   "tahmin edilecek (bulunamazsa 'Diğer'). Ürün kartından düzeltebilirsiniz.")
        if "Tuketici_Urunu" not in u.columns:
            o.varsayilanlar.append("Tüketici ürünü bilgisi yok; sektöre göre varsayılacak (ör. tekstil: evet, demir-çelik: hayır).")
        if "_Geri_Donusturulebilirlik" in u.columns:
            o.uyarilar.append("'Geri dönüştürülebilirlik oranı' geri dönüştürülmüş İÇERİK oranı değildir; aktarılmayacak.")
        bilinmeyen = [c[1:] for c in u.columns if str(c).startswith("~")]
        if bilinmeyen:
            o.uyarilar.append(f"Tanınmayan {len(bilinmeyen)} sütun var ({', '.join(bilinmeyen[:6])}). Eşleme tablosundan bir alana "
                              "atayabilir veya 'tanınmayan sütunları ürün notlarına ekle' seçeneğiyle saklayabilirsiniz.")
        for kolon, ad_ in (("SVHC_Beyani", "SVHC beyanı"), ("Uretim_Ulkesi", "üretim ülkesi")):
            if kolon not in u.columns:
                o.varsayilanlar.append(f"Dosyada {ad_} yok. Bu bir yasal beyan olduğu için varsayılan değer ATANMAZ; "
                                       "ilgili ürünler değerlendirmede eksik görünecek.")
        o.yeni_urun = int((~u["Urun_Kodu"].isin(mevcut_kodlar)).sum())
        o.guncel_urun = int(u["Urun_Kodu"].isin(mevcut_kodlar).sum())
        o.sayfalar["Urunler"] = u

    tum_kodlar = set(o.sayfalar["Urunler"]["Urun_Kodu"]) if not o.sayfalar["Urunler"].empty else set()
    tum_kodlar |= mevcut_kodlar
    for tur in ("Malzemeler", "Partiler", "Tedarik_Zinciri"):
        df = o.sayfalar[tur]
        if df.empty:
            continue
        if "Urun_Kodu" not in df.columns:
            o.uyarilar.append(f"{tur.replace('_', ' ')} sayfasında ürün kodu sütunu bulunamadı; bu sayfa aktarılmayacak. "
                              "Eşleme tablosundan ürün kodu sütununu seçin.")
            o.sayfalar[tur] = pd.DataFrame()
            continue
        df["Urun_Kodu"] = df["Urun_Kodu"].map(metin)
        bilinmeyen = sorted(set(df["Urun_Kodu"]) - tum_kodlar - {""})
        if bilinmeyen:
            o.uyarilar.append(f"{tur.replace('_', ' ')}: {len(bilinmeyen)} ürün kodu sistemde ve dosyada yok; bu satırlar atlanacak "
                              f"(ör. {', '.join(bilinmeyen[:5])}).")
    m = o.sayfalar["Malzemeler"]
    if not m.empty and "Oran_Yuzde" in m.columns:
        toplam = m.assign(_o=m["Oran_Yuzde"].map(lambda v: sayi(v) or 0)).groupby("Urun_Kodu")["_o"].sum()
        # 0-1 arası oranlar (0,95 gibi) yüzdeye çevrilir
        kesirli = toplam[(toplam > 0.9) & (toplam <= 1.01)].index.tolist()
        if kesirli:
            o.varsayilanlar.append(f"{len(kesirli)} üründe oranlar 0-1 arasında girilmiş (ör. 0,95); yüzdeye çevrilecek.")
            o.sayfalar["Malzemeler"].attrs["kesirli"] = set(kesirli)
            toplam.loc[kesirli] = toplam.loc[kesirli] * 100
        yanlis = toplam[(toplam - 100).abs() > 1]
        if len(yanlis):
            o.uyarilar.append(f"{len(yanlis)} ürünün malzeme toplamı %100 değil (ör. "
                              f"{', '.join(f'{k}: %{v:g}' for k, v in yanlis.head(3).items())}); aktarılacak, değerlendirmede görünecek.")
    if not o.sayfalar["Urunler"].empty and "_Malzeme_Bilesimi" in o.sayfalar["Urunler"].columns:
        okunamayan = [r["Urun_Kodu"] for r in o.sayfalar["Urunler"].to_dict("records")
                      if not bos_mu(r["_Malzeme_Bilesimi"]) and not malzeme_ayristir(r["_Malzeme_Bilesimi"])]
        if okunamayan:
            o.uyarilar.append(f"{len(okunamayan)} üründe bileşim metni çözümlenemedi (ör. {', '.join(okunamayan[:3])}).")
    b = o.sayfalar["Belgeler"]
    if not b.empty and "Belge_Turu" in b.columns:
        diger = b[b["Belge_Turu"].map(belge_turu_tahmin) == "DIGER"]["Belge_Turu"].dropna().astype(str).unique().tolist()
        if diger:
            o.uyarilar.append(f"Türü tanınamayan belgeler 'Diğer belge' olarak kaydedilecek: {', '.join(diger[:5])}")
    return o


def _s(r: dict, k: str):
    v = r.get(k)
    return None if bos_mu(v) else v


@dataclass
class AktarimSonucu:
    sayac: dict
    atlanan: list[dict]
    notlar: list[str]

    def ozet(self) -> str:
        adlar = {"urun_yeni": "yeni ürün", "urun_guncel": "güncellenen ürün", "malzeme": "malzeme satırı", "parti": "parti",
                 "asama": "tedarik aşaması", "belge": "belge", "tedarikci": "tedarikçi", "tesis": "tesis"}
        return ", ".join(f"{v} {adlar.get(k, k)}" for k, v in self.sayac.items() if v) or "aktarılan kayıt yok"


_SAYI_ALANLARI = {"Geri_Donusturulmus_Icerik_Yuzde": "geri_donusturulmus_yuzde", "Karbon_Ayak_Izi_kgCO2e": "karbon_kg",
                  "Gomulu_Emisyon_tCO2e_t": "gomulu_emisyon", "Batarya_Kapasite_kWh": "batarya_kwh"}
_SVHC = {"yok": "Yok", "hayir": "Yok", "no": "Yok", "none": "Yok", "icermez": "Yok", "var": "Var", "evet": "Var", "yes": "Var",
         "icerir": "Var", "bilinmiyor": "Bilinmiyor", "belirsiz": "Bilinmiyor", "unknown": "Bilinmiyor"}


def _sertifikalari_bol(deger) -> list[str]:
    return [p.strip() for p in re.split(r"[;,/+\n]| ve | and ", metin(deger)) if p.strip()]


def uygula(db: Veritabani, firma_id: int, o: Onizleme, kullanici: str, bilinmeyenleri_nota: bool = False) -> AktarimSonucu:
    """
    Önizlenen veriyi yazar. Tek işlem içinde satır bazında kurtarma noktası kullanılır: hatalı bir satır
    yalnızca kendisini etkiler, diğer satırlar aktarılır ve hatalar özetlenir.
    """
    sayac = {"urun_yeni": 0, "urun_guncel": 0, "malzeme": 0, "parti": 0, "asama": 0, "belge": 0, "tedarikci": 0, "tesis": 0}
    atlanan = list(o.atlanacak)
    notlar: list[str] = []
    gecersiz_sayi = 0
    kesirli = o.sayfalar.get("Malzemeler", pd.DataFrame()).attrs.get("kesirli", set())

    from contextlib import nullcontext
    kurtarma = getattr(db, "kurtarma_noktasi", None) or nullcontext

    def dene(kaynak, satir, urun, is_):
        try:
            with kurtarma():
                is_()
            return True
        except Exception as hata:
            atlanan.append({"Kaynak": kaynak, "Satır": satir, "Ürün": urun, "Neden": str(hata)[:200]})
            return False

    with db.islem():
        for r in o.sayfalar.get("Tesisler", pd.DataFrame()).to_dict("records"):
            if _s(r, "Ad"):
                def is_(r=r):
                    tid = repo.tesis_bul_veya_ekle(db, firma_id, r["Ad"])
                    db.guncelle("tesisler", tid, {k2: metin(_s(r, k1)) for k1, k2 in (("Adres", "adres"), ("Ulke", "ulke"),
                                                                                       ("GLN", "gln"), ("Tur", "tur")) if _s(r, k1)}, firma_id)
                if dene(r.get("_kaynak"), r.get("_satir"), r["Ad"], is_):
                    sayac["tesis"] += 1
        for r in o.sayfalar.get("Tedarikciler", pd.DataFrame()).to_dict("records"):
            if _s(r, "Unvan"):
                def is_(r=r):
                    tid = repo.tedarikci_bul_veya_ekle(db, firma_id, r["Unvan"])
                    guncel = {k2: metin(_s(r, k1)) for k1, k2 in (("Ulke", "ulke"), ("Eposta", "eposta"), ("Yetkili", "yetkili"),
                                                                    ("Kimlik_No", "kimlik_no")) if _s(r, k1)}
                    ek = "; ".join(f"{k[1:]}: {metin(v)}" for k, v in r.items() if str(k).startswith("~") and not bos_mu(v))
                    if ek and bilinmeyenleri_nota:
                        guncel["notlar"] = f"[Excel ek bilgi: {ek}]"
                    db.guncelle("tedarikciler", tid, guncel, firma_id)
                if dene(r.get("_kaynak"), r.get("_satir"), r["Unvan"], is_):
                    sayac["tedarikci"] += 1

        urun_id: dict[str, int] = {r["urun_kodu"]: r["id"] for r in
                                   db.tumu("SELECT id, urun_kodu FROM urunler WHERE firma_id = ?", (firma_id,))}
        tek_hucre_malzeme: dict[str, list] = {}
        urun_belgeleri: list[dict] = []
        urun_tedarikci: dict[str, tuple] = {}
        ek_partiler: list[dict] = []

        for r in o.sayfalar.get("Urunler", pd.DataFrame()).to_dict("records"):
            kod = metin(r["Urun_Kodu"])

            def is_(r=r, kod=kod):
                nonlocal gecersiz_sayi
                sektor = _s(r, "Sektor")
                veri = {"urun_kodu": kod, "ad": metin(_s(r, "Urun_Adi")) or None, "gtip": metin(_s(r, "GTIP")) or None,
                        "gtin": gtin_temizle(_s(r, "GTIN")) or None, "marka": metin(_s(r, "Marka")) or None,
                        "ab_sorumlu_operator": _s(r, "AB_Sorumlu_Operator"), "uretim_ulkesi": _s(r, "Uretim_Ulkesi"),
                        "hammadde_mensei": _s(r, "Hammadde_Mensei"), "svhc_maddeler": _s(r, "SVHC_Maddeler"),
                        "cevresel_iddia": _s(r, "Cevresel_Iddia"), "karbon_yontemi": _s(r, "Karbon_Yontemi"),
                        "eprel_no": metin(_s(r, "EPREL_No")) or None, "imds_id": metin(_s(r, "IMDS_ID")) or None,
                        "batarya_kategori": _s(r, "Batarya_Kategorisi"), "batarya_kimya": _s(r, "Batarya_Kimyasi"),
                        "bakim_onarim": _s(r, "Bakim_Onarim_Bilgisi"), "omur_sonu": _s(r, "Omur_Sonu_Talimati")}
                for kaynak_k, hedef_k in _SAYI_ALANLARI.items():
                    ham = _s(r, kaynak_k)
                    veri[hedef_k] = sayi(ham)
                    if ham is not None and veri[hedef_k] is None:
                        gecersiz_sayi += 1
                if _s(r, "SVHC_Beyani"):
                    veri["svhc_beyani"] = _SVHC.get(tr_norm(r["SVHC_Beyani"]), metin(r["SVHC_Beyani"]))
                if "Tuketici_Urunu" in r:
                    e = evet_mi(r.get("Tuketici_Urunu"))
                    veri["tuketici_urunu"] = None if e is None else int(e)
                if _s(r, "Uretim_Tesisi"):
                    veri["tesis_id"] = repo.tesis_bul_veya_ekle(db, firma_id, r["Uretim_Tesisi"])
                if sektor or kod not in urun_id:
                    veri["sektor_kodu"] = sektor_oner(_s(r, "GTIP"), sektor) if sektor else sektor_oner(_s(r, "GTIP"), _s(r, "Urun_Adi"))
                if bilinmeyenleri_nota:
                    ek = "; ".join(f"{k[1:]}: {metin(v)}" for k, v in r.items() if str(k).startswith("~") and not bos_mu(v))
                    if ek:
                        eski_not = metin((repo.urun_kod_ile(db, firma_id, kod) or {}).get("notlar"))
                        eski_not = re.sub(r"\s*\[Excel ek bilgi:.*?\]", "", eski_not).strip()
                        veri["notlar"] = (eski_not + " " if eski_not else "") + f"[Excel ek bilgi: {ek}]"
                veri = {k: v for k, v in veri.items() if k in ("urun_kodu", "sektor_kodu") or v is not None}
                if kod in urun_id:
                    repo.urun_kaydet(db, firma_id, veri, kullanici, urun_id[kod])
                    sayac["urun_guncel"] += 1
                else:
                    urun_id[kod] = repo.urun_kaydet(db, firma_id, veri, kullanici)
                    sayac["urun_yeni"] += 1

            if not dene(r.get("_kaynak"), r.get("_satir"), kod, is_):
                continue
            if _s(r, "_Malzeme_Bilesimi"):
                tek_hucre_malzeme[kod] = [{"malzeme": a, "oran": o_} for a, o_ in malzeme_ayristir(r["_Malzeme_Bilesimi"])]
            if _s(r, "_Cevre_Sertifikasi"):
                turler = _sertifikalari_bol(r["_Cevre_Sertifikasi"])
                for t in turler:
                    urun_belgeleri.append({"Baglanti": kod, "Belge_Turu": t, "_kaynak": r.get("_kaynak"), "_satir": r.get("_satir"),
                                           "Belge_No": _sertifika_no(t, r.get("_Sertifika_No") if len(turler) == 1 else None),
                                           "Gecerlilik_Bitis": r.get("_Sertifika_Bitis")})
            if _s(r, "_Tedarikci"):
                urun_tedarikci[kod] = (r["_Tedarikci"], _s(r, "_Tedarikci_Ulke") or _s(r, "Hammadde_Mensei"))
            if _s(r, "Parti_No"):
                ek_partiler.append({"Urun_Kodu": kod, "Parti_No": r["Parti_No"], "Uretim_Tarihi": r.get("Uretim_Tarihi"),
                                    "_kaynak": r.get("_kaynak"), "_satir": r.get("_satir")})

        def grupla(tur, ek=()):
            df = o.sayfalar.get(tur, pd.DataFrame())
            satirlar = (df.to_dict("records") if not df.empty and "Urun_Kodu" in df.columns else []) + list(ek)
            gruplar: dict[str, list] = {}
            for s in satirlar:
                gruplar.setdefault(metin(s.get("Urun_Kodu")), []).append(s)
            return gruplar

        bom_asamalari: dict[str, list] = {}
        for r in o.sayfalar.get("_BOM", pd.DataFrame()).to_dict("records"):
            kod = metin(r["Urun_Kodu"])
            if kod not in urun_id:
                continue
            ad_ = metin(r["_Bilesen"])
            komp = metin(_s(r, "_Malzeme_Bilesimi"))
            mense = _s(r, "Uretim_Ulkesi") or _s(r, "Hammadde_Mensei")
            satir = {"malzeme": f"{ad_} ({komp})" if komp and tr_norm(komp) not in tr_norm(ad_) else ad_, "oran": None,
                     "mense": mense, "_tedarikci": _s(r, "_Tedarikci")}
            tek_hucre_malzeme.setdefault(kod, [])
            if tek_hucre_malzeme[kod] and "_bom" not in tek_hucre_malzeme[kod][0]:
                tek_hucre_malzeme[kod] = []
            satir["_bom"] = True
            tek_hucre_malzeme[kod].append(satir)
            if _s(r, "_Tedarikci"):
                bom_asamalari.setdefault(kod, []).append({"Urun_Kodu": kod, "Asama": ad_, "Tedarikci": r["_Tedarikci"],
                                                          "Ulke": _s(r, "_Tedarikci_Ulke") or mense})
            if _s(r, "_Cevre_Sertifikasi"):
                for t in _sertifikalari_bol(r["_Cevre_Sertifikasi"]):
                    baglar = kod + (f";TEDARIKCI:{r['_Tedarikci']}" if _s(r, "_Tedarikci") else "")
                    urun_belgeleri.append({"Baglanti": baglar, "Belge_Turu": t, "Belge_No": _sertifika_no(t, r.get("_Sertifika_No")),
                                           "Gecerlilik_Bitis": r.get("_Sertifika_Bitis"), "_kaynak": r.get("_kaynak"),
                                           "_satir": r.get("_satir")})

        malzeme_gruplari = grupla("Malzemeler")
        for kod, liste in tek_hucre_malzeme.items():
            malzeme_gruplari.setdefault(kod, liste)
        for kod, satirlar in malzeme_gruplari.items():
            if kod not in urun_id:
                continue

            def is_(kod=kod, satirlar=satirlar):
                temiz = []
                for s in satirlar:
                    if "malzeme" in s:
                        satir = {k: v for k, v in s.items() if not k.startswith("_")}
                        if s.get("_tedarikci"):
                            satir["tedarikci_id"] = repo.tedarikci_bul_veya_ekle(db, firma_id, s["_tedarikci"])
                        temiz.append(satir)
                        continue
                    oran = sayi(_s(s, "Oran_Yuzde"))
                    if oran is not None and kod in kesirli:
                        oran = round(oran * 100, 4)
                    temiz.append({"malzeme": _s(s, "Malzeme"), "oran": oran, "mense": _s(s, "Mense"),
                                  "geri_donusturulmus": 1 if evet_mi(s.get("Geri_Donusturulmus")) else 0,
                                  "tedarikci_id": repo.tedarikci_bul_veya_ekle(db, firma_id, _s(s, "Tedarikci")) if _s(s, "Tedarikci") else None})
                sayac["malzeme"] += repo.alt_degistir(db, "malzemeler", firma_id, urun_id[kod], temiz, kullanici, denetle=False)
            dene("Malzemeler", "—", kod, is_)

        for kod, satirlar in grupla("Partiler", ek_partiler).items():
            if kod not in urun_id:
                continue

            def is_(kod=kod, satirlar=satirlar):
                mevcut = {p["parti_no"]: p for p in repo.alt_liste(db, "partiler", firma_id, urun_id[kod])}
                for s in satirlar:
                    no = metin(_s(s, "Parti_No"))
                    if not no:
                        continue
                    onceki = mevcut.get(no, {})
                    mevcut[no] = {"parti_no": no, "uretim_tarihi": tarih_metni(_s(s, "Uretim_Tarihi")) or onceki.get("uretim_tarihi"),
                                  "miktar": sayi(_s(s, "Miktar")) if _s(s, "Miktar") is not None else onceki.get("miktar"),
                                  "tesis_id": repo.tesis_bul_veya_ekle(db, firma_id, _s(s, "Tesis")) if _s(s, "Tesis") else onceki.get("tesis_id")}
                sayac["parti"] += repo.alt_degistir(db, "partiler", firma_id, urun_id[kod], list(mevcut.values()), kullanici, denetle=False)
            dene("Partiler", "—", kod, is_)

        asama_gruplari = grupla("Tedarik_Zinciri")
        for kod, liste in bom_asamalari.items():
            if kod not in asama_gruplari:
                gorulen, tekil = set(), []
                for a in liste:
                    if (a["Asama"], a["Tedarikci"]) not in gorulen:
                        gorulen.add((a["Asama"], a["Tedarikci"]))
                        tekil.append(a)
                asama_gruplari[kod] = tekil
        for kod, satirlar in asama_gruplari.items():
            if kod not in urun_id:
                continue

            def is_(kod=kod, satirlar=satirlar):
                temiz = [{"sira": int(sayi(_s(s, "Sira")) or i + 1), "asama": _s(s, "Asama"), "ulke": _s(s, "Ulke"),
                          "belge_no": metin(_s(s, "Belge_No")) or None,
                          "tedarikci_id": repo.tedarikci_bul_veya_ekle(db, firma_id, _s(s, "Tedarikci")) if _s(s, "Tedarikci") else None}
                         for i, s in enumerate(satirlar)]
                sayac["asama"] += repo.alt_degistir(db, "tedarik_asamalari", firma_id, urun_id[kod], temiz, kullanici, denetle=False)
            dene("Tedarik zinciri", "—", kod, is_)

        eklenen_ana = 0
        for kod, (unvan, ulke) in urun_tedarikci.items():
            if kod not in urun_id or kod in asama_gruplari or repo.alt_liste(db, "tedarik_asamalari", firma_id, urun_id[kod]):
                continue
            eklenen_ana += 1

            def is_(kod=kod, unvan=unvan, ulke=ulke):
                tid = repo.tedarikci_bul_veya_ekle(db, firma_id, unvan, {"ulke": ulke})
                repo.alt_degistir(db, "tedarik_asamalari", firma_id, urun_id[kod],
                                  [{"sira": 1, "asama": "Ana tedarikçi", "tedarikci_id": tid, "ulke": ulke}], kullanici, denetle=False)
                sayac["asama"] += 1
            dene("Ürünler", "—", kod, is_)
        if eklenen_ana:
            notlar.append("Ürün satırındaki tedarikçi bilgisi, tedarik zinciri girilmemiş ürünlerde 'Ana tedarikçi' aşaması olarak eklendi.")

        belgeler = o.sayfalar.get("Belgeler", pd.DataFrame()).to_dict("records") + urun_belgeleri
        for r in belgeler:
            tur_ham = _s(r, "Belge_Turu")
            if not tur_ham:
                continue

            def is_(r=r, tur_ham=tur_ham):
                baglanti_metni = metin(_s(r, "Baglanti") or _s(r, "Urun_Kodu")) or "*"
                baglar = []
                for parca in [p.strip() for p in re.split(r"[;\n]", baglanti_metni) if p.strip()]:
                    n = tr_norm(parca)
                    if parca == "*" or n in ("tumu", "hepsi", "firma", "tum urunler"):
                        baglar.append(("firma", None))
                    elif n.startswith("tesis:"):
                        baglar.append(("tesis", repo.tesis_bul_veya_ekle(db, firma_id, parca.split(":", 1)[1])))
                    elif n.startswith("tedarikci:"):
                        baglar.append(("tedarikci", repo.tedarikci_bul_veya_ekle(db, firma_id, parca.split(":", 1)[1])))
                    elif parca in urun_id:
                        baglar.append(("urun", urun_id[parca]))
                if not baglar:
                    raise ValueError(f"Belgenin bağlanacağı ürün bulunamadı: '{baglanti_metni}'")
                kod_ = belge_turu_tahmin(tur_ham)
                veri = {"tur_kodu": kod_, "tur_serbest": metin(tur_ham), "belge_no": metin(_s(r, "Belge_No")) or None,
                        "duzenleyen": _s(r, "Duzenleyen"), "baslangic": tarih_metni(_s(r, "Gecerlilik_Baslangic")),
                        "bitis": tarih_metni(_s(r, "Gecerlilik_Bitis")), "kapsam": _s(r, "Kapsam")}
                if _s(r, "Gecerlilik_Bitis") and not veri["bitis"]:
                    notlar.append(f"'{tur_ham}' belgesinin bitiş tarihi okunamadı ('{metin(r.get('Gecerlilik_Bitis'))}'); boş bırakıldı.")
                ayni = None
                if veri["belge_no"]:
                    ayni = db.bir("SELECT id FROM belgeler WHERE firma_id = ? AND tur_kodu = ? AND belge_no = ?", (firma_id, kod_, veri["belge_no"]))
                else:
                    # numarasız belgede aynı tür + aynı bağlantı tekrar yüklenirse çoğaltma
                    for bag_tur, bag_id in baglar:
                        ayni = db.bir("SELECT b.id FROM belgeler b JOIN belge_baglantilari bb ON bb.belge_id = b.id "
                                      "WHERE b.firma_id = ? AND b.tur_kodu = ? AND b.belge_no IS NULL AND bb.hedef_tur = ? AND "
                                      + ("bb.hedef_id IS NULL" if bag_id is None else "bb.hedef_id = ?"),
                                      (firma_id, kod_, bag_tur) + (() if bag_id is None else (bag_id,)))
                        if ayni:
                            break
                if ayni:
                    db.guncelle("belgeler", ayni["id"], {k: v for k, v in veri.items() if v is not None}, firma_id)
                    mevcut_bag = [(x["hedef_tur"], x["hedef_id"]) for x in
                                  db.tumu("SELECT hedef_tur, hedef_id FROM belge_baglantilari WHERE belge_id = ?", (ayni["id"],))]
                    repo.belge_baglantilari_ayarla(db, firma_id, ayni["id"], mevcut_bag + baglar)
                    belge_id = ayni["id"]
                else:
                    belge_id = repo.belge_ekle(db, firma_id, veri, baglar, kullanici, kaynak="Excel içe aktarım")
                sonuc_ = _test_sonucu(r.get("_Test_Sonuc"))
                if sonuc_ == "olumsuz":
                    db.guncelle("belgeler", belge_id, {"dogrulama_durumu": "Reddedildi", "dogrulayan": "Sistem (test sonucu)",
                                                       "dogrulama_notu": f"Test sonucu uyumsuz: {metin(r.get('_Test_Ozet'))}"}, firma_id)
                elif sonuc_ == "sartli":
                    db.guncelle("belgeler", belge_id, {"dogrulama_notu": f"Şartlı kabul: {metin(r.get('_Test_Ozet'))}"}, firma_id)
                sayac["belge"] += 1
            dene(r.get("_kaynak", "Belgeler"), r.get("_satir", "—"), metin(_s(r, "Baglanti")) or "—", is_)

        if gecersiz_sayi:
            notlar.append(f"{gecersiz_sayi} hücrede sayı beklenirken metin vardı (ör. 'yaklaşık 4'); bu hücreler boş bırakıldı.")
        audit.kaydet(db, firma_id, kullanici, "Excel içe aktarım", "firma", firma_id,
                     ", ".join(f"{k}: {v}" for k, v in sayac.items() if v) + (f"; atlanan {len(atlanan)}" if atlanan else ""))
    return AktarimSonucu(sayac, atlanan, list(dict.fromkeys(notlar)))



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
