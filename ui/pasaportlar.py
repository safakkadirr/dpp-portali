"""Pasaport yönetimi: yayımlanan sürümler, QR kod, PDF etiket, geri çekme."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from dpp import config, passport, reports
from ui import ortak as o
from ui.kamu import _qr


def sayfa():
    f = o.firma_gerekli()
    db = o.db()
    o.sayfa_basligi("Pasaportlar", "Yayımlanan dijital ürün pasaportları. QR kod her zaman ürünün en güncel sürümüne yönlendirir.")
    liste = passport.pasaportlar(db, f)
    if not liste:
        st.info("Henüz yayımlanmış pasaport yok. Ürün kartındaki **Pasaport** sekmesinden yayımlayabilirsiniz "
                "(kritik yasal eksiği olan ürünler yayımlanamaz).")
        return
    st.dataframe(pd.DataFrame([{
        "Ürün": p["urun_kodu"], "Ad": p["urun_adi"], "Düzey": f"Parti {p['parti_no']}" if p["parti_no"] else "Model",
        "Sürüm": p["surum"], "Durum": p["durum"], "Yasal uyum": p["yasal_durum"], "DPP hazırlık": p["hazirlik_skoru"],
        "Yayımlayan": p["yayimlayan"], "Yayım": o.tarih_tr(p["yayim_tarihi"]), "Kural seti": p["kural_seti"],
    } for p in liste]), hide_index=True)

    yayinda = {f"{p['urun_kodu']} — {p['urun_adi']} · {'Parti ' + p['parti_no'] if p['parti_no'] else 'Model'} · v{p['surum']}": p
               for p in liste if p["durum"] == "Yayında"}
    if not yayinda:
        return
    st.subheader("Pasaport ayrıntısı")
    p = yayinda[st.selectbox("Pasaport", list(yayinda))]
    kayit = passport.kamu_kaydi(db, p["genel_kimlik"])
    adres = kayit["icerik"].get("@id") or f"{config.uygulama_adresi()}/?p={p['genel_kimlik']}"
    uygulama_adresi = f"{config.uygulama_adresi()}/?p={p['genel_kimlik']}"
    a, b = st.columns([1, 3])
    with a:
        _qr(adres, 180)
    with b:
        st.markdown(f"**QR adresi:** `{adres}`")
        if adres != uygulama_adresi:
            st.caption(f"Kendi alan adınız kullanılıyor. Bu adresin `{uygulama_adresi}` adresine yönlendirilmesi gerekir.")
        st.markdown(f"**Herkese açık görünüm:** [{uygulama_adresi}]({uygulama_adresi})")
        if o.izin("pasaport_yayimla") or o.rol() in ("denetci", "platform_yonetici"):
            st.markdown(f"**Alıcı (B2B) erişim kodu:** `{p['alici_kodu']}` — yalnızca müşterilerinizle paylaşın.")
        st.caption(f"İçerik özeti: `{p['icerik_ozeti']}` · bütünlük: {'✅' if kayit['ozet_dogru'] else '⚠️'}")
    seviye = st.radio("İndirme görünümü", passport.ERISIM_SEVIYELERI, horizontal=True)
    icerik = passport.gorunum(kayit["icerik"], seviye)
    c1, c2, c3 = st.columns(3)
    c1.download_button("PDF pasaport sayfası", reports.pdf_pasaport(icerik, adres, seviye), f"{p['urun_kodu']}_pasaport.pdf",
                       mime="application/pdf")
    c2.download_button("JSON-LD", json.dumps(icerik, ensure_ascii=False, indent=2), f"{p['urun_kodu']}_v{p['surum']}.jsonld",
                       mime="application/ld+json")
    png = reports.qr_png(adres)
    if png:
        c3.download_button("QR kod (PNG)", png, f"{p['urun_kodu']}_qr.png", mime="image/png")
    else:
        c3.download_button("QR kod (SVG)", reports.qr_svg(adres, 400), f"{p['urun_kodu']}_qr.svg", mime="image/svg+xml")

    if o.izin("pasaport_yayimla"):
        with st.expander("Pasaportu geri çek"):
            st.caption("Geri çekilen pasaportun QR adresi açılmaya devam eder ve 'geri çekildi' uyarısı gösterir.")
            neden = st.text_input("Geri çekme nedeni", key=f"gc_{p['id']}")
            if st.button("Geri çek", key=f"gcb_{p['id']}"):
                try:
                    passport.geri_cek(db, f, p["id"], neden, o.eposta())
                    st.rerun()
                except ValueError as h:
                    st.error(str(h))
