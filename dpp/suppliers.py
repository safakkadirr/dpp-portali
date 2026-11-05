"""
Tedarikçi veri talepleri.

Firma, bir tedarikçisine hesap açmadan kullanabileceği tek kullanımlık bir bağlantı
gönderir. Tedarikçi istenen bilgileri girer ve belgeleri yükler. Yüklenen belgeler
'Beklemede' durumunda belge kasasına düşer; ürün verisine aktarma işlemini firma
kullanıcısı onaylar.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Optional

from . import audit, repo
from .db import Veritabani, simdi
from .security import token_ozeti, token_uret
from .util import bos_mu, metin, sayi

ISTENEBILIR = {
    "malzeme": "Malzeme bileşimi (malzeme, oran, menşe)",
    "svhc": "REACH / SVHC beyanı",
    "mense": "Menşe bilgisi",
    "karbon": "Karbon ayak izi",
    "belge": "Belge / sertifika yükleme",
}


def talep_olustur(db: Veritabani, firma_id: int, tedarikci_id: int, urun_id: Optional[int], istenenler: list[str],
                  mesaj: str, gun: int, kullanici: str) -> tuple[int, str]:
    if not istenenler:
        raise ValueError("En az bir bilgi türü seçin")
    if not db.bir("SELECT id FROM tedarikciler WHERE id = ? AND firma_id = ?", (tedarikci_id, firma_id)):
        raise ValueError("Tedarikçi bulunamadı")
    token = token_uret(24)
    kimlik = db.ekle("tedarikci_talepleri", {
        "firma_id": firma_id, "tedarikci_id": tedarikci_id, "urun_id": urun_id, "token_ozet": token_ozeti(token),
        "istenenler": json.dumps([i for i in istenenler if i in ISTENEBILIR]), "mesaj": mesaj, "durum": "Açık",
        "son_tarih": (date.today() + timedelta(days=int(gun))).isoformat(), "olusturan": kullanici, "olusturma": simdi(),
    })
    audit.kaydet(db, firma_id, kullanici, "Tedarikçi talebi oluşturuldu", "talep", kimlik, ", ".join(istenenler))
    return kimlik, token


def talepler(db: Veritabani, firma_id: int) -> list[dict]:
    satirlar = db.tumu("""
        SELECT t.id, t.tedarikci_id, td.unvan AS tedarikci, td.eposta, t.urun_id, u.urun_kodu, u.ad AS urun_adi,
               t.istenenler, t.mesaj, t.durum, t.son_tarih, t.yanit_json, t.yanit_tarihi, t.olusturan, t.olusturma
        FROM tedarikci_talepleri t JOIN tedarikciler td ON td.id = t.tedarikci_id
        LEFT JOIN urunler u ON u.id = t.urun_id WHERE t.firma_id = ? ORDER BY t.id DESC""", (firma_id,))
    for s in satirlar:
        s["istenenler"] = json.loads(s["istenenler"] or "[]")
        s["yanit"] = json.loads(s["yanit_json"]) if s["yanit_json"] else None
    return satirlar


def token_ile(db: Veritabani, token: str) -> Optional[dict]:
    if not token or len(token) > 100:
        return None
    t = db.bir("""
        SELECT t.*, f.unvan AS firma_unvan, td.unvan AS tedarikci_unvan, u.urun_kodu, u.ad AS urun_adi
        FROM tedarikci_talepleri t JOIN firmalar f ON f.id = t.firma_id
        JOIN tedarikciler td ON td.id = t.tedarikci_id LEFT JOIN urunler u ON u.id = t.urun_id
        WHERE t.token_ozet = ?""", (token_ozeti(token),))
    if not t:
        return None
    t["istenenler"] = json.loads(t["istenenler"] or "[]")
    t["suresi_doldu"] = bool(t["son_tarih"] and t["son_tarih"] < date.today().isoformat())
    return t


def yanitla(db: Veritabani, token: str, yanit: dict, dosyalar: list[dict], yanitlayan: str) -> None:
    """dosyalar: [{'tur_kodu','belge_no','duzenleyen','bitis','dosya','dosya_adi','dosya_mime'}]"""
    t = token_ile(db, token)
    if not t:
        raise ValueError("Bağlantı geçersiz")
    if t["durum"] != "Açık":
        raise ValueError("Bu talep daha önce yanıtlanmış veya kapatılmış")
    if t["suresi_doldu"]:
        raise ValueError("Bu bağlantının süresi dolmuş; firmadan yeni bağlantı isteyin")
    if not metin(yanitlayan):
        raise ValueError("Adınızı ve ünvanınızı yazın")
    with db.islem():
        belge_idler = []
        for d in dosyalar:
            baglar = [("tedarikci", t["tedarikci_id"])] + ([("urun", t["urun_id"])] if t["urun_id"] else [])
            belge_idler.append(repo.belge_ekle(
                db, t["firma_id"], {k: d.get(k) for k in ("tur_kodu", "tur_serbest", "belge_no", "duzenleyen", "bitis")},
                baglar, f"Tedarikçi: {yanitlayan}", d.get("dosya"), d.get("dosya_adi"), d.get("dosya_mime"),
                kaynak="Tedarikçi portalı"))
        yanit = dict(yanit)
        yanit["yanitlayan"] = yanitlayan
        yanit["belge_idler"] = belge_idler
        db.guncelle("tedarikci_talepleri", t["id"], {"durum": "Yanıtlandı", "yanit_json": json.dumps(yanit, ensure_ascii=False),
                                                   "yanit_tarihi": simdi()})
        audit.kaydet(db, t["firma_id"], f"Tedarikçi: {yanitlayan}", "Tedarikçi talebi yanıtlandı", "talep", t["id"],
                     f"{len(belge_idler)} belge yüklendi")


def kapat(db: Veritabani, firma_id: int, talep_id: int, kullanici: str):
    db.yaz("UPDATE tedarikci_talepleri SET durum = 'Kapandı' WHERE id = ? AND firma_id = ?", (talep_id, firma_id))
    audit.kaydet(db, firma_id, kullanici, "Tedarikçi talebi kapatıldı", "talep", talep_id)


def urune_aktar(db: Veritabani, firma_id: int, talep_id: int, kullanici: str) -> list[str]:
    """Yanıttaki verileri ürüne aktarır. Yapılan işlemlerin listesini döner."""
    t = db.bir("SELECT * FROM tedarikci_talepleri WHERE id = ? AND firma_id = ?", (talep_id, firma_id))
    if not t or not t["yanit_json"]:
        raise ValueError("Aktarılacak yanıt yok")
    if not t["urun_id"]:
        raise ValueError("Talep bir ürüne bağlı değil; verileri ürün ekranından elle girin")
    y = json.loads(t["yanit_json"])
    yapilan = []
    guncel = {}
    if not bos_mu(y.get("svhc_beyani")):
        guncel["svhc_beyani"] = y["svhc_beyani"]
        guncel["svhc_maddeler"] = y.get("svhc_maddeler")
        yapilan.append("SVHC beyanı")
    if not bos_mu(y.get("hammadde_mensei")):
        guncel["hammadde_mensei"] = y["hammadde_mensei"]
        yapilan.append("Hammadde menşei")
    if sayi(y.get("karbon_kg")) is not None:
        guncel["karbon_kg"] = sayi(y["karbon_kg"])
        guncel["karbon_yontemi"] = y.get("karbon_yontemi")
        yapilan.append("Karbon ayak izi")
    with db.islem():
        if guncel:
            repo.urun_kaydet(db, firma_id, guncel, kullanici, t["urun_id"])
        malzemeler = [m for m in (y.get("malzemeler") or []) if not bos_mu(m.get("malzeme"))]
        if malzemeler:
            mevcut = repo.alt_liste(db, "malzemeler", firma_id, t["urun_id"])
            # Mevcut satırların hiçbiri bir tedarikçiye bağlı değilse, tedarikçinin bildirdiği bileşim ürünün bileşimi kabul edilir.
            # Aksi halde yalnızca bu tedarikçinin satırları değiştirilir.
            if any(m.get("tedarikci_id") for m in mevcut):
                digerleri = [m for m in mevcut if m.get("tedarikci_id") != t["tedarikci_id"]]
            else:
                digerleri = []
            yeni = [{"malzeme": m["malzeme"], "oran": sayi(m.get("oran")), "mense": m.get("mense"),
                     "geri_donusturulmus": 1 if m.get("geri_donusturulmus") else 0, "tedarikci_id": t["tedarikci_id"]}
                    for m in malzemeler]
            repo.alt_degistir(db, "malzemeler", firma_id, t["urun_id"], digerleri + yeni, kullanici)
            yapilan.append(f"{len(yeni)} malzeme satırı")
        db.guncelle("tedarikci_talepleri", talep_id, {"durum": "Kapandı"}, firma_id)
        audit.kaydet(db, firma_id, kullanici, "Tedarikçi yanıtı ürüne aktarıldı", "talep", talep_id, ", ".join(yapilan))
    return yapilan
