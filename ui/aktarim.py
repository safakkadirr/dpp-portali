"""Excel ile toplu içe aktarım (önizlemeli) ve dışa aktarım."""

from __future__ import annotations

import streamlit as st

from dpp import evaluation, importer
from ui import ortak as o


def sayfa():
    f = o.firma_gerekli()
    db = o.db()
    o.sayfa_basligi("Excel Aktarım", "Ürün, malzeme, parti, tedarik zinciri, belge, tedarikçi ve tesis verilerini toplu yükleyin.")
    a, b = st.columns(2)
    a.download_button("📄 Boş şablonu indir", importer.sablon(), "dpp_veri_sablonu.xlsx",
                      help="Her sütunun açıklaması 'Aciklama' sayfasındadır.")
    if b.download_button("📤 Tüm verimi indir (yeniden yüklenebilir)", importer.disa_aktar(db, f), "dpp_firma_verisi.xlsx"):
        o.kayit("Veri dışa aktarıldı", "firma", f)

    if not o.izin("veri_duzenle"):
        st.caption("İçe aktarım yetkiniz yok.")
        return
    st.divider()
    st.markdown("**Nasıl çalışır?** Dosyayı yükleyin → program kontrol eder ve özet gösterir → **İçe aktar** dediğinizde tek seferde "
                "kaydedilir. Hata olursa hiçbir değişiklik yapılmaz. Mevcut ürünler ürün koduna göre güncellenir; dosyada boş "
                "bırakılan alanlar mevcut veriyi silmez. Önceki sürümün Excel dosyaları da okunur.")
    dosyalar = st.file_uploader("Excel dosyaları", type=["xlsx", "xls"], accept_multiple_files=True, key="aktarim_dosya")
    if not dosyalar:
        return
    onizleme = importer.oku([(d.name, d.getvalue()) for d in dosyalar], db, f)
    for h in onizleme.hatalar:
        st.error(h)
    for u in onizleme.uyarilar:
        st.warning(u)
    sayim = {k: len(v) for k, v in onizleme.sayfalar.items() if not v.empty}
    c = st.columns(4)
    c[0].metric("Yeni ürün", onizleme.yeni_urun)
    c[1].metric("Güncellenecek ürün", onizleme.guncel_urun)
    c[2].metric("Belge satırı", sayim.get("Belgeler", 0))
    c[3].metric("Malzeme satırı", sayim.get("Malzemeler", 0))
    with st.expander("Okunan sayfalar"):
        for ad, df in onizleme.sayfalar.items():
            if not df.empty:
                st.markdown(f"**{ad}** — {len(df)} satır")
                st.dataframe(df.drop(columns=["_kaynak", "_satir"], errors="ignore").head(50).astype(str), hide_index=True)
    if st.button("İçe aktar", type="primary", disabled=not onizleme.gecerli):
        try:
            sonuc = importer.uygula(db, f, onizleme, o.eposta())
            with st.spinner("Ürünler değerlendiriliyor…"):
                evaluation.firma_degerlendir(db, f, o.eposta())
            st.success("İçe aktarım tamamlandı: " + ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in sonuc.items() if v))
        except Exception as h:
            st.error(f"İçe aktarım yapılamadı, hiçbir değişiklik kaydedilmedi: {h}")
