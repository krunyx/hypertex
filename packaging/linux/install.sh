#!/bin/sh
# HyperTeX 뷰어를 사용자 단위(~/.local)로 설치하고 .htex 와 htex:// 를 이 뷰어에 연결한다.
# 관리자 권한이 필요 없다.
#
# 사용:
#   packaging/linux/install.sh [번들 폴더]          # PyInstaller 결과 dist/htex-viewer (또는 tar.gz 를 푼 폴더)
#   packaging/linux/install.sh --pip                 # pip 로 설치한 htex-viewer 명령을 그대로 쓸 때 (등록만)
#   HTEX_EXEC=~/Applications/HyperTeX.AppImage packaging/linux/install.sh --exec   # 임의 실행 파일(AppImage) 등록만
#   packaging/linux/install.sh --uninstall
#
# 환경 변수: PREFIX (기본 ~/.local), XDG_DATA_HOME (기본 $PREFIX/share)
#            HTEX_SET_DEFAULT=0 이면 기본 앱 지정(xdg-mime default)을 하지 않는다.
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PREFIX=${PREFIX:-"$HOME/.local"}
DATA=${XDG_DATA_HOME:-"$PREFIX/share"}
BIN="$PREFIX/bin"
APPDIR="$PREFIX/lib/hypertex"
DESKTOP_ID=org.hypertex.viewer.desktop
ICONS_SRC="$HERE/../icons/png"

have() { command -v "$1" >/dev/null 2>&1; }

refresh() {
    if have update-mime-database; then
        # 검색 경로 밖이라는 안내는 버리고, XML 오류는 보이게 한다
        update-mime-database "$DATA/mime" 2>&1 | grep -i "error" >&2 || true
    else
        echo "  참고: update-mime-database 가 없어 MIME 데이터베이스를 갱신하지 못했습니다 (shared-mime-info 패키지)." >&2
    fi
    if have update-desktop-database; then
        update-desktop-database "$DATA/applications" >/dev/null 2>&1 || true
    else
        echo "  참고: update-desktop-database 가 없습니다 (desktop-file-utils 패키지). 대부분의 데스크톱은 없어도 동작합니다." >&2
    fi
    if have gtk-update-icon-cache; then gtk-update-icon-cache -q -t "$DATA/icons/hicolor" >/dev/null 2>&1 || true; fi
}

uninstall() {
    rm -f "$DATA/applications/$DESKTOP_ID" "$DATA/mime/packages/hypertex-mime.xml"
    for s in 16 24 32 48 64 128 256 512; do
        rm -f "$DATA/icons/hicolor/${s}x${s}/apps/org.hypertex.viewer.png"
    done
    rm -f "$DATA/icons/hicolor/scalable/apps/org.hypertex.viewer.svg"
    if [ -L "$BIN/htex-viewer" ] && [ "$(readlink "$BIN/htex-viewer")" = "$APPDIR/htex-viewer" ]; then
        rm -f "$BIN/htex-viewer"
    fi
    rm -rf "$APPDIR"
    # mimeapps.list 의 기본 앱 지정 정리
    for f in "${XDG_CONFIG_HOME:-$HOME/.config}/mimeapps.list" "$DATA/applications/mimeapps.list"; do
        [ -f "$f" ] && sed -i "/=$DESKTOP_ID;\?\$/d" "$f" || true
    done
    refresh
    echo "HyperTeX 뷰어를 지웠습니다."
}

MODE=bundle
SRC=""
case "${1:-}" in
    --uninstall) uninstall; exit 0 ;;
    --pip) MODE=pip ;;
    --exec) MODE=exec ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    "") SRC="$HERE/../../dist/htex-viewer" ;;
    *) SRC=$1 ;;
esac

mkdir -p "$BIN" "$DATA/applications" "$DATA/mime/packages"

if [ "$MODE" = bundle ]; then
    [ -x "$SRC/htex-viewer" ] || { echo "실행 파일이 없습니다: $SRC/htex-viewer" >&2; exit 1; }
    SRC=$(CDPATH= cd -- "$SRC" && pwd)
    if [ "$SRC" != "$APPDIR" ]; then
        rm -rf "$APPDIR"; mkdir -p "$(dirname "$APPDIR")"
        cp -a "$SRC" "$APPDIR"
    fi
    ln -sf "$APPDIR/htex-viewer" "$BIN/htex-viewer"
    EXEC="$APPDIR/htex-viewer"
elif [ "$MODE" = exec ]; then
    EXEC=${HTEX_EXEC:?HTEX_EXEC=실행 파일 경로 를 지정하세요}
    [ -x "$EXEC" ] || { echo "실행할 수 없는 파일: $EXEC" >&2; exit 1; }
    EXEC=$(CDPATH= cd -- "$(dirname -- "$EXEC")" && pwd)/$(basename -- "$EXEC")
else
    EXEC=$(command -v htex-viewer || true)
    [ -n "$EXEC" ] || { echo "htex-viewer 명령이 없습니다. 먼저: pip install --user 'htex[viewer]'" >&2; exit 1; }
fi

# .desktop: Exec 를 절대 경로로 (PATH 에 ~/.local/bin 이 없는 세션에서도 열리게)
sed -e "s|^Exec=.*|Exec=\"$EXEC\" %U|" -e "s|^TryExec=.*|TryExec=$EXEC|" \
    "$HERE/$DESKTOP_ID" > "$DATA/applications/$DESKTOP_ID"
cp "$HERE/hypertex-mime.xml" "$DATA/mime/packages/hypertex-mime.xml"

for s in 16 24 32 48 64 128 256 512; do
    if [ -f "$ICONS_SRC/htex-$s.png" ]; then
        mkdir -p "$DATA/icons/hicolor/${s}x${s}/apps"
        cp "$ICONS_SRC/htex-$s.png" "$DATA/icons/hicolor/${s}x${s}/apps/org.hypertex.viewer.png"
    fi
done
if [ -f "$HERE/../icons/htex.svg" ]; then
    mkdir -p "$DATA/icons/hicolor/scalable/apps"
    cp "$HERE/../icons/htex.svg" "$DATA/icons/hicolor/scalable/apps/org.hypertex.viewer.svg"
fi

refresh

if [ "${HTEX_SET_DEFAULT:-1}" = 1 ] && have xdg-mime; then
    xdg-mime default "$DESKTOP_ID" text/x-hypertex x-scheme-handler/htex || true
fi

echo "설치: $EXEC"
echo "  .desktop  $DATA/applications/$DESKTOP_ID"
echo "  MIME      $DATA/mime/packages/hypertex-mime.xml (text/x-hypertex, *.htex)"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "  참고: $BIN 이 PATH 에 없습니다." ;; esac
