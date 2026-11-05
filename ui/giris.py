"""Kurulum, giriş, zorunlu parola değişikliği ve hesap sayfası."""

from __future__ import annotations

import hmac

import streamlit as st

from dpp import URUN_ADI, audit, config, security
from ui import ortak as o


def kurulum():
    st.title(f"{URUN_ADI} — İlk kurulum")
    st.markdown("Sistemde henüz kullanıcı yok. İlk **platform yöneticisi** hesabını oluşturun.")
    anahtar = config.kurulum_anahtari()
    if not anahtar:
        st.error("Güvenlik için kurulum anahtarı tanımlanmamış. Streamlit **Settings › Secrets** bölümüne "
                 "`KURULUM_ANAHTARI = \"uzun-ve-gizli-bir-metin\"` satırını ekleyin ve sayfayı yenileyin.")
        st.stop()
    with st.form("kurulum"):
        girilen = st.text_input("Kurulum anahtarı", type="password")
        ad = st.text_input("Ad soyad")
        eposta = st.text_input("E-posta")
        p1 = st.text_input("Parola", type="password", help="En az 10 karakter, harf ve rakam içermeli")
        p2 = st.text_input("Parola (tekrar)", type="password")
        gonder = st.form_submit_button("Yönetici hesabını oluştur", type="primary")
    if gonder:
        if not hmac.compare_digest(girilen or "", str(anahtar)):
            st.error("Kurulum anahtarı hatalı.")
        elif p1 != p2:
            st.error("Parolalar eşleşmiyor.")
        elif security.kullanici_sayisi(o.db()) > 0:
            st.error("Kurulum zaten tamamlanmış.")
        else:
            try:
                kid = security.kullanici_olustur(o.db(), eposta, ad, "platform_yonetici", p1, None, parola_degismeli=False)
                audit.kaydet(o.db(), None, eposta, "İlk kurulum", "kullanici", kid, "Platform yöneticisi oluşturuldu")
                st.success("Hesap oluşturuldu. Şimdi giriş yapabilirsiniz.")
                st.rerun()
            except ValueError as h:
                st.error(str(h))


def giris_ekrani():
    sol, orta, sag = st.columns([1, 1.3, 1])
    with orta:
        st.markdown(f"## {config.platform_unvani()}")
        st.caption("Dijital Ürün Pasaportu hazırlık ve uyum yönetimi")
        if mesaj := st.session_state.pop("bilgi_mesaji", None):
            st.info(mesaj)
        with st.form("giris"):
            eposta = st.text_input("E-posta")
            parola = st.text_input("Parola", type="password")
            gonder = st.form_submit_button("Giriş yap", type="primary")
        if gonder:
            k, hata = security.giris(o.db(), eposta, parola)
            if k:
                o.giris_yap(k)
                st.rerun()
            else:
                audit.kaydet(o.db(), None, security.eposta_normal(eposta), "Başarısız giriş", "kullanici", None, hata)
                st.error(hata)
        st.caption("Parolanızı unuttuysanız firma yöneticinizden sıfırlama isteyin.")


def parola_degistir_formu(zorunlu: bool = False):
    if zorunlu:
        st.title("Parolanızı değiştirin")
        st.info("Güvenliğiniz için ilk girişte veya sıfırlamadan sonra parolanızı değiştirmeniz gerekiyor.")
    with st.form("parola"):
        eski = st.text_input("Mevcut parola", type="password")
        y1 = st.text_input("Yeni parola", type="password", help="En az 10 karakter, harf ve rakam")
        y2 = st.text_input("Yeni parola (tekrar)", type="password")
        gonder = st.form_submit_button("Parolayı değiştir", type="primary")
    if gonder:
        if y1 != y2:
            st.error("Yeni parolalar eşleşmiyor.")
            return
        hata = security.parola_degistir(o.db(), o.kullanici()["id"], eski, y1)
        if hata:
            st.error(hata)
        else:
            st.session_state["kullanici"]["parola_degismeli"] = 0
            o.kayit("Parola değiştirildi", "kullanici", o.kullanici()["id"])
            st.success("Parolanız değiştirildi.")
            if zorunlu:
                st.rerun()


def hesabim():
    k = o.kullanici()
    o.sayfa_basligi("Hesabım")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Ad soyad:** {k['ad_soyad']}  \n**E-posta:** {k['eposta']}  \n"
                    f"**Rol:** {security.ROLLER.get(k['rol'], k['rol'])}  \n**Son giriş:** {o.tarih_tr(k.get('son_giris'))}")
    with c2:
        st.markdown("**Rolünüzün yetkileri**")
        st.markdown("\n".join(f"- {ad}" for e, ad in YETKI_ADLARI.items() if security.yetkili(k["rol"], e)))
    st.divider()
    st.subheader("Parola değiştir")
    parola_degistir_formu()


YETKI_ADLARI = {
    "veri_duzenle": "Ürün ve belge verisi girme / düzenleme",
    "belge_dogrula": "Belge doğrulama",
    "urun_dogrula": "Ürün doğrulama beyanı düzenleme",
    "pasaport_yayimla": "Pasaport yayımlama ve geri çekme",
    "talep_olustur": "Tedarikçiden veri talep etme",
    "kullanici_yonet": "Kullanıcı yönetimi",
    "firma_yonet": "Firma yönetimi",
    "kural_yonet": "Kural seti ayarları",
    "iz_gor": "Denetim izini görme",
    "rapor_al": "Rapor alma",
}
