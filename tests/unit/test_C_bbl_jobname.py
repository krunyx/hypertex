"""BibTeX 가 만든 .bbl: LaTeX 처럼 문서 이름의 .bbl (paper.tex → paper.bbl) 을 먼저 쓰고, \\newblock 은 조용히."""
from __future__ import annotations

import json

from htex.parser import parse_file

BBL = r"""\begin{thebibliography}{1}

\bibitem{French1971}
A.~P. French.
\newblock {\em Vibrations and Waves}.
\newblock W. W. Norton, 1971.

\end{thebibliography}
"""
DOC = r"""\documentclass{article}
\begin{document}
See \cite{French1971}.
\bibliographystyle{plain}
\bibliography{refs}
\end{document}
"""


def test_jobname_bbl_is_used(tmp_path):
    (tmp_path / "paper.tex").write_text(DOC, encoding="utf-8")
    (tmp_path / "paper.bbl").write_text(BBL, encoding="utf-8")
    tree = parse_file(tmp_path / "paper.tex")
    assert tree["diagnostics"] == []
    text = json.dumps(tree, ensure_ascii=False)
    assert "Vibrations and Waves" in text and "newblock" not in text


def test_named_bbl_still_works(tmp_path):
    (tmp_path / "paper.tex").write_text(DOC, encoding="utf-8")
    (tmp_path / "refs.bbl").write_text(BBL, encoding="utf-8")
    tree = parse_file(tmp_path / "paper.tex")
    assert tree["diagnostics"] == []


def test_missing_bbl_reports_named_file_once(tmp_path):
    (tmp_path / "paper.tex").write_text(DOC, encoding="utf-8")
    tree = parse_file(tmp_path / "paper.tex")
    missing = [d for d in tree["diagnostics"] if d["code"] == "missing-resource"]
    assert len(missing) == 1 and "refs" in missing[0]["message"]
