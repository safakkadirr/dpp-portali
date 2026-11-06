"""Uyum asistanı: yerel (veri dışarı gitmez) ve isteğe bağlı Gemini modu."""

from __future__ import annotations

from collections import Counter

from .catalog import SEKTOR, SEKTOR_ADLARI
from .regulations import MEVZUAT
from .rules import DURUM_KRITIK, KURAL, KURALLAR, Baglam, yaklasan_yukumlulukler
from .util import tr_norm


def yerel_yanit(soru: str, urunler: list[dict], bulgular: list[dict], belgeler: list[dict]) -> str:
    s = tr_norm(soru)
    if not urunler:
        return "Henüz ürün yok. Ürünler ekranından ürün ekleyin veya Excel ile toplu aktarın."

    for u in urunler:
        if tr_norm(u["urun_kodu"]) and tr_norm(u["urun_kodu"]) in s:
            return urun_recetesi(u, [b for b in bulgular if b["urun_id"] == u["id"]])

    if any(k in s for k in ("merhaba", "selam", "yardim", "ne sorabilirim", "neler yapabilirsin")):
        return ("Şunları sorabilirsiniz:\n\n- *Hangi ürünlerde kritik eksik var?*\n- *Süresi dolan belgeler hangileri?*\n"
                "- *En sık eksik ne?*\n- *Yaklaşan yükümlülükler neler?*\n- *Batarya / tekstil / elektronik için ne gerekiyor?*\n"
                "- Bir ürün kodu yazın (ör. *TK-1001*), o ürünün çözüm adımlarını vereyim.")

    if any(k in s for k in ("yaklasan", "takvim", "ne zaman", "tarih", "zorunlu olacak")):
        yk = yaklasan_yukumlulukler()
        satirlar = [f"- **{k.zorunlu_tarih:%d.%m.%Y}** — {k.ad} ({k.kapsam}) · {k.dayanak}" for k in yk]
        ek = "\n".join(f"- **{m['Mevzuat']}** — {m['Durum']}" for m in MEVZUAT[:8])
        return ("Önümüzdeki 12 ay içinde zorunlu hale gelen ve programın izlediği yükümlülükler:\n\n"
                + ("\n".join(satirlar) or "- Yok") + "\n\nGenel takvim (gösterge niteliğinde):\n\n" + ek)

    if any(k in s for k in ("belge", "sertifika", "sure", "dolan", "yenile")):
        riskli = [b for b in belgeler if b["durum"] in ("Süresi dolmuş", "30 gün içinde doluyor", "60 gün içinde doluyor")]
        bekleyen = [b for b in belgeler if b.get("dogrulama_durumu") == "Beklemede"]
        if not riskli:
            metin = f"{len(belgeler)} belgenin hiçbirinin süresi 60 gün içinde dolmuyor."
        else:
            metin = f"Dikkat gerektiren {len(riskli)} belge var:\n\n" + "\n".join(
                f"- {b.get('tur_serbest') or b['tur_kodu']} {b.get('belge_no') or ''}: **{b['durum']}** ({b.get('bitis')})" for b in riskli[:15])
        return metin + (f"\n\nAyrıca {len(bekleyen)} belge bağımsız doğrulama bekliyor." if bekleyen else "")

    if any(k in s for k in ("en sik", "en cok", "genel", "ozet", "durum")):
        eksik = [b for b in bulgular if b["sonuc"] == "Eksik"]
        sayim = Counter(b["kural_kodu"] for b in eksik).most_common(6)
        dagilim = Counter(u.get("genel_durum") or "Değerlendirilmedi" for u in urunler)
        return (f"{len(urunler)} ürün: " + ", ".join(f"{k}: {v}" for k, v in dagilim.items())
                + "\n\nEn sık eksikler:\n\n" + "\n".join(f"- **{KURAL[k].ad}** ({KURAL[k].sinif}, {KURAL[k].seviye}) — {n} ürün"
                                                         for k, n in sayim))

    if any(k in s for k in ("kritik", "risk", "hata", "sorun", "hangi", "eksik")):
        riskli = sorted([u for u in urunler if u.get("genel_durum") == DURUM_KRITIK], key=lambda u: u.get("hazirlik_skoru") or 0)
        if not riskli:
            return "Kritik yasal eksiği olan ürün yok. Diğer eksikler için Eksikler ve Çözüm ekranına bakabilirsiniz."
        return (f"{len(riskli)} üründe kritik yasal eksik var:\n\n"
                + "\n".join(f"- **{u['urun_kodu']}** {u['ad']} — {u.get('kritik_eksik')} kritik eksik" for u in riskli[:12])
                + "\n\nÇözüm adımları için ürün kodunu yazın.")

    for sek in SEKTOR.values():
        if sek.kod != "diger" and (any(a in s for a in sek.anahtarlar) or tr_norm(sek.ad).split()[0] in s):
            ornek = Baglam(urun={"batarya_kategori": "EV", "ad": "ahsap" if sek.kod == "mobilya" else ""}, sektor=sek, tuketici=True,
                           malzemeler=[{"malzeme": "ahşap"}] if sek.kod == "mobilya" else [])
            ozel = []
            for k in KURALLAR:
                try:
                    if k.kapsam not in ("Tüm sektörler", "Tüketici ürünleri", "Tekstil dışındaki sektörler") and k.uygulanir(ornek):
                        ozel.append(k)
                except Exception:
                    pass
            satir = "\n".join(f"- **{k.ad}** ({k.sinif}, {k.seviye}) — {k.dayanak}" for k in ozel) or "- Genel kurallar uygulanıyor."
            return f"**{sek.ad}** için sektöre özel kontroller:\n\n{satir}\n\nBunlara ek olarak tüm sektörlere uygulanan genel kurallar da çalışır."

    return ("Sorunuzu tam eşleştiremedim. Örneğin *'kritik eksik hangi ürünlerde'*, *'süresi dolan belgeler'*, "
            "*'yaklaşan yükümlülükler'* yazabilir ya da bir ürün kodu girebilirsiniz.")


def urun_recetesi(u: dict, bulgular: list[dict]) -> str:
    eksik = [b for b in bulgular if b["sonuc"] == "Eksik"]
    bas = f"**{u['urun_kodu']} — {u['ad']}** · {u.get('genel_durum') or '—'} · hazırlık %{(u.get('hazirlik_skoru') or 0):.0f}\n"
    if not eksik:
        return bas + "\nEksik bulunmadı."
    parcalar = [bas]
    for i, b in enumerate(eksik, 1):
        k = KURAL.get(b["kural_kodu"])
        if not k:
            continue
        adimlar = "\n".join(f"    - {a}" for a in k.recete)
        parcalar.append(f"{i}. **{k.ad}** ({b['sinif']}, {k.seviye}) — {b['detay']}\n{adimlar}")
    return "\n".join(parcalar)


def yz_baglami(urunler: list[dict], bulgular: list[dict], maskele: bool) -> str:
    """Dış yapay zekâya gönderilecek ÖZET bağlam (ham veri ve belge gönderilmez)."""
    harita = {u["id"]: (f"URUN-{i + 1:03d}" if maskele else f"{u['urun_kodu']} {u['ad']}") for i, u in enumerate(urunler)}
    satirlar = [f"Toplam ürün: {len(urunler)}. Durum: {dict(Counter(u.get('genel_durum') for u in urunler))}."]
    for u in sorted(urunler, key=lambda x: x.get("hazirlik_skoru") or 0)[:25]:
        e = [b for b in bulgular if b["urun_id"] == u["id"] and b["sonuc"] == "Eksik"]
        satirlar.append(f"- {harita[u['id']]} [{SEKTOR_ADLARI.get(u['sektor_kodu'])}] {u.get('genel_durum')}, hazırlık "
                        f"%{(u.get('hazirlik_skoru') or 0):.0f}; eksikler: " + "; ".join(f"{b['kural_kodu']} {b['kural']}: {b['detay']}" for b in e))
    return "\n".join(satirlar)


YZ_TALIMAT = ("Sen Türk ihracatçılara AB ürün mevzuatı (ESPR, Dijital Ürün Pasaportu, REACH, GPSR, CBAM, Batarya Tüzüğü, "
              "RoHS/WEEE, EUDR) konusunda yardımcı olan bir uyum asistanısın. Türkçe, kısa ve somut yanıt ver. Yalnızca verilen "
              "veri özetine ve genel mevzuat bilgisine dayan. Gümrük onayı, kesin uyum veya hukuki görüş verme; emin olmadığın "
              "tarih ve hükümlerde resmi kaynağın (EUR-Lex, Ticaret Bakanlığı) teyit edilmesini söyle.")


def yz_yanit(soru: str, baglam: str, anahtar: str, model: str) -> str:
    from google import genai
    istemci = genai.Client(api_key=anahtar)
    cevap = istemci.models.generate_content(model=model, contents=f"{YZ_TALIMAT}\n\nVERİ ÖZETİ:\n{baglam}\n\nSORU: {soru}")
    return cevap.text


TALEP_TALIMAT = ("Aşağıdaki tedarikçi bilgi talebi e-postasını daha akıcı, kibar ve kurumsal bir dille yeniden yaz. "
                 "KURALLAR: Bağlantıyı (URL), tarihleri, ürün kodlarını ve 'REACH' / 'ESPR' ile başlayan hukuki dayanak "
                 "paragraflarını AYNEN koru. Yeni bir kanun, madde, yaptırım veya tehdit ifadesi EKLEME. Metni ihtarname gibi "
                 "değil, iş birliği isteyen bir talep olarak yaz. Metnin dilini değiştirme. Yalnızca e-posta gövdesini döndür.")


def talep_metni_duzenle(govde: str, anahtar: str, model: str) -> str:
    """Talep e-postasını yapay zekâ ile düzenler; bağlantı veya dayanak kaybolursa orijinali döner."""
    import re
    from google import genai
    istemci = genai.Client(api_key=anahtar)
    yeni = (istemci.models.generate_content(model=model, contents=f"{TALEP_TALIMAT}\n\n---\n{govde}").text or "").strip()
    korunacak = re.findall(r"https?://\S+", govde) + [p for p in govde.split("\n\n") if p.startswith(("REACH", "Under Article", "Talep edilen bilgiler", "The requested information"))]
    if not yeni or any(k not in yeni for k in korunacak):
        raise ValueError("Yapay zekâ bağlantıyı veya hukuki dayanak paragrafını değiştirdi; orijinal metin korundu.")
    return yeni
