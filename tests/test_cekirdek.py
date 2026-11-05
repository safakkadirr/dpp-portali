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


def test_gorevler_ayriligi():
    assert security.yetkili("editor", "veri_duzenle") and not security.yetkili("editor", "belge_dogrula")
    assert security.yetkili("denetci", "belge_dogrula") and not security.yetkili("denetci", "veri_duzenle")
    assert not security.yetkili("izleyici", "veri_duzenle")


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
    ted = repo.tedarikciler(db, firma)[0]
    tid, token = suppliers.talep_olustur(db, firma, ted["id"], denim["id"], ["svhc", "malzeme"], "", 7, "t")
    suppliers.yanitla(db, token, {"svhc_beyani": "Yok", "malzemeler": [{"malzeme": "Pamuk", "oran": 100}]}, [], "Ali")
    with pytest.raises(ValueError):
        suppliers.yanitla(db, token, {}, [], "Ali")
    suppliers.urune_aktar(db, firma, tid, "t")
    assert repo.urun(db, firma, denim["id"])["svhc_beyani"] == "Yok"
    assert sum(m["oran"] for m in repo.alt_liste(db, "malzemeler", firma, denim["id"])) == 100


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
