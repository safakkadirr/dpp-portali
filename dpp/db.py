"""
Veritabanı katmanı.

SQLite (yerel / deneme) ve PostgreSQL (kalıcı, canlı kullanım) desteklenir.
SQL ifadeleri '?' yer tutucusuyla yazılır; PostgreSQL'de otomatik '%s'e çevrilir.
Tarihler ISO metin (YYYY-MM-DD / YYYY-MM-DDTHH:MM:SS) olarak saklanır.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterable, Optional

SEMA_SURUMU = 1

# {PK} ve {BLOB} yer tutucuları veritabanı türüne göre doldurulur.
SEMA = """
CREATE TABLE IF NOT EXISTS ayarlar (
    anahtar TEXT PRIMARY KEY,
    deger TEXT
);

CREATE TABLE IF NOT EXISTS firmalar (
    id {PK},
    unvan TEXT NOT NULL,
    vergi_no TEXT,
    adres TEXT,
    ulke TEXT DEFAULT 'Türkiye',
    eposta TEXT,
    telefon TEXT,
    web TEXT,
    cozumleyici_alan TEXT,
    plan TEXT DEFAULT 'Standart',
    aktif INTEGER DEFAULT 1,
    olusturma TEXT
);

CREATE TABLE IF NOT EXISTS kullanicilar (
    id {PK},
    firma_id INTEGER REFERENCES firmalar(id),
    eposta TEXT NOT NULL UNIQUE,
    ad_soyad TEXT NOT NULL,
    rol TEXT NOT NULL,
    parola_hash TEXT NOT NULL,
    aktif INTEGER DEFAULT 1,
    basarisiz_giris INTEGER DEFAULT 0,
    kilit_bitis TEXT,
    son_giris TEXT,
    parola_degismeli INTEGER DEFAULT 0,
    olusturma TEXT
);

CREATE TABLE IF NOT EXISTS tesisler (
    id {PK},
    firma_id INTEGER NOT NULL REFERENCES firmalar(id),
    ad TEXT NOT NULL,
    adres TEXT,
    ulke TEXT,
    gln TEXT,
    tur TEXT DEFAULT 'Üretim',
    notlar TEXT,
    UNIQUE (firma_id, ad)
);

CREATE TABLE IF NOT EXISTS tedarikciler (
    id {PK},
    firma_id INTEGER NOT NULL REFERENCES firmalar(id),
    unvan TEXT NOT NULL,
    ulke TEXT,
    eposta TEXT,
    yetkili TEXT,
    kimlik_no TEXT,
    notlar TEXT,
    UNIQUE (firma_id, unvan)
);

CREATE TABLE IF NOT EXISTS urunler (
    id {PK},
    firma_id INTEGER NOT NULL REFERENCES firmalar(id),
    urun_kodu TEXT NOT NULL,
    ad TEXT NOT NULL,
    sektor_kodu TEXT NOT NULL DEFAULT 'diger',
    tuketici_urunu INTEGER,
    marka TEXT,
    gtin TEXT,
    gtip TEXT,
    tesis_id INTEGER REFERENCES tesisler(id),
    ab_sorumlu_operator TEXT,
    uretim_ulkesi TEXT,
    hammadde_mensei TEXT,
    geri_donusturulmus_yuzde REAL,
    svhc_beyani TEXT,
    svhc_maddeler TEXT,
    cevresel_iddia TEXT,
    karbon_kg REAL,
    karbon_yontemi TEXT,
    gomulu_emisyon REAL,
    eprel_no TEXT,
    imds_id TEXT,
    batarya_kategori TEXT,
    batarya_kimya TEXT,
    batarya_kwh REAL,
    bakim_onarim TEXT,
    omur_sonu TEXT,
    notlar TEXT,
    aktif INTEGER DEFAULT 1,
    olusturma TEXT,
    guncelleme TEXT,
    guncelleyen TEXT,
    UNIQUE (firma_id, urun_kodu)
);

CREATE TABLE IF NOT EXISTS partiler (
    id {PK},
    firma_id INTEGER NOT NULL REFERENCES firmalar(id),
    urun_id INTEGER NOT NULL REFERENCES urunler(id) ON DELETE CASCADE,
    parti_no TEXT NOT NULL,
    uretim_tarihi TEXT,
    miktar REAL,
    tesis_id INTEGER REFERENCES tesisler(id),
    notlar TEXT,
    UNIQUE (urun_id, parti_no)
);

CREATE TABLE IF NOT EXISTS malzemeler (
    id {PK},
    firma_id INTEGER NOT NULL REFERENCES firmalar(id),
    urun_id INTEGER NOT NULL REFERENCES urunler(id) ON DELETE CASCADE,
    malzeme TEXT NOT NULL,
    oran REAL,
    mense TEXT,
    geri_donusturulmus INTEGER DEFAULT 0,
    tedarikci_id INTEGER REFERENCES tedarikciler(id)
);

CREATE TABLE IF NOT EXISTS tedarik_asamalari (
    id {PK},
    firma_id INTEGER NOT NULL REFERENCES firmalar(id),
    urun_id INTEGER NOT NULL REFERENCES urunler(id) ON DELETE CASCADE,
    sira INTEGER,
    asama TEXT NOT NULL,
    tedarikci_id INTEGER REFERENCES tedarikciler(id),
    ulke TEXT,
    belge_no TEXT
);

CREATE TABLE IF NOT EXISTS belgeler (
    id {PK},
    firma_id INTEGER NOT NULL REFERENCES firmalar(id),
    tur_kodu TEXT NOT NULL,
    tur_serbest TEXT,
    belge_no TEXT,
    duzenleyen TEXT,
    baslangic TEXT,
    bitis TEXT,
    kapsam TEXT,
    dosya_adi TEXT,
    dosya_mime TEXT,
    dosya {BLOB},
    dosya_boyut INTEGER,
    dosya_ozet TEXT,
    dogrulama_durumu TEXT DEFAULT 'Beklemede',
    dogrulayan TEXT,
    dogrulama_tarihi TEXT,
    dogrulama_notu TEXT,
    kaynak TEXT,
    yukleyen TEXT,
    olusturma TEXT
);

CREATE TABLE IF NOT EXISTS belge_baglantilari (
    id {PK},
    firma_id INTEGER NOT NULL REFERENCES firmalar(id),
    belge_id INTEGER NOT NULL REFERENCES belgeler(id) ON DELETE CASCADE,
    hedef_tur TEXT NOT NULL,
    hedef_id INTEGER,
    UNIQUE (belge_id, hedef_tur, hedef_id)
);

CREATE TABLE IF NOT EXISTS kural_ayarlari (
    kural_kodu TEXT PRIMARY KEY,
    aktif INTEGER DEFAULT 1,
    agirlik INTEGER,
    guncelleyen TEXT,
    guncelleme TEXT
);

CREATE TABLE IF NOT EXISTS degerlendirmeler (
    id {PK},
    firma_id INTEGER NOT NULL REFERENCES firmalar(id),
    urun_id INTEGER NOT NULL REFERENCES urunler(id) ON DELETE CASCADE,
    kural_seti TEXT,
    tarih TEXT,
    yasal_durum TEXT,
    yasal_eksik INTEGER,
    kritik_eksik INTEGER,
    hazirlik_skoru REAL,
    genel_durum TEXT,
    uygulanan INTEGER,
    calistiran TEXT,
    son INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS bulgular (
    id {PK},
    degerlendirme_id INTEGER NOT NULL REFERENCES degerlendirmeler(id) ON DELETE CASCADE,
    kural_kodu TEXT,
    sinif TEXT,
    seviye TEXT,
    agirlik INTEGER,
    sonuc TEXT,
    detay TEXT
);

CREATE TABLE IF NOT EXISTS dogrulamalar (
    id {PK},
    firma_id INTEGER NOT NULL REFERENCES firmalar(id),
    urun_id INTEGER NOT NULL REFERENCES urunler(id) ON DELETE CASCADE,
    degerlendirme_id INTEGER,
    dogrulayan TEXT,
    unvan TEXT,
    tarih TEXT,
    sonuc TEXT,
    kapsam TEXT,
    aciklama TEXT,
    veri_ozeti TEXT
);

CREATE TABLE IF NOT EXISTS pasaportlar (
    id {PK},
    firma_id INTEGER NOT NULL REFERENCES firmalar(id),
    urun_id INTEGER NOT NULL REFERENCES urunler(id) ON DELETE CASCADE,
    parti_id INTEGER REFERENCES partiler(id),
    surum INTEGER NOT NULL,
    durum TEXT NOT NULL,
    genel_kimlik TEXT NOT NULL,
    alici_kodu TEXT,
    icerik_json TEXT NOT NULL,
    icerik_ozeti TEXT NOT NULL,
    kural_seti TEXT,
    hazirlik_skoru REAL,
    yasal_durum TEXT,
    yayimlayan TEXT,
    yayim_tarihi TEXT,
    geri_cekme_tarihi TEXT,
    geri_cekme_nedeni TEXT
);

CREATE TABLE IF NOT EXISTS tedarikci_talepleri (
    id {PK},
    firma_id INTEGER NOT NULL REFERENCES firmalar(id),
    tedarikci_id INTEGER NOT NULL REFERENCES tedarikciler(id),
    urun_id INTEGER REFERENCES urunler(id) ON DELETE SET NULL,
    token_ozet TEXT NOT NULL UNIQUE,
    istenenler TEXT,
    mesaj TEXT,
    durum TEXT DEFAULT 'Açık',
    son_tarih TEXT,
    yanit_json TEXT,
    yanit_tarihi TEXT,
    olusturan TEXT,
    olusturma TEXT,
    urun_idler TEXT,
    dil TEXT,
    kaynak TEXT,
    gonderilen_eposta TEXT,
    gonderim TEXT,
    gonderim_tarihi TEXT,
    ilk_acilis TEXT,
    son_acilis TEXT,
    acilis_sayisi INTEGER DEFAULT 0,
    hatirlatma_sayisi INTEGER DEFAULT 0,
    son_hatirlatma TEXT,
    revizyon_notu TEXT,
    yanit_sayisi INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tedarikci_beyanlari (
    id {PK},
    firma_id INTEGER NOT NULL REFERENCES firmalar(id),
    talep_id INTEGER,
    tedarikci_id INTEGER NOT NULL REFERENCES tedarikciler(id),
    urun_id INTEGER NOT NULL REFERENCES urunler(id) ON DELETE CASCADE,
    svhc_beyani TEXT,
    svhc_maddeler TEXT,
    mense TEXT,
    karbon_kg REAL,
    karbon_yontemi TEXT,
    yanitlayan TEXT,
    tarih TEXT,
    kabul_eden TEXT,
    UNIQUE (tedarikci_id, urun_id)
);

CREATE TABLE IF NOT EXISTS denetim_izi (
    id {PK},
    firma_id INTEGER,
    kullanici TEXT,
    zaman TEXT NOT NULL,
    islem TEXT NOT NULL,
    varlik TEXT,
    varlik_id TEXT,
    detay TEXT,
    onceki_ozet TEXT,
    ozet TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_urunler_firma ON urunler(firma_id);
CREATE INDEX IF NOT EXISTS ix_malzemeler_urun ON malzemeler(urun_id);
CREATE INDEX IF NOT EXISTS ix_asama_urun ON tedarik_asamalari(urun_id);
CREATE INDEX IF NOT EXISTS ix_belge_firma ON belgeler(firma_id);
CREATE INDEX IF NOT EXISTS ix_bag_belge ON belge_baglantilari(belge_id);
CREATE INDEX IF NOT EXISTS ix_bag_hedef ON belge_baglantilari(hedef_tur, hedef_id);
CREATE INDEX IF NOT EXISTS ix_deg_urun ON degerlendirmeler(urun_id, son);
CREATE INDEX IF NOT EXISTS ix_bulgu_deg ON bulgular(degerlendirme_id);
CREATE INDEX IF NOT EXISTS ix_pas_urun ON pasaportlar(urun_id);
CREATE INDEX IF NOT EXISTS ix_pas_genel ON pasaportlar(genel_kimlik);
CREATE INDEX IF NOT EXISTS ix_iz_firma ON denetim_izi(firma_id);
CREATE INDEX IF NOT EXISTS ix_talep_firma ON tedarikci_talepleri(firma_id);
CREATE INDEX IF NOT EXISTS ix_beyan_urun ON tedarikci_beyanlari(urun_id)
"""


# Sonradan eklenen sütunlar: mevcut kurulumlarda sema_olustur() bunları ekler.
EK_KOLONLAR = {
    "tedarikci_talepleri": [
        ("urun_idler", "TEXT"), ("dil", "TEXT"), ("kaynak", "TEXT"), ("gonderilen_eposta", "TEXT"), ("gonderim", "TEXT"),
        ("gonderim_tarihi", "TEXT"), ("ilk_acilis", "TEXT"), ("son_acilis", "TEXT"), ("acilis_sayisi", "INTEGER DEFAULT 0"),
        ("hatirlatma_sayisi", "INTEGER DEFAULT 0"), ("son_hatirlatma", "TEXT"), ("revizyon_notu", "TEXT"),
        ("yanit_sayisi", "INTEGER DEFAULT 0"),
    ],
}


def simdi() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Veritabani:
    """İnce bir DB-API sarmalayıcısı. Tek bağlantı + kilit; Streamlit'te st.cache_resource ile paylaşılır."""

    def __init__(self, adres: str):
        self.adres = adres
        self.postgres = adres.startswith(("postgres://", "postgresql://"))
        self._kilit = threading.RLock()
        self._baglanti = None
        self._baglan()

    # -- bağlantı ---------------------------------------------------------
    def _baglan(self):
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row
            adres = self.adres.replace("postgres://", "postgresql://", 1)
            self._baglanti = psycopg.connect(adres, row_factory=dict_row, autocommit=False)
        else:
            yol = self.adres.replace("sqlite:///", "", 1)
            if yol != ":memory:":
                os.makedirs(os.path.dirname(os.path.abspath(yol)), exist_ok=True)
            self._baglanti = sqlite3.connect(yol, check_same_thread=False, isolation_level=None)
            self._baglanti.row_factory = sqlite3.Row
            self._baglanti.execute("PRAGMA foreign_keys = ON")
            self._baglanti.execute("PRAGMA journal_mode = WAL") if yol != ":memory:" else None

    @property
    def kalici(self) -> bool:
        return self.postgres

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.postgres else sql

    def _satir(self, r) -> dict:
        if r is None:
            return None
        return dict(r)

    # -- işlem yönetimi -----------------------------------------------------
    @contextmanager
    def islem(self):
        """Toplu yazma için işlem bloğu. Hata olursa geri alınır."""
        with self._kilit:
            self._ic_islem = getattr(self, "_ic_islem", 0) + 1
            ilk = self._ic_islem == 1
            try:
                if ilk and not self.postgres:
                    self._baglanti.execute("BEGIN")
                yield self
                if ilk:
                    self._baglanti.commit() if self.postgres else self._baglanti.execute("COMMIT")
            except Exception:
                if ilk:
                    try:
                        self._baglanti.rollback() if self.postgres else self._baglanti.execute("ROLLBACK")
                    except Exception:
                        pass
                raise
            finally:
                self._ic_islem -= 1

    @contextmanager
    def kurtarma_noktasi(self):
        """İşlem içinde tek bir satırın hatasını izole eder: hata olursa yalnızca o satırın değişiklikleri geri alınır."""
        with self._kilit:
            self._sp = getattr(self, "_sp", 0) + 1
            ad = f"sp_{self._sp}"
            self._calistir(f"SAVEPOINT {ad}")
            try:
                yield self
                self._calistir(f"RELEASE SAVEPOINT {ad}")
            except Exception:
                self._calistir(f"ROLLBACK TO SAVEPOINT {ad}")
                self._calistir(f"RELEASE SAVEPOINT {ad}")
                raise

    def _calistir(self, sql: str, parametreler: Iterable[Any] = ()):
        sql = self._sql(sql)
        parametreler = tuple(parametreler)
        with self._kilit:
            try:
                if self.postgres:
                    imlec = self._baglanti.cursor()
                    imlec.execute(sql, parametreler)
                else:
                    imlec = self._baglanti.execute(sql, parametreler)
                if self.postgres and getattr(self, "_ic_islem", 0) == 0:
                    self._baglanti.commit()
                return imlec
            except Exception as hata:
                if self.postgres and getattr(self, "_ic_islem", 0) == 0:
                    try:
                        self._baglanti.rollback()
                    except Exception:
                        pass
                    if "closed" in str(hata).lower() or "connection" in str(hata).lower():
                        self._baglan()
                raise

    def tumu(self, sql: str, parametreler: Iterable[Any] = ()) -> list[dict]:
        with self._kilit:
            return [self._satir(r) for r in self._calistir(sql, parametreler).fetchall()]

    def bir(self, sql: str, parametreler: Iterable[Any] = ()) -> Optional[dict]:
        with self._kilit:
            return self._satir(self._calistir(sql, parametreler).fetchone())

    def deger(self, sql: str, parametreler: Iterable[Any] = ()):
        r = self.bir(sql, parametreler)
        return None if r is None else next(iter(r.values()))

    def yaz(self, sql: str, parametreler: Iterable[Any] = ()) -> int:
        with self._kilit:
            return self._calistir(sql, parametreler).rowcount

    def ekle(self, tablo: str, veri: dict) -> int:
        kolonlar = [guvenli_kolon(k) for k in veri]
        guvenli_kolon(tablo)
        sql = (f"INSERT INTO {tablo} ({', '.join(kolonlar)}) VALUES ({', '.join('?' for _ in kolonlar)}) RETURNING id")
        with self._kilit:
            r = self._calistir(sql, [veri[k] for k in kolonlar]).fetchone()
            return int(dict(r)["id"])

    def guncelle(self, tablo: str, kimlik: int, veri: dict, firma_id: Optional[int] = None) -> int:
        if not veri:
            return 0
        guvenli_kolon(tablo)
        atama = ", ".join(f"{guvenli_kolon(k)} = ?" for k in veri)
        sql = f"UPDATE {tablo} SET {atama} WHERE id = ?"
        parametre = list(veri.values()) + [kimlik]
        if firma_id is not None:
            sql += " AND firma_id = ?"
            parametre.append(firma_id)
        return self.yaz(sql, parametre)

    # -- şema -------------------------------------------------------------
    def sema_olustur(self):
        pk = "BIGSERIAL PRIMARY KEY" if self.postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
        blob = "BYTEA" if self.postgres else "BLOB"
        ddl = SEMA.replace("{PK}", pk).replace("{BLOB}", blob)
        with self.islem():
            for ifade in [s.strip() for s in ddl.split(";") if s.strip()]:
                self._calistir(ifade)
            self._kolonlari_tamamla()
            mevcut = self.deger("SELECT deger FROM ayarlar WHERE anahtar = 'sema_surumu'")
            if mevcut is None:
                self._calistir("INSERT INTO ayarlar (anahtar, deger) VALUES (?, ?)", ("sema_surumu", str(SEMA_SURUMU)))

    def _kolonlari_tamamla(self):
        """Eski sürümle oluşturulmuş tablolara sonradan eklenen sütunları ekler (veri kaybı olmadan)."""
        for tablo, kolonlar in EK_KOLONLAR.items():
            if self.postgres:
                for ad, tur in kolonlar:
                    self._calistir(f"ALTER TABLE {tablo} ADD COLUMN IF NOT EXISTS {ad} {tur}")
            else:
                mevcut = {r[1] for r in self._calistir(f"PRAGMA table_info({tablo})").fetchall()}
                for ad, tur in kolonlar:
                    if ad not in mevcut:
                        self._calistir(f"ALTER TABLE {tablo} ADD COLUMN {ad} {tur}")

    def ayar_al(self, anahtar: str, varsayilan=None):
        d = self.deger("SELECT deger FROM ayarlar WHERE anahtar = ?", (anahtar,))
        return varsayilan if d is None else d

    def ayar_yaz(self, anahtar: str, deger: str):
        self.yaz("INSERT INTO ayarlar (anahtar, deger) VALUES (?, ?) "
                 "ON CONFLICT (anahtar) DO UPDATE SET deger = excluded.deger", (anahtar, deger))


_GECERLI_AD = re.compile(r"^[a-z_][a-z0-9_]*$")


def guvenli_kolon(ad: str) -> str:
    """Dinamik SQL'de kullanılan sütun adlarının güvenli olduğunu doğrular."""
    if not _GECERLI_AD.match(ad):
        raise ValueError(f"Geçersiz alan adı: {ad}")
    return ad
