"""Gösterge paneli."""

from __future__ import annotations

from collections import Counter

import pandas as pd
import streamlit as st

from dpp import evaluation, repo
from dpp.catalog import SEKTOR_ADLARI
from dpp.rules import DURUMLAR, KURAL, yaklasan_yukumlulukler
from ui import ortak as o


def sayfa():
    f = o.firma_gerekli()
    db = o.db()
    o.kalicilik_uyarisi()
    if evaluation.guncel_degil_mi(db, f):
        with st.spinner("Değerlendirmeler güncelleniyor…"):
            evaluation.firma_degerlendir(db, f, "sistem (günlük güncelleme)")
    firma = repo.firma(db, f)
    urunler = repo.urunler(db, f)
    belgeler = repo.belgeler(db, f)
    o.sayfa_basligi(f"Gösterge paneli — {firma['unvan']}", f"Hoş geldiniz, {o.ad()}.")

    if not urunler:
        st.info("Henüz ürün yok. **Ürünler** ekranından ekleyin veya **Excel Aktarım** ile toplu yükleyin.")
        return

    sayim = Counter(u["genel_durum"] for u in urunler)
    skorlar = [u["hazirlik_skoru"] for u in urunler if u["hazirlik_skoru"] is not None]
    m = st.columns(6)
    m[0].metric("Ürün", len(urunler))
    for i, d in enumerate(DURUMLAR, 1):
        m[i].metric(o.durum_metni(d), sayim.get(d, 0))
    m[5].metric("Ortalama DPP hazırlığı", f"%{sum(skorlar) / len(skorlar):.0f}" if skorlar else "—")
    st.caption("🔴 Kritik yasal eksik · 🟠 Kritik olmayan yasal eksik · 🟡 Yasal olarak uygun, DPP hazırlığı %80 altında · "
               "🟢 Yasal olarak uygun ve DPP hazırlığı %80 ve üzeri")

    sol, sag = st.columns([3, 2])
    with sol:
        st.subheader("Öncelikli işler")
        bulgular = evaluation.firma_bulgulari(db, f)
        isler = []
        for u in urunler:
            if u["genel_durum"] in DURUMLAR[:2]:
                kritik = [b for b in bulgular if b["urun_id"] == u["id"] and b["sonuc"] == "Eksik" and b["sinif"] == "Yasal"]
                for b in kritik[:3]:
                    isler.append({" ": o.SEVIYE_SIMGE[b["seviye"]], "Ürün": u["urun_kodu"], "İş": b["kural"], "Tespit": b["detay"]})
        for b in belgeler:
            if b["durum"] in ("Süresi dolmuş", "30 gün içinde doluyor"):
                isler.append({" ": "📄", "Ürün": ", ".join(x["hedef_adi"] or "" for x in b["baglantilar"])[:40],
                              "İş": f"Belge yenile: {b['tur_serbest'] or b['tur_kodu']}", "Tespit": f"{b['durum']} ({o.tarih_tr(b['bitis'])})"})
        if isler:
            st.dataframe(pd.DataFrame(isler[:25]), hide_index=True)
        else:
            st.success("Yasal eksik veya süresi dolan belge yok.")

        st.subheader("Sektöre göre durum")
        df = pd.DataFrame([{"Sektör": SEKTOR_ADLARI.get(u["sektor_kodu"]), "Durum": u["genel_durum"]} for u in urunler])
        tablo = pd.crosstab(df["Sektör"], df["Durum"])
        renk = {"Kritik eksik": "#D92D20", "Yasal eksik": "#F79009", "Hazırlık sürüyor": "#FDB022", "Hazır": "#12B76A"}
        kolonlar = [d for d in DURUMLAR if d in tablo.columns]
        st.bar_chart(tablo[kolonlar], color=[renk[k] for k in kolonlar], horizontal=True)
    with sag:
        st.subheader("Yaklaşan yükümlülükler")
        yk = yaklasan_yukumlulukler()
        etkilenen = Counter(b["kural_kodu"] for b in bulgular if b["sinif"] == "Yaklaşan yükümlülük" and b["sonuc"] == "Eksik")
        if yk:
            for k in yk:
                n = etkilenen.get(k.kod, 0)
                st.markdown(f"**{k.zorunlu_tarih:%d.%m.%Y}** — {k.ad}  \n<span class='dpp-kucuk'>{k.kapsam} · "
                            f"{'⚠️ ' + str(n) + ' ürününüzde eksik' if n else 'ürünlerinizde eksik yok'}</span>",
                            unsafe_allow_html=True)
        else:
            st.caption("12 ay içinde yürürlüğe girecek izlenen yükümlülük yok.")
        st.subheader("Belgeler")
        bs = Counter(b["durum"] for b in belgeler)
        ds = Counter(b["dogrulama_durumu"] for b in belgeler)
        st.markdown("\n".join(f"- {o.BELGE_SIMGE[k]} {k}: **{bs.get(k, 0)}**" for k in o.BELGE_SIMGE))
        st.markdown(f"Doğrulama: ✅ {ds.get('Doğrulandı', 0)} · ⏳ {ds.get('Beklemede', 0)} · ⛔ {ds.get('Reddedildi', 0)}")
        st.subheader("En sık eksikler")
        sik = Counter(b["kural_kodu"] for b in bulgular if b["sonuc"] == "Eksik").most_common(5)
        st.markdown("\n".join(f"- {KURAL[k].ad} — **{n}** ürün" for k, n in sik) or "—")
