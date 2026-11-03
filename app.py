import streamlit as st
import pandas as pd
import io

# 1. Sayfa Ayarları (Kurumsal Geniş Ekran)
st.set_page_config(page_title="DPP Kurumsal Yönetim Paneli", layout="wide")

st.title("🌍 Dijital Ürün Pasaportu (DPP) Yönetim Paneli")
st.markdown("Kurumsal verileriniz üzerinden Avrupa Birliği ESPR kriterlerine göre **Gap (Eksik) Analizi** ve Uyum Raporlaması.")

# 2. Sol Menü (Sidebar) Ayarları
st.sidebar.header("📁 Veri Yükleme")
uploaded_file = st.sidebar.file_uploader("Ürün Excel Dosyanızı Yükleyin", type=["xlsx", "xls"])

if uploaded_file is not None:
    df = pd.read_excel(uploaded_file)
    
    # Gerekli sütunlar var mı kontrolü
    if set(['Cevre_Sertifikasi', 'Hammadde_Mensei', 'Sektor']).issubset(df.columns):
        
        # Eksik verileri tespit etme mantığı
        df['Eksik_Var_Mi'] = df['Cevre_Sertifikasi'].isnull() | df['Hammadde_Mensei'].isnull()
        eksikler_df = df[df['Eksik_Var_Mi']]
        
        # 3. Tepe Metrikleri (KPI Kartları)
        st.subheader("📊 Yönetici Özeti")
        col1, col2, col3 = st.columns(3)
        col1.metric("📦 Toplam İncelenen Ürün", len(df))
        col2.metric("✅ DPP'ye Uygun Ürün", len(df) - len(eksikler_df))
        col3.metric("🚨 Kritik Eksik (Aksiyon Bekleyen)", len(eksikler_df))
        
        st.divider()
        
        # 4. Sol Menü Filtreleme Sistemi
        st.sidebar.subheader("🔍 Filtreler")
        sektorler = df['Sektor'].dropna().unique().tolist()
        secilen_sektor = st.sidebar.multiselect("Görüntülenecek Sektörleri Seçin", sektorler, default=sektorler)
        
        # Veriyi filtreye göre daralt
        filtrelenmis_eksikler = eksikler_df[eksikler_df['Sektor'].isin(secilen_sektor)]
        
        if not filtrelenmis_eksikler.empty:
            st.error(f"DİKKAT! Seçili sektörlerde toplam {len(filtrelenmis_eksikler)} üründe zorunlu DPP verisi eksik. Bu ürünler gümrük onayı alamaz.")
            st.dataframe(filtrelenmis_eksikler[['Sektor', 'Urun_Kodu', 'Urun_Adi', 'Cevre_Sertifikasi', 'Hammadde_Mensei']], use_container_width=True)
            
            # Alt kısıma Grafik ve Buton için 2 sütun açıyoruz
            alt_sol, alt_sag = st.columns([2, 1])
            
            with alt_sol:
                st.warning("📉 Hatalı Ürünlerin Sektörel Dağılımı")
                st.bar_chart(filtrelenmis_eksikler['Sektor'].value_counts())
                
            with alt_sag:
                st.info("💡 Hatalı listeyi tedarikçilerinize göndermek için aşağıdan Excel formatında indirebilirsiniz.")
                # Excel olarak indirme motoru
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    filtrelenmis_eksikler.to_excel(writer, index=False, sheet_name='Duzeltilecek_Urunler')
                rapor_verisi = output.getvalue()
                
                st.download_button(
                    label="📥 Düzeltilecekler Raporunu İndir",
                    data=rapor_verisi,
                    file_name="dpp_eksik_raporu.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
        else:
            st.success("✅ Harika! Seçili sektörlerdeki tüm ürünler DPP standartlarına uygun. Kritik bir eksik bulunamadı.")
    else:
        st.error("Yüklenen dosyada 'Cevre_Sertifikasi', 'Hammadde_Mensei' veya 'Sektor' sütunları bulunamadı. Lütfen şablonu kontrol edin.")
else:
    st.info("👈 Analize başlamak için lütfen sol menüden Excel dosyanızı yükleyin.")
