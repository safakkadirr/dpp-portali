"""
Zincirleme özetli denetim izi.

Her kayıt, bir önceki kaydın özetini içerir. Bir kayıt sonradan değiştirilir
veya silinirse zincir doğrulaması kırılır (değişikliğe karşı belirti verir).
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional

from .db import Veritabani, simdi

BASLANGIC = "0" * 64


def _ozet(onceki: str, kayit: dict) -> str:
    govde = json.dumps({k: kayit.get(k) for k in ("firma_id", "kullanici", "zaman", "islem", "varlik", "varlik_id", "detay")},
                       ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256((onceki + govde).encode("utf-8")).hexdigest()


def kaydet(db: Veritabani, firma_id: Optional[int], kullanici: str, islem: str,
           varlik: str = "", varlik_id=None, detay: str = "") -> None:
    with db.islem():
        onceki = db.deger("SELECT ozet FROM denetim_izi ORDER BY id DESC LIMIT 1") or BASLANGIC
        kayit = {"firma_id": firma_id, "kullanici": kullanici or "sistem", "zaman": simdi(), "islem": islem,
                 "varlik": varlik, "varlik_id": None if varlik_id is None else str(varlik_id), "detay": (detay or "")[:4000]}
        kayit["onceki_ozet"] = onceki
        kayit["ozet"] = _ozet(onceki, kayit)
        db.ekle("denetim_izi", kayit)


def listele(db: Veritabani, firma_id: Optional[int], limit: int = 500) -> list[dict]:
    if firma_id is None:
        return db.tumu("SELECT * FROM denetim_izi ORDER BY id DESC LIMIT ?", (limit,))
    return db.tumu("SELECT * FROM denetim_izi WHERE firma_id = ? ORDER BY id DESC LIMIT ?", (firma_id, limit))


def zinciri_dogrula(db: Veritabani) -> tuple[bool, int, Optional[int]]:
    """(sağlam_mı, kontrol_edilen_kayıt, ilk_bozuk_kayıt_id)"""
    onceki = BASLANGIC
    sayi = 0
    for kayit in db.tumu("SELECT * FROM denetim_izi ORDER BY id"):
        sayi += 1
        if kayit["onceki_ozet"] != onceki or _ozet(onceki, kayit) != kayit["ozet"]:
            return False, sayi, kayit["id"]
        onceki = kayit["ozet"]
    return True, sayi, None
