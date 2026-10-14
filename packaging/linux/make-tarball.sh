#!/bin/sh
# 릴리스용 tar.gz: 번들 + 사용자 단위 설치 스크립트 + .desktop·MIME·아이콘.
#   HyperTeX-<버전>-linux-<아키텍처>/
#     htex-viewer/        PyInstaller 결과 (htex-viewer 실행 파일)
#     install.sh          ~/.local 에 설치하고 .htex·htex:// 연결 (--uninstall 로 제거)
#     org.hypertex.viewer.desktop, hypertex-mime.xml, icons/
# 사용: packaging/linux/make-tarball.sh [번들 폴더] [출력 폴더]
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
SRC=${1:-"$ROOT/dist/htex-viewer"}
OUTDIR=${2:-"$ROOT/dist"}
VERSION=$(cd "$ROOT" && python3 -c "import htex; print(htex.__version__)")
NAME="HyperTeX-$VERSION-linux-$(uname -m)"
[ -x "$SRC/htex-viewer" ] || { echo "실행 파일이 없습니다: $SRC/htex-viewer" >&2; exit 1; }
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/$NAME/icons"
cp -a "$SRC" "$WORK/$NAME/htex-viewer"
cp "$HERE/install.sh" "$HERE/org.hypertex.viewer.desktop" "$HERE/hypertex-mime.xml" "$WORK/$NAME/"
cp -a "$ROOT/packaging/icons/png" "$ROOT/packaging/icons/htex.svg" "$WORK/$NAME/icons/"
mkdir -p "$OUTDIR"
tar -C "$WORK" -czf "$OUTDIR/$NAME.tar.gz" "$NAME"
echo "tar.gz: $OUTDIR/$NAME.tar.gz ($(du -h "$OUTDIR/$NAME.tar.gz" | cut -f1))"
