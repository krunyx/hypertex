# F (전용 뷰어) 질문과 임시 가정

## 1. 로컬 문서의 주소와 접근 범위 (명세 7절 "파일 시스템 직접 접근 불가", 8절 전용 뷰어)
- 문제: 명세에 로컬 파일을 열 때 어디까지 읽어도 되는지, 웹 엔진 안에서 어떤 주소로 보일지가 없다.
- 임시 가정: 사용자가 직접 연 파일의 폴더를 "뿌리"로 등록하고 `htexapp://doc-<뿌리키>/<상대경로>` 로 보인다.
  뿌리마다 출처가 달라 `../` 나 다른 뿌리로 나갈 수 없고(심볼릭 링크도 resolve 후 검사), 웹 페이지(http/https)나
  원격 문서(htex:)에서 시작된 요청은 로컬 주소에 닿지 못한다. 주소 표시줄에는 실제 파일 경로를 보인다.
- 제안: 명세 8절에 "로컬 문서는 연 파일의 폴더 아래만" 을 적는다.

## 2. 원격 문서가 쓰는 파서 기준 폴더
- 문제: `parse_text(base_dir=…)` 의 Loader 는 상대 주소를 로컬에서 읽는다. 원격 문서를 현재 폴더 기준으로 해석하면
  `\usemacros{AGENTS.md}` 처럼 사용자 컴퓨터 파일을 읽게 된다.
- 임시 가정: 원격 문서는 빈 임시 폴더를 기준으로 파싱한다(→ missing-resource 진단). 원격 문서의 `\usemacros` ·
  `\usestyle` 를 HTTPS 로 가져오는 일은 아직 하지 않는다.
- 제안: Loader 에 "가져오기 함수"를 주입하는 훅(C 담당)을 두면 뷰어가 같은 출처 HTTPS 로 채워 줄 수 있다.

## 3. \transclude 를 어디서 채우나
- 문제: 렌더러는 전사를 링크 자리 표시로 낸다(E). 명세 5절은 "이 자리에 표시".
- 임시 가정: 뷰어가 HTML 을 만든 뒤 자리 표시(`div.htex-transclusion[data-href]`)를 조각(G 의 render_fragment)으로 바꾼다.
  한 단계만(조각 안의 전사는 링크 그대로), 문서당 20개, 가져오기 포함 3초 예산. 실패하면 링크를 남기고
  `htex-transclusion-failed` 클래스. 원격 문서는 원격 대상만, 로컬 문서는 같은 뿌리나 원격만.
- 제안: 웹 서버(G)도 같은 처리를 하도록 규약에 "호스트가 전사를 채운다" 를 추가.

## 4. 렌더링 시간 상한 2초의 범위
- 문제: "문서당 2초" 가 파싱만인지, HTML 변환·가져오기·전사까지인지 불명확.
- 임시 가정: 파싱 2초, HTML 변환 2초를 각각(스레드에서 돌리고 넘으면 결과를 버리고 오류 페이지).
  가져오기는 별도 시간 제한(10초), 전사는 3초 예산. 파이썬 스레드는 죽일 수 없어 넘은 작업은 뒤에서 끝까지 돈다
  (파서는 반드시 끝난다는 원칙 2에 기댄다). 통합 단계에서 프로세스 분리를 검토할 만하다.

## 5. htex:// 응답이 HTML 이면
- 임시 가정: 가져온 내용 형식이 text/html 이면 HyperTeX 문서가 아니라고 보고 같은 https 주소의 일반 웹 페이지로
  넘긴다(302). 그 밖의 형식(text/plain, text/x-hypertex, 없음)은 HyperTeX 로 해석한다.
- 제안: 명세 2절에 서버가 `text/x-hypertex` 를 내야 함을, 뷰어가 다른 형식을 어떻게 다룰지를 적는다.

## 6. 캐시
- 원격 문서만 디스크 캐시(플랫폼 캐시 폴더/trees, 키 = 구현 버전 + 주소 + 내용 sha256). 원문은 메모리에 5분.
  로컬 문서는 메모리만(내용 해시로는 `\usemacros` 등 의존 파일 변경을 알 수 없다. G 질문 4와 같은 문제).
  새로고침(Ctrl/Cmd+R)은 원문을 다시 가져오고 다시 해석한다.
- 캐시 폴더: macOS `~/Library/Caches/HyperTeX`, Windows `%LOCALAPPDATA%\HyperTeX\Cache`, 그 밖 `$XDG_CACHE_HOME/hypertex`.
  웹 엔진 캐시는 그 아래 `web/`.

## 7. 조각 주소 doc 값과 상태 코드 (G 질문 1·3과 맞춤)
- 뷰어는 doc 를 조각 주소의 문서(키) 기준으로 해석한다: 상대 주소, `htex://…`, `htexapp://doc-…`(같은 뿌리), `https://….htex`
  모두 받는다. doc 에 `#라벨` 이 붙어 와도 label 이 비면 그것을 쓴다.
- 그림 주소: 문서·노드 없음 404, 렌더러가 None 422(H stub 이면 항상 422), 값 형식 오류 400. G 서버와 같다.
- 내부 주소(htexapp://picture·fragment·asset)는 웹 페이지 출처에서 쓸 수 없다(403). 응답에
  `Access-Control-Allow-Origin: <요청 출처>` 를 붙인다(htex: 문서 → htexapp: 주소 fetch 가 교차 출처이므로).

## 8. 보안 정리
- 문서 페이지: `Content-Security-Policy` 헤더와 meta 둘 다(`script-src htexapp:` → interact.js 만 실행, 인라인 스크립트 불가,
  `connect-src htexapp:`, `img-src htexapp: htex: https: blob:`, `style-src 'unsafe-inline'`(렌더러가 CSS 인라인, G 질문 7)).
- 가져오기: https 만(리다이렉트도), 5MB, 10초, 사용자 에이전트 `HyperTeX-Viewer/<버전>`. urllib 의 build_opener 는
  file:/ftp:/data:/http: 처리기를 넣으므로 쓰지 않고 HTTPS 처리기만 넣은 opener 를 직접 만든다.
- 탐색: http(s) 의 .htex/.tex 링크는 가로채 htex:// 로(http 는 거부), file: 탐색 금지, 웹 페이지 → htexapp: 탐색 금지,
  새 창 열기 금지. 일반 웹 페이지는 QtWebEngine 의 보통 동작 그대로.

## 9. 패키징 주의점 (다음 단계, PyInstaller 등)
- **스킴 등록 순서**: `QWebEngineUrlScheme.registerScheme` 은 QApplication 생성 전에 해야 한다(`htex.viewer.app.register_schemes`).
  진입점에서 다른 모듈이 먼저 QApplication 을 만들지 않게.
- **QtWebEngineProcess**: 렌더러는 별도 실행 파일(QtWebEngineProcess, macOS 는 `QtWebEngineCore.framework/Helpers/QtWebEngineProcess.app`)이다.
  PyInstaller 의 PySide6 훅이 넣지만 `resources/`(icudtl.dat, qtwebengine_resources*.pak)와 `translations/qtwebengine_locales/`
  를 함께 넣었는지 확인. 빠지면 빈 창이나 즉시 종료.
- **샌드박스**: 리눅스 컨테이너·일부 배포판에서는 `--no-sandbox` 가 필요할 수 있다(이 작업 공간). 배포판에서는 샌드박스를 켜 두고,
  macOS 는 서명·공증(hardened runtime + `com.apple.security.cs.allow-jit` 등 QtWebEngine 이 요구하는 entitlement).
- **OS 에 htex:// 등록**: 브라우저·메일에서 htex:// 링크를 누르면 뷰어가 열리게 하려면 macOS Info.plist `CFBundleURLTypes`,
  Windows 레지스트리 `HKCU\Software\Classes\htex`, 리눅스 .desktop `MimeType=x-scheme-handler/htex;text/x-hypertex;`.
  .htex 파일 연결도 같이. 이미 떠 있는 뷰어로 넘기려면 단일 인스턴스(QLocalServer) 처리 필요(아직 없음).
- **데이터 파일**: `htex/web/interact.js` 를 패키지 데이터로 넣어야 한다(없으면 뷰어는 빈 스크립트를 내고 상호작용만 빠진다).
- 캐시·프로필 폴더는 사용자 폴더에 만들므로 앱 번들 안에 쓰지 않는다.

## 10. 아직 안 한 것
- 탭, 찾기(Ctrl+F), 확대/축소, 인쇄, 다크 모드 선택(`<html data-theme>`), 단일 인스턴스, 로컬 파일 변경 자동 새로고침.
- 원격 문서의 `\includegraphics` 상대 주소는 htex:// 로 요청되어 뷰어가 https 로 가져온다(이미지 확장자만). 로컬은 같은 뿌리 안만.
