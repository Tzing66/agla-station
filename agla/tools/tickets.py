"""Mock QR ticket image. Clearly a DEMO: DMRC has no public ticket-issuing API."""

from __future__ import annotations

import io
import json
from datetime import datetime

import qrcode
from PIL import Image, ImageDraw, ImageFont

from agla.tools.stations import get_station
from agla.tools.types import Trip

W, H = 720, 1080
INK, MUTED, ACCENT, WARN = "#1b1f24", "#5b6470", "#0b6e4f", "#b42318"


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def render_ticket(trip: Trip) -> bytes:
    a, b = get_station(trip.route.from_id).name, get_station(trip.route.to_id).name
    depart = datetime.fromisoformat(trip.depart_at)
    eta = datetime.fromisoformat(trip.eta)

    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 120], fill=ACCENT)
    d.text((40, 30), "Agla Station", font=_font(44), fill="white")
    d.text((40, 82), "Delhi NCR Metro  ·  single journey", font=_font(22), fill="#d6f5e8")

    d.rectangle([0, 120, W, 175], fill="#fde8e7")
    d.text((W // 2, 147), "DEMO TICKET · NOT VALID FOR TRAVEL", font=_font(26), fill=WARN, anchor="mm")

    y = 205
    d.text((40, y), "FROM", font=_font(20), fill=MUTED)
    d.text((40, y + 26), a, font=_font(36), fill=INK)
    d.text((40, y + 90), "TO", font=_font(20), fill=MUTED)
    d.text((40, y + 116), b, font=_font(36), fill=INK)

    y = 390
    lines = " > ".join(leg.line_name for leg in trip.route.legs if leg.line_id != "WALK")  # font has no →
    rows = [
        ("Route", lines),
        ("Fare", f"Rs {trip.fare.total} ({trip.fare.day_type.replace('_', '/')})"),
        ("Issued", depart.strftime("%d %b %Y, %I:%M %p")),
        ("Est. arrival", eta.strftime("%I:%M %p")),
        ("Ticket", trip.ticket_id),
    ]
    for label, value in rows:
        d.text((40, y), label, font=_font(22), fill=MUTED)
        d.text((220, y), value, font=_font(24), fill=INK)
        y += 44

    payload = json.dumps({"t": trip.ticket_id, "f": trip.route.from_id, "to": trip.route.to_id, "demo": True})
    qr = qrcode.make(payload, box_size=8, border=2).convert("RGB").resize((380, 380))
    img.paste(qr, ((W - 380) // 2, 630))
    d.text((W // 2, 1040), "Concept demo · payment not verified", font=_font(20), fill=MUTED, anchor="mm")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
