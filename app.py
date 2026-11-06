"""
DPP Hazırlık Platformu — kurumsal sürüm
Çalıştırma: streamlit run app.py
"""

import streamlit as st

from dpp import SURUM, config, security
from ui import ortak as o

st.set_page_config(page_title=config.platform_unvani(), page_icon="🌍", layout="wide")
st.markdown(o.CSS, unsafe_allow_html=True)

from ui import aktarim, belgeler, bilgi, dogrulama, giris, kamu, pano, pasaportlar, portal, raporlar, tedarik, urunler, yonetim  # noqa: E402

# --- Giriş gerektirmeyen bağlantılar ------------------------------------------
parametreler = st.query_params
if parametreler.get("p"):
    kamu.pasaport_sayfasi(parametreler.get("p"), parametreler.get("k"))
    st.stop()
if parametreler.get("t"):
    kamu.tedarikci_portali(parametreler.get("t"))
    st.stop()

# --- Kurulum ve giriş ------------------------------------------------------
if security.kullanici_sayisi(o.db()) == 0:
    giris.kurulum()
    st.stop()

k = o.kullanici()
if not k:
    giris.giris_ekrani()
    st.stop()

if k.get("parola_degismeli"):
    giris.parola_degistir_formu(zorunlu=True)
    st.stop()

# --- Kenar çubuğu -------------------------------------------------------------
with st.sidebar:
    st.markdown(f"### 🌍 {config.platform_unvani()}")
    st.markdown(f"**{k['ad_soyad']}**  \n<span class='dpp-kucuk'>{security.ROLLER.get(k['rol'], k['rol'])}</span>",
                unsafe_allow_html=True)
    if o.platform_yoneticisi():
        from dpp import repo
        firmalar = {x["unvan"]: x["id"] for x in repo.firmalar(o.db())}
        if firmalar:
            adlar = list(firmalar)
            mevcut = next((a for a, i in firmalar.items() if i == o.firma_id()), None)
            secim = st.selectbox("Çalışılan firma", adlar, index=adlar.index(mevcut) if mevcut else None, placeholder="Firma seçin")
            if secim and firmalar[secim] != o.firma_id():
                st.session_state["aktif_firma"] = firmalar[secim]
                st.session_state["secili_urun"] = None
                st.rerun()
    elif k.get("firma_id"):
        from dpp import repo
        st.caption(repo.firma(o.db(), k["firma_id"])["unvan"])

# --- Gezinme -----------------------------------------------------------------
P = st.Page
sayfalar = {
    "Genel": [P(pano.sayfa, title="Gösterge paneli", icon="📊", url_path="pano", default=True)],
    "Veri": [P(urunler.sayfa, title="Ürünler", icon="📦", url_path="urunler"),
             P(belgeler.sayfa, title="Belge Kasası", icon="📁", url_path="belgeler"),
             P(tedarik.sayfa, title="Tedarik Zinciri", icon="🤝", url_path="tedarik"),
             P(portal.sayfa, title="Tedarikçi Portalı", icon="🔗", url_path="tedarikci-portali"),
             P(aktarim.sayfa, title="Excel Aktarım", icon="📥", url_path="aktarim")],
    "Uyum": [P(raporlar.eksikler_sayfasi, title="Eksikler ve Çözüm", icon="🔎", url_path="eksikler"),
             P(dogrulama.sayfa, title="Bağımsız Doğrulama", icon="✅", url_path="dogrulama"),
             P(pasaportlar.sayfa, title="Pasaportlar", icon="🏷️", url_path="pasaportlar"),
             P(raporlar.raporlar_sayfasi, title="Raporlar", icon="📄", url_path="raporlar")],
    "Bilgi": [P(bilgi.asistan_sayfasi, title="Uyum Asistanı", icon="💬", url_path="asistan"),
              P(bilgi.mevzuat_sayfasi, title="Mevzuat Rehberi", icon="📚", url_path="mevzuat"),
              P(bilgi.kural_seti_sayfasi, title="Kural Seti", icon="⚖️", url_path="kurallar")],
}
yonetim_sayfalari = []
if o.izin("kullanici_yonet"):
    yonetim_sayfalari.append(P(yonetim.kullanicilar_sayfasi, title="Kullanıcılar", icon="👥", url_path="kullanicilar"))
if o.izin("firma_ayarlari") and o.firma_id():
    yonetim_sayfalari.append(P(yonetim.firma_ayarlari_sayfasi, title="Firma Ayarları", icon="🏢", url_path="firma"))
if o.izin("iz_gor"):
    yonetim_sayfalari.append(P(yonetim.denetim_izi_sayfasi, title="Denetim İzi", icon="🧾", url_path="iz"))
if o.izin("firma_yonet"):
    yonetim_sayfalari.append(P(yonetim.firmalar_sayfasi, title="Firmalar", icon="🏛️", url_path="firmalar"))
yonetim_sayfalari.append(P(giris.hesabim, title="Hesabım", icon="👤", url_path="hesabim"))
sayfalar["Yönetim"] = yonetim_sayfalari

secilen = st.navigation(sayfalar)

with st.sidebar:
    st.divider()
    if st.button("Çıkış yap"):
        o.cikis()
        st.rerun()
    st.caption(f"Sürüm {SURUM}")

secilen.run()
st.divider()
st.caption(o.UYARI)
