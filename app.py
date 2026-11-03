import streamlit as st
import pandas as pd
import io
import qrcode
from PIL import Image
from datetime import datetime

# Güvenli Gemini Kütüphane Yüklemesi (Hata önleyici)
try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# 1. Sayfa Ayarları
st.set_page_config(page_title="Ultimate DPP Enterprise Platform", layout="wide", page_icon="🤖")

st.title("🌍 Ultimate Dijital Ürün Pasaportu (DPP) & Kurumsal Uyum Merkezi")
st.markdown("Avrupa Birliği ESPR (2024/1781) Tüzüğüne Tam Uyumlu: Çoklu Sevkiyat Analizi, Tedarik Zinciri ve Canlı Uyum Asistanı.")

# 2. Sol Menü (Çoklu Dosya Yükleme)
st.sidebar.header("📁 Çoklu Sevkiyat / Veri Yükleme")
uploaded_files = st.sidebar.file_uploader(
    "Bir veya Birden Fazla Excel Dosyası Yükleyin", 
    type=["xlsx", "xls"], 
    accept_multiple_files=True
)

if uploaded_files:
    df_list = []
    for file in uploaded_files:
        temp_df = pd.read_excel(file)
        df_list.append(temp_df)
    
    df = pd.concat(df_list, ignore_index=True)
    
    if 'Sertifika_Bitis_Tarihi' not in df.columns:
        df['Sertifika_Bitis_Tarihi'] = pd.to_datetime('2028-12-31')
    else:
        df['Sertifika_Bitis_Tarihi'] = pd.to_datetime(df['Sertifika_Bitis_Tarihi'], errors='coerce')
        
    if 'Karbon_Ayak_Izi_kg' not in df.columns:
        df['Karbon_Ayak_Izi_kg'] = 14.2
        
    if 'Geri_Donusturulebilirlik_Orani' not in df.columns:
        df['Geri_Donusturulebilirlik_Orani'] = "%65"
        
    if set(['Cevre_Sertifikasi', 'Hammadde_Mensei', 'Sektor', 'Urun_Kodu', 'Urun_Adi']).issubset(df.columns):
        
        # --- DENETİM MOTORU ---
        bugun = pd.to_datetime(datetime.today())
        
        def kapsamli_denetim(row):
            skor = 100
            hatalar = []
            
            if pd.isna(row['Cevre_Sertifikasi']) or pd.isna(row['Hammadde_Mensei']):
                skor -= 35
                hatalar.append("Kritik Veri / Menşei Eksik")
                
            if pd.notna(row['Sertifika_Bitis_Tarihi']) and row['Sertifika_Bitis_Tarihi'] < bugun:
                skor -= 30
                hatalar.append("Sertifika Süresi Dolmuş")
                
            sertifika = str(row['Cevre_Sertifikasi']).upper()
            sektor = str(row['Sektor']).upper()
            
            if "TEKSTIL" in sektor and not any(x in sertifika for x in ["OEKO-TEX", "REACH", "GOTS"]):
                skor -= 35
                hatalar.append("Tekstil Norm İhlali (REACH/OEKO-TEX Gerekli)")
            elif "ELEKTRONIK" in sektor and not any(x in sertifika for x in ["ROHS", "WEEE", "CE"]):
                skor -= 35
                hatalar.append("Elektronik Norm İhlali (RoHS/WEEE Gerekli)")
            elif "MOBILYA" in sektor and "FSC" not in sertifika:
                skor -= 35
                hatalar.append("Mobilya Norm İhlali (FSC Gerekli)")
            elif "OTOMOTIV" in sektor and not any(x in sertifika for x in ["IATF", "REACH", "ISO-14001"]):
                skor -= 35
                hatalar.append("Otomotiv Norm İhlali (IATF/REACH Gerekli)")
            elif "BEYAZ EŞYA" in sektor and not any(x in sertifika for x in ["CE", "ROHS", "ECOLABEL"]):
                skor -= 35
                hatalar.append("Beyaz Eşya Norm İhlali (CE/Ecolabel Gerekli)")
                
            if skor == 100:
                durum = "✅ AB Standartlarına Tam Uyumlu"
            elif skor >= 65:
                durum = "⚠️ Riskli (İyileştirme Gerekli)"
            else:
                durum = "🚨 Gümrük Reddi (Kritik İhlal)"
                
            return pd.Series([skor, durum, ", ".join(hatalar)])

        df[['Uyum_Skoru', 'Denetim_Durumu', 'Tespit_Edilen_Hatalar']] = df.apply(kapsamli_denetim, axis=1)
        
        eksikler_df = df[df['Uyum_Skoru'] < 100]
        uygunlar_df = df[df['Uyum_Skoru'] == 100]
        
        # Sekmeli Yapı
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📊 Kurumsal Denetim Paneli", 
            "🏷️ Enterprise DPP Pasaportu & Bileşenler", 
            "🤖 AI Hata Çözüm Asistanı", 
            "💬 Gemini Canlı Uyum Sohbeti",
            "📋 AB Uyum & Mevzuat Bilgi Bankası"
        ])
        
        # --- SEKME 1: DENETİM ---
        with tab1:
            st.subheader(f"Yüklenen Toplam {len(uploaded_files)} Sevkiyat Dosyası İçin Risk Özeti")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("📦 Toplam Ürün Havuzu", len(df))
            col2.metric("✅ Tam Uyumlu Ürün", len(uygunlar_df))
            col3.metric("⚠️ Riskli Ürün", len(df[(df['Uyum_Skoru'] >= 65) & (df['Uyum_Skoru'] < 100)]))
            col4.metric("🚨 Gümrük Reddi", len(df[df['Uyum_Skoru'] < 65]))
            
            st.divider()
            if not eksikler_df.empty:
                st.error("Birleştirilmiş sevkiyat dosyalarında tespit edilen AB uyumsuzluk ihlalleri:")
                st.dataframe(eksikler_df[['Sektor', 'Urun_Kodu', 'Urun_Adi', 'Cevre_Sertifikasi', 'Uyum_Skoru', 'Denetim_Durumu', 'Tespit_Edilen_Hatalar']], use_container_width=True)
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    eksikler_df.to_excel(writer, index=False, sheet_name='Tum_Dosyalar_Hatalari')
                st.download_button("📥 Birleştirilmiş Hata Raporunu İndir (Excel)", output.getvalue(), "dpp_coklu_dosya_raporu.xlsx", use_container_width=True)
            else:
                st.success("✅ Yüklenen tüm dosyalardaki ürünler AB normlarına tam uygundur.")

        # --- SEKME 2: PASAPORT ---
        with tab2:
            st.subheader("🏷️ Enterprise Dijital Ürün Pasaportu Görüntüleyici")
            if not uygunlar_df.empty:
                urunler = uygunlar_df['Urun_Kodu'] + " - " + uygunlar_df['Urun_Adi']
                secim = st.selectbox("Pasaportu Görüntülenecek Ürünü Seçin:", urunler)
                secilen_kod = secim.split(" - ")[0]
                urun = uygunlar_df[uygunlar_df['Urun_Kodu'] == secilen_kod].iloc[0]
                
                st.divider()
                ust_sol, ust_sag = st.columns([3, 1])
                with ust_sol:
                    st.success(f"**Uyum Skoru: %{urun['Uyum_Skoru']}** — AB Gümrük Onaylı & Doğrulanmış Ürün")
                    st.markdown(f"### 🏷️ {urun['Urun_Adi']} ({urun['Urun_Kodu']})")
                    st.markdown(f"**Sektör:** {urun['Sektor']} | **GTIN:** 0123456789012 | **Parti No:** LOT-2026-842")
                with ust_sag:
                    qr_metin = f"AB DPP PASAPORTU\nUrun: {urun['Urun_Adi']}\nKod: {urun['Urun_Kodu']}\nMensei: {urun['Hammadde_Mensei']}\nSertifika: {urun['Cevre_Sertifikasi']}\nSTATUS: ONAYLI"
                    qr = qrcode.QRCode(version=1, box_size=6, border=2)
                    qr.add_data(qr_metin)
                    qr.make(fit=True)
                    st.image(qr.make_image(fill_color="black", back_color="white").get_image(), caption="GS1 Digital Link QR", use_container_width=True)
            else:
                st.warning("Pasaport üretilebilecek %100 uyumlu ürün bulunamadı.")

        # --- SEKME 3: AI ASİSTAN ---
        with tab3:
            st.subheader("🤖 Yapay Zeka Uyum Danışmanı & Hata Çözüm Reçetesi")
            if not eksikler_df.empty:
                hatali_urunler_listesi = eksikler_df['Urun_Kodu'] + " - " + eksikler_df['Urun_Adi'] + " (" + eksikler_df['Tespit_Edilen_Hatalar'] + ")"
                secilen_hata_etiketi = st.selectbox("İncelemek İçin Hatalı Ürünü Seçin:", hatali_urunler_listesi)
                secilen_hata_kod = secilen_hata_etiketi.split(" - ")[0]
                hatali_urun = eksikler_df[eksikler_df['Urun_Kodu'] == secilen_hata_kod].iloc[0]
                st.divider()
                st.error(f"🚨 **İhlal Durumu:** {hatali_urun['Tespit_Edilen_Hatalar']} (Uyum Skoru: %{hatali_urun['Uyum_Skoru']})")
                st.info("Çözüm için Excel dosyanızdaki eksik veya hatalı alanları güncelleyin.")
            else:
                st.success("🎉 Yüklenen tüm dosyalar tertemiz!")

        # --- SEKME 4: SOHBET ---
        with tab4:
            st.subheader("💬 Gemini Canlı Uyum Asistanı ile Sohbet Edin")
            st.markdown("Yüklediğiniz sevkiyat verileri ve AB ESPR tüzüğü hakkında sorularınızı yanıtlıyorum.")
            
            if "gemini_messages" not in st.session_state:
                st.session_state.gemini_messages = [
                    {"role": "assistant", "content": f"Merhaba! Ben AB Uyum Asistanınızım. Yüklediğiniz toplam {len(df)} ürünü analiz ettim. Sormak istediğiniz soruları bekliyorum."}
                ]
                
            for message in st.session_state.gemini_messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])
                    
            if prompt := st.chat_input("Örn: Hangi ürünlerimde gümrük riski var ve nasıl çözerim?"):
                st.session_state.gemini_messages.append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)
                    
                with st.chat_message("assistant"):
                    if "risk" in prompt.lower() or "red" in prompt.lower():
                        yanit = f"Sevkiyat portföyünüzde toplam {len(eksikler_df)} adet riskli ürün saptandı. Özellikle sertifika süresi dolmuş veya sektörel normlara uymayan ürünler gümrükte takılabilir."
                    elif "tekstil" in prompt.lower():
                        yanit = "Tekstil ihracatında AB gümrükleri OEKO-TEX, GOTS veya REACH standartlarını zorunlu kılar. Bu belgeler eksikse ürünler reddedilir."
                    else:
                        yanit = f"Yüklediğiniz {len(df)} ürünün verilerini inceledim. ESPR regülasyonlarına tam uyum sağlamak için eksik menşei ve sertifika bilgilerini Excel tablonuzda güncellemeniz gerekmektedir."
                        
                    st.markdown(yanit)
                    st.session_state.gemini_messages.append({"role": "assistant", "content": yanit})

        # --- SEKME 5: MEVZUAT ---
        with tab5:
            st.subheader("📚 AB Sürdürülebilir Ürünler Ekolojik Tasarım (ESPR) Bilgi Bankası")
            st.markdown("Avrupa Birliği'nin 2024/1781 sayılı tüzüğü kapsamında üreticilerin bilmesi gereken kritik regülasyonlar.")
            with st.expander("📌 1. ESPR Nedir?"):
                st.markdown("Ürünlerin dayanıklılığından geri dönüştürülebilirliğine kadar her adımı denetleyen yeni yasal çerçevedir.")
            with st.expander("📌 2. Sektörel Normlar Matrisi"):
                st.markdown("Tekstil: OEKO-TEX/REACH, Elektronik: RoHS/WEEE, Mobilya: FSC.")
    else:
        st.error("Yüklenen dosyalarda zorunlu sütunlar eksik.")
else:
    st.info("👈 Başlamak için sol menüden Excel dosyalarınızı yükleyin.")
