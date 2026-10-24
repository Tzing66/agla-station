"""A QR code that opens the bot in Telegram, for people who can't find it by search.

    uv run python -m scripts.bot_qr [--out docs/telegram-qr.png]

Reads TELEGRAM_BOT_USERNAME from .env and draws a card with the QR code for https://t.me/<username> and the handle
underneath, in the app's palette. Scanning it with a phone camera opens the chat in Telegram.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont

from agla.config import settings

FONTS = Path(__file__).resolve().parents[1] / "data" / "fonts"
INK, SOFT, PAPER = "#3b1f1a", "#7a4a3c", "#fff6ee"


def font(size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONTS / "Baloo2.ttf"), size)
    f.set_variation_by_name(weight)
    return f


def card(username: str) -> Image.Image:
    url = f"https://t.me/{username}"
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=18, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    code = qr.make_image(fill_color=INK, back_color=PAPER).convert("RGB")

    w = code.width + 120
    img = Image.new("RGB", (w, code.height + 300), PAPER)
    d = ImageDraw.Draw(img)
    d.text((w // 2, 56), "Agla Station on Telegram", font=font(46, "ExtraBold"), fill=INK, anchor="mm")
    img.paste(code, (60, 100))
    y = 100 + code.height + 20
    d.text((w // 2, y + 30), f"@{username}", font=font(42), fill=INK, anchor="mm")
    body = ImageFont.truetype(str(FONTS / "Mukta-Medium.ttf"), 28)
    d.text((w // 2, y + 90), "Scan with your phone camera, then tap Start", font=body, fill=SOFT, anchor="mm")
    d.text((w // 2, y + 132), url.removeprefix("https://"), font=body, fill=SOFT, anchor="mm")
    return img


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=Path("docs/telegram-qr.png"))
    args = p.parse_args()
    username = settings().telegram_bot_username.lstrip("@")
    if not username:
        raise SystemExit("TELEGRAM_BOT_USERNAME is not set in .env")
    card(username).save(args.out, optimize=True)
    print(f"{args.out}: opens https://t.me/{username}")


if __name__ == "__main__":
    main()
