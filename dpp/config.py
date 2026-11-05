"""Ayarlar: önce ortam değişkenleri, sonra Streamlit secrets okunur."""

from __future__ import annotations

import os
from functools import lru_cache


def _secrets() -> dict:
    try:
        import streamlit as st  # yalnızca varsa
        return dict(st.secrets)
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _tum() -> dict:
    return _secrets()


def ayar(anahtar: str, varsayilan=None):
    if anahtar in os.environ:
        return os.environ[anahtar]
    try:
        deger = _tum().get(anahtar)
    except Exception:
        deger = None
    return varsayilan if deger in (None, "") else deger


def veritabani_adresi() -> str:
    """DATABASE_URL tanımlıysa PostgreSQL, değilse yerel SQLite dosyası."""
    return ayar("DATABASE_URL", "sqlite:///data/dpp.db")


def uygulama_adresi() -> str:
    """QR kodların yönlendirileceği uygulama adresi (ör. https://firma-dpp.streamlit.app)."""
    return str(ayar("APP_URL", "http://localhost:8501")).rstrip("/")


def kurulum_anahtari() -> str | None:
    return ayar("KURULUM_ANAHTARI")


def gemini() -> tuple[str | None, str]:
    return ayar("GEMINI_API_KEY"), ayar("GEMINI_MODEL", "gemini-2.5-flash")


def platform_unvani() -> str:
    return ayar("PLATFORM_UNVANI", "DPP Hazırlık Platformu")
