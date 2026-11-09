// HyperTeX 뷰어의 원문 편집기 (10단계 Q). esbuild 로 htex/viewer/editor.js 하나에 묶는다.
// 창(Python)과는 QWebChannel 의 bridge 객체로 말한다:
//   JS → Python : bridge.init(cb) 처음 상태 받기, bridge.created() 편집기 준비됨, bridge.changed(text) 내용 바뀜(잠깐 멈추면), bridge.touched() 첫 수정
//   Python → JS : window.HtexEditor.setText / setDiagnostics / setDark / openSearch / gotoLine / focus / getText
import {EditorState, Compartment} from "@codemirror/state";
import {EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter,
        drawSelection, dropCursor, rectangularSelection, crosshairCursor,
        highlightSpecialChars} from "@codemirror/view";
import {defaultKeymap, history, historyKeymap, indentWithTab} from "@codemirror/commands";
import {syntaxHighlighting, defaultHighlightStyle, bracketMatching, foldGutter, foldKeymap,
        indentOnInput, StreamLanguage} from "@codemirror/language";
import {searchKeymap, highlightSelectionMatches, openSearchPanel} from "@codemirror/search";
import {closeBrackets, closeBracketsKeymap} from "@codemirror/autocomplete";
import {setDiagnostics, lintGutter} from "@codemirror/lint";
import {markdown} from "@codemirror/lang-markdown";
import {html} from "@codemirror/lang-html";
import {stex} from "@codemirror/legacy-modes/mode/stex";
import {oneDark} from "@codemirror/theme-one-dark";

const KO = {
  "Find": "찾기", "Replace": "바꿀 말", "next": "다음", "previous": "이전", "all": "모두",
  "match case": "대소문자 구분", "regexp": "정규식", "by word": "단어 단위", "replace": "바꾸기",
  "replace all": "모두 바꾸기", "close": "닫기", "current match": "현재 위치", "on line": "줄",
  "Go to line": "줄로 이동", "go": "이동", "Folded lines": "접힌 줄", "Unfolded lines": "펼친 줄",
  "Fold line": "줄 접기", "Unfold line": "줄 펼치기", "Diagnostics": "진단", "No diagnostics": "진단 없음",
  "Selection deleted": "선택 지움", "replaced match on line $": "$ 줄을 바꿈",
  "replaced $ matches": "$ 군데를 바꿈", "Control character": "제어 문자",
};

function language(mode) {
  if (mode === "md") return markdown();
  if (mode === "html") return html();
  return StreamLanguage.define(stex);
}

const light = EditorView.theme({
  "&": {backgroundColor: "#ffffff", color: "#1f1f1f"},
  ".cm-gutters": {backgroundColor: "#f8f9fa", color: "#80868b", borderRight: "1px solid #e3e3e3"},
  ".cm-activeLineGutter": {backgroundColor: "#e8f0fe"},
  ".cm-activeLine": {backgroundColor: "#f6f8fc"},
});
const base = EditorView.theme({
  "&": {height: "100%", fontSize: "13.5px"},
  ".cm-scroller": {fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, 'D2Coding', 'Noto Sans Mono CJK KR', monospace",
                   lineHeight: "1.55"},
  ".cm-content": {padding: "8px 0"},
  "&.cm-focused": {outline: "none"},
});

let view = null, bridge = null, timer = null, quiet = false, touched = false;
const themeSlot = new Compartment();

function send() {
  timer = null;
  if (bridge) bridge.changed(view.state.doc.toString());
}

function create(init) {
  const parent = document.getElementById("editor");
  const ext = [
    lineNumbers(), highlightActiveLineGutter(), highlightSpecialChars(), history(), foldGutter(),
    drawSelection(), dropCursor(), EditorState.allowMultipleSelections.of(true), indentOnInput(),
    syntaxHighlighting(defaultHighlightStyle, {fallback: true}), bracketMatching(), closeBrackets(),
    rectangularSelection(), crosshairCursor(), highlightActiveLine(), highlightSelectionMatches(),
    lintGutter(), EditorView.lineWrapping, base,
    keymap.of([...closeBracketsKeymap, ...defaultKeymap, ...searchKeymap, ...historyKeymap,
               ...foldKeymap, indentWithTab]),
    language(init.mode),
    themeSlot.of(init.dark ? oneDark : light),
    EditorView.updateListener.of(u => {
      if (!u.docChanged || quiet) return;
      if (!touched) { touched = true; if (bridge) bridge.touched(); }
      clearTimeout(timer);
      timer = setTimeout(send, init.delay || 250);
    }),
  ];
  if (init.lang === "ko") ext.push(EditorState.phrases.of(KO));
  if (init.readOnly) ext.push(EditorState.readOnly.of(true));
  view = new EditorView({state: EditorState.create({doc: init.text, extensions: ext}), parent});
  view.focus();
  document.documentElement.setAttribute("data-ready", "1");
}

function lineSpan(doc, d) {
  const n = Math.max(1, Math.min(doc.lines, d.line || 1));
  const line = doc.line(n);
  const from = Math.min(line.to, line.from + Math.max(0, (d.col || 1) - 1));
  let to = line.to;
  if (d.endLine) {
    const e = doc.line(Math.max(n, Math.min(doc.lines, d.endLine)));
    to = Math.min(e.to, e.from + Math.max(0, (d.endCol || 1) - 1));
  }
  if (to <= from) to = Math.min(line.to, from + 1);
  return {from, to: Math.max(from, to)};
}

window.HtexEditor = {
  setText(text) {
    quiet = true;
    view.dispatch({changes: {from: 0, to: view.state.doc.length, insert: text}});
    quiet = false;
    touched = false;
  },
  markClean() { touched = false; },
  getText() { return view.state.doc.toString(); },
  flush() { if (timer) { clearTimeout(timer); send(); } },
  setDiagnostics(list) {
    const doc = view.state.doc;
    const ds = (list || []).map(d => Object.assign(lineSpan(doc, d),
      {severity: d.severity === "error" ? "error" : "warning", message: d.message || d.code || ""}));
    view.dispatch(setDiagnostics(view.state, ds));
  },
  setDark(on) { view.dispatch({effects: themeSlot.reconfigure(on ? oneDark : light)}); },
  openSearch() { openSearchPanel(view); },
  gotoLine(n) {
    const line = view.state.doc.line(Math.max(1, Math.min(view.state.doc.lines, n)));
    view.dispatch({selection: {anchor: line.from}, scrollIntoView: true});
    view.focus();
  },
  focus() { view.focus(); },
  lines() { return view.state.doc.lines; },
  // 사용자가 친 것처럼 n 째 줄 앞에 글자를 넣는다 (시험용)
  typeAt(n, text) {
    const line = view.state.doc.line(Math.max(1, Math.min(view.state.doc.lines, n)));
    view.dispatch({changes: {from: line.from, insert: text}, userEvent: "input.type"});
  },
};

function start() {
  /* global QWebChannel, qt */
  if (typeof QWebChannel === "undefined" || typeof qt === "undefined") {
    create({text: "", mode: "tex", dark: false, lang: "en"});      // 테스트·미리보기용
    return;
  }
  new QWebChannel(qt.webChannelTransport, ch => {
    bridge = ch.objects.bridge;
    bridge.init(s => { create(JSON.parse(s)); bridge.created(); });
  });
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
else start();
