"""화면 글자 언어 (한국어·영어). 원문은 한국어로 코드에 두고, 영어는 htex/i18n_en.py 의 표에서 찾는다.

    from htex.i18n import tr
    tr("새 탭")                       → "새 탭" 또는 "New Tab"
    tr("파일이 없습니다: {path}", path=p)

언어 고르기 (앞에 있는 것이 이긴다):
1. set_language("ko" | "en") — 뷰어가 설정(보기 › 언어)에 따라 부른다. "auto" 면 아래로.
2. 환경 변수 HTEX_LANG=ko|en
3. 운영체제 화면 언어 (Qt 가 있으면 QLocale.uiLanguages, 없으면 LANGUAGE·LC_ALL·LC_MESSAGES·LANG)
한국어가 아니면 모두 영어다.

문서 안의 이름(그림·표·증명·참고문헌 …)은 화면 언어가 아니라 문서 언어를 따른다: doc_language().
"""
from __future__ import annotations

import os
import re
from typing import Any, Optional

LANGS = ("ko", "en")
_lang: Optional[str] = None


def _norm(code: str) -> Optional[str]:
    c = (code or "").strip().lower().replace("_", "-")
    if not c or c in ("c", "posix"):
        return None
    return "ko" if c.startswith("ko") else "en"


def detect_system() -> str:
    try:
        from PySide6.QtCore import QLocale
        for code in QLocale.system().uiLanguages():
            got = _norm(code)
            if got:
                return got
    except Exception:   # noqa: BLE001 - Qt 없음
        pass
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var, "")
        for part in val.split(":"):
            got = _norm(part.split(".")[0])
            if got:
                return got
    return "en"


def ui_language() -> str:
    global _lang
    if _lang is None:
        _lang = _norm(os.environ.get("HTEX_LANG", "")) or detect_system()
    return _lang


def set_language(code: Optional[str]) -> str:
    """"ko"·"en" 이면 그것으로, "auto"·None 이면 다시 고른다. 고른 언어를 돌려준다."""
    global _lang
    _lang = None
    if code and code != "auto":
        _lang = _norm(code) or "en"
    return ui_language()


def tr(text: str, **kw: Any) -> str:
    """한국어 원문 → 화면 언어. kw 가 있으면 str.format 으로 채운다."""
    if ui_language() != "ko":
        from .i18n_en import EN
        text = EN.get(text, text)
    return text.format(**kw) if kw else text


# ---------------------------------------------------------------- 문서 언어
_HANGUL = re.compile("[가-힣ㄱ-ㅎㅏ-ㅣ]")
_LATIN = re.compile("[A-Za-z]")


def doc_language(text: str) -> str:
    """본문 글자로 문서 언어를 고른다: 한글이 글자의 1/5 이상이면 "ko", 아니면 "en".
    (한국어 논문도 영어 낱말·수식 기호가 많으므로 문턱을 낮게 둔다.)"""
    h = len(_HANGUL.findall(text))
    a = len(_LATIN.findall(text))
    if h + a == 0:
        return ui_language()
    return "ko" if h * 5 >= h + a else "en"


DOC_WORDS = {
    "figure": ("그림", "Figure"), "table": ("표", "Table"), "theorem": ("정리", "Theorem"),
    "lemma": ("보조정리", "Lemma"), "proposition": ("명제", "Proposition"), "corollary": ("따름정리", "Corollary"),
    "definition": ("정의", "Definition"), "example": ("예", "Example"), "remark": ("참고", "Remark"),
    "proof": ("증명", "Proof"), "bibliography": ("참고문헌", "References"), "abstract": ("요약", "Abstract"),
    "keywords": ("핵심어", "Keywords"), "footnotes": ("각주", "Notes"), "warning": ("경고", "Warning"),
    "error": ("오류", "Error"), "untitled": ("HyperTeX 문서", "HyperTeX document"),
    "parameters": ("매개변수", "Parameters"), "parameters_default": ("매개변수 (기본값)", "Parameters (defaults)"),
    "end_of_proof": ("증명 끝", "End of proof"), "back_to_text": ("본문으로", "Back to text"),
    "transclusion": ("가져올 내용:", "Included content:"),
}


def doc_word(key: str, lang: str) -> str:
    ko, en = DOC_WORDS[key]
    return ko if lang == "ko" else en
