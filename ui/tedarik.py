"""Tedarikçiler, tesisler ve tedarikçi veri talepleri."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dpp import repo
from ui import ortak as o


def sayfa():
    f = o.firma_gerekli()
    o.sayfa_basligi("Tedarik Zinciri", "Tedarikçiler ve üretim tesisleri. Tedarikçilerden bilgi ve belge toplamak için "
                                       "Tedarikçi Portalı ekranını kullanın.")
    s = st.tabs(["Tedarikçiler", "Tesisler"])
    with s[0]:
        _tablo_ekrani(f, "tedarikciler", repo.TEDARIKCI_ALANLARI, "unvan",
                      {"unvan": "Unvan *", "ulke": "Ülke", "eposta": "E-posta", "yetkili": "Yetkili", "kimlik_no": "Vergi no / GLN",
                       "notlar": "Not"}, repo.tedarikciler(o.db(), f))
    with s[1]:
        _tablo_ekrani(f, "tesisler", repo.TESIS_ALANLARI, "ad",
                      {"ad": "Tesis adı *", "adres": "Adres", "ulke": "Ülke", "gln": "GLN", "tur": "Tür", "notlar": "Not"},
                      repo.tesisler(o.db(), f))


def _tablo_ekrani(f, tablo, alanlar, anahtar, etiketler, satirlar):
    duzenle = o.izin("veri_duzenle")
    df = pd.DataFrame(satirlar, columns=["id"] + alanlar)
    cfg = {k: v for k, v in etiketler.items()}
    cfg["id"] = st.column_config.NumberColumn("No", disabled=True)
    duz = st.data_editor(df, num_rows="dynamic" if duzenle else "fixed", hide_index=True, disabled=not duzenle,
                         column_config=cfg, key=f"ed_{tablo}_{st.session_state.get('ted_sayac', 0)}")
    st.caption("Satır silmek bu ekranda desteklenmez; kayıtlar ürün ve belge geçmişinde kullanıldığı için korunur.")
    if duzenle and st.button("Kaydet", type="primary", key=f"kaydet_{tablo}"):
        try:
            e, g = repo.tablo_kaydet(o.db(), tablo, alanlar, f, duz.to_dict("records"), o.eposta(), anahtar)
            st.session_state["ted_sayac"] = st.session_state.get("ted_sayac", 0) + 1
            st.toast(f"{e} kayıt eklendi, {g} kayıt güncellendi.", icon="✅")
            st.rerun()
        except Exception as h:
            st.error(f"Kaydedilemedi: {h}")
