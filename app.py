"""
DPP Hazırlık Platformu — Streamlit arayüzü

Çalıştırma:  streamlit run app.py
İş mantığı dpp_core.py dosyasındadır; bu dosya yalnızca ekranları içerir.
"""

import io
import json
from dataclasses import replace

import pandas as pd
import streamlit as st

import dpp_core as dc

try:
    import qrcode
    QR_VAR = True
except ImportError:
    QR_VAR = False

# ---------------------------------------------------------------------------
# Sayfa ayarları ve oturum durumu
# ---------------------------------------------------------------------------

st.set_page_config(page_title="DPP Hazırlık Platformu", layout="wide", page_icon="🌍")

ss = st.session_state
for anahtar, varsayilan in (("veri", None), ("imza", None), ("denetim_izi", []), ("sohbet", []), ("okuma_hatalari", []),
                            ("duzenleme_sayac", 0)):
    if anahtar not in ss:
        ss[anahtar] = varsayilan

SEVIYE_SIMGE = {"Kritik": "🔴", "Yüksek": "🟠", "Orta": "🟡", "Bilgi": "🔵"}
BELGE_SIMGE = {"Geçerli": "🟢", "60 gün içinde doluyor": "🟡", "30 gün içinde doluyor": "🟠",
               "Süresi dolmuş": "🔴", "Bitiş tarihi yok": "⚪"}
UYARI_METNI = ("Bu program bir **hazırlık ve ön kontrol** aracıdır. Gümrük, piyasa gözetimi veya onaylanmış "
               "kuruluş kararı yerine geçmez. Mevzuat hükümleri ve tarihleri resmi kaynaklardan doğrulanmalıdır.")


def kayit(islem: str, detay: str):
    ss.denetim_izi.append(dc.denetim_kaydi(ss.get("hazirlayan", ""), islem, detay))


def gizli(anahtar, varsayilan=None):
    try:
        return st.secrets.get(anahtar, varsayilan)
    except Exception:
        return varsayilan


def goster(df: pd.DataFrame) -> pd.DataFrame:
    """Karışık tipli sütunları ekranda güvenle göstermek için metne çevirir."""
    kopya = df.copy()
    for kolon in kopya.columns:
        if kopya[kolon].dtype == object:
            kopya[kolon] = kopya[kolon].map(lambda v: dc.metin(v, yok_bos=False) or None)
    return kopya


def qr_png(metin: str) -> bytes:
    img = qrcode.make(metin, box_size=8, border=2)
    tampon = io.BytesIO()
    img.save(tampon, format="PNG")
    return tampon.getvalue()


# ---------------------------------------------------------------------------
# Sol menü
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("🌍 DPP Hazırlık")
    st.caption(f"Sürüm {dc.SURUM} · Mevzuat gözden geçirme: {dc.MEVZUAT_GOZDEN_GECIRME}")

    st.text_input("Firma unvanı", key="firma", placeholder="Örnek İhracat A.Ş.")
    st.text_input("Hazırlayan", key="hazirlayan", placeholder="Ad Soyad",
                  help="Denetim izinde ve raporlarda görünür.")
    st.text_input("Pasaport adresi (çözümleyici)", key="cozumleyici", value="https://dpp.ornek.com.tr",
                  help="QR kodun yönlendireceği alan adı. Kendi alan adınızı yazın; GS1 Digital Link biçiminde adres üretilir.")

    st.divider()
    st.subheader("📁 Veri yükleme")
    dosyalar = st.file_uploader("Bir veya birden fazla Excel dosyası", type=["xlsx", "xls"], accept_multiple_files=True,
                                help="Urunler, Belgeler ve Tedarik_Zinciri sayfaları okunur. Eski tek sayfalı dosyalar da desteklenir.")
    st.download_button("📄 Boş şablonu indir (Excel)", dc.sablon_excel(), "dpp_veri_sablonu.xlsx",
                       help="Sütun açıklamaları ve örnek satırlar içerir.")
    ornek_tikla = st.button("🧪 Örnek veriyle dene", help="8 farklı sektörden, bilerek eksikler içeren örnek veri yükler.")

    st.divider()
    st.caption(UYARI_METNI)

# ---------------------------------------------------------------------------
# Veriyi yükle
# ---------------------------------------------------------------------------

if dosyalar:
    imza = tuple((f.name, f.size) for f in dosyalar)
    if ss.imza != imza:
        setler, hatalar = [], []
        for f in dosyalar:
            try:
                setler.append(dc.excel_oku(f, f.name))
            except Exception as hata:
                hatalar.append(f"{f.name}: dosya okunamadı ({hata})")
        ss.veri = dc.veri_birlestir(setler)
        ss.imza = imza
        ss.okuma_hatalari = hatalar
        ss.sohbet = []
        kayit("Veri yükleme", f"{', '.join(f.name for f in dosyalar)} — {len(ss.veri.urunler)} ürün satırı, "
                              f"{len(ss.veri.belgeler)} belge, {len(ss.veri.tedarik)} tedarik aşaması")
elif ornek_tikla:
    ss.veri = dc.ornek_veri()
    ss.imza = "ornek"
    ss.okuma_hatalari = []
    ss.sohbet = []
    kayit("Örnek veri", "Örnek veri seti yüklendi")
elif isinstance(ss.imza, tuple):
    # Kullanıcı dosyaları kaldırdı
    ss.veri, ss.imza = None, None
    kayit("Veri kaldırma", "Yüklenen dosyalar kaldırıldı")

# ---------------------------------------------------------------------------
# Başlık
# ---------------------------------------------------------------------------

st.title("Dijital Ürün Pasaportu Hazırlık Platformu")
st.markdown("AB **ESPR (2024/1781)** ve ilgili ürün mevzuatına hazırlık: veri kontrolü, belge takibi, "
            "pasaport taslağı ve çözüm reçetesi — **tüm sektörlerdeki ihracatçılar için**.")

if ss.veri is None:
    st.info("👈 Başlamak için sol menüden Excel dosyanızı yükleyin, **boş şablonu** indirin ya da **örnek veriyle deneyin**.")
    a, b, c = st.columns(3)
    with a:
        st.markdown("#### 1. Veriyi yükleyin")
        st.markdown("Ürünler, belgeler (sertifika, beyan, test raporu) ve tedarik zinciri aşamaları. "
                    "Birden fazla dosya birleştirilir; eski formatlı dosyalar da okunur.")
    with b:
        st.markdown("#### 2. Eksikleri görün")
        st.markdown("Her ürün, sektörüne uygun kurallarla kontrol edilir. Her eksik için **dayanak** ve "
                    "**adım adım çözüm** gösterilir.")
    with c:
        st.markdown("#### 3. Pasaport taslağını alın")
        st.markdown("GS1 Digital Link QR kodu, erişim seviyesine göre (kamu / alıcı / otorite) pasaport görünümü "
                    "ve JSON-LD çıktısı.")
    st.markdown("**Kapsanan sektörler:** " + ", ".join(s.ad for s in dc.SEKTORLER if s.kod != "diger") + " ve diğerleri.")
    st.stop()

# ---------------------------------------------------------------------------
# Değerlendirme
# ---------------------------------------------------------------------------

veri: dc.VeriSeti = ss.veri
ozet, bulgular, kasa = dc.degerlendir(veri)

if ss.okuma_hatalari or veri.uyarilar:
    with st.expander(f"⚠️ Veri okuma notları ({len(ss.okuma_hatalari) + len(veri.uyarilar)})"):
        for h in ss.okuma_hatalari:
            st.error(h)
        for u in veri.uyarilar:
            st.warning(u)
        tekrar = dc.yinelenenler(veri.urunler)
        if not tekrar.empty:
            st.markdown("**Yinelenen kayıtlar**")
            st.dataframe(goster(tekrar), hide_index=True)

if ozet.empty:
    st.error("Değerlendirilecek ürün bulunamadı. Dosyanızda 'Urun_Kodu' sütunu ve en az bir dolu satır olmalı.")
    st.stop()

ozet_ekran = ozet.copy()
ozet_ekran.insert(0, " ", ozet_ekran["Durum"].map(dc.DURUM_SIMGE))

sekmeler = st.tabs([
    "📊 Genel Bakış", "🔎 Eksikler ve Çözüm", "🏷️ Pasaport Taslağı", "📁 Belge Kasası",
    "✏️ Veri Düzenleme", "⚖️ Kural Seti", "💬 Uyum Asistanı", "📚 Mevzuat Rehberi", "🧾 Denetim İzi",
])

# ---------------------------------------------------------------------------
# 1. Genel bakış
# ---------------------------------------------------------------------------

with sekmeler[0]:
    durum_sayilari = ozet["Durum"].value_counts()
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Ürün", len(ozet))
    m2.metric("🟢 Hazır", int(durum_sayilari.get("Hazır", 0)))
    m3.metric("🟡 Eksikleri var", int(durum_sayilari.get("Eksikleri var", 0)))
    m4.metric("🔴 Yüksek risk", int(durum_sayilari.get("Yüksek risk", 0)))
    m5.metric("Ortalama hazırlık", f"%{ozet['Hazirlik_Skoru'].mean():.0f}")
    st.caption("**Hazır:** skor ≥ 85 ve kritik eksik yok · **Eksikleri var:** kritik eksik yok, skor < 85 · "
               "**Yüksek risk:** en az bir kritik eksik (AB'ye arzda sorun çıkma olasılığı yüksek)")

    f1, f2 = st.columns(2)
    sektor_sec = f1.multiselect("Sektör", sorted(ozet["Sektor"].unique()))
    durum_sec = f2.multiselect("Durum", ["Yüksek risk", "Eksikleri var", "Hazır"])
    filtre = ozet_ekran.copy()
    if sektor_sec:
        filtre = filtre[filtre["Sektor"].isin(sektor_sec)]
    if durum_sec:
        filtre = filtre[filtre["Durum"].isin(durum_sec)]

    st.dataframe(
        filtre.drop(columns=["Sektor_Kodu"]).sort_values("Hazirlik_Skoru"),
        hide_index=True,
        column_config={
            "Hazirlik_Skoru": st.column_config.ProgressColumn("Hazırlık skoru", min_value=0, max_value=100, format="%.0f"),
            "Urun_Kodu": "Ürün kodu", "Urun_Adi": "Ürün adı", "Sektor": "Sektör", "Tuketici_Urunu": "Tüketici ürünü",
            "Kritik_Eksik": "Kritik eksik", "Eksik_Sayisi": "Toplam eksik", "Uygulanan_Kural": "Uygulanan kural",
            "Kaynak_Dosya": "Kaynak",
        },
    )

    g1, g2 = st.columns(2)
    with g1:
        st.markdown("**Sektöre göre durum dağılımı**")
        dagilim = pd.crosstab(ozet["Sektor"], ozet["Durum"])
        st.bar_chart(dagilim[[k for k in ["Hazır", "Eksikleri var", "Yüksek risk"] if k in dagilim.columns]])
    with g2:
        st.markdown("**En sık görülen eksikler**")
        eksikler = bulgular[bulgular["Sonuc"] == "Eksik"]
        if eksikler.empty:
            st.success("Tüm kurallar karşılanıyor.")
        else:
            sik = (eksikler.groupby(["Kural_Kodu", "Kural", "Seviye"]).size().reset_index(name="Ürün sayısı")
                   .sort_values("Ürün sayısı", ascending=False))
            sik.insert(0, " ", sik["Seviye"].map(SEVIYE_SIMGE))
            st.dataframe(sik, hide_index=True)

    rapor = dc.rapor_excel(ozet, bulgular, kasa, ss.denetim_izi, ss.get("firma", ""), ss.get("hazirlayan", ""))
    if st.download_button("📥 Ön kontrol raporunu indir (Excel)", rapor, "dpp_on_kontrol_raporu.xlsx", type="primary"):
        kayit("Rapor indirme", "Ön kontrol raporu (Excel)")

# ---------------------------------------------------------------------------
# 2. Eksikler ve çözüm reçetesi
# ---------------------------------------------------------------------------

with sekmeler[1]:
    sirali = ozet.sort_values(["Kritik_Eksik", "Hazirlik_Skoru"], ascending=[False, True])
    etiketler = {f"{dc.DURUM_SIMGE[r.Durum]} {r.Urun_Kodu} — {r.Urun_Adi} (skor {r.Hazirlik_Skoru:g})": r.Urun_Kodu
                 for r in sirali.itertuples()}
    secim = st.selectbox("Ürün seçin (en riskliden başlayarak)", list(etiketler), key="recete_urun")
    kod = etiketler[secim]
    o = ozet[ozet["Urun_Kodu"] == kod].iloc[0]
    urun_bulgulari = bulgular[bulgular["Urun_Kodu"] == kod]
    eksik = urun_bulgulari[urun_bulgulari["Sonuc"] == "Eksik"]
    uygun = urun_bulgulari[urun_bulgulari["Sonuc"] == "Uygun"]

    mesaj = (f"**{o['Durum']}** · Hazırlık skoru **{o['Hazirlik_Skoru']:g}** · {o['Sektor']} · "
             f"{len(urun_bulgulari)} kural uygulandı, {len(eksik)} eksik ({o['Kritik_Eksik']} kritik)")
    {"Yüksek risk": st.error, "Eksikleri var": st.warning, "Hazır": st.success}[o["Durum"]](mesaj)

    if eksik.empty:
        st.success("Bu ürün için eksik bulunmadı.")
    for r in eksik.itertuples():
        kural = dc.KURAL_SOZLUK[r.Kural_Kodu]
        with st.expander(f"{SEVIYE_SIMGE[r.Seviye]} [{r.Kural_Kodu}] {r.Kural} — {r.Seviye}", expanded=r.Seviye == "Kritik"):
            st.markdown(f"**Tespit:** {r.Detay}")
            st.markdown(f"**Dayanak:** {r.Dayanak}  \n**Mevzuat durumu:** {r.Mevzuat_Durumu}")
            st.markdown("**Yapılacaklar:**\n" + "\n".join(f"{i}. {a}" for i, a in enumerate(kural.recete, 1)))

    with st.expander(f"✅ Karşılanan kurallar ({len(uygun)})"):
        st.dataframe(uygun[["Kural_Kodu", "Kural", "Seviye", "Detay"]], hide_index=True)

# ---------------------------------------------------------------------------
# 3. Pasaport taslağı
# ---------------------------------------------------------------------------

with sekmeler[2]:
    urun_tablosu = dc.tekil_urunler(veri.urunler)
    p_etiketler = {f"{dc.DURUM_SIMGE[r.Durum]} {r.Urun_Kodu} — {r.Urun_Adi}": r.Urun_Kodu for r in ozet.itertuples()}
    s1, s2 = st.columns([3, 2])
    p_secim = s1.selectbox("Ürün", list(p_etiketler), key="pasaport_urun")
    erisim = s2.radio("Görünüm", dc.ERISIM_SEVIYELERI, horizontal=True,
                      help="ESPR'de pasaport alanlarına erişim kişiye göre değişir. Kamu en dar, Otorite en geniş görünümdür.")
    p_kod = p_etiketler[p_secim]
    satir = urun_tablosu[urun_tablosu["Urun_Kodu"] == p_kod].iloc[0]
    p_ozet = ozet[ozet["Urun_Kodu"] == p_kod].iloc[0]
    p_belgeler = dc.urun_belgeleri(kasa, p_kod)
    p_tedarik = veri.tedarik[veri.tedarik["Urun_Kodu"] == p_kod]
    p_tedarik = (p_tedarik.assign(_sira=pd.to_numeric(p_tedarik["Asama_Sira"], errors="coerce"))
                 .sort_values("_sira").drop(columns="_sira"))
    adres = dc.digital_link(satir, ss.get("cozumleyici"))

    st.divider()
    sol, sag = st.columns([3, 1])
    with sol:
        st.caption("PASAPORT TASLAĞI — resmi kayıt değildir")
        st.markdown(f"### {dc.metin(satir.get('Urun_Adi'))}")
        gtin_ok, gtin_mesaj = dc.gtin_dogrula(satir.get("GTIN"))
        st.markdown(f"**Pasaport kimliği:** `{dc.pasaport_kimligi(satir)}`  \n"
                    f"**GTIN:** {dc.metin(satir.get('GTIN')) or '—'} {'✅' if gtin_ok else '⚠️ ' + gtin_mesaj}")
        bilgi = f"Hazırlık: **{p_ozet['Durum']}** (skor {p_ozet['Hazirlik_Skoru']:g}). Ayrıntılar 'Eksikler ve Çözüm' sekmesinde."
        {"Yüksek risk": st.error, "Eksikleri var": st.warning, "Hazır": st.success}[p_ozet["Durum"]](bilgi)
        if not gtin_ok:
            st.caption("Geçerli GTIN olmadığı için QR adresi ürün kodu ile oluşturuldu; GS1 Digital Link biçiminde değildir.")
    with sag:
        if QR_VAR:
            st.image(qr_png(adres), caption="GS1 Digital Link (taslak)" if gtin_ok else "Ürün bağlantısı (taslak)", width=200)
        else:
            st.warning("QR için 'qrcode' paketi kurulu değil.")
        st.code(adres, language=None)

    gizlenen = sum(1 for _, _, k, e in dc.PASAPORT_ALANLARI if not dc.gorunur_mu(e, erisim) and not dc.bos_mu(satir.get(k), False))
    bolumler = list(dict.fromkeys(b for b, *_ in dc.PASAPORT_ALANLARI))
    alt = st.tabs(bolumler + ["Belgeler", "Tedarik zinciri"])
    for i, bolum in enumerate(bolumler):
        with alt[i]:
            satirlar = []
            for b, etiket, kolon, seviye in dc.PASAPORT_ALANLARI:
                if b != bolum or not dc.gorunur_mu(seviye, erisim):
                    continue
                if kolon == "Sektor":
                    deger = dc.sektor_bul(satir.get("Sektor")).ad
                else:
                    deger = dc.metin(satir.get(kolon), yok_bos=False)
                satirlar.append({"Alan": etiket, "Değer": deger or "—", "Erişim": seviye})
            if satirlar:
                st.dataframe(pd.DataFrame(satirlar), hide_index=True)
            else:
                st.caption("Bu görünümde gösterilecek alan yok.")
    with alt[len(bolumler)]:
        if p_belgeler.empty:
            st.caption("Bu ürüne bağlı belge yok.")
        else:
            kolonlar = ["Kanonik_Tur", "Kategori", "Gecerlilik_Bitis", "Durum"]
            if dc.gorunur_mu("Alıcı (B2B)", erisim):
                kolonlar[1:1] = ["Belge_No", "Duzenleyen"]
            gosterim = p_belgeler[kolonlar].copy()
            gosterim.insert(0, " ", p_belgeler["Durum"].map(BELGE_SIMGE))
            st.dataframe(goster(gosterim), hide_index=True)
    with alt[len(bolumler) + 1]:
        if not dc.gorunur_mu("Alıcı (B2B)", erisim):
            st.caption("Tedarik zinciri ayrıntıları Alıcı ve Otorite görünümlerinde gösterilir.")
        elif p_tedarik.empty:
            st.caption("Bu ürün için tedarik zinciri aşaması girilmemiş.")
        else:
            st.dataframe(goster(p_tedarik[["Asama_Sira", "Asama", "Tedarikci", "Ulke", "Belge_No"]]), hide_index=True)
    if gizlenen:
        st.caption(f"Bu görünümde {gizlenen} dolu alan gizlendi (erişim seviyesi).")

    jsonld = dc.pasaport_jsonld(satir, p_belgeler, p_tedarik, p_ozet, ss.get("cozumleyici"), erisim, ss.get("hazirlayan", ""))
    j1, j2 = st.columns(2)
    if j1.download_button("⬇️ Bu pasaport taslağını indir (JSON-LD)", json.dumps(jsonld, ensure_ascii=False, indent=2),
                          f"{p_kod}_pasaport_{erisim.split()[0].lower()}.jsonld", mime="application/ld+json"):
        kayit("Pasaport indirme", f"{p_kod} ({erisim})")
    tum = [dc.pasaport_jsonld(r, dc.urun_belgeleri(kasa, r["Urun_Kodu"]),
                              veri.tedarik[veri.tedarik["Urun_Kodu"] == r["Urun_Kodu"]],
                              ozet[ozet["Urun_Kodu"] == r["Urun_Kodu"]].iloc[0], ss.get("cozumleyici"), erisim)
           for _, r in urun_tablosu.iterrows()]
    if j2.download_button(f"⬇️ Tüm pasaport taslakları ({len(tum)} ürün, JSON-LD)", json.dumps(tum, ensure_ascii=False, indent=2),
                          f"tum_pasaportlar_{erisim.split()[0].lower()}.jsonld", mime="application/ld+json"):
        kayit("Pasaport indirme", f"Tüm ürünler ({erisim})")
    with st.expander("JSON-LD içeriğini göster"):
        st.json(jsonld)
    st.caption(f"İçerik özeti (SHA-256): `{jsonld['dpp:icerikOzeti']}` — verinin değişip değişmediğini kontrol etmek içindir; "
               "dijital imza değildir. Yapı, EN 18216/18223 yaklaşımına göre düzenlenmiş bir taslaktır; resmi şema ilgili "
               "yetki tüzüğüyle belirlenecektir.")

# ---------------------------------------------------------------------------
# 4. Belge kasası
# ---------------------------------------------------------------------------

with sekmeler[3]:
    if kasa.empty:
        st.info("Belge kasası boş. Excel dosyanıza 'Belgeler' sayfası ekleyin (şablonda örnek var).")
    else:
        sayim = kasa["Durum"].value_counts()
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Belge", len(kasa))
        k2.metric("🟢 Geçerli", int(sayim.get("Geçerli", 0)))
        k3.metric("🟡/🟠 60 gün içinde", int(sayim.get("60 gün içinde doluyor", 0) + sayim.get("30 gün içinde doluyor", 0)))
        k4.metric("🔴 Süresi dolmuş", int(sayim.get("Süresi dolmuş", 0)))
        k5.metric("⚪ Tarihsiz", int(sayim.get("Bitiş tarihi yok", 0)))

        durumlar = st.multiselect("Durum filtresi", list(BELGE_SIMGE))
        kasa_ekran = kasa if not durumlar else kasa[kasa["Durum"].isin(durumlar)]
        kasa_ekran = kasa_ekran.sort_values("Kalan_Gun", na_position="last")
        kasa_ekran = kasa_ekran[["Durum", "Urun_Kodu", "Belge_Turu", "Kanonik_Tur", "Kategori", "Belge_No", "Duzenleyen",
                                 "Gecerlilik_Bitis", "Kalan_Gun", "Kapsam", "Not"]].copy()
        kasa_ekran.insert(0, " ", kasa_ekran["Durum"].map(BELGE_SIMGE))
        st.dataframe(goster(kasa_ekran), hide_index=True,
                     column_config={"Urun_Kodu": "Ürün (* = tümü)", "Belge_Turu": "Girilen tür", "Kanonik_Tur": "Tanınan tür",
                                    "Kalan_Gun": st.column_config.NumberColumn("Kalan gün", format="%d")})

        yonetim = kasa[kasa["Kanonik_Tur"].isin(dc.YONETIM_SISTEMLERI)]
        if not yonetim.empty:
            st.info(f"**{len(yonetim)} yönetim sistemi belgesi** (ISO 9001, ISO 14001, IATF vb.) var. Bunlar kuruluşun "
                    "süreçlerini belgeler; ürünün çevre veya mevzuat uygunluğunu tek başına kanıtlamaz. Ürün için "
                    "sertifika, uygunluk beyanı veya test raporu ayrıca gereklidir.")
        tanimsiz = kasa[kasa["Kategori"] == "Tanımlanamayan belge"]
        if not tanimsiz.empty:
            st.warning("Türü tanınamayan belgeler: " + ", ".join(tanimsiz["Belge_Turu"].astype(str).unique()))

# ---------------------------------------------------------------------------
# 5. Veri düzenleme
# ---------------------------------------------------------------------------

with sekmeler[4]:
    st.markdown("Tablolarda doğrudan düzeltme yapabilirsiniz. **Değişiklikleri uygula** dediğinizde değerlendirme yenilenir "
                "ve her değişiklik denetim izine yazılır.")
    st.warning("Değişiklikler yalnızca bu oturumda tutulur. Kalıcı olması için **düzenlenmiş veriyi Excel olarak indirip** "
               "bir sonraki sefer o dosyayı yükleyin.")
    tablolar = {"Ürünler": ("urunler", "Urun_Kodu"), "Belgeler": ("belgeler", "Urun_Kodu"), "Tedarik zinciri": ("tedarik", "Urun_Kodu")}
    tablo_adi = st.radio("Tablo", list(tablolar), horizontal=True, key="duzenle_tablo")
    alan, anahtar_kolon = tablolar[tablo_adi]
    mevcut = getattr(veri, alan)
    duzenlenecek = goster(mevcut.drop(columns=["Kaynak_Dosya"], errors="ignore")).reset_index(drop=True)
    duzenlenmis = st.data_editor(duzenlenecek, num_rows="dynamic", key=f"editor_{alan}_{ss.imza}_{ss.duzenleme_sayac}", hide_index=True)

    d1, d2 = st.columns(2)
    if d1.button("💾 Değişiklikleri uygula", type="primary"):
        farklar = dc.tablo_farki(duzenlenecek, duzenlenmis, anahtar_kolon)
        if not farklar:
            st.info("Değişiklik yok.")
        else:
            yeni = duzenlenmis.copy()
            kaynak = mevcut["Kaynak_Dosya"].reset_index(drop=True) if "Kaynak_Dosya" in mevcut.columns else pd.Series(dtype=object)
            yeni["Kaynak_Dosya"] = [kaynak.iloc[i] if i < len(kaynak) else "Elle eklendi" for i in range(len(yeni))]
            if alan == "urunler":
                yeni = yeni[yeni["Urun_Kodu"].map(lambda v: dc.metin(v) != "")]
            ss.veri = replace(veri, **{alan: yeni.reset_index(drop=True)})
            kayit("Veri düzenleme", f"{tablo_adi}: {len(farklar)} değişiklik — " + "; ".join(farklar[:30]))
            ss.duzenleme_sayac += 1
            st.rerun()
    d2.download_button("📤 Düzenlenmiş veriyi indir (Excel)", dc.veri_excel(veri), "dpp_verim_duzenlenmis.xlsx",
                       help="Bu dosyayı bir sonraki çalışmada yükleyerek kaldığınız yerden devam edebilirsiniz.")

# ---------------------------------------------------------------------------
# 6. Kural seti
# ---------------------------------------------------------------------------

with sekmeler[5]:
    st.markdown("Hazırlık skoru tamamen **şeffaftır**: her ürüne yalnızca sektörüne ve özelliklerine uygun kurallar "
                "uygulanır ve skor şöyle hesaplanır:")
    st.latex(r"\text{Hazırlık skoru} = 100 \times \frac{\text{karşılanan kuralların ağırlıkları toplamı}}{\text{uygulanan kuralların ağırlıkları toplamı}}")
    st.markdown("- **Kritik** bir kuralın karşılanmaması ürünü skordan bağımsız olarak **Yüksek risk** yapar.\n"
                "- **Durum** sütunu: *Yürürlükte* = bugün uygulanan mevzuat; *Beklenen DPP verisi* = yetki tüzüğüyle "
                "zorunlu hale gelmesi beklenen alan; *İyi uygulama* = mevzuat şartı değil, denetim ve alıcı beklentisi.\n"
                "- Kurallar, ağırlıklar ve çözüm adımları `dpp_core.py` dosyasındaki `KURALLAR` listesinden değiştirilebilir.")
    kt = dc.kural_tablosu()
    kt.insert(0, " ", kt["Seviye"].map(SEVIYE_SIMGE))
    st.dataframe(kt, hide_index=True)

# ---------------------------------------------------------------------------
# 7. Uyum asistanı
# ---------------------------------------------------------------------------

with sekmeler[6]:
    api_anahtari = gizli("GEMINI_API_KEY")
    model_adi = gizli("GEMINI_MODEL", "gemini-2.5-flash")
    gemini_kullan = False
    if api_anahtari:
        a1, a2 = st.columns(2)
        gemini_kullan = a1.toggle("Yapay zekâ (Gemini) ile yanıtla", value=False,
                                  help="Kapalıyken asistan yalnızca bu programdaki verilerle, yerel kurallarla yanıt verir.")
        maskele = a2.toggle("Ürün kodlarını ve adlarını maskele", value=True)
        if gemini_kullan:
            onay = st.checkbox("Ürün verilerimin **özetinin** yanıt üretmek için Google Gemini servisine gönderileceğini "
                               "anladım ve onaylıyorum.", key="yz_onay")
            if not onay:
                st.info("Onay verilmedikçe yerel mod kullanılır.")
                gemini_kullan = False
    else:
        st.caption("Asistan **yerel modda** çalışıyor: veriniz hiçbir dış servise gönderilmez. "
                   "Gemini bağlantısı için README'deki adımlara bakın.")

    if not ss.sohbet:
        ss.sohbet = [{"role": "assistant", "content":
                      f"Merhaba! {len(ozet)} ürünü değerlendirdim: "
                      + ", ".join(f"{dc.DURUM_SIMGE[k]} {k}: {v}" for k, v in ozet['Durum'].value_counts().items())
                      + ". Örneğin *'hangi ürünlerde yüksek risk var?'*, *'süresi dolan belgeler'* veya bir ürün kodu yazabilirsiniz."}]
    for m in ss.sohbet:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    if soru := st.chat_input("Sorunuzu yazın…"):
        ss.sohbet.append({"role": "user", "content": soru})
        with st.chat_message("user"):
            st.markdown(soru)
        with st.chat_message("assistant"):
            yanit = None
            if gemini_kullan:
                try:
                    from google import genai
                    istemci = genai.Client(api_key=api_anahtari)
                    baglam = dc.yapay_zeka_baglami(ozet, bulgular, kasa, maskele)
                    talimat = ("Sen Türk ihracatçılara AB ürün mevzuatı (ESPR, Dijital Ürün Pasaportu, REACH, GPSR, CBAM, "
                               "Batarya Tüzüğü vb.) konusunda yardımcı olan bir uyum asistanısın. Türkçe, kısa ve somut yanıt ver. "
                               "Yalnızca verilen veri özetine ve genel mevzuat bilgisine dayan. Gümrük onayı, kesin uyum veya "
                               "hukuki görüş verme; emin olmadığın tarih ve hükümlerde resmi kaynağın teyit edilmesini söyle.")
                    cevap = istemci.models.generate_content(model=model_adi,
                                                            contents=f"{talimat}\n\nVERİ ÖZETİ:\n{baglam}\n\nSORU: {soru}")
                    yanit = cevap.text
                    kayit("Yapay zekâ sorgusu", f"Gemini ({model_adi}), maskeleme {'açık' if maskele else 'kapalı'}: {soru[:120]}")
                except Exception as hata:
                    st.warning(f"Gemini'ye ulaşılamadı, yerel moda geçildi ({hata}).")
            if not yanit:
                yanit = dc.asistan_yaniti(soru, ozet, bulgular, kasa)
            st.markdown(yanit)
        ss.sohbet.append({"role": "assistant", "content": yanit})

# ---------------------------------------------------------------------------
# 8. Mevzuat rehberi
# ---------------------------------------------------------------------------

with sekmeler[7]:
    st.markdown(f"Bilgi amaçlıdır · Son gözden geçirme: **{dc.MEVZUAT_GOZDEN_GECIRME}** · Tarihler gösterge niteliğindedir; "
                "uygulamadan önce resmi kaynaktan teyit edin.")
    st.dataframe(dc.mevzuat_tablosu(), hide_index=True)
    with st.expander("Dijital Ürün Pasaportu (DPP) nedir?"):
        st.markdown("DPP, bir ürünün kimliğini, malzemelerini, kimyasal içeriğini, çevresel performansını, onarım ve geri "
                    "dönüşüm bilgilerini taşıyan dijital kayıttır. Ürün üzerindeki bir veri taşıyıcısıyla (genellikle QR kod) "
                    "erişilir. Pasaportun kendisi firmanın veya hizmet sağlayıcının sisteminde tutulur; AB DPP Registry "
                    "yalnızca benzersiz tanımlayıcıları kaydeder ve gümrüğün elektronik kontrolüne imkân verir. Zorunluluk her "
                    "ürün grubu için ayrı yetki tüzüğüyle başlar.")
    with st.expander("Hazırlık skoru neyi gösterir, neyi göstermez?"):
        st.markdown("Skor, verinizin bugünkü ve beklenen AB şartlarına göre **ne kadar hazır** olduğunu gösterir. "
                    "Bir ürünün AB'ye girişine izin verildiği veya verilmediği anlamına gelmez; bu kararı gümrük ve piyasa "
                    "gözetim otoriteleri verir. Belgelerin içeriği bu program tarafından doğrulanmaz; yalnızca türü ve "
                    "geçerlilik tarihi kontrol edilir.")
    with st.expander("Resmi kaynaklar"):
        st.markdown(
            "- [ESPR — Tüzük (AB) 2024/1781, EUR-Lex](https://eur-lex.europa.eu/eli/reg/2024/1781/oj)\n"
            "- [AB DPP Registry duyurusu](https://transition-pathways.europa.eu/retail/news/digital-product-passport-registry-now-live)\n"
            "- [Genel Ürün Güvenliği Tüzüğü (AB) 2023/988](https://eur-lex.europa.eu/eli/reg/2023/988/oj)\n"
            "- [Batarya Tüzüğü (AB) 2023/1542](https://eur-lex.europa.eu/eli/reg/2023/1542/oj)\n"
            "- [ECHA SVHC aday listesi](https://echa.europa.eu/candidate-list-table)\n"
            "- [T.C. Ticaret Bakanlığı — AB teknik mevzuatı](https://ticaret.gov.tr)")

# ---------------------------------------------------------------------------
# 9. Denetim izi
# ---------------------------------------------------------------------------

with sekmeler[8]:
    st.markdown("Bu oturumda yapılan yükleme, düzenleme, indirme ve yapay zekâ sorguları kaydedilir. Kayıtlar ön kontrol "
                "raporunun **Denetim_Izi** sayfasına da yazılır.")
    if ss.denetim_izi:
        iz = pd.DataFrame(ss.denetim_izi).iloc[::-1]
        st.dataframe(iz, hide_index=True)
        st.download_button("⬇️ Denetim izini indir (CSV)", iz.to_csv(index=False).encode("utf-8-sig"), "denetim_izi.csv")
    else:
        st.caption("Henüz kayıt yok.")
    st.caption("Not: Denetim izi oturum kapandığında silinir. Kalıcı ve değiştirilemez kayıt için veritabanı tabanlı sürüm gerekir.")

st.divider()
st.caption(UYARI_METNI)
