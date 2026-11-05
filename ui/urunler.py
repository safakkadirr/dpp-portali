"""Ürün listesi ve ürün kartı (genel bilgiler, malzeme, tedarik zinciri, partiler, belgeler, değerlendirme, pasaport)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dpp import config, evaluation, passport, repo
from dpp.catalog import BELGE, SEKTOR, SEKTOR_ADLARI, SEKTORLER, sektor_oner
from dpp.util import bos_mu, gtin_dogrula, gtip_dogrula, metin, sayi, tarih_metni
from ui import ortak as o

SEKTOR_SECENEK = {s.ad: s.kod for s in SEKTORLER}


def sayfa():
    f = o.firma_gerekli()
    secili = st.session_state.get("secili_urun")
    if secili and repo.urun(o.db(), f, secili):
        urun_karti(f, secili)
    else:
        st.session_state["secili_urun"] = None
        liste(f)


# ---------------------------------------------------------------------------
# Liste
# ---------------------------------------------------------------------------

def liste(f: int):
    db = o.db()
    o.sayfa_basligi("Ürünler", "Ürün kartlarını açarak veri girin, eksikleri görün ve pasaport yayımlayın.")
    urunler = repo.urunler(db, f)
    c1, c2, c3 = st.columns([2, 1.3, 1.3])
    ara = c1.text_input("Ara", placeholder="Ürün kodu, adı veya GTIN")
    sektor = c2.multiselect("Sektör", sorted({SEKTOR_ADLARI.get(u["sektor_kodu"]) for u in urunler}))
    durum = c3.multiselect("Durum", ["Kritik eksik", "Yasal eksik", "Hazırlık sürüyor", "Hazır"])
    if ara:
        a = ara.lower()
        urunler = [u for u in urunler if a in (u["urun_kodu"] or "").lower() or a in (u["ad"] or "").lower() or a in (u["gtin"] or "")]
    if sektor:
        urunler = [u for u in urunler if SEKTOR_ADLARI.get(u["sektor_kodu"]) in sektor]
    if durum:
        urunler = [u for u in urunler if u["genel_durum"] in durum]

    if urunler:
        df = pd.DataFrame([{
            " ": o.DURUM_SIMGE.get(u["genel_durum"], "⚪"), "Ürün kodu": u["urun_kodu"], "Ürün adı": u["ad"],
            "Sektör": SEKTOR_ADLARI.get(u["sektor_kodu"]), "Durum": u["genel_durum"] or "—",
            "Yasal eksik": u["yasal_eksik"], "DPP hazırlık": u["hazirlik_skoru"],
            "Pasaport": f"v{u['yayindaki_surum']}" if u["yayindaki_surum"] else "—",
            "Güncelleme": o.tarih_tr(u["guncelleme"]),
        } for u in urunler])
        st.dataframe(df, hide_index=True, column_config={
            "DPP hazırlık": st.column_config.ProgressColumn("DPP hazırlık", min_value=0, max_value=100, format="%.0f%%")})
        secenek = {f"{o.DURUM_SIMGE.get(u['genel_durum'], '⚪')} {u['urun_kodu']} — {u['ad']}": u["id"] for u in urunler}
        s1, s2 = st.columns([4, 1])
        secim = s1.selectbox("Ürün kartını aç", list(secenek), index=None, placeholder="Ürün seçin")
        if s2.button("Aç", type="primary", disabled=secim is None):
            st.session_state["secili_urun"] = secenek[secim]
            st.rerun()
    else:
        st.info("Kriterlere uyan ürün yok.")

    if o.izin("veri_duzenle"):
        with st.expander("➕ Yeni ürün"):
            with st.form("yeni_urun", clear_on_submit=True):
                a, b = st.columns(2)
                kod = a.text_input("Ürün kodu *")
                ad = b.text_input("Ürün adı *")
                gtip = a.text_input("GTİP kodu", help="Sektör boş bırakılırsa GTİP kodundan önerilir")
                sek = b.selectbox("Sektör", ["(GTİP'ten öner)"] + list(SEKTOR_SECENEK))
                if st.form_submit_button("Oluştur", type="primary"):
                    try:
                        sk = SEKTOR_SECENEK.get(sek) or sektor_oner(gtip, ad)
                        uid = repo.urun_kaydet(db, f, {"urun_kodu": kod, "ad": ad, "gtip": gtip, "sektor_kodu": sk}, o.eposta())
                        evaluation.urun_degerlendir(db, f, uid, o.eposta())
                        st.session_state["secili_urun"] = uid
                        st.rerun()
                    except ValueError as h:
                        st.error(str(h))


# ---------------------------------------------------------------------------
# Ürün kartı
# ---------------------------------------------------------------------------

def urun_karti(f: int, uid: int):
    db = o.db()
    u = repo.urun(db, f, uid)
    duzenle = o.izin("veri_duzenle")
    if st.button("← Ürün listesi"):
        st.session_state["secili_urun"] = None
        st.rerun()
    deg = db.bir("SELECT * FROM degerlendirmeler WHERE urun_id = ? AND son = 1", (uid,))
    st.title(f"{u['urun_kodu']} — {u['ad']}")
    if deg:
        st.markdown(f"{o.durum_metni(deg['genel_durum'])} · Yasal uyum: **{deg['yasal_durum']}** "
                    f"({deg['yasal_eksik']} eksik, {deg['kritik_eksik']} kritik) · DPP hazırlık: **%{deg['hazirlik_skoru']:.0f}** · "
                    f"<span class='dpp-kucuk'>Kural seti {deg['kural_seti']} · {o.tarih_tr(deg['tarih'])}</span>",
                    unsafe_allow_html=True)
    if not u["aktif"]:
        st.warning("Bu ürün arşivlenmiş.")

    sekmeler = st.tabs(["Genel bilgiler", "Malzemeler", "Tedarik zinciri", "Partiler", "Belgeler", "Değerlendirme", "Pasaport"])
    with sekmeler[0]:
        genel_bilgiler(f, u, duzenle)
    with sekmeler[1]:
        malzemeler(f, u, duzenle)
    with sekmeler[2]:
        asamalar(f, u, duzenle)
    with sekmeler[3]:
        partiler(f, u, duzenle)
    with sekmeler[4]:
        belgeler(f, u)
    with sekmeler[5]:
        degerlendirme(f, u, deg)
    with sekmeler[6]:
        pasaport_sekmesi(f, u)


def _kaydet_ve_degerlendir(f, uid, veri):
    try:
        repo.urun_kaydet(o.db(), f, veri, o.eposta(), uid)
        evaluation.urun_degerlendir(o.db(), f, uid, o.eposta())
        st.toast("Kaydedildi ve yeniden değerlendirildi.", icon="✅")
        st.rerun()
    except ValueError as h:
        st.error(str(h))


def genel_bilgiler(f, u, duzenle):
    db = o.db()
    tesisler = {t["ad"]: t["id"] for t in repo.tesisler(db, f)}
    tesis_adi = next((a for a, i in tesisler.items() if i == u["tesis_id"]), None)
    sektor_kodu = u["sektor_kodu"] or "diger"
    with st.form(f"genel_{u['id']}"):
        st.markdown("##### Kimlik")
        a, b, c = st.columns(3)
        v = {}
        v["urun_kodu"] = a.text_input("Ürün kodu *", u["urun_kodu"], disabled=not duzenle)
        v["ad"] = b.text_input("Ürün adı *", u["ad"], disabled=not duzenle)
        v["marka"] = c.text_input("Marka", metin(u["marka"]), disabled=not duzenle)
        sek_adlari = list(SEKTOR_SECENEK)
        v["sektor_kodu"] = SEKTOR_SECENEK[a.selectbox("Sektör", sek_adlari, index=sek_adlari.index(SEKTOR[sektor_kodu].ad), disabled=not duzenle)]
        v["gtip"] = b.text_input("GTİP kodu", metin(u["gtip"]), disabled=not duzenle)
        v["gtin"] = c.text_input("GTIN (barkod)", metin(u["gtin"]), disabled=not duzenle)
        tuk = {None: "Sektöre göre", 1: "Evet", 0: "Hayır"}
        v["tuketici_urunu"] = {"Sektöre göre": None, "Evet": 1, "Hayır": 0}[
            a.selectbox("Tüketici ürünü mü?", list(tuk.values()), index=list(tuk).index(u["tuketici_urunu"]), disabled=not duzenle,
                        help="Son tüketiciye satılan ürünlerde Genel Ürün Güvenliği Tüzüğü şartları uygulanır.")]
        ts = ["—"] + list(tesisler)
        v["tesis_id"] = tesisler.get(b.selectbox("Üretim tesisi", ts, index=ts.index(tesis_adi) if tesis_adi else 0, disabled=not duzenle))

        st.markdown("##### Aktörler ve menşe")
        a, b, c = st.columns(3)
        v["ab_sorumlu_operator"] = a.text_input("AB sorumlu ekonomik operatör", metin(u["ab_sorumlu_operator"]),
                                                 help="Unvan, adres, e-posta", disabled=not duzenle)
        v["uretim_ulkesi"] = b.text_input("Üretim (menşe) ülkesi", metin(u["uretim_ulkesi"]), disabled=not duzenle)
        v["hammadde_mensei"] = c.text_input("Hammadde menşei", metin(u["hammadde_mensei"]), disabled=not duzenle)

        st.markdown("##### Kimyasallar ve çevre")
        a, b, c = st.columns(3)
        svhc = ["Yok", "Var", "Bilinmiyor"]
        mevcut_svhc = metin(u["svhc_beyani"])
        v["svhc_beyani"] = a.selectbox("SVHC beyanı (%0,1 eşiği)", ["—"] + svhc,
                                       index=(svhc.index(mevcut_svhc) + 1) if mevcut_svhc in svhc else 0, disabled=not duzenle)
        v["svhc_maddeler"] = b.text_input("SVHC maddeler (ad, CAS)", metin(u["svhc_maddeler"]), disabled=not duzenle)
        v["geri_donusturulmus_yuzde"] = c.number_input("Geri dönüştürülmüş içerik (%)", 0.0, 100.0, sayi(u["geri_donusturulmus_yuzde"]),
                                                       disabled=not duzenle)
        v["cevresel_iddia"] = a.text_input("Çevresel iddia", metin(u["cevresel_iddia"]), disabled=not duzenle,
                                           help="Etiket veya katalogda kullanılan ifade. Kanıtsız genel iddialar yasaktır.")
        v["karbon_kg"] = b.number_input("Karbon ayak izi (kg CO2e / birim)", 0.0, None, sayi(u["karbon_kg"]), disabled=not duzenle)
        v["karbon_yontemi"] = c.text_input("Karbon hesaplama yöntemi", metin(u["karbon_yontemi"]), disabled=not duzenle)

        st.markdown("##### Kullanım ve ömür sonu")
        a, b = st.columns(2)
        v["bakim_onarim"] = a.text_area("Bakım / onarım bilgisi", metin(u["bakim_onarim"]), height=80, disabled=not duzenle)
        v["omur_sonu"] = b.text_area("Ömür sonu talimatı", metin(u["omur_sonu"]), height=80, disabled=not duzenle)

        st.markdown("##### Sektörel alanlar")
        a, b, c = st.columns(3)
        if sektor_kodu in ("demir_celik", "aluminyum"):
            v["gomulu_emisyon"] = a.number_input("Gömülü emisyon (tCO2e / ton) — CBAM", 0.0, None, sayi(u["gomulu_emisyon"]), disabled=not duzenle)
        if sektor_kodu in ("beyaz_esya", "lastik", "elektronik"):
            v["eprel_no"] = a.text_input("EPREL kayıt no", metin(u["eprel_no"]), disabled=not duzenle)
        if sektor_kodu == "otomotiv":
            v["imds_id"] = a.text_input("IMDS kayıt no", metin(u["imds_id"]), disabled=not duzenle)
        if sektor_kodu == "batarya":
            kat = ["—", "EV", "LMT", "Endüstriyel", "Taşınabilir", "SLI"]
            m = metin(u["batarya_kategori"])
            v["batarya_kategori"] = a.selectbox("Batarya kategorisi", kat, index=kat.index(m) if m in kat else 0, disabled=not duzenle)
            v["batarya_kimya"] = b.text_input("Batarya kimyası", metin(u["batarya_kimya"]), disabled=not duzenle)
            v["batarya_kwh"] = c.number_input("Kapasite (kWh)", 0.0, None, sayi(u["batarya_kwh"]), disabled=not duzenle)
        if sektor_kodu not in ("demir_celik", "aluminyum", "beyaz_esya", "lastik", "elektronik", "otomotiv", "batarya"):
            st.caption("Bu sektör için ek alan yok.")
        v["notlar"] = st.text_input("İç notlar", metin(u["notlar"]), disabled=not duzenle)
        kaydet = st.form_submit_button("Kaydet", type="primary", disabled=not duzenle)
    ok, msg = gtin_dogrula(u["gtin"])
    if u["gtin"] and not ok:
        st.caption(f"⚠️ {msg}")
    ok, msg = gtip_dogrula(u["gtip"])
    if u["gtip"] and not ok:
        st.caption(f"⚠️ {msg}")
    oneri = sektor_oner(u["gtip"])
    if u["gtip"] and oneri != "diger" and oneri != sektor_kodu:
        st.caption(f"ℹ️ GTİP koduna göre önerilen sektör: **{SEKTOR[oneri].ad}**")
    if kaydet:
        for k in ("svhc_beyani", "batarya_kategori"):
            if v.get(k) == "—":
                v[k] = None
        _kaydet_ve_degerlendir(f, u["id"], v)
    if duzenle and u["aktif"]:
        with st.expander("Ürünü arşivle"):
            st.caption("Arşivlenen ürün listelerde ve değerlendirmede görünmez; kayıtları ve pasaport geçmişi saklanır.")
            if st.button("Arşivle", key=f"arsiv_{u['id']}"):
                repo.urun_pasiflestir(o.db(), f, u["id"], o.eposta())
                st.session_state["secili_urun"] = None
                st.rerun()


def _editor(f, u, tablo, kolonlar: dict, config_: dict, duzenle: bool, donustur, geri_donustur):
    satirlar = repo.alt_liste(o.db(), tablo, f, u["id"])
    df = pd.DataFrame([donustur(s) for s in satirlar], columns=list(kolonlar))
    duz = st.data_editor(df, num_rows="dynamic" if duzenle else "fixed", hide_index=True, disabled=not duzenle,
                         column_config=config_, key=f"ed_{tablo}_{u['id']}_{st.session_state.get('ed_sayac', 0)}")
    return duz, satirlar


def malzemeler(f, u, duzenle):
    db = o.db()
    ted = {t["unvan"]: t["id"] for t in repo.tedarikciler(db, f)}
    ted_ters = {v: k for k, v in ted.items()}
    st.caption("Ağırlıkça yüzdeler; toplam %100 olmalı. Tekstilde lif adlarını Tekstil Etiketleme Tüzüğü'ndeki adlarla girin.")
    duz, _ = _editor(f, u, "malzemeler", {"malzeme": 0, "oran": 0, "mense": 0, "geri_donusturulmus": 0, "tedarikci": 0}, {
        "malzeme": st.column_config.TextColumn("Malzeme", required=True),
        "oran": st.column_config.NumberColumn("Oran (%)", min_value=0, max_value=100, format="%.1f"),
        "mense": "Menşe ülke",
        "geri_donusturulmus": st.column_config.CheckboxColumn("Geri dönüştürülmüş"),
        "tedarikci": st.column_config.SelectboxColumn("Tedarikçi", options=list(ted)),
    }, duzenle, lambda s: {"malzeme": s["malzeme"], "oran": s["oran"], "mense": s["mense"],
                           "geri_donusturulmus": bool(s["geri_donusturulmus"]), "tedarikci": ted_ters.get(s["tedarikci_id"])}, None)
    toplam = pd.to_numeric(duz["oran"], errors="coerce").fillna(0).sum() if len(duz) else 0
    (st.caption if abs(toplam - 100) <= 1 or not len(duz) else st.warning)(f"Toplam: %{toplam:g}")
    if duzenle and st.button("Malzemeleri kaydet", type="primary", key=f"mk_{u['id']}"):
        satirlar = [{"malzeme": metin(r["malzeme"]), "oran": sayi(r["oran"]), "mense": metin(r["mense"]) or None,
                     "geri_donusturulmus": 1 if r.get("geri_donusturulmus") in (True, 1) else 0, "tedarikci_id": ted.get(r["tedarikci"])}
                    for r in duz.to_dict("records")]
        repo.alt_degistir(db, "malzemeler", f, u["id"], satirlar, o.eposta())
        _sonra(f, u["id"])


def asamalar(f, u, duzenle):
    db = o.db()
    ted = {t["unvan"]: t["id"] for t in repo.tedarikciler(db, f)}
    ted_ters = {v: k for k, v in ted.items()}
    st.caption("Hammaddeden nihai ürüne kadar üretim aşamaları. Tedarikçiyi listede görmüyorsanız önce Tedarikçiler ekranından ekleyin.")
    duz, _ = _editor(f, u, "tedarik_asamalari", {"sira": 0, "asama": 0, "tedarikci": 0, "ulke": 0, "belge_no": 0}, {
        "sira": st.column_config.NumberColumn("Sıra", min_value=1, step=1),
        "asama": st.column_config.TextColumn("Aşama", required=True),
        "tedarikci": st.column_config.SelectboxColumn("Tedarikçi", options=list(ted)),
        "ulke": "Ülke", "belge_no": "Belge no",
    }, duzenle, lambda s: {"sira": s["sira"], "asama": s["asama"], "tedarikci": ted_ters.get(s["tedarikci_id"]), "ulke": s["ulke"],
                           "belge_no": s["belge_no"]}, None)
    if duzenle and st.button("Aşamaları kaydet", type="primary", key=f"ak_{u['id']}"):
        satirlar = [{"sira": int(sayi(r["sira"]) or i + 1), "asama": metin(r["asama"]), "tedarikci_id": ted.get(r["tedarikci"]),
                     "ulke": metin(r["ulke"]) or None, "belge_no": metin(r["belge_no"]) or None} for i, r in enumerate(duz.to_dict("records"))]
        repo.alt_degistir(db, "tedarik_asamalari", f, u["id"], satirlar, o.eposta())
        _sonra(f, u["id"])


def partiler(f, u, duzenle):
    db = o.db()
    tes = {t["ad"]: t["id"] for t in repo.tesisler(db, f)}
    tes_ters = {v: k for k, v in tes.items()}
    st.caption("Pasaport model düzeyinde veya parti (lot) düzeyinde yayımlanabilir.")
    duz, _ = _editor(f, u, "partiler", {"parti_no": 0, "uretim_tarihi": 0, "miktar": 0, "tesis": 0, "notlar": 0}, {
        "parti_no": st.column_config.TextColumn("Parti / lot no", required=True),
        "uretim_tarihi": st.column_config.TextColumn("Üretim tarihi (YYYY-AA-GG)"),
        "miktar": st.column_config.NumberColumn("Miktar"),
        "tesis": st.column_config.SelectboxColumn("Tesis", options=list(tes)), "notlar": "Not",
    }, duzenle, lambda s: {"parti_no": s["parti_no"], "uretim_tarihi": s["uretim_tarihi"], "miktar": s["miktar"],
                           "tesis": tes_ters.get(s["tesis_id"]), "notlar": s["notlar"]}, None)
    if duzenle and st.button("Partileri kaydet", type="primary", key=f"pk_{u['id']}"):
        try:
            satirlar = [{"parti_no": metin(r["parti_no"]), "uretim_tarihi": tarih_metni(r["uretim_tarihi"]), "miktar": sayi(r["miktar"]),
                         "tesis_id": tes.get(r["tesis"]), "notlar": metin(r["notlar"]) or None} for r in duz.to_dict("records")]
            repo.alt_degistir(db, "partiler", f, u["id"], satirlar, o.eposta())
            _sonra(f, u["id"])
        except ValueError as h:
            st.error(str(h))


def _sonra(f, uid):
    evaluation.urun_degerlendir(o.db(), f, uid, o.eposta())
    st.session_state["ed_sayac"] = st.session_state.get("ed_sayac", 0) + 1
    st.toast("Kaydedildi ve yeniden değerlendirildi.", icon="✅")
    st.rerun()


def belgeler(f, u):
    bl = repo.urun_belgeleri(o.db(), f, u["id"])
    st.caption("Ürüne doğrudan bağlı belgeler ile firmanın tamamına, ürünün tesisine veya tedarikçilerine bağlı belgeler. "
               "Belge eklemek ve bağlamak için **Belge Kasası** ekranını kullanın.")
    if not bl:
        st.info("Bu ürünle ilişkili belge yok.")
        return
    bag = {"urun": "Ürün", "firma": "Firma geneli", "tesis": "Tesis", "tedarikci": "Tedarikçi"}
    st.dataframe(pd.DataFrame([{
        " ": o.BELGE_SIMGE.get(b["durum"]), "Belge": BELGE.get(b["tur_kodu"], BELGE["DIGER"]).ad if b["tur_kodu"] != "DIGER" else b["tur_serbest"],
        "No": b["belge_no"], "Düzenleyen": b["duzenleyen"], "Bitiş": o.tarih_tr(b["bitis"]), "Durum": b["durum"],
        "Doğrulama": f"{o.DOGRULAMA_SIMGE.get(b['dogrulama_durumu'], '')} {b['dogrulama_durumu']}", "Bağ": bag.get(b["bag_turu"]),
        "Dosya": "📎" if b["dosya_adi"] else "",
    } for b in bl]), hide_index=True)


def degerlendirme(f, u, deg):
    db = o.db()
    if st.button("Yeniden değerlendir", key=f"yd_{u['id']}"):
        evaluation.urun_degerlendir(db, f, u["id"], o.eposta())
        st.rerun()
    if not deg:
        st.info("Henüz değerlendirme yok.")
        return
    bulgular = evaluation.bulgular(db, deg["id"])
    eksik = [b for b in bulgular if b["sonuc"] == "Eksik"]
    uygun = [b for b in bulgular if b["sonuc"] == "Uygun"]
    for baslik, sinif in (("Yasal eksikler (bugün yürürlükte)", ("Yasal",)),
                          ("Yaklaşan yükümlülükler", ("Yaklaşan yükümlülük",)),
                          ("DPP hazırlığı ve iyi uygulama", ("DPP", "İyi uygulama"))):
        grup = [b for b in eksik if b["sinif"] in sinif]
        if not grup:
            continue
        st.subheader(f"{baslik} ({len(grup)})")
        for b in grup:
            tarih = f" · zorunlu: {o.tarih_tr(b['zorunlu_tarih'])}" if b.get("zorunlu_tarih") else ""
            with st.expander(f"{o.SEVIYE_SIMGE[b['seviye']]} [{b['kural_kodu']}] {b['kural']} — {b['seviye']}{tarih}",
                             expanded=b["sinif"] == "Yasal" and b["seviye"] == "Kritik"):
                st.markdown(f"**Tespit:** {b['detay']}")
                st.markdown(f"**Dayanak:** {b['dayanak']}" + (f" · [kaynak]({b['kaynak']})" if b.get("kaynak") else ""))
                st.markdown("**Yapılacaklar:**\n" + "\n".join(f"{i}. {a}" for i, a in enumerate(b["recete"], 1)))
    if not eksik:
        st.success("Uygulanan tüm kurallar karşılanıyor.")
    with st.expander(f"✅ Karşılanan kurallar ({len(uygun)})"):
        st.dataframe(pd.DataFrame([{"Kod": b["kural_kodu"], "Kural": b["kural"], "Sınıf": b["sinif"], "Detay": b["detay"]} for b in uygun]),
                     hide_index=True)
    gecmis = db.tumu("SELECT tarih, genel_durum, yasal_eksik, hazirlik_skoru, kural_seti, calistiran FROM degerlendirmeler "
                     "WHERE urun_id = ? ORDER BY id DESC LIMIT 30", (u["id"],))
    with st.expander("Değerlendirme geçmişi"):
        st.dataframe(o.tablo(gecmis, {"tarih": "Tarih", "genel_durum": "Durum", "yasal_eksik": "Yasal eksik",
                                      "hazirlik_skoru": "DPP hazırlık", "kural_seti": "Kural seti", "calistiran": "Çalıştıran"}),
                     hide_index=True)
    d, guncel = evaluation.dogrulama_gecerli_mi(db, f, u["id"])
    if d:
        st.info(f"**Bağımsız doğrulama:** {d['sonuc']} — {d['dogrulayan']} ({o.tarih_tr(d['tarih'])})"
                + ("" if guncel else " · ⚠️ Doğrulamadan sonra ürün verisi değişti; yeniden doğrulama gerekir."))


def pasaport_sekmesi(f, u):
    db = o.db()
    kayitlar = passport.pasaportlar(db, f, u["id"])
    yayinda = [k for k in kayitlar if k["durum"] == "Yayında"]
    if yayinda:
        for k in yayinda:
            adres = f"{config.uygulama_adresi()}/?p={k['genel_kimlik']}"
            st.success(f"Yayında: sürüm {k['surum']}" + (f" · parti {k['parti_no']}" if k["parti_no"] else " · model düzeyi")
                       + f" · {o.tarih_tr(k['yayim_tarihi'])}")
            st.code(adres, language=None)
    else:
        st.info("Bu ürün için yayımlanmış pasaport yok.")
    if o.izin("pasaport_yayimla"):
        partiler = repo.alt_liste(db, "partiler", f, u["id"])
        secenek = {"Model düzeyi (tüm partiler)": None} | {f"Parti {p['parti_no']}": p["id"] for p in partiler}
        s = st.selectbox("Pasaport düzeyi", list(secenek), key=f"pd_{u['id']}")
        if st.button("Yayımla / yeni sürüm yayımla", type="primary", key=f"py_{u['id']}"):
            try:
                r = passport.yayimla(db, f, u["id"], secenek[s], o.eposta(), config.uygulama_adresi())
                st.success(f"Sürüm {r['surum']} yayımlandı.")
                if r["uyari"]:
                    st.warning(r["uyari"])
            except ValueError as h:
                st.error(str(h))
    else:
        st.caption("Pasaport yayımlama yetkisi firma yöneticisindedir.")
    st.caption("Yönetim ve QR kod için **Pasaportlar** ekranına bakın.")
