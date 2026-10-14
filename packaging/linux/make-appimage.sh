#!/bin/sh
# PyInstaller 결과(dist/htex-viewer)로 AppImage 를 만든다.
#
# 사용: packaging/linux/make-appimage.sh [번들 폴더] [출력 파일]
#   기본: dist/htex-viewer → dist/HyperTeX-<버전>-<아키텍처>.AppImage
# appimagetool 이 PATH 에 없으면 packaging/.tools/ 에 내려받는다 (APPIMAGETOOL=경로 로 지정 가능).
# FUSE 가 없는 환경(컨테이너, CI)에서도 돌도록 appimagetool 을 --appimage-extract-and-run 으로 실행한다.
#
# AppImage 는 .desktop·MIME 을 스스로 등록하지 않는다. 등록하려면 AppImageLauncher 같은 도구를 쓰거나
# install.sh 처럼 .desktop 의 Exec 를 AppImage 경로로 바꿔 넣는다:
#   HTEX_EXEC=~/Applications/HyperTeX.AppImage packaging/linux/install.sh --exec
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
SRC=${1:-"$ROOT/dist/htex-viewer"}
ARCH=${ARCH:-$(uname -m)}
VERSION=$(cd "$ROOT" && python3 -c "import htex; print(htex.__version__)" 2>/dev/null || echo 0)
OUT=${2:-"$ROOT/dist/HyperTeX-$VERSION-$ARCH.AppImage"}
[ -x "$SRC/htex-viewer" ] || { echo "실행 파일이 없습니다: $SRC/htex-viewer (먼저 pyinstaller)" >&2; exit 1; }

TOOL=${APPIMAGETOOL:-$(command -v appimagetool || true)}
if [ -z "$TOOL" ]; then
    TOOL="$ROOT/packaging/.tools/appimagetool-$ARCH.AppImage"
    if [ ! -x "$TOOL" ]; then
        mkdir -p "$(dirname "$TOOL")"
        URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"
        echo "appimagetool 내려받기: $URL"
        curl -fsSL -o "$TOOL.part" "$URL"
        chmod +x "$TOOL.part"; mv "$TOOL.part" "$TOOL"
    fi
fi

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
APPDIR="$WORK/HyperTeX.AppDir"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/mime/packages" "$APPDIR/usr/share/metainfo"
cp -a "$SRC" "$APPDIR/usr/lib/hypertex"
ln -s ../lib/hypertex/htex-viewer "$APPDIR/usr/bin/htex-viewer"

sed -e 's|^Exec=.*|Exec=htex-viewer %U|' -e '/^TryExec=/d' \
    "$HERE/org.hypertex.viewer.desktop" > "$APPDIR/usr/share/applications/org.hypertex.viewer.desktop"
cp "$APPDIR/usr/share/applications/org.hypertex.viewer.desktop" "$APPDIR/org.hypertex.viewer.desktop"
cp "$HERE/hypertex-mime.xml" "$APPDIR/usr/share/mime/packages/"
for s in 16 32 48 64 128 256 512; do
    d="$APPDIR/usr/share/icons/hicolor/${s}x${s}/apps"; mkdir -p "$d"
    cp "$ROOT/packaging/icons/png/htex-$s.png" "$d/org.hypertex.viewer.png"
done
cp "$ROOT/packaging/icons/png/htex-256.png" "$APPDIR/org.hypertex.viewer.png"
ln -s org.hypertex.viewer.png "$APPDIR/.DirIcon"

cat > "$APPDIR/AppRun" <<'RUN'
#!/bin/sh
# AppImage 진입점. 사용자 네임스페이스가 막힌 시스템(일부 배포판·컨테이너)에서 Chromium 샌드박스가
# 실패하면 HTEX_NO_SANDBOX=1 로 실행한다.
HERE=$(dirname "$(readlink -f "$0")")
exec "$HERE/usr/lib/hypertex/htex-viewer" "$@"
RUN
chmod +x "$APPDIR/AppRun"

mkdir -p "$(dirname "$OUT")"
ARCH=$ARCH "$TOOL" --appimage-extract-and-run --no-appstream "$APPDIR" "$OUT"
echo "AppImage: $OUT ($(du -h "$OUT" | cut -f1))"
