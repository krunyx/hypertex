"""HTML 출력에 인라인으로 넣는 스타일시트 (명세 8절 한글 조판). (담당: E)

- 한글 본문은 어절 단위 줄바꿈 (word-break: keep-all), 한 어절이 줄보다 길 때만 끊김 (overflow-wrap: anywhere).
- 라이트·다크 모드 (prefers-color-scheme), 본문 최대 폭 약 70자, 좁은 화면 대응.
- 긴 디스플레이 수식·표는 가로 스크롤.
- 수식 안 한글(.htex-hangul)은 직립 고딕 (기본 Noto Sans KR).
"""

CSS = r"""
:root{
  --fg:#1d1d1f;--bg:#fdfdfc;--muted:#5f6368;--rule:#d7d7d2;--accent:#1f5fa8;
  --panel:#f3f3ef;--err:#c4161c;--err-bg:#fdecec;--warn:#8a5a00;
  --body-font:"Noto Serif KR","Nanum Myeongjo","Batang",Georgia,serif;
  --sans-font:"Noto Sans KR","Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif;
  --mono-font:"D2Coding","Noto Sans Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --math-font:"Latin Modern Math","STIX Two Math","Cambria Math",math;
  --math-hangul-font:"Noto Sans KR","Apple SD Gothic Neo","Malgun Gothic",sans-serif;
  color-scheme:light dark;
}
@media (prefers-color-scheme:dark){
  :root{--fg:#e6e6e3;--bg:#161618;--muted:#a1a1a6;--rule:#3a3a3e;--accent:#8ab4f8;
    --panel:#222226;--err:#ff7b72;--err-bg:#3a1d1d;--warn:#e3b341;}
}
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font-family:var(--body-font);
  font-size:1.0625rem;line-height:1.75;word-break:keep-all;overflow-wrap:anywhere;
  line-break:strict;hanging-punctuation:allow-end}
.htex-doc{max-width:42rem;margin:0 auto;padding:2.5rem 1.25rem 4rem}
@media (max-width:40rem){.htex-doc{padding:1.25rem 1rem 3rem}body{font-size:1rem}}
a{color:var(--accent);text-decoration-thickness:.06em;text-underline-offset:.15em}
a:hover{text-decoration-thickness:.12em}
h1,h2,h3,h4,h5{font-family:var(--sans-font);line-height:1.35;font-weight:700;
  margin:2rem 0 .75rem;scroll-margin-top:1rem}
h1{font-size:1.75rem;margin-top:0}
h2{font-size:1.4rem}h3{font-size:1.2rem}h4{font-size:1.05rem}
h5{font-size:1rem;display:inline;margin:0 .6em 0 0}
.htex-level-4>h5+p{display:inline}
.htex-secnum{margin-right:.4em;color:var(--muted)}
p{margin:.9rem 0}
.htex-header{margin-bottom:2rem;border-bottom:1px solid var(--rule);padding-bottom:1rem}
.htex-authors,.htex-date{margin:.25rem 0;color:var(--muted);font-family:var(--sans-font)}
.htex-keywords{font-family:var(--sans-font);font-size:.9rem;color:var(--muted)}
.htex-keywords ul{display:inline;list-style:none;padding:0;margin:0 0 0 .5em}
.htex-keywords li{display:inline}
.htex-keywords li+li::before{content:", "}
.htex-kw-label{font-weight:700}
.htex-abstract{background:var(--panel);padding:.25rem 1.25rem;border-radius:.4rem;margin-top:1rem}
.htex-abstract h2{font-size:1rem;margin:.75rem 0 0}
.htex-tt,.htex-code,code,pre{font-family:var(--mono-font);font-size:.9em}
.htex-code{background:var(--panel);padding:.05em .3em;border-radius:.2em}
.htex-sc{font-variant:small-caps}
pre{overflow-x:auto;background:var(--panel);padding:.75rem 1rem;border-radius:.4rem;
  line-height:1.5;word-break:normal;overflow-wrap:normal;white-space:pre}
blockquote{margin:1rem 0;padding:0 0 0 1rem;border-left:3px solid var(--rule);color:var(--muted)}
ul,ol,dl{padding-left:1.6rem}
.htex-list>li>p:first-child{margin-top:0}
.htex-list>li>p:last-child{margin-bottom:.3rem}
ol.htex-explicit{list-style:none;padding-left:1rem}
.htex-itemnum{font-variant-numeric:tabular-nums;margin-right:.2em}
ol.htex-explicit>li>p:first-child{display:inline}
dl.htex-description dt{font-weight:700;font-family:var(--sans-font)}
dl.htex-description dd{margin-left:1.5rem}
dl.htex-description dd>p:first-child{margin-top:.2rem}

/* 수식 */
math{font-family:var(--math-font);font-size:1.07em}
.htex-hangul,mi.htex-hangul,mo.htex-hangul{font-family:var(--math-hangul-font);font-style:normal}
mtext.htex-hangul-text{font-family:var(--body-font)}
.htex-display{margin:1rem 0;overflow-x:auto;overflow-y:hidden;max-width:100%;
  -webkit-overflow-scrolling:touch}
.htex-eqtable{border-collapse:collapse;width:100%;margin:0}
.htex-eqtable td{padding:.2rem 0;vertical-align:middle;border:0}
.htex-eqpad,.htex-eqno{width:3.5rem;min-width:3.5rem}
.htex-eqno{text-align:right;white-space:nowrap;font-family:var(--body-font);
  font-variant-numeric:tabular-nums;padding-left:1rem!important}
.htex-eqcell{white-space:nowrap}
.htex-eqcell.htex-c{text-align:center}
.htex-eqcell.htex-r{text-align:right;width:50%}
.htex-eqcell.htex-l{text-align:left}
.htex-eqcell.htex-gap{padding-left:2em!important}
mtd.htex-l{text-align:left}mtd.htex-c{text-align:center}mtd.htex-r{text-align:right}
mtd.htex-pair-a{padding-right:0}mtd.htex-pair-b{padding-left:0}
.htex-math-error{color:var(--err);background:var(--err-bg);padding:0 .25em;border-radius:.2em;
  white-space:pre-wrap}
.htex-param-error{color:var(--err)}

/* 정리·증명 */
.htex-theorem{margin:1.25rem 0;padding:.1rem 0 .1rem 1rem;border-left:3px solid var(--accent)}
.htex-theorem>p:first-child{margin-top:.4rem}
.htex-thm-head{font-family:var(--sans-font)}
.htex-env-theorem,.htex-env-lemma,.htex-env-proposition,.htex-env-corollary{font-style:normal}
.htex-env-definition,.htex-env-example,.htex-env-remark{border-left-color:var(--rule)}
.htex-proof{margin:1rem 0}
.htex-proof-head{font-style:italic;font-family:var(--sans-font)}
.htex-qed{display:block;text-align:right;line-height:1;color:var(--muted)}
details{margin:1rem 0;padding:.25rem .9rem;border:1px solid var(--rule);border-radius:.4rem}
details>summary{cursor:pointer;font-family:var(--sans-font);padding:.25rem 0}
details[open]>summary{border-bottom:1px solid var(--rule);margin-bottom:.4rem}
.htex-steps{padding-left:1.6rem}
.htex-step{margin:.4rem 0;padding-left:.25rem}
.htex-step::marker{color:var(--accent);font-family:var(--sans-font);font-weight:700}
.htex-step>p:first-child{margin-top:0}

/* 그림·표 */
figure{margin:1.5rem 0;text-align:center}
figcaption{font-family:var(--sans-font);font-size:.92rem;color:var(--muted);margin:.5rem 0}
.htex-float-name{font-weight:700;color:var(--fg)}
.htex-image{max-width:100%;height:auto}
.htex-picture pre{text-align:left;border:1px dashed var(--rule);background:transparent}
.htex-picture::before{content:"그림 (TikZ, 이 보기에서는 원문으로 표시)";display:block;
  font-family:var(--sans-font);font-size:.8rem;color:var(--muted);text-align:left}
.htex-table-wrap{overflow-x:auto;max-width:100%}
.htex-tabular{border-collapse:collapse;margin:0 auto;font-variant-numeric:tabular-nums}
.htex-tabular td{padding:.3rem .75rem;vertical-align:top}
.htex-tabular td.htex-l{text-align:left}.htex-tabular td.htex-c{text-align:center}
.htex-tabular td.htex-r{text-align:right}
.htex-tabular .htex-rule-left{border-left:1px solid var(--fg)}
.htex-tabular .htex-rule-right{border-right:1px solid var(--fg)}
.htex-tabular tr.htex-rule-above>td{border-top:1px solid var(--fg)}
.htex-tabular tr.htex-rule-below>td{border-bottom:1px solid var(--fg)}
.htex-transclusion{margin:1rem 0;padding:.5rem 1rem;border:1px dashed var(--accent);
  border-radius:.4rem;font-family:var(--sans-font);font-size:.92rem}

/* 링크·인용 */
.htex-broken{color:var(--err);text-decoration:underline dotted;cursor:help}
.htex-blocked-url{color:var(--muted);text-decoration:line-through}
.htex-cite{white-space:nowrap}
.htex-bibliography ol{list-style:none;padding-left:0}
.htex-bibliography li{padding-left:2.5em;text-indent:-2.5em;margin:.4rem 0}
.htex-bibnum{font-variant-numeric:tabular-nums;margin-right:.3em}
.htex-anchor{position:relative;top:-1rem}
:target{scroll-margin-top:1rem}
tr:target,li:target,section:target>.htex-heading,div:target{background:color-mix(in srgb,var(--accent) 12%,transparent)}

/* 각주 */
.htex-fnref{line-height:0}
.htex-fnref a{text-decoration:none;padding:0 .1em}
.htex-footnotes{margin-top:3rem;border-top:1px solid var(--rule);font-size:.92rem}
.htex-footnotes h2{font-size:1rem}
.htex-footnotes ol{list-style:none;padding-left:0}
.htex-footnotes li{display:flex;gap:.4em;align-items:baseline}
.htex-footnotes li>p{margin:.2rem 0}
.htex-fnback{text-decoration:none}

/* 매개변수 */
.htex-parameters{font-family:var(--sans-font);font-size:.9rem;background:var(--panel);
  border-radius:.4rem;padding:.5rem 1rem;margin:0 0 1.5rem}
.htex-parameters ul{list-style:none;padding:0;margin:.25rem 0 0;display:flex;flex-wrap:wrap;gap:.25rem 1.5rem}
.htex-param-label{font-weight:700}
.htex-param-range{color:var(--muted)}
math+output.htex-param{margin-left:.28em}
output.htex-param{font-family:var(--mono-font);font-variant-numeric:tabular-nums}

/* 오류·진단 */
.htex-error{color:var(--err);font-family:var(--mono-font);font-size:.9em}
pre.htex-error{background:var(--err-bg);white-space:pre-wrap;overflow-wrap:anywhere}
code.htex-error{background:var(--err-bg);padding:0 .2em;border-radius:.2em}
.htex-error-args{margin-left:.15em}
.htex-diagnostics{font-family:var(--sans-font);font-size:.88rem;margin-top:2rem}
.htex-diagnostics ul{padding-left:1.2rem}
.htex-diag-sev{font-weight:700}
.htex-diag-error .htex-diag-sev{color:var(--err)}
.htex-diag-warning .htex-diag-sev{color:var(--warn)}
.htex-diag-pos{color:var(--muted)}
@media print{
  :root{--fg:#000;--bg:#fff}
  details{border:0;padding:0}
  .htex-diagnostics,.htex-fnback{display:none}
}
""".strip()
