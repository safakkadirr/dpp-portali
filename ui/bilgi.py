"""Uyum asistanı, mevzuat rehberi ve kural seti."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dpp import assistant, config, evaluation, repo
from dpp.regulations import GOZDEN_GECIRME, MEVZUAT
from dpp.rules import HAZIR_ESIGI, KURAL_SETI_TEMEL, KURALLAR, kural_seti_surumu
from ui import ortak as o


def asistan_sayfasi():
    f = o.firma_gerekli()
    db = o.db()
    o.sayfa_basligi("Uyum Asistanı")
    anahtar, model = config.gemini()
    yz = False
    maskele = True
    if anahtar and o.izin("yapay_zeka"):
        a, b = st.columns(2)
        yz = a.toggle("Yapay zekâ (Gemini) ile yanıtla", value=False)
        maskele = b.toggle("Ürün kodlarını ve adlarını maskele", value=True)
        if yz and not st.checkbox("Ürün verilerimin özetinin yanıt üretmek için Google Gemini servisine gönderileceğini onaylıyorum."):
            st.info("Onay verilmedikçe yerel mod kullanılır.")
            yz = False
    else:
        st.caption("Asistan yerel modda: verileriniz hiçbir dış servise gönderilmez.")
    urunler = repo.urunler(db, f)
    bulgular = evaluation.firma_bulgulari(db, f)
    belgeler = repo.belgeler(db, f)
    anahtar_sohbet = f"sohbet_{f}"
    if anahtar_sohbet not in st.session_state:
        st.session_state[anahtar_sohbet] = [{"role": "assistant", "content": assistant.yerel_yanit("yardım", urunler, bulgular, belgeler)}]
    for m in st.session_state[anahtar_sohbet]:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
    if soru := st.chat_input("Sorunuzu yazın…"):
        st.session_state[anahtar_sohbet].append({"role": "user", "content": soru})
        with st.chat_message("user"):
            st.markdown(soru)
        with st.chat_message("assistant"):
            yanit = None
            if yz:
                try:
                    yanit = assistant.yz_yanit(soru, assistant.yz_baglami(urunler, bulgular, maskele), anahtar, model)
                    o.kayit("Yapay zekâ sorgusu", "asistan", None, f"{model}, maskeleme {'açık' if maskele else 'kapalı'}: {soru[:150]}")
                except Exception as h:
                    st.warning(f"Gemini'ye ulaşılamadı, yerel moda geçildi ({h}).")
            yanit = yanit or assistant.yerel_yanit(soru, urunler, bulgular, belgeler)
            st.markdown(yanit)
        st.session_state[anahtar_sohbet].append({"role": "assistant", "content": yanit})


def mevzuat_sayfasi():
    o.sayfa_basligi("Mevzuat Rehberi", f"Bilgi amaçlıdır · Son gözden geçirme: {GOZDEN_GECIRME} · Tarihler gösterge niteliğindedir.")
    st.dataframe(pd.DataFrame(MEVZUAT), hide_index=True, column_config={"Kaynak": st.column_config.LinkColumn("Kaynak")})
    with st.expander("Dijital Ürün Pasaportu nedir?"):
        st.markdown("DPP; ürünün kimliğini, malzemelerini, kimyasal içeriğini, çevresel performansını, onarım ve geri dönüşüm "
                    "bilgilerini taşıyan dijital kayıttır. Ürün üzerindeki veri taşıyıcısıyla (genellikle QR kod) erişilir. "
                    "Pasaportun kendisi firmanın veya hizmet sağlayıcının sisteminde tutulur; AB DPP Registry yalnızca benzersiz "
                    "tanımlayıcıları kaydeder ve gümrüğün elektronik kontrolüne imkân verir. Zorunluluk her ürün grubu için ayrı "
                    "yetki tüzüğüyle başlar.")
    with st.expander("Programın göstergeleri neyi gösterir?"):
        st.markdown(f"- **Yasal uyum:** bugün yürürlükte olan şartlar. Bir kritik eksik bile ürünü 'Kritik eksik' yapar ve pasaport "
                    f"yayımını engeller.\n- **DPP hazırlık skoru:** ileride zorunlu olacak veriler ve iyi uygulamalar; ağırlıklı yüzde. "
                    f"%{HAZIR_ESIGI:.0f} ve üzeri 'Hazır' kabul edilir.\n- **Yaklaşan yükümlülük:** yürürlük tarihi gelmemiş yasal şart; "
                    "tarihi gelince kendiliğinden yasal uyuma dahil olur.\n- Belgelerin içeriği program tarafından okunmaz; türü, "
                    "süresi ve bağımsız doğrulama durumu izlenir.")


def kural_seti_sayfasi():
    db = o.db()
    ayarlar = repo.kural_ayarlari(db)
    o.sayfa_basligi("Kural Seti", f"Temel sürüm {KURAL_SETI_TEMEL} · Etkin sürüm {kural_seti_surumu(ayarlar)}")
    st.latex(r"\text{DPP hazırlık} = 100 \times \frac{\sum \text{karşılanan hazırlık kurallarının ağırlığı}}{\sum \text{uygulanan hazırlık kurallarının ağırlığı}}")
    st.caption("Yasal sınıftaki kurallar skora girmez; ayrı 'yasal uyum' göstergesini belirler.")
    df = pd.DataFrame([{
        "Kod": k.kod, "Kural": k.ad, "Sınıf": k.sinif, "Seviye": k.seviye,
        "Varsayılan ağırlık": k.agirlik, "Aktif": bool((ayarlar.get(k.kod) or {}).get("aktif", 1)),
        "Ağırlık": (ayarlar.get(k.kod) or {}).get("agirlik") or k.agirlik,
        "Zorunlu tarih": k.zorunlu_tarih.isoformat() if k.zorunlu_tarih else "", "Kapsam": k.kapsam, "Dayanak": k.dayanak,
    } for k in KURALLAR])
    if o.izin("kural_yonet"):
        duz = st.data_editor(df, hide_index=True, disabled=[c for c in df.columns if c not in ("Aktif", "Ağırlık")],
                             column_config={"Ağırlık": st.column_config.NumberColumn(min_value=1, max_value=20, step=1)}, key="kural_ed")
        if st.button("Kural ayarlarını kaydet", type="primary"):
            for r, k in zip(duz.to_dict("records"), KURALLAR):
                aktif, agirlik = bool(r["Aktif"]), int(r["Ağırlık"])
                eski = ayarlar.get(k.kod) or {}
                if aktif != bool(eski.get("aktif", 1)) or agirlik != (eski.get("agirlik") or k.agirlik):
                    repo.kural_ayari_kaydet(db, k.kod, aktif, agirlik, o.eposta(), k.agirlik)
            st.toast("Kaydedildi. Değerlendirmeler bir sonraki açılışta yeni kural setiyle güncellenir.", icon="✅")
            st.rerun()
    else:
        st.dataframe(df, hide_index=True)
