"""파서 진입점: 원문 → 문서 트리. 각 단계를 잇기만 한다.

    lexer.tokenize → macros.Expander.expand → builder.build → (+ 진단, source 정보)
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional

from .builder import BuildContext, build
from .diagnostics import Sink
from .lexer import tokenize
from .loader import Loader
from .macros import Expander, MacroTable


def parse_text(text: str, url: str = "", base_dir: Optional[Path] = None,
               mode: Optional[str] = None) -> dict[str, Any]:
    """원문 → 문서 트리. mode 가 없으면 주소의 확장자로: .tex = compat, .md·.markdown = markdown, 그 밖 native."""
    if mode is None:
        from .markdown import is_markdown
        mode = "compat" if url.endswith(".tex") else "markdown" if is_markdown(url) else "native"
    if mode == "markdown":
        from .markdown import parse_markdown
        return parse_markdown(text, url=url, base_dir=base_dir)
    sink = Sink()
    loader = Loader(base_dir or Path.cwd())

    tokens = tokenize(text, sink)
    tokens = Expander(MacroTable(), sink, loader, mode=mode).expand(tokens)
    ctx = BuildContext(sink=sink, loader=loader, mode=mode, source_url=url)
    tree = build(tokens, ctx)

    tree["source"] = {
        "url": url,
        "mode": mode,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    tree["diagnostics"] = sink.to_json()
    return tree


def parse_file(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    return parse_text(p.read_text(encoding="utf-8"), url=p.name, base_dir=p.parent)
