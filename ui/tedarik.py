"""Tedarikçiler, tesisler ve tedarikçi veri talepleri."""

from __future__ import annotations

from urllib.parse import quote

import pandas as pd
import streamlit as st

from dpp import config, evaluation, repo, suppliers
from ui import ortak as o


def sayfa():
    f = o.firma_gerekli()
    o.sayfa_basligi("Tedarik Zinciri", "Tedarikçiler, üretim tesisleri ve tedarikçilerden veri talepleri.")
    s = st.tabs(["Veri talepleri", "Tedarikçiler", "Tesisler"])
    with s[0]:
        talepler(f)
    with s[1]:
        _tablo_ekrani(f, "tedarikciler", repo.TEDARIKCI_ALANLARI, "unvan",
                      {"unvan": "Unvan *", "ulke": "Ülke", "eposta": "E-posta", "yetkili": "Yetkili", "kimlik_no": "Vergi no / GLN",
                       "notlar": "Not"}, repo.tedarikciler(o.db(), f))
    with s[2]:
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


def talepler(f):
    db = o.db()
    ted = repo.tedarikciler(db, f)
    if o.izin("talep_olustur"):
        with st.expander("➕ Yeni veri talebi", expanded=not suppliers.talepler(db, f)):
            if not ted:
                st.info("Önce Tedarikçiler sekmesinden tedarikçi ekleyin.")
            else:
                urunler = {f"{u['urun_kodu']} — {u['ad']}": u["id"] for u in repo.urunler(db, f)}
                with st.form("talep"):
                    a, b = st.columns(2)
                    t_sec = {t["unvan"]: t["id"] for t in ted}
                    tedarikci = a.selectbox("Tedarikçi", list(t_sec))
                    urun = b.selectbox("İlgili ürün", ["(ürüne bağlı değil)"] + list(urunler))
                    istenen = st.multiselect("İstenen bilgiler", list(suppliers.ISTENEBILIR),
                                             default=["svhc", "malzeme", "belge"], format_func=lambda k: suppliers.ISTENEBILIR[k])
                    mesaj = st.text_area("Tedarikçiye mesaj", "AB'ye ihraç ettiğimiz ürünler için Dijital Ürün Pasaportu ve REACH "
                                                              "kapsamında aşağıdaki bilgilere ihtiyacımız var. Desteğiniz için teşekkür ederiz.")
                    gun = st.number_input("Geçerlilik (gün)", 1, 90, 14)
                    gonder = st.form_submit_button("Bağlantı oluştur", type="primary")
                if gonder:
                    try:
                        tid, token = suppliers.talep_olustur(db, f, t_sec[tedarikci], urunler.get(urun), istenen, mesaj, gun, o.eposta())
                        adres = f"{config.uygulama_adresi()}/?t={token}"
                        st.success("Bağlantı oluşturuldu. Bu bağlantı yalnızca şimdi gösterilir; güvenlik için sistemde açık hali saklanmaz.")
                        st.code(adres, language=None)
                        eposta = next((t["eposta"] for t in ted if t["id"] == t_sec[tedarikci]), "") or ""
                        konu = quote(f"{repo.firma(db, f)['unvan']} — veri talebi")
                        govde = quote(f"{mesaj}\n\nBilgileri aşağıdaki bağlantıdan girebilirsiniz (hesap gerekmez):\n{adres}\n\n"
                                      f"Bağlantı {gun} gün geçerlidir.")
                        st.link_button("E-posta ile gönder", f"mailto:{eposta}?subject={konu}&body={govde}")
                    except ValueError as h:
                        st.error(str(h))

    liste = suppliers.talepler(db, f)
    if not liste:
        st.caption("Henüz veri talebi yok.")
        return
    st.dataframe(pd.DataFrame([{
        "No": t["id"], "Tedarikçi": t["tedarikci"], "Ürün": t["urun_kodu"] or "—",
        "İstenen": ", ".join(suppliers.ISTENEBILIR.get(i, i).split(" (")[0] for i in t["istenenler"]),
        "Durum": t["durum"], "Son tarih": o.tarih_tr(t["son_tarih"]), "Yanıt": o.tarih_tr(t["yanit_tarihi"]),
    } for t in liste]), hide_index=True)
    yanitli = {f"#{t['id']} {t['tedarikci']} — {t['urun_kodu'] or 'ürünsüz'}": t for t in liste if t["durum"] == "Yanıtlandı"}
    if yanitli:
        st.subheader("Yanıtları incele")
        t = yanitli[st.selectbox("Yanıt", list(yanitli))]
        y = t["yanit"] or {}
        st.markdown(f"**Yanıtlayan:** {y.get('yanitlayan', '—')} · {o.tarih_tr(t['yanit_tarihi'])}")
        if y.get("svhc_beyani"):
            st.markdown(f"**SVHC beyanı:** {y['svhc_beyani']} {y.get('svhc_maddeler') or ''}")
        if y.get("hammadde_mensei"):
            st.markdown(f"**Menşe:** {y['hammadde_mensei']}")
        if y.get("karbon_kg") is not None:
            st.markdown(f"**Karbon ayak izi:** {y['karbon_kg']} kg CO2e ({y.get('karbon_yontemi') or '—'})")
        if y.get("malzemeler"):
            st.dataframe(pd.DataFrame(y["malzemeler"]), hide_index=True)
        if y.get("belge_idler"):
            st.markdown(f"**Yüklenen belge:** {len(y['belge_idler'])} adet (Belge Kasası'nda 'Beklemede' durumunda)")
        if y.get("not"):
            st.markdown(f"**Not:** {y['not']}")
        if o.izin("veri_duzenle"):
            a, b = st.columns(2)
            if a.button("Ürüne aktar", type="primary", disabled=not t["urun_id"]):
                try:
                    yapilan = suppliers.urune_aktar(db, f, t["id"], o.eposta())
                    evaluation.urun_degerlendir(db, f, t["urun_id"], o.eposta())
                    st.success("Aktarıldı: " + (", ".join(yapilan) or "aktarılacak alan yoktu"))
                except ValueError as h:
                    st.error(str(h))
            if b.button("Aktarmadan kapat"):
                suppliers.kapat(db, f, t["id"], o.eposta())
                st.rerun()
