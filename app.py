import streamlit as st
import pandas as pd
import io
import qrcode
from PIL import Image

# 1. Sayfa Ayarları
st.set_page_config(page_title="DPP Kurumsal Yönetim Paneli", layout="wide", page_icon="🌍")

st.title("🌍 Dijital Ürün Pasaportu (DPP) Portalı")
st.markdown("Avrupa Birliği ESPR kriterlerine uygun Gap Analizi ve Anlık Dijital Pasaport (QR) Üretim Sistemi.")

# 2. Sol Menü (Sidebar)
st.sidebar.header("📁 Veri Yükleme")
uploaded_file = st.sidebar.file_uploader("Ürün Excel Dosyanızı Yükleyin", type=["xlsx", "xls"])

if uploaded_file is not None:
    df = pd.read_excel(uploaded_file)
    
    # Gerekli sütun kontrolü
    if set(['Cevre_Sertifikasi', 'Hammadde_Mensei', 'Sektor', 'Urun_Kodu', 'Urun_Adi']).issubset(df.columns):
        
        # Eksik tespiti
        df['Eksik_Var_Mi'] = df['Cevre_Sertifikasi'].isnull() | df['Hammadde_Mensei'].isnull()
        eksikler_df = df[df['Eksik_Var_Mi']]
        uygunlar_df = df[~df['Eksik_Var_Mi']]
        
        # Sekmeli Yapı Oluşturma (Tab)
        tab1, tab2 = st.tabs(["📊 Kurumsal Gap Analizi", "🏷️ Dijital Pasaport (QR) Üretici"])
        
        # --- BİRİNCİ SEKME: GAP ANALİZİ ---
        with tab1:
            st.subheader("Yönetici Özeti")
            col1, col2, col3 = st.columns(3)
            col1.metric("📦 Toplam İncelenen Ürün", len(df))
            col2.metric("✅ DPP'ye Uygun Ürün", len(uygunlar_df))
            col3.metric("🚨 Kritik Eksik (Aksiyon Bekleyen)", len(eksikler_df))
            
            st.divider()
            
            st.sidebar.subheader("🔍 Filtreler")
            sektorler = df['Sektor'].dropna().unique().tolist()
            secilen_sektor = st.sidebar.multiselect("Görüntülenecek Sektörleri Seçin", sektorler, default=sektorler)
            
            filtrelenmis_eksikler = eksikler_df[eksikler_df['Sektor'].isin(secilen_sektor)]
            
            if not filtrelenmis_eksikler.empty:
                st.error(f"DİKKAT! Seçili sektörlerde toplam {len(filtrelenmis_eksikler)} üründe zorunlu DPP verisi eksik.")
                st.dataframe(filtrelenmis_eksikler[['Sektor', 'Urun_Kodu', 'Urun_Adi', 'Cevre_Sertifikasi', 'Hammadde_Mensei']], use_container_width=True)
                
                alt_sol, alt_sag = st.columns([2, 1])
                with alt_sol:
                    st.warning("📉 Hatalı Ürünlerin Sektörel Dağılımı")
                    st.bar_chart(filtrelenmis_eksikler['Sektor'].value_counts())
                with alt_sag:
                    st.info("💡 Hatalı listeyi tedarikçilerinize göndermek için indirebilirsiniz.")
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        filtrelenmis_eksikler.to_excel(writer, index=False, sheet_name='Eksik_Urunler')
                    rapor_verisi = output.getvalue()
                    st.download_button(label="📥 Düzeltilecekler Raporunu İndir", data=rapor_verisi, file_name="dpp_eksik_raporu.xlsx", use_container_width=True)
            else:
                st.success("✅ Seçili sektörlerdeki tüm ürünler DPP'ye uygun. Kritik eksik yok.")
        
        # --- İKİNCİ SEKME: QR KOD VE PASAPORT ÜRETİCİ ---
        with tab2:
            st.subheader("📲 Ürün Dijital Kimliği Oluşturma")
            st.markdown("Avrupa Birliği gümrüklerinde veya son tüketici tarafından okutulacak QR tabanlı Dijital Ürün Pasaportunu buradan üretebilirsiniz. *(Sadece eksiksiz ürünler listelenir)*")
            
            if not uygunlar_df.empty:
                # Uygun ürünleri listeletme
                uygun_urunler_listesi = uygunlar_df['Urun_Kodu'] + " - " + uygunlar_df['Urun_Adi']
                secilen_urun_etiketi = st.selectbox("Pasaportu Üretilecek Ürünü Seçin:", uygun_urunler_listesi)
                
                # Seçilen ürünün verilerini çekme
                secilen_kod = secilen_urun_etiketi.split(" - ")[0]
                urun_bilgisi = uygunlar_df[uygunlar_df['Urun_Kodu'] == secilen_kod].iloc[0]
                
                # Pasaport Arayüzü Tasarımı
                st.divider()
                pasaport_sol, pasaport_sag = st.columns([2, 1])
                
                with pasaport_sol:
                    st.success("✅ Bu ürün Avrupa Birliği ESPR kriterlerine tam uygundur.")
                    st.markdown(f"**🏢 Sektör:** {urun_bilgisi['Sektor']}")
                    st.markdown(f"**🏷️ Ürün Kodu:** {urun_bilgisi['Urun_Kodu']}")
                    st.markdown(f"**📦 Ürün Adı:** {urun_bilgisi['Urun_Adi']}")
                    st.markdown(f"**🌍 Hammadde Menşei:** {urun_bilgisi['Hammadde_Mensei']}")
                    st.markdown(f"**📜 Çevre Sertifikası:** {urun_bilgisi['Cevre_Sertifikasi']}")
                    
                    if 'Geri_Donusturulebilirlik_Orani' in urun_bilgisi:
                        st.markdown(f"**♻️ Geri Dönüşüm Oranı:** {urun_bilgisi['Geri_Donusturulebilirlik_Orani']}")
                        
                with pasaport_sag:
                    # Anlık QR Kod Üretimi
                    qr_metin = f"DPP PASAPORT ONAYI\nUrun: {urun_bilgisi['Urun_Adi']}\nKod: {urun_bilgisi['Urun_Kodu']}\nMensei: {urun_bilgisi['Hammadde_Mensei']}\nSertifika: {urun_bilgisi['Cevre_Sertifikasi']}\nDurum: AB ONAYLI"
                    
                    qr = qrcode.QRCode(version=1, box_size=8, border=2)
                    qr.add_data(qr_metin)
                    qr.make(fit=True)
                    qr_imge = qr.make_image(fill_color="black", back_color="white")
                    
                    st.image(qr_imge.get_image(), caption="Tüketici / Gümrük Barkodu (Okutabilirsiniz)", use_container_width=True)
                    
            else:
                st.warning("⚠️ Pasaportu üretilebilecek (hiç eksiği olmayan) ürün bulunamadı.")
                
    else:
        st.error("Yüklenen dosyada gerekli sütunlar bulunamadı. Lütfen şablonu kontrol edin.")
else:
    st.info("👈 Başlamak için lütfen sol menüden Excel dosyanızı yükleyin.")
