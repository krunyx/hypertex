"""packaging/icons/htex.svg → PNG(여러 크기), htex.ico, htex.icns.

사용: python packaging/icons/make_icons.py [--out 폴더]
필요: PySide6(QtSvg, SVG 래스터화)와 Pillow(.ico·.icns 쓰기). 둘 다 빌드용 도구다.
macOS 에서 iconutil 이 있으면 .icns 는 iconutil 로 만들고, 없으면 Pillow 로 만든다.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "htex.svg"
PNG_SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def render_png(svg: Path, size: int, dest: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    _app = QGuiApplication.instance() or QGuiApplication([sys.argv[0]])  # noqa: F841
    r = QSvgRenderer(str(svg))
    if not r.isValid():
        raise SystemExit(f"SVG 를 읽을 수 없음: {svg}")
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    if not img.save(str(dest), "PNG"):
        raise SystemExit(f"PNG 저장 실패: {dest}")


def make_icns(out: Path, pngs: dict[int, Path]) -> None:
    dest = out / "htex.icns"
    if sys.platform == "darwin" and shutil.which("iconutil"):
        with tempfile.TemporaryDirectory() as td:
            iset = Path(td) / "htex.iconset"
            iset.mkdir()
            for base in (16, 32, 128, 256, 512):
                shutil.copy(pngs[base], iset / f"icon_{base}x{base}.png")
                shutil.copy(pngs[base * 2], iset / f"icon_{base}x{base}@2x.png")
            subprocess.run(["iconutil", "-c", "icns", str(iset), "-o", str(dest)], check=True)
        return
    from PIL import Image
    Image.open(pngs[1024]).save(dest, format="ICNS")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=HERE)
    ap.add_argument("--svg", type=Path, default=SRC)
    a = ap.parse_args(argv)
    out = a.out
    (out / "png").mkdir(parents=True, exist_ok=True)
    pngs: dict[int, Path] = {}
    for s in PNG_SIZES:
        pngs[s] = out / "png" / f"htex-{s}.png"
        render_png(a.svg, s, pngs[s])
    from PIL import Image
    big = Image.open(pngs[256])
    big.save(out / "htex.ico", format="ICO", sizes=[(s, s) for s in ICO_SIZES],
             append_images=[Image.open(pngs[s]) for s in ICO_SIZES if s != 256])
    make_icns(out, pngs)
    shutil.copy(pngs[256], out / "htex.png")      # 리눅스 .desktop·창 아이콘용 기본 크기
    print(f"아이콘: {out}/png/htex-*.png, htex.png, htex.ico, htex.icns")
    return 0


if __name__ == "__main__":
    sys.exit(main())
