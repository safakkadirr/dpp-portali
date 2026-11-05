"""Bağımsız doğrulama: belgelerin incelenmesi ve ürün doğrulama beyanı."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dpp import evaluation, repo
from dpp.catalog import BELGE
from ui import ortak as o


def sayfa():
    f = o.firma_gerekli()
    db = o.db()
    o.sayfa_basligi("Bağımsız Doğrulama", "Belgelerin ve ürün verisinin bağımsız doğrulayıcı tarafından incelenmesi. "
                                          "Her doğrulama, yapan kişinin adıyla denetim izine kaydedilir.")
    s = st.tabs(["Belge doğrulama", "Ürün doğrulama beyanı", "Doğrulama geçmişi"])
    with s[0]:
        belgeler = repo.belgeler(db, f)
        bekleyen = [b for b in belgeler if b["dogrulama_durumu"] == "Beklemede"]
        st.markdown(f"**{len(bekleyen)}** belge doğrulama bekliyor.")
        goster = st.toggle("Tüm belgeleri göster", value=False)
        liste = belgeler if goster else bekleyen
        if not liste:
            st.success("Doğrulama bekleyen belge yok.")
        else:
            secenek = {f"#{b['id']} {BELGE.get(b['tur_kodu'], BELGE['DIGER']).ad if b['tur_kodu'] != 'DIGER' else b['tur_serbest']} "
                       f"{b['belge_no'] or ''} · {b['dogrulama_durumu']}": b for b in liste}
            b = secenek[st.selectbox("Belge", list(secenek))]
            a, c = st.columns(2)
            with a:
                st.markdown(f"**Tür:** {BELGE.get(b['tur_kodu'], BELGE['DIGER']).ad}  \n**No:** {b['belge_no'] or '—'}  \n"
                            f"**Düzenleyen:** {b['duzenleyen'] or '—'}  \n**Geçerlilik:** {o.tarih_tr(b['baslangic'])} – {o.tarih_tr(b['bitis'])} "
                            f"({b['durum']})  \n**Kapsam:** {b['kapsam'] or '—'}  \n"
                            f"**Bağlı olduğu:** {', '.join(x['hedef_adi'] or '' for x in b['baglantilar'])}  \n"
                            f"**Yükleyen:** {b['yukleyen']} ({b['kaynak']})")
                if b["dosya_adi"]:
                    d = repo.belge_dosyasi(db, f, b["id"])
                    st.download_button(f"📎 {b['dosya_adi']}", d["dosya"], d["dosya_adi"], mime=d["dosya_mime"] or "application/octet-stream")
                    st.caption(f"SHA-256: `{b['dosya_ozet']}`")
                else:
                    st.warning("Bu belgenin dosyası yüklenmemiş; yalnızca kayıt bilgisi var.")
            with c:
                if o.izin("belge_dogrula"):
                    with st.form(f"bd_{b['id']}"):
                        sonuc = st.radio("Sonuç", ["Doğrulandı", "Reddedildi", "Beklemede"], horizontal=True)
                        st.caption("Kontrol: belge türü ve numarası, düzenleyen kuruluşun yetkisi, geçerlilik tarihi, kapsamın ürünü "
                                   "kapsaması, unvan ve adres uyumu.")
                        notu = st.text_area("İnceleme notu (reddetmede zorunlu)")
                        if st.form_submit_button("Kaydet", type="primary"):
                            try:
                                repo.belge_dogrula(db, f, b["id"], sonuc, notu, f"{o.ad()} <{o.eposta()}>")
                                evaluation.firma_degerlendir(db, f, o.eposta())
                                st.rerun()
                            except ValueError as h:
                                st.error(str(h))
                else:
                    st.caption("Belge doğrulama yetkisi bağımsız doğrulayıcı rolündedir.")

    with s[1]:
        urunler = repo.urunler(db, f)
        if not urunler:
            st.info("Ürün yok.")
        else:
            secenek = {f"{o.DURUM_SIMGE.get(u['genel_durum'], '⚪')} {u['urun_kodu']} — {u['ad']}": u for u in urunler}
            u = secenek[st.selectbox("Ürün", list(secenek), key="dog_urun")]
            d, guncel = evaluation.dogrulama_gecerli_mi(db, f, u["id"])
            if d:
                st.info(f"Son doğrulama: **{d['sonuc']}** — {d['dogrulayan']} ({o.tarih_tr(d['tarih'])})"
                        + ("" if guncel else " · ⚠️ veri o tarihten sonra değişti"))
            bel = repo.urun_belgeleri(db, f, u["id"])
            st.markdown(f"Durum: {o.durum_metni(u['genel_durum'])} · Yasal eksik: {u['yasal_eksik']} · DPP hazırlık: "
                        f"%{(u['hazirlik_skoru'] or 0):.0f} · Belgeler: {len(bel)} "
                        f"(doğrulanan {sum(1 for b in bel if b['dogrulama_durumu'] == 'Doğrulandı')})")
            if o.izin("urun_dogrula"):
                with st.form(f"ud_{u['id']}"):
                    sonuc = st.radio("Sonuç", evaluation.DOGRULAMA_SONUCLARI, horizontal=True)
                    unvan = st.text_input("Doğrulayıcı unvanı", placeholder="ör. Yeminli Mali Müşavir / Bağımsız Denetçi")
                    kapsam = st.text_area("Doğrulama kapsamı", "Ürün kartındaki kimlik, menşe, malzeme ve SVHC bilgilerinin ilgili "
                                                              "belgelerle tutarlılığı; belge geçerlilikleri.")
                    aciklama = st.text_area("Açıklama / şartlar")
                    st.caption("Beyan, ürün verisinin o anki parmak izini (SHA-256) saklar; veri sonradan değişirse pasaportta "
                               "'doğrulamadan sonra güncellendi' notu görünür.")
                    if st.form_submit_button("Doğrulama beyanını kaydet", type="primary"):
                        try:
                            evaluation.urun_dogrula(db, f, u["id"], o.ad(), unvan, sonuc, kapsam, aciklama)
                            st.success("Beyan kaydedildi. Pasaportta görünmesi için pasaportu yeniden yayımlayın.")
                        except ValueError as h:
                            st.error(str(h))
            else:
                st.caption("Ürün doğrulama yetkisi bağımsız doğrulayıcı rolündedir.")

    with s[2]:
        st.dataframe(o.tablo(repo.dogrulamalar(db, f), {"urun_kodu": "Ürün", "sonuc": "Sonuç", "dogrulayan": "Doğrulayan", "unvan": "Unvan",
                                                         "tarih": "Tarih", "kapsam": "Kapsam", "aciklama": "Açıklama"}), hide_index=True)
