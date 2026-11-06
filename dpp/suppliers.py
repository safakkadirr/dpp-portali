"""
Tedarikçi Portalı: eksik analizi, veri talepleri, tedarikçi yanıtları ve tedarikçi karnesi.

Akış
  1. Eksik analizi, her tedarikçi için hangi ürünlerde hangi bilginin eksik olduğunu bulur
     (SVHC beyanı, bileşim oranı, menşe, süresi dolan / reddedilen belge).
  2. Firma tek tıkla bir veya birden çok tedarikçiye talep hazırlar. Bir talep birden fazla
     ürünü kapsayabilir; tedarikçi tek bağlantıdan hepsini yanıtlar.
  3. Tedarikçi hesap açmadan bağlantıya girer (Türkçe / İngilizce), bilgileri girer, belgeleri
     yükler. Süre bitene veya firma kapatana kadar yanıtını güncelleyebilir.
  4. Firma yanıtı inceler; kabul ederse ürüne aktarılır, eksikse revizyon ister.

Bağlantının açık hali sistemde saklanmaz (yalnızca SHA-256 özeti). Hatırlatma, yeni bağlantı üretir.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Optional

from . import audit, repo
from .db import Veritabani, simdi
from .rules import BELGE_DOLMUS
from .security import token_ozeti, token_uret
from .util import bos_mu, metin, sayi, tr_norm

ISTENEBILIR = {
    "malzeme": "Malzeme bileşimi (malzeme, oran, menşe)",
    "svhc": "REACH / SVHC beyanı",
    "mense": "Menşe bilgisi",
    "karbon": "Karbon ayak izi",
    "belge": "Belge / sertifika yükleme",
}

ACIK_DURUMLAR = ("Açık", "Revizyon istendi", "Yanıtlandı")
EN_BUYUK_DOSYA = 10 * 1024 * 1024
_BOS_SVHC = ("", "bilinmiyor", "belirsiz", "none", "unknown")


def _bugun() -> str:
    return date.today().isoformat()


def varsayilan_dil(ulke: Optional[str]) -> str:
    u = tr_norm(ulke or "")
    return "tr" if (not u or "turk" in u or u in ("tr", "tur")) else "en"


# ---------------------------------------------------------------------------
# Eksik analizi
# ---------------------------------------------------------------------------

def _tedarikci_urunleri(db: Veritabani, firma_id: int) -> dict[int, set[int]]:
    """tedarikci_id -> bu tedarikçinin malzeme veya tedarik aşaması olarak bağlı olduğu aktif ürünler."""
    harita: dict[int, set[int]] = {}
    for r in db.tumu("""
            SELECT m.tedarikci_id AS t, m.urun_id AS u FROM malzemeler m JOIN urunler x ON x.id = m.urun_id
            WHERE m.firma_id = ? AND m.tedarikci_id IS NOT NULL AND x.aktif = 1
            UNION
            SELECT a.tedarikci_id AS t, a.urun_id AS u FROM tedarik_asamalari a JOIN urunler x ON x.id = a.urun_id
            WHERE a.firma_id = ? AND a.tedarikci_id IS NOT NULL AND x.aktif = 1""", (firma_id, firma_id)):
        harita.setdefault(r["t"], set()).add(r["u"])
    return harita


def urun_tedarikcileri(db: Veritabani, firma_id: int, urun_id: int) -> set[int]:
    return {r["tedarikci_id"] for r in db.tumu(
        "SELECT tedarikci_id FROM malzemeler WHERE firma_id = ? AND urun_id = ? AND tedarikci_id IS NOT NULL "
        "UNION SELECT tedarikci_id FROM tedarik_asamalari WHERE firma_id = ? AND urun_id = ? AND tedarikci_id IS NOT NULL",
        (firma_id, urun_id, firma_id, urun_id))}


def beyanlar(db: Veritabani, firma_id: int, urun_id: Optional[int] = None, tedarikci_id: Optional[int] = None) -> list[dict]:
    sql = """SELECT b.*, t.unvan AS tedarikci, u.urun_kodu FROM tedarikci_beyanlari b
             JOIN tedarikciler t ON t.id = b.tedarikci_id JOIN urunler u ON u.id = b.urun_id WHERE b.firma_id = ?"""
    p: list = [firma_id]
    if urun_id:
        sql += " AND b.urun_id = ?"
        p.append(urun_id)
    if tedarikci_id:
        sql += " AND b.tedarikci_id = ?"
        p.append(tedarikci_id)
    return db.tumu(sql + " ORDER BY u.urun_kodu, t.unvan", p)


def eksik_analizi(db: Veritabani, firma_id: int, bugun: Optional[date] = None) -> list[dict]:
    """Her tedarikçi için istenmesi gereken bilgileri çıkarır. Öncelik puanına göre sıralı döner."""
    bugun = bugun or date.today()
    ted_urun = _tedarikci_urunleri(db, firma_id)
    urunler = {u["id"]: u for u in db.tumu("SELECT * FROM urunler WHERE firma_id = ? AND aktif = 1", (firma_id,))}
    malzeme = db.tumu("SELECT * FROM malzemeler WHERE firma_id = ? AND tedarikci_id IS NOT NULL", (firma_id,))
    asama = db.tumu("SELECT * FROM tedarik_asamalari WHERE firma_id = ? AND tedarikci_id IS NOT NULL", (firma_id,))
    beyan = {(b["tedarikci_id"], b["urun_id"]): b for b in db.tumu("SELECT * FROM tedarikci_beyanlari WHERE firma_id = ?", (firma_id,))}
    acik: dict[int, int] = {}
    for t in db.tumu("SELECT tedarikci_id, son_tarih, durum FROM tedarikci_talepleri WHERE firma_id = ?", (firma_id,)):
        if gorunen_durum(t, bugun.isoformat()) in ("Gönderildi", "Görüntülendi", "Revizyon istendi", "Yanıtlandı"):
            acik[t["tedarikci_id"]] = acik.get(t["tedarikci_id"], 0) + 1
    belgeler = repo.belgeler(db, firma_id, bugun)
    sonuc = []
    for td in repo.tedarikciler(db, firma_id):
        tid = td["id"]
        urun_kalemleri = []
        istenen: set[str] = set()
        for uid in sorted(ted_urun.get(tid, set()), key=lambda x: urunler.get(x, {}).get("urun_kodu", "")):
            u = urunler.get(uid)
            if not u:
                continue
            eksik = []
            b = beyan.get((tid, uid))
            if tr_norm(u.get("svhc_beyani")) in _BOS_SVHC and not (b and not bos_mu(b.get("svhc_beyani"))):
                eksik.append("svhc")
            satirlar = [m for m in malzeme if m["urun_id"] == uid and m["tedarikci_id"] == tid]
            # Oranı boş ve içeriği de yazılmamış satır varsa (ör. yalnızca "Kumaş") tedarikçiden bileşim istenir.
            # "Denim kumaş (Pamuk %98, Elastan %2)" gibi içeriği bilinen satırın ürün içindeki payını firma belirler.
            if any(m.get("oran") is None and "%" not in metin(m["malzeme"]) for m in satirlar):
                eksik.append("malzeme")
            asamalar = [a for a in asama if a["urun_id"] == uid and a["tedarikci_id"] == tid]
            if (satirlar and any(bos_mu(m.get("mense")) for m in satirlar)) or \
                    (not satirlar and asamalar and all(bos_mu(a.get("ulke")) for a in asamalar)):
                if not (b and not bos_mu(b.get("mense"))):
                    eksik.append("mense")
            if eksik:
                urun_kalemleri.append({"id": uid, "kod": u["urun_kodu"], "ad": u["ad"], "eksik": eksik})
                istenen.update(eksik)
        bagli = [x for x in belgeler if any(g["hedef_tur"] == "tedarikci" and g["hedef_id"] == tid for g in x["baglantilar"])]
        belge_sorunlari = []
        for x in bagli:
            ad = metin(x.get("tur_serbest") or x["tur_kodu"])
            no = f" {x['belge_no']}" if x.get("belge_no") else ""
            if x["durum"] == BELGE_DOLMUS:
                belge_sorunlari.append(f"{ad}{no}: süresi dolmuş ({x.get('bitis')})")
            elif x["durum"] in ("30 gün içinde doluyor", "60 gün içinde doluyor"):
                belge_sorunlari.append(f"{ad}{no}: {x['durum'].lower()} ({x.get('bitis')})")
            elif x.get("dogrulama_durumu") == "Reddedildi":
                belge_sorunlari.append(f"{ad}{no}: reddedildi — {metin(x.get('dogrulama_notu'))[:80]}")
        if ted_urun.get(tid) and not bagli:
            belge_sorunlari.append("Hiç sertifika veya test raporu yüklenmemiş")
        if belge_sorunlari:
            istenen.add("belge")
        if not istenen:
            continue
        puan = sum(3 if "svhc" in k["eksik"] else 1 for k in urun_kalemleri) + 2 * len(belge_sorunlari)
        sonuc.append({
            "tedarikci_id": tid, "unvan": td["unvan"], "eposta": td.get("eposta"), "ulke": td.get("ulke"),
            "yetkili": td.get("yetkili"), "urunler": urun_kalemleri, "belge_sorunlari": belge_sorunlari,
            "istenenler": [k for k in ISTENEBILIR if k in istenen], "acik_talep": acik.get(tid, 0), "puan": puan,
            "dil": varsayilan_dil(td.get("ulke")),
        })
    sonuc.sort(key=lambda x: (-x["puan"], x["unvan"]))
    return sonuc


# ---------------------------------------------------------------------------
# Talepler
# ---------------------------------------------------------------------------

def talep_olustur(db: Veritabani, firma_id: int, tedarikci_id: int, urun_id, istenenler: list[str], mesaj: str, gun: int,
                  kullanici: str, dil: Optional[str] = None, kaynak: str = "Elle", eposta: Optional[str] = None) -> tuple[int, str]:
    """urun_id: tek ürün kimliği, ürün kimlikleri listesi veya None. (talep_id, açık bağlantı anahtarı) döner."""
    istenenler = [i for i in istenenler if i in ISTENEBILIR]
    if not istenenler:
        raise ValueError("En az bir bilgi türü seçin")
    td = db.bir("SELECT * FROM tedarikciler WHERE id = ? AND firma_id = ?", (tedarikci_id, firma_id))
    if not td:
        raise ValueError("Tedarikçi bulunamadı")
    idler = [urun_id] if isinstance(urun_id, int) else [int(x) for x in (urun_id or [])]
    idler = list(dict.fromkeys(i for i in idler if repo.urun(db, firma_id, i)))
    gun = max(1, min(int(gun or 14), 180))
    token = token_uret(24)
    kimlik = db.ekle("tedarikci_talepleri", {
        "firma_id": firma_id, "tedarikci_id": tedarikci_id, "urun_id": idler[0] if idler else None,
        "urun_idler": json.dumps(idler), "token_ozet": token_ozeti(token), "istenenler": json.dumps(istenenler),
        "mesaj": mesaj, "durum": "Açık", "son_tarih": (date.today() + timedelta(days=gun)).isoformat(), "olusturan": kullanici,
        "olusturma": simdi(), "dil": dil or varsayilan_dil(td.get("ulke")), "kaynak": kaynak,
        "gonderilen_eposta": eposta if eposta is not None else td.get("eposta"), "acilis_sayisi": 0, "hatirlatma_sayisi": 0,
        "yanit_sayisi": 0,
    })
    audit.kaydet(db, firma_id, kullanici, "Tedarikçi talebi oluşturuldu", "talep", kimlik,
                 f"{td['unvan']}: {', '.join(istenenler)}; {len(idler)} ürün")
    return kimlik, token


def _urun_idler(t: dict) -> list[int]:
    try:
        idler = json.loads(t.get("urun_idler") or "[]")
    except (TypeError, ValueError):
        idler = []
    if not idler and t.get("urun_id"):
        idler = [t["urun_id"]]
    return [int(i) for i in idler]


def gorunen_durum(t: dict, bugun: Optional[str] = None) -> str:
    bugun = bugun or _bugun()
    if t["durum"] in ("Açık", "Revizyon istendi") and t.get("son_tarih") and t["son_tarih"] < bugun:
        return "Süresi doldu"
    if t["durum"] == "Açık":
        return "Görüntülendi" if t.get("ilk_acilis") else "Gönderildi"
    return t["durum"]


DURUM_SIMGE = {"Gönderildi": "📨", "Görüntülendi": "👁️", "Revizyon istendi": "↩️", "Yanıtlandı": "📥", "Kapandı": "✅",
               "Süresi doldu": "⌛"}


def talepler(db: Veritabani, firma_id: int) -> list[dict]:
    satirlar = db.tumu("""
        SELECT t.*, td.unvan AS tedarikci, td.eposta, td.yetkili, td.ulke AS tedarikci_ulke
        FROM tedarikci_talepleri t JOIN tedarikciler td ON td.id = t.tedarikci_id
        WHERE t.firma_id = ? ORDER BY t.id DESC""", (firma_id,))
    kodlar = {u["id"]: (u["urun_kodu"], u["ad"]) for u in db.tumu("SELECT id, urun_kodu, ad FROM urunler WHERE firma_id = ?", (firma_id,))}
    bugun = _bugun()
    for s in satirlar:
        s["istenenler"] = json.loads(s["istenenler"] or "[]")
        s["yanit"] = json.loads(s["yanit_json"]) if s["yanit_json"] else None
        s["urun_idler"] = _urun_idler(s)
        s["urunler"] = [{"id": i, "kod": kodlar.get(i, ("?", ""))[0], "ad": kodlar.get(i, ("?", ""))[1]} for i in s["urun_idler"]]
        s["urun_kodu"] = ", ".join(u["kod"] for u in s["urunler"]) or None
        s["gorunen_durum"] = gorunen_durum(s, bugun)
    return satirlar


def talep(db: Veritabani, firma_id: int, talep_id: int) -> Optional[dict]:
    return next((t for t in talepler(db, firma_id) if t["id"] == talep_id), None)


def token_ile(db: Veritabani, token: str) -> Optional[dict]:
    if not token or len(token) > 100:
        return None
    t = db.bir("""
        SELECT t.*, f.unvan AS firma_unvan, f.eposta AS firma_eposta, td.unvan AS tedarikci_unvan
        FROM tedarikci_talepleri t JOIN firmalar f ON f.id = t.firma_id
        JOIN tedarikciler td ON td.id = t.tedarikci_id WHERE t.token_ozet = ?""", (token_ozeti(token),))
    if not t:
        return None
    t["istenenler"] = json.loads(t["istenenler"] or "[]")
    t["yanit"] = json.loads(t["yanit_json"]) if t.get("yanit_json") else None
    t["suresi_doldu"] = bool(t["son_tarih"] and t["son_tarih"] < _bugun())
    t["duzenlenebilir"] = t["durum"] in ACIK_DURUMLAR and not t["suresi_doldu"]
    t["urunler"] = []
    for i in _urun_idler(t):
        u = db.bir("SELECT id, urun_kodu, ad FROM urunler WHERE id = ? AND firma_id = ?", (i, t["firma_id"]))
        if u:
            u["malzemeler"] = db.tumu("SELECT malzeme, oran, mense, geri_donusturulmus FROM malzemeler "
                                      "WHERE urun_id = ? AND tedarikci_id = ? ORDER BY id", (i, t["tedarikci_id"]))
            t["urunler"].append(u)
    t["urun_kodu"] = t["urunler"][0]["urun_kodu"] if t["urunler"] else None
    t["urun_adi"] = t["urunler"][0]["ad"] if t["urunler"] else None
    # Tedarikçinin firmada kayıtlı belgeleri: yenileme gereksinimini görmesi için (dosya içeriği verilmez).
    t["mevcut_belgeler"] = []
    for x in repo.belgeler(db, t["firma_id"]):
        if any(g["hedef_tur"] == "tedarikci" and g["hedef_id"] == t["tedarikci_id"] for g in x["baglantilar"]):
            t["mevcut_belgeler"].append({"tur": x.get("tur_serbest") or x["tur_kodu"], "no": x.get("belge_no"),
                                         "bitis": x.get("bitis"), "durum": x["durum"], "dogrulama": x.get("dogrulama_durumu")})
    return t


def acildi(db: Veritabani, token: str) -> None:
    """Tedarikçi bağlantıyı açtığında çağrılır (okundu bilgisi)."""
    t = db.bir("SELECT id FROM tedarikci_talepleri WHERE token_ozet = ?", (token_ozeti(token or ""),))
    if not t:
        return
    zaman = simdi()
    db.yaz("UPDATE tedarikci_talepleri SET ilk_acilis = COALESCE(ilk_acilis, ?), son_acilis = ?, "
           "acilis_sayisi = COALESCE(acilis_sayisi, 0) + 1 WHERE id = ?", (zaman, zaman, t["id"]))


def gonderildi(db: Veritabani, firma_id: int, talep_id: int, yontem: str, eposta: Optional[str], kullanici: str) -> None:
    db.yaz("UPDATE tedarikci_talepleri SET gonderim = ?, gonderim_tarihi = ?, gonderilen_eposta = COALESCE(?, gonderilen_eposta) "
           "WHERE id = ? AND firma_id = ?", (yontem, simdi(), eposta, talep_id, firma_id))
    audit.kaydet(db, firma_id, kullanici, "Tedarikçi talebi gönderildi", "talep", talep_id, f"{yontem} {eposta or ''}".strip())


def yeni_baglanti(db: Veritabani, firma_id: int, talep_id: int, uzat_gun: int, kullanici: str) -> str:
    """Hatırlatma: yeni bağlantı üretir (önceki geçersiz olur), gerekirse süreyi uzatır."""
    t = db.bir("SELECT * FROM tedarikci_talepleri WHERE id = ? AND firma_id = ?", (talep_id, firma_id))
    if not t:
        raise ValueError("Talep bulunamadı")
    if t["durum"] == "Kapandı":
        raise ValueError("Kapanmış talep için hatırlatma gönderilemez; yeni talep oluşturun")
    token = token_uret(24)
    yeni_son = max(t["son_tarih"] or _bugun(), (date.today() + timedelta(days=max(1, int(uzat_gun)))).isoformat())
    db.yaz("UPDATE tedarikci_talepleri SET token_ozet = ?, son_tarih = ?, hatirlatma_sayisi = COALESCE(hatirlatma_sayisi, 0) + 1, "
           "son_hatirlatma = ? WHERE id = ? AND firma_id = ?", (token_ozeti(token), yeni_son, simdi(), talep_id, firma_id))
    audit.kaydet(db, firma_id, kullanici, "Tedarikçi talebi için yeni bağlantı / hatırlatma", "talep", talep_id, f"son tarih {yeni_son}")
    return token


def _dolu(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, list):
        return bool(v)
    if isinstance(v, dict):
        return any(_dolu(x) for x in v.values())
    return isinstance(v, str) and v.strip() not in ("", "—")


def yanitla(db: Veritabani, token: str, yanit: dict, dosyalar: list[dict], yanitlayan: str) -> None:
    """
    yanit (yeni biçim): {"urunler": {"<urun_id>": {svhc_beyani, svhc_maddeler, malzemeler, hammadde_mensei,
                          karbon_kg, karbon_yontemi}}, "genel": {...}, "not": "..."}
    Eski biçim (tek ürün alanları üst düzeyde) de kabul edilir.
    dosyalar: [{'tur_kodu','belge_no','duzenleyen','bitis','dosya','dosya_adi','dosya_mime','urun_idler'?}]
    """
    t = token_ile(db, token)
    if not t:
        raise ValueError("Bağlantı geçersiz")
    if t["durum"] == "Kapandı":
        raise ValueError("Bu talep firma tarafından kapatılmış")
    if t["suresi_doldu"]:
        raise ValueError("Bu bağlantının süresi dolmuş; firmadan yeni bağlantı isteyin")
    if not metin(yanitlayan):
        raise ValueError("Adınızı ve ünvanınızı yazın")
    urun_idler = [u["id"] for u in t["urunler"]]
    if "urunler" not in yanit and "genel" not in yanit:
        eski = {k: v for k, v in yanit.items() if k != "not"}
        yanit = {"urunler": {str(urun_idler[0]): eski} if urun_idler else {}, "genel": {} if urun_idler else eski,
                 "not": yanit.get("not")}

    def temizle(v: dict) -> dict:
        v = dict(v or {})
        v["malzemeler"] = [m for m in (v.get("malzemeler") or []) if not bos_mu(m.get("malzeme"))]
        if v.get("svhc_beyani") in ("—", ""):
            v["svhc_beyani"] = None
        return v

    temiz_urun = {str(k): temizle(v) for k, v in (yanit.get("urunler") or {}).items() if int(k) in urun_idler and isinstance(v, dict)}
    genel = temizle(yanit.get("genel") or {})
    for d in dosyalar:
        if d.get("dosya") is not None and len(d["dosya"]) > EN_BUYUK_DOSYA:
            raise ValueError(f"{d.get('dosya_adi')}: dosya 10 MB'tan büyük")
    if not (_dolu(temiz_urun) or _dolu(genel) or dosyalar or metin(yanit.get("not"))):
        raise ValueError("Gönderilecek bilgi veya belge yok")
    onceki = t.get("yanit") or {}
    if t["durum"] == "Yanıtlandı" and not (_dolu(temiz_urun) or _dolu(genel) or dosyalar) and \
            metin(yanit.get("not")) == metin(onceki.get("not")):
        raise ValueError("Bu talep yanıtlanmış; güncellemek için yeni bilgi veya belge ekleyin")
    with db.islem():
        belge_idler = list(onceki.get("belge_idler") or [])
        for d in dosyalar:
            hedef = [i for i in (d.get("urun_idler") or urun_idler) if i in urun_idler]
            baglar = [("tedarikci", t["tedarikci_id"])] + [("urun", i) for i in hedef]
            belge_idler.append(repo.belge_ekle(
                db, t["firma_id"], {k: d.get(k) for k in ("tur_kodu", "tur_serbest", "belge_no", "duzenleyen", "bitis")},
                baglar, f"Tedarikçi: {yanitlayan}", d.get("dosya"), d.get("dosya_adi"), d.get("dosya_mime"),
                kaynak="Tedarikçi portalı"))
        # Önceki yanıtla birleştir: tedarikçinin bu sefer boş bıraktığı alan önceki değeri korur.
        birlesik_urun = {k: dict(v) for k, v in (onceki.get("urunler") or {}).items()}
        for k, v in temiz_urun.items():
            hedef_kayit = birlesik_urun.setdefault(k, {})
            for alan, deger in v.items():
                if _dolu(deger) or alan not in hedef_kayit:
                    hedef_kayit[alan] = deger
        birlesik_genel = dict(onceki.get("genel") or {})
        for alan, deger in genel.items():
            if _dolu(deger) or alan not in birlesik_genel:
                birlesik_genel[alan] = deger
        kayit = {"urunler": birlesik_urun, "genel": birlesik_genel, "not": yanit.get("not") or onceki.get("not"),
                 "yanitlayan": yanitlayan, "belge_idler": belge_idler}
        db.yaz("UPDATE tedarikci_talepleri SET durum = 'Yanıtlandı', yanit_json = ?, yanit_tarihi = ?, revizyon_notu = NULL, "
               "yanit_sayisi = COALESCE(yanit_sayisi, 0) + 1 WHERE id = ?",
               (json.dumps(kayit, ensure_ascii=False), simdi(), t["id"]))
        audit.kaydet(db, t["firma_id"], f"Tedarikçi: {yanitlayan}", "Tedarikçi talebi yanıtlandı", "talep", t["id"],
                     f"{len(dosyalar)} yeni belge, {len(temiz_urun)} ürün")


def revizyon_iste(db: Veritabani, firma_id: int, talep_id: int, not_: str, kullanici: str, uzat_gun: int = 7) -> None:
    if not metin(not_):
        raise ValueError("Tedarikçiye neyin eksik olduğunu yazın")
    t = db.bir("SELECT * FROM tedarikci_talepleri WHERE id = ? AND firma_id = ?", (talep_id, firma_id))
    if not t or t["durum"] == "Kapandı":
        raise ValueError("Talep bulunamadı veya kapalı")
    yeni_son = max(t["son_tarih"] or _bugun(), (date.today() + timedelta(days=max(1, int(uzat_gun)))).isoformat())
    db.yaz("UPDATE tedarikci_talepleri SET durum = 'Revizyon istendi', revizyon_notu = ?, son_tarih = ? WHERE id = ?",
           (not_, yeni_son, talep_id))
    audit.kaydet(db, firma_id, kullanici, "Tedarikçiden revizyon istendi", "talep", talep_id, not_[:200])


def kapat(db: Veritabani, firma_id: int, talep_id: int, kullanici: str):
    db.yaz("UPDATE tedarikci_talepleri SET durum = 'Kapandı' WHERE id = ? AND firma_id = ?", (talep_id, firma_id))
    audit.kaydet(db, firma_id, kullanici, "Tedarikçi talebi kapatıldı", "talep", talep_id)


def yanit_urunleri(t: dict) -> dict[int, dict]:
    y = json.loads(t["yanit_json"]) if t.get("yanit_json") else {}
    if "urunler" not in y and "genel" not in y:   # eski biçim
        alanlar = {k: v for k, v in y.items() if k not in ("not", "yanitlayan", "belge_idler")}
        return {t["urun_id"]: alanlar} if t.get("urun_id") and alanlar else {}
    return {int(k): v for k, v in (y.get("urunler") or {}).items()}


def svhc_sentezi(db: Veritabani, firma_id: int, urun_id: int) -> tuple[Optional[str], Optional[str], str]:
    """Ürünün tedarikçilerinin kabul edilmiş beyanlarından ürün düzeyinde SVHC sonucu üretir.
    (beyan, maddeler, açıklama). Beyan None ise ürün kartı değiştirilmez."""
    tedarikciler = urun_tedarikcileri(db, firma_id, urun_id)
    bey = {b["tedarikci_id"]: b for b in beyanlar(db, firma_id, urun_id) if not bos_mu(b.get("svhc_beyani"))}
    tedarikciler |= set(bey)
    var = [b for b in bey.values() if tr_norm(b["svhc_beyani"]) in ("var", "evet", "yes")]
    if var:
        maddeler = "; ".join(dict.fromkeys(metin(b.get("svhc_maddeler")) for b in var if metin(b.get("svhc_maddeler"))))
        return "Var", maddeler or None, f"{', '.join(b['tedarikci'] for b in var)} SVHC içerdiğini beyan etti"
    yok = {b["tedarikci_id"] for b in bey.values() if tr_norm(b["svhc_beyani"]) in ("yok", "hayir", "no")}
    if tedarikciler and tedarikciler <= yok:
        return "Yok", None, f"ürünün {len(tedarikciler)} tedarikçisinin tamamı 'Yok' beyan etti"
    return None, None, f"{len(tedarikciler)} tedarikçiden {len(yok)} tanesi 'Yok' beyan etti; diğerlerinin beyanı bekleniyor"


def urune_aktar(db: Veritabani, firma_id: int, talep_id: int, kullanici: str, urun_idler: Optional[list[int]] = None) -> list[str]:
    """Yanıtı kabul eder ve ürünlere aktarır. Yapılan işlemlerin listesini döner."""
    t = db.bir("SELECT * FROM tedarikci_talepleri WHERE id = ? AND firma_id = ?", (talep_id, firma_id))
    if not t or not t["yanit_json"]:
        raise ValueError("Aktarılacak yanıt yok")
    yu = yanit_urunleri(t)
    if not yu:
        raise ValueError("Yanıtta ürüne aktarılacak bilgi yok (yalnızca belge veya genel bilgi gönderilmiş)")
    hedef = [u for u in yu if (not urun_idler or u in urun_idler)]
    tid = t["tedarikci_id"]
    yanitlayan = (json.loads(t["yanit_json"]) or {}).get("yanitlayan")
    yapilan = []
    with db.islem():
        for uid in hedef:
            y = yu[uid] or {}
            u = repo.urun(db, firma_id, uid)
            if not u:
                continue
            parca = []
            beyan = {}
            if not bos_mu(y.get("svhc_beyani")) and tr_norm(y.get("svhc_beyani")) not in _BOS_SVHC:
                beyan.update(svhc_beyani=y["svhc_beyani"], svhc_maddeler=metin(y.get("svhc_maddeler")) or None)
            if not bos_mu(y.get("hammadde_mensei")):
                beyan["mense"] = metin(y["hammadde_mensei"])
            if sayi(y.get("karbon_kg")) is not None:
                beyan.update(karbon_kg=sayi(y["karbon_kg"]), karbon_yontemi=metin(y.get("karbon_yontemi")) or None)
            if beyan:
                mevcut = db.bir("SELECT id FROM tedarikci_beyanlari WHERE tedarikci_id = ? AND urun_id = ?", (tid, uid))
                kayit = {**beyan, "talep_id": talep_id, "yanitlayan": yanitlayan, "tarih": t["yanit_tarihi"], "kabul_eden": kullanici}
                if mevcut:
                    db.guncelle("tedarikci_beyanlari", mevcut["id"], kayit)
                else:
                    db.ekle("tedarikci_beyanlari", {"firma_id": firma_id, "tedarikci_id": tid, "urun_id": uid, **kayit})
            guncel = {}
            if "svhc_beyani" in beyan:
                s_beyan, s_madde, aciklama = svhc_sentezi(db, firma_id, uid)
                if s_beyan:
                    guncel.update(svhc_beyani=s_beyan, svhc_maddeler=s_madde)
                parca.append(f"SVHC: {aciklama}")
            malzemeler = [m for m in (y.get("malzemeler") or []) if not bos_mu(m.get("malzeme"))]
            mevcut_m = repo.alt_liste(db, "malzemeler", firma_id, uid)
            if malzemeler:
                # Üründe bu tedarikçiye ait olmayan satır yoksa bildirilen bileşim ürünün bileşimi olur.
                # Varsa firmanın girdiği bileşim asla silinmez; tedarikçinin içeriği tek bir bileşen satırı olarak eklenir.
                digerleri = [m for m in mevcut_m if m.get("tedarikci_id") != tid]
                if digerleri:
                    # Üründe başka malzeme satırları da var: tedarikçinin bildirdiği oranlar kendi malzemesinin
                    # içeriğidir, ürünün toplam bileşimi değildir. Bileşen olarak saklanır; ürün içindeki payını firma belirler.
                    ozet = ", ".join(metin(m["malzeme"]) + (f" %{sayi(m.get('oran')):g}" if sayi(m.get("oran")) is not None else "")
                                     for m in malzemeler)
                    kendi = [m for m in mevcut_m if m.get("tedarikci_id") == tid]
                    eski_ad = metin(kendi[0]["malzeme"]) if kendi else \
                        f"{db.deger('SELECT unvan FROM tedarikciler WHERE id = ?', (tid,))} malzemesi"
                    if eski_ad.endswith(")") and "%" in eski_ad.rsplit(" (", 1)[-1]:
                        eski_ad = eski_ad.rsplit(" (", 1)[0]
                    yeni = [{"malzeme": f"{eski_ad} ({ozet})", "oran": next((m["oran"] for m in kendi if m.get("oran") is not None), None),
                             "mense": metin(malzemeler[0].get("mense")) or beyan.get("mense") or (kendi[0].get("mense") if kendi else None),
                             "geri_donusturulmus": 1 if any(m.get("geri_donusturulmus") for m in malzemeler) else 0,
                             "tedarikci_id": tid}]
                    parca.append("bileşen içeriği (ürün içindeki payı firma tarafından girilmeli)")
                else:
                    yeni = [{"malzeme": metin(m["malzeme"]), "oran": sayi(m.get("oran")),
                             "mense": metin(m.get("mense")) or beyan.get("mense"),
                             "geri_donusturulmus": 1 if m.get("geri_donusturulmus") else 0, "tedarikci_id": tid} for m in malzemeler]
                    parca.append(f"{len(yeni)} malzeme satırı")
                repo.alt_degistir(db, "malzemeler", firma_id, uid, digerleri + yeni, kullanici)
            elif beyan.get("mense"):
                n = db.yaz("UPDATE malzemeler SET mense = ? WHERE urun_id = ? AND tedarikci_id = ? AND (mense IS NULL OR mense = '')",
                           (beyan["mense"], uid, tid))
                n += db.yaz("UPDATE tedarik_asamalari SET ulke = ? WHERE urun_id = ? AND tedarikci_id = ? AND (ulke IS NULL OR ulke = '')",
                            (beyan["mense"], uid, tid))
                if n:
                    parca.append("menşe")
            if beyan.get("mense") and bos_mu(u.get("hammadde_mensei")) and not (urun_tedarikcileri(db, firma_id, uid) - {tid}):
                guncel["hammadde_mensei"] = beyan["mense"]
            if "karbon_kg" in beyan:
                parca.append("karbon beyanı (tedarikçi beyanı olarak saklandı)")
            if guncel:
                repo.urun_kaydet(db, firma_id, guncel, kullanici, uid)
            if parca:
                yapilan.append(f"{u['urun_kodu']}: " + ", ".join(parca))
        db.guncelle("tedarikci_talepleri", talep_id, {"durum": "Kapandı"}, firma_id)
        audit.kaydet(db, firma_id, kullanici, "Tedarikçi yanıtı kabul edildi ve ürüne aktarıldı", "talep", talep_id,
                     " | ".join(yapilan)[:500])
    return yapilan


# ---------------------------------------------------------------------------
# Tedarikçi karnesi
# ---------------------------------------------------------------------------

def karne(db: Veritabani, firma_id: int) -> list[dict]:
    analiz = {a["tedarikci_id"]: a for a in eksik_analizi(db, firma_id)}
    tum = talepler(db, firma_id)
    ted_urun = _tedarikci_urunleri(db, firma_id)
    sonuc = []
    for td in repo.tedarikciler(db, firma_id):
        tl = [t for t in tum if t["tedarikci_id"] == td["id"]]
        yanitli = [t for t in tl if t.get("yanit_tarihi")]
        sureler = []
        for t in yanitli:
            try:
                bas = datetime.fromisoformat(t.get("gonderim_tarihi") or t["olusturma"])
                sureler.append(max(0.0, (datetime.fromisoformat(t["yanit_tarihi"]) - bas).total_seconds() / 86400))
            except (TypeError, ValueError):
                pass
        a = analiz.get(td["id"])
        eksik_kalem = (sum(len(k["eksik"]) for k in a["urunler"]) + len(a["belge_sorunlari"])) if a else 0
        oran = (len(yanitli) / len(tl) * 100) if tl else None
        ort = (sum(sureler) / len(sureler)) if sureler else None
        puan = None
        if tl:
            # Yanıt oranı %50, yanıt hızı %20 (her gün 7 puan düşer), açık eksik azlığı %30 (her kalem 15 puan düşer)
            hiz = max(0.0, 100 - ort * 7) if ort is not None else 0.0
            puan = round(0.5 * (oran or 0) + 0.2 * hiz + 0.3 * max(0, 100 - eksik_kalem * 15))
        sonuc.append({
            "tedarikci_id": td["id"], "unvan": td["unvan"], "ulke": td.get("ulke"), "eposta": td.get("eposta"),
            "urun_sayisi": len(ted_urun.get(td["id"], ())), "talep": len(tl), "yanitlanan": len(yanitli),
            "yanit_orani": oran, "ort_yanit_gun": ort,
            "acik": sum(1 for t in tl if t["gorunen_durum"] in ("Gönderildi", "Görüntülendi", "Revizyon istendi", "Yanıtlandı")),
            "suresi_dolan": sum(1 for t in tl if t["gorunen_durum"] == "Süresi doldu"),
            "eksik_kalem": eksik_kalem, "puan": puan,
            "son_yanit": max((t["yanit_tarihi"] for t in yanitli), default=None),
        })
    sonuc.sort(key=lambda x: (x["puan"] is None, -(x["puan"] or 0), x["unvan"]))
    return sonuc
