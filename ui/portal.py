"""Tedarikçi Portalı (firma tarafı): eksik analizi, talepler, inceleme, karne ve beyanlar."""

from __future__ import annotations

from urllib.parse import quote

import pandas as pd
import streamlit as st

from dpp import assistant, config, eposta, evaluation, repo, suppliers
from dpp.suppliers import DURUM_SIMGE, ISTENEBILIR
from ui import ortak as o

KISA = {"malzeme": "Bileşim", "svhc": "SVHC beyanı", "mense": "Menşe", "karbon": "Karbon", "belge": "Belge"}
BEKLEYEN = ("Gönderildi", "Görüntülendi", "Revizyon istendi")


def sayfa():
    f = o.firma_gerekli()
    db = o.db()
    o.sayfa_basligi("Tedarikçi Portalı", "Eksik bilgileri tedarikçilerden tek bağlantıyla toplayın: talep, takip, inceleme ve ürüne aktarım.")
    analiz = suppliers.eksik_analizi(db, f)
    liste = suppliers.talepler(db, f)
    c = st.columns(4)
    c[0].metric("Eksiği olan tedarikçi", len(analiz))
    c[1].metric("Yanıt bekleyen talep", sum(1 for t in liste if t["gorunen_durum"] in BEKLEYEN))
    c[2].metric("İncelemenizi bekleyen", sum(1 for t in liste if t["gorunen_durum"] == "Yanıtlandı"))
    c[3].metric("Süresi dolan", sum(1 for t in liste if t["gorunen_durum"] == "Süresi doldu"))
    if not eposta.ayarli():
        st.caption("✉️ Otomatik e-posta gönderimi ayarlı değil. Talepler hazırlanır; metni kopyalayıp kendi e-postanızla "
                   "gönderebilir veya 'E-posta programında aç' düğmesini kullanabilirsiniz.")
    _hazirlananlar(f)
    inceleme = sum(1 for t in liste if t["gorunen_durum"] == "Yanıtlandı")
    s = st.tabs(["🔎 Eksik analizi", f"📨 Talepler ({len(liste)})" + (f" · {inceleme} inceleme" if inceleme else ""),
                 "✍️ Tekil talep", "📈 Tedarikçi karnesi", "🧾 Tedarikçi beyanları"])
    with s[0]:
        _eksik_analizi(f, analiz)
    with s[1]:
        _talepler(f, liste)
    with s[2]:
        _tekil_talep(f)
    with s[3]:
        _karne(f)
    with s[4]:
        _beyanlar(f)


# ---------------------------------------------------------------------------
# Hazırlanan talepler (bağlantının açık hali yalnızca bu oturumda gösterilir)
# ---------------------------------------------------------------------------

def _hazir_listesi() -> list[dict]:
    return st.session_state.setdefault("portal_hazir", [])


def _hazirla(db, f, talep_id: int, token: str, hatirlatma: bool = False) -> dict:
    t = suppliers.talep(db, f, talep_id)
    firma = repo.firma(db, f)
    adres = f"{config.uygulama_adresi()}/?t={token}"
    belge_notlari = []
    if "belge" in t["istenenler"]:
        a = next((x for x in suppliers.eksik_analizi(db, f) if x["tedarikci_id"] == t["tedarikci_id"]), None)
        belge_notlari = a["belge_sorunlari"] if a else []
    konu, govde = eposta.talep_metni(firma["unvan"], t["tedarikci"], t.get("yetkili"),
                                     [f"{u['kod']} {u['ad']}" for u in t["urunler"]], t["istenenler"], t.get("mesaj") or "",
                                     adres, o.tarih_tr(t["son_tarih"]), t.get("dil") or "tr", o.ad(), belge_notlari)
    if hatirlatma:
        konu, govde = eposta.hatirlatma_metni(konu, govde, t.get("dil") or "tr")
    kayit = {"talep_id": talep_id, "unvan": t["tedarikci"], "eposta": t.get("gonderilen_eposta") or t.get("eposta") or "",
             "konu": konu, "govde": govde, "adres": adres, "dil": t.get("dil") or "tr", "gonderildi": False,
             "firma_eposta": firma.get("eposta")}
    liste = [x for x in _hazir_listesi() if x["talep_id"] != talep_id]
    liste.append(kayit)
    st.session_state["portal_hazir"] = liste
    return kayit


def _gonder(db, f, k: dict) -> bool:
    try:
        eposta.gonder(k["eposta"], k["konu"], k["govde"], yanit_adresi=k.get("firma_eposta") or o.eposta(),
                      gonderen_adi=repo.firma(db, f)["unvan"])
        suppliers.gonderildi(db, f, k["talep_id"], "E-posta", k["eposta"], o.eposta())
        k["gonderildi"] = True
        return True
    except ValueError as h:
        st.error(f"{k['unvan']}: {h}")
        return False


def _hazirlananlar(f):
    hazir = _hazir_listesi()
    if not hazir:
        return
    db = o.db()
    st.subheader(f"Gönderime hazır talepler ({len(hazir)})")
    st.caption("Bağlantılar güvenlik nedeniyle yalnızca şimdi gösterilir; sistemde açık hâli saklanmaz. Kaybederseniz talepler "
               "sekmesinden yeni bağlantı oluşturabilirsiniz.")
    gonderilebilir = [k for k in hazir if not k["gonderildi"] and eposta.gecerli_mi(k["eposta"])]
    a, b = st.columns(2)
    if eposta.ayarli() and gonderilebilir and a.button(f"✉️ Tümünü e-postayla gönder ({len(gonderilebilir)})", type="primary"):
        basarili = sum(1 for k in gonderilebilir if _gonder(db, f, k))
        st.toast(f"{basarili} e-posta gönderildi.", icon="✅")
    if b.button("Listeyi temizle"):
        st.session_state["portal_hazir"] = []
        st.rerun()
    yz_anahtar, yz_model = config.gemini()
    for k in hazir:
        durum = "✅ gönderildi" if k["gonderildi"] else ("⚠️ e-posta adresi yok" if not eposta.gecerli_mi(k["eposta"]) else "gönderilmedi")
        with st.expander(f"#{k['talep_id']} · {k['unvan']} — {durum}", expanded=len(hazir) == 1):
            k["eposta"] = st.text_input("Alıcı e-posta", k["eposta"], key=f"hz_ep_{k['talep_id']}")
            k["konu"] = st.text_input("Konu", k["konu"], key=f"hz_konu_{k['talep_id']}")
            k["govde"] = st.text_area("E-posta metni", k["govde"], height=320, key=f"hz_govde_{k['talep_id']}")
            st.code(k["adres"], language=None)
            c = st.columns(4)
            if eposta.ayarli() and c[0].button("✉️ Gönder", key=f"hz_g_{k['talep_id']}", disabled=not eposta.gecerli_mi(k["eposta"])):
                if _gonder(db, f, k):
                    st.toast("E-posta gönderildi.", icon="✅")
            govde_kisa = k["govde"] if len(k["govde"]) < 1800 else k["govde"][:1700] + "\n…\n" + k["adres"]
            c[1].link_button("E-posta programında aç", f"mailto:{k['eposta']}?subject={quote(k['konu'])}&body={quote(govde_kisa)}")
            if c[2].button("Gönderdim olarak işaretle", key=f"hz_e_{k['talep_id']}", disabled=k["gonderildi"]):
                suppliers.gonderildi(o.db(), f, k["talep_id"], "Elle", k["eposta"] or None, o.eposta())
                k["gonderildi"] = True
                st.rerun()
            if yz_anahtar and c[3].button("✨ Yapay zekâ ile düzenle", key=f"hz_yz_{k['talep_id']}"):
                try:
                    with st.spinner("Metin düzenleniyor…"):
                        k["govde"] = assistant.talep_metni_duzenle(k["govde"], yz_anahtar, yz_model)
                    st.session_state.pop(f"hz_govde_{k['talep_id']}", None)
                    st.rerun()
                except Exception as h:
                    st.warning(f"Düzenlenemedi: {h}")
    st.divider()


# ---------------------------------------------------------------------------
# Eksik analizi
# ---------------------------------------------------------------------------

def _eksik_analizi(f, analiz: list[dict]):
    db = o.db()
    if not analiz:
        st.success("Tedarikçilerden istenmesi gereken eksik bilgi bulunmadı.")
        st.caption("Analiz, ürünlerin malzeme ve tedarik zinciri satırlarında tedarikçisi belli olan kayıtlara bakar. Tedarikçisi "
                   "girilmemiş ürünler için Ürünler ekranından tedarikçi atayın veya Tekil talep sekmesini kullanın.")
        return
    st.caption("Program, ürünlerinizin tedarikçi bağlantılarına bakarak her tedarikçiden neyin istenmesi gerektiğini çıkardı. "
               "Seçtiğiniz tedarikçilere tek tıkla, ilgili tüm ürünleri kapsayan birer talep hazırlanır.")
    df = pd.DataFrame([{
        "Seç": a["acik_talep"] == 0, "Öncelik": a["puan"], "Tedarikçi": a["unvan"], "Ülke": a.get("ulke") or "—",
        "E-posta": a.get("eposta") or "⚠️ yok", "Dil": "Türkçe" if a["dil"] == "tr" else "İngilizce",
        "İstenecek": ", ".join(KISA[i] for i in a["istenenler"]),
        "Ürünler": ", ".join(f"{k['kod']} ({', '.join(KISA[e] for e in k['eksik'])})" for k in a["urunler"]) or "—",
        "Belge durumu": "; ".join(a["belge_sorunlari"]) or "—",
        "Açık talep": a["acik_talep"],
    } for a in analiz])
    duz = st.data_editor(df, hide_index=True, key=f"analiz_{len(analiz)}",
                         disabled=[c for c in df.columns if c not in ("Seç", "Dil")],
                         column_config={"Seç": st.column_config.CheckboxColumn("Seç"),
                                        "Dil": st.column_config.SelectboxColumn("Dil", options=["Türkçe", "İngilizce"], required=True),
                                        "Öncelik": st.column_config.NumberColumn("Öncelik", help="SVHC eksiği 3, diğer eksikler 1, "
                                                                                 "belge sorunu 2 puan")})
    if any(not a.get("eposta") for a in analiz):
        st.caption("⚠️ E-posta adresi olmayan tedarikçiler için talep yine hazırlanır; adresi Tedarik Zinciri › Tedarikçiler "
                   "sekmesinden ekleyebilir veya bağlantıyı kendiniz iletebilirsiniz.")
    secilen = [(a, r) for a, r in zip(analiz, duz.to_dict("records")) if r["Seç"]]
    a1, a2 = st.columns(2)
    gun = a1.number_input("Yanıt süresi (gün)", 1, 90, 14, key="analiz_gun")
    hemen = a2.checkbox("Hazırlanınca e-postayla gönder", value=eposta.ayarli(), disabled=not eposta.ayarli(), key="analiz_hemen",
                        help=None if eposta.ayarli() else "E-posta gönderimi ayarlı değil")
    mesaj = st.text_area("Tedarikçilere ek not (isteğe bağlı)", key="analiz_mesaj",
                         placeholder="Ör. Yeni sezon siparişlerimiz için bu bilgilere 30 Kasım'a kadar ihtiyacımız var.")
    if st.button(f"Seçilen {len(secilen)} tedarikçiye talep hazırla", type="primary", disabled=not secilen):
        hazirlanan = gonderilen = 0
        for a, r in secilen:
            try:
                tid, token = suppliers.talep_olustur(db, f, a["tedarikci_id"], [k["id"] for k in a["urunler"]], a["istenenler"],
                                                     mesaj, gun, o.eposta(), dil="tr" if r["Dil"] == "Türkçe" else "en",
                                                     kaynak="Eksik analizi")
                k = _hazirla(db, f, tid, token)
                hazirlanan += 1
                if hemen and eposta.gecerli_mi(k["eposta"]) and _gonder(db, f, k):
                    gonderilen += 1
            except ValueError as h:
                st.error(f"{a['unvan']}: {h}")
        st.session_state["portal_mesaj"] = f"{hazirlanan} talep hazırlandı" + (f", {gonderilen} tanesi e-postayla gönderildi" if hemen else "") + "."
        st.rerun()
    if st.session_state.get("portal_mesaj"):
        st.success(st.session_state.pop("portal_mesaj"))


# ---------------------------------------------------------------------------
# Talepler: takip, inceleme, aktarım
# ---------------------------------------------------------------------------

def _talepler(f, liste: list[dict]):
    db = o.db()
    if not liste:
        st.caption("Henüz talep yok. Eksik analizi veya Tekil talep sekmesinden oluşturabilirsiniz.")
        return
    filtre = st.radio("Göster", ["Tümü", "Yanıt bekleyen", "İnceleme bekleyen", "Süresi dolan", "Kapanan"], horizontal=True,
                      key="talep_filtre")
    eslesme = {"Yanıt bekleyen": BEKLEYEN, "İnceleme bekleyen": ("Yanıtlandı",), "Süresi dolan": ("Süresi doldu",),
               "Kapanan": ("Kapandı",)}
    gosterilen = [t for t in liste if filtre == "Tümü" or t["gorunen_durum"] in eslesme[filtre]]
    st.dataframe(pd.DataFrame([{
        "No": t["id"], "Durum": f"{DURUM_SIMGE.get(t['gorunen_durum'], '')} {t['gorunen_durum']}", "Tedarikçi": t["tedarikci"],
        "Ürünler": t["urun_kodu"] or "—", "İstenen": ", ".join(KISA.get(i, i) for i in t["istenenler"]),
        "Gönderim": (f"{t['gonderim']} · " if t.get("gonderim") else "") + o.tarih_tr(t.get("gonderim_tarihi") or t["olusturma"]),
        "İlk açılış": o.tarih_tr(t.get("ilk_acilis")), "Yanıt": o.tarih_tr(t.get("yanit_tarihi")),
        "Son tarih": o.tarih_tr(t["son_tarih"]), "Hatırlatma": t.get("hatirlatma_sayisi") or 0,
    } for t in gosterilen], columns=["No", "Durum", "Tedarikçi", "Ürünler", "İstenen", "Gönderim", "İlk açılış", "Yanıt",
                                     "Son tarih", "Hatırlatma"]), hide_index=True)
    if not gosterilen:
        return
    secenek = {f"#{t['id']} · {t['tedarikci']} — {DURUM_SIMGE.get(t['gorunen_durum'], '')} {t['gorunen_durum']}": t for t in gosterilen}
    onerilen = next((i for i, t in enumerate(gosterilen) if t["gorunen_durum"] == "Yanıtlandı"), 0)
    t = secenek[st.selectbox("Talep ayrıntısı", list(secenek), index=onerilen, key="talep_sec")]
    _talep_ayrinti(f, db, t)


def _talep_ayrinti(f, db, t: dict):
    if st.session_state.get("talep_sonuc"):
        st.success("Ürünlere aktarıldı:\n\n" + "\n".join(f"- {x}" for x in st.session_state.pop("talep_sonuc")))
    with st.container(border=True):
        st.markdown(f"#### #{t['id']} {t['tedarikci']}")
        olaylar = [("Oluşturuldu", t["olusturma"], t.get("olusturan")), ("Gönderildi", t.get("gonderim_tarihi"), t.get("gonderim")),
                   ("Tedarikçi açtı", t.get("ilk_acilis"), f"{t.get('acilis_sayisi') or 0} kez"),
                   ("Son hatırlatma", t.get("son_hatirlatma"), f"{t.get('hatirlatma_sayisi') or 0} hatırlatma"),
                   ("Yanıt", t.get("yanit_tarihi"), f"{t.get('yanit_sayisi') or 0} gönderim")]
        st.markdown("  \n".join(f"{'✅' if z else '▫️'} **{ad}:** {o.tarih_tr(z)}" + (f" · {ek}" if z and ek else "")
                                for ad, z, ek in olaylar))
        st.caption(f"Son tarih: {o.tarih_tr(t['son_tarih'])} · Dil: {'Türkçe' if (t.get('dil') or 'tr') == 'tr' else 'İngilizce'} · "
                   f"Kaynak: {t.get('kaynak') or 'Elle'} · Alıcı: {t.get('gonderilen_eposta') or '—'}")
        if t.get("revizyon_notu"):
            st.warning(f"Revizyon notu: {t['revizyon_notu']}")
        y = t.get("yanit")
        if y:
            _yanit_goster(f, db, t, y)
        if t["durum"] == "Kapandı":
            st.success("Talep kapandı.")
            return
        st.markdown("**İşlemler**")
        c = st.columns(3)
        with c[0]:
            if t["gorunen_durum"] == "Yanıtlandı" and suppliers.yanit_urunleri(t):
                urun_sec = {f"{u['kod']} — {u['ad']}": u["id"] for u in t["urunler"] if u["id"] in suppliers.yanit_urunleri(t)}
                secilen = st.multiselect("Aktarılacak ürünler", list(urun_sec), default=list(urun_sec), key=f"akt_{t['id']}")
                if st.button("✅ Kabul et ve ürünlere aktar", type="primary", key=f"aktar_{t['id']}", disabled=not secilen):
                    try:
                        yapilan = suppliers.urune_aktar(db, f, t["id"], o.eposta(), [urun_sec[s] for s in secilen])
                        for s in secilen:
                            evaluation.urun_degerlendir(db, f, urun_sec[s], o.eposta())
                        st.session_state["talep_sonuc"] = yapilan or ["Aktarılacak alan yoktu; talep kapatıldı."]
                        st.rerun()
                    except ValueError as h:
                        st.error(str(h))
            elif t["gorunen_durum"] == "Yanıtlandı":
                st.caption("Yanıtta ürüne aktarılacak alan yok; belgeler Belge Kasası'nda.")
        with c[1]:
            with st.form(f"rev_{t['id']}"):
                not_ = st.text_area("Tedarikçiden istenecek düzeltme", placeholder="Ör. GOTS sertifikasının güncel hâlini yükleyin.")
                uzat = st.number_input("Süreyi uzat (gün)", 1, 60, 7)
                if st.form_submit_button("↩️ Revizyon iste"):
                    try:
                        suppliers.revizyon_iste(db, f, t["id"], not_, o.eposta(), uzat)
                        token = suppliers.yeni_baglanti(db, f, t["id"], uzat, o.eposta())
                        k = _hazirla(db, f, t["id"], token, hatirlatma=True)
                        k["govde"] = f"{not_}\n\n" + k["govde"]
                        st.rerun()
                    except ValueError as h:
                        st.error(str(h))
        with c[2]:
            uzat_h = st.number_input("Hatırlatmada süre (gün)", 1, 60, 7, key=f"hu_{t['id']}")
            if st.button("🔔 Hatırlatma / yeni bağlantı", key=f"hat_{t['id']}"):
                try:
                    token = suppliers.yeni_baglanti(db, f, t["id"], uzat_h, o.eposta())
                    _hazirla(db, f, t["id"], token, hatirlatma=True)
                    st.rerun()
                except ValueError as h:
                    st.error(str(h))
            if st.button("Kapat (aktarmadan)", key=f"kap_{t['id']}"):
                suppliers.kapat(db, f, t["id"], o.eposta())
                st.rerun()


def _yanit_goster(f, db, t: dict, y: dict):
    st.markdown(f"**Yanıtlayan:** {y.get('yanitlayan', '—')} · {o.tarih_tr(t.get('yanit_tarihi'))}")
    adlar = {str(u["id"]): f"{u['kod']} — {u['ad']}" for u in t["urunler"]}
    bloklar = list((y.get("urunler") or {}).items())
    if not bloklar and any(k in y for k in ("svhc_beyani", "malzemeler", "hammadde_mensei")):   # eski biçim
        bloklar = [(str(t["urun_id"]), y)]
    if y.get("genel") and any(suppliers._dolu(v) for v in y["genel"].values()):
        bloklar.append(("genel", y["genel"]))
    for anahtar, v in bloklar:
        st.markdown(f"**{adlar.get(anahtar, 'Genel')}**")
        satirlar = []
        if v.get("svhc_beyani"):
            satirlar.append(f"SVHC: **{v['svhc_beyani']}** {v.get('svhc_maddeler') or ''}")
        if v.get("hammadde_mensei"):
            satirlar.append(f"Menşe: {v['hammadde_mensei']}")
        if v.get("karbon_kg") is not None:
            satirlar.append(f"Karbon: {v['karbon_kg']} kg CO2e ({v.get('karbon_yontemi') or '—'})")
        if satirlar:
            st.markdown(" · ".join(satirlar))
        if v.get("malzemeler"):
            st.dataframe(pd.DataFrame(v["malzemeler"]).rename(columns={"malzeme": "Malzeme", "oran": "Oran (%)", "mense": "Menşe",
                                                                       "geri_donusturulmus": "Geri dönüştürülmüş"}), hide_index=True)
    if y.get("belge_idler"):
        bel = {b["id"]: b for b in repo.belgeler(db, f)}
        st.markdown("**Yüklenen belgeler** (Belge Kasası'nda, doğrulama bekliyor)")
        st.dataframe(pd.DataFrame([{"Belge": bel[i].get("tur_serbest") or bel[i]["tur_kodu"], "No": bel[i].get("belge_no") or "—",
                                    "Bitiş": o.tarih_tr(bel[i].get("bitis")), "Dosya": bel[i].get("dosya_adi") or "—",
                                    "Doğrulama": bel[i].get("dogrulama_durumu")} for i in y["belge_idler"] if i in bel]), hide_index=True)
    if y.get("not"):
        st.markdown(f"**Not:** {y['not']}")


# ---------------------------------------------------------------------------
# Tekil talep
# ---------------------------------------------------------------------------

def _tekil_talep(f):
    db = o.db()
    ted = repo.tedarikciler(db, f)
    if not ted:
        st.info("Önce Tedarik Zinciri › Tedarikçiler sekmesinden tedarikçi ekleyin.")
        return
    t_sec = {t["unvan"]: t for t in ted}
    tedarikci = t_sec[st.selectbox("Tedarikçi", list(t_sec), key="tekil_ted")]
    urunler = {f"{u['urun_kodu']} — {u['ad']}": u["id"] for u in repo.urunler(db, f)}
    bagli = suppliers._tedarikci_urunleri(db, f).get(tedarikci["id"], set())
    with st.form("tekil_talep"):
        secilen = st.multiselect("İlgili ürünler", list(urunler), default=[k for k, v in urunler.items() if v in bagli],
                                 help="Boş bırakılırsa genel bir talep olur (ör. yalnızca sertifika yenileme).")
        istenen = st.multiselect("İstenen bilgiler", list(ISTENEBILIR), default=["svhc", "malzeme", "belge"],
                                 format_func=lambda k: ISTENEBILIR[k])
        a, b, c = st.columns(3)
        dil = a.radio("Dil", ["Türkçe", "İngilizce"], index=0 if suppliers.varsayilan_dil(tedarikci.get("ulke")) == "tr" else 1,
                      horizontal=True)
        gun = b.number_input("Yanıt süresi (gün)", 1, 90, 14)
        alici = c.text_input("Alıcı e-posta", tedarikci.get("eposta") or "")
        mesaj = st.text_area("Ek not (isteğe bağlı)")
        gonder = st.form_submit_button("Talebi hazırla", type="primary")
    if gonder:
        try:
            tid, token = suppliers.talep_olustur(db, f, tedarikci["id"], [urunler[s] for s in secilen], istenen, mesaj, gun, o.eposta(),
                                                 dil="tr" if dil == "Türkçe" else "en", eposta=alici or None)
            _hazirla(db, f, tid, token)
            st.rerun()
        except ValueError as h:
            st.error(str(h))


# ---------------------------------------------------------------------------
# Karne ve beyanlar
# ---------------------------------------------------------------------------

def _karne(f):
    k = suppliers.karne(o.db(), f)
    if not k:
        st.caption("Tedarikçi yok.")
        return
    st.dataframe(pd.DataFrame([{
        "Tedarikçi": x["unvan"], "Ülke": x.get("ulke") or "—", "Puan": x["puan"], "Ürün": x["urun_sayisi"], "Talep": x["talep"],
        "Yanıtlanan": x["yanitlanan"], "Yanıt oranı (%)": None if x["yanit_orani"] is None else round(x["yanit_orani"]),
        "Ort. yanıt (gün)": None if x["ort_yanit_gun"] is None else round(x["ort_yanit_gun"], 1), "Açık": x["acik"],
        "Süresi dolan": x["suresi_dolan"], "Açık eksik": x["eksik_kalem"], "Son yanıt": o.tarih_tr(x["son_yanit"]),
    } for x in k]), hide_index=True,
        column_config={"Puan": st.column_config.ProgressColumn("Puan", min_value=0, max_value=100, format="%d")})
    st.caption("Puan: yanıt oranı %50, yanıt hızı %20 (her gün 7 puan düşer), açık eksik azlığı %30 (her eksik 15 puan düşer). "
               "Hiç talep gönderilmemiş tedarikçide puan hesaplanmaz.")


def _beyanlar(f):
    db = o.db()
    b = suppliers.beyanlar(db, f)
    st.caption("Kabul ettiğiniz tedarikçi beyanları ürün bazında saklanır. Ürünün SVHC beyanı, ürünün tüm tedarikçileri 'Yok' "
               "beyan ettiğinde 'Yok', herhangi biri 'Var' dediğinde 'Var' olarak güncellenir.")
    if not b:
        st.caption("Henüz kabul edilmiş beyan yok.")
        return
    st.dataframe(pd.DataFrame([{
        "Ürün": x["urun_kodu"], "Tedarikçi": x["tedarikci"], "SVHC": x.get("svhc_beyani") or "—", "Maddeler": x.get("svhc_maddeler") or "",
        "Menşe": x.get("mense") or "", "Karbon (kg CO2e)": x.get("karbon_kg"), "Yanıtlayan": x.get("yanitlayan") or "",
        "Tarih": o.tarih_tr(x.get("tarih")), "Kabul eden": x.get("kabul_eden") or "",
    } for x in b]), hide_index=True)
    st.markdown("**Ürün bazında SVHC durumu**")
    ozet = []
    for kod in sorted({x["urun_kodu"] for x in b}):
        u = repo.urun_kod_ile(db, f, kod)
        beyan, _, aciklama = suppliers.svhc_sentezi(db, f, u["id"])
        ozet.append({"Ürün": kod, "Ürün kartındaki beyan": u.get("svhc_beyani") or "—", "Tedarikçi beyanlarından": beyan or "Tamamlanmadı",
                     "Açıklama": aciklama})
    st.dataframe(pd.DataFrame(ozet), hide_index=True)
