#!/bin/sh
# HyperTeX.app 서명(Developer ID, hardened runtime) → (선택) DMG 서명 → 공증 → 스테이플.
#
# 사용: packaging/macos/sign-and-notarize.sh sign   dist/HyperTeX.app
#       packaging/macos/sign-and-notarize.sh notarize dist/HyperTeX-….dmg
#
# 환경 변수
#   서명:  MACOS_SIGN_IDENTITY   예: "Developer ID Application: 이름 (TEAMID)"  (키체인에 인증서가 있어야 함)
#   공증:  APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PASSWORD (appleid.apple.com 의 앱 암호)
#          또는 NOTARY_PROFILE (xcrun notarytool store-credentials 로 저장한 프로필 이름)
#
# 순서가 중요하다: 안쪽(프레임워크 안의 dylib, QtWebEngineProcess.app)부터 서명하고 마지막에 .app.
# --deep 은 쓰지 않는다(Apple 권장 아님, entitlements 를 안쪽 실행 파일에 제대로 못 준다).
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ENT="$HERE/entitlements.plist"
cmd=${1:?sign 또는 notarize}
target=${2:?대상 경로}

sign_one() {
    codesign --force --timestamp --options runtime --entitlements "$ENT" \
        --sign "$MACOS_SIGN_IDENTITY" "$1"
}

case "$cmd" in
sign)
    : "${MACOS_SIGN_IDENTITY:?MACOS_SIGN_IDENTITY 필요}"
    # 1) 모든 Mach-O 파일 (dylib, so, 실행 파일) — 깊은 것부터
    find "$target/Contents" -type f \( -name "*.dylib" -o -name "*.so" -o -perm -u+x \) -print0 |
        xargs -0 file | grep "Mach-O" | cut -d: -f1 | awk '{ print length, $0 }' | sort -rn | cut -d' ' -f2- |
        while IFS= read -r f; do sign_one "$f"; done
    # 2) 안쪽 번들(.app: QtWebEngineProcess.app, .framework) — 깊은 것부터
    find "$target/Contents" -depth \( -name "*.app" -o -name "*.framework" \) -type d |
        while IFS= read -r b; do sign_one "$b"; done
    # 3) 바깥 .app
    sign_one "$target"
    codesign --verify --deep --strict --verbose=2 "$target"
    spctl --assess --type execute --verbose "$target" || echo "(공증 전에는 spctl 이 거부할 수 있다)"
    ;;
notarize)
    if [ "${target##*.}" = dmg ] && [ -n "${MACOS_SIGN_IDENTITY:-}" ]; then
        codesign --force --timestamp --sign "$MACOS_SIGN_IDENTITY" "$target"
    fi
    if [ -n "${NOTARY_PROFILE:-}" ]; then
        xcrun notarytool submit "$target" --keychain-profile "$NOTARY_PROFILE" --wait
    else
        : "${APPLE_ID:?}" "${APPLE_TEAM_ID:?}" "${APPLE_APP_PASSWORD:?}"
        xcrun notarytool submit "$target" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" \
            --password "$APPLE_APP_PASSWORD" --wait
    fi
    xcrun stapler staple "$target"
    ;;
*) echo "알 수 없는 명령: $cmd" >&2; exit 2 ;;
esac
