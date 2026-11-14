"""Monochrome vector icons drawn with QPainter.

No emoji anywhere: every glyph is a thin stroke line-art icon in the palette of
the application (#8E95A0 idle, #00D8F6 active, #EDEDED neutral).
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

IDLE = "#8E95A0"
ACTIVE = "#00D8F6"
NEUTRAL = "#EDEDED"
DIM = "#5F6672"


def _pen(painter: QPainter, color: str, width: float = 1.5) -> None:
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _draw(name: str, painter: QPainter, color: str) -> None:
    _pen(painter, color)
    if name == "chat":
        path = QPainterPath()
        path.addRoundedRect(QRectF(2.5, 3.5, 15, 11), 3, 3)
        path.moveTo(7.0, 14.5)
        path.lineTo(6.0, 18.0)
        path.lineTo(10.5, 14.5)
        painter.drawPath(path)
    elif name == "engineer":
        painter.drawLine(QPointF(4, 16.5), QPointF(13, 7.5))
        path = QPainterPath()
        path.moveTo(11.0, 5.0)
        path.lineTo(15.0, 9.0)
        path.lineTo(16.5, 7.5)
        path.lineTo(12.5, 3.5)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawEllipse(QRectF(3.0, 15.5, 2.4, 2.4))
    elif name == "professor":
        path = QPainterPath()
        path.moveTo(2.5, 7.0)
        path.lineTo(10.0, 3.8)
        path.lineTo(17.5, 7.0)
        path.lineTo(10.0, 10.2)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(QPointF(17.0, 7.6), QPointF(17.0, 12.5))
        painter.drawArc(QRectF(5.0, 8.6, 10.0, 6.0), 200 * 16, 140 * 16)
    elif name == "library":
        painter.drawRoundedRect(QRectF(3.5, 3.0, 4.4, 14.0), 1, 1)
        painter.drawRoundedRect(QRectF(9.6, 3.0, 4.4, 14.0), 1, 1)
        painter.drawLine(QPointF(15.6, 4.2), QPointF(17.4, 16.6))
    elif name == "evolution":
        path = QPainterPath()
        path.moveTo(3.0, 14.5)
        path.lineTo(7.0, 10.5)
        path.lineTo(10.5, 13.0)
        path.lineTo(17.0, 5.5)
        painter.drawPath(path)
        painter.drawLine(QPointF(17.0, 5.5), QPointF(13.2, 5.5))
        painter.drawLine(QPointF(17.0, 5.5), QPointF(17.0, 9.3))
    elif name == "call":
        path = QPainterPath()
        path.moveTo(5.0, 3.5)
        path.lineTo(7.8, 7.0)
        path.lineTo(6.2, 9.0)
        path.cubicTo(8.0, 12.0, 9.5, 13.2, 12.0, 14.6)
        path.lineTo(13.8, 12.8)
        path.lineTo(17.0, 15.4)
        path.lineTo(15.2, 17.2)
        path.cubicTo(10.5, 16.4, 5.4, 11.2, 3.4, 5.6)
        path.closeSubpath()
        painter.drawPath(path)
    elif name == "devices":
        painter.drawRoundedRect(QRectF(6.0, 2.6, 8.0, 14.8), 1.8, 1.8)
        painter.drawLine(QPointF(8.6, 14.6), QPointF(11.4, 14.6))
    elif name == "tools":
        painter.drawRoundedRect(QRectF(2.8, 3.2, 6.4, 5.0), 1.2, 1.2)
        painter.drawRoundedRect(QRectF(10.8, 3.2, 6.4, 5.0), 1.2, 1.2)
        painter.drawRoundedRect(QRectF(2.8, 11.4, 6.4, 5.0), 1.2, 1.2)
        painter.drawRoundedRect(QRectF(10.8, 11.4, 6.4, 5.0), 1.2, 1.2)
    elif name == "settings":
        painter.drawEllipse(QRectF(7.6, 7.6, 4.8, 4.8))
        for angle in range(0, 360, 45):
            painter.save()
            painter.translate(10.0, 10.0)
            painter.rotate(angle)
            painter.drawLine(QPointF(0.0, -6.6), QPointF(0.0, -8.6))
            painter.restore()
        _pen(painter, color)
        painter.drawEllipse(QRectF(3.6, 3.6, 12.8, 12.8))
    elif name == "attach":
        path = QPainterPath()
        path.moveTo(13.8, 6.0)
        path.cubicTo(15.6, 7.8, 15.6, 10.6, 13.6, 12.6)
        path.lineTo(9.6, 16.6)
        path.cubicTo(7.4, 18.6, 4.2, 15.6, 6.2, 13.4)
        path.lineTo(11.0, 8.4)
        path.cubicTo(12.2, 7.2, 13.8, 8.8, 12.6, 10.0)
        path.lineTo(8.4, 14.2)
        painter.drawPath(path)
    elif name == "send":
        painter.drawLine(QPointF(10.0, 16.2), QPointF(10.0, 4.4))
        painter.drawLine(QPointF(10.0, 4.4), QPointF(5.6, 8.8))
        painter.drawLine(QPointF(10.0, 4.4), QPointF(14.4, 8.8))
    elif name == "refresh":
        painter.drawArc(QRectF(4.0, 4.0, 12.0, 12.0), 40 * 16, 280 * 16)
        painter.drawLine(QPointF(15.4, 3.4), QPointF(15.4, 7.6))
        painter.drawLine(QPointF(15.4, 7.6), QPointF(11.2, 7.6))
    elif name == "copy":
        painter.drawRoundedRect(QRectF(7.0, 3.4, 9.6, 11.0), 1.6, 1.6)
        painter.drawLine(QPointF(13.0, 16.6), QPointF(3.4, 16.6))
        painter.drawLine(QPointF(3.4, 16.6), QPointF(3.4, 7.0))
    elif name == "think":
        path = QPainterPath()
        path.moveTo(10.0, 2.8)
        path.cubicTo(11.6, 6.4, 13.6, 8.4, 17.2, 10.0)
        path.cubicTo(13.6, 11.6, 11.6, 13.6, 10.0, 17.2)
        path.cubicTo(8.4, 13.6, 6.4, 11.6, 2.8, 10.0)
        path.cubicTo(6.4, 8.4, 8.4, 6.4, 10.0, 2.8)
        painter.drawPath(path)
    elif name == "chevron":
        painter.drawLine(QPointF(7.0, 8.2), QPointF(10.0, 11.4))
        painter.drawLine(QPointF(10.0, 11.4), QPointF(13.0, 8.2))
    elif name == "shield":
        path = QPainterPath()
        path.moveTo(10.0, 2.6)
        path.lineTo(16.4, 5.2)
        path.lineTo(16.4, 10.4)
        path.cubicTo(16.4, 14.4, 13.2, 16.8, 10.0, 17.6)
        path.cubicTo(6.8, 16.8, 3.6, 14.4, 3.6, 10.4)
        path.lineTo(3.6, 5.2)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(QPointF(7.4, 10.2), QPointF(9.4, 12.2))
        painter.drawLine(QPointF(9.4, 12.2), QPointF(12.8, 8.2))
    elif name == "chip":
        painter.drawRoundedRect(QRectF(5.4, 5.4, 9.2, 9.2), 1.4, 1.4)
        for offset in (7.4, 10.0, 12.6):
            painter.drawLine(QPointF(offset, 2.8), QPointF(offset, 5.4))
            painter.drawLine(QPointF(offset, 14.6), QPointF(offset, 17.2))
            painter.drawLine(QPointF(2.8, offset), QPointF(5.4, offset))
            painter.drawLine(QPointF(14.6, offset), QPointF(17.2, offset))
    elif name == "diff":
        painter.drawLine(QPointF(5.0, 4.0), QPointF(5.0, 16.0))
        painter.drawLine(QPointF(11.0, 6.0), QPointF(17.0, 6.0))
        painter.drawLine(QPointF(14.0, 3.0), QPointF(14.0, 9.0))
        painter.drawLine(QPointF(11.0, 13.0), QPointF(17.0, 13.0))
    else:
        painter.drawEllipse(QRectF(4.0, 4.0, 12.0, 12.0))


def vector_icon(name: str, color: str = IDLE, size: int = 20) -> QIcon:
    """Desenha um icone vetorial monocromatico e devolve um QIcon."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    scale = size / 20.0
    painter.scale(scale, scale)
    _draw(name, painter, color)
    painter.end()
    return QIcon(pixmap)


def app_icon() -> QIcon:
    """Icone do aplicativo: marca MARK em traco fino ciano."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    _pen(painter, ACTIVE, 2.4)
    painter.drawRoundedRect(QRectF(6, 6, 52, 52), 12, 12)
    _pen(painter, NEUTRAL, 3.2)
    path = QPainterPath()
    path.moveTo(18, 44)
    path.lineTo(18, 22)
    path.lineTo(26, 34)
    path.lineTo(34, 22)
    path.lineTo(34, 44)
    painter.drawPath(path)
    painter.end()
    return QIcon(pixmap)
