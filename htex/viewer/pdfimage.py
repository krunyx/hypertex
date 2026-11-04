"""PDF 그림 → PNG (뷰어 전용, QtPdf). pdflatex 원고의 \\includegraphics{fig.pdf} 를 보여 주려고.

첫 쪽만 그린다 (그림 PDF 는 거의 한 쪽). 화면에서 또렷하도록 2배 해상도로 그리되 긴 변은 MAX_SIDE 이하.
투명한 배경은 흰색으로 채운다 (논문 그림은 흰 종이를 가정하고 그려진다 — 어두운 테마에서도 읽히게).
<img> 에는 SVG 로 감싸서 내준다: 원래 크기(pt → CSS px)를 지니면서 안의 PNG 는 2배 해상도라 또렷하다.
결과는 (내용 해시)로 작은 LRU 에 담아 둔다. 스레드 안전 (뷰어 처리기는 작업 스레드에서 부른다).
"""
from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict

SCALE = 2.0
MAX_SIDE = 3000
_CACHE: "OrderedDict[str, bytes]" = OrderedDict()
_CACHE_MAX = 32
_LOCK = threading.Lock()
_RENDER_LOCK = threading.Lock()      # pdfium 은 한 번에 하나씩


class PdfImageError(Exception):
    pass


def available() -> bool:
    try:
        from PySide6.QtPdf import QPdfDocument  # noqa: F401
        return True
    except Exception:   # noqa: BLE001
        return False


def render_svg(data: bytes, page: int = 0) -> bytes:
    """PDF 바이트 → <img> 용 SVG (2배 해상도 PNG 를 품고, 크기는 원래 쪽 크기). 못 그리면 PdfImageError."""
    import base64
    png, (w_pt, h_pt) = render_png(data, page, with_size=True)
    w, h = w_pt * 96 / 72, h_pt * 96 / 72          # pt → CSS px
    b64 = base64.b64encode(png).decode("ascii")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.2f}" height="{h:.2f}" '
            f'viewBox="0 0 {w:.2f} {h:.2f}"><image width="{w:.2f}" height="{h:.2f}" '
            f'href="data:image/png;base64,{b64}"/></svg>').encode("ascii")


def render_png(data: bytes, page: int = 0, with_size: bool = False):
    """PDF 바이트 → PNG 바이트 (with_size 면 (PNG, (폭 pt, 높이 pt))). 못 그리면 PdfImageError."""
    key = hashlib.sha256(data).hexdigest() + f":{page}"
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None:
            _CACHE.move_to_end(key)
            return hit if with_size else hit[0]
    got = _render(data, page)
    with _LOCK:
        _CACHE[key] = got
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return got if with_size else got[0]


def _render(data: bytes, page: int) -> "tuple[bytes, tuple[float, float]]":
    try:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize
        from PySide6.QtGui import QColor, QImage, QPainter
        from PySide6.QtPdf import QPdfDocument
    except Exception as e:   # noqa: BLE001
        raise PdfImageError("PDF 그림을 그릴 모듈(QtPdf)이 없습니다.") from e
    with _RENDER_LOCK:
        buf = QBuffer()
        buf.setData(QByteArray(data))
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        doc = QPdfDocument()
        doc.load(buf)
        if doc.status() != QPdfDocument.Status.Ready or doc.pageCount() <= page:
            err = doc.error()
            doc.close()
            raise PdfImageError(f"PDF 를 열 수 없습니다 ({getattr(err, 'name', err)}).")
        pts = doc.pagePointSize(page)          # 1pt = 1/72 in, CSS px 와 거의 같다
        w, h = max(1.0, pts.width()), max(1.0, pts.height())
        scale = min(SCALE, MAX_SIDE / max(w, h))
        size = QSize(max(1, round(w * scale)), max(1, round(h * scale)))
        img = doc.render(page, size)
        doc.close()
        if img.isNull():
            raise PdfImageError("PDF 를 그리지 못했습니다.")
        out = QImage(img.size(), QImage.Format.Format_RGB32)
        out.fill(QColor("white"))
        p = QPainter(out)
        p.drawImage(0, 0, img)
        p.end()
        ba = QByteArray()
        ob = QBuffer(ba)
        ob.open(QIODevice.OpenModeFlag.WriteOnly)
        if not out.save(ob, "PNG"):
            raise PdfImageError("PNG 로 저장하지 못했습니다.")
        ob.close()
        return bytes(ba.data()), (w, h)

