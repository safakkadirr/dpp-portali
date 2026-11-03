import streamlit as st
import pandas as pd

# Sayfa Ayarları
st.set_page_config(page_title="DPP Uyum Portalı", layout="wide")

# Başlık ve Açıklama
st.title("🌍 Dijital Ürün Pasaportu (DPP) Uyum Portalı")
st.markdown("Tedarikçi ve ürün verilerinizi sisteme yükleyerek Avrupa Birliği ESPR kriterlerine göre **Gap (Eksik) Analizi** yapabilirsiniz.")
st.divider()

# Dosya Yükleme Alanı
uploaded_file = st.file_uploader("Lütfen ürün verilerinizi içeren Excel (.xlsx) dosyasını sürükleyip bırakın", type=["xlsx", "xls"])

if uploaded_file is not None:
    # Dosya yüklendiyse oku
    df = pd.read_excel(uploaded_file)
    
    st.subheader("📌 1. Sisteme Yüklenen Ham Veriler")
    st.dataframe(df, use_container_width=True)
    
    st.divider()
    st.subheader("⚠️ 2. Gap (Eksik Veri) Analizi Raporu")
    
    # Gerekli sütunlar var mı diye kontrol et
    if 'Cevre_Sertifikasi' in df.columns and 'Hammadde_Mensei' in df.columns:
        eksikler = df[df['Cevre_Sertifikasi'].isnull() | df['Hammadde_Mensei'].isnull()]
        
        if not eksikler.empty:
            st.error(f"DİKKAT! Toplam {len(eksikler)} üründe kritik veri veya belge eksikliği tespit edildi. Bu ürünler DPP onayı alamaz.")
            st.dataframe(eksikler[['Sektor', 'Urun_Kodu', 'Urun_Adi', 'Cevre_Sertifikasi', 'Hammadde_Mensei']], use_container_width=True)
            
            st.warning("Yönetici Özeti: Eksiklerin Sektörel Dağılımı")
            st.bar_chart(eksikler['Sektor'].value_counts())
        else:
            st.success("✅ Mükemmel! Yüklenen Excel dosyasındaki tüm ürünler DPP standartlarına uygun ve eksiksiz.")
    else:
        st.error("Yüklenen dosyada aranan zorunlu sütunlar bulunamadı. Lütfen Excel şablonunuzu kontrol edin.")
