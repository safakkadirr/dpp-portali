import streamlit as st
import pandas as pd
import io
import qrcode
from PIL import Image
from datetime import datetime

# 1. Sayfa Ayarları
st.set_page_config(page_title="Ultimate Multi-File DPP & AI Platform", layout="wide", page_icon="🌍")

st.title("🌍 Ultimate Dijital Ürün Pasaportu (DPP) & Çoklu Dosya Denetim Merkezi")
st.markdown("Avrupa Birliği ESPR Regülasyonu: Çoklu Sevkiyat Entegrasyonu, Yapay Zeka Hata Çözüm Asistanı ve Akıllı QR Pasaport.")

# 2. Sol Menü (Çoklu Dosya Yükleme Desteği)
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
        df['Karbon_Ayak_Izi_kg'] = 12.5
        
    if 'Geri_Donusturulebilirlik_Orani' not in df.columns:
        df['Geri_Donusturulebilirlik_Orani'] = "%50"
        
    if set(['Cevre_Sertifikasi', 'Hammadde_Mensei', 'Sektor', 'Urun_Kodu', 'Urun_Adi']).issubset(df.columns):
        
        # --- KAPSAMLI DENETİM MOTORU ---
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
        tab1, tab2, tab3, tab4 = st.tabs([
            "📊 Birleştirilmiş Kurumsal Denetim", 
            "🏷️ Akıllı DPP Pasaportu & QR", 
            "🤖 AI Uyum & Hata Çözüm Asistanı", 
            "📋 ESPR Mevzuat Kılavuzu"
        ])
        
        # --- SEKME 1: DENETİM ---
        with tab1:
            st.subheader(f"Yüklenen Toplam {len(uploaded_files)} Dosya İçin Birleştirilmiş Risk Özeti")
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

        # --- SEKME 2: PASAPORT & QR ---
        with tab2:
            st.subheader("📲 Ürün Dijital Kimliği ve QR Pasaport Merkezi")
            if not uygunlar_df.empty:
                urunler = uygunlar_df['Urun_Kodu'] + " - " + uygunlar_df['Urun_Adi']
                secim = st.selectbox("Pasaport Görüntülenecek Ürünü Seçin:", urunler)
                secilen_kod = secim.split(" - ")[0]
                urun = uygunlar_df[uygunlar_df['Urun_Kodu'] == secilen_kod].iloc[0]
                
                st.divider()
                sol, sag = st.columns([2, 1])
                with sol:
                    st.success(f"**Uyum Skoru: %{urun['Uyum_Skoru']}** — AB Gümrük Onaylı")
                    st.markdown(f"**🏢 Sektör:** {urun['Sektor']}")
                    st.markdown(f"**🏷️ Ürün Kodu & Adı:** {urun['Urun_Kodu']} | {urun['Urun_Adi']}")
                    tarih = urun['Sertifika_Bitis_Tarihi']
                    tarih_metni = tarih.strftime('%Y-%m-%d') if pd.notna(tarih) else "Süresiz / Belirtilmemiş"
                    st.markdown(f"**📜 Çevre Sertifikası:** {urun['Cevre_Sertifikasi']} (Geçerlilik: {tarih_metni})")
                    st.markdown(f"**🌍 Hammadde Menşei:** {urun['Hammadde_Mensei']}")
                    st.markdown(f"**♻️ Geri Dönüştürülmüş İçerik:** {urun['Geri_Donusturulebilirlik_Orani']}")
                    st.markdown(f"**💨 Karbon Ayak İzi:** {urun['Karbon_Ayak_Izi_kg']} kg CO2e")
                with sag:
                    qr_metin = f"AB DPP PASAPORTU\nUrun: {urun['Urun_Adi']}\nKod: {urun['Urun_Kodu']}\nMensei: {urun['Hammadde_Mensei']}\nSertifika: {urun['Cevre_Sertifikasi']}\nSTATUS: ONAYLI"
                    qr = qrcode.QRCode(version=1, box_size=8, border=2)
                    qr.add_data(qr_metin)
                    qr.make(fit=True)
                    st.image(qr.make_image(fill_color="black", back_color="white").get_image(), use_container_width=True)
            else:
                st.warning("Pasaport üretilebilecek %100 uyumlu ürün bulunamadı.")

        # --- SEKME 3: AI ASİSTAN ---
        with tab3:
            st.subheader("🤖 Yapay Zeka Uyum Danışmanı & Hata Çözüm Reçetesi")
            st.markdown("Yüklediğiniz tüm dosyalar taranır; asistanımız hatalı satırları süzerek size nokta atışı düzeltme talimatı verir.")
            
            if not eksikler_df.empty:
                hatali_urunler_listesi = eksikler_df['Urun_Kodu'] + " - " + eksikler_df['Urun_Adi'] + " (" + eksikler_df['Tespit_Edilen_Hatalar'] + ")"
                secilen_hata_etiketi = st.selectbox("İncelemek İçin Hatalı Ürünü Seçin:", hatali_urunler_listesi)
                
                secilen_hata_kod = secilen_hata_etiketi.split(" - ")[0]
                hatali_urun = eksikler_df[eksikler_df['Urun_Kodu'] == secilen_hata_kod].iloc[0]
                
                st.divider()
                st.error(f"🚨 **İhlal Durumu:** {hatali_urun['Tespit_Edilen_Hatalar']} (Uyum Skoru: %{hatali_urun['Uyum_Skoru']})")
                
                hata_metni = hatali_urun['Tespit_Edilen_Hatalar']
                sektor_bilgisi = hatali_urun['Sektor']
                
                st.markdown("### 💡 Yapay Zeka Uzman Tavsiyesi")
                if "Kritik Veri" in hata_metni:
                    st.warning(f"**Analiz:** {hatali_urun['Urun_Kodu']} kodlu üründe menşei veya çevre sertifikası eksik.")
                    st.info("**Çözüm:** Excel dosyanızdaki ilgili satıra hammadde menşei ve geçerli sertifikayı ekleyip dosyayı tekrar sisteme yükleyin.")
                elif "Süresi Dolmuş" in hata_metni:
                    st.warning("**Analiz:** Ürünün sertifika geçerlilik tarihi geçmiş.")
                    st.info("**Çözüm:** `Sertifika_Bitis_Tarihi` sütununu güncel ileri bir tarihe güncelleyin.")
                else:
                    st.warning(f"**Analiz:** **{sektor_bilgisi}** sektörü için girilen sertifika AB EN normlarına uymuyor.")
                    st.info("**Çözüm:** Sektöre özel zorunlu standardı (Örn: Tekstil için REACH/OEKO-TEX) ekleyin.")
            else:
                st.success("🎉 Yüklenen tüm dosyalar tertemiz!")

        # --- SEKME 4: MEVZUAT ---
        with tab4:
            st.subheader("📚 AB ESPR Rehberi")
            st.markdown("Çoklu dosya birleştirme desteğiyle tüm tedarik zinciri tek ekranda denetlenir.")
    else:
        st.error("Yüklenen dosyalarda zorunlu sütunlar eksik.")
else:
    st.info("👈 Başlamak için sol menüden **birden fazla** Excel dosyasını seçip yükleyin.")
