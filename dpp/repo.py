"""
Veri erişim katmanı. Her fonksiyon firma_id ile çalışır; bir firmanın kullanıcısı
başka bir firmanın verisine erişemez (çok kiracılı ayrım).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Optional

from . import audit
from .catalog import SEKTOR
from .db import Veritabani, simdi
from .rules import belge_durumu
from .util import bos_mu, gtin_temizle, metin, tr_norm

AZAMI_DOSYA = 10 * 1024 * 1024  # 10 MB

URUN_ALANLARI = [
    "urun_kodu", "ad", "sektor_kodu", "tuketici_urunu", "marka", "gtin", "gtip", "tesis_id", "ab_sorumlu_operator",
    "uretim_ulkesi", "hammadde_mensei", "geri_donusturulmus_yuzde", "svhc_beyani", "svhc_maddeler", "cevresel_iddia",
    "karbon_kg", "karbon_yontemi", "gomulu_emisyon", "eprel_no", "imds_id", "batarya_kategori", "batarya_kimya",
    "batarya_kwh", "bakim_onarim", "omur_sonu", "notlar",
]


def _temiz(veri: dict, alanlar: list[str]) -> dict:
    sonuc = {}
    for k in alanlar:
        if k in veri:
            v = veri[k]
            if isinstance(v, str):
                v = v.strip() or None
            elif v is not None and bos_mu(v):
                v = None
            sonuc[k] = v
    return sonuc


# ---------------------------------------------------------------------------
# Firmalar ve kullanıcılar
# ---------------------------------------------------------------------------

def firmalar(db: Veritabani) -> list[dict]:
    return db.tumu("""
        SELECT f.*, (SELECT COUNT(*) FROM urunler u WHERE u.firma_id = f.id AND u.aktif = 1) AS urun_sayisi,
               (SELECT COUNT(*) FROM kullanicilar k WHERE k.firma_id = f.id) AS kullanici_sayisi
        FROM firmalar f ORDER BY f.unvan""")


def firma(db: Veritabani, firma_id: int) -> Optional[dict]:
    return db.bir("SELECT * FROM firmalar WHERE id = ?", (firma_id,))


FIRMA_ALANLARI = ["unvan", "vergi_no", "adres", "ulke", "eposta", "telefon", "web", "cozumleyici_alan", "plan", "aktif"]


def firma_kaydet(db: Veritabani, veri: dict, kullanici: str, firma_id: Optional[int] = None) -> int:
    temiz = _temiz(veri, FIRMA_ALANLARI)
    if not temiz.get("unvan") and firma_id is None:
        raise ValueError("Firma unvanı zorunludur")
    if firma_id:
        db.guncelle("firmalar", firma_id, temiz)
        audit.kaydet(db, firma_id, kullanici, "Firma güncellendi", "firma", firma_id, json.dumps(temiz, ensure_ascii=False))
        return firma_id
    temiz["olusturma"] = simdi()
    yeni = db.ekle("firmalar", temiz)
    audit.kaydet(db, yeni, kullanici, "Firma oluşturuldu", "firma", yeni, temiz["unvan"])
    return yeni


def kullanicilar(db: Veritabani, firma_id: Optional[int]) -> list[dict]:
    sql = ("SELECT k.id, k.firma_id, f.unvan AS firma, k.eposta, k.ad_soyad, k.rol, k.aktif, k.son_giris, k.olusturma "
           "FROM kullanicilar k LEFT JOIN firmalar f ON f.id = k.firma_id")
    if firma_id is None:
        return db.tumu(sql + " ORDER BY f.unvan, k.ad_soyad")
    return db.tumu(sql + " WHERE k.firma_id = ? ORDER BY k.ad_soyad", (firma_id,))


def kullanici_guncelle(db: Veritabani, hedef_id: int, veri: dict, firma_id: Optional[int], kullanici: str):
    temiz = _temiz(veri, ["ad_soyad", "rol", "aktif"])
    if firma_id is not None:
        db.yaz("UPDATE kullanicilar SET " + ", ".join(f"{k} = ?" for k in temiz) + " WHERE id = ? AND firma_id = ?",
               list(temiz.values()) + [hedef_id, firma_id])
    else:
        db.guncelle("kullanicilar", hedef_id, temiz)
    audit.kaydet(db, firma_id, kullanici, "Kullanıcı güncellendi", "kullanici", hedef_id, json.dumps(temiz, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Tesisler ve tedarikçiler
# ---------------------------------------------------------------------------

TESIS_ALANLARI = ["ad", "adres", "ulke", "gln", "tur", "notlar"]
TEDARIKCI_ALANLARI = ["unvan", "ulke", "eposta", "yetkili", "kimlik_no", "notlar"]


def tesisler(db, firma_id) -> list[dict]:
    return db.tumu("SELECT * FROM tesisler WHERE firma_id = ? ORDER BY ad", (firma_id,))


def tedarikciler(db, firma_id) -> list[dict]:
    return db.tumu("SELECT * FROM tedarikciler WHERE firma_id = ? ORDER BY unvan", (firma_id,))


_UNVAN_EKLERI = {"san", "sanayi", "tic", "ticaret", "ve", "ltd", "sti", "limited", "sirketi", "as", "a", "s", "anonim", "inc",
                 "co", "corp", "company", "gmbh", "srl", "sa", "spa", "bv", "llc", "plc", "industries", "industry", "tekstil",
                 "textile", "textiles"}


def unvan_anahtari(ad) -> str:
    """'Uçur Tekstil San. ve Tic. A.Ş.' ile 'Uçur Tekstil San.' aynı firma sayılsın diye unvan eklerini ayıklar."""
    import re
    kelimeler = re.sub(r"[^a-z0-9]+", " ", tr_norm(ad)).split()
    cekirdek = [k for k in kelimeler if k not in _UNVAN_EKLERI]
    return " ".join(cekirdek or kelimeler)


def _ad_ile_bul_veya_ekle(db, tablo, ad_alani, firma_id, ad, ek: Optional[dict] = None) -> Optional[int]:
    ad = metin(ad)
    if not ad:
        return None
    r = db.bir(f"SELECT id FROM {tablo} WHERE firma_id = ? AND LOWER({ad_alani}) = LOWER(?)", (firma_id, ad))
    if r:
        return r["id"]
    if tablo == "tedarikciler":
        anahtar = unvan_anahtari(ad)
        if anahtar:
            for x in db.tumu(f"SELECT id, {ad_alani} AS ad FROM {tablo} WHERE firma_id = ?", (firma_id,)):
                diger = unvan_anahtari(x["ad"])
                if diger and (diger == anahtar or diger.startswith(anahtar + " ") or anahtar.startswith(diger + " ")):
                    return x["id"]
    veri = {"firma_id": firma_id, ad_alani: ad}
    veri.update({k: v for k, v in (ek or {}).items() if not bos_mu(v)})
    return db.ekle(tablo, veri)


def tesis_bul_veya_ekle(db, firma_id, ad, ek=None):
    return _ad_ile_bul_veya_ekle(db, "tesisler", "ad", firma_id, ad, ek)


def tedarikci_bul_veya_ekle(db, firma_id, unvan, ek=None):
    return _ad_ile_bul_veya_ekle(db, "tedarikciler", "unvan", firma_id, unvan, ek)


def tablo_kaydet(db, tablo: str, alanlar: list[str], firma_id: int, satirlar: list[dict], kullanici: str,
                 anahtar: str) -> tuple[int, int]:
    """Tesis/tedarikçi tablosunu ekrandaki düzenlemeyle eşitler. (eklenen, güncellenen)"""
    eklenen = guncellenen = 0
    with db.islem():
        for s in satirlar:
            temiz = _temiz(s, alanlar)
            if not temiz.get(anahtar):
                continue
            kimlik = s.get("id")
            if kimlik and not bos_mu(kimlik):
                guncellenen += db.guncelle(tablo, int(kimlik), temiz, firma_id)
            else:
                temiz["firma_id"] = firma_id
                db.ekle(tablo, temiz)
                eklenen += 1
        audit.kaydet(db, firma_id, kullanici, f"{tablo} güncellendi", tablo, None, f"{eklenen} eklendi, {guncellenen} güncellendi")
    return eklenen, guncellenen


# ---------------------------------------------------------------------------
# Ürünler
# ---------------------------------------------------------------------------

def urunler(db, firma_id, sadece_aktif: bool = True) -> list[dict]:
    sql = """
        SELECT u.*, t.ad AS tesis_adi,
               d.id AS degerlendirme_id, d.tarih AS degerlendirme_tarihi, d.yasal_durum, d.yasal_eksik, d.kritik_eksik,
               d.hazirlik_skoru, d.genel_durum, d.kural_seti,
               (SELECT MAX(p.surum) FROM pasaportlar p WHERE p.urun_id = u.id AND p.durum = 'Yayında') AS yayindaki_surum
        FROM urunler u
        LEFT JOIN tesisler t ON t.id = u.tesis_id
        LEFT JOIN degerlendirmeler d ON d.urun_id = u.id AND d.son = 1
        WHERE u.firma_id = ?"""
    if sadece_aktif:
        sql += " AND u.aktif = 1"
    return db.tumu(sql + " ORDER BY u.urun_kodu", (firma_id,))


def urun(db, firma_id, urun_id) -> Optional[dict]:
    return db.bir("SELECT * FROM urunler WHERE id = ? AND firma_id = ?", (urun_id, firma_id))


def urun_kod_ile(db, firma_id, kod) -> Optional[dict]:
    return db.bir("SELECT * FROM urunler WHERE firma_id = ? AND urun_kodu = ?", (firma_id, metin(kod)))


def urun_kaydet(db, firma_id: int, veri: dict, kullanici: str, urun_id: Optional[int] = None) -> int:
    temiz = _temiz(veri, URUN_ALANLARI)
    if "gtin" in temiz and temiz["gtin"]:
        temiz["gtin"] = gtin_temizle(temiz["gtin"]) or None
    if "sektor_kodu" in temiz and temiz["sektor_kodu"] not in SEKTOR:
        temiz["sektor_kodu"] = "diger"
    temiz["guncelleme"] = simdi()
    temiz["guncelleyen"] = kullanici
    if urun_id:
        eski = urun(db, firma_id, urun_id)
        if not eski:
            raise ValueError("Ürün bulunamadı")
        degisen = {k: v for k, v in temiz.items() if k not in ("guncelleme", "guncelleyen") and metin(eski.get(k)) != metin(v)}
        if "urun_kodu" in degisen and urun_kod_ile(db, firma_id, temiz["urun_kodu"]):
            raise ValueError("Bu ürün kodu başka bir üründe kullanılıyor")
        db.guncelle("urunler", urun_id, temiz, firma_id)
        if degisen:
            audit.kaydet(db, firma_id, kullanici, "Ürün güncellendi", "urun", urun_id,
                         "; ".join(f"{k}: '{metin(eski.get(k))}' → '{metin(v)}'" for k, v in degisen.items()))
        return urun_id
    if not temiz.get("urun_kodu") or not temiz.get("ad"):
        raise ValueError("Ürün kodu ve ürün adı zorunludur")
    if urun_kod_ile(db, firma_id, temiz["urun_kodu"]):
        raise ValueError("Bu ürün kodu zaten kayıtlı")
    temiz.update({"firma_id": firma_id, "olusturma": simdi(), "aktif": 1})
    temiz.setdefault("sektor_kodu", "diger")
    yeni = db.ekle("urunler", temiz)
    audit.kaydet(db, firma_id, kullanici, "Ürün oluşturuldu", "urun", yeni, f"{temiz['urun_kodu']} — {temiz['ad']}")
    return yeni


def urun_pasiflestir(db, firma_id, urun_id, kullanici):
    db.guncelle("urunler", urun_id, {"aktif": 0, "guncelleme": simdi(), "guncelleyen": kullanici}, firma_id)
    audit.kaydet(db, firma_id, kullanici, "Ürün arşivlendi", "urun", urun_id)


def gtin_tekrarlari(db, firma_id) -> set:
    satirlar = db.tumu("SELECT gtin FROM urunler WHERE firma_id = ? AND aktif = 1 AND gtin IS NOT NULL AND gtin <> '' "
                       "GROUP BY gtin HAVING COUNT(*) > 1", (firma_id,))
    return {r["gtin"] for r in satirlar}


# --- alt tablolar (malzeme, tedarik aşaması, parti) ------------------------

ALT_TABLOLAR = {
    "malzemeler": ["malzeme", "oran", "mense", "geri_donusturulmus", "tedarikci_id"],
    "tedarik_asamalari": ["sira", "asama", "tedarikci_id", "ulke", "belge_no"],
    "partiler": ["parti_no", "uretim_tarihi", "miktar", "tesis_id", "notlar"],
}
_ALT_ZORUNLU = {"malzemeler": "malzeme", "tedarik_asamalari": "asama", "partiler": "parti_no"}
_ALT_SIRA = {"malzemeler": "oran DESC, id", "tedarik_asamalari": "sira, id", "partiler": "uretim_tarihi DESC, id"}


def alt_liste(db, tablo, firma_id, urun_id) -> list[dict]:
    if tablo not in ALT_TABLOLAR:
        raise ValueError(tablo)
    return db.tumu(f"SELECT * FROM {tablo} WHERE firma_id = ? AND urun_id = ? ORDER BY {_ALT_SIRA[tablo]}", (firma_id, urun_id))


def alt_degistir(db, tablo, firma_id, urun_id, satirlar: list[dict], kullanici: str, denetle: bool = True) -> int:
    """Bir ürünün alt tablosunu verilen satırlarla tamamen değiştirir."""
    alanlar = ALT_TABLOLAR[tablo]
    zorunlu = _ALT_ZORUNLU[tablo]
    temiz = [_temiz(s, alanlar) for s in satirlar]
    temiz = [s for s in temiz if not bos_mu(s.get(zorunlu))]
    if tablo == "partiler":
        nolar = [metin(s["parti_no"]) for s in temiz]
        if len(nolar) != len(set(nolar)):
            raise ValueError("Aynı parti numarası birden fazla kez girilmiş")
    with db.islem():
        eski = alt_liste(db, tablo, firma_id, urun_id)
        db.yaz(f"DELETE FROM {tablo} WHERE firma_id = ? AND urun_id = ?", (firma_id, urun_id))
        for s in temiz:
            s.update({"firma_id": firma_id, "urun_id": urun_id})
            db.ekle(tablo, s)
        if denetle:
            audit.kaydet(db, firma_id, kullanici, f"{tablo} güncellendi", "urun", urun_id,
                         f"{len(eski)} satır → {len(temiz)} satır")
    return len(temiz)


# ---------------------------------------------------------------------------
# Belgeler
# ---------------------------------------------------------------------------

BELGE_ALANLARI = ["tur_kodu", "tur_serbest", "belge_no", "duzenleyen", "baslangic", "bitis", "kapsam"]


def belgeler(db, firma_id, bugun: Optional[date] = None) -> list[dict]:
    bugun = bugun or date.today()
    satirlar = db.tumu("""
        SELECT b.id, b.tur_kodu, b.tur_serbest, b.belge_no, b.duzenleyen, b.baslangic, b.bitis, b.kapsam,
               b.dosya_adi, b.dosya_boyut, b.dosya_ozet, b.dogrulama_durumu, b.dogrulayan, b.dogrulama_tarihi,
               b.dogrulama_notu, b.kaynak, b.yukleyen, b.olusturma
        FROM belgeler b WHERE b.firma_id = ? ORDER BY b.bitis""", (firma_id,))
    baglar = db.tumu("""
        SELECT bb.belge_id, bb.hedef_tur, bb.hedef_id,
               CASE bb.hedef_tur WHEN 'urun' THEN u.urun_kodu WHEN 'tesis' THEN t.ad
                                 WHEN 'tedarikci' THEN td.unvan ELSE 'Tüm firma' END AS hedef_adi
        FROM belge_baglantilari bb
        LEFT JOIN urunler u ON bb.hedef_tur = 'urun' AND u.id = bb.hedef_id
        LEFT JOIN tesisler t ON bb.hedef_tur = 'tesis' AND t.id = bb.hedef_id
        LEFT JOIN tedarikciler td ON bb.hedef_tur = 'tedarikci' AND td.id = bb.hedef_id
        WHERE bb.firma_id = ?""", (firma_id,))
    harita: dict[int, list] = {}
    for b in baglar:
        harita.setdefault(b["belge_id"], []).append(b)
    for s in satirlar:
        s["durum"], s["kalan"] = belge_durumu(s["bitis"], bugun)
        s["baglantilar"] = harita.get(s["id"], [])
    return satirlar


def urun_belgeleri(db, firma_id, urun_id, bugun: Optional[date] = None) -> list[dict]:
    """Ürüne doğrudan, firmanın tamamına, ürünün tesisine veya ürünün tedarikçilerine bağlı belgeler."""
    u = urun(db, firma_id, urun_id)
    if not u:
        return []
    tedarikci_idler = {r["tedarikci_id"] for r in db.tumu(
        "SELECT tedarikci_id FROM malzemeler WHERE urun_id = ? AND tedarikci_id IS NOT NULL "
        "UNION SELECT tedarikci_id FROM tedarik_asamalari WHERE urun_id = ? AND tedarikci_id IS NOT NULL", (urun_id, urun_id))}
    sonuc = []
    for b in belgeler(db, firma_id, bugun):
        for bag in b["baglantilar"]:
            t, h = bag["hedef_tur"], bag["hedef_id"]
            if (t == "urun" and h == urun_id) or t == "firma" or (t == "tesis" and h == u.get("tesis_id")) \
                    or (t == "tedarikci" and h in tedarikci_idler):
                b = dict(b)
                b["bag_turu"] = t
                sonuc.append(b)
                break
    return sonuc


def belge_ekle(db, firma_id: int, veri: dict, baglantilar: list[tuple[str, Optional[int]]], kullanici: str,
               dosya: Optional[bytes] = None, dosya_adi: Optional[str] = None, dosya_mime: Optional[str] = None,
               kaynak: str = "Kullanıcı") -> int:
    temiz = _temiz(veri, BELGE_ALANLARI)
    if not temiz.get("tur_kodu"):
        raise ValueError("Belge türü zorunludur")
    if dosya is not None:
        if len(dosya) > AZAMI_DOSYA:
            raise ValueError("Dosya 10 MB'tan büyük olamaz")
        temiz.update({"dosya": dosya, "dosya_adi": dosya_adi, "dosya_mime": dosya_mime, "dosya_boyut": len(dosya),
                      "dosya_ozet": hashlib.sha256(dosya).hexdigest()})
    temiz.update({"firma_id": firma_id, "dogrulama_durumu": "Beklemede", "kaynak": kaynak, "yukleyen": kullanici,
                  "olusturma": simdi()})
    with db.islem():
        kimlik = db.ekle("belgeler", temiz)
        belge_baglantilari_ayarla(db, firma_id, kimlik, baglantilar)
        audit.kaydet(db, firma_id, kullanici, "Belge eklendi", "belge", kimlik,
                     f"{temiz['tur_kodu']} {temiz.get('belge_no') or ''} — dosya: {dosya_adi or 'yok'} "
                     f"{('SHA-256 ' + temiz['dosya_ozet'][:16]) if dosya else ''}")
    return kimlik


def belge_guncelle(db, firma_id, belge_id, veri: dict, kullanici: str):
    temiz = _temiz(veri, BELGE_ALANLARI)
    # İçerik değişen belge yeniden doğrulama bekler
    temiz.update({"dogrulama_durumu": "Beklemede", "dogrulayan": None, "dogrulama_tarihi": None})
    db.guncelle("belgeler", belge_id, temiz, firma_id)
    audit.kaydet(db, firma_id, kullanici, "Belge güncellendi", "belge", belge_id, json.dumps(_temiz(veri, BELGE_ALANLARI), ensure_ascii=False, default=str))


def belge_baglantilari_ayarla(db, firma_id, belge_id, baglantilar: list[tuple[str, Optional[int]]]):
    db.yaz("DELETE FROM belge_baglantilari WHERE belge_id = ? AND firma_id = ?", (belge_id, firma_id))
    for tur, hedef in dict.fromkeys(baglantilar):
        if tur not in ("urun", "tesis", "tedarikci", "firma"):
            continue
        db.ekle("belge_baglantilari", {"firma_id": firma_id, "belge_id": belge_id, "hedef_tur": tur,
                                       "hedef_id": None if tur == "firma" else hedef})


def belge_sil(db, firma_id, belge_id, kullanici):
    b = db.bir("SELECT tur_kodu, belge_no FROM belgeler WHERE id = ? AND firma_id = ?", (belge_id, firma_id))
    if not b:
        return
    with db.islem():
        db.yaz("DELETE FROM belge_baglantilari WHERE belge_id = ? AND firma_id = ?", (belge_id, firma_id))
        db.yaz("DELETE FROM belgeler WHERE id = ? AND firma_id = ?", (belge_id, firma_id))
        audit.kaydet(db, firma_id, kullanici, "Belge silindi", "belge", belge_id, f"{b['tur_kodu']} {b['belge_no'] or ''}")


def belge_dosyasi(db, firma_id, belge_id) -> Optional[dict]:
    r = db.bir("SELECT dosya, dosya_adi, dosya_mime FROM belgeler WHERE id = ? AND firma_id = ?", (belge_id, firma_id))
    if r and r["dosya"] is not None:
        r["dosya"] = bytes(r["dosya"])
    return r


def belge_dogrula(db, firma_id, belge_id, durum: str, not_: str, dogrulayan: str):
    if durum not in ("Doğrulandı", "Reddedildi", "Beklemede"):
        raise ValueError("Geçersiz durum")
    if durum == "Reddedildi" and not metin(not_):
        raise ValueError("Reddetme gerekçesi yazılmalıdır")
    db.guncelle("belgeler", belge_id, {"dogrulama_durumu": durum, "dogrulama_notu": metin(not_) or None,
                                       "dogrulayan": dogrulayan, "dogrulama_tarihi": simdi()}, firma_id)
    audit.kaydet(db, firma_id, dogrulayan, f"Belge doğrulama: {durum}", "belge", belge_id, not_)


# ---------------------------------------------------------------------------
# Kural ayarları
# ---------------------------------------------------------------------------

def kural_ayarlari(db) -> dict[str, dict]:
    return {r["kural_kodu"]: r for r in db.tumu("SELECT * FROM kural_ayarlari")}


def kural_ayari_kaydet(db, kod: str, aktif: bool, agirlik: Optional[int], kullanici: str, varsayilan_agirlik: int):
    if aktif and (agirlik is None or agirlik == varsayilan_agirlik):
        db.yaz("DELETE FROM kural_ayarlari WHERE kural_kodu = ?", (kod,))
    else:
        db.yaz("INSERT INTO kural_ayarlari (kural_kodu, aktif, agirlik, guncelleyen, guncelleme) VALUES (?, ?, ?, ?, ?) "
               "ON CONFLICT (kural_kodu) DO UPDATE SET aktif = excluded.aktif, agirlik = excluded.agirlik, "
               "guncelleyen = excluded.guncelleyen, guncelleme = excluded.guncelleme",
               (kod, 1 if aktif else 0, agirlik, kullanici, simdi()))
    audit.kaydet(db, None, kullanici, "Kural ayarı değişti", "kural", kod, f"aktif={aktif}, ağırlık={agirlik}")


# ---------------------------------------------------------------------------
# Bağımsız doğrulama beyanları
# ---------------------------------------------------------------------------

def dogrulamalar(db, firma_id, urun_id=None) -> list[dict]:
    sql = ("SELECT d.*, u.urun_kodu, u.ad AS urun_adi FROM dogrulamalar d JOIN urunler u ON u.id = d.urun_id "
           "WHERE d.firma_id = ?")
    p = [firma_id]
    if urun_id:
        sql += " AND d.urun_id = ?"
        p.append(urun_id)
    return db.tumu(sql + " ORDER BY d.id DESC", p)


def son_dogrulama(db, firma_id, urun_id) -> Optional[dict]:
    r = dogrulamalar(db, firma_id, urun_id)
    return r[0] if r else None
