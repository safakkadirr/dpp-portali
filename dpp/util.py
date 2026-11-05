"""Genel yardımcılar ve doğrulayıcılar (GTIN, GTİP, malzeme bileşimi)."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

_TR_MAP = str.maketrans("çğıöşüâîû", "cgiosuaiu")
_BOS = {"", "nan", "none", "null", "-", "—", "n/a", "na", "nat"}


def tr_norm(deger) -> str:
    s = "" if deger is None else str(deger)
    s = s.replace("İ", "i").replace("I", "ı").lower().translate(_TR_MAP).replace("̇", "")
    return s.strip()


def bos_mu(deger) -> bool:
    if deger is None:
        return True
    if isinstance(deger, float) and deger != deger:  # NaN
        return True
    try:
        import pandas as pd
        if deger is pd.NA or deger is pd.NaT:
            return True
    except Exception:
        pass
    return tr_norm(deger) in _BOS


def metin(deger, varsayilan: str = "") -> str:
    if bos_mu(deger):
        return varsayilan
    if isinstance(deger, float) and deger.is_integer():
        return str(int(deger))
    if isinstance(deger, (datetime, date)):
        return deger.strftime("%Y-%m-%d")
    if hasattr(deger, "strftime"):
        return deger.strftime("%Y-%m-%d")
    return str(deger).strip()


def sayi(deger) -> Optional[float]:
    if bos_mu(deger):
        return None
    if isinstance(deger, (int, float)):
        return float(deger)
    s = str(deger).replace("%", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def tarih_metni(deger) -> Optional[str]:
    """Çeşitli tarih biçimlerini YYYY-MM-DD metnine çevirir."""
    if bos_mu(deger):
        return None
    if isinstance(deger, datetime):
        return deger.date().isoformat()
    if isinstance(deger, date):
        return deger.isoformat()
    if hasattr(deger, "to_pydatetime"):
        return deger.to_pydatetime().date().isoformat()
    s = str(deger).strip()[:19]
    for bicim in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d.%m.%y"):
        try:
            return datetime.strptime(s if "%H" in bicim else s[:10], bicim).date().isoformat()
        except ValueError:
            continue
    if isinstance(deger, (int, float)) and 20000 < float(deger) < 80000:  # Excel seri tarihi
        from datetime import timedelta
        return (date(1899, 12, 30) + timedelta(days=int(deger))).isoformat()
    return None


def tarih(deger) -> Optional[date]:
    t = tarih_metni(deger)
    return date.fromisoformat(t) if t else None


def evet_mi(deger) -> Optional[bool]:
    n = tr_norm(deger)
    if n in {"evet", "e", "yes", "y", "true", "1", "var", "1.0"}:
        return True
    if n in {"hayir", "h", "no", "n", "false", "0", "0.0"}:
        return False
    return None


# --- GTIN ------------------------------------------------------------------

def gtin_temizle(deger) -> str:
    return re.sub(r"\D", "", metin(deger))


def gtin_kontrol_hanesi(govde: str) -> int:
    toplam = sum(int(r) * (3 if i % 2 == 0 else 1) for i, r in enumerate(reversed(govde)))
    return (10 - toplam % 10) % 10


def gtin_tamamla(govde: str) -> str:
    """Kontrol hanesi olmadan girilen numaraya kontrol hanesini ekler."""
    return govde + str(gtin_kontrol_hanesi(govde))


_YER_TUTUCU = {"0123456789012", "1234567890123", "1234567890128", "01234567890128", "12345678"}


def gtin_dogrula(deger) -> tuple[bool, str]:
    g = gtin_temizle(deger)
    if not g:
        return False, "GTIN girilmemiş"
    if len(g) not in (8, 12, 13, 14):
        return False, f"GTIN {len(g)} hane; 8, 12, 13 veya 14 hane olmalı"
    if len(set(g)) == 1 or g in _YER_TUTUCU:
        return False, "GTIN örnek / yer tutucu bir değer"
    beklenen = gtin_kontrol_hanesi(g[:-1])
    if int(g[-1]) != beklenen:
        return False, f"GTIN kontrol hanesi hatalı (son hane {beklenen} olmalı)"
    return True, "GTIN geçerli"


def gtin14(deger) -> str:
    g = gtin_temizle(deger)
    return g.zfill(14) if g else ""


# --- GTİP ------------------------------------------------------------------

def gtip_temizle(deger) -> str:
    return re.sub(r"\D", "", metin(deger))


def gtip_dogrula(deger) -> tuple[bool, str]:
    g = gtip_temizle(deger)
    if not g:
        return False, "GTİP kodu girilmemiş"
    if len(g) < 6:
        return False, f"GTİP kodu {len(g)} hane; en az 6 hane (HS) olmalı"
    if len(g) > 12:
        return False, "GTİP kodu 12 haneden uzun olamaz"
    fasil = int(g[:2])
    if fasil < 1 or fasil > 97 or fasil == 77:
        return False, f"GTİP faslı ({g[:2]}) geçersiz"
    return True, "GTİP kodu biçimi uygun"


# --- Malzeme bileşimi ------------------------------------------------------

def malzeme_ayristir(deger) -> list[tuple[str, float]]:
    """'Pamuk:95;Elastan:5' veya '%95 Pamuk, %5 Elastan' biçimlerini okur."""
    s = metin(deger)
    if not s:
        return []
    sonuc = []
    for parca in [p for p in re.split(r"[;\n/]+|,(?!\d)", s) if p.strip()]:
        m = re.search(r"(\d+(?:[.,]\d+)?)", parca)
        if not m:
            continue
        oran = float(m.group(1).replace(",", "."))
        ad = (parca[: m.start()] + parca[m.end():]).replace("%", "").replace(":", "").strip(" -=")
        sonuc.append((ad or "Belirtilmemiş", oran))
    return sonuc
