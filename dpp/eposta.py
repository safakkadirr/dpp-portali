"""
E-posta gönderimi ve tedarikçi talep metinleri.

SMTP ayarları Streamlit Secrets'tan okunur. Ayar yoksa program e-posta göndermez;
kullanıcı hazırlanan metni kopyalar veya kendi e-posta programıyla açar.

    SMTP_HOST = "mail.firma.com.tr"
    SMTP_PORT = 465                 # 465 (SSL) veya 587 (STARTTLS)
    SMTP_KULLANICI = "dpp@firma.com.tr"
    SMTP_PAROLA = "..."
    SMTP_GONDEREN = "Firma DPP <dpp@firma.com.tr>"   # isteğe bağlı
"""

from __future__ import annotations

import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Optional

from . import config

EPOSTA_DESENI = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


def ayarli() -> bool:
    return bool(config.ayar("SMTP_HOST") and config.ayar("SMTP_KULLANICI") and config.ayar("SMTP_PAROLA"))


def gecerli_mi(adres: Optional[str]) -> bool:
    return bool(adres and EPOSTA_DESENI.match(adres.strip()))


def gonder(alici: str, konu: str, govde: str, yanit_adresi: Optional[str] = None, gonderen_adi: Optional[str] = None) -> None:
    """Düz metin e-posta gönderir. Hata durumunda anlaşılır bir ValueError fırlatır."""
    if not ayarli():
        raise ValueError("E-posta gönderimi ayarlanmamış (SMTP_HOST / SMTP_KULLANICI / SMTP_PAROLA).")
    alicilar = [a.strip() for a in re.split(r"[;,]", alici or "") if a.strip()]
    if not alicilar or not all(gecerli_mi(a) for a in alicilar):
        raise ValueError(f"Geçersiz e-posta adresi: {alici!r}")
    host = str(config.ayar("SMTP_HOST"))
    port = int(config.ayar("SMTP_PORT", 465))
    kullanici = str(config.ayar("SMTP_KULLANICI"))
    gonderen = str(config.ayar("SMTP_GONDEREN", "") or (formataddr((gonderen_adi, kullanici)) if gonderen_adi else kullanici))
    m = EmailMessage()
    m["From"] = gonderen
    m["To"] = ", ".join(alicilar)
    m["Subject"] = konu
    m["Message-ID"] = make_msgid()
    if yanit_adresi and gecerli_mi(yanit_adresi):
        m["Reply-To"] = yanit_adresi
    m.set_content(govde)
    try:
        baglam = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=baglam, timeout=20) as s:
                s.login(kullanici, str(config.ayar("SMTP_PAROLA")))
                s.send_message(m)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls(context=baglam)
                s.login(kullanici, str(config.ayar("SMTP_PAROLA")))
                s.send_message(m)
    except smtplib.SMTPAuthenticationError:
        raise ValueError("E-posta sunucusu kullanıcı adı veya parolayı kabul etmedi.")
    except (smtplib.SMTPException, OSError) as h:
        raise ValueError(f"E-posta gönderilemedi: {h}")


# ---------------------------------------------------------------------------
# Talep metinleri
# ---------------------------------------------------------------------------
# Hukuki dayanak cümleleri sabittir; yapay zekâ ile düzenlemede değiştirilmez.

DAYANAK = {
    "tr": {
        "svhc": ("REACH Tüzüğü (EC) No 1907/2006 Madde 33 uyarınca, aday listedeki (SVHC) maddeleri ağırlıkça %0,1'in "
                 "üzerinde içeren bir eşyanın tedarikçisi, eşyanın güvenli kullanımı için yeterli bilgiyi — en azından "
                 "maddenin adını — alıcıya sağlamakla yükümlüdür."),
        "genel": ("Talep edilen bilgiler, AB'ye ihraç edilen ürünler için Sürdürülebilir Ürünler için Ekotasarım Tüzüğü "
                  "(ESPR, (EU) 2024/1781) kapsamında hazırlanan Dijital Ürün Pasaportu ve müşteri uyum talepleri için "
                  "kullanılacaktır."),
    },
    "en": {
        "svhc": ("Under Article 33 of the REACH Regulation (EC) No 1907/2006, a supplier of an article containing a substance "
                 "on the Candidate List (SVHC) in a concentration above 0.1% weight by weight shall provide the recipient "
                 "with sufficient information to allow safe use of the article, including, as a minimum, the name of that substance."),
        "genel": ("The requested information will be used for the Digital Product Passport prepared under the Ecodesign for "
                  "Sustainable Products Regulation (ESPR, (EU) 2024/1781) and for our customers' compliance requests for "
                  "products exported to the EU."),
    },
}

ISTENEN_ADLARI = {
    "tr": {"malzeme": "Malzeme bileşimi (malzeme ve oranları)", "svhc": "REACH / SVHC beyanı", "mense": "Menşe ülke bilgisi",
           "karbon": "Karbon ayak izi (varsa)", "belge": "Geçerli sertifika ve test raporları"},
    "en": {"malzeme": "Material composition (materials and percentages)", "svhc": "REACH / SVHC declaration",
           "mense": "Country of origin", "karbon": "Carbon footprint (if available)", "belge": "Valid certificates and test reports"},
}


def talep_metni(firma_unvan: str, tedarikci_unvan: str, yetkili: Optional[str], urunler: list[str], istenenler: list[str],
                ek_mesaj: str, adres: str, son_tarih: str, dil: str = "tr", gonderen: str = "",
                belge_notlari: Optional[list[str]] = None) -> tuple[str, str]:
    """(konu, gövde) döner. Bağlantı ve hukuki dayanak metinde sabit yer alır."""
    dil = dil if dil in DAYANAK else "tr"
    adlar = ISTENEN_ADLARI[dil]
    maddeler = "\n".join(f"  • {adlar.get(i, i)}" for i in istenenler)
    urun_satiri = "\n".join(f"  – {u}" for u in urunler[:30]) + (f"\n  … (+{len(urunler) - 30})" if len(urunler) > 30 else "")
    belge_satiri = "\n".join(f"  – {b}" for b in (belge_notlari or []))
    dayanak = [DAYANAK[dil]["genel"]] + ([DAYANAK[dil]["svhc"]] if "svhc" in istenenler else [])
    if dil == "en":
        konu = f"{firma_unvan} – Product compliance data request (DPP / REACH)"
        govde = (f"Dear {yetkili or tedarikci_unvan},\n\n"
                 f"As part of our EU export compliance work, we kindly ask you to provide the following information for the "
                 f"products/materials you supply to us:\n\n{maddeler}\n"
                 + (f"\nRelated products:\n{urun_satiri}\n" if urunler else "")
                 + (f"\nDocuments that need renewal or replacement:\n{belge_satiri}\n" if belge_satiri else "")
                 + (f"\n{ek_mesaj.strip()}\n" if ek_mesaj and ek_mesaj.strip() else "")
                 + f"\nPlease submit the information and upload your documents via the secure link below (no account needed):\n{adres}\n\n"
                 f"The link is valid until {son_tarih}.\n\n" + "\n\n".join(dayanak)
                 + f"\n\nThank you for your cooperation.\n\nKind regards,\n{gonderen or firma_unvan}\n{firma_unvan}")
    else:
        konu = f"{firma_unvan} – Ürün uyum bilgi ve belge talebi (DPP / REACH)"
        govde = (f"Sayın {yetkili or tedarikci_unvan},\n\n"
                 f"AB'ye yaptığımız ihracata ilişkin uyum çalışmalarımız kapsamında, tarafımıza tedarik ettiğiniz ürün ve "
                 f"malzemeler için aşağıdaki bilgi ve belgeleri iletmenizi rica ederiz:\n\n{maddeler}\n"
                 + (f"\nİlgili ürünler:\n{urun_satiri}\n" if urunler else "")
                 + (f"\nYenilenmesi veya yeniden gönderilmesi gereken belgeler:\n{belge_satiri}\n" if belge_satiri else "")
                 + (f"\n{ek_mesaj.strip()}\n" if ek_mesaj and ek_mesaj.strip() else "")
                 + f"\nBilgileri aşağıdaki güvenli bağlantıdan girebilir ve belgelerinizi yükleyebilirsiniz (hesap gerekmez):\n{adres}\n\n"
                 f"Bağlantı {son_tarih} tarihine kadar geçerlidir.\n\n" + "\n\n".join(dayanak)
                 + f"\n\nİş birliğiniz için teşekkür ederiz.\n\nSaygılarımızla,\n{gonderen or firma_unvan}\n{firma_unvan}")
    return konu, govde


def hatirlatma_metni(konu: str, govde: str, dil: str = "tr") -> tuple[str, str]:
    if dil == "en":
        return f"Reminder: {konu}", ("This is a friendly reminder regarding our request below. A new link has been created; "
                                      "the previous link is no longer valid.\n\n" + govde)
    return f"Hatırlatma: {konu}", ("Aşağıdaki talebimizi hatırlatmak isteriz. Sizin için yeni bir bağlantı oluşturuldu; "
                                   "önceki bağlantı artık geçerli değildir.\n\n" + govde)
