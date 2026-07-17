"""
Generates the DSigner logo assets:
  logo.png       - full-color app icon (256px)
  logo_light.png - light variant used as signature stamp background
  logo.ico       - multi-size Windows icon for the exe / window

Run:  python assets/make_logo.py
"""
import os
import sys

from PySide6.QtGui import (QGuiApplication, QImage, QPainter, QColor,
                         QLinearGradient, QFont, QPainterPath, QPen, QBrush)
from PySide6.QtCore import Qt, QRectF, QPointF

ASSETS = os.path.dirname(os.path.abspath(__file__))

FULL = {"bg1": "#3b82f6", "bg2": "#1e3a8a",
        "letter": "#ffffff", "stroke": "#fbbf24"}
# lighter shade for the stamp background
LIGHT = {"bg1": "#eff6ff", "bg2": "#dbeafe",
         "letter": "#bfdbfe", "stroke": "#fde68a"}


def draw_logo(size, palette):
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256.0

    # rounded-square badge with gradient
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, QColor(palette["bg1"]))
    grad.setColorAt(1.0, QColor(palette["bg2"]))
    p.setBrush(QBrush(grad))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 48 * s, 48 * s)

    # the "D"
    font = QFont("Segoe UI")
    font.setPixelSize(int(148 * s))
    font.setBold(True)
    p.setFont(font)
    p.setPen(QColor(palette["letter"]))
    p.drawText(QRectF(0, 14 * s, size, 168 * s), Qt.AlignCenter, "D")

    # handwritten signature swoosh under the D
    path = QPainterPath(QPointF(50 * s, 198 * s))
    path.cubicTo(QPointF(92 * s, 168 * s), QPointF(118 * s, 226 * s),
                 QPointF(158 * s, 194 * s))
    path.cubicTo(QPointF(180 * s, 178 * s), QPointF(194 * s, 192 * s),
                 QPointF(208 * s, 184 * s))
    pen = QPen(QColor(palette["stroke"]), 11 * s,
               Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)

    p.end()
    return img


def main():
    app = QGuiApplication(sys.argv)  # noqa: F841 - keep Qt alive while drawing

    logo_png = os.path.join(ASSETS, "logo.png")
    light_png = os.path.join(ASSETS, "logo_light.png")
    logo_ico = os.path.join(ASSETS, "logo.ico")

    draw_logo(256, FULL).save(logo_png)
    draw_logo(256, LIGHT).save(light_png)

    # multi-size .ico via Pillow
    from PIL import Image
    Image.open(logo_png).save(
        logo_ico,
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
               (128, 128), (256, 256)])

    for f in (logo_png, light_png, logo_ico):
        print(f"wrote {f} ({os.path.getsize(f)} bytes)")


if __name__ == "__main__":
    main()
