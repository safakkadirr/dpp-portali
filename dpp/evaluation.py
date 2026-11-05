"""Değerlendirmelerin çalıştırılması, kaydedilmesi ve bağımsız doğrulama beyanları."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Optional

from . import audit, repo
from .catalog import SEKTOR
from .db import Veritabani, simdi
from .rules import Baglam, KURAL, Sonuc, degerlendir, kural_seti_surumu
from .util import metin


def baglam(db: Veritabani, firma_id: int, urun: dict, gtin_tekrar: Optional[set] = None,
           bugun: Optional[date] = None) -> Baglam:
    bugun = bugun or date.today()
    sektor = SEKTOR.get(urun.get("sektor_kodu") or "diger", SEKTOR["diger"])
    tuketici = urun.get("tuketici_urunu")
    tuketici = sektor.tuketici_varsayilan if tuketici is None else bool(tuketici)
    return Baglam(
        urun=urun, sektor=sektor, tuketici=tuketici,
        malzemeler=repo.alt_liste(db, "malzemeler", firma_id, urun["id"]),
        asamalar=repo.alt_liste(db, "tedarik_asamalari", firma_id, urun["id"]),
        partiler=repo.alt_liste(db, "partiler", firma_id, urun["id"]),
        belgeler=repo.urun_belgeleri(db, firma_id, urun["id"], bugun),
        gtin_tekrarlari=gtin_tekrar if gtin_tekrar is not None else repo.gtin_tekrarlari(db, firma_id),
        bugun=bugun,
    )


def veri_ozeti(b: Baglam) -> str:
    """Ürünün değerlendirmeye giren verisinin parmak izi (doğrulama sonrası değişikliği tespit için)."""
    govde = {
        "urun": {k: metin(b.urun.get(k)) for k in repo.URUN_ALANLARI},
        "malzeme": [[metin(m.get(k)) for k in repo.ALT_TABLOLAR["malzemeler"]] for m in b.malzemeler],
        "asama": [[metin(a.get(k)) for k in repo.ALT_TABLOLAR["tedarik_asamalari"]] for a in b.asamalar],
        "parti": [[metin(p.get(k)) for k in repo.ALT_TABLOLAR["partiler"]] for p in b.partiler],
        "belge": sorted([[x["id"], x["tur_kodu"], metin(x.get("bitis")), metin(x.get("dosya_ozet")), x.get("dogrulama_durumu")]
                         for x in b.belgeler]),
    }
    return hashlib.sha256(json.dumps(govde, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def urun_degerlendir(db: Veritabani, firma_id: int, urun_id: int, kullanici: str = "sistem",
                     gtin_tekrar: Optional[set] = None, ayarlar: Optional[dict] = None,
                     bugun: Optional[date] = None) -> tuple[int, Sonuc]:
    u = repo.urun(db, firma_id, urun_id)
    if not u:
        raise ValueError("Ürün bulunamadı")
    ayarlar = repo.kural_ayarlari(db) if ayarlar is None else ayarlar
    b = baglam(db, firma_id, u, gtin_tekrar, bugun)
    s = degerlendir(b, ayarlar)
    with db.islem():
        db.yaz("UPDATE degerlendirmeler SET son = 0 WHERE urun_id = ? AND firma_id = ? AND son = 1", (urun_id, firma_id))
        did = db.ekle("degerlendirmeler", {
            "firma_id": firma_id, "urun_id": urun_id, "kural_seti": kural_seti_surumu(ayarlar), "tarih": simdi(),
            "yasal_durum": s.yasal_durum, "yasal_eksik": s.yasal_eksik, "kritik_eksik": s.kritik_eksik,
            "hazirlik_skoru": s.hazirlik_skoru, "genel_durum": s.genel_durum, "uygulanan": s.uygulanan,
            "calistiran": kullanici, "son": 1,
        })
        for r in s.bulgular:
            db.ekle("bulgular", {"degerlendirme_id": did, **r})
    return did, s


def firma_degerlendir(db: Veritabani, firma_id: int, kullanici: str = "sistem", bugun: Optional[date] = None) -> int:
    ayarlar = repo.kural_ayarlari(db)
    tekrar = repo.gtin_tekrarlari(db, firma_id)
    sayi = 0
    for u in db.tumu("SELECT id FROM urunler WHERE firma_id = ? AND aktif = 1", (firma_id,)):
        urun_degerlendir(db, firma_id, u["id"], kullanici, tekrar, ayarlar, bugun)
        sayi += 1
    audit.kaydet(db, firma_id, kullanici, "Toplu değerlendirme", "firma", firma_id, f"{sayi} ürün değerlendirildi")
    return sayi


def guncel_degil_mi(db: Veritabani, firma_id: int) -> bool:
    """Bugün veya güncel kural setiyle değerlendirilmemiş ürün varsa True."""
    bugun = date.today().isoformat()
    surum = kural_seti_surumu(repo.kural_ayarlari(db))
    eski = db.deger("""SELECT COUNT(*) FROM urunler u LEFT JOIN degerlendirmeler d ON d.urun_id = u.id AND d.son = 1
                        WHERE u.firma_id = ? AND u.aktif = 1
                          AND (d.id IS NULL OR substr(d.tarih, 1, 10) < ? OR d.kural_seti <> ?)""",
                    (firma_id, bugun, surum))
    return bool(eski)


def bulgular(db: Veritabani, degerlendirme_id: int) -> list[dict]:
    satirlar = db.tumu("SELECT * FROM bulgular WHERE degerlendirme_id = ? ORDER BY id", (degerlendirme_id,))
    for r in satirlar:
        k = KURAL.get(r["kural_kodu"])
        if k:
            r.update({"kural": k.ad, "dayanak": k.dayanak, "kaynak": k.kaynak, "recete": k.recete, "kapsam": k.kapsam,
                      "zorunlu_tarih": k.zorunlu_tarih.isoformat() if k.zorunlu_tarih else None})
    return satirlar


def firma_bulgulari(db: Veritabani, firma_id: int) -> list[dict]:
    satirlar = db.tumu("""
        SELECT u.id AS urun_id, u.urun_kodu, u.ad AS urun_adi, u.sektor_kodu, b.*
        FROM bulgular b JOIN degerlendirmeler d ON d.id = b.degerlendirme_id AND d.son = 1
        JOIN urunler u ON u.id = d.urun_id AND u.aktif = 1
        WHERE d.firma_id = ?""", (firma_id,))
    for r in satirlar:
        k = KURAL.get(r["kural_kodu"])
        r["kural"] = k.ad if k else r["kural_kodu"]
        r["recete"] = k.recete if k else []
        r["dayanak"] = k.dayanak if k else ""
    return satirlar


# ---------------------------------------------------------------------------
# Bağımsız doğrulama beyanı
# ---------------------------------------------------------------------------

DOGRULAMA_SONUCLARI = ["Doğrulandı", "Şartlı doğrulandı", "Doğrulanmadı"]


def urun_dogrula(db: Veritabani, firma_id: int, urun_id: int, dogrulayan: str, unvan: str, sonuc: str,
                 kapsam: str, aciklama: str) -> int:
    if sonuc not in DOGRULAMA_SONUCLARI:
        raise ValueError("Geçersiz sonuç")
    if sonuc != "Doğrulandı" and not metin(aciklama):
        raise ValueError("Şartlı veya olumsuz sonuçta açıklama yazılmalıdır")
    did, _ = urun_degerlendir(db, firma_id, urun_id, dogrulayan)
    u = repo.urun(db, firma_id, urun_id)
    ozet = veri_ozeti(baglam(db, firma_id, u))
    kimlik = db.ekle("dogrulamalar", {
        "firma_id": firma_id, "urun_id": urun_id, "degerlendirme_id": did, "dogrulayan": dogrulayan, "unvan": unvan,
        "tarih": simdi(), "sonuc": sonuc, "kapsam": kapsam, "aciklama": aciklama, "veri_ozeti": ozet,
    })
    audit.kaydet(db, firma_id, dogrulayan, f"Ürün doğrulama: {sonuc}", "urun", urun_id, f"veri özeti {ozet[:16]}")
    return kimlik


def dogrulama_gecerli_mi(db: Veritabani, firma_id: int, urun_id: int) -> tuple[Optional[dict], bool]:
    """(son doğrulama, veri o tarihten beri değişmedi mi)"""
    d = repo.son_dogrulama(db, firma_id, urun_id)
    if not d:
        return None, False
    u = repo.urun(db, firma_id, urun_id)
    return d, veri_ozeti(baglam(db, firma_id, u)) == d["veri_ozeti"]
