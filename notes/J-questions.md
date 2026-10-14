# J (뷰어 다듬기) 질문과 임시 가정

형식: 어디 / 무엇이 문제 / 제안 / 임시 가정

## 1. 다른 문서 참조 번호를 어디서 채우나
- 어디: schema `link.resolved` 설명("다른 문서는 뷰어가 가져와 채운다"), 명세 5절.
- 문제: 누가 언제 채우는지(파서? 호스트?), 시간 예산, 실패 시 표시가 정해져 있지 않다.
- 제안: 명세 5절에 "호스트가 대상 문서의 labels[라벨].number 로 채운다. 문서당 다른 문서 20개, 1초. 실패하면 라벨 이름" 을 적는다.
- 임시 가정: `htex/linkres.py` 의 `resolve_cross_refs(tree, loader)` 순수 함수. 대상 문서는 labels 만 읽고 그 안의 참조는
  따라가지 않는다(순환도 한 단계). 렌더러(E)는 이미 `resolved.number` 를 쓴다(`htex/html/render.py` ref()): `\ref` 는 `1`,
  `\eqref` 는 `(1)`. 렌더러 쪽 수정이나 HTML 후처리는 필요 없었다.
  - 뷰어(core.page_html): 로컬 문서는 같은 뿌리 안의 로컬 문서와 **이미 가져온** 원격 문서만(로컬 문서를 열었다고
    네트워크에 나가지 않는다: 기존 F 테스트가 "요청은 그 서버로만" 을 본다). 원격 문서는 같은 규칙(원격→원격만)으로 가져온다
    (core 의 캐시·5MB·https 규칙 그대로). 네트워크 실패는 조용히.
  - 웹 서버(`htex serve`)·정적 빌드(`htex build`): 루트 안의 상대 주소 문서만(`linkres.local_doc_for_link`: `..` 탈출, 심볼릭 링크,
    숨김 파일, 문서 아닌 파일 거부). htex:// · https:// 는 서버가 가져오지 않는다(SSRF 방지, G 의 조각 주소와 같은 방침).
  - 주의(G 질문 4와 같은 문제): 웹 서버 캐시는 문서 자신의 수정 시각만 보므로 **대상 문서**가 바뀌어도 번호가 갱신되지 않는다
    (가리키는 문서를 저장하면 갱신). 통합 단계에서 DocCache 키에 의존 문서를 넣는 것을 검토.

## 2. 찾기와 MathML
- 문제: `QWebEnginePage.findText` 는 Chromium 찾기라 MathML(`<math>`) 안의 글자(예: 수식 안 한글, `H`)는 대개 걸리지 않는다.
- 제안: 필요하면 수식의 `alttext`/주석(TeX 원문)으로 찾는 보조 찾기를 interact.js 쪽(G)에 둔다.
- 임시 가정: 본문 글자만 찾는다(과제 허용 범위). 일치 개수도 Chromium 이 센 것.

## 3. 테마
- `<html data-theme>`: core.theme 이 light/dark 면 서버 응답(문서·오류·원문 페이지)에 넣고, 이미 열린 탭은 JS 로 속성만 바꾼다
  (다시 그리지 않음, 슬라이더 값 유지). 시스템이면 속성 없음. QSettings("HyperTeX", "Viewer") 의 `view/theme`.
- 창 테두리: Qt 6.8+ `styleHints().setColorScheme`. 플랫폼 스타일이 따르지 않으면(리눅스 일부, offscreen) Fusion 다크 팔레트로 맞춘다.
- 일반 웹 페이지(http/https)에는 data-theme 을 넣지 않는다(그 사이트 CSS 를 모른다).

## 4. 로컬 자동 새로고침의 범위
- 문제: 파서가 읽은 로컬 파일 목록을 트리에 남기지 않는다(G 질문 4, F 질문 6).
- 제안: 파서(C)가 `source.dependencies`(읽은 로컬 파일 목록)를 남긴다. 그러면 정규식 추정을 없앨 수 있다.
- 임시 가정: `viewer/instance.local_dependencies` 가 원문을 정규식으로 훑어 `\usemacros`(.htex), `\usestyle`(.hsty),
  `\input`/`\include`(.tex), `\bibliography`(.bbl), 다른 로컬 문서 `\ref{x.htex#…}`·`\transclude{x.htex#…}` 를 같은 폴더(아래) 안에서
  찾는다. 한 단계(입력 파일 안의 `\input` 은 모름), 매크로로 만든 이름은 모름. 바뀌면 300ms 묶어 다시 해석하고
  스크롤(`scrollX/Y`)과 슬라이더 값(`HTEX.getParams` → `HTEX.setParam`)을 되살린다.
  편집기의 "새 파일에 쓰고 이름 바꾸기" 저장도 잡도록 폴더도 감시한다. 원격 문서는 감시하지 않는다(새로고침 Ctrl+R).

## 5. 단일 인스턴스
- 서버 이름: `instance.instance_name()` = `hypertex-viewer-` + sha256(사용자 이름 + 홈 폴더)[:16]. 환경 변수
  `HTEX_VIEWER_INSTANCE` 로 바꿀 수 있다(테스트·여러 프로필). `HTEX_VIEWER_SINGLE=0` 이면 끈다.
  QLocalServer 의 `UserAccessOption`(유닉스 소켓 권한 0700 상당).
- 메시지: UTF-8 JSON 한 줄 `{"v":1,"cmd":"open","targets":[…],"cwd":"…"}` + `\n`, 답 `ok\n`. 보내는 쪽이 대상을 이미
  절대 경로로 바꿔 보낸다(`normalize_target`: file: URL → 경로, 상대 경로 → 보내는 쪽 현재 폴더 기준, 주소는 그대로).
- 알려진 한계: (a) 윈도에서 파일 여러 개를 한꺼번에 열면 프로세스가 동시에 여러 개 뜬다. 거의 동시에 뜬 둘이 모두
  "떠 있는 뷰어 없음" 으로 보고 둘 다 창을 띄울 수 있다(짧은 경쟁 구간). 필요하면 잠금 파일(QLockFile)로 첫 실행만 서버가 되게.
  (b) 유닉스에서 listen 이 실패하면 남은 소켓 파일로 보고 지운 뒤 다시 듣는다(앞선 실행이 비정상 종료한 경우).
- 제안: `htex/__main__.py` 의 `_call_run` 은 이제 `run(targets)` 한 줄로 정리할 수 있다(I 담당이라 고치지 않음).
  `run` 의 첫 매개변수 이름은 `targets` (test_I_entry 가 서명을 본다), str 하나도 받는다.

## 6. macOS 파일 열기 이벤트 (QFileOpenEvent)
- 처리: `run()` 이 만드는 `HtexApplication(QApplication)` 의 `event()` 가 FileOpen 을 받아 `file()`(Finder) 또는
  `url()`(htex:// 등 CFBundleURLTypes) → 새 탭. 창이 생기기 전에 온 것은 모아 두었다가 첫 대상들과 함께 연다.
- 문제: 처음엔 `app.installEventFilter(파이썬 객체)` 로 했는데, 앱 전체 이벤트 필터는 QtWebEngine 내부 이벤트까지 모두
  파이썬을 거쳐 PySide6 6.12 + offscreen 에서 `app.exec()` 중 segfault 가 났다. 그래서 QApplication 하위 클래스의 event() 로 바꿨다.
  (이미 다른 곳에서 QApplication 을 만든 경우에만 macOS 에서 필터로 대신한다.)
- 확인하지 못한 것: 실제 macOS 에서 Apple 이벤트 전달(이 작업 공간은 리눅스). 이벤트 객체를 직접 보내는 테스트만 했다.

## 7. 원문 보기
- `htexapp://source/<문서키>`: 원문을 escape 한 `<pre>`, 줄 번호, CSP `default-src 'none'`(스크립트 불가), 읽기 전용.
  웹 페이지 출처에서는 403. 주소 표시줄에는 `원문: <파일 경로>`.

## 8. 렌더 프로세스 종료 (I 제안)
- `renderProcessTerminated`(정상 종료 제외)면 0.2초 뒤 안내 페이지(`htexapp://crashed/` 기준 setHtml, 히스토리에 안 남김).
  새로고침하면 원래 주소를 다시 연다. 바로 setHtml 하면 엔진이 새 렌더 프로세스를 띄우기 전이라 버려져 짧게 미룬다.

## 9. I(배포)에게
- 쓰는 Qt 모듈: QtCore, QtGui, QtWidgets, QtNetwork(QLocalServer/QLocalSocket), QtWebEngineCore, QtWebEngineWidgets.
  (테스트만 QtTest.) spec 의 EXCLUDE_QT 에 QtNetwork 가 없어 그대로 들어간다.
- 창 아이콘: `htex/viewer/icon.png` (packaging/icons/png/htex-256.png 복사본, 패키지 데이터 `*.png` 로 들어간다).
  `QGuiApplication.setDesktopFileName("org.hypertex.viewer")`.
- QSettings 위치: 조직 "HyperTeX", 앱 "Viewer".
