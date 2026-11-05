"""Satış sunumu ve eğitim için örnek firma verisi (farklı sektörler, bilerek eksikler içerir)."""

from __future__ import annotations

from datetime import date, timedelta

from . import evaluation, repo
from .db import Veritabani
from .util import gtin_tamamla


def demo_firma_olustur(db: Veritabani, kullanici: str, unvan: str = "Örnek İhracat A.Ş. (Demo)") -> int:
    bugun = date.today()
    with db.islem():
        f = repo.firma_kaydet(db, {"unvan": unvan, "adres": "Ankara, Türkiye", "ulke": "Türkiye", "eposta": "dis-ticaret@ornek.com.tr",
                                   "plan": "Demo"}, kullanici)
        t_bursa = repo.tesis_bul_veya_ekle(db, f, "Bursa OSB Tesisi", {"adres": "Bursa OSB", "ulke": "Türkiye", "gln": gtin_tamamla("869000000901")})
        t_manisa = repo.tesis_bul_veya_ekle(db, f, "Manisa OSB Tesisi", {"adres": "Manisa OSB", "ulke": "Türkiye"})
        t_iskenderun = repo.tesis_bul_veya_ekle(db, f, "İskenderun Çelik Tesisi", {"adres": "İskenderun, Hatay", "ulke": "Türkiye",
                                                                                     "gln": gtin_tamamla("869000000904")})
        t_ankara = repo.tesis_bul_veya_ekle(db, f, "Ankara OSTİM Tesisi", {"adres": "OSTİM, Ankara", "ulke": "Türkiye"})
        iplik = repo.tedarikci_bul_veya_ekle(db, f, "Örnek İplik Ltd.", {"ulke": "Türkiye", "eposta": "kalite@ornekiplik.com.tr"})
        boya = repo.tedarikci_bul_veya_ekle(db, f, "Örnek Boya Terbiye A.Ş.", {"ulke": "Türkiye", "eposta": "kalite@ornekboya.com.tr"})
        led = repo.tedarikci_bul_veya_ekle(db, f, "Shenzhen Example Electronics", {"ulke": "Çin", "eposta": "qa@example.cn"})
        hucre = repo.tedarikci_bul_veya_ekle(db, f, "Example Cell Co.", {"ulke": "Çin"})
        kereste = repo.tedarikci_bul_veya_ekle(db, f, "Karpat Kereste SRL", {"ulke": "Romanya"})

        def urun(veri, malzemeler=(), asamalar=(), partiler=()):
            uid = repo.urun_kaydet(db, f, veri, kullanici)
            repo.alt_degistir(db, "malzemeler", f, uid, list(malzemeler), kullanici, denetle=False)
            repo.alt_degistir(db, "tedarik_asamalari", f, uid, list(asamalar), kullanici, denetle=False)
            repo.alt_degistir(db, "partiler", f, uid, list(partiler), kullanici, denetle=False)
            return uid

        tisort = urun({"urun_kodu": "TK-1001", "ad": "Organik Pamuk Tişört", "sektor_kodu": "tekstil", "tuketici_urunu": 1,
                       "gtin": gtin_tamamla("869000000001"), "gtip": "6109.10", "tesis_id": t_bursa, "marka": "Örnek",
                       "ab_sorumlu_operator": "Beispiel Mode GmbH, Köln, info@beispiel.de", "uretim_ulkesi": "Türkiye",
                       "hammadde_mensei": "Türkiye", "svhc_beyani": "Yok", "cevresel_iddia": "Organik pamuk",
                       "karbon_kg": 4.1, "karbon_yontemi": "ISO 14067", "bakim_onarim": "30°C'de ters yıkayın",
                       "omur_sonu": "Tekstil geri dönüşüm noktasına bırakınız"},
                      [{"malzeme": "Organik pamuk", "oran": 95, "mense": "Türkiye", "tedarikci_id": iplik},
                       {"malzeme": "Elastan", "oran": 5, "mense": "Türkiye"}],
                      [{"sira": 1, "asama": "İplik", "tedarikci_id": iplik, "ulke": "Türkiye"},
                       {"sira": 2, "asama": "Örme ve boya-terbiye", "tedarikci_id": boya, "ulke": "Türkiye"},
                       {"sira": 3, "asama": "Konfeksiyon", "ulke": "Türkiye"}],
                      [{"parti_no": "LOT-2026-101", "uretim_tarihi": (bugun - timedelta(days=40)).isoformat(), "miktar": 5000, "tesis_id": t_bursa}])
        denim = urun({"urun_kodu": "TK-1002", "ad": "Geri Dönüştürülmüş Denim Pantolon", "sektor_kodu": "tekstil", "tuketici_urunu": 1,
                      "gtin": "0123456789012", "gtip": "6203.42", "uretim_ulkesi": "Türkiye", "hammadde_mensei": "Pakistan",
                      "geri_donusturulmus_yuzde": 28, "svhc_beyani": "Bilinmiyor"},
                     [{"malzeme": "Pamuk", "oran": 70, "mense": "Pakistan"}, {"malzeme": "Geri dönüştürülmüş pamuk", "oran": 28,
                                                                            "geri_donusturulmus": 1}])
        led_panel = urun({"urun_kodu": "EL-2001", "ad": "LED Panel Armatür 40W", "sektor_kodu": "elektronik", "tuketici_urunu": 1,
                          "gtin": gtin_tamamla("869000000002"), "gtip": "9405.11", "tesis_id": t_ankara,
                          "ab_sorumlu_operator": "Lumen Import BV, Rotterdam, sales@lumen.nl", "uretim_ulkesi": "Türkiye",
                          "svhc_beyani": "Yok", "bakim_onarim": "LED sürücüsü değiştirilebilir", "omur_sonu": "WEEE toplama noktasına"},
                         [{"malzeme": "Alüminyum", "oran": 55, "mense": "Türkiye"}, {"malzeme": "Polikarbonat", "oran": 30, "mense": "Türkiye"},
                          {"malzeme": "Elektronik kart", "oran": 15, "mense": "Çin", "tedarikci_id": led}],
                         [{"sira": 1, "asama": "LED çip ve sürücü", "tedarikci_id": led, "ulke": "Çin"},
                          {"sira": 2, "asama": "Montaj ve test", "ulke": "Türkiye"}],
                         [{"parti_no": "EL-26-07", "uretim_tarihi": (bugun - timedelta(days=20)).isoformat(), "tesis_id": t_ankara}])
        camasir = urun({"urun_kodu": "BE-3001", "ad": "Çamaşır Makinesi 9 kg", "sektor_kodu": "beyaz_esya", "tuketici_urunu": 1,
                        "gtin": gtin_tamamla("869000000003"), "gtip": "8450.11", "tesis_id": t_manisa, "uretim_ulkesi": "Türkiye",
                        "hammadde_mensei": "Türkiye", "svhc_beyani": "Yok", "eprel_no": "1234567", "bakim_onarim": "Yedek parça 10 yıl",
                        "omur_sonu": "WEEE toplama noktasına"},
                       [{"malzeme": "Çelik", "oran": 60}, {"malzeme": "Plastik", "oran": 30}, {"malzeme": "Bakır", "oran": 5},
                        {"malzeme": "Diğer", "oran": 5}])
        demir = urun({"urun_kodu": "DC-4001", "ad": "İnşaat Demiri B500C", "sektor_kodu": "demir_celik", "tuketici_urunu": 0,
                      "gtin": gtin_tamamla("869000000004"), "gtip": "7214.20", "tesis_id": t_iskenderun, "uretim_ulkesi": "Türkiye",
                      "hammadde_mensei": "Türkiye", "geri_donusturulmus_yuzde": 85, "svhc_beyani": "Yok", "gomulu_emisyon": 0.48,
                      "bakim_onarim": "Uygulanmaz", "omur_sonu": "Hurda olarak geri kazanılır"},
                     [{"malzeme": "Çelik", "oran": 100, "mense": "Türkiye"}],
                     [{"sira": 1, "asama": "Hurda toplama", "ulke": "Türkiye"}, {"sira": 2, "asama": "Ark ocağı ve haddeleme", "ulke": "Türkiye"}],
                     [{"parti_no": "DK-2611-04", "uretim_tarihi": (bugun - timedelta(days=5)).isoformat(), "miktar": 120, "tesis_id": t_iskenderun}])
        masa = urun({"urun_kodu": "MB-5001", "ad": "Meşe Yemek Masası", "sektor_kodu": "mobilya", "tuketici_urunu": 1,
                     "gtin": gtin_tamamla("869000000005"), "gtip": "9403.60", "uretim_ulkesi": "Türkiye", "svhc_beyani": "Yok",
                     "cevresel_iddia": "Doğal ahşap"},
                    [{"malzeme": "Meşe kereste", "oran": 90, "mense": "Romanya", "tedarikci_id": kereste},
                     {"malzeme": "Çelik bağlantı", "oran": 10, "mense": "Türkiye"}],
                    [{"sira": 1, "asama": "Kereste", "tedarikci_id": kereste, "ulke": "Romanya"}, {"sira": 2, "asama": "Üretim", "ulke": "Türkiye"}])
        batarya = urun({"urun_kodu": "BT-6001", "ad": "E-Bisiklet Bataryası 0,5 kWh", "sektor_kodu": "batarya", "tuketici_urunu": 1,
                        "gtin": gtin_tamamla("869000000006"), "gtip": "8507.60", "tesis_id": t_ankara,
                        "ab_sorumlu_operator": "EBike Parts SAS, Lyon, contact@ebp.fr", "uretim_ulkesi": "Türkiye", "hammadde_mensei": "Çin",
                        "svhc_beyani": "Yok", "batarya_kategori": "LMT", "batarya_kimya": "NMC", "batarya_kwh": 0.5},
                       [{"malzeme": "Hücreler", "oran": 70, "mense": "Çin", "tedarikci_id": hucre}, {"malzeme": "Kasa", "oran": 20, "mense": "Türkiye"},
                        {"malzeme": "BMS", "oran": 10, "mense": "Türkiye"}],
                       [{"sira": 1, "asama": "Hücre üretimi", "tedarikci_id": hucre, "ulke": "Çin"}, {"sira": 2, "asama": "Paketleme ve BMS", "ulke": "Türkiye"}])
        balata = urun({"urun_kodu": "OT-7001", "ad": "Fren Balatası", "sektor_kodu": "otomotiv", "tuketici_urunu": 0,
                       "gtin": gtin_tamamla("869000000007"), "gtip": "6813.81", "tesis_id": t_bursa, "uretim_ulkesi": "Türkiye",
                       "hammadde_mensei": "Türkiye", "svhc_beyani": "Yok", "imds_id": "123456789",
                       "bakim_onarim": "Aşınma göstergesine göre değiştirin", "omur_sonu": "Yetkili atık firmasına"},
                      [{"malzeme": "Çelik", "oran": 45}, {"malzeme": "Reçine", "oran": 20}, {"malzeme": "Lif", "oran": 20}, {"malzeme": "Dolgu", "oran": 15}])

        def belge(veri, baglar, dogrulandi=False):
            bid = repo.belge_ekle(db, f, veri, baglar, kullanici, kaynak="Demo")
            if dogrulandi:
                db.guncelle("belgeler", bid, {"dogrulama_durumu": "Doğrulandı", "dogrulayan": "Demo doğrulayıcı",
                                              "dogrulama_tarihi": bugun.isoformat()}, f)

        belge({"tur_kodu": "GOTS", "belge_no": "CU-889911", "duzenleyen": "Control Union",
               "bitis": (bugun + timedelta(days=300)).isoformat(), "kapsam": "Örme ürünler"}, [("urun", tisort)], True)
        belge({"tur_kodu": "OEKOTEX", "belge_no": "OT-55621", "duzenleyen": "Hohenstein",
               "bitis": (bugun + timedelta(days=40)).isoformat()}, [("tedarikci", boya)], True)
        belge({"tur_kodu": "REACH", "belge_no": "SVHC-2026-11", "duzenleyen": "Örnek İplik Ltd."}, [("tedarikci", iplik)])
        belge({"tur_kodu": "ISO9001", "belge_no": "Q-1200", "duzenleyen": "TSE", "bitis": (bugun + timedelta(days=420)).isoformat()},
              [("urun", denim)])
        belge({"tur_kodu": "GRS", "belge_no": "GRS-778", "duzenleyen": "Control Union", "bitis": (bugun - timedelta(days=30)).isoformat()},
              [("urun", denim)])
        belge({"tur_kodu": "CE_DOC", "belge_no": "DoC-2026-14"}, [("urun", led_panel)], True)
        belge({"tur_kodu": "ROHS", "belge_no": "SGS-RH-22", "duzenleyen": "SGS", "bitis": (bugun + timedelta(days=120)).isoformat()},
              [("urun", led_panel)], True)
        belge({"tur_kodu": "WEEE", "belge_no": "DE 12345678", "duzenleyen": "stiftung ear"}, [("urun", led_panel), ("urun", camasir)])
        belge({"tur_kodu": "CE_DOC", "belge_no": "DoC-BE-9"}, [("urun", camasir)])
        belge({"tur_kodu": "ROHS", "belge_no": "RH-BE-9"}, [("urun", camasir)])
        belge({"tur_kodu": "EPD", "belge_no": "EPD-TR-2026-01", "duzenleyen": "EPD Türkiye",
               "bitis": (bugun + timedelta(days=1500)).isoformat()}, [("urun", demir)], True)
        belge({"tur_kodu": "FSC", "belge_no": "FSC-C123456", "duzenleyen": "SGS", "bitis": (bugun + timedelta(days=540)).isoformat()},
              [("tedarikci", kereste)])
        belge({"tur_kodu": "CE_DOC", "belge_no": "DoC-BT-1"}, [("urun", batarya)])
        belge({"tur_kodu": "IATF", "belge_no": "IATF-0091", "duzenleyen": "TÜV", "bitis": (bugun + timedelta(days=360)).isoformat()},
              [("urun", balata)])
        belge({"tur_kodu": "ISO14001", "belge_no": "EMS-001", "duzenleyen": "TSE", "bitis": (bugun + timedelta(days=600)).isoformat(),
               "kapsam": "Firma geneli"}, [("firma", None)])
    evaluation.firma_degerlendir(db, f, kullanici)
    return f
