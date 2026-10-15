"""트리 빌더: 실제 LaTeX 원고(호환 모드, 명세 9절) 전용 처리. (4단계, 담당 K)

native(.htex) 문서에는 쓰지 않는다. 모두 `ctx.mode == "compat"` 일 때만 불린다.
매크로 층에서 버릴 수 있는 명령(\\index, \\medskip …)은 macros.COMPAT_SKIP 이 맡고,
여기서는 문서 트리에 흔적이 남아야 하는 것만 다룬다.

- 옛 글꼴 전환 \\bf \\it \\em \\tt \\sc …: 둘러싼 그룹(짝 없는 `}`)·단락·\\end·절 앞까지 styled 노드
- \\cref \\Cref \\autoref \\pageref \\nameref: ref 링크. 해석 단계에서 "Theorem 2.1" 같은 글을 채운다
- 본문 기호(\\textgreater, \\ss, \\o …)와 글자 악센트(\\c{c}, \\v{s}, \\H{o} …)
- \\textsuperscript·\\textsubscript·\\ensuremath: 인라인 수식
- 내용만 남기는 상자·색 명령 (\\fbox, \\textcolor, \\raisebox …)
- \\chapter 가 있는 책: chapter→section, section→subsection … 으로 한 단계씩 내린다 (스키마의 절은 4단계)
- 표시와 무관한 레이아웃 환경(multicols, spacing …)은 진단 없이 내용만
"""
from __future__ import annotations

import unicodedata
from typing import Optional

from .build_math import norm_ws, raw_text
from .build_state import sanitize_label
from .tokens import T, Token

# 옛 글꼴 전환 → styled 의 style
FONT_SWITCH = {
    "bf": "bold", "bfseries": "bold", "it": "italic", "itshape": "italic", "sl": "italic",
    "slshape": "italic", "em": "emph", "tt": "mono", "ttfamily": "mono", "sc": "smallcaps",
    "scshape": "smallcaps",
}
# 모양을 바꾸지 않는 전환 (보통 글꼴로 되돌림 등): 버린다
FONT_NEUTRAL = {"rm", "rmfamily", "sf", "sffamily", "upshape", "mdseries", "normalfont", "cal",
                "mit", "boldmath", "unboldmath", "small", "large", "Large", "LARGE", "huge",
                "Huge", "normalsize", "footnotesize", "scriptsize", "tiny", "centering",
                "raggedright", "raggedleft"}

TEXT_SYMBOLS = {
    "textgreater": ">", "textless": "<", "textbar": "|", "textbullet": "•",
    "textperiodcentered": "·", "textdegree": "°", "textregistered": "®", "texttrademark": "™",
    "textcopyright": "©", "textquotedblleft": "“", "textquotedblright": "”",
    "textquoteleft": "‘", "textquoteright": "’", "textellipsis": "…", "textunderscore": "_",
    "textbraceleft": "{", "textbraceright": "}", "textdollar": "$", "textsterling": "£",
    "pounds": "£", "texteuro": "€", "euro": "€", "textyen": "¥", "textsection": "§",
    "textparagraph": "¶", "textdagger": "†", "textdaggerdbl": "‡", "textasteriskcentered": "∗",
    "textvisiblespace": "␣", "textexclamdown": "¡", "textquestiondown": "¿",
    "guillemotleft": "«", "guillemotright": "»", "guilsinglleft": "‹", "guilsinglright": "›",
    "quotedblbase": "„", "quotesinglbase": "‚", "checkmark": "✓", "textmu": "µ",
    "ss": "ß", "SS": "SS", "ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ", "o": "ø", "O": "Ø",
    "aa": "å", "AA": "Å", "l": "ł", "L": "Ł", "i": "ı", "j": "ȷ", "dh": "ð", "DH": "Ð",
    "th": "þ", "TH": "Þ", "ng": "ŋ", "NG": "Ŋ",
    "enspace": " ", "thinspace": " ", "space": " ", "nobreakspace": " ", "enskip": " ",
    "qquad": "  ", "hfill": " ", "dotfill": " … ", "textendash": "–", "textemdash": "—",
    "qed": "∎", "eg": "e.g.", "ie": "i.e.", "etal": "et al.",
}
# 글자 악센트 → 결합 문자
LETTER_ACCENTS = {"c": "̧", "u": "̆", "v": "̌", "H": "̋", "k": "̨", "r": "̊", "d": "̣",
                  "b": "̱", "t": "͡", "G": "̏", "U": "̎"}

# 내용만 남기는 명령: 이름 → 앞에서 버릴 인수 서명 ('[' 선택, '{' 필수)
CONTENT_ONLY = {
    "fbox": "", "framebox": "[[", "makebox": "[[", "raisebox": "{[[", "parbox": "[[[{",
    "textcolor": "[{", "colorbox": "[{", "fcolorbox": "[{{", "scalebox": "{[", "rotatebox": "[{",
    "resizebox": "{{", "sout": "", "st": "", "uline": "", "underline": "", "uwave": "",
    "xout": "", "hl": "", "textls": "[", "mbox": "", "hbox": "", "foreignlanguage": "[{",
    "textenglish": "", "textlatin": "", "smash": "[", "phantom": "", "lowercase": "",
    "uppercase": "", "MakeUppercase": "", "MakeLowercase": "", "nolinkurl": "",
    "texorpdfstring": "",
}
# 인수 하나를 받아 통째로 버리는 명령 (빌더 쪽: 내용이 그려지면 안 되는 것)
DROP_WITH_ARG = {"color": "[{", "footnotemark": "[", "label": "{", "thanks": "{",
                 "hphantom": "{", "vphantom": "{", "hspace": "*{", "vspace": "*{",
                 "pdfbookmark": "[{{", "bookmark": "[{"}

CREF_COMMANDS = {"cref", "Cref", "crefrange", "Crefrange", "autoref", "Autoref", "pageref",
                 "cpageref", "Cpageref", "nameref", "Nameref", "vref", "Vref", "labelcref",
                 "namecref", "nameCref", "fullref", "subref", "hyperref"}

# 라벨 종류 → (\cref 이름, \Cref 이름). 정리류는 라벨의 display 에서 이름을 가져온다.
CREF_NAMES = {
    "section": ("section", "Section"), "equation": ("eq.", "Equation"),
    "figure": ("fig.", "Figure"), "table": ("table", "Table"), "item": ("item", "Item"),
    "footnote": ("footnote", "Footnote"), "step": ("step", "Step"),
}

# 표시와 무관한 레이아웃 환경 (진단 없이 내용만)
COMPAT_LAYOUT_ENVS = {
    "multicols", "multicols*", "spacing", "singlespace", "onehalfspace", "doublespace",
    "sloppypar", "samepage", "adjustwidth", "landscape", "framed", "mdframed", "tcolorbox",
    "raggedright", "raggedleft", "flushleft", "flushright", "center", "titlepage",
    "minipage", "small", "footnotesize", "scriptsize", "large", "normalsize", "tiny",
    "frontmatter", "mainmatter", "backmatter", "otherlanguage", "otherlanguage*",
    "linenumbers", "fullwidth", "widetext", "acknowledgments", "acknowledgements",
    "acknowledgment", "keywords", "IEEEkeywords", "subequations", "alignat", "alignat*",
    "wrapfigure", "subfigure", "sidewaysfigure", "sidewaystable", "threeparttable", "tablenotes",
    "appendices", "itemize*", "enumerate*", "description*", "compactitem", "compactenum",
}
# 환경 이름 뒤에 버릴 인수 서명
COMPAT_ENV_ARGS = {"multicols": "{[", "multicols*": "{[", "spacing": "{", "adjustwidth": "{{",
                   "otherlanguage": "{", "otherlanguage*": "{", "wrapfigure": "[{[{",
                   "subfigure": "[{", "minipage": "[[[{", "mdframed": "[", "tcolorbox": "["}


def remap_chapters(tokens: list[Token]) -> list[Token]:
    """\\chapter 가 있는 책 원고: 절 단계를 하나씩 내린다. \\part 는 번호 없는 최상위 절로."""
    if not any(t.type is T.CS and t.text == "chapter" for t in tokens):
        shift = {}
    else:
        shift = {"chapter": "section", "section": "subsection", "subsection": "subsubsection",
                 "subsubsection": "paragraph"}
    out: list[Token] = []
    for t in tokens:
        if t.type is T.CS and t.text in shift:
            out.append(Token(T.CS, shift[t.text], t.span))
        elif t.type is T.CS and t.text == "part":
            out.append(Token(T.CS, "section", t.span))
            out.append(Token(T.CHAR, "*", t.span))
        else:
            out.append(t)
    # \section** 처럼 별표가 겹치면 하나로
    res: list[Token] = []
    for t in out:
        if (t.type is T.CHAR and t.text == "*" and len(res) >= 2 and res[-1].type is T.CHAR
                and res[-1].text == "*" and res[-2].type is T.CS and res[-2].text == "section"):
            continue
        res.append(t)
    return res


class CompatMixin:
    pending_crefs: list

    def compat_command(self, tok: Token) -> bool:  # noqa: C901 - 분기 표
        """호환 모드 본문 명령을 처리했으면 True."""
        name = tok.text
        if name in FONT_SWITCH:
            self.font_switch(tok)
            return True
        if name in FONT_NEUTRAL:
            self.adv()
            return True
        if name in TEXT_SYMBOLS:
            self.adv()
            self.add_text(TEXT_SYMBOLS[name])
            # \ss{} 처럼 빈 그룹으로 끝맺는 관용구
            if self.cur.type is T.BGROUP and self.at(self.pos + 1).type is T.EGROUP:
                self.adv(2)
            return True
        if name in LETTER_ACCENTS:
            self.adv()
            s = raw_text(self.read_group())
            if s:
                self.add_text(unicodedata.normalize("NFC", s[0] + LETTER_ACCENTS[name] + s[1:]))
            return True
        if name in ("textsuperscript", "textsubscript", "ensuremath"):
            self.adv()
            arg = self.read_group()
            if name == "ensuremath":
                body = arg
            else:
                sp = tok.span
                body = ([Token(T.CHAR, "^" if name == "textsuperscript" else "_", sp),
                         Token(T.BGROUP, "{", sp), Token(T.CS, "text", sp),
                         Token(T.BGROUP, "{", sp)] + list(arg)
                        + [Token(T.EGROUP, "}", sp), Token(T.EGROUP, "}", sp)])
            for n in self.math_nodes(body, tok, "\\" + name + "{" + raw_text(arg) + "}"):
                self.emit(n)
            return True
        if name in CONTENT_ONLY:
            self.adv()
            self.take_star()
            self.skip_signature(CONTENT_ONLY[name])
            for n in self.inline_seq(self.read_group(), trim=False):
                self.emit(n) if n.get("kind") != "text" else self.add_text(n["text"])
            return True
        if name in DROP_WITH_ARG:
            self.adv()
            if name == "label":  # 확장 결과 등에서 빌더에 남은 \label 은 원래 처리로
                self.pos -= 1
                return False
            self.skip_signature(DROP_WITH_ARG[name])
            return True
        if name in CREF_COMMANDS:
            self.cref_link(tok)
            return True
        return False

    # ------------------------------------------------------------ 도우미
    def skip_signature(self, sig: str) -> None:
        for ch in sig:
            if ch == "*":
                self.take_star()
            elif ch == "[":
                self.read_opt()
            else:
                self.read_group(report=False)

    def font_switch(self, tok: Token) -> None:
        """{\\bf 글} : 둘러싼 그룹 끝(짝 없는 }), 단락 끝, \\end, \\item, 절 앞까지를 styled 로."""
        self.adv()
        style = FONT_SWITCH[tok.text]
        start = i = self.pos
        depth = 0
        while True:
            u = self.at(i)
            if u.type in (T.EOF, T.PAR):
                break
            if u.type is T.BGROUP:
                depth += 1
            elif u.type is T.EGROUP:
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0 and u.type is T.CS and (
                    u.text in ("end", "item", "par", "bibitem", "begin") and u.text != "begin"
                    or self.is_section_at(i)):
                break
            elif depth == 0 and u.type is T.CS and u.text in FONT_SWITCH:
                break  # 다음 전환이 이어받는다
            i += 1
        body = self.toks[start:i]
        self.pos = i
        children = self.inline_seq(body, trim=False)
        if children:
            self.emit({"kind": "styled", "style": style, "children": children})

    def cref_link(self, tok: Token) -> None:
        name = tok.text
        self.adv()
        self.take_star()
        if name == "hyperref":
            # \hyperref[label]{글}
            opt = self.read_opt()
            text_toks = self.read_group()
            label = sanitize_label(norm_ws(raw_text(opt or [])))
            node = {"kind": "link", "linkType": "ref", "target": {"label": label} if label else {}}
            kids = self.inline_seq(text_toks)
            if kids:
                node["children"] = kids
            self.emit(node)
            self.pending_refs.append((node, label, tok))
            return
        raw = norm_ws(raw_text(self.read_group()))
        if name in ("crefrange", "Crefrange"):
            raw = raw + "," + norm_ws(raw_text(self.read_group()))
        labels = [sanitize_label(x.strip()) for x in raw.split(",") if x.strip()]
        for k, label in enumerate(labels):
            if k:
                sep = "–" if name in ("crefrange", "Crefrange") else (
                    " and " if k == len(labels) - 1 else ", ")
                self.add_text(sep)
            node = {"kind": "link", "linkType": "ref",
                    "target": {"label": label} if label else {}}
            self.emit(node)
            self.pending_refs.append((node, label, tok))
            self.pending_crefs.append((node, label, name, k))

    def resolve_crefs(self) -> None:
        """해석이 끝난 ref 링크에 "Theorem 2.1" 같은 글을 채운다."""
        for node, label, name, k in self.pending_crefs:
            tgt = self.labels.get(label)
            if not tgt or not tgt.get("number"):
                continue
            num = tgt["number"]
            if name in ("pageref", "cpageref", "Cpageref", "subref", "labelcref"):
                continue  # 번호만 (렌더러 기본)
            if name in ("nameref", "Nameref"):
                title = self.target_title(tgt.get("node"))
                if title:
                    node["children"] = [{"kind": "text", "text": title}]
                continue
            word = cref_word(tgt, capital=name[0].isupper() or name == "autoref")
            if name in ("namecref", "nameCref"):
                node["children"] = [{"kind": "text", "text": word}]
                continue
            shown = f"({num})" if tgt.get("kind") == "equation" else num
            node["children"] = [{"kind": "text", "text": f"{word} {shown}" if word else shown}]

    def target_title(self, node_id: Optional[str]) -> str:
        if not node_id:
            return ""
        found: list[dict] = []

        def find(x):
            if found:
                return
            if isinstance(x, dict):
                if x.get("id") == node_id:
                    found.append(x)
                    return
                for v in x.values():
                    if isinstance(v, (list, dict)):
                        find(v)
            elif isinstance(x, list):
                for v in x:
                    find(v)
        find(self.out_root)
        if not found:
            return ""
        parts = []
        for n in found[0].get("title") or []:
            if n.get("kind") == "text":
                parts.append(n["text"])
        return "".join(parts).strip()


def cref_word(tgt: dict, capital: bool) -> str:
    kind = tgt.get("kind", "")
    if kind in CREF_NAMES:
        low, cap = CREF_NAMES[kind]
        return cap if capital else low
    disp = tgt.get("display") or ""
    num = tgt.get("number") or ""
    if disp.endswith(" " + num):
        word = disp[: -len(num) - 1]
        return word if capital else word[:1].lower() + word[1:]
    return ""
