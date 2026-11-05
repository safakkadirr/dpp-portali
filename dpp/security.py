"""Kimlik doğrulama, parola güvenliği, roller ve yetkiler."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional

from .db import Veritabani, simdi

# ---------------------------------------------------------------------------
# Roller ve yetkiler
# ---------------------------------------------------------------------------

# Firma içinde tüm kullanıcılar eşittir: herkes veri girebilir, doğrulayabilir, pasaport yayımlayabilir,
# kullanıcı ekleyebilir. Eski sürümden kalan rol kodları (editor, denetci, izleyici) da "Kullanıcı" sayılır.
# Tek ayrım platform düzeyindedir: firmaları ve tüm firmaları etkileyen kural setini yalnızca
# platform yöneticisi yönetir (bir firmanın kullanıcısı diğer firmaları göremez).
ROLLER = {
    "platform_yonetici": "Platform yöneticisi",
    "firma_yonetici": "Kullanıcı",
    "editor": "Kullanıcı",
    "denetci": "Kullanıcı",
    "izleyici": "Kullanıcı",
}
YENI_KULLANICI_ROLU = "firma_yonetici"

PLATFORM_YETKILERI = {"firma_yonet", "kural_yonet"}


def yetkili(rol: str, eylem: str) -> bool:
    if not rol:
        return False
    if eylem in PLATFORM_YETKILERI:
        return rol == "platform_yonetici"
    return True


# ---------------------------------------------------------------------------
# Parola
# ---------------------------------------------------------------------------

_N, _R, _P = 2 ** 14, 8, 1


def parola_hash(parola: str) -> str:
    tuz = secrets.token_bytes(16)
    ozet = hashlib.scrypt(parola.encode("utf-8"), salt=tuz, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(_N, _R, _P, base64.b64encode(tuz).decode(), base64.b64encode(ozet).decode())


def parola_dogrula(parola: str, kayit: str) -> bool:
    try:
        algo, n, r, p, tuz, ozet = kayit.split("$")
        if algo != "scrypt":
            return False
        hesap = hashlib.scrypt(parola.encode("utf-8"), salt=base64.b64decode(tuz), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(hesap, base64.b64decode(ozet))
    except Exception:
        return False


def parola_kurali(parola: str) -> Optional[str]:
    """Uygunsa None, değilse açıklama döner."""
    if len(parola) < 10:
        return "Parola en az 10 karakter olmalı."
    if not re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]", parola) or not re.search(r"\d", parola):
        return "Parola en az bir harf ve bir rakam içermeli."
    return None


def gecici_parola() -> str:
    govde = secrets.token_urlsafe(9)
    return govde + str(secrets.randbelow(10))


def token_uret(bayt: int = 24) -> str:
    return secrets.token_urlsafe(bayt)


def token_ozeti(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Kullanıcı işlemleri
# ---------------------------------------------------------------------------

AZAMI_DENEME = 5
KILIT_DAKIKA = 15

GENEL_HATA = "E-posta veya parola hatalı."


def eposta_normal(eposta: str) -> str:
    return (eposta or "").strip().lower()


def eposta_gecerli(eposta: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", eposta_normal(eposta)))


def kullanici_sayisi(db: Veritabani) -> int:
    return int(db.deger("SELECT COUNT(*) FROM kullanicilar") or 0)


def kullanici_olustur(db: Veritabani, eposta: str, ad_soyad: str, rol: str, parola: str,
                      firma_id: Optional[int], parola_degismeli: bool = True) -> int:
    if rol not in ROLLER:
        raise ValueError("Geçersiz rol")
    if rol != "platform_yonetici" and not firma_id:
        raise ValueError("Bu rol için firma seçilmelidir")
    if not eposta_gecerli(eposta):
        raise ValueError("Geçerli bir e-posta adresi girin")
    if db.bir("SELECT id FROM kullanicilar WHERE eposta = ?", (eposta_normal(eposta),)):
        raise ValueError("Bu e-posta ile kayıtlı bir kullanıcı zaten var")
    hata = parola_kurali(parola)
    if hata:
        raise ValueError(hata)
    return db.ekle("kullanicilar", {
        "firma_id": None if rol == "platform_yonetici" else firma_id,
        "eposta": eposta_normal(eposta), "ad_soyad": ad_soyad.strip(), "rol": rol,
        "parola_hash": parola_hash(parola), "aktif": 1, "basarisiz_giris": 0,
        "parola_degismeli": 1 if parola_degismeli else 0, "olusturma": simdi(),
    })


def giris(db: Veritabani, eposta: str, parola: str) -> tuple[Optional[dict], str]:
    """Başarılıysa (kullanıcı, ''), değilse (None, mesaj)."""
    k = db.bir("SELECT * FROM kullanicilar WHERE eposta = ?", (eposta_normal(eposta),))
    if not k:
        parola_hash(parola)  # zamanlama farkını azaltmak için
        return None, GENEL_HATA
    if not k["aktif"]:
        return None, "Hesabınız pasif durumda. Firma yöneticinize başvurun."
    if k["kilit_bitis"] and k["kilit_bitis"] > simdi():
        return None, f"Çok sayıda hatalı deneme nedeniyle hesap {KILIT_DAKIKA} dakika kilitlendi."
    if k["firma_id"]:
        firma = db.bir("SELECT aktif FROM firmalar WHERE id = ?", (k["firma_id"],))
        if not firma or not firma["aktif"]:
            return None, "Firmanızın hesabı pasif durumda."
    if not parola_dogrula(parola, k["parola_hash"]):
        deneme = (k["basarisiz_giris"] or 0) + 1
        kilit = None
        if deneme >= AZAMI_DENEME:
            kilit = (datetime.now() + timedelta(minutes=KILIT_DAKIKA)).isoformat(timespec="seconds")
            deneme = 0
        db.guncelle("kullanicilar", k["id"], {"basarisiz_giris": deneme, "kilit_bitis": kilit})
        return None, GENEL_HATA
    db.guncelle("kullanicilar", k["id"], {"basarisiz_giris": 0, "kilit_bitis": None, "son_giris": simdi()})
    k = dict(k)
    k.pop("parola_hash", None)
    return k, ""


def parola_degistir(db: Veritabani, kullanici_id: int, eski: str, yeni: str) -> Optional[str]:
    k = db.bir("SELECT parola_hash FROM kullanicilar WHERE id = ?", (kullanici_id,))
    if not k or not parola_dogrula(eski, k["parola_hash"]):
        return "Mevcut parola hatalı."
    if eski == yeni:
        return "Yeni parola eskisiyle aynı olamaz."
    hata = parola_kurali(yeni)
    if hata:
        return hata
    db.guncelle("kullanicilar", kullanici_id, {"parola_hash": parola_hash(yeni), "parola_degismeli": 0})
    return None


def parola_sifirla(db: Veritabani, kullanici_id: int) -> str:
    yeni = gecici_parola()
    db.guncelle("kullanicilar", kullanici_id, {"parola_hash": parola_hash(yeni), "parola_degismeli": 1,
                                               "basarisiz_giris": 0, "kilit_bitis": None})
    return yeni
