"""Giriş gerektirmeyen sayfalar: herkese açık pasaport ve tedarikçi veri portalı."""

from __future__ import annotations

import streamlit as st

from dpp import config, passport, reports, suppliers
from dpp.catalog import BELGE, BELGE_TURLERI
from ui import ortak as o


def _qr(adres: str, genislik: int = 170):
    png = reports.qr_png(adres)
    if png:
        st.image(png, width=genislik)
    else:
        svg = reports.qr_svg(adres, genislik)
        st.markdown(svg[svg.find("<svg"):], unsafe_allow_html=True)


def pasaport_sayfasi(genel_kimlik: str, kod: str | None):
    kayit = passport.kamu_kaydi(o.db(), genel_kimlik)
    if not kayit:
        st.error("Pasaport bulunamadı. QR kod veya bağlantı hatalı olabilir.")
        return
    seviye = passport.erisim_seviyesi(kayit, kod)
    icerik = passport.gorunum(kayit["icerik"], seviye)
    st.caption("DİJİTAL ÜRÜN PASAPORTU")
    if kayit["durum"] == "Geri çekildi":
        st.error(f"Bu pasaport {o.tarih_tr(kayit.get('geri_cekme_tarihi'))} tarihinde üretici tarafından geri çekilmiştir. "
                 f"Neden: {kayit.get('geri_cekme_nedeni') or '—'}")
    sol, sag = st.columns([4, 1])
    with sol:
        st.title(icerik.get("name", "—"))
        st.markdown(f"**{icerik.get('manufacturer', {}).get('name', '')}** · {icerik.get('category', '')}")
        st.caption(f"Pasaport: {icerik.get('dpp:pasaportKimligi')} · Sürüm {icerik.get('dpp:surum')} · "
                   f"Yayım: {o.tarih_tr(kayit.get('yayim_tarihi'))} · Görünüm: {seviye}")
    with sag:
        _qr(icerik.get("@id") or f"{config.uygulama_adresi()}/?p={genel_kimlik}", 150)

    dog = icerik.get("dpp:bagimsizDogrulama")
    if dog:
        metin = (f"**Bağımsız doğrulama:** {dog.get('sonuc')} — {dog.get('dogrulayan')} {dog.get('unvan') or ''}, "
                 f"{o.tarih_tr(dog.get('tarih'))}")
        (st.success if dog.get("sonuc") == "Doğrulandı" and dog.get("guncel") else st.info)(
            metin + ("" if dog.get("guncel") else " · Doğrulamadan sonra veri güncellenmiştir."))

    def satirlar(liste):
        return [{"Alan": a, "Değer": str(b)} for a, b in liste if b not in (None, "", [], {})]

    sek = st.tabs(["Ürün", "Malzeme ve kimyasallar", "Çevre", "Kullanım ve ömür sonu", "Belgeler"]
                  + (["Tedarik zinciri"] if icerik.get("dpp:tedarikZinciri") else []))
    with sek[0]:
        st.dataframe(o.tablo(satirlar([
            ("Ürün kodu", icerik.get("sku")), ("GTIN", icerik.get("gtin")), ("Marka", icerik.get("brand")),
            ("Üretim ülkesi", icerik.get("countryOfOrigin")), ("AB sorumlu ekonomik operatör", icerik.get("dpp:abSorumluOperator")),
            ("Parti / lot", icerik.get("dpp:partiNo")), ("Üretim tarihi", icerik.get("dpp:uretimTarihi")),
            ("GTİP", icerik.get("dpp:gtip")), ("Üretim tesisi", (icerik.get("dpp:uretimTesisi") or {}).get("ad")),
            ("Üretici iletişim", icerik.get("manufacturer", {}).get("email"))])), hide_index=True)
    with sek[1]:
        if icerik.get("material"):
            st.dataframe(o.tablo([{"Malzeme": m.get("name"), "Oran (%)": m.get("dpp:oranYuzde"), "Menşe": m.get("dpp:mense"),
                                   "Geri dönüştürülmüş": "Evet" if m.get("dpp:geriDonusturulmus") else "Hayır"}
                                  for m in icerik["material"]]), hide_index=True)
        svhc = icerik.get("dpp:svhc", {})
        st.markdown(f"**Endişe verici maddeler (SVHC, %0,1 eşiği):** {svhc.get('beyan', '—')} {svhc.get('maddeler', '')}")
        if icerik.get("dpp:geriDonusturulmusIcerikYuzde") is not None:
            st.markdown(f"**Geri dönüştürülmüş içerik:** %{icerik['dpp:geriDonusturulmusIcerikYuzde']:g}")
    with sek[2]:
        c = icerik.get("dpp:cevre", {})
        st.dataframe(o.tablo(satirlar([("Çevresel iddia", c.get("iddia")),
                                       ("Karbon ayak izi (kg CO2e / birim)", c.get("karbonAyakIziKgCO2e")),
                                       ("Hesaplama yöntemi", c.get("yontem")),
                                       ("Gömülü emisyon (tCO2e / t)", icerik.get("dpp:gomuluEmisyon"))])), hide_index=True)
    with sek[3]:
        k = icerik.get("dpp:kullanim", {})
        st.markdown(f"**Bakım ve onarım:** {k.get('bakimOnarim', '—')}")
        st.markdown(f"**Ömür sonu:** {k.get('omurSonu', '—')}")
        b = icerik.get("dpp:batarya", {})
        if b:
            st.markdown(f"**Batarya:** {b.get('kategori', '')} · {b.get('kimya', '')} · {b.get('kapasiteKWh', '')} kWh")
    with sek[4]:
        if icerik.get("dpp:belgeler"):
            st.dataframe(o.tablo(icerik["dpp:belgeler"], {"tur": "Belge", "kategori": "Kategori", "no": "No", "duzenleyen": "Düzenleyen",
                                                         "gecerlilikBitis": "Geçerlilik", "durum": "Durum", "dogrulama": "Doğrulama"}),
                         hide_index=True)
        else:
            st.caption("Belge bilgisi yok.")
    if icerik.get("dpp:tedarikZinciri"):
        with sek[5]:
            st.dataframe(o.tablo(icerik["dpp:tedarikZinciri"], {"sira": "Sıra", "asama": "Aşama", "tedarikci": "Tedarikçi", "ulke": "Ülke"}),
                         hide_index=True)

    st.divider()
    if seviye == "Kamu":
        with st.expander("Alıcı (B2B) erişimi"):
            with st.form("alici"):
                girilen = st.text_input("Alıcı erişim kodu", type="password")
                if st.form_submit_button("Göster"):
                    st.query_params["k"] = girilen
                    st.rerun()
    c1, c2 = st.columns(2)
    c1.download_button("PDF olarak indir", reports.pdf_pasaport(icerik, icerik.get("@id", ""), seviye),
                       f"pasaport_{icerik.get('sku', 'urun')}.pdf", mime="application/pdf")
    c2.caption(f"İçerik özeti (SHA-256): `{kayit['icerik_ozeti'][:32]}…` "
               + ("✅ bütünlük kontrolü başarılı" if kayit["ozet_dogru"] else "⚠️ bütünlük kontrolü başarısız"))
    st.caption("Hazırlık göstergeleri resmi uygunluk kararı değildir. Veri yapısı taslaktır; ilgili yetki tüzüğü yayımlandığında "
               "resmi şemaya uyarlanacaktır.")


# ---------------------------------------------------------------------------
# Tedarikçi portalı
# ---------------------------------------------------------------------------

def tedarikci_portali(token: str):
    t = suppliers.token_ile(o.db(), token)
    if not t:
        st.error("Bağlantı geçersiz. Lütfen bağlantıyı gönderen firmayla iletişime geçin.")
        return
    st.caption("TEDARİKÇİ VERİ PORTALI")
    st.title(f"{t['firma_unvan']} — veri talebi")
    st.markdown(f"**Tedarikçi:** {t['tedarikci_unvan']}"
                + (f"  \n**Ürün:** {t['urun_kodu']} — {t['urun_adi']}" if t.get("urun_kodu") else "")
                + f"  \n**Son tarih:** {o.tarih_tr(t['son_tarih'])}")
    if t.get("mesaj"):
        st.info(t["mesaj"])
    if t["durum"] != "Açık":
        st.success("Bu talep yanıtlanmış. Teşekkür ederiz.")
        return
    if t["suresi_doldu"]:
        st.error("Bu bağlantının süresi dolmuş. Firmadan yeni bağlantı isteyin.")
        return
    istenen = t["istenenler"]
    st.caption("Girdiğiniz bilgiler yalnızca talep eden firmaya iletilir. Yüklediğiniz belgeler firma tarafından incelenir.")

    with st.form("tedarikci_yanit"):
        yanit: dict = {}
        if "malzeme" in istenen:
            st.subheader("Malzeme bileşimi")
            st.caption("Tedarik ettiğiniz ürünün malzemelerini ağırlıkça yüzdeleriyle girin.")
            import pandas as pd
            df = st.data_editor(pd.DataFrame([{"malzeme": "", "oran": None, "mense": "", "geri_donusturulmus": False}]),
                                num_rows="dynamic", hide_index=True, key="ted_malzeme",
                                column_config={"malzeme": "Malzeme", "oran": st.column_config.NumberColumn("Oran (%)", min_value=0, max_value=100),
                                               "mense": "Menşe ülke", "geri_donusturulmus": st.column_config.CheckboxColumn("Geri dönüştürülmüş")})
            yanit["malzemeler"] = [r for r in df.to_dict("records") if str(r.get("malzeme") or "").strip()]
        if "svhc" in istenen:
            st.subheader("REACH / SVHC beyanı")
            yanit["svhc_beyani"] = st.radio("Ürün, ECHA aday listesindeki maddelerden herhangi birini ağırlıkça %0,1'in üzerinde içeriyor mu?",
                                            ["Yok", "Var", "Bilinmiyor"], horizontal=True)
            yanit["svhc_maddeler"] = st.text_input("'Var' ise madde adı ve CAS numarası")
        if "mense" in istenen:
            st.subheader("Menşe")
            yanit["hammadde_mensei"] = st.text_input("Hammaddenin / ürünün menşe ülkesi")
        if "karbon" in istenen:
            st.subheader("Karbon ayak izi")
            yanit["karbon_kg"] = st.number_input("Birim başına kg CO2e", min_value=0.0, value=None)
            yanit["karbon_yontemi"] = st.text_input("Hesaplama yöntemi (ISO 14067, PEF ...)")
        dosyalar = []
        if "belge" in istenen:
            st.subheader("Belgeler")
            secenek = {b.ad: b.kod for b in BELGE_TURLERI}
            for i in range(3):
                c1, c2, c3 = st.columns([2, 2, 1])
                tur = c1.selectbox(f"Belge {i + 1} türü", ["—"] + list(secenek), key=f"tb_tur{i}")
                no = c2.text_input(f"Belge {i + 1} numarası", key=f"tb_no{i}")
                bitis = c3.date_input(f"Bitiş", value=None, key=f"tb_bitis{i}")
                dosya = st.file_uploader(f"Belge {i + 1} dosyası (PDF / görsel, en çok 10 MB)", type=["pdf", "png", "jpg", "jpeg"], key=f"tb_dosya{i}")
                if tur != "—" and dosya is not None:
                    dosyalar.append({"tur_kodu": secenek[tur], "belge_no": no, "bitis": bitis.isoformat() if bitis else None,
                                     "dosya": dosya.getvalue(), "dosya_adi": dosya.name, "dosya_mime": dosya.type})
        yanit["not"] = st.text_area("Eklemek istedikleriniz")
        yanitlayan = st.text_input("Adınız, soyadınız ve ünvanınız *")
        onay = st.checkbox("Verdiğim bilgilerin doğru ve güncel olduğunu beyan ederim.")
        gonder = st.form_submit_button("Gönder", type="primary")
    if gonder:
        if not onay:
            st.error("Lütfen beyan kutusunu işaretleyin.")
            return
        try:
            suppliers.yanitla(o.db(), token, yanit, dosyalar, yanitlayan)
            st.success("Yanıtınız iletildi. Teşekkür ederiz.")
            st.balloons()
        except ValueError as h:
            st.error(str(h))
