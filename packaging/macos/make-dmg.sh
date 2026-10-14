#!/bin/sh
# dist/HyperTeX.app → dist/HyperTeX-<버전>-macos-<아키텍처>.dmg  (macOS 의 hdiutil)
# 사용: packaging/macos/make-dmg.sh [앱 경로] [출력 파일]
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
APP=${1:-"$ROOT/dist/HyperTeX.app"}
VERSION=$(cd "$ROOT" && python3 -c "import htex; print(htex.__version__)")
OUT=${2:-"$ROOT/dist/HyperTeX-$VERSION-macos-$(uname -m).dmg"}
[ -d "$APP" ] || { echo "앱이 없습니다: $APP" >&2; exit 1; }
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f "$OUT"
hdiutil create -volname "HyperTeX" -srcfolder "$STAGE" -ov -format UDZO -fs HFS+ "$OUT"
echo "DMG: $OUT"
