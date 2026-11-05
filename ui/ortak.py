"""Arayüz ortak yardımcıları: veritabanı, oturum, yetki, biçim."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from dpp import audit, config, security
from dpp.db import Veritabani
from dpp.rules import DURUM_HAZIR, DURUM_KRITIK, DURUM_SURUYOR, DURUM_YASAL

OTURUM_SURESI = timedelta(hours=8)

DURUM_SIMGE = {DURUM_KRITIK: "🔴", DURUM_YASAL: "🟠", DURUM_SURUYOR: "🟡", DURUM_HAZIR: "🟢", None: "⚪"}
DURUM_RENK = {DURUM_KRITIK: "red", DURUM_YASAL: "orange", DURUM_SURUYOR: "orange", DURUM_HAZIR: "green"}
SEVIYE_SIMGE = {"Kritik": "🔴", "Yüksek": "🟠", "Orta": "🟡", "Bilgi": "🔵"}
BELGE_SIMGE = {"Geçerli": "🟢", "60 gün içinde doluyor": "🟡", "30 gün içinde doluyor": "🟠", "Süresi dolmuş": "🔴",
               "Bitiş tarihi yok": "⚪"}
DOGRULAMA_SIMGE = {"Doğrulandı": "✅", "Beklemede": "⏳", "Reddedildi": "⛔"}

UYARI = ("Bu platform bir **hazırlık ve ön kontrol** aracıdır; gümrük, piyasa gözetimi veya onaylanmış kuruluş kararı "
         "yerine geçmez. Mevzuat hükümleri ve tarihleri resmi kaynaklardan doğrulanmalıdır.")

CSS = """
<style>
.block-container {padding-top: 2rem; max-width: 1400px;}
[data-testid="stMetric"] {background: var(--secondary-background-color); border-radius: 10px; padding: 12px 16px;}
[data-testid="stMetricLabel"] p {font-size: 0.85rem;}
.dpp-kart {border: 1px solid rgba(128,128,128,.25); border-radius: 12px; padding: 16px 20px; margin-bottom: 12px;}
.dpp-etiket {display:inline-block; padding: 2px 10px; border-radius: 999px; font-size: .8rem; font-weight: 600;
             background: rgba(31,58,95,.08); color: inherit; margin-right: 6px;}
.dpp-kucuk {font-size: .85rem; opacity: .75;}
</style>
"""


@st.cache_resource(show_spinner=False)
def _veritabani(adres: str) -> Veritabani:
    db = Veritabani(adres)
    db.sema_olustur()
    return db


def db() -> Veritabani:
    return _veritabani(config.veritabani_adresi())


# ---------------------------------------------------------------------------
# Oturum
# ---------------------------------------------------------------------------

def kullanici() -> dict | None:
    k = st.session_state.get("kullanici")
    if not k:
        return None
    son = st.session_state.get("son_aktivite")
    if son and datetime.now() - son > OTURUM_SURESI:
        cikis("Oturum süresi doldu, lütfen yeniden giriş yapın.")
        return None
    st.session_state["son_aktivite"] = datetime.now()
    return k


def giris_yap(k: dict):
    st.session_state["kullanici"] = k
    st.session_state["son_aktivite"] = datetime.now()
    st.session_state["aktif_firma"] = k.get("firma_id")
    audit.kaydet(db(), k.get("firma_id"), k["eposta"], "Giriş", "kullanici", k["id"])


def cikis(mesaj: str | None = None):
    k = st.session_state.get("kullanici")
    if k:
        try:
            audit.kaydet(db(), k.get("firma_id"), k["eposta"], "Çıkış", "kullanici", k["id"])
        except Exception:
            pass
    for anahtar in list(st.session_state.keys()):
        del st.session_state[anahtar]
    if mesaj:
        st.session_state["bilgi_mesaji"] = mesaj


def rol() -> str:
    k = st.session_state.get("kullanici") or {}
    return k.get("rol", "")


def eposta() -> str:
    k = st.session_state.get("kullanici") or {}
    return k.get("eposta", "")


def ad() -> str:
    k = st.session_state.get("kullanici") or {}
    return k.get("ad_soyad", "")


def platform_yoneticisi() -> bool:
    return rol() == "platform_yonetici"


def firma_id() -> int | None:
    return st.session_state.get("aktif_firma")


def izin(eylem: str) -> bool:
    return security.yetkili(rol(), eylem)


def izin_gerekli(eylem: str):
    if not izin(eylem):
        st.warning("Bu işlem için yetkiniz yok.")
        st.stop()


def firma_gerekli() -> int:
    f = firma_id()
    if not f:
        st.info("Çalışmak için sol menüden bir firma seçin." if platform_yoneticisi() else "Hesabınız bir firmaya bağlı değil.")
        st.stop()
    return f


def kayit(islem: str, varlik: str = "", varlik_id=None, detay: str = ""):
    audit.kaydet(db(), firma_id(), eposta(), islem, varlik, varlik_id, detay)


# ---------------------------------------------------------------------------
# Biçim
# ---------------------------------------------------------------------------

def durum_metni(durum: str | None) -> str:
    return f"{DURUM_SIMGE.get(durum, '⚪')} {durum or 'Değerlendirilmedi'}"


def tarih_tr(deger) -> str:
    if not deger:
        return "—"
    s = str(deger)
    try:
        if len(s) > 10:
            return datetime.fromisoformat(s[:19]).strftime("%d.%m.%Y %H:%M")
        return datetime.fromisoformat(s[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return s


def tablo(satirlar: list[dict], kolonlar: dict[str, str] | None = None) -> pd.DataFrame:
    df = pd.DataFrame(satirlar)
    if kolonlar:
        mevcut = [k for k in kolonlar if k in df.columns]
        df = df[mevcut].rename(columns=kolonlar) if mevcut else pd.DataFrame(columns=list(kolonlar.values()))
    return df


def sayfa_basligi(baslik: str, alt: str = ""):
    st.title(baslik)
    if alt:
        st.caption(alt)


def kalicilik_uyarisi():
    if not db().kalici and platform_yoneticisi():
        st.warning("Veritabanı olarak yerel SQLite kullanılıyor. Streamlit Community Cloud yeniden başlatıldığında veriler "
                   "silinir. Canlı kullanım için **DATABASE_URL** ile PostgreSQL bağlayın (README › Kurulum).", icon="⚠️")
