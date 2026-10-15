"""토큰 → 문서 트리 (명세 2, 3, 5, 6, 7, 9절). (담당: C)

구현은 htex/build_*.py 에 나뉘어 있다.
  build_state  토큰 커서, 인수 읽기, 카운터, 라벨 표
  build_meta   전문 명령, 메타데이터, \\parameter, 스타일 파일
  build_inline 인라인 노드, 인라인 수식, 링크
  build_blocks 절·단락·환경·디스플레이 수식·그림·표·참고문헌
  build_math   수식 구문 검사, 행 나누기, 문자 체계 (순수 함수)
표현 규칙은 docs/tree-conventions.md, 그 밖에 정한 것은 notes/C-questions.md.

계약
- 입력: Expander가 확장을 끝낸 토큰 목록 (\\newcommand 정의는 이미 사라짐).
- 출력: schema/document-tree.schema.json 을 만족하는 dict. diagnostics 는 비워 두고
  (parser.py가 sink에서 채운다) 진단은 ctx.sink.add 로만 남긴다.
- 노드 id는 문서 순서대로 n1, n2, … (ctx.new_id()).
- 번호 규칙은 README "테스트가 가정하는 번호 규칙"과 스타일 파일(equation.number)을 따른다.
- 수식은 detokenize 로 math.tex 를 만들고, scripts 에 쓰인 문자 체계를 적는다
  (ASCII 글자 → latin, 그리스 문자 명령 → greek, 한글 음절 → hangul).
- tikzpicture 는 detokenize 한 원문을 picture.check_picture 에 넘기고 결과로 picture 노드를 만든다.
- \\usetikzlibrary 의 허용 목록 밖 라이브러리는 unknown-tikz-library (경고).
- 오류 관용: 어떤 입력에도 예외 없이 끝까지 트리를 만든다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .diagnostics import Sink
from .loader import Loader
from .tokens import Token


@dataclass
class BuildContext:
    sink: Sink
    loader: Loader
    mode: str = "native"          # "native" | "compat"
    source_url: str = ""
    _next_id: int = field(default=0, repr=False)

    def new_id(self) -> str:
        self._next_id += 1
        return f"n{self._next_id}"


from .build_blocks import BlockMixin  # noqa: E402
from .build_compat import CompatMixin, remap_chapters  # noqa: E402
from .build_inline import InlineMixin  # noqa: E402
from .build_meta import MetaMixin  # noqa: E402
from .build_state import StateMixin  # noqa: E402


class _Builder(StateMixin, MetaMixin, InlineMixin, CompatMixin, BlockMixin):
    """build_state / build_meta / build_inline / build_blocks 의 기능을 합친 해석기."""

    def __init__(self, tokens: list[Token], ctx: BuildContext):
        if ctx.mode == "compat":
            tokens = remap_chapters(tokens)
        self._init_state(tokens, ctx)
        self.pending_crefs: list = []
        self._init_meta()
        self.bibliography: list[dict] = []
        self.out: list[dict] = []
        self.para = None
        self.inl_out = None
        self.brace_depth = 0

    def run(self) -> dict[str, Any]:
        body = self.out
        self.out_root = body
        self.run_top()
        self.finish_params(body)
        self.finish_ids(body)
        self.resolve()
        self.resolve_crefs()
        meta = self.meta
        if "abstract" in meta and not meta["abstract"]:
            del meta["abstract"]
        return {
            "hypertex": "2.0",
            "meta": meta,
            "labels": self.labels,
            "parameters": self.parameters,
            "bibliography": self.bibliography,
            "body": body,
            "diagnostics": [],
        }

    def finish_params(self, body: list) -> None:
        """미리 훑어 본 \\parameter 가 실제로는 선언되지 못했을 때 (깨진 선언) 그 참조를 정리한다."""
        declared = {p["name"] for p in self.parameters}
        if self.param_names <= declared:
            return

        def fix(x):
            if isinstance(x, list):
                out = []
                for y in x:
                    if isinstance(y, dict) and y.get("kind") == "showparam" and y["name"] not in declared:
                        self.sink.add("unknown-parameter", f"선언되지 않은 매개변수: {y['name']}")
                        out.append({"kind": "error", "code": "unknown-parameter",
                                    "raw": f"\\showparam{{\\{y['name']}}}"})
                    else:
                        fix(y)
                        out.append(y)
                x[:] = out
            elif isinstance(x, dict):
                for holder in (x, x.get("math")):
                    if isinstance(holder, dict) and "params" in holder:
                        holder["params"] = [p for p in holder["params"] if p in declared]
                        if not holder["params"]:
                            del holder["params"]
                for k, v in x.items():
                    if isinstance(v, (list, dict)) and k != "math":
                        fix(v)
                    elif k == "math" and isinstance(v, dict):
                        pass
                if isinstance(x.get("rows"), list):
                    fix(x["rows"])
        fix(body)

    def finish_ids(self, body: list) -> None:
        """인라인 자리로 펼쳐진 블록 때문에 생긴 id 빈틈을 메우고, 사라진 노드를 가리키는 라벨을 지운다."""
        found: list[dict] = []
        _collect_ids(body, found)
        _collect_ids(self.meta.get("abstract", []), found)
        present = {n["id"] for n in found}
        for k in [k for k, v in self.labels.items() if v["node"] not in present]:
            del self.labels[k]
        order = sorted(present, key=lambda x: int(x[1:]))
        if order and order[-1] == f"n{len(order)}":
            return
        remap = {old: f"n{i}" for i, old in enumerate(order, 1)}
        for n in found:
            n["id"] = remap[n["id"]]
        for v in self.labels.values():
            v["node"] = remap[v["node"]]

    def resolve(self) -> None:
        for node, label, tok in self.pending_refs:
            tgt = self.labels.get(label)
            if tgt is None:
                node["resolved"] = {"broken": True}
                self.sink.add("broken-ref", f"라벨 {label}을 찾을 수 없다", tok.span)
            else:
                res: dict[str, Any] = {}
                if "number" in tgt:
                    res["number"] = tgt["number"]
                res["node"] = tgt["node"]
                node["resolved"] = res
        numbers = {b["key"]: b["number"] for b in self.bibliography}
        for node, keys, tok in self.pending_cites:
            missing = [k for k in keys if k not in numbers]
            if missing:
                node["resolved"] = {"broken": True}
                self.sink.add("broken-ref", f"참고문헌 키를 찾을 수 없다: {', '.join(missing)}", tok.span)
            else:
                node["resolved"] = {"numbers": [numbers[k] for k in keys]}


def _collect_ids(x, out: list) -> None:
    if isinstance(x, list):
        for y in x:
            _collect_ids(y, out)
    elif isinstance(x, dict):
        if isinstance(x.get("id"), str):
            out.append(x)
        for k, v in x.items():
            if k != "math" and isinstance(v, (list, dict)):
                _collect_ids(v, out)


def build(tokens: list[Token], ctx: BuildContext) -> dict[str, Any]:
    """확장이 끝난 토큰 → 문서 트리. 어떤 입력에도 예외 없이 트리를 낸다."""
    try:
        return _Builder(tokens, ctx).run()
    except RecursionError:
        ctx.sink.add("render-timeout", "문서 중첩이 너무 깊어 해석을 멈췄다")
    except Exception as e:  # 마지막 방어선: 내부 오류도 트리로 (명세 7절)
        ctx.sink.add("render-timeout", f"트리 빌더 내부 오류: {type(e).__name__}: {e}")
    return {
        "hypertex": "2.0",
        "meta": {"documentclass": "hypertex"},
        "labels": {},
        "parameters": [],
        "bibliography": [],
        "body": [],
        "diagnostics": [],
    }
