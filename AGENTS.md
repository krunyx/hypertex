# 작업 분담 규칙 (1단계)

이 저장소는 HyperTeX 2.0 기준 구현이다. 명세는 `docs/spec.md`, 계약은 `schema/`와 `tests/manifest.json`이다.

## 공통 규칙

1. **자기 담당 파일만 수정한다.** 아래 표에 없는 파일, 특히 `schema/`, `tests/manifest.json`,
   `tests/docs/`, `tools/check.py`, `AGENTS.md`, `docs/spec.md` 는 **수정 금지**.
2. 명세·스키마·테스트가 틀렸거나 모호하거나 서로 모순되면 **고치지 말고** `notes/<담당>-questions.md` 에
   적는다: 어느 파일 어느 부분, 무엇이 문제인지, 제안하는 해결, 그 사이 임시로 어떻게 가정했는지.
3. 외부 패키지를 추가하지 않는다 (파이썬 표준 라이브러리만. 테스트용 pytest·jsonschema는 예외).
4. 예외로 파싱을 멈추지 않는다. 문제는 `ctx.sink.add(...)` 진단으로 남기고 계속한다 (명세 7절).
5. 완료 기준을 `python tools/run_all.py <사례>` 와 자기 단위 테스트(`tests/unit/test_<담당>_*.py`)로 확인한다.
6. 끝나면 git에 커밋한다. 커밋 메시지 첫 줄은 `[A]`, `[B]` 처럼 담당 표시로 시작.

## 담당 구역

| 담당 | 수정 가능한 파일 | 완료 기준 |
| --- | --- | --- |
| A 정답 트리 | `tests/trees/*.tree.json` (01, 11 제외), `notes/A-questions.md` | 26건 모두 `python tools/check.py --all tests/trees` 통과 |
| B 토큰·매크로 | `htex/lexer.py`, `htex/macros.py`, `tests/unit/test_B_*.py`, `notes/B-questions.md` | `macros.py` docstring 계약 구현. 단위 테스트로 사례 15–18, 20의 매크로 동작 검증 |
| C 구조 | `htex/builder.py`, `htex/commands.py`, `htex/parser.py`, 새 파일 `htex/build_*.py`, `tests/unit/test_C_*.py`, `notes/C-questions.md` | `run_all.py` 로 01–14, 19, 24, 26, 28 통과 (27은 B 결과 합친 뒤) |
| D 계산식·그림 | `htex/expr.py`, `htex/picture.py`, `tests/unit/test_D_*.py`, `notes/D-questions.md` | 두 파일 docstring 계약 구현. 단위 테스트로 21–23, 25의 그림 진단 검증 |
| E HTML | `htex/html/` 아래 전부, `tests/unit/test_E_*.py`, `notes/E-questions.md` | `tests/trees/` 의 모든 트리를 예외 없이 HTML로 변환, 수식은 MathML |

다른 담당의 모듈은 **인터페이스(함수 이름·인자·docstring 계약)만 믿고** 쓴다. 0단계에서는 통과(stub) 구현이므로,
자기 테스트는 자기 모듈만으로 확인할 수 있게 짠다.

## 모듈 사이의 흐름

```
lexer.tokenize ─▶ macros.Expander.expand ─▶ builder.build ─▶ 문서 트리(JSON) ─▶ html.render
   (B)                 (B)                      (C)                                  (E)
                                                 │
                                                 └─▶ picture.check_picture ─▶ expr.parse
                                                         (D)                    (D)
```

## 테스트가 가정하는 번호 규칙

`README.md`의 같은 이름 절을 따른다.
