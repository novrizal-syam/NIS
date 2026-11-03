"""Bahasa Indonesia HTML emails on the Nustrad theme. Table layout and inline styles so they
render in Outlook/Gmail; every inserted value is HTML-escaped."""

from dataclasses import dataclass
from html import escape

from app.core.config import get_settings

INK, GOLD, MIST, BODY, MUTED = "#1A1A1A", "#FFBD52", "#F1F2F2", "#333333", "#555555"
FOOTER = "Dikirim oleh Nustrad ERP untuk PT Global Energi KITA"


@dataclass(frozen=True)
class Rendered:
    subject: str
    html: str
    text: str


def _layout(title: str, intro: str, button: str, link: str, note: str) -> str:
    base = get_settings().app_base_url.rstrip("/")
    logo = f"{base}/brand/nustrad-logo-primary.png"
    return f"""<!doctype html>
<html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{escape(title)}</title></head>
<body style="margin:0;padding:0;background:{MIST};font-family:Montserrat,Arial,sans-serif;color:{BODY}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{MIST};padding:24px 12px">
<tr><td align="center">
<table role="presentation" width="560" cellpadding="0" cellspacing="0"
 style="max-width:560px;width:100%;background:#FFFFFF;border:1px solid #E2E3E3;border-radius:8px">
<tr><td style="padding:24px 32px 8px"><img src="{escape(logo)}" width="150" alt="Nustrad"
 style="display:block;border:0;height:auto"></td></tr>
<tr><td style="padding:8px 32px 0">
<h1 style="margin:0 0 12px;font-family:Prompt,Arial,sans-serif;font-size:22px;line-height:30px;color:{INK}">{escape(title)}</h1>
<p style="margin:0 0 20px;font-size:14px;line-height:22px">{intro}</p>
<table role="presentation" cellpadding="0" cellspacing="0"><tr><td style="border-radius:6px;background:{GOLD}">
<a href="{escape(link)}" style="display:inline-block;padding:12px 24px;font-size:14px;font-weight:700;
color:{INK};text-decoration:none;border-radius:6px">{escape(button)}</a></td></tr></table>
<p style="margin:20px 0 4px;font-size:12px;line-height:18px;color:{MUTED}">{note}</p>
<p style="margin:0 0 24px;font-size:12px;line-height:18px;color:{MUTED};word-break:break-all">
Jika tombol tidak berfungsi, salin tautan ini ke browser:<br>{escape(link)}</p>
</td></tr>
<tr><td style="padding:16px 32px;border-top:1px solid #E2E3E3;font-size:11px;line-height:16px;color:{MUTED}">
{FOOTER}</td></tr>
</table></td></tr></table></body></html>"""


def _link(path: str) -> str:
    return get_settings().app_base_url.rstrip("/") + path


def invite(name: str, token: str, hours: int) -> Rendered:
    link = _link(f"/activate?token={token}")
    title = "Aktifkan akun Nustrad ERP Anda"
    html = _layout(
        title,
        f"Halo {escape(name)}, Anda diundang menggunakan Nustrad ERP PT Global Energi KITA. "
        "Klik tombol di bawah untuk membuat kata sandi dan mengaktifkan akun.",
        "Aktifkan akun",
        link,
        f"Tautan berlaku {hours} jam dan hanya dapat dipakai sekali. "
        "Abaikan email ini jika Anda tidak merasa diundang.",
    )
    text = (
        f"Halo {name},\n\nAnda diundang menggunakan Nustrad ERP PT Global Energi KITA.\n"
        f"Aktifkan akun: {link}\n\nTautan berlaku {hours} jam dan hanya sekali pakai. "
        f"Abaikan email ini jika Anda tidak merasa diundang.\n\n{FOOTER}"
    )
    return Rendered(title, html, text)


def password_reset(name: str, token: str, minutes: int) -> Rendered:
    link = _link(f"/reset-password?token={token}")
    title = "Atur ulang kata sandi Nustrad ERP"
    html = _layout(
        title,
        f"Halo {escape(name)}, kami menerima permintaan untuk mengatur ulang kata sandi akun Anda.",
        "Atur ulang kata sandi",
        link,
        f"Tautan berlaku {minutes} menit dan hanya dapat dipakai sekali. Abaikan email ini jika "
        "bukan Anda yang meminta; kata sandi Anda tidak berubah.",
    )
    text = (
        f"Halo {name},\n\nAtur ulang kata sandi: {link}\n\nTautan berlaku {minutes} menit dan "
        f"hanya sekali pakai. Abaikan jika bukan Anda yang meminta.\n\n{FOOTER}"
    )
    return Rendered(title, html, text)


def test_message(name: str) -> Rendered:
    link = _link("/")
    title = "Email uji Nustrad ERP"
    html = _layout(
        title,
        f"Halo {escape(name)}, pengiriman email dari Nustrad ERP berfungsi.",
        "Buka Nustrad ERP",
        link,
        "Email ini dikirim dari Pengaturan oleh Super Admin.",
    )
    return Rendered(
        title, html, f"Pengiriman email dari Nustrad ERP berfungsi.\n{link}\n\n{FOOTER}"
    )


def notification(name: str, title: str, body: str, path: str | None) -> Rendered:
    link = _link(path or "/")
    html = _layout(
        title,
        f"Halo {escape(name)}, {escape(body)}",
        "Buka di Nustrad ERP",
        link,
        "Notifikasi otomatis; atur preferensi di aplikasi.",
    )
    return Rendered(title, html, f"{body}\n\nBuka: {link}\n\n{FOOTER}")
