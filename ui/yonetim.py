"""Yönetim: kullanıcılar, firma ayarları, denetim izi, firmalar (platform)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dpp import audit, config, demo, repo, security
from ui import ortak as o


def kullanicilar_sayfasi():
    o.izin_gerekli("kullanici_yonet")
    db = o.db()
    platform = o.platform_yoneticisi()
    f = o.firma_id()
    o.sayfa_basligi("Kullanıcılar")
    if platform:
        kapsam = st.radio("Kapsam", ["Seçili firma", "Tüm platform"], horizontal=True) if f else "Tüm platform"
        liste_firma = None if kapsam == "Tüm platform" else f
    else:
        liste_firma = f
    liste = repo.kullanicilar(db, liste_firma)
    st.dataframe(pd.DataFrame([{"No": k["id"], "Ad soyad": k["ad_soyad"], "E-posta": k["eposta"], "Firma": k["firma"] or "Platform",
                                "Rol": security.ROLLER.get(k["rol"], k["rol"]), "Aktif": "Evet" if k["aktif"] else "Hayır",
                                "Son giriş": o.tarih_tr(k["son_giris"])} for k in liste]), hide_index=True)

    roller = {v: k for k, v in security.ROLLER.items() if platform or k != "platform_yonetici"}
    with st.expander("➕ Yeni kullanıcı"):
        firmalar = {x["unvan"]: x["id"] for x in repo.firmalar(db)} if platform else {}
        with st.form("yeni_kullanici", clear_on_submit=True):
            a, b = st.columns(2)
            ad = a.text_input("Ad soyad *")
            eposta = b.text_input("E-posta *")
            rol = a.selectbox("Rol", list(roller), index=list(roller.values()).index("editor"))
            firma = b.selectbox("Firma", list(firmalar)) if platform and firmalar else None
            st.caption("Geçici parola oluşturulur; kullanıcı ilk girişte değiştirmek zorundadır.")
            if st.form_submit_button("Oluştur", type="primary"):
                try:
                    hedef_firma = firmalar.get(firma) if platform else f
                    gecici = security.gecici_parola()
                    kid = security.kullanici_olustur(db, eposta, ad, roller[rol], gecici, hedef_firma)
                    audit.kaydet(db, hedef_firma, o.eposta(), "Kullanıcı oluşturuldu", "kullanici", kid, f"{eposta} ({roller[rol]})")
                    st.success("Kullanıcı oluşturuldu. Geçici parolayı güvenli bir kanaldan iletin (bir daha gösterilmez):")
                    st.code(gecici, language=None)
                    st.caption(f"Giriş adresi: {config.uygulama_adresi()}")
                except ValueError as h:
                    st.error(str(h))

    duzenlenebilir = {f"{k['ad_soyad']} <{k['eposta']}>": k for k in liste if k["id"] != o.kullanici()["id"]}
    if duzenlenebilir:
        with st.expander("✏️ Kullanıcı düzenle / parola sıfırla"):
            k = duzenlenebilir[st.selectbox("Kullanıcı", list(duzenlenebilir))]
            if k["rol"] == "platform_yonetici" and not platform:
                st.caption("Platform yöneticisini düzenleyemezsiniz.")
                return
            with st.form(f"kd_{k['id']}"):
                rol_adlari = list(roller)
                mevcut_rol = security.ROLLER.get(k["rol"])
                rol = st.selectbox("Rol", rol_adlari, index=rol_adlari.index(mevcut_rol) if mevcut_rol in rol_adlari else 0)
                aktif = st.checkbox("Aktif", value=bool(k["aktif"]))
                kaydet = st.form_submit_button("Kaydet", type="primary")
            if kaydet:
                repo.kullanici_guncelle(db, k["id"], {"rol": roller[rol], "aktif": 1 if aktif else 0},
                                        None if platform else f, o.eposta())
                st.rerun()
            if st.button("Parolayı sıfırla", key=f"ps_{k['id']}"):
                yeni = security.parola_sifirla(db, k["id"])
                audit.kaydet(db, k["firma_id"], o.eposta(), "Parola sıfırlandı", "kullanici", k["id"])
                st.success("Geçici parola (bir daha gösterilmez):")
                st.code(yeni, language=None)


def firma_ayarlari_sayfasi():
    o.izin_gerekli("firma_ayarlari")
    f = o.firma_gerekli()
    db = o.db()
    x = repo.firma(db, f)
    o.sayfa_basligi("Firma Ayarları")
    with st.form("firma"):
        a, b = st.columns(2)
        v = {"unvan": a.text_input("Unvan *", x["unvan"]), "vergi_no": b.text_input("Vergi no", x["vergi_no"] or ""),
             "adres": st.text_input("Adres", x["adres"] or ""), "ulke": a.text_input("Ülke", x["ulke"] or ""),
             "eposta": b.text_input("E-posta (pasaportta görünür)", x["eposta"] or ""),
             "telefon": a.text_input("Telefon", x["telefon"] or ""), "web": b.text_input("Web sitesi", x["web"] or ""),
             "cozumleyici_alan": st.text_input("Kendi pasaport alan adınız (isteğe bağlı)", x["cozumleyici_alan"] or "",
                                               help="ör. dpp.firmaniz.com — doluysa ve ürünün GTIN'i geçerliyse QR kodlar GS1 Digital Link "
                                                    "biçiminde bu alana yönlenir. Alan adınızın bu uygulamaya yönlendirilmesi gerekir.")}
        if st.form_submit_button("Kaydet", type="primary"):
            try:
                repo.firma_kaydet(db, v, o.eposta(), f)
                st.toast("Kaydedildi.", icon="✅")
            except ValueError as h:
                st.error(str(h))


def denetim_izi_sayfasi():
    o.izin_gerekli("iz_gor")
    db = o.db()
    o.sayfa_basligi("Denetim İzi", "Tüm önemli işlemler zincirleme özetle kaydedilir; sonradan değiştirilen kayıt tespit edilir.")
    tum = o.platform_yoneticisi() and st.toggle("Tüm platform", value=not o.firma_id())
    kayitlar = audit.listele(db, None if tum else o.firma_gerekli(), 1000)
    ara = st.text_input("Ara", placeholder="kullanıcı, işlem veya ayrıntı")
    if ara:
        a = ara.lower()
        kayitlar = [k for k in kayitlar if a in " ".join(str(k.get(x) or "") for x in ("kullanici", "islem", "detay", "varlik")).lower()]
    df = pd.DataFrame([{"Zaman": o.tarih_tr(k["zaman"]), "Kullanıcı": k["kullanici"], "İşlem": k["islem"], "Kayıt": f"{k['varlik'] or ''} {k['varlik_id'] or ''}",
                        "Ayrıntı": k["detay"], "Özet": (k["ozet"] or "")[:12]} for k in kayitlar])
    st.dataframe(df, hide_index=True)
    a, b = st.columns(2)
    a.download_button("CSV indir", df.to_csv(index=False).encode("utf-8-sig"), "denetim_izi.csv")
    if o.platform_yoneticisi() and b.button("Zincir bütünlüğünü doğrula"):
        saglam, sayi, bozuk = audit.zinciri_dogrula(db)
        (st.success(f"Zincir sağlam — {sayi} kayıt kontrol edildi.") if saglam
         else st.error(f"Zincir {bozuk} numaralı kayıtta kırılmış. Kayıtlar sonradan değiştirilmiş olabilir."))


def firmalar_sayfasi():
    o.izin_gerekli("firma_yonet")
    db = o.db()
    o.sayfa_basligi("Firmalar", "Platformu kullanan firmalar. Sol menüden çalışmak istediğiniz firmayı seçin.")
    o.kalicilik_uyarisi()
    liste = repo.firmalar(db)
    st.dataframe(pd.DataFrame([{"No": x["id"], "Unvan": x["unvan"], "Plan": x["plan"], "Aktif": "Evet" if x["aktif"] else "Hayır",
                                "Ürün": x["urun_sayisi"], "Kullanıcı": x["kullanici_sayisi"], "Oluşturma": o.tarih_tr(x["olusturma"])}
                               for x in liste]), hide_index=True)
    a, b = st.columns(2)
    with a.expander("➕ Yeni firma", expanded=not liste):
        with st.form("yeni_firma", clear_on_submit=True):
            unvan = st.text_input("Unvan *")
            vergi = st.text_input("Vergi no")
            eposta = st.text_input("E-posta")
            plan = st.selectbox("Plan", ["Standart", "Profesyonel", "Kurumsal", "Demo"])
            if st.form_submit_button("Oluştur", type="primary"):
                try:
                    yeni = repo.firma_kaydet(db, {"unvan": unvan, "vergi_no": vergi, "eposta": eposta, "plan": plan}, o.eposta())
                    st.session_state["aktif_firma"] = yeni
                    st.success("Firma oluşturuldu ve seçildi. Kullanıcılar ekranından firma yöneticisi ekleyin.")
                except ValueError as h:
                    st.error(str(h))
    with b.expander("🧪 Demo firma oluştur"):
        st.caption("Sekiz farklı sektörden, bilerek eksikler içeren örnek ürün, belge ve tedarikçilerle bir demo firma oluşturur. "
                   "Satış sunumu ve eğitim için kullanılabilir.")
        if st.button("Demo firmayı oluştur"):
            with st.spinner("Demo veri hazırlanıyor…"):
                yeni = demo.demo_firma_olustur(db, o.eposta())
            st.session_state["aktif_firma"] = yeni
            st.success("Demo firma oluşturuldu ve seçildi.")
    if liste:
        with st.expander("Firma durumunu değiştir"):
            sec = {x["unvan"]: x for x in liste}
            x = sec[st.selectbox("Firma", list(sec), key="firma_durum")]
            aktif = st.checkbox("Aktif", value=bool(x["aktif"]), key=f"fa_{x['id']}")
            plan = st.selectbox("Plan", ["Standart", "Profesyonel", "Kurumsal", "Demo"],
                                index=["Standart", "Profesyonel", "Kurumsal", "Demo"].index(x["plan"]) if x["plan"] in
                                ["Standart", "Profesyonel", "Kurumsal", "Demo"] else 0, key=f"fp_{x['id']}")
            if st.button("Kaydet", key=f"fk_{x['id']}"):
                repo.firma_kaydet(db, {"aktif": 1 if aktif else 0, "plan": plan}, o.eposta(), x["id"])
                st.rerun()
