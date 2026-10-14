# HyperTeX 2.0 — 문서 트리 스키마와 테스트 묶음

명세 초안(HyperTeX 2.0 명세 초안)의 8절 "기준 파서 → 문서 트리 → 여러 렌더러" 구조에서,
모든 구현이 공유하는 **계약**을 담은 묶음이다. 파서, HTML 변환기, 웹 폴백, 전용 뷰어를
누가(사람이든 에이전트든) 만들든 이 묶음을 통과하면 서로 맞물린다.

```
hypertex/
├── schema/document-tree.schema.json   문서 트리 JSON 스키마 (Draft 2020-12)
├── tests/
│   ├── manifest.json                  28개 사례의 목적, 명세 절, 기대 결과
│   ├── docs/                          테스트 입력 (.htex 26개 + 호환 모드 .tex 1개 + 보조 파일)
│   └── trees/                         손으로 쓴 정답 트리 예시 (01, 11)
└── tools/check.py                     검사기
```

## 문서 트리의 요점

- 파서는 **매크로 확장, 번호 매김, 라벨 해석을 끝낸 상태**로 트리를 낸다. 렌더러는 TeX를 다시 해석하지 않는다.
- 노드는 `kind`로 구분한다. 블록 17종(section, paragraph, displaymath, theorem, picture, …), 인라인 9종(text, math, link, footnote, …).
- 모든 노드는 문서 안에서 유일한 `id`(`n1`, `n2`, …)를 갖고, 최상위 `labels` 표가 라벨 → 노드 id·종류·번호를 잇는다. `htex://…#라벨` 주소는 이 표로 해석한다.
- 수식은 확장이 끝난 TeX 문자열(`math.tex`)과 쓰인 문자 체계(`scripts`, 한글이면 `hangul`)로 저장한다. MathML 변환은 렌더러 몫이다.
- TikZ·pgfplots 그림은 1.0에서 확장된 소스 문자열(`picture.source`)로 넘긴다. 그림 내부 구조 스키마는 다음 단계 과제다.
- 오류는 `diagnostics` 배열과, 해석하지 못한 자리의 `error` 노드로 동시에 남긴다(명세 7절).
- 주소에는 `javascript:`, `data:`, `file:`, `http:`가 들어갈 수 없다(스키마가 거부).

## 테스트가 가정하는 번호 규칙

명세에 아직 적히지 않은 기본값을 테스트가 아래처럼 고정했다. 다르게 하고 싶으면 manifest와 명세를 함께 고친다.

- 절: `1`, `1.1`, `1.1.1`. `\paragraph`와 별표 절은 번호 없음. 부록은 `A`, `A.1`.
- 식, 그림, 표, 각주: 각각 문서 전체 일련번호. `align`의 `\nonumber` 행은 번호를 쓰지 않는다.
- 정리류(definition, theorem, lemma, remark, `\newtheorem` 정의 환경)는 카운터 하나를 공유. proof는 번호 없음.
- 스타일 파일의 `equation.number = "(section.equation)"`이 있으면 식 번호가 `1.1`, `2.1` 꼴이 된다(사례 28).
- 호환 모드의 `\input{파일}`은 그 자리에 펼쳐 넣어 번호와 라벨이 한 문서로 이어진다(사례 27).
- 매개변수 이름이 그리스 문자 명령과 같아도 된다. 계산식과 `\showparam` 안에서만 매개변수로 해석한다(사례 25).

## 검사기 사용법

```bash
pip install jsonschema

# 트리 하나: 스키마 + 내부 일관성
python tools/check.py out/06-math-basic.tree.json

# 기대값까지
python tools/check.py out/06-math-basic.tree.json --case 06-math-basic

# 파서가 out/ 에 <id>.tree.json 들을 써 두었을 때 전체
python tools/check.py --all out/
```

검사 항목은 세 층이다.

1. **스키마**: 구조와 값의 형식. oneOf 실패는 가장 깊은 원인 위치를 보여준다.
2. **일관성**: 노드 id 중복, 없는 노드를 가리키는 라벨·진단, 선언되지 않은 매개변수 참조, 범위 밖 기본값.
3. **기대값**: manifest의 `count`, `labels`, `links`, `meta`, `parameters`, `diagnostics`(`exact` 또는 `atLeast`) 등.

현재 상태: 손으로 쓴 정답 트리 2개가 통과하고(`--all tests/trees`), 나머지 26개는 파서가 만들 차례다.

## 사례 목록

| 사례 | 명세 | 확인하는 것 |
| --- | --- | --- |
| 01–05 | 2, 3 | 최소 구조, 메타데이터, 절 번호, 텍스트 서식, 목록 |
| 06–07 | 3 | 수식 기본, 여러 줄 수식과 번호 |
| 08–10 | 3 | 정리 환경, 그림, 표 |
| 11–14 | 5 | 문서 안·문서 간 참조, 인용, 전사 |
| 15–18 | 4 | 매크로, 순환 거부, 확장 상한, 매크로 가져오기 |
| 19–20 | 7 | 오류 관용, 제외된 명령 차단 |
| 21–23 | 3.1 | TikZ, TikZ 제한, pgfplots |
| 24–25 | 3.2 | 접기·단계, 매개변수 슬라이더와 계산식 |
| 26 | 8 | 한글 줄바꿈과 한글 수식 |
| 27 | 9 | 기존 LaTeX 호환 모드 |
| 28 | 6 | 스타일 파일 |
