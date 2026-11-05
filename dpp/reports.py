"""Raporlar: Excel ön kontrol raporu, PDF hazırlık raporu, PDF pasaport sayfası, QR kod."""

from __future__ import annotations

import io
import json
import os
from collections import Counter
from datetime import date, datetime
from typing import Optional

import pandas as pd

from . import SURUM, evaluation, repo
from .catalog import BELGE, SEKTOR_ADLARI
from .rules import DURUMLAR, KURAL, KURALLAR, MEVZUAT_GOZDEN_GECIRME, yaklasan_yukumlulukler

_FONT_DIZIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
UYARI = ("Bu rapor bir hazırlık ve ön kontrol çalışmasıdır. Gümrük, piyasa gözetimi veya onaylanmış kuruluş kararı yerine "
         "geçmez. Belgelerin içeriği bu raporda yalnızca türü, geçerlilik tarihi ve doğrulama durumu açısından ele alınmıştır. "
         "Mevzuat hükümleri ve tarihleri resmi kaynaklardan teyit edilmelidir.")

ROMA = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]


# ---------------------------------------------------------------------------
# QR
# ---------------------------------------------------------------------------

def qr_png(veri: str) -> Optional[bytes]:
    try:
        import qrcode
    except ImportError:
        return None
    img = qrcode.make(veri, box_size=8, border=2)
    t = io.BytesIO()
    img.save(t, format="PNG")
    return t.getvalue()


def qr_svg(veri: str, boyut: int = 180) -> str:
    from reportlab.graphics import renderSVG
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    w = QrCodeWidget(veri)
    x1, y1, x2, y2 = w.getBounds()
    d = Drawing(boyut, boyut, transform=[boyut / (x2 - x1), 0, 0, boyut / (y2 - y1), 0, 0])
    d.add(w)
    return renderSVG.drawToString(d)


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------

def _yaz(y, df, ad):
    from openpyxl.styles import Font, PatternFill
    df.to_excel(y, index=False, sheet_name=ad[:31])
    ws = y.sheets[ad[:31]]
    for i, k in enumerate(df.columns, 1):
        h = ws.cell(row=1, column=i)
        h.font = Font(bold=True, color="FFFFFF")
        h.fill = PatternFill("solid", fgColor="1F3A5F")
        uz = max([len(str(k))] + [len(str(v)) for v in df[k].head(200).tolist()])
        ws.column_dimensions[h.column_letter].width = min(max(10, uz + 2), 70)
    ws.freeze_panes = "A2"


def excel_rapor(db, firma_id: int, hazirlayan: str) -> bytes:
    f = repo.firma(db, firma_id)
    urunler = repo.urunler(db, firma_id)
    bulgular = evaluation.firma_bulgulari(db, firma_id)
    belgeler = repo.belgeler(db, firma_id)
    c = io.BytesIO()
    with pd.ExcelWriter(c, engine="openpyxl") as y:
        _yaz(y, pd.DataFrame([
            {"Alan": "Rapor", "Değer": "DPP Hazırlık ve Ön Kontrol Raporu"}, {"Alan": "Firma", "Değer": f["unvan"]},
            {"Alan": "Hazırlayan", "Değer": hazirlayan}, {"Alan": "Tarih", "Değer": datetime.now().strftime("%d.%m.%Y %H:%M")},
            {"Alan": "Program sürümü", "Değer": SURUM}, {"Alan": "Mevzuat gözden geçirme", "Değer": MEVZUAT_GOZDEN_GECIRME},
            {"Alan": "Not", "Değer": UYARI}]), "Bilgi")
        _yaz(y, pd.DataFrame([{"Ürün kodu": u["urun_kodu"], "Ürün adı": u["ad"], "Sektör": SEKTOR_ADLARI.get(u["sektor_kodu"]),
                               "Genel durum": u["genel_durum"], "Yasal uyum": u["yasal_durum"], "Yasal eksik": u["yasal_eksik"],
                               "Kritik eksik": u["kritik_eksik"], "DPP hazırlık (%)": u["hazirlik_skoru"],
                               "Yayındaki pasaport sürümü": u["yayindaki_surum"], "Kural seti": u["kural_seti"],
                               "Değerlendirme": u["degerlendirme_tarihi"]} for u in urunler]), "Ozet")
        eksik = [b for b in bulgular if b["sonuc"] == "Eksik"]
        _yaz(y, pd.DataFrame([{"Ürün kodu": b["urun_kodu"], "Kural": f"{b['kural_kodu']} {b['kural']}", "Sınıf": b["sinif"],
                               "Seviye": b["seviye"], "Tespit": b["detay"], "Dayanak": b["dayanak"],
                               "Yapılacaklar": " | ".join(b["recete"])} for b in eksik]), "Eksikler_ve_Cozum")
        _yaz(y, pd.DataFrame([{"Ürün kodu": b["urun_kodu"], "Kural": f"{b['kural_kodu']} {b['kural']}", "Sınıf": b["sinif"],
                               "Seviye": b["seviye"], "Ağırlık": b["agirlik"], "Sonuç": b["sonuc"], "Detay": b["detay"]}
                              for b in bulgular]), "Tum_Kontroller")
        _yaz(y, pd.DataFrame([{"Belge": BELGE.get(b["tur_kodu"], BELGE["DIGER"]).ad if b["tur_kodu"] != "DIGER" else b["tur_serbest"],
                               "No": b["belge_no"], "Düzenleyen": b["duzenleyen"], "Bitiş": b["bitis"], "Durum": b["durum"],
                               "Doğrulama": b["dogrulama_durumu"], "Bağlı olduğu": ", ".join(x["hedef_adi"] or "" for x in b["baglantilar"]),
                               "Dosya SHA-256": b["dosya_ozet"]} for b in belgeler]), "Belgeler")
        _yaz(y, pd.DataFrame([{"Kod": k.kod, "Kural": k.ad, "Sınıf": k.sinif, "Seviye": k.seviye, "Ağırlık": k.agirlik,
                               "Zorunlu tarih": k.zorunlu_tarih, "Kapsam": k.kapsam, "Dayanak": k.dayanak} for k in KURALLAR]), "Kural_Seti")
    return c.getvalue()


# ---------------------------------------------------------------------------
# PDF altyapısı
# ---------------------------------------------------------------------------

_FONT_KAYITLI = False


def _fontlar():
    global _FONT_KAYITLI
    if _FONT_KAYITLI:
        return "DejaVu", "DejaVu-Bold"
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    try:
        pdfmetrics.registerFont(TTFont("DejaVu", os.path.join(_FONT_DIZIN, "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", os.path.join(_FONT_DIZIN, "DejaVuSans-Bold.ttf")))
        from reportlab.lib.fonts import addMapping
        addMapping("DejaVu", 0, 0, "DejaVu")
        addMapping("DejaVu", 1, 0, "DejaVu-Bold")
        _FONT_KAYITLI = True
        return "DejaVu", "DejaVu-Bold"
    except Exception:
        return "Helvetica", "Helvetica-Bold"


LACIVERT = "#1F3A5F"
DURUM_RENK = {"Kritik eksik": "#B42318", "Yasal eksik": "#C4320A", "Hazırlık sürüyor": "#B54708", "Hazır": "#067647"}


def _stiller():
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors
    f, fb = _fontlar()
    return {
        "govde": ParagraphStyle("g", fontName=f, fontSize=9.5, leading=13.5),
        "kucuk": ParagraphStyle("k", fontName=f, fontSize=8, leading=10.5, textColor=colors.HexColor("#475467")),
        "baslik": ParagraphStyle("b", fontName=fb, fontSize=13, leading=17, spaceBefore=10, spaceAfter=6,
                                 textColor=colors.HexColor(LACIVERT), keepWithNext=1),
        "alt": ParagraphStyle("a", fontName=fb, fontSize=10.5, leading=14, spaceBefore=8, spaceAfter=3, keepWithNext=1),
        "kapak1": ParagraphStyle("k1", fontName=fb, fontSize=22, leading=28, textColor=colors.HexColor(LACIVERT)),
        "kapak2": ParagraphStyle("k2", fontName=f, fontSize=12, leading=17),
        "hucre": ParagraphStyle("h", fontName=f, fontSize=8, leading=10),
        "hucre_b": ParagraphStyle("hb", fontName=fb, fontSize=8, leading=10, textColor=colors.white),
    }


def _esc(s) -> str:
    from xml.sax.saxutils import escape
    return escape("" if s is None else str(s))


def _tablo(satirlar: list[list], genislikler: list[float], st, vurgu_sutun: Optional[int] = None):
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle
    veri = [[Paragraph(_esc(h), st["hucre_b"]) for h in satirlar[0]]]
    for r in satirlar[1:]:
        veri.append([Paragraph(_esc(h).replace("\n", "<br/>"), st["hucre"]) for h in r])
    t = Table(veri, colWidths=genislikler, repeatRows=1)
    stil = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(LACIVERT)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D0D5DD")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FC")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    if vurgu_sutun is not None:
        for i, r in enumerate(satirlar[1:], 1):
            renk = DURUM_RENK.get(str(r[vurgu_sutun]))
            if renk:
                stil.append(("TEXTCOLOR", (vurgu_sutun, i), (vurgu_sutun, i), colors.HexColor(renk)))
    t.setStyle(TableStyle(stil))
    return t


def _sayfa_cerceve(baslik: str, alt: str):
    f, _ = _fontlar()

    def ciz(canvas, doc):
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        canvas.saveState()
        w, h = doc.pagesize
        canvas.setStrokeColor(colors.HexColor(LACIVERT))
        canvas.setLineWidth(0.6)
        canvas.line(18 * mm, h - 14 * mm, w - 18 * mm, h - 14 * mm)
        canvas.setFont(f, 7.5)
        canvas.setFillColor(colors.HexColor("#475467"))
        canvas.drawString(18 * mm, h - 12 * mm, baslik)
        canvas.drawRightString(w - 18 * mm, 10 * mm, f"Sayfa {doc.page}")
        canvas.drawString(18 * mm, 10 * mm, alt)
        canvas.restoreState()
    return ciz


# ---------------------------------------------------------------------------
# PDF hazırlık raporu
# ---------------------------------------------------------------------------

def pdf_hazirlik_raporu(db, firma_id: int, hazirlayan: str, rapor_no: str = "", urun_idler: Optional[list[int]] = None) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    st = _stiller()
    f = repo.firma(db, firma_id)
    urunler = repo.urunler(db, firma_id)
    if urun_idler:
        urunler = [u for u in urunler if u["id"] in set(urun_idler)]
    secili = {u["id"] for u in urunler}
    bulgular = [b for b in evaluation.firma_bulgulari(db, firma_id) if b["urun_id"] in secili]
    belgeler = repo.belgeler(db, firma_id)
    dogrulamalar = [d for d in repo.dogrulamalar(db, firma_id) if d["urun_id"] in secili]
    bugun = datetime.now()
    rapor_no = rapor_no or f"DPP-{firma_id:04d}-{bugun:%Y%m%d%H%M}"

    c = io.BytesIO()
    doc = SimpleDocTemplate(c, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=20 * mm, bottomMargin=18 * mm,
                            title="DPP Hazırlık ve Ön Kontrol Raporu", author=hazirlayan)
    G = doc.width
    h: list = []

    # Kapak
    h += [Spacer(1, 45 * mm), Paragraph("DPP HAZIRLIK VE<br/>ÖN KONTROL RAPORU", st["kapak1"]), Spacer(1, 10 * mm),
          Paragraph(_esc(f["unvan"]), st["kapak2"]), Spacer(1, 30 * mm)]
    h.append(_tablo([["Bilgi", ""],
                     ["Rapor no", rapor_no], ["Rapor tarihi", f"{bugun:%d.%m.%Y}"], ["Hazırlayan", hazirlayan],
                     ["Kapsam", f"{len(urunler)} ürün"], ["Kural seti", urunler[0]["kural_seti"] if urunler and urunler[0]["kural_seti"] else "—"],
                     ["Mevzuat gözden geçirme", MEVZUAT_GOZDEN_GECIRME], ["Program sürümü", SURUM]],
                    [G * 0.35, G * 0.65], st))
    h.append(PageBreak())

    # I
    h.append(Paragraph(f"{ROMA[0]}. RAPORUN AMACI VE KAPSAMI", st["baslik"]))
    h.append(Paragraph(
        f"Bu rapor, {_esc(f['unvan'])} tarafından Avrupa Birliği pazarına arz edilen veya edilmesi planlanan ürünlerin, "
        "AB Sürdürülebilir Ürünler için Ekotasarım Tüzüğü (ESPR, (AB) 2024/1781) kapsamındaki Dijital Ürün Pasaportu (DPP) "
        "gerekliliklerine ve bugün yürürlükte olan ilgili ürün mevzuatına hazırlık düzeyini ortaya koymak amacıyla hazırlanmıştır.", st["govde"]))
    h.append(Spacer(1, 3 * mm))
    h.append(Paragraph(
        "Her ürün iki ayrı gösterge ile değerlendirilmiştir: <b>Yasal uyum</b>, bugün yürürlükte olan şartların karşılanıp "
        "karşılanmadığını; <b>DPP hazırlık skoru</b> ise ileride zorunlu hale gelmesi beklenen veriler ile iyi uygulamaların "
        "ağırlıklı karşılanma oranını gösterir. Kritik yasal eksiği bulunan ürünler 'Kritik eksik' olarak sınıflandırılmıştır.", st["govde"]))
    h.append(Spacer(1, 3 * mm))
    h.append(Paragraph(_esc(UYARI), st["kucuk"]))

    # II
    h.append(Paragraph(f"{ROMA[1]}. ÖZET BULGULAR", st["baslik"]))
    sayim = Counter(u["genel_durum"] or "Değerlendirilmedi" for u in urunler)
    skorlar = [u["hazirlik_skoru"] for u in urunler if u["hazirlik_skoru"] is not None]
    belge_sayim = Counter(b["durum"] for b in belgeler)
    ozet = [["Gösterge", "Değer"], ["Değerlendirilen ürün", str(len(urunler))]]
    ozet += [[d, str(sayim.get(d, 0))] for d in DURUMLAR]
    ozet += [["Ortalama DPP hazırlık skoru", f"%{sum(skorlar) / len(skorlar):.0f}" if skorlar else "—"],
             ["Kayıtlı belge", str(len(belgeler))], ["Süresi dolmuş belge", str(belge_sayim.get("Süresi dolmuş", 0))],
             ["60 gün içinde süresi dolacak belge", str(belge_sayim.get("30 gün içinde doluyor", 0) + belge_sayim.get("60 gün içinde doluyor", 0))],
             ["Bağımsız doğrulama bekleyen belge", str(sum(1 for b in belgeler if b["dogrulama_durumu"] == "Beklemede"))]]
    h.append(_tablo(ozet, [G * 0.6, G * 0.4], st))
    sik = Counter(b["kural_kodu"] for b in bulgular if b["sonuc"] == "Eksik").most_common(5)
    if sik:
        h.append(Paragraph("En sık görülen eksikler", st["alt"]))
        h.append(_tablo([["Kural", "Sınıf", "Ürün sayısı"]] +
                        [[f"{k} {KURAL[k].ad}", KURAL[k].sinif, str(n)] for k, n in sik], [G * 0.6, G * 0.2, G * 0.2], st))

    # III
    h.append(Paragraph(f"{ROMA[2]}. ÜRÜN BAZINDA SONUÇLAR", st["baslik"]))
    sirali = sorted(urunler, key=lambda u: (DURUMLAR.index(u["genel_durum"]) if u["genel_durum"] in DURUMLAR else 9, u["urun_kodu"]))
    h.append(_tablo([["Ürün kodu", "Ürün adı", "Sektör", "Genel durum", "Yasal eksik", "DPP hazırlık"]] +
                    [[u["urun_kodu"], u["ad"], SEKTOR_ADLARI.get(u["sektor_kodu"]), u["genel_durum"] or "—",
                      str(u["yasal_eksik"] if u["yasal_eksik"] is not None else "—"),
                      f"%{u['hazirlik_skoru']:.0f}" if u["hazirlik_skoru"] is not None else "—"] for u in sirali],
                    [G * 0.14, G * 0.3, G * 0.18, G * 0.15, G * 0.1, G * 0.13], st, vurgu_sutun=3))

    # IV
    h.append(Paragraph(f"{ROMA[3]}. YASAL EKSİKLER VE ÇÖZÜM ÖNERİLERİ", st["baslik"]))
    yasal = [b for b in bulgular if b["sonuc"] == "Eksik" and b["sinif"] == "Yasal"]
    if not yasal:
        h.append(Paragraph("Değerlendirilen ürünlerde yürürlükteki mevzuat bakımından eksik tespit edilmemiştir.", st["govde"]))
    for u in sirali:
        ub = [b for b in yasal if b["urun_id"] == u["id"]]
        if not ub:
            continue
        h.append(Paragraph(f"{_esc(u['urun_kodu'])} — {_esc(u['ad'])}", st["alt"]))
        satir = [["Kural", "Seviye", "Tespit", "Yapılacaklar"]]
        for b in sorted(ub, key=lambda x: ["Kritik", "Yüksek", "Orta", "Bilgi"].index(x["seviye"])):
            satir.append([f"{b['kural_kodu']} {b['kural']}\n({b['dayanak']})", b["seviye"], b["detay"],
                          "\n".join(f"• {a}" for a in b["recete"])])
        h.append(_tablo(satir, [G * 0.25, G * 0.1, G * 0.27, G * 0.38], st))

    # V
    h.append(Paragraph(f"{ROMA[4]}. DPP HAZIRLIĞI İÇİN TAMAMLANMASI GEREKEN VERİLER", st["baslik"]))
    hz = Counter((b["kural_kodu"]) for b in bulgular if b["sonuc"] == "Eksik" and b["sinif"] != "Yasal")
    if hz:
        h.append(_tablo([["Kural", "Sınıf", "Eksik olan ürün", "İlk adım"]] +
                        [[f"{k} {KURAL[k].ad}", KURAL[k].etkin_sinif(date.today()), str(n), KURAL[k].recete[0]] for k, n in hz.most_common()],
                        [G * 0.3, G * 0.17, G * 0.13, G * 0.4], st))
    else:
        h.append(Paragraph("DPP hazırlık kurallarının tamamı karşılanmaktadır.", st["govde"]))

    # VI
    h.append(Paragraph(f"{ROMA[5]}. BELGE DURUMU", st["baslik"]))
    dikkat = [b for b in belgeler if b["durum"] != "Geçerli" and b["durum"] != "Bitiş tarihi yok" or b["dogrulama_durumu"] != "Doğrulandı"]
    if dikkat:
        h.append(_tablo([["Belge", "No", "Bitiş", "Durum", "Doğrulama"]] +
                        [[BELGE.get(b["tur_kodu"], BELGE["DIGER"]).ad if b["tur_kodu"] != "DIGER" else (b["tur_serbest"] or "Diğer"),
                          b["belge_no"] or "—", b["bitis"] or "—", b["durum"], b["dogrulama_durumu"]] for b in dikkat[:60]],
                        [G * 0.32, G * 0.18, G * 0.14, G * 0.2, G * 0.16], st))
    else:
        h.append(Paragraph("Tüm belgeler geçerli ve doğrulanmış durumdadır.", st["govde"]))

    # VII
    h.append(Paragraph(f"{ROMA[6]}. YAKLAŞAN YÜKÜMLÜLÜKLER (12 AY)", st["baslik"]))
    yk = yaklasan_yukumlulukler()
    if yk:
        h.append(_tablo([["Tarih", "Yükümlülük", "Kapsam", "Dayanak"]] +
                        [[f"{k.zorunlu_tarih:%d.%m.%Y}", k.ad, k.kapsam, k.dayanak] for k in yk],
                        [G * 0.13, G * 0.27, G * 0.25, G * 0.35], st))
    else:
        h.append(Paragraph("Programın izlediği kurallar arasında 12 ay içinde yürürlüğe girecek yükümlülük bulunmamaktadır.", st["govde"]))

    # VIII
    h.append(Paragraph(f"{ROMA[7]}. BAĞIMSIZ DOĞRULAMA", st["baslik"]))
    if dogrulamalar:
        h.append(_tablo([["Ürün", "Sonuç", "Doğrulayan", "Tarih", "Kapsam / açıklama"]] +
                        [[d["urun_kodu"], d["sonuc"], f"{d['dogrulayan']}\n{d.get('unvan') or ''}", d["tarih"][:10],
                          " ".join(filter(None, [d.get("kapsam"), d.get("aciklama")]))] for d in dogrulamalar],
                        [G * 0.14, G * 0.16, G * 0.22, G * 0.12, G * 0.36], st))
    else:
        h.append(Paragraph("Bu rapor kapsamındaki ürünler için bağımsız doğrulama beyanı düzenlenmemiştir. Rapordaki bulgular "
                           "firmanın sisteme girdiği verilere dayanmaktadır.", st["govde"]))
    h.append(Spacer(1, 12 * mm))
    h.append(Paragraph(f"Hazırlayan: {_esc(hazirlayan)}", st["govde"]))
    h.append(Paragraph(f"Tarih: {bugun:%d.%m.%Y}", st["govde"]))

    cerceve = _sayfa_cerceve(f"{f['unvan']} · DPP Hazırlık ve Ön Kontrol Raporu · {rapor_no}",
                             "Ön kontrol raporudur; resmi uygunluk kararı değildir.")
    doc.build(h, onFirstPage=lambda c_, d_: None, onLaterPages=cerceve)
    return c.getvalue()


# ---------------------------------------------------------------------------
# PDF pasaport sayfası
# ---------------------------------------------------------------------------

def pdf_pasaport(icerik: dict, adres: str, seviye: str = "Kamu") -> bytes:
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    st = _stiller()
    c = io.BytesIO()
    doc = SimpleDocTemplate(c, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=20 * mm, bottomMargin=18 * mm,
                            title=f"Dijital Ürün Pasaportu — {icerik.get('name')}")
    G = doc.width
    w = QrCodeWidget(adres)
    x1, y1, x2, y2 = w.getBounds()
    boyut = 38 * mm
    qr = Drawing(boyut, boyut, transform=[boyut / (x2 - x1), 0, 0, boyut / (y2 - y1), 0, 0])
    qr.add(w)
    baslik = [Paragraph("DİJİTAL ÜRÜN PASAPORTU", st["kucuk"]), Paragraph(_esc(icerik.get("name")), st["kapak1"]),
              Paragraph(f"{_esc(icerik.get('manufacturer', {}).get('name'))} · {_esc(icerik.get('category'))}", st["kapak2"]),
              Spacer(1, 2 * mm),
              Paragraph(f"Pasaport: {_esc(icerik.get('dpp:pasaportKimligi'))} · Sürüm {icerik.get('dpp:surum')} · "
                        f"Görünüm: {_esc(seviye)}", st["kucuk"])]
    ust = Table([[baslik, qr]], colWidths=[G - boyut - 6 * mm, boyut + 6 * mm])
    ust.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    h = [ust, Spacer(1, 6 * mm)]

    def bolum(ad, satirlar):
        satirlar = [s for s in satirlar if s[1] not in (None, "", [], {})]
        if satirlar:
            h.append(Paragraph(ad, st["baslik"]))
            h.append(_tablo([["Alan", "Değer"]] + [[a, str(b)] for a, b in satirlar], [G * 0.35, G * 0.65], st))

    bolum("Kimlik", [("Ürün kodu", icerik.get("sku")), ("GTIN", icerik.get("gtin")), ("Marka", icerik.get("brand")),
                     ("Parti / lot", icerik.get("dpp:partiNo")), ("Üretim tarihi", icerik.get("dpp:uretimTarihi")),
                     ("GTİP", icerik.get("dpp:gtip"))])
    bolum("Aktörler", [("Üretici / ihracatçı", icerik.get("manufacturer", {}).get("name")),
                       ("AB sorumlu ekonomik operatör", icerik.get("dpp:abSorumluOperator")),
                       ("Üretim tesisi", (icerik.get("dpp:uretimTesisi") or {}).get("ad"))])
    bolum("Menşe ve malzeme", [("Üretim ülkesi", icerik.get("countryOfOrigin")), ("Hammadde menşei", icerik.get("dpp:hammaddeMensei")),
                               ("Malzeme bileşimi", ", ".join(f"{m.get('name')} %{m.get('dpp:oranYuzde', 0):g}" for m in icerik.get("material", []))),
                               ("Geri dönüştürülmüş içerik", f"%{icerik['dpp:geriDonusturulmusIcerikYuzde']:g}" if icerik.get("dpp:geriDonusturulmusIcerikYuzde") is not None else None),
                               ("SVHC beyanı", " — ".join(filter(None, [icerik.get("dpp:svhc", {}).get("beyan"), icerik.get("dpp:svhc", {}).get("maddeler")])))])
    cevre = icerik.get("dpp:cevre", {})
    bolum("Çevre", [("Çevresel iddia", cevre.get("iddia")),
                    ("Karbon ayak izi", f"{cevre['karbonAyakIziKgCO2e']:g} kg CO2e / birim ({cevre.get('yontem', '')})" if cevre.get("karbonAyakIziKgCO2e") is not None else None),
                    ("Gömülü emisyon", f"{icerik['dpp:gomuluEmisyon']:g} tCO2e / t" if icerik.get("dpp:gomuluEmisyon") is not None else None)])
    bat = icerik.get("dpp:batarya", {})
    bolum("Batarya", [("Kategori", bat.get("kategori")), ("Kimya", bat.get("kimya")), ("Kapasite (kWh)", bat.get("kapasiteKWh"))])
    kul = icerik.get("dpp:kullanim", {})
    bolum("Kullanım ve ömür sonu", [("Bakım / onarım", kul.get("bakimOnarim")), ("Ömür sonu", kul.get("omurSonu"))])
    if icerik.get("dpp:belgeler"):
        h.append(Paragraph("Belgeler", st["baslik"]))
        h.append(_tablo([["Belge", "Geçerlilik", "Durum", "Doğrulama"]] +
                        [[b.get("tur"), b.get("gecerlilikBitis", "—"), b.get("durum"), b.get("dogrulama", "—")] for b in icerik["dpp:belgeler"]],
                        [G * 0.4, G * 0.18, G * 0.22, G * 0.2], st))
    if icerik.get("dpp:tedarikZinciri"):
        h.append(Paragraph("Tedarik zinciri", st["baslik"]))
        h.append(_tablo([["Sıra", "Aşama", "Tedarikçi", "Ülke"]] +
                        [[str(a.get("sira", "")), a.get("asama"), a.get("tedarikci", "—"), a.get("ulke", "—")] for a in icerik["dpp:tedarikZinciri"]],
                        [G * 0.1, G * 0.35, G * 0.35, G * 0.2], st))
    dog = icerik.get("dpp:bagimsizDogrulama")
    if dog:
        h.append(Paragraph("Bağımsız doğrulama", st["baslik"]))
        h.append(Paragraph(f"{_esc(dog.get('sonuc'))} — {_esc(dog.get('dogrulayan'))} {_esc(dog.get('unvan') or '')}, "
                           f"{_esc(dog.get('tarih'))}. {_esc(dog.get('kapsam') or '')}", st["govde"]))
    h.append(Spacer(1, 8 * mm))
    h.append(Paragraph(f"Çevrim içi pasaport: {_esc(adres)}", st["kucuk"]))
    h.append(Paragraph(f"İçerik özeti (SHA-256): {_esc(icerik.get('dpp:icerikOzeti'))}", st["kucuk"]))
    h.append(Paragraph("Bu pasaport taslak veri yapısıyla hazırlanmıştır; ilgili yetki tüzüğü yayımlandığında resmi şemaya "
                       "uyarlanacaktır. Hazırlık göstergeleri resmi uygunluk kararı değildir.", st["kucuk"]))
    doc.build(h)
    return c.getvalue()
