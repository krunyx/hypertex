# B(토큰·매크로) 질문과 임시 가정

각 항목: 어디 / 무엇이 문제 / 제안 / 임시 가정.

## Q1. "한 번의 확장 결과 10,000토큰"의 단위
- 어디: spec.md 4절 3항, macros.py docstring
- 문제: 중첩 확장 각각인지, 최상위 호출 하나가 최종적으로 내는 전체 토큰인지 불분명.
  사례 17은 `\xe`(최종 20,000토큰, 각 단계 본문은 10토큰)가 오류여야 하므로 "최상위 호출의 최종 결과"로 읽어야 맞는다.
- 제안: 명세에 "최상위 매크로 호출 하나가 완전히 확장된 결과의 토큰 수"라고 적는다. 공백 토큰도 센다는 것도 함께.
- 임시 가정: 최상위 호출이 시작된 뒤 (이미 확정된 토큰 + 아직 대기 중인 확장 토큰) 수가 10,000을 넘는 순간
  그 호출 전체를 버리고 expansion-limit 하나. 진단 span은 최상위 호출 위치. 본문 끝의 매크로가 본문 뒤
  원문 토큰을 인수로 읽으면 그 토큰도 결과에 포함된다(TeX 입력 스택 방식).

## Q2. 내장 명령·매개변수 이름을 \newcommand로 정의할 때
- 어디: macros.py docstring "매개변수와 같은 이름의 매크로는 만들지 않는다", spec 4절
- 문제: 진단을 내야 하는지, 어떤 코드인지 정하지 않았다. \renewcommand{\alpha}{…}도 마찬가지.
- 제안: 경고 수준 진단 코드(예: `macro-redefinition`)를 스키마에 추가하거나, 조용히 무시한다고 명세에 명시.
- 임시 가정: 진단 없이 정의만 소비하고 무시한다. 내장 명령(commands.is_builtin), EXCLUDED, \parameter로 선언된 이름,
  정의 명령 자체(\newcommand 등)가 대상. \parameter는 정의보다 앞에 있어야 인식된다.

## Q3. 이미 정의된 이름에 \newcommand, 정의되지 않은 이름에 \renewcommand
- 어디: spec 4절
- 문제: LaTeX는 둘 다 오류지만 HyperTeX 진단 코드에 해당하는 것이 없다.
- 제안: 명세에 처리 방법 명시.
- 임시 가정: \newcommand 재정의는 기존 정의 유지(새 정의 무시, 진단 없음). \renewcommand 미정의 이름은 새로 정의
  (\providecommand처럼). 둘 다 진단 없음. 호환 모드 \def는 \renewcommand처럼(덮어씀).

## Q4. 형식이 틀린 정의
- 어디: spec 4절, 7절
- 문제: `\newcommand{\f}[x]{…}`, `\newcommand{a}{…}` 같은 형식 오류의 진단 코드가 없다.
- 제안: math-syntax 같은 범용 코드 대신 정의 오류용 코드가 있으면 좋다. 아니면 macro-recursion 재사용.
- 임시 가정: 정의 토큰을 소비하고 진단 없이 무시. 인수 수 10 이상도 같다.

## Q5. 정의 본문의 "미정의 명령" 판정 범위
- 어디: macros.py docstring "내장 명령도 아니고 이미 정의된 매크로도 아닌 명령"
- 문제: commands.py 목록에 없는 흔한 명령(\middle은 있으나 \| 같은 제어기호, \mathscr, \textcolor, \hspace,
  \left. 등)을 본문에 쓰면 정의 전체가 macro-recursion으로 거부된다. 목록이 불완전하면 정상 문서가 깨진다.
  예: 사례 15의 `\left\|`는 제어기호 `\|`를 쓴다.
- 제안: (a) 판정은 "자기 자신 또는 순환"과 "사용자 매크로 이름 중 아직 정의 안 된 것"에만 적용하고,
  모르는 명령은 사용 시 빌더가 undefined-command를 내게 하거나, (b) commands.py를 보강한다(C 담당).
- 임시 가정: 제어기호(이름이 ASCII 글자가 아닌 것: `\|`, `\,`, `\{` …)는 검사에서 뺀다. 제어어는 계약대로
  내장·매개변수·정의된 매크로가 아니면 거부. 본문이 제외 명령을 쓰면 macro-recursion 대신 excluded-command 하나로
  정의를 거부한다(native). 호환 모드에서는 무시 대상 명령(\newpage 등)과 \input, \def는 허용.
  C에게: commands.py에 \| 등 제어기호 추가 여부와 별개로 이 판정은 제어기호를 통과시킨다.

## Q6. \renewcommand에 의한 간접 순환
- 어디: spec 4절 2항 "순환이면 정의 거부"
- 문제: 정의 시점 검사만으로는 `\newcommand{\b}{B}\newcommand{\a}{\b}\renewcommand{\b}{\a}`의 순환을 못 잡는다.
- 임시 가정: 정의할 때 본문이 참조하는 정의된 매크로들의 본문을 따라가 자기 이름에 닿으면 macro-recursion으로 거부.
  어차피 확장 상한이 최후 방어선이다.

## Q7. 사례 20의 excluded-command 개수와 인수 소비 범위
- 어디: tests/docs/20-excluded-commands.htex, manifest(atLeast 8)
- 문제: 원문에는 제외 명령이 9개(\catcode, \def, \input, \include, \immediate, \write, \openin, \newpage, \vspace) 있다.
  \immediate\write18을 하나로 셀지 둘로 셀지 정해지지 않았다. 각 명령이 소비하는 인수 범위도 명세에 없다.
- 임시 가정: 명령마다 하나씩 9건. 인수 소비 규칙: \catcode`\@=11 (번호=번호), \def\name<매개변수 문법>{본문},
  \let\a=\b, \input{f}/\input f, \write<번호>{…}, \openin<번호>=<파일명>, \read<번호> to \cs,
  \csname…\endcsname, \vspace/\pagestyle/\thispagestyle{…}(별표 허용). \immediate, \expandafter, \newpage, \clearpage는 인수 없음.
  `\openin1=/etc/passwd`의 파일명은 공백·제어 시퀀스·빈 줄 전까지의 문자.

## Q8. 호환 모드 \input 깊이 초과의 진단 코드
- 어디: macros.py docstring "재귀 깊이 8 제한"
- 문제: 초과 시 진단 코드가 정해지지 않았다.
- 임시 가정: expansion-limit (그 \input만 무시하고 계속). 자기 자신을 \input하는 파일은 8단계까지 펼쳐진 뒤 1건.

## Q9. 호환 모드 무시 목록과 인수
- 어디: macros.py COMPAT_IGNORED
- 문제: \small, \large, \centering 등은 "페이지 명령"이 아니라 글꼴·배치 명령인데 여기서 버린다. 그리고
  native 모드에서 \hspace, \bibliographystyle은 EXCLUDED에도 builtin에도 없어 빌더가 undefined-command를 낸다.
- 임시 가정: 목록대로 진단 없이 버린다. \pagestyle, \thispagestyle, \bibliographystyle, \vspace, \hspace는
  중괄호 인수 하나(별표 허용)도 함께 버리고, 나머지는 명령만 버린다(`{\small text}`의 text는 남는다).

## Q10. \usemacros의 범위
- 어디: macros.py docstring, spec 4절
- 문제: 가져온 문서가 다시 \usemacros를 하면? 같은 주소를 두 번 가져오면? 가져온 문서의 진단은?
  htex://·https:// 주소는 파서가 읽지 않으므로 그 매크로를 쓰는 본문은 빌더에서 undefined-command가 된다.
- 임시 가정: 중첩 \usemacros는 깊이 8까지 따라간다. 같은 주소는 한 번만. 가져온 문서의 어휘 오류는 무시하고,
  정의 거부(macro-recursion 등)는 이 문서의 진단으로 남긴다. 확장자 생략 시 ".htex"도 시도.
  절대 주소는 진단 없이 아무것도 가져오지 않는다(loader 계약). 전문 판정: 정의·전문 명령(commands.PREAMBLE,
  인수 포함)을 건너뛰다 \begin(문서 시작 포함) 또는 그 밖의 첫 토큰에서 멈춘다.

## Q11. 매크로 확장 결과 토큰의 span
- 어디: tokens.py / 진단 span
- 문제: 확장 결과 토큰이 어느 위치를 가리켜야 하는지 정해지지 않았다.
- 임시 가정: 본문에서 온 토큰은 호출한 매크로 토큰의 span으로 바뀌는데, 중첩 확장에서는 그 매크로 토큰도 이미
  바뀐 span을 가지므로 결국 원문의 최상위 호출 위치가 된다. 인수에서 온 토큰은 원래 위치 유지.
  빌더가 확장 결과 안의 미정의 명령에 undefined-command를 낼 때 사용처를 가리키게 된다.

## Q12. lexer 변경 (시그니처·토큰 타입 변경 없음)
- `a%주석\n\n b`는 TeX처럼 PAR가 생기도록 고쳤다(이전에는 빈 줄이 SPACE로 합쳐져 단락이 이어졌다).
- 바꾸고 싶지만 바꾸지 않은 것: `\begin{verbatim}`이 `\begin {verbatim}`처럼 공백을 두면 인식되지 않는다.
  `\verb*|…|`도 지원하지 않는다. 필요하면 C와 합의 후 처리.
