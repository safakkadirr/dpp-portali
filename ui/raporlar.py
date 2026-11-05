"""Raporlar, eksikler ve çözüm listesi."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dpp import evaluation, reports, repo
from dpp.catalog import SEKTOR_ADLARI
from dpp.rules import SEVIYE_SIRA
from ui import ortak as o


def eksikler_sayfasi():
    f = o.firma_gerekli()
    db = o.db()
    o.sayfa_basligi("Eksikler ve Çözüm", "Tüm ürünlerdeki eksikler, önceliğe göre sıralı. Her satırda mevzuat dayanağı ve yapılacaklar.")
    bulgular = [b for b in evaluation.firma_bulgulari(db, f) if b["sonuc"] == "Eksik"]
    if not bulgular:
        st.success("Eksik bulunmadı.")
        return
    a, b, c = st.columns(3)
    sinif = a.multiselect("Sınıf", ["Yasal", "Yaklaşan yükümlülük", "DPP", "İyi uygulama"], default=["Yasal", "Yaklaşan yükümlülük"])
    seviye = b.multiselect("Seviye", ["Kritik", "Yüksek", "Orta", "Bilgi"])
    gorunum = c.radio("Görünüm", ["Kurala göre", "Ürüne göre"], horizontal=True)
    liste = [x for x in bulgular if (not sinif or x["sinif"] in sinif) and (not seviye or x["seviye"] in seviye)]
    sira = {"Yasal": 0, "Yaklaşan yükümlülük": 1, "DPP": 2, "İyi uygulama": 3}
    liste.sort(key=lambda x: (sira[x["sinif"]], SEVIYE_SIRA[x["seviye"]], x["kural_kodu"], x["urun_kodu"]))
    if gorunum == "Kurala göre":
        gruplar: dict[str, list] = {}
        for x in liste:
            gruplar.setdefault(x["kural_kodu"], []).append(x)
        for kod, g in gruplar.items():
            x = g[0]
            with st.expander(f"{o.SEVIYE_SIMGE[x['seviye']]} [{kod}] {x['kural']} — {x['sinif']} · {len(g)} ürün"):
                st.markdown(f"**Dayanak:** {x['dayanak']}")
                st.markdown("**Yapılacaklar:**\n" + "\n".join(f"{i}. {a_}" for i, a_ in enumerate(x["recete"], 1)))
                st.dataframe(pd.DataFrame([{"Ürün": y["urun_kodu"], "Ad": y["urun_adi"], "Tespit": y["detay"]} for y in g]), hide_index=True)
    else:
        st.dataframe(pd.DataFrame([{" ": o.SEVIYE_SIMGE[x["seviye"]], "Ürün": x["urun_kodu"], "Sektör": SEKTOR_ADLARI.get(x["sektor_kodu"]),
                                    "Kural": f"{x['kural_kodu']} {x['kural']}", "Sınıf": x["sinif"], "Tespit": x["detay"],
                                    "İlk adım": x["recete"][0] if x["recete"] else ""} for x in liste]), hide_index=True)


def raporlar_sayfasi():
    f = o.firma_gerekli()
    o.izin_gerekli("rapor_al")
    db = o.db()
    o.sayfa_basligi("Raporlar")
    urunler = repo.urunler(db, f)
    st.subheader("DPP Hazırlık ve Ön Kontrol Raporu (PDF)")
    st.caption("Kapak, özet bulgular, ürün bazında sonuçlar, yasal eksikler ve çözüm önerileri, belge durumu, yaklaşan yükümlülükler "
               "ve bağımsız doğrulama bölümlerini içerir. Müşteriye veya yönetime sunulabilir.")
    a, b = st.columns(2)
    hazirlayan = a.text_input("Hazırlayan", o.ad())
    rapor_no = b.text_input("Rapor no (boşsa otomatik)")
    secim = st.multiselect("Kapsam (boşsa tüm ürünler)", [f"{u['urun_kodu']} — {u['ad']}" for u in urunler])
    idler = [u["id"] for u in urunler if f"{u['urun_kodu']} — {u['ad']}" in secim] or None
    if st.button("PDF raporu oluştur", type="primary"):
        with st.spinner("Rapor hazırlanıyor…"):
            st.session_state["pdf_rapor"] = reports.pdf_hazirlik_raporu(db, f, hazirlayan, rapor_no, idler)
        o.kayit("PDF rapor oluşturuldu", "firma", f, f"{len(idler or urunler)} ürün")
    if st.session_state.get("pdf_rapor"):
        st.download_button("📥 PDF raporu indir", st.session_state["pdf_rapor"], "dpp_hazirlik_raporu.pdf", mime="application/pdf")
    st.divider()
    st.subheader("Ayrıntılı Excel raporu")
    st.caption("Özet, eksikler ve çözüm adımları, tüm kontroller, belgeler ve kural seti sayfaları.")
    if st.download_button("📥 Excel raporu indir", reports.excel_rapor(db, f, o.ad()), "dpp_on_kontrol_raporu.xlsx"):
        o.kayit("Excel rapor indirildi", "firma", f)
