"""트리 빌더: 메타데이터·전문 명령·정의 건너뛰기·스타일 파일 (명세 2, 4, 6, 9절). (담당: C)"""
from __future__ import annotations

import re
from typing import Optional

from . import commands as C
from .build_math import norm_ws, raw_text
from .loader import classify
from .picture import ALLOWED_LIBRARIES
from .tokens import T, Token

# 호환 모드에서 내장으로 보고 조용히 넘기는 패키지 (명세 9절)
KNOWN_PACKAGES = {
    "amsmath", "amssymb", "amsthm", "amsfonts", "hyperref", "graphicx", "graphics",
    "tikz", "pgfplots", "mathtools", "kotex", "url", "xcolor", "color", "bm",
}
# 호환 모드(명세 9절, 2026-10-15 결정): 이 구현이 지원하는 기능의 패키지와 화면 표시와 무관한
# 글꼴·여백·조판 패키지는 경고 없이 무시한다. 표시가 달라질 수 있는데 지원하지 않는 패키지만 경고한다.
COMPAT_QUIET_PACKAGES = {
    # 지원하는 기능
    "amscd", "tikz-cd", "xy", "xypic", "cleveref", "mathrsfs", "eucal", "euscript", "dsfont",
    "bbm", "amsbsy", "latexsym", "textcomp", "cancel", "ulem", "soul", "comment", "verbatim",
    "xspace", "upgreek", "amsfonts", "amsxtra", "accents", "bbold", "mathbbol", "stmaryrd",
    "epsfig", "subcaption", "subfig", "caption", "float", "wrapfig", "multicol", "booktabs",
    "array", "enumerate", "enumitem", "paralist", "mdwlist", "framed", "mdframed", "csquotes",
    "bookmark", "nameref", "varioref", "xr", "xr-hyper", "chngcntr", "etoolbox", "ifthen",
    "calc", "xparse", "keyval", "kvoptions", "makeidx", "imakeidx", "showkeys", "appendix",
    "abstract", "authblk", "thmtools", "aliascnt", "doi", "url",
    # 글꼴·여백·쪽·조판 (화면 표시와 무관)
    "inputenc", "fontenc", "lmodern", "times", "mathptmx", "palatino", "mathpazo", "helvet",
    "courier", "charter", "newtxtext", "newtxmath", "libertine", "libertinus", "fourier",
    "kpfonts", "txfonts", "pxfonts", "tgtermes", "tgpagella", "ebgaramond", "microtype",
    "geometry", "fullpage", "a4wide", "a4", "setspace", "parskip", "indentfirst", "ragged2e",
    "lscape", "pdflscape", "afterpage", "placeins", "needspace", "hyphenat", "fixltx2e",
    "fix-cm", "cmap", "ae", "aecompl", "type1cm", "anyfontsize", "relsize", "fancyhdr",
    "lastpage", "emptypage", "nopageno", "titlesec", "titletoc", "tocloft", "silence",
    "pdfsync", "lineno", "changepage", "babel", "polyglossia", "fontspec", "xltxtra",
    "xunicode", "luatextra", "iftex", "ifpdf", "ifxetex", "pdfpages",
}
MATH_EXTENSIONS = {"hangulmath"}
DEFINITION_COMMANDS = {"newcommand", "renewcommand", "providecommand", "DeclareMathOperator", "def"}
META_COMMANDS = {
    "documentclass", "HyperTeXversion", "title", "author", "date", "keywords", "abstract",
    "usestyle", "usemacros", "usemath", "usetikzlibrary", "usepackage", "newtheorem",
    "parameter", "maketitle",
}

_NUM = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


def _num(s: str) -> Optional[float]:
    s = s.strip()
    if not _NUM.match(s):
        return None
    v = float(s)
    return int(v) if v.is_integer() and abs(v) < 1e15 else v


def parse_hsty(text: str) -> dict[str, str]:
    """.hsty 키-값. '%'로 시작하는 줄은 주석, 값의 바깥 따옴표는 뗀다."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("%"):
            continue
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if re.match(r"^[A-Za-z][A-Za-z0-9._-]*$", k):
            out[k] = v
    return out


class MetaMixin:
    def _init_meta(self) -> None:
        self.meta: dict = {"documentclass": "hypertex"}
        self.parameters: list[dict] = []
        self.theorem_envs: dict[str, tuple[str, bool]] = {
            k: (v, True) for k, v in C.THEOREM_NAMES.items()}
        self.param_names: set[str] = self._prescan_params()

    def _prescan_params(self) -> set[str]:
        names = set()
        toks = self.toks
        for i, t in enumerate(toks):
            if t.type is T.CS and t.text == "parameter":
                j = i + 1
                while j < len(toks) and toks[j].type is T.SPACE:
                    j += 1
                if j < len(toks) and toks[j].type is T.BGROUP:
                    k = j + 1
                    while k < len(toks) and toks[k].type is T.SPACE:
                        k += 1
                    if k < len(toks) and toks[k].type is T.CS:
                        names.add(toks[k].text)
        return names

    # ------------------------------------------------------------ 정의 건너뛰기
    def skip_definition(self) -> None:
        """\\newcommand 류. B가 실제로 처리하므로 여기서는 인수만 조용히 소비한다."""
        name = self.cur.text
        self.adv()
        if name == "def":
            # \def\name<매개변수 텍스트>{본문}
            if self.cur.type is T.CS:
                self.adv()
            n = 0
            while self.cur.type not in (T.BGROUP, T.EOF, T.PAR) and n < 32:
                self.adv()
                n += 1
            if self.cur.type is T.BGROUP:
                self.read_group(report=False)
            return
        self.take_star()
        self.read_group(report=False)          # {\name} 또는 \name
        if name == "DeclareMathOperator":
            self.read_group(report=False)
            return
        self.read_opt()                        # [인수 수]
        self.read_opt()                        # [첫 인수 기본값]
        self.read_group(report=False)          # 본문

    # ------------------------------------------------------------ 메타 명령
    def meta_command(self) -> None:
        tok = self.cur
        name = tok.text
        self.adv()
        m = self.meta
        if name == "documentclass":
            opts = self.read_opt()
            cls = self.read_text_arg()
            if self.ctx.mode == "compat":
                m["documentclass"] = "hypertex"
                m.pop("classOptions", None)
            else:
                m["documentclass"] = cls or "hypertex"
                if opts is not None:
                    o = [x.strip() for x in raw_text(opts).split(",") if x.strip()]
                    if o:
                        m["classOptions"] = o
        elif name == "HyperTeXversion":
            self.read_group()
        elif name == "title":
            self.read_opt()
            m["title"] = self.inline_seq(self.read_group())
        elif name == "author":
            self.read_opt()
            for part in _split_and(self.read_group()):
                inl = self.inline_seq(part)
                if inl:
                    m.setdefault("authors", []).append(inl)
        elif name == "date":
            m["date"] = norm_ws(raw_text(self.read_group()))
        elif name == "keywords":
            kws = [k.strip() for k in norm_ws(raw_text(self.read_group())).split(",")]
            m.setdefault("keywords", []).extend(k for k in kws if k)
        elif name == "abstract":
            m.setdefault("abstract", []).extend(self.blocks_seq(self.read_group(allow_par=True)))
        elif name == "usestyle":
            url = self.read_text_arg()
            if url and classify(url) != "forbidden":
                m.setdefault("styles", []).append(url)
            if url:
                text = self.ctx.loader.read_text(url, tok.span, self.sink, extensions=("", ".hsty"))
                if text is not None:
                    self.apply_style(parse_hsty(text))
        elif name == "usemacros":
            # 읽기와 주소 진단은 B(Expander)의 몫. 여기서는 기록만 한다.
            url = self.read_text_arg()
            if url and classify(url) != "forbidden":
                m.setdefault("macroImports", []).append(url)
        elif name == "usemath":
            for ext in (x.strip() for x in self.read_text_arg().split(",")):
                if not ext:
                    continue
                if ext in MATH_EXTENSIONS:
                    lst = m.setdefault("mathExtensions", [])
                    if ext not in lst:
                        lst.append(ext)
                else:
                    self.sink.add("unknown-package", f"알 수 없는 수식 확장: {ext}", tok.span)
        elif name == "usetikzlibrary":
            for lib in (x.strip() for x in self.read_text_arg().split(",")):
                if not lib:
                    continue
                if lib in ALLOWED_LIBRARIES:
                    lst = m.setdefault("tikzLibraries", [])
                    if lib not in lst:
                        lst.append(lib)
                else:
                    self.sink.add("unknown-tikz-library",
                                  f"허용 목록 밖의 TikZ 라이브러리를 무시했다: {lib}", tok.span)
        elif name == "usepackage":
            self.read_opt()
            for pkg in (x.strip() for x in self.read_text_arg().split(",")):
                if pkg and pkg not in KNOWN_PACKAGES and not (
                        self.ctx.mode == "compat" and pkg in COMPAT_QUIET_PACKAGES):
                    self.sink.add("unknown-package", f"지원하지 않는 패키지를 무시했다: {pkg}", tok.span)
        elif name == "newtheorem":
            star = self.take_star()
            env = self.read_text_arg()
            self.read_opt()                     # [공유할 카운터] — 카운터는 어차피 하나
            title = norm_ws(raw_text(self.read_group()))
            self.read_opt()                     # [상위 카운터]
            if env:
                self.theorem_envs[env] = (title or env, not star)
        elif name == "parameter":
            self.parameter_command(tok)
        elif name == "maketitle":
            pass

    def parameter_command(self, tok: Token) -> None:
        pname_toks = self.read_group()
        from .build_math import param_name
        pname = param_name(pname_toks)
        vals = [_num(raw_text(self.read_group())) for _ in range(3)]
        opt = self.read_opt()
        step = None
        if opt is not None:
            for kv in raw_text(opt).split(","):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    if k.strip() == "step":
                        step = _num(v)
        lo, hi, dv = vals
        if not pname or lo is None or hi is None or dv is None or lo > hi or (step is not None and step <= 0):
            self.sink.add("expression-syntax", f"\\parameter 선언을 해석할 수 없다: {pname}", tok.span)
            if not pname or lo is None or hi is None or lo > hi:
                if not any(p["name"] == pname for p in self.parameters):
                    self.param_names.discard(pname)
                return
            if dv is None:
                dv = lo
            if step is not None and step <= 0:
                step = None
        if not (lo <= dv <= hi):
            self.sink.add("expression-syntax", f"매개변수 {pname}의 기본값이 범위 밖이다", tok.span)
            dv = min(max(dv, lo), hi)
        if any(p["name"] == pname for p in self.parameters):
            return
        p = {"name": pname, "min": lo, "max": hi, "default": dv}
        if step is not None:
            p["step"] = step
        self.parameters.append(p)
        self.param_names.add(pname)

    def apply_style(self, kv: dict[str, str]) -> None:
        for k, v in kv.items():
            if not k.endswith(".number"):
                continue
            counter = k[: -len(".number")]
            if counter not in self.cnt:
                continue
            tpl = v.strip()
            if tpl.startswith("(") and tpl.endswith(")"):
                tpl = tpl[1:-1]
            words = re.findall(r"[A-Za-z]+", tpl)
            ok_words = set(self.cnt) | {"section", "subsection", "subsubsection"}
            if counter in words and all(w in ok_words for w in words):
                self.num_templates[counter] = tpl


def _split_and(tokens: list[Token]) -> list[list[Token]]:
    parts: list[list[Token]] = [[]]
    depth = 0
    for t in tokens:
        if t.type is T.BGROUP:
            depth += 1
        elif t.type is T.EGROUP:
            depth -= 1
        if t.type is T.CS and t.text == "and" and depth == 0:
            parts.append([])
            continue
        parts[-1].append(t)
    return parts
