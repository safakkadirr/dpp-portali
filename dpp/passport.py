"""
Dijital ürün pasaportu: içerik üretimi (JSON-LD), sürümlü yayım, geri çekme,
GS1 Digital Link / uygulama bağlantısı ve erişim seviyesine göre görünüm.

Not: JSON-LD yapısı EN 18216/18223 yaklaşımına göre düzenlenmiş bir TASLAKTIR;
resmi veri şeması her ürün grubu için yetki tüzüğüyle belirlenecektir.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Optional
from urllib.parse import quote

from . import SURUM, audit, evaluation, repo
from .catalog import BELGE, SEKTOR
from .db import Veritabani, simdi
from .rules import DURUM_KRITIK
from .security import token_uret
from .util import bos_mu, gtin14, gtin_dogrula, metin, sayi

ERISIM_SEVIYELERI = ["Kamu", "Alıcı (B2B)", "Otorite"]
_SIRA = {s: i for i, s in enumerate(ERISIM_SEVIYELERI)}

# JSON anahtarı -> en düşük erişim seviyesi (listede olmayanlar Kamu)
ANAHTAR_ERISIM = {
    "dpp:partiNo": "Alıcı (B2B)", "dpp:uretimTarihi": "Alıcı (B2B)", "dpp:gtip": "Alıcı (B2B)",
    "dpp:uretimTesisi": "Alıcı (B2B)", "dpp:tedarikZinciri": "Alıcı (B2B)", "dpp:gomuluEmisyon": "Alıcı (B2B)",
    "dpp:imds": "Alıcı (B2B)", "dpp:tesisKimligi": "Otorite", "dpp:degerlendirmeAyrinti": "Otorite",
}
BELGE_B2B_ANAHTARLARI = {"no", "duzenleyen", "dosyaOzeti"}


def gorunur(seviye: str, istenen: str) -> bool:
    return _SIRA[seviye] <= _SIRA[istenen]


def baglanti_adresi(firma: dict, urun: dict, parti: Optional[dict], genel_kimlik: str, uygulama_adresi: str) -> str:
    """Firmanın kendi çözümleyici alanı ve geçerli GTIN varsa GS1 Digital Link, yoksa uygulama bağlantısı."""
    alan = metin(firma.get("cozumleyici_alan")).rstrip("/")
    if alan and gtin_dogrula(urun.get("gtin"))[0]:
        if not alan.startswith("http"):
            alan = "https://" + alan
        adres = f"{alan}/01/{gtin14(urun.get('gtin'))}"
        if parti:
            adres += f"/10/{quote(metin(parti.get('parti_no')), safe='')}"
        return adres
    return f"{uygulama_adresi.rstrip('/')}/?p={genel_kimlik}"


def icerik_ozeti(icerik: dict) -> str:
    kopya = {k: v for k, v in icerik.items() if k != "dpp:icerikOzeti"}
    return hashlib.sha256(json.dumps(kopya, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _temizle(o):
    if isinstance(o, dict):
        return {k: _temizle(v) for k, v in o.items() if v not in (None, "", [], {})}
    if isinstance(o, list):
        return [_temizle(v) for v in o]
    return o


def icerik_olustur(db: Veritabani, firma_id: int, urun_id: int, parti_id: Optional[int], adres: str,
                   pasaport_kimligi: str, surum: int) -> dict:
    """Pasaportun tam (Otorite düzeyi) içeriğini üretir."""
    f = repo.firma(db, firma_id)
    u = repo.urun(db, firma_id, urun_id)
    b = evaluation.baglam(db, firma_id, u)
    parti = next((p for p in b.partiler if p["id"] == parti_id), None) if parti_id else None
    tesis = db.bir("SELECT * FROM tesisler WHERE id = ? AND firma_id = ?", (u.get("tesis_id"), firma_id)) if u.get("tesis_id") else None
    tedarikci = {t["id"]: t for t in repo.tedarikciler(db, firma_id)}
    deg = db.bir("SELECT * FROM degerlendirmeler WHERE urun_id = ? AND son = 1", (urun_id,))
    dog, dog_gecerli = evaluation.dogrulama_gecerli_mi(db, firma_id, urun_id)

    icerik = {
        "@context": {"@vocab": "https://schema.org/", "dpp": "https://dpp-hazirlik.org/vocab#"},
        "@type": "Product",
        "@id": adres,
        "dpp:pasaportKimligi": pasaport_kimligi,
        "dpp:surum": surum,
        "dpp:semaSurumu": f"taslak-{SURUM}",
        "name": metin(u.get("ad")),
        "sku": metin(u.get("urun_kodu")),
        "gtin": metin(u.get("gtin")) or None,
        "brand": metin(u.get("marka")) or None,
        "category": SEKTOR.get(u.get("sektor_kodu"), SEKTOR["diger"]).ad,
        "manufacturer": {"@type": "Organization", "name": metin(f.get("unvan")), "address": metin(f.get("adres")) or None,
                         "email": metin(f.get("eposta")) or None, "url": metin(f.get("web")) or None},
        "dpp:abSorumluOperator": metin(u.get("ab_sorumlu_operator")) or None,
        "countryOfOrigin": metin(u.get("uretim_ulkesi")) or None,
        "dpp:hammaddeMensei": metin(u.get("hammadde_mensei")) or None,
        "material": [{"name": metin(m.get("malzeme")), "dpp:oranYuzde": sayi(m.get("oran")),
                      "dpp:mense": metin(m.get("mense")) or None,
                      "dpp:geriDonusturulmus": bool(m.get("geri_donusturulmus"))} for m in b.malzemeler],
        "dpp:geriDonusturulmusIcerikYuzde": sayi(u.get("geri_donusturulmus_yuzde")),
        "dpp:svhc": {"beyan": metin(u.get("svhc_beyani")) or None, "maddeler": metin(u.get("svhc_maddeler")) or None},
        "dpp:cevre": {"iddia": metin(u.get("cevresel_iddia")) or None, "karbonAyakIziKgCO2e": sayi(u.get("karbon_kg")),
                      "yontem": metin(u.get("karbon_yontemi")) or None},
        "dpp:kayitlar": {"eprel": metin(u.get("eprel_no")) or None},
        "dpp:batarya": {"kategori": metin(u.get("batarya_kategori")) or None, "kimya": metin(u.get("batarya_kimya")) or None,
                        "kapasiteKWh": sayi(u.get("batarya_kwh"))},
        "dpp:kullanim": {"bakimOnarim": metin(u.get("bakim_onarim")) or None, "omurSonu": metin(u.get("omur_sonu")) or None},
        "dpp:belgeler": [{
            "tur": BELGE.get(x["tur_kodu"], BELGE["DIGER"]).ad if x["tur_kodu"] != "DIGER" else (x.get("tur_serbest") or "Diğer"),
            "kategori": BELGE.get(x["tur_kodu"], BELGE["DIGER"]).kategori,
            "no": metin(x.get("belge_no")) or None, "duzenleyen": metin(x.get("duzenleyen")) or None,
            "gecerlilikBitis": metin(x.get("bitis")) or None, "durum": x["durum"],
            "dogrulama": x.get("dogrulama_durumu"), "dosyaOzeti": x.get("dosya_ozet"),
        } for x in b.belgeler if x["durum"] != "Süresi dolmuş" and x.get("dogrulama_durumu") != "Reddedildi"],
        # Alıcı (B2B)
        "dpp:partiNo": metin(parti.get("parti_no")) if parti else None,
        "dpp:uretimTarihi": metin(parti.get("uretim_tarihi")) if parti else None,
        "dpp:gtip": metin(u.get("gtip")) or None,
        "dpp:uretimTesisi": ({"ad": metin(tesis.get("ad")), "ulke": metin(tesis.get("ulke")) or None,
                              "adres": metin(tesis.get("adres")) or None} if tesis else None),
        "dpp:tedarikZinciri": [{"sira": a.get("sira"), "asama": metin(a.get("asama")), "ulke": metin(a.get("ulke")) or None,
                                "tedarikci": metin(tedarikci.get(a.get("tedarikci_id"), {}).get("unvan")) or None}
                               for a in b.asamalar],
        "dpp:gomuluEmisyon": sayi(u.get("gomulu_emisyon")),
        "dpp:imds": metin(u.get("imds_id")) or None,
        # Otorite
        "dpp:tesisKimligi": metin(tesis.get("gln")) if tesis else None,
        "dpp:degerlendirmeAyrinti": {"kuralSeti": deg.get("kural_seti"), "yasalUyum": deg.get("yasal_durum"),
                                     "hazirlikSkoru": deg.get("hazirlik_skoru"), "tarih": deg.get("tarih")} if deg else None,
        # Herkese açık özet
        "dpp:hazirlik": {"yasalUyum": deg.get("yasal_durum"), "hazirlikSkoru": deg.get("hazirlik_skoru"),
                         "not": "Ön kontrol göstergesidir; resmi uygunluk kararı değildir."} if deg else None,
        "dpp:bagimsizDogrulama": ({"sonuc": dog["sonuc"], "dogrulayan": dog["dogrulayan"], "unvan": dog.get("unvan"),
                                   "tarih": dog["tarih"][:10], "kapsam": dog.get("kapsam"), "guncel": dog_gecerli}
                                  if dog else None),
        "dpp:yayimTarihi": simdi(),
    }
    icerik = _temizle(icerik)
    icerik["dpp:icerikOzeti"] = icerik_ozeti(icerik)
    return icerik


def gorunum(icerik: dict, seviye: str) -> dict:
    """Tam içerikten erişim seviyesine göre görünüm üretir."""
    sonuc = {}
    for k, v in icerik.items():
        if not gorunur(ANAHTAR_ERISIM.get(k, "Kamu"), seviye):
            continue
        if k == "dpp:belgeler" and not gorunur("Alıcı (B2B)", seviye):
            v = [{a: b for a, b in x.items() if a not in BELGE_B2B_ANAHTARLARI} for x in v]
        sonuc[k] = v
    sonuc["dpp:erisimSeviyesi"] = seviye
    return sonuc


# ---------------------------------------------------------------------------
# Yayım
# ---------------------------------------------------------------------------

def pasaportlar(db: Veritabani, firma_id: int, urun_id: Optional[int] = None) -> list[dict]:
    sql = ("SELECT p.id, p.urun_id, u.urun_kodu, u.ad AS urun_adi, p.parti_id, pa.parti_no, p.surum, p.durum, "
           "p.genel_kimlik, p.alici_kodu, p.icerik_ozeti, p.kural_seti, p.hazirlik_skoru, p.yasal_durum, p.yayimlayan, "
           "p.yayim_tarihi, p.geri_cekme_tarihi, p.geri_cekme_nedeni "
           "FROM pasaportlar p JOIN urunler u ON u.id = p.urun_id LEFT JOIN partiler pa ON pa.id = p.parti_id "
           "WHERE p.firma_id = ?")
    prm = [firma_id]
    if urun_id:
        sql += " AND p.urun_id = ?"
        prm.append(urun_id)
    return db.tumu(sql + " ORDER BY u.urun_kodu, p.surum DESC", prm)


def yayimla(db: Veritabani, firma_id: int, urun_id: int, parti_id: Optional[int], kullanici: str,
            uygulama_adresi: str) -> dict:
    _, sonuc = evaluation.urun_degerlendir(db, firma_id, urun_id, kullanici)
    if sonuc.genel_durum == DURUM_KRITIK:
        raise ValueError(f"Üründe {sonuc.kritik_eksik} kritik yasal eksik var; pasaport yayımlanamaz. "
                         "Önce 'Eksikler ve Çözüm' ekranındaki kritik maddeleri giderin.")
    f = repo.firma(db, firma_id)
    u = repo.urun(db, firma_id, urun_id)
    parti = db.bir("SELECT * FROM partiler WHERE id = ? AND urun_id = ?", (parti_id, urun_id)) if parti_id else None
    with db.islem():
        onceki = db.bir("SELECT genel_kimlik, alici_kodu, surum FROM pasaportlar WHERE urun_id = ? AND "
                        + ("parti_id = ?" if parti_id else "parti_id IS NULL") + " ORDER BY surum DESC LIMIT 1",
                        (urun_id, parti_id) if parti_id else (urun_id,))
        genel = onceki["genel_kimlik"] if onceki else token_uret(9)
        alici = onceki["alici_kodu"] if onceki else token_uret(6)
        surum = (onceki["surum"] + 1) if onceki else 1
        adres = baglanti_adresi(f, u, parti, genel, uygulama_adresi)
        kimlik = f"DPP-{gtin14(u.get('gtin')) if gtin_dogrula(u.get('gtin'))[0] else metin(u.get('urun_kodu'))}" \
                 f"-{metin(parti.get('parti_no')) if parti else 'MODEL'}"
        icerik = icerik_olustur(db, firma_id, urun_id, parti_id, adres, kimlik, surum)
        db.yaz("UPDATE pasaportlar SET durum = 'Arşiv' WHERE genel_kimlik = ? AND durum = 'Yayında'", (genel,))
        pid = db.ekle("pasaportlar", {
            "firma_id": firma_id, "urun_id": urun_id, "parti_id": parti_id, "surum": surum, "durum": "Yayında",
            "genel_kimlik": genel, "alici_kodu": alici, "icerik_json": json.dumps(icerik, ensure_ascii=False),
            "icerik_ozeti": icerik["dpp:icerikOzeti"], "kural_seti": icerik.get("dpp:degerlendirmeAyrinti", {}).get("kuralSeti"),
            "hazirlik_skoru": sonuc.hazirlik_skoru, "yasal_durum": sonuc.yasal_durum, "yayimlayan": kullanici,
            "yayim_tarihi": simdi(),
        })
        audit.kaydet(db, firma_id, kullanici, "Pasaport yayımlandı", "pasaport", pid,
                     f"{u['urun_kodu']} sürüm {surum}, özet {icerik['dpp:icerikOzeti'][:16]}")
    return {"id": pid, "genel_kimlik": genel, "alici_kodu": alici, "surum": surum, "adres": adres,
            "uyari": None if sonuc.yasal_durum == "Uygun" else f"Üründe {sonuc.yasal_eksik} yasal eksik var (kritik değil)."}


def geri_cek(db: Veritabani, firma_id: int, pasaport_id: int, neden: str, kullanici: str):
    if not metin(neden):
        raise ValueError("Geri çekme nedeni yazılmalıdır")
    db.yaz("UPDATE pasaportlar SET durum = 'Geri çekildi', geri_cekme_tarihi = ?, geri_cekme_nedeni = ? "
           "WHERE id = ? AND firma_id = ? AND durum = 'Yayında'", (simdi(), neden, pasaport_id, firma_id))
    audit.kaydet(db, firma_id, kullanici, "Pasaport geri çekildi", "pasaport", pasaport_id, neden)


def kamu_kaydi(db: Veritabani, genel_kimlik: str) -> Optional[dict]:
    """Herkese açık sayfa için en güncel yayım (geri çekilmişse o bilgiyle)."""
    if not genel_kimlik or len(genel_kimlik) > 64:
        return None
    r = db.bir("SELECT p.*, f.unvan AS firma_unvan FROM pasaportlar p JOIN firmalar f ON f.id = p.firma_id "
               "WHERE p.genel_kimlik = ? AND p.durum IN ('Yayında', 'Geri çekildi') ORDER BY p.surum DESC LIMIT 1",
               (genel_kimlik,))
    if r:
        r["icerik"] = json.loads(r["icerik_json"])
        r["ozet_dogru"] = icerik_ozeti(r["icerik"]) == r["icerik_ozeti"] == r["icerik"].get("dpp:icerikOzeti")
    return r


def erisim_seviyesi(kayit: dict, kod: Optional[str]) -> str:
    if kod and kayit.get("alici_kodu") and hmac.compare_digest(str(kod), kayit["alici_kodu"]):
        return "Alıcı (B2B)"
    return "Kamu"
