"""Belge kasası: sertifika, beyan ve test raporlarının yüklenmesi, bağlanması, süre ve doğrulama takibi."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dpp import evaluation, repo
from dpp.catalog import BELGE, BELGE_TURLERI, KATEGORI_YONETIM
from dpp.util import metin
from ui import ortak as o

TUR_SECENEK = {f"{b.ad} — {b.kategori}": b.kod for b in BELGE_TURLERI}


def _ad(b):
    return BELGE.get(b["tur_kodu"], BELGE["DIGER"]).ad if b["tur_kodu"] != "DIGER" else (b["tur_serbest"] or "Diğer")


def _hedef_secenekleri(f):
    db = o.db()
    s = {"🏢 Tüm firma": ("firma", None)}
    s |= {f"📦 {u['urun_kodu']} — {u['ad']}": ("urun", u["id"]) for u in repo.urunler(db, f)}
    s |= {f"🏭 Tesis: {t['ad']}": ("tesis", t["id"]) for t in repo.tesisler(db, f)}
    s |= {f"🤝 Tedarikçi: {t['unvan']}": ("tedarikci", t["id"]) for t in repo.tedarikciler(db, f)}
    return s


def sayfa():
    f = o.firma_gerekli()
    db = o.db()
    o.sayfa_basligi("Belge Kasası", "Sertifikalar, uygunluk beyanları, test raporları ve kayıtlar. Süreleri ve doğrulama durumları "
                                     "otomatik izlenir.")
    belgeler = repo.belgeler(db, f)
    durum = pd.Series([b["durum"] for b in belgeler]).value_counts() if belgeler else pd.Series(dtype=int)
    m = st.columns(5)
    m[0].metric("Belge", len(belgeler))
    m[1].metric("🟢 Geçerli", int(durum.get("Geçerli", 0)))
    m[2].metric("🟡/🟠 60 gün içinde", int(durum.get("60 gün içinde doluyor", 0) + durum.get("30 gün içinde doluyor", 0)))
    m[3].metric("🔴 Süresi dolmuş", int(durum.get("Süresi dolmuş", 0)))
    m[4].metric("⏳ Doğrulama bekliyor", sum(1 for b in belgeler if b["dogrulama_durumu"] == "Beklemede"))

    sekmeler = st.tabs(["Belgeler", "Yeni belge", "Belge düzenle"])
    with sekmeler[0]:
        c1, c2 = st.columns(2)
        df_durum = c1.multiselect("Süre durumu", list(o.BELGE_SIMGE))
        df_dog = c2.multiselect("Doğrulama", ["Beklemede", "Doğrulandı", "Reddedildi"])
        liste = [b for b in belgeler if (not df_durum or b["durum"] in df_durum) and (not df_dog or b["dogrulama_durumu"] in df_dog)]
        if liste:
            st.dataframe(pd.DataFrame([{
                " ": o.BELGE_SIMGE.get(b["durum"]), "No.": b["id"], "Belge": _ad(b), "Kategori": BELGE.get(b["tur_kodu"], BELGE["DIGER"]).kategori,
                "Belge no": b["belge_no"], "Düzenleyen": b["duzenleyen"], "Bitiş": o.tarih_tr(b["bitis"]), "Kalan gün": b["kalan"],
                "Durum": b["durum"], "Doğrulama": f"{o.DOGRULAMA_SIMGE.get(b['dogrulama_durumu'], '')} {b['dogrulama_durumu']}",
                "Bağlı olduğu": ", ".join((x["hedef_adi"] or "—") for x in b["baglantilar"]), "Dosya": "📎" if b["dosya_adi"] else "",
                "Kaynak": b["kaynak"],
            } for b in liste]), hide_index=True)
            yonetim = [b for b in belgeler if BELGE.get(b["tur_kodu"], BELGE["DIGER"]).kategori == KATEGORI_YONETIM]
            if yonetim:
                st.info(f"{len(yonetim)} yönetim sistemi belgesi (ISO 9001, ISO 14001, IATF vb.) var. Bunlar kuruluşun süreçlerini "
                        "belgeler; ürünün çevre veya mevzuat uygunluğunu tek başına kanıtlamaz.")
            dosyali = {f"#{b['id']} {_ad(b)} {b['belge_no'] or ''} — {b['dosya_adi']}": b["id"] for b in liste if b["dosya_adi"]}
            if dosyali:
                s1, s2 = st.columns([3, 1])
                sec = s1.selectbox("Dosya indir", list(dosyali), index=None, placeholder="Belge seçin")
                if sec:
                    d = repo.belge_dosyasi(db, f, dosyali[sec])
                    s2.download_button("İndir", d["dosya"], d["dosya_adi"], mime=d["dosya_mime"] or "application/octet-stream")
        else:
            st.info("Belge yok." if not belgeler else "Filtreye uyan belge yok.")

    with sekmeler[1]:
        if not o.izin("belge_yukle"):
            st.caption("Belge ekleme yetkiniz yok.")
        else:
            hedefler = _hedef_secenekleri(f)
            with st.form("yeni_belge", clear_on_submit=True):
                a, b = st.columns(2)
                tur = a.selectbox("Belge türü *", list(TUR_SECENEK))
                serbest = b.text_input("Belge adı (türü 'Diğer' ise)")
                no = a.text_input("Belge / sertifika no")
                duz = b.text_input("Düzenleyen kuruluş")
                bas = a.date_input("Geçerlilik başlangıcı", value=None)
                bit = b.date_input("Geçerlilik bitişi (süresizse boş)", value=None)
                kapsam = st.text_input("Kapsam")
                bag = st.multiselect("Bağlı olduğu kayıtlar *", list(hedefler),
                                     help="Ürün, tesis, tedarikçi veya tüm firma. Bir belge birden fazla kayda bağlanabilir.")
                dosya = st.file_uploader("Dosya (PDF / görsel, en çok 10 MB)", type=["pdf", "png", "jpg", "jpeg", "xlsx", "docx"])
                if st.form_submit_button("Belgeyi kaydet", type="primary"):
                    if not bag:
                        st.error("En az bir bağlantı seçin.")
                    else:
                        try:
                            repo.belge_ekle(db, f, {"tur_kodu": TUR_SECENEK[tur], "tur_serbest": serbest or None, "belge_no": no,
                                                    "duzenleyen": duz, "baslangic": bas.isoformat() if bas else None,
                                                    "bitis": bit.isoformat() if bit else None, "kapsam": kapsam},
                                            [hedefler[x] for x in bag], o.eposta(),
                                            dosya.getvalue() if dosya else None, dosya.name if dosya else None, dosya.type if dosya else None)
                            evaluation.firma_degerlendir(db, f, o.eposta())
                            st.success("Belge kaydedildi; ilgili ürünler yeniden değerlendirildi.")
                        except ValueError as h:
                            st.error(str(h))

    with sekmeler[2]:
        if not belgeler:
            st.caption("Düzenlenecek belge yok.")
            return
        if not o.izin("belge_yukle"):
            st.caption("Belge düzenleme yetkiniz yok.")
            return
        secenek = {f"#{b['id']} {_ad(b)} {b['belge_no'] or ''}": b for b in belgeler}
        sec = st.selectbox("Belge", list(secenek), key="duzenle_belge")
        b = secenek[sec]
        hedefler = _hedef_secenekleri(f)
        mevcut = [k for k, v in hedefler.items() if (v[0], v[1]) in {(x["hedef_tur"], x["hedef_id"]) for x in b["baglantilar"]}]
        turler = list(TUR_SECENEK)
        with st.form(f"belge_duzenle_{b['id']}"):
            a, c = st.columns(2)
            tur = a.selectbox("Belge türü", turler, index=list(TUR_SECENEK.values()).index(b["tur_kodu"]) if b["tur_kodu"] in TUR_SECENEK.values() else 0)
            no = c.text_input("Belge no", metin(b["belge_no"]))
            duz = a.text_input("Düzenleyen", metin(b["duzenleyen"]))
            from datetime import date
            bit = c.date_input("Bitiş", value=date.fromisoformat(b["bitis"]) if b["bitis"] else None)
            kapsam = st.text_input("Kapsam", metin(b["kapsam"]))
            bag = st.multiselect("Bağlantılar", list(hedefler), default=mevcut)
            st.caption("Belge içeriği değiştirilirse doğrulama durumu 'Beklemede'ye döner.")
            k1, k2 = st.columns(2)
            kaydet = k1.form_submit_button("Kaydet", type="primary")
        if kaydet:
            repo.belge_guncelle(db, f, b["id"], {"tur_kodu": TUR_SECENEK[tur], "belge_no": no, "duzenleyen": duz,
                                                "bitis": bit.isoformat() if bit else None, "kapsam": kapsam}, o.eposta())
            repo.belge_baglantilari_ayarla(db, f, b["id"], [hedefler[x] for x in bag])
            evaluation.firma_degerlendir(db, f, o.eposta())
            st.toast("Belge güncellendi.", icon="✅")
            st.rerun()
        with st.expander("Belgeyi sil"):
            onay = st.checkbox("Bu belgeyi kalıcı olarak silmek istediğimi onaylıyorum.", key=f"sil_onay_{b['id']}")
            if st.button("Sil", disabled=not onay, key=f"sil_{b['id']}"):
                repo.belge_sil(db, f, b["id"], o.eposta())
                evaluation.firma_degerlendir(db, f, o.eposta())
                st.rerun()
