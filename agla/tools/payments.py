"""UPI payment links. Payment is NOT verified: this is an intent link a UPI app (GPay, PhonePe, Paytm) opens."""

from __future__ import annotations

import io
from urllib.parse import quote as urlquote

import qrcode

from agla.tools.stations import get_station
from agla.tools.types import PaymentLink, Quote, ToolError


def make_payment_link(quote: Quote, upi_vpa: str, payee_name: str) -> PaymentLink:
    """Amount comes from the stored quote, never from an argument."""
    if not upi_vpa:
        raise ToolError("Payments aren't set up (UPI_VPA is missing).")
    a, b = get_station(quote.route.from_id).name, get_station(quote.route.to_id).name
    note = f"Agla Station {a}-{b}"[:50]  # UPI apps truncate long notes
    params = {
        "pa": upi_vpa,
        "pn": payee_name,
        "am": f"{quote.fare.total:.2f}",
        "cu": "INR",
        "tn": note,
    }
    uri = "upi://pay?" + "&".join(f"{k}={urlquote(v, safe='@.')}" for k, v in params.items())
    return PaymentLink(upi_uri=uri, qr_png=qr_png(uri), amount=quote.fare.total, payee_name=payee_name, note=note)


def qr_png(data: str, box_size: int = 10) -> bytes:
    img = qrcode.make(data, box_size=box_size, border=3)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
