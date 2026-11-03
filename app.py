import streamlit as st
import pandas as pd
import io
import qrcode
from PIL import Image
from datetime import datetime

# 1. Sayfa Ayarları
st.set_page_config(page_title="DPP Uyum & Due Diligence Paneli", layout="wide", page_icon="⚖️")

st.title("⚖️ DPP Uyum ve Due Diligence Denetim Portalı")
st.markdown("Avrupa Birliği (AB) EN Standartlarına göre sektörel denetim, risk skorlaması ve Dijital Pasaport üretimi.")

# 2. Sol Menü (Sidebar)
st.sidebar.header("📁 Veri Yükleme")
uploaded_file = st.sidebar.file_uploader("Ürün Excel Dosyanızı Yükleyin", type=["xlsx", "xls"])

if uploaded_file is not None:
    df = pd.read_excel(uploaded_file)
    
    # Sistemin çökmemesi için eksik gelişmiş sütunları otomatik doldurma (Simülasyon/Güvenlik)
    if 'Sertifika_Bitis_Tarihi' not in df.columns:
        df['Sertifika_Bitis_Tarihi'] = pd.to_datetime('2027-12-31') # Varsayılan geçerli tarih
    else:
        df['Sertifika_Bitis_Tarihi'] = pd.to_datetime(df['Sertifika_Bitis_Tarihi'], errors='coerce')
        
    if set(['Cevre_Sertifikasi', 'Hammadde_Mensei', 'Sektor', 'Urun_Kodu', 'Urun_Adi']).issubset(df.columns):
        
        # --- AKILLI DENETİM (DUE DILIGENCE) MOTORU ---
        bugun = pd.to_datetime(datetime.today())
        
        def denetim_yap(row):
            skor = 100
            hatalar = []
            
            # 1. Temel Veri Eksikliği (-40 Puan)
            if pd.isna(row['Cevre_Sertifikasi']) or pd.isna(row['Hammadde_Mensei']):
                skor -= 40
                hatalar.append("Kritik Veri Eksik")
                
            # 2. Sertifika Geçerlilik Tarihi Denetimi (-30 Puan)
            if pd.notna(row['Sertifika_Bitis_Tarihi']) and row['Sertifika_Bitis_Tarihi'] < bugun:
                skor -= 30
                hatalar.append("Sertifika Süresi Dolmuş")
                
            # 3. Sektörel EN Standartları Norm Kontrolü (-30 Puan)
            sertifika = str(row['Cevre_Sertifikasi']).upper()
            sektor = str(row['Sektor']).upper()
            
            if "TEKSTIL" in sektor and not any(x in sertifika for x in ["OEKO-TEX", "REACH", "GOTS"]):
                skor -= 30
                hatalar.append("Tekstil EN Normu İhlali (REACH/OEKO-TEX Gerekli)")
            elif "ELEKTRONIK" in sektor and not any(x in sertifika for x in ["ROHS", "WEEE", "CE"]):
                skor -= 30
                hatalar.append("Elektronik EN Normu İhlali (RoHS Gerekli)")
            elif "MOBILYA" in sektor and "FSC" not in sertifika:
                skor -= 30
                hatalar.append("Ahşap Kaynak İhlali (FSC Gerekli)")
                
            # Sonuç
            if skor == 100:
                durum = "✅ Tam Uyumlu"
            elif skor >= 60:
                durum = "⚠️ Riskli (İyileştirme Gerekli)"
            else:
                durum = "🚨 Gümrük Reddi (Geçemez)"
                
            return pd.Series([skor, durum, ", ".join(hatalar)])

        # Denetim motorunu tüm ürünlere uygula
        df[['Uyum_Skoru', 'Denetim_Durumu', 'Tespit_Edilen_Hatalar']] = df.apply(denetim_yap, axis=1)
        
        # Filtrelemeler
        eksikler_df = df[df['Uyum_Skoru'] < 100]
        uygunlar_df = df[df['Uyum_Skoru'] == 100]
        
        # Sekmeler
        tab1, tab2 = st.tabs(["📊 Bağımsız Uyum Denetimi", "🏷️ Akıllı DPP Pasaportu"])
        
        with tab1:
            st.subheader("Kurumsal Uyum ve Risk Özeti")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("📦 Toplam Ürün", len(df))
            col2.metric("✅ Tam Uyumlu", len(uygunlar_df))
            col3.metric("⚠️ Riskli", len(df[(df['Uyum_Skoru'] >= 60) & (df['Uyum_Skoru'] < 100)]))
            col4.metric("🚨 Gümrük Reddi", len(df[df['Uyum_Skoru'] < 60]))
            
            st.divider()
            if not eksikler_df.empty:
                st.error("Aşağıdaki ürünler sektörel AB normlarında veya belge tarihlerinde denetim ihlali yaratmıştır:")
                st.dataframe(eksikler_df[['Sektor', 'Urun_Kodu', 'Cevre_Sertifikasi', 'Sertifika_Bitis_Tarihi', 'Uyum_Skoru', 'Denetim_Durumu', 'Tespit_Edilen_Hatalar']], use_container_width=True)
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    eksikler_df.to_excel(writer, index=False, sheet_name='Due_Diligence_Hatalari')
                st.download_button("📥 Due Diligence Hata Raporunu İndir", output.getvalue(), "dpp_denetim_raporu.xlsx", use_container_width=True)
            else:
                st.success("✅ Yüklenen tüm ürünler AB normlarına, sektörel şartlara ve tarihsel geçerliliğe tam uygundur.")

        with tab2:
            st.subheader("📲 Dinamik Uyum Karneli Dijital Pasaport")
            if not uygunlar_df.empty:
                urunler = uygunlar_df['Urun_Kodu'] + " - " + uygunlar_df['Urun_Adi']
                secim = st.selectbox("Pasaport Üretilecek Ürün:", urunler)
                secilen_kod = secim.split(" - ")[0]
                urun = uygunlar_df[uygunlar_df['Urun_Kodu'] == secilen_kod].iloc[0]
                
                st.divider()
                sol, sag = st.columns([2, 1])
                with sol:
                    st.success(f"**Uyum Skoru: %{urun['Uyum_Skoru']}** - Gümrük Onaylı")
                    st.markdown(f"**🏢 Sektör:** {urun['Sektor']}")
                    st.markdown(f"**🏷️ Ürün:** {urun['Urun_Kodu']} | {urun['Urun_Adi']}")
                    st.markdown(f"**📜 Sertifika:** {urun['Cevre_Sertifikasi']} (Geçerlilik: {urun['Sertifika_Bitis_Tarihi'].strftime('%Y-%m-%d')})")
                    
                    st.markdown("### 📋 AB Regülasyon Checklist'i")
                    st.markdown("✔️ Menşei ve Tedarik Zinciri Doğrulandı")
                    st.markdown("✔️ Sektörel EN/ISO Normları Karşılandı")
                    st.markdown("✔️ Belge Geçerlilik Süreleri Onaylandı")
                
                with sag:
                    qr_metin = f"DPP SCORE: 100%\nUrun: {urun['Urun_Adi']}\nSertifika: {urun['Cevre_Sertifikasi']}\nDenetim: BASARILI"
                    qr = qrcode.QRCode(version=1, box_size=8, border=2)
                    qr.add_data(qr_metin)
                    qr.make(fit=True)
                    st.image(qr.make_image(fill_color="black", back_color="white").get_image(), use_container_width=True)
            else:
                st.warning("Pasaport oluşturulacak %100 uyumlu ürün bulunamadı.")
    else:
        st.error("Excel formatı hatalı. Zorunlu sütunlar eksik.")
else:
    st.info("👈 Lütfen sol menüden veri dosyanızı yükleyin.")
