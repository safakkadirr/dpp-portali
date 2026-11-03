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
                hat
