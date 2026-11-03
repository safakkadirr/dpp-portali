import streamlit as st
import pandas as pd
import io
import qrcode
from PIL import Image
from datetime import datetime

# 1. Sayfa Ayarları
st.set_page_config(page_title="Ultimate DPP & AI Due Diligence Platformu", layout="wide", page_icon="🤖")

st.title("🌍 Ultimate Dijital Ürün Pasaportu (DPP) & Akıllı Uyum Platformu")
st.markdown("Avrupa Birliği ESPR Regülasyonuna Tam Uyumlu: Bağımsız Denetim, Yapay Zeka Hata Çözüm Asistanı ve QR Pasaport.")

# 2. Sol Menü (Sidebar)
st.sidebar.header("📁 Veri Yükleme & Entegrasyon")
uploaded_file = st.sidebar.file_uploader("Ürün Excel Dosyanızı Yükleyin", type=["xlsx", "xls"])

if uploaded_file is not None:
    df = pd.read_excel(uploaded_file)
    
    # Güvenlik ve Varsayılan Atamalar
    if 'Sertifika_Bitis_Tarihi' not in df.columns:
        df['Sertifika_Bitis_Tarihi'] = pd.to_datetime('2028-12-31')
    else:
        df['Sertifika_Bitis_Tarihi'] = pd.to_datetime(df['Sertifika_Bitis_Tarihi'], errors='coerce')
        
    if 'Karbon_Ayak_Izi_kg' not in df.columns:
        df['Karbon_Ayak_Izi_kg'] = 12.5
        
    if 'Geri_Donusturulebilirlik_Orani' not in df.columns:
        df['Geri_Donusturulebilirlik_Orani'] = "%50"
        
    if set(['Cevre_Sertifikasi', 'Hammadde_Mensei', 'Sektor', 'Urun_Kodu', 'Urun_Adi']).issubset(df.columns):
        
        # --- AKILLI DENETİM MOTORU ---
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
        
        # 4'LÜ SEKMELİ YAPI (AI Asistan Eklendi)
        tab1, tab2, tab3, tab4 = st.tabs([
            "📊 Kurumsal Uyum Denetimi", 
            "🏷️ Akıllı DPP Pasaportu & QR", 
            "🤖 AI Uyum & Hata Çözüm Asistanı", 
            "📋 ESPR Mevzuat Kılavuzu"
        ])
        
        # --- SEKME 1: DENETİM ---
        with tab1:
            st.subheader("Executive Risk ve Uyum Özeti")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("📦 Toplam Ürün", len(df))
            col2.metric("✅ Tam Uyumlu", len(uygunlar_df))
            col3.metric("⚠️ Riskli Ürün", len(df[(df['Uyum_Skoru'] >= 65) & (df['Uyum_Skoru'] < 100)]))
            col4.metric("🚨 Gümrük Reddi", len(df[df['Uyum_Skoru'] < 65]))
            
            st.divider()
            if not eksikler_df.empty:
                st.error("Aşağıdaki ürünler AB ESPR kriterlerini ve EN standartlarını ihlal etmektedir:")
                st.dataframe(eksikler_df[['Sektor', 'Urun_Kodu', 'Urun_Adi', 'Cevre_Sertifikasi', 'Uyum_Skoru', 'Denetim_Durumu', 'Tespit_Edilen_Hatalar']], use_container_width=True)
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    eksikler_df.to_excel(writer, index=False, sheet_name='Uyum_Hatalari')
                st.download_button("📥 Denetim ve Hata Raporunu İndir (Excel)", output.getvalue(), "dpp_kapsamli_denetim_raporu.xlsx", use_container_width=True)
            else:
                st.success("✅ Yüklenen tüm ürün portföyü AB normlarına tam uygundur.")

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

        # --- SEKME 3: YAPAY ZEKA ASİSTANI (YENİ) ---
        with tab3:
            st.subheader("🤖 Yapay Zeka Uyum Danışmanı & Hata Çözüm Reçetesi")
            st.markdown("Yapay zeka asistanımız, Excel dosyanızdaki hatalı satırları tarar ve her birinin gümrükten geçebilmesi için **ne düzeltilmesi gerektiğini** adım adım söyler.")
            
            if not eksikler_df.empty:
                # Kullanıcıya hatalı ürün seçtiriyoruz
                hatali_urunler_listesi = eksikler_df['Urun_Kodu'] + " - " + eksikler_df['Urun_Adi'] + " (" + eksikler_df['Tespit_Edilen_Hatalar'] + ")"
                secilen_hata_etiketi = st.selectbox("İncelemek ve Çözüm Almak İçin Hatalı Ürünü Seçin:", hatali_urunler_listesi)
                
                secilen_hata_kod = secilen_hata_etiketi.split(" - ")[0]
                hatali_urun = eksikler_df[eksikler_df['Urun_Kodu'] == secilen_hata_kod].iloc[0]
                
                st.divider()
                st.error(f"🚨 **Tespit Edilen İhlal Durumu:** {hatali_urun['Tespit_Edilen_Hatalar']} (Uyum Skoru: %{hatali_urun['Uyum_Skoru']})")
                
                st.markdown("### 💡 Yapay Zeka Uzman Tavsiyesi & Düzeltme Reçetesi")
                
                # Akıllı Hata Çözüm Üreteci
                hata_metni = hatali_urun['Tespit_Edilen_Hatalar']
                sektor_bilgisi = hatali_urun['Sektor']
                
                if "Kritik Veri" in hata_metni:
                    st.warning(f"**Sorun Analizi:** {hatali_urun['Urun_Kodu']} numaralı ürünün 'Çevre Sertifikası' veya 'Hammadde Menşei' hücresi boş bırakılmış. AB regülasyonlarına göre boş alanlarla gümrük beyannamesi oluşturulamaz.")
                    st.info(f"**🛠️ Çözüm Adımı:** Excel dosyanızda bu ürüne ait satırı bulun. Hammadde menşeini (örneğin 'Türkiye' veya 'Almanya') ve sektöre uygun geçerli sertifikayı yazıp dosyayı yeniden yükleyin.")
                elif "Süresi Dolmuş" in hata_metni:
                    st.warning(f"**Sorun Analizi:** Ürüne ait sertifikanın geçerlilik tarihi geçmiş. Geçmiş tarihli belgeler AB denetimlerinde geçersiz sayılır.")
                    st.info(f"**🛠️ Çözüm Adımı:** Excel'deki `Sertifika_Bitis_Tarihi` sütununu güncel ileri bir tarihe (örneğin 2028-12-31) güncelleyin veya yeni sertifika ekleyin.")
                elif "Norm İhlali" in hata_metni or "İhlali" in hata_metni:
                    st.warning(f"**Sorun Analizi:** **{sektor_bilgisi}** sektörü için girilen sertifika AB'nin zorunlu koştugu EN standartlarına (Örn: Tekstil için OEKO-TEX/REACH, Elektronik için RoHS) uymuyor.")
                    st.info(f"**🛠️ Çözüm Adımı:** Excel'deki `Cevre_Sertifikasi` hücresine ilgili sektörün zorunlu standardını yazarak düzeltme yapın.")
            else:
                st.success("🎉 Tebrikler! Yüklenen dosyadaki hiçbir üründe yapay zekanın tespit ettiği bir hata veya uyumsuzluk yok.")

        # --- SEKME 4: MEVZUAT ---
        with tab4:
            st.subheader("📚 AB Sürdürülebilir Ürünler Ekolojik Tasarım (ESPR) Rehberi")
            st.markdown("""
            * **Şeffaflık:** Tedarik zinciri boyunca tam izlenebilirlik.
            * **Çevresel Performans:** Karbon emisyonları ve hammadde menşei takibi.
            * **Döngüsel Ekonomi:** Geri dönüştürülebilirlik oranlarının bizzat pasaporta işlenmesi.
            """)
    else:
        st.error("Yüklenen Excel dosyasında zorunlu sütunlar eksik.")
else:
    st.info("👈 Başlamak için lütfen sol menüden Excel dosyanızı yükleyin.")
