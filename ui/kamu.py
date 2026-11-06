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
# Tedarikçi portalı (hesap gerektirmez, Türkçe / İngilizce)
# ---------------------------------------------------------------------------

M = {
    "tr": {
        "ust": "TEDARİKÇİ VERİ PORTALI", "talep": "bilgi ve belge talebi", "gecersiz": "Bağlantı geçersiz veya yenilenmiş. "
        "Lütfen size bağlantıyı gönderen firmayla iletişime geçin.", "tedarikci": "Tedarikçi", "son": "Son tarih",
        "kalan": "{} gün kaldı", "bugun": "bugün son gün", "urunler": "İlgili ürünler", "revizyon": "Firma, yanıtınızda düzeltme veya "
        "ek bilgi istedi:", "kapali": "Bu talep firma tarafından kapatılmıştır. Teşekkür ederiz.", "doldu": "Bu bağlantının süresi "
        "dolmuş. Firmadan yeni bağlantı isteyin.", "yanitlandi": "Yanıtınız alındı ({}). Süre bitene kadar bilgileri güncelleyebilir "
        "veya yeni belge ekleyebilirsiniz.", "gizlilik": "Girdiğiniz bilgiler yalnızca talep eden firmaya iletilir. Yüklediğiniz "
        "belgeler firma tarafından incelenir.", "mevcut": "Firmada kayıtlı belgeleriniz", "mevcut_acik": "Süresi dolan veya yaklaşan "
        "belgelerin güncel hâlini aşağıdan yükleyebilirsiniz.", "genel": "Genel bilgiler", "malzeme": "Malzeme bileşimi",
        "malzeme_acik": "Tedarik ettiğiniz malzemenin içeriğini ağırlıkça yüzdeleriyle girin (ör. Pamuk 98, Elastan 2).",
        "m_malzeme": "Malzeme", "m_oran": "Oran (%)", "m_mense": "Menşe ülke", "m_gd": "Geri dönüştürülmüş",
        "svhc_soru": "Tedarik ettiğiniz ürün/malzeme, ECHA aday listesindeki (SVHC) maddelerden herhangi birini ağırlıkça %0,1'in "
        "üzerinde içeriyor mu?", "svhc_madde": "'Var' ise madde adı ve CAS numarası", "sec": "— seçin —", "yok": "Yok", "var": "Var",
        "bilinmiyor": "Bilinmiyor", "mense": "Hammaddenin / malzemenin menşe ülkesi", "karbon": "Karbon ayak izi (birim başına kg CO2e)",
        "karbon_y": "Hesaplama yöntemi (ISO 14067, PEF ...)", "belgeler": "Belgeler", "belge_sayi": "Kaç belge yükleyeceksiniz?",
        "b_tur": "Belge {} türü", "b_no": "Belge {} numarası", "b_duz": "Belge {} düzenleyen kuruluş", "b_bitis": "Belge {} geçerlilik bitişi",
        "b_urun": "Belge {} hangi ürünler için", "b_dosya": "Belge {} dosyası (PDF / görsel, en çok 10 MB)", "not": "Eklemek istedikleriniz",
        "ad": "Adınız, soyadınız ve ünvanınız *", "onay": "Verdiğim bilgilerin doğru ve güncel olduğunu beyan ederim.",
        "gonder": "Gönder", "onay_hata": "Lütfen beyan kutusunu işaretleyin.", "basari": "Yanıtınız iletildi. Teşekkür ederiz.",
        "svhc_madde_hata": "'{}' için SVHC 'Var' seçildi; madde adını / CAS numarasını yazın.", "tur_hata": "Belge {} için tür seçin.",
        "durum": "Durum", "bitis": "Bitiş", "no": "No", "tur": "Belge",
    },
    "en": {
        "ust": "SUPPLIER DATA PORTAL", "talep": "information and document request", "gecersiz": "This link is invalid or has been "
        "renewed. Please contact the company that sent it to you.", "tedarikci": "Supplier", "son": "Deadline",
        "kalan": "{} days left", "bugun": "today is the last day", "urunler": "Related products", "revizyon": "The company asked "
        "for corrections or additional information:", "kapali": "This request has been closed by the company. Thank you.",
        "doldu": "This link has expired. Please ask the company for a new link.", "yanitlandi": "Your response was received ({}). "
        "You can update the information or add documents until the deadline.", "gizlilik": "Your information is shared only with "
        "the requesting company. Uploaded documents are reviewed by the company.", "mevcut": "Your documents on file",
        "mevcut_acik": "Please upload the current version of expired or expiring documents below.", "genel": "General information",
        "malzeme": "Material composition", "malzeme_acik": "Enter the composition of the material you supply as weight percentages "
        "(e.g. Cotton 98, Elastane 2).", "m_malzeme": "Material", "m_oran": "Share (%)", "m_mense": "Country of origin",
        "m_gd": "Recycled", "svhc_soru": "Does the product/material you supply contain any substance on the ECHA Candidate List "
        "(SVHC) above 0.1% weight by weight?", "svhc_madde": "If 'Yes', substance name and CAS number", "sec": "— select —",
        "yok": "No", "var": "Yes", "bilinmiyor": "Unknown", "mense": "Country of origin of the raw material",
        "karbon": "Carbon footprint (kg CO2e per unit)", "karbon_y": "Calculation method (ISO 14067, PEF ...)", "belgeler": "Documents",
        "belge_sayi": "How many documents will you upload?", "b_tur": "Document {} type", "b_no": "Document {} number",
        "b_duz": "Document {} issued by", "b_bitis": "Document {} valid until", "b_urun": "Document {} applies to",
        "b_dosya": "Document {} file (PDF / image, max 10 MB)", "not": "Additional comments", "ad": "Your name and title *",
        "onay": "I declare that the information provided is accurate and up to date.", "gonder": "Submit",
        "onay_hata": "Please tick the declaration box.", "basari": "Your response has been submitted. Thank you.",
        "svhc_madde_hata": "SVHC 'Yes' was selected for '{}'; please enter the substance name / CAS number.",
        "tur_hata": "Please select a type for document {}.", "durum": "Status", "bitis": "Valid until", "no": "No", "tur": "Document",
    },
}


def tedarikci_portali(token: str):
    import pandas as pd
    from datetime import date

    db = o.db()
    t = suppliers.token_ile(db, token)
    if not t:
        st.error(M["tr"]["gecersiz"] + "  \n" + M["en"]["gecersiz"])
        return
    acilis_anahtari = f"portal_acildi_{t['id']}"
    if not st.session_state.get(acilis_anahtari):
        suppliers.acildi(db, token)
        st.session_state[acilis_anahtari] = True
    bas, dil_kutu = st.columns([5, 1])
    dil = st.session_state.get("portal_dil") or (t.get("dil") if t.get("dil") in M else "tr")
    secim = dil_kutu.selectbox("Dil / Language", ["Türkçe", "English"], index=0 if dil == "tr" else 1)
    if (secim == "English") != (dil == "en"):
        st.session_state["portal_dil"] = "en" if secim == "English" else "tr"
        st.rerun()
    m = M[dil]
    with bas:
        st.caption(m["ust"])
        st.title(f"{t['firma_unvan']} — {m['talep']}")
    kalan = (date.fromisoformat(t["son_tarih"]) - date.today()).days if t.get("son_tarih") else None
    kalan_metni = "" if kalan is None or kalan < 0 else f" ({m['bugun'] if kalan == 0 else m['kalan'].format(kalan)})"
    st.markdown(f"**{m['tedarikci']}:** {t['tedarikci_unvan']}  \n**{m['son']}:** {o.tarih_tr(t['son_tarih'])}{kalan_metni}"
                + (f"  \n**{m['urunler']}:** " + ", ".join(f"{u['urun_kodu']} {u['ad']}" for u in t["urunler"]) if t["urunler"] else ""))
    if t.get("mesaj"):
        st.info(t["mesaj"])
    if t["durum"] == "Kapandı":
        st.success(m["kapali"])
        return
    if t["suresi_doldu"]:
        st.error(m["doldu"])
        return
    if t.get("revizyon_notu"):
        st.warning(f"**{m['revizyon']}** {t['revizyon_notu']}")
    if t["durum"] == "Yanıtlandı":
        st.success(m["yanitlandi"].format(o.tarih_tr(t.get("yanit_tarihi"))))
    st.caption(m["gizlilik"])
    istenen = t["istenenler"]
    onceki = t.get("yanit") or {}
    if "belge" in istenen and t["mevcut_belgeler"]:
        with st.expander(f"{m['mevcut']} ({len(t['mevcut_belgeler'])})", expanded=any(
                b["durum"] not in ("Geçerli", "Bitiş tarihi yok") for b in t["mevcut_belgeler"])):
            st.caption(m["mevcut_acik"])
            st.dataframe(pd.DataFrame([{m["tur"]: b["tur"], m["no"]: b["no"] or "—", m["bitis"]: o.tarih_tr(b["bitis"]),
                                        m["durum"]: f"{o.BELGE_SIMGE.get(b['durum'], '')} {b['durum']}"} for b in t["mevcut_belgeler"]]),
                         hide_index=True)
    belge_sayisi = 0
    if "belge" in istenen:
        belge_sayisi = int(st.number_input(m["belge_sayi"], min_value=0, max_value=8, value=1 if t["durum"] == "Yanıtlandı" else 2))
    svhc_kod = ["—", "Yok", "Var", "Bilinmiyor"]
    svhc_ad = {"—": m["sec"], "Yok": m["yok"], "Var": m["var"], "Bilinmiyor": m["bilinmiyor"]}
    hedefler = [(str(u["id"]), f"{u['urun_kodu']} — {u['ad']}", u) for u in t["urunler"]] or [("genel", m["genel"], None)]

    with st.form("tedarikci_yanit"):
        yanit: dict = {"urunler": {}, "genel": {}}
        for anahtar, baslik, u in hedefler:
            st.subheader(baslik)
            eski = (onceki.get("urunler") or {}).get(anahtar) if u else onceki.get("genel")
            eski = eski or {}
            alan: dict = {}
            if "malzeme" in istenen:
                st.markdown(f"**{m['malzeme']}**")
                st.caption(m["malzeme_acik"])
                baslangic = eski.get("malzemeler") or [
                    {"malzeme": x["malzeme"], "oran": x["oran"], "mense": x["mense"] or "", "geri_donusturulmus": bool(x["geri_donusturulmus"])}
                    for x in (u or {}).get("malzemeler", [])] or [{"malzeme": "", "oran": None, "mense": "", "geri_donusturulmus": False}]
                df = st.data_editor(pd.DataFrame(baslangic, columns=["malzeme", "oran", "mense", "geri_donusturulmus"]),
                                    num_rows="dynamic", hide_index=True, key=f"ted_malzeme_{anahtar}",
                                    column_config={"malzeme": m["m_malzeme"],
                                                   "oran": st.column_config.NumberColumn(m["m_oran"], min_value=0, max_value=100),
                                                   "mense": m["m_mense"],
                                                   "geri_donusturulmus": st.column_config.CheckboxColumn(m["m_gd"])})
                alan["malzemeler"] = [{k: (None if pd.isna(v) else v) if not isinstance(v, (list, dict)) else v for k, v in r.items()}
                                      for r in df.to_dict("records") if str(r.get("malzeme") or "").strip()]
            if "svhc" in istenen:
                varsayilan = eski.get("svhc_beyani") if eski.get("svhc_beyani") in svhc_kod else "—"
                alan["svhc_beyani"] = st.radio(m["svhc_soru"], svhc_kod, index=svhc_kod.index(varsayilan), horizontal=True,
                                               format_func=lambda k: svhc_ad[k], key=f"ted_svhc_{anahtar}")
                alan["svhc_maddeler"] = st.text_input(m["svhc_madde"], value=eski.get("svhc_maddeler") or "", key=f"ted_madde_{anahtar}")
            if "mense" in istenen:
                alan["hammadde_mensei"] = st.text_input(m["mense"], value=eski.get("hammadde_mensei") or "", key=f"ted_mense_{anahtar}")
            if "karbon" in istenen:
                alan["karbon_kg"] = st.number_input(m["karbon"], min_value=0.0, value=eski.get("karbon_kg"), key=f"ted_karbon_{anahtar}")
                alan["karbon_yontemi"] = st.text_input(m["karbon_y"], value=eski.get("karbon_yontemi") or "", key=f"ted_ky_{anahtar}")
            if u:
                yanit["urunler"][anahtar] = alan
            else:
                yanit["genel"] = alan
        dosyalar, eksik_tur = [], []
        if belge_sayisi:
            st.subheader(m["belgeler"])
            secenek = {f"{b.ad}" if dil == "tr" else f"{b.kod} — {b.ad}": b.kod for b in BELGE_TURLERI}
            urun_secenek = {f"{u['urun_kodu']} — {u['ad']}": u["id"] for u in t["urunler"]}
            for i in range(1, belge_sayisi + 1):
                c1, c2, c3 = st.columns([2, 2, 1])
                tur = c1.selectbox(m["b_tur"].format(i), ["—"] + list(secenek), key=f"tb_tur{i}")
                no = c2.text_input(m["b_no"].format(i), key=f"tb_no{i}")
                bitis = c3.date_input(m["b_bitis"].format(i), value=None, key=f"tb_bitis{i}")
                duzenleyen = st.text_input(m["b_duz"].format(i), key=f"tb_duz{i}")
                hedef = list(urun_secenek)
                if len(urun_secenek) > 1:
                    hedef = st.multiselect(m["b_urun"].format(i), list(urun_secenek), default=list(urun_secenek), key=f"tb_urun{i}")
                dosya = st.file_uploader(m["b_dosya"].format(i), type=["pdf", "png", "jpg", "jpeg"], key=f"tb_dosya{i}")
                if dosya is not None:
                    if tur == "—":
                        eksik_tur.append(i)
                        continue
                    dosyalar.append({"tur_kodu": secenek[tur], "belge_no": no, "duzenleyen": duzenleyen,
                                     "bitis": bitis.isoformat() if bitis else None, "dosya": dosya.getvalue(),
                                     "dosya_adi": dosya.name, "dosya_mime": dosya.type,
                                     "urun_idler": [urun_secenek[h] for h in hedef] if hedef else None})
        yanit["not"] = st.text_area(m["not"], value=onceki.get("not") or "")
        yanitlayan = st.text_input(m["ad"], value=onceki.get("yanitlayan") or "")
        onay = st.checkbox(m["onay"])
        gonder = st.form_submit_button(m["gonder"], type="primary")
    if gonder:
        if not onay:
            st.error(m["onay_hata"])
            return
        if eksik_tur:
            st.error(" ".join(m["tur_hata"].format(i) for i in eksik_tur))
            return
        for anahtar, baslik, _ in hedefler:
            a = yanit["urunler"].get(anahtar) if anahtar != "genel" else yanit["genel"]
            if a and a.get("svhc_beyani") == "Var" and not str(a.get("svhc_maddeler") or "").strip():
                st.error(m["svhc_madde_hata"].format(baslik))
                return
        try:
            suppliers.yanitla(db, token, yanit, dosyalar, yanitlayan)
            st.success(m["basari"])
            st.balloons()
        except ValueError as h:
            st.error(str(h))
