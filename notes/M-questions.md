# M (6단계: Markdown 읽기와 로컬 HTML) — 정한 것과 확인이 필요한 것

## 범위 (2026-10-31 결정)
- `.md`·`.markdown` 을 문서 트리로 바꿔 보여 준다 (`htex/markdown.py`, 표준 라이브러리만). 트리가 같으므로 HTML·MathML,
  뷰어의 탭·찾기·테마·북마크·원본 보기·자동 새로고침, `htex serve`·`htex build` 가 그대로 된다.
- 뷰어는 내 컴퓨터의 `.html`·`.htm` 도 연다 (격리 상자, 아래).
- hwpx·docx 는 직접 읽지 않는다. 쪽 단위 배치를 흉내 내는 일은 워드프로세서를 하나 만드는 일이라, 변환은 hwp2x 에 맡긴다.

## 계약을 바꾼 곳 (명세·스키마)
- 스키마 `source.mode` 에 `"markdown"`, `Styled.style` 에 `"strike"`(~~취소선~~) 를 더했다. 렌더러는 `<s>`.
- 명세 9.1절(Markdown 표, 로컬 HTML), 10절 결정 기록.

## 정한 것
1. **제목**: 문서 첫 블록이 유일한 `#` 제목이면 meta.title, 나머지 제목은 한 단계씩 올린다. 절 번호는 붙이지 않는다.
   제목마다 GitHub 식 앵커를 라벨로 단다 (`## 첫 절` → `첫-절`, 같은 이름은 `-1`, `-2`). 라벨 이름 규칙(영숫자·한글·:._-) 밖의 글자는 버린다.
2. **수식**: `$…$` 는 pandoc 규칙 (여는 `$` 뒤·닫는 `$` 앞에 공백이 없고, 닫는 `$` 뒤가 숫자가 아닐 것). `$5 와 $10` 은 글자.
   글 안의 `$$…$$` 는 `\displaystyle` 을 붙인 글 안 수식. 줄 맨 앞의 `$$`·`\[` 는 전시 수식. `\begin{equation}`·`align` 은 번호를 단다.
3. **http:// 링크**: `https://` 로 올린다 (Chrome 의 HTTPS 우선과 같다). `mailto:`·`tel:` 은 글자만(기울임), `javascript:` 등은 오류 표시 + `insecure-resource` 진단.
4. **HTML**: 그대로 넣지 않는다. `<br>`, `<a href>`, `<img>`, `<details><summary>` 만 해석하고 나머지 태그는 지운다.
   문장 안 그림은 그림으로 가는 링크(🖼 대체 글)로, 그림만 있는 문단은 그림 블록으로 (그림은 블록만 된다).
5. **확장 문법**: GitHub 알림(`> [!NOTE]` → 굵은 제목 인용), MkDocs 알림(`!!! note "제목"` → 인용, `??? ` → 접기), 할 일 목록(☐ ☑).
6. **원격 .md**: `https://….md` 링크는 HyperTeX 문서처럼 가져온다. 서버가 HTML 을 주면(GitHub 의 blob 페이지 등) 웹 페이지로 돌려보낸다.
   그 리디렉트는 다시 가로채지 않는다 (가로채면 맴돈다: `acceptNavigationRequest` 의 NavigationTypeRedirect).
7. **웹 빌드**: `x.md` → `x.html`, 링크 `y.md#a` → `y.html#a`. `htex serve` 의 폴더 첫 페이지는 `index.htex`, `index.md`, `README.md` 순.

## 로컬 HTML 의 안전 장치
- `htexapp://doc-<뿌리>/…` 로 내준다 (사용자가 연 폴더만). CSP `sandbox allow-scripts allow-forms` (allow-same-origin 없음):
  스크립트는 돌지만 고유 출처가 없어 저장소·쿠키를 못 쓰고, `connect-src 'none'` 으로 fetch·XHR 로 다른 파일을 읽지 못한다.
  같은 폴더의 그림·CSS·JS·글꼴과 https 자원은 불러온다 (Chrome 이 file:// 를 다루는 것과 비슷).
- 데이터 파일(.json·.txt·.csv)은 내주지 않는다 (`test_F_core.test_local_non_document_and_image` 유지).
- 글자 인코딩은 문서의 `<meta charset>` 을 따른다 (EUC-KR 로 저장된 옛 한글 페이지).
- 창 테마(밝게·어둡게)는 로컬 HTML 에 넣지 않는다. 그 파일의 모양 그대로.

## 남은 것 (다음 후보)
- hwp2x 연결: `.hwp`·`.hwpx`·`.docx` 를 열려고 하면 hwp2x 로 변환해서 열기 (hwp2x 가 있으면), 없으면 내려받기 안내.
- hangulmath 명령(`\giyeok`, `\hangulsum` …): krunyx.com 의 hangulmath 문서가 이 명령을 써서 지금은 빨간 표시가 된다.
  HyperTeX 수식 변환기가 hangulmath 를 알게 하면 좋다.
- Markdown 안의 `\newcommand` (수식 매크로), 정의 목록, 각주 안의 각주.
- OS 에 `.md` 를 HyperTeX 로 연결하기는 하지 않았다 (다른 편집기의 기본 연결을 빼앗지 않게). "다른 프로그램으로 열기" 목록에는 넣을 수 있다.
