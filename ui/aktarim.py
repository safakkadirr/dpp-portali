"""Excel / CSV ile toplu içe aktarım: akıllı sütun eşleme, düzeltilebilir eşleme tablosu, ayrıntılı özet."""

from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from dpp import esleme, evaluation, importer
from ui import ortak as o

AKTARMA = "— Aktarma"
TUR_ADLARI = {"Urunler": "Ürünler", "Malzemeler": "Malzemeler", "Partiler": "Partiler", "Tedarik_Zinciri": "Tedarik zinciri",
              "Belgeler": "Belgeler", "Tedarikciler": "Tedarikçiler", "Tesisler": "Tesisler",
              "Testler": "Laboratuvar testleri"}


def sayfa():
    f = o.firma_gerekli()
    db = o.db()
    o.sayfa_basligi("Excel Aktarım", "Kendi Excel veya CSV dosyanızı olduğu gibi yükleyin; sütunlar otomatik tanınır.")
    a, b = st.columns(2)
    a.download_button("📄 Önerilen şablonu indir (isteğe bağlı)", importer.sablon(), "dpp_veri_sablonu.xlsx",
                      help="Şablon kullanmak zorunlu değildir; en kapsamlı veri yapısını görmek için faydalıdır.")
    if b.download_button("📤 Tüm verimi indir (yeniden yüklenebilir)", importer.disa_aktar(db, f), "dpp_firma_verisi.xlsx"):
        o.kayit("Veri dışa aktarıldı", "firma", f)

    if not o.izin("veri_duzenle"):
        st.caption("İçe aktarım yetkiniz yok.")
        return
    st.divider()
    with st.expander("Nasıl çalışır?", expanded=False):
        st.markdown(
            "- Sütun başlıkları büyük/küçük harf, boşluk ve Türkçe karakter farkı gözetilmeden tanınır: *Model, Model Kodu, "
            "Stok Kodu, Artikel, SKU, Item code* → **Ürün kodu**; *Bileşen, Kumaş İçeriği, Composition* → **Malzeme bileşimi** gibi.\n"
            "- Başlık satırı dosyanın ilk satırında olmak zorunda değildir; rapor başlıkları ve boş satırlar atlanır.\n"
            "- Birden fazla sayfa varsa (ürünler, kompozisyon, sertifikalar, lotlar) her sayfanın türü kendiliğinden anlaşılır.\n"
            "- *'%95 Pamuk %5 Elastan'*, *'95% Cotton 5% Elastane'*, *'Pamuk:95;Elastan:5'* gibi tek hücredeki bileşimler ayrıştırılır; "
            "*'GOTS, OEKO-TEX'* gibi tek hücredeki sertifikalar ayrı belgelere dönüşür.\n"
            "- Maliyet, fiyat, stok gibi DPP dışı sütunlar aktarılmaz.\n"
            "- Ürün kodu yoksa barkod, o da yoksa ürün adından kod üretilir. Sektör GTİP kodundan veya ürün adından tahmin edilir.\n"
            "- **SVHC beyanı ve menşe gibi yasal beyanlara varsayılan değer atanmaz**; eksikse değerlendirmede görünür.\n"
            "- Hatalı bir satır yalnızca kendisini etkiler; diğerleri aktarılır, atlananlar nedenleriyle listelenir.\n"
            "- Aynı dosyayı tekrar yüklemek ürünleri çoğaltmaz, günceller.")
    dosyalar = st.file_uploader("Excel veya CSV dosyaları", type=["xlsx", "xls", "csv"], accept_multiple_files=True, key="aktarim_dosya")
    if not dosyalar:
        return
    icerikler = [(d.name, d.getvalue()) for d in dosyalar]
    imza = hashlib.sha256(b"".join(n.encode() + c for n, c in icerikler)).hexdigest()[:16]
    if st.session_state.get("aktarim_imza") != imza:
        st.session_state["aktarim_imza"] = imza
        st.session_state["aktarim_elle"] = {}
        st.session_state["aktarim_tur"] = {}
        st.session_state.pop("aktarim_sonuc", None)
    elle = st.session_state["aktarim_elle"]
    elle_tur = st.session_state["aktarim_tur"]

    onizleme = importer.oku(icerikler, db, f, elle, elle_tur)

    for h in onizleme.hatalar:
        st.error(h)
    c = st.columns(4)
    c[0].metric("Yeni ürün", onizleme.yeni_urun)
    c[1].metric("Güncellenecek ürün", onizleme.guncel_urun)
    c[2].metric("Tanınan sütun", sum(1 for r in onizleme.esleme_raporu if r["Alan"]))
    c[3].metric("Atlanacak satır", len(onizleme.atlanacak))

    # --- Eşleme tablosu (düzeltilebilir) -----------------------------------------
    st.subheader("Sütun eşlemesi")
    st.caption("Program sütunları aşağıdaki gibi tanıdı. Yanlış veya boş kalan bir eşleme varsa 'Eşlenen alan' sütunundan "
               "düzeltin; tablo kendiliğinden güncellenir.")
    degisti = False
    for s in onizleme.sayfa_raporu:
        anahtar = s["anahtar"]
        tur_secenek = ["(atla)"] + [TUR_ADLARI[t] for t in TUR_ADLARI]
        mevcut_tur = TUR_ADLARI.get(s["Tür"], "(atla)")
        with st.expander(f"📄 {s['Dosya']} › {s['Sayfa']} — {mevcut_tur} · {s['Satır']} satır · başlık {s['Başlık satırı']}. satırda",
                         expanded=True):
            secilen_tur = st.selectbox("Bu sayfanın içeriği", tur_secenek, index=tur_secenek.index(mevcut_tur), key=f"tur_{imza}_{anahtar}")
            if secilen_tur != mevcut_tur:
                ters = {v: k for k, v in TUR_ADLARI.items()}
                elle_tur[anahtar] = ters.get(secilen_tur, esleme.YOK_SAY)
                degisti = True
            if s["Not"]:
                st.caption(s["Not"])
            if not s["Tür"]:
                continue
            alanlar = esleme.ALANLAR[s["Tür"]]
            secenekler = [AKTARMA] + [e for _, e, _ in alanlar]
            etiket_kanonik = {e: k for k, e, _ in alanlar}
            satirlar = [r for r in onizleme.esleme_raporu if r["anahtar"].startswith(anahtar + "|")]
            df = pd.DataFrame([{"Excel sütunu": r["Excel sütunu"], "Örnek değer": r["Örnek değer"],
                                "Eşlenen alan": r["Eşlenen alan"] if r["Alan"] else AKTARMA,
                                "Durum": (f"✅ %{r['Güven']} · {r['Yöntem']}" if r["Alan"] else r["Eşlenen alan"].replace("— ", ""))}
                               for r in satirlar])
            duz = st.data_editor(df, hide_index=True, key=f"esle_{imza}_{anahtar}_{s['Tür']}", disabled=["Excel sütunu", "Örnek değer", "Durum"],
                                 column_config={"Eşlenen alan": st.column_config.SelectboxColumn("Eşlenen alan", options=secenekler,
                                                                                                 required=True)})
            for eski, yeni in zip(df.to_dict("records"), duz.to_dict("records")):
                if eski["Eşlenen alan"] != yeni["Eşlenen alan"]:
                    elle[f"{anahtar}|{eski['Excel sütunu']}"] = etiket_kanonik.get(yeni["Eşlenen alan"], esleme.YOK_SAY)
                    degisti = True
    if degisti:
        st.rerun()

    # --- Kontrol sonuçları -------------------------------------------------------
    if onizleme.uyarilar or onizleme.varsayilanlar or onizleme.atlanacak:
        st.subheader("Kontrol sonuçları")
        for u in onizleme.uyarilar:
            st.warning(u)
        for v in onizleme.varsayilanlar:
            st.info(v)
        if onizleme.atlanacak:
            st.markdown("**Atlanacak satırlar**")
            st.dataframe(pd.DataFrame(onizleme.atlanacak), hide_index=True)

    with st.expander("Aktarılacak verinin önizlemesi"):
        for ad, df in onizleme.sayfalar.items():
            if not df.empty:
                st.markdown(f"**{TUR_ADLARI.get(ad, ad)}** — {len(df)} satır")
                st.dataframe(df.drop(columns=["_kaynak", "_satir"], errors="ignore").head(50).astype(str), hide_index=True)

    nota = st.checkbox("Tanınmayan sütunları ürün notlarına ekle", value=False,
                       help="Örneğin 'Sezon' gibi platformda karşılığı olmayan bilgiler ürünün iç notlarında saklanır; pasaportta görünmez.")
    if st.button("İçe aktar", type="primary", disabled=not onizleme.gecerli):
        try:
            sonuc = importer.uygula(db, f, onizleme, o.eposta(), bilinmeyenleri_nota=nota)
            with st.spinner("Ürünler değerlendiriliyor…"):
                evaluation.firma_degerlendir(db, f, o.eposta())
            st.session_state["aktarim_sonuc"] = sonuc
        except Exception as h:
            st.error(f"İçe aktarım yapılamadı, hiçbir değişiklik kaydedilmedi: {h}")

    sonuc = st.session_state.get("aktarim_sonuc")
    if sonuc:
        st.subheader("Aktarım özeti")
        (st.success if not sonuc.atlanan else st.warning)(
            f"Aktarıldı: {sonuc.ozet()}." + (f" {len(sonuc.atlanan)} satır atlandı (aşağıda)." if sonuc.atlanan else ""))
        for n in sonuc.notlar:
            st.info(n)
        if sonuc.atlanan:
            st.dataframe(pd.DataFrame(sonuc.atlanan), hide_index=True)
        st.caption("Ürünler yeniden değerlendirildi. Eksikleri **Eksikler ve Çözüm** ekranında görebilirsiniz.")
