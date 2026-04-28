"""
Run this once before the event to generate the player join QR code.

Usage:
    python qr_generator.py           # auto-detects local IP, port 8000
    python qr_generator.py 8080      # custom port
"""
import os
import socket
import sys
from pathlib import Path

import qrcode
from qrcode.constants import ERROR_CORRECT_M


def local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def generate(port: int = 8000) -> str:
    url = "https://trivia-elgoss.onrender.com/player.html"
    out = Path(__file__).parent / "static" / "qr_code.png"

    qr = qrcode.QRCode(
        version=1,
        error_correction=ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0d1117", back_color="white")
    with open(out, "wb") as f:
        img.save(f)

    print(f"QR code saved : {out}")
    print(f"Players join  : {url}")
    print(f"Admin panel   : http://{local_ip()}:{port}/admin")
    return url


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.getenv("PORT", 8000))
    generate(port)
