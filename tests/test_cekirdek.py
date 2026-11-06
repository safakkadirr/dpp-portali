"""Çekirdek birim testleri. Çalıştırma: python -m pytest -q"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dpp import audit, demo, evaluation, importer, passport, repo, reports, security, suppliers  # noqa: E402
from dpp.db import Veritabani  # noqa: E402
from dpp.util import gtin_dogrula, gtin_tamamla, gtip_dogrula, malzeme_ayristir  # noqa: E402


@pytest.fixture
def db():
    d = Veritabani("sqlite:///:memory:")
    d.sema_olustur()
    return d


@pytest.fixture
def firma(db):
    return demo.demo_firma_olustur(db, "test")


def test_gtin():
    assert gtin_dogrula(gtin_tamamla("869000000001"))[0]
    assert not gtin_dogrula("0123456789012")[0]
    assert not gtin_dogrula("8690000000017")[0]
    assert gtip_dogrula("6109.10")[0] and not gtip_dogrula("61")[0]


def test_malzeme_ayristir():
    assert malzeme_ayristir("Pamuk:95;Elastan:5") == [("Pamuk", 95.0), ("Elastan", 5.0)]
    assert malzeme_ayristir("%60 Pamuk, %40 Polyester") == [("Pamuk", 60.0), ("Polyester", 40.0)]


def test_parola_ve_kilit(db):
    f = repo.firma_kaydet(db, {"unvan": "A"}, "t")
    security.kullanici_olustur(db, "a@b.co", "A", "editor", "Parola12345", f)
    assert security.giris(db, "a@b.co", "Parola12345")[0]
    for _ in range(5):
        security.giris(db, "a@b.co", "yanlis")
    assert security.giris(db, "a@b.co", "Parola12345")[0] is None
    with pytest.raises(ValueError):
        security.kullanici_olustur(db, "x@b.co", "X", "editor", "kisa", f)


def test_esit_yetkiler():
    for rol in ("firma_yonetici", "editor", "denetci", "izleyici"):
        for eylem in ("veri_duzenle", "belge_dogrula", "urun_dogrula", "pasaport_yayimla", "kullanici_yonet", "iz_gor"):
            assert security.yetkili(rol, eylem)
        assert not security.yetkili(rol, "firma_yonet") and not security.yetkili(rol, "kural_yonet")
    assert security.yetkili("platform_yonetici", "firma_yonet")


def test_demo_durumlari(db, firma):
    d = {u["urun_kodu"]: u["genel_durum"] for u in repo.urunler(db, firma)}
    assert d["TK-1002"] == "Kritik eksik"
    assert d["TK-1001"] == "Hazır"


def test_kiraci_ayrimi(db, firma):
    baska = repo.firma_kaydet(db, {"unvan": "Başka"}, "t")
    u = repo.urunler(db, firma)[0]
    assert repo.urun(db, baska, u["id"]) is None
    assert repo.belgeler(db, baska) == []


def test_kritik_eksikte_yayim_engeli(db, firma):
    denim = repo.urun_kod_ile(db, firma, "TK-1002")
    with pytest.raises(ValueError):
        passport.yayimla(db, firma, denim["id"], None, "t", "https://x")


def test_pasaport_surum_ve_erisim(db, firma):
    tk = repo.urun_kod_ile(db, firma, "TK-1001")
    r1 = passport.yayimla(db, firma, tk["id"], None, "t", "https://x")
    r2 = passport.yayimla(db, firma, tk["id"], None, "t", "https://x")
    assert r1["genel_kimlik"] == r2["genel_kimlik"] and r2["surum"] == 2
    k = passport.kamu_kaydi(db, r1["genel_kimlik"])
    assert k["surum"] == 2 and k["ozet_dogru"]
    assert "dpp:gtip" not in passport.gorunum(k["icerik"], "Kamu")
    assert passport.erisim_seviyesi(k, r1["alici_kodu"]) == "Alıcı (B2B)"
    assert passport.erisim_seviyesi(k, "yanlis") == "Kamu"


def test_tedarikci_akisi(db, firma):
    denim = repo.urun_kod_ile(db, firma, "TK-1002")
    onceki = repo.alt_liste(db, "malzemeler", firma, denim["id"])
    db.yaz("UPDATE malzemeler SET tedarikci_id = NULL WHERE urun_id = ?", (denim["id"],))
    db.yaz("DELETE FROM tedarik_asamalari WHERE urun_id = ?", (denim["id"],))
    ted = repo.tedarikciler(db, firma)[0]
    tid, token = suppliers.talep_olustur(db, firma, ted["id"], denim["id"], ["svhc", "malzeme"], "", 7, "t")
    assert suppliers.token_ile(db, token)["urun_kodu"] == "TK-1002"
    suppliers.acildi(db, token)
    suppliers.yanitla(db, token, {"svhc_beyani": "Yok", "malzemeler": [{"malzeme": "Pamuk", "oran": 100}]}, [], "Ali")
    with pytest.raises(ValueError):
        suppliers.yanitla(db, token, {}, [], "Ali")          # boş güncelleme kabul edilmez
    suppliers.yanitla(db, token, {"not": "ek bilgi"}, [], "Ali")   # süre içinde güncelleme
    t = suppliers.talep(db, firma, tid)
    assert t["gorunen_durum"] == "Yanıtlandı" and t["yanit_sayisi"] == 2 and t["acilis_sayisi"] == 1
    suppliers.urune_aktar(db, firma, tid, "t")
    assert repo.urun(db, firma, denim["id"])["svhc_beyani"] == "Yok"   # ürünün tek tedarikçisi 'Yok' dedi
    sonra = repo.alt_liste(db, "malzemeler", firma, denim["id"])
    # firmanın girdiği bileşim silinmez; tedarikçinin içeriği bileşen satırı olarak eklenir
    assert len(sonra) == len(onceki) + 1 and any("Pamuk %100" in m["malzeme"] for m in sonra)
    with pytest.raises(ValueError):
        suppliers.yanitla(db, token, {"not": "x"}, [], "Ali")       # kapanan talep yanıtlanamaz


def test_tedarikci_svhc_sentezi_ve_hatirlatma(db, firma):
    u = repo.urun_kod_ile(db, firma, "TK-1001")
    t1, t2 = repo.tedarikciler(db, firma)[:2]
    db.yaz("DELETE FROM malzemeler WHERE urun_id = ?", (u["id"],))
    db.yaz("DELETE FROM tedarik_asamalari WHERE urun_id = ?", (u["id"],))
    repo.urun_kaydet(db, firma, {"svhc_beyani": None}, "t", u["id"])
    repo.alt_degistir(db, "malzemeler", firma, u["id"], [{"malzeme": "Kumaş", "oran": 90, "tedarikci_id": t1["id"]},
                                                          {"malzeme": "Düğme", "oran": 10, "tedarikci_id": t2["id"]}], "t")
    analiz = {a["tedarikci_id"]: a for a in suppliers.eksik_analizi(db, firma)}
    assert "svhc" in analiz[t1["id"]]["istenenler"] and "svhc" in analiz[t2["id"]]["istenenler"]
    a, tok_a = suppliers.talep_olustur(db, firma, t1["id"], [u["id"]], ["svhc"], "", 7, "t")
    suppliers.yanitla(db, tok_a, {"urunler": {str(u["id"]): {"svhc_beyani": "Yok"}}}, [], "A")
    suppliers.urune_aktar(db, firma, a, "t")
    assert not repo.urun(db, firma, u["id"])["svhc_beyani"]            # bir tedarikçi eksik: ürün 'Yok' sayılmaz
    b, tok_b = suppliers.talep_olustur(db, firma, t2["id"], [u["id"]], ["svhc"], "", 7, "t")
    yeni = suppliers.yeni_baglanti(db, firma, b, 5, "t")
    assert suppliers.token_ile(db, tok_b) is None and suppliers.token_ile(db, yeni)
    suppliers.yanitla(db, yeni, {"urunler": {str(u["id"]): {"svhc_beyani": "Yok"}}}, [], "B")
    suppliers.urune_aktar(db, firma, b, "t")
    assert repo.urun(db, firma, u["id"])["svhc_beyani"] == "Yok"
    assert len(suppliers.beyanlar(db, firma, u["id"])) == 2
    assert any(k["talep"] for k in suppliers.karne(db, firma))


def test_disa_ice_aktarim_esdegerligi(db, firma):
    db.yaz("UPDATE belgeler SET dogrulama_durumu = 'Beklemede'")
    evaluation.firma_degerlendir(db, firma)
    yeni = repo.firma_kaydet(db, {"unvan": "Kopya"}, "t")
    o = importer.oku([("x.xlsx", importer.disa_aktar(db, firma))], db, yeni)
    assert not o.hatalar
    importer.uygula(db, yeni, o, "t")
    evaluation.firma_degerlendir(db, yeni)
    a = {u["urun_kodu"]: u["hazirlik_skoru"] for u in repo.urunler(db, firma)}
    b = {u["urun_kodu"]: u["hazirlik_skoru"] for u in repo.urunler(db, yeni)}
    assert a == b


def test_dogrulama_sonrasi_degisiklik(db, firma):
    tk = repo.urun_kod_ile(db, firma, "TK-1001")
    evaluation.urun_dogrula(db, firma, tk["id"], "D", "YMM", "Doğrulandı", "kapsam", "")
    assert evaluation.dogrulama_gecerli_mi(db, firma, tk["id"])[1]
    repo.urun_kaydet(db, firma, {"marka": "Değişti"}, "t", tk["id"])
    assert not evaluation.dogrulama_gecerli_mi(db, firma, tk["id"])[1]


def test_raporlar(db, firma):
    assert reports.pdf_hazirlik_raporu(db, firma, "Test")[:4] == b"%PDF"
    assert len(reports.excel_rapor(db, firma, "Test")) > 1000


def test_denetim_zinciri(db, firma):
    assert audit.zinciri_dogrula(db)[0]
    db.yaz("UPDATE denetim_izi SET detay = 'oynandı' WHERE id = 3")
    assert not audit.zinciri_dogrula(db)[0]


def _excel(sayfalar: dict, baslik_ustu: int = 0) -> bytes:
    import io
    import pandas as pd
    c = io.BytesIO()
    with pd.ExcelWriter(c) as w:
        for ad, df in sayfalar.items():
            df.to_excel(w, sheet_name=ad, index=False, startrow=baslik_ustu)
    return c.getvalue()


def test_akilli_esleme_ham_dosya(db):
    import pandas as pd
    f = repo.firma_kaydet(db, {"unvan": "Ham"}, "t")
    veri = _excel({"Liste": pd.DataFrame({
        "MODEL KODU": ["A-1", "A-2", None], "Ürün Adı": ["Tişört", "Gömlek", None], "Kumaş İçeriği": ["95% Cotton 5% Elastane", "Keten", None],
        "Menşei": ["Türkiye", "Türkiye", None], "Maliyet": [3, 4, 5], "Sertifika": ["GOTS, OEKO-TEX", None, None],
        "Sertifika Bitiş": ["31.08.2027", None, None], "Sezon": ["SS27", "AW26", None]})}, baslik_ustu=2)
    o = importer.oku([("ham.xlsx", veri)], db, f)
    alanlar = {r["Excel sütunu"]: r["Alan"] for r in o.esleme_raporu}
    assert alanlar["MODEL KODU"] == "Urun_Kodu" and alanlar["Kumaş İçeriği"] == "_Malzeme_Bilesimi"
    assert alanlar["Maliyet"] is None and alanlar["Sezon"] is None
    s = importer.uygula(db, f, o, "t", bilinmeyenleri_nota=True)
    assert s.sayac["urun_yeni"] == 2 and s.sayac["belge"] == 2
    a1 = repo.urun_kod_ile(db, f, "A-1")
    assert [(m["malzeme"], m["oran"]) for m in repo.alt_liste(db, "malzemeler", f, a1["id"])] == [("Cotton", 95.0), ("Elastane", 5.0)]
    assert "Sezon: SS27" in a1["notlar"] and a1["sektor_kodu"] == "tekstil" and a1["svhc_beyani"] is None
    importer.uygula(db, f, importer.oku([("ham.xlsx", veri)], db, f), "t")
    assert len(repo.urunler(db, f)) == 2 and len(repo.belgeler(db, f)) == 2


def test_elle_esleme_ve_satir_hatasi(db):
    import pandas as pd
    f = repo.firma_kaydet(db, {"unvan": "Elle"}, "t")
    veri = _excel({"Sheet1": pd.DataFrame({"x": ["K-1", "K-2"], "y": ["Masa", "Sandalye"]})})
    assert not importer.oku([("e.xlsx", veri)], db, f).gecerli
    o = importer.oku([("e.xlsx", veri)], db, f, elle={"e.xlsx|Sheet1|x": "Urun_Kodu", "e.xlsx|Sheet1|y": "Urun_Adi"},
                     elle_tur={"e.xlsx|Sheet1": "Urunler"})
    assert o.gecerli and o.yeni_urun == 2
    # Bağlanacak ürünü olmayan belge satırı tüm aktarımı bozmaz
    o.sayfalar["Belgeler"] = pd.DataFrame([{"Baglanti": "YOK-1", "Belge_Turu": "GOTS", "_kaynak": "e", "_satir": 9}])
    s = importer.uygula(db, f, o, "t")
    assert s.sayac["urun_yeni"] == 2 and len(s.atlanan) == 1
