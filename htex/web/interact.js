/* HyperTeX 2.0 상호작용 스크립트 (docs/interaction-protocol.md 5절). 담당: G
 *
 * 호스트(웹 서버 G, 전용 뷰어 F)가 넣는 신뢰된 스크립트. 문서 자체는 스크립트를 담지 않으며,
 * 이 스크립트가 없어도 문서는 완전히 읽힌다(점진적 향상). 외부 라이브러리 없음, ES2017.
 *
 * 읽는 것
 *   <meta name="htex-picture-endpoint" content="…">   없으면 그림은 다시 그리지 않는다.
 *   <meta name="htex-fragment-endpoint" content="…">  없으면 다른 문서 미리보기를 하지 않는다.
 * 하는 것
 *   1. 매개변수 목록(aside.htex-parameters output.htex-param[data-min])마다 <input type="range">.
 *      움직이면 같은 data-param 의 모든 output·mn 값을 바꾸고, data-params 에 그 이름이 있는
 *      figure.htex-picture 를 그림 주소로 다시 받는다(150ms 묶음, 늦게 온 옛 응답 버림, 실패 시 기존 그림 유지).
 *   2. 참조 링크 미리보기: 마우스 올림·키보드 포커스·길게 누르기. 같은 문서는 노드를 복제(id 속성 제거),
 *      다른 문서는 조각 주소. 화면 밖으로 넘치지 않게 놓고 Esc 로 닫는다.
 * 호스트용 API (window.HTEX)
 *   HTEX.setParam(이름, 값), HTEX.getParams(), HTEX.closePreview(), HTEX.version
 *   document 에 'htex:paramchange' 사용자 이벤트 (detail: {name, value, params}).
 */
(function () {
  "use strict";
  if (window.HTEX && window.HTEX.version) return; // 두 번 넣어도 한 번만

  var DEBOUNCE_MS = 150;
  var HOVER_DELAY_MS = 350;
  var HIDE_DELAY_MS = 250;
  var LONG_PRESS_MS = 500;
  var SVG_NS = "http://www.w3.org/2000/svg";

  var reduceMotion = false;
  try {
    var mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    reduceMotion = mq.matches;
    var onMq = function (ev) { reduceMotion = ev.matches; };
    if (mq.addEventListener) mq.addEventListener("change", onMq);
    else if (mq.addListener) mq.addListener(onMq);
  } catch (e) { /* 오래된 브라우저 */ }

  function meta(name) {
    var m = document.querySelector('meta[name="' + name + '"]');
    var v = m && m.getAttribute("content");
    return v ? v : null;
  }

  function cssEscape(s) {
    if (window.CSS && CSS.escape) return CSS.escape(s);
    return String(s).replace(/[^A-Za-z0-9_ -￿-]/g, function (c) { return "\\" + c; });
  }

  /* ------------------------------------------------------------------ 스타일 */
  var STYLE = [
    ".htex-param-slider{display:inline-flex;align-items:center;gap:.5em;margin-left:.5em;vertical-align:middle}",
    ".htex-param-slider input[type=range]{width:9rem;max-width:40vw;accent-color:var(--accent,#1f5fa8);margin:0}",
    ".htex-param-slider input[type=range]:focus-visible{outline:2px solid var(--accent,#1f5fa8);outline-offset:2px}",
    "figure.htex-picture[aria-busy=true]>svg{opacity:.75}",
    "figure.htex-picture.htex-picture-live::before{content:none;display:none}",
    "figure.htex-picture>svg{display:block;max-width:100%;height:auto;margin:0 auto}",
    ".htex-preview{position:fixed;z-index:2147483000;box-sizing:border-box;",
    "  max-width:min(36rem,calc(100vw - 16px));max-height:min(50vh,28rem);overflow:auto;",
    "  padding:.6rem .9rem;background:var(--bg,#fdfdfc);color:var(--fg,#1d1d1f);",
    "  border:1px solid var(--rule,#d7d7d2);border-radius:.5rem;",
    "  box-shadow:0 6px 24px rgba(0,0,0,.18);font-size:.92rem;line-height:1.6;",
    "  opacity:0;transition:opacity .12s ease-out;overscroll-behavior:contain}",
    ".htex-preview.htex-preview-shown{opacity:1}",
    ".htex-preview.htex-no-motion{transition:none}",
    ".htex-preview>:first-child,.htex-preview .htex-fragment>:first-child{margin-top:0}",
    ".htex-preview>:last-child,.htex-preview .htex-fragment>:last-child{margin-bottom:0}",
    ".htex-preview section{margin:0}",
    ".htex-preview h2,.htex-preview h3,.htex-preview h4{margin:.2rem 0 .4rem;font-size:1.05rem}",
    ".htex-preview .htex-display{margin:.4rem 0;overflow-x:auto}",
    ".htex-preview .htex-fragment-head{font-family:var(--sans-font,system-ui,sans-serif);font-size:.8rem;",
    "  color:var(--muted,#5f6368);margin-bottom:.3rem}",
    ".htex-preview .htex-preview-status{color:var(--muted,#5f6368);font-family:var(--sans-font,system-ui,sans-serif);font-size:.85rem}",
    ".htex-preview ol,.htex-preview ul{margin:.2rem 0;padding-left:1.4rem}",
    "@media (prefers-reduced-motion:reduce){.htex-preview{transition:none}}"
  ].join("\n");

  function injectStyle() {
    if (document.getElementById("htex-interact-style")) return;
    var st = document.createElement("style");
    st.id = "htex-interact-style";
    st.textContent = STYLE;
    (document.head || document.documentElement).appendChild(st);
  }

  /* ------------------------------------------------------------------ 숫자 */
  function decimalsOf(x) {
    var s = String(x);
    if (/e-/i.test(s)) return Math.min(20, parseInt(s.split(/e-/i)[1], 10) + ((s.split(".")[1] || "").replace(/e.*/i, "").length));
    var i = s.indexOf(".");
    return i < 0 ? 0 : s.length - i - 1;
  }

  /* 단계가 없을 때: 범위의 약 1/100 을 1·2·5×10^k 로 반올림 */
  function niceStep(min, max) {
    var raw = (max - min) / 100;
    if (!(raw > 0) || !isFinite(raw)) return 1;
    var p = Math.pow(10, Math.floor(Math.log10(raw)));
    var m = raw / p;
    var nice = m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10;
    return Number((nice * p).toPrecision(12));
  }

  /* 렌더러 format_number 와 같은 모양: 1.0 → "1", 0.25 → "0.25" */
  function formatNumber(v, decimals) {
    if (!isFinite(v)) return String(v);
    var s = v.toFixed(Math.max(0, Math.min(decimals, 12)));
    if (s.indexOf(".") >= 0) s = s.replace(/0+$/, "").replace(/\.$/, "");
    if (s === "-0") s = "0";
    return s;
  }

  /* ------------------------------------------------------------------ 매개변수 */
  var params = {};      // 이름 → {min,max,step,decimals,value,input}
  var pictureEndpoint = null;
  var fragmentEndpoint = null;

  function setupSliders() {
    var outs = document.querySelectorAll("aside.htex-parameters output.htex-param[data-param][data-min][data-max]");
    for (var i = 0; i < outs.length; i++) {
      var out = outs[i];
      var name = out.getAttribute("data-param");
      if (params[name]) continue;
      var min = parseFloat(out.getAttribute("data-min"));
      var max = parseFloat(out.getAttribute("data-max"));
      var def = parseFloat(out.getAttribute("data-default"));
      if (!isFinite(min) || !isFinite(max) || max < min) continue;
      if (!isFinite(def)) def = min;
      var stepAttr = out.getAttribute("data-step");
      var step = stepAttr != null && parseFloat(stepAttr) > 0 ? parseFloat(stepAttr) : niceStep(min, max);
      var decimals = Math.max(decimalsOf(step), decimalsOf(min), decimalsOf(def));

      var li = out.closest("li") || out.parentNode;
      var symEl = li && li.querySelector(".htex-param-name");
      var sym = symEl ? symEl.textContent.trim() : name;

      var input = document.createElement("input");
      input.type = "range";
      input.min = String(min);
      input.max = String(max);
      input.step = String(step);
      input.value = String(def);
      input.className = "htex-param-input";
      input.setAttribute("data-param", name);
      input.setAttribute("aria-label", sym + " 값 (" + formatNumber(min, decimals) + "–" + formatNumber(max, decimals) + ")");
      input.setAttribute("aria-valuetext", sym + " = " + formatNumber(def, decimals));
      var wrap = document.createElement("span");
      wrap.className = "htex-param-slider";
      wrap.appendChild(input);
      out.parentNode.insertBefore(wrap, out.nextSibling);
      out.setAttribute("aria-live", "polite");

      params[name] = { name: name, min: min, max: max, step: step, decimals: decimals, value: def, def: def, input: input, sym: sym };
      input.addEventListener("input", onSliderInput);
      input.addEventListener("change", onSliderInput);
    }
    var label = document.querySelector("aside.htex-parameters .htex-param-label");
    if (label && Object.keys(params).length) label.textContent = "매개변수";
  }

  function onSliderInput(ev) {
    var name = ev.target.getAttribute("data-param");
    setParam(name, parseFloat(ev.target.value), ev.target);
  }

  function clampSnap(p, v) {
    if (!isFinite(v)) v = p.def;
    v = Math.min(p.max, Math.max(p.min, v));
    var k = Math.round((v - p.min) / p.step);
    var snapped = p.min + k * p.step;
    if (snapped > p.max + 1e-12) snapped -= p.step;
    return Number(snapped.toFixed(Math.min(12, p.decimals + 2)));
  }

  function setParam(name, value, fromInput) {
    var p = params[name];
    if (!p) return false;
    var v = clampSnap(p, Number(value));
    var changed = v !== p.value;
    p.value = v;
    var shown = formatNumber(v, p.decimals);
    if (fromInput !== p.input && String(p.input.value) !== String(v)) p.input.value = String(v);
    p.input.setAttribute("aria-valuetext", p.sym + " = " + shown);
    var els = document.querySelectorAll('.htex-param[data-param="' + cssEscape(name) + '"]');
    for (var i = 0; i < els.length; i++) {
      if (els[i].textContent !== shown) els[i].textContent = shown;
    }
    if (changed) {
      schedulePictures(name);
      try {
        document.dispatchEvent(new CustomEvent("htex:paramchange", { detail: { name: name, value: v, params: getParams() } }));
      } catch (e) { /* 무시 */ }
    }
    return true;
  }

  function getParams() {
    var o = {};
    Object.keys(params).forEach(function (k) { o[k] = params[k].value; });
    return o;
  }

  /* ------------------------------------------------------------------ 그림 */
  var dirty = {};          // 그림 id → true
  var timer = null;
  var seq = {};            // 그림 id → 마지막으로 보낸 요청 번호

  function picturesUsing(name) {
    var figs = document.querySelectorAll("figure.htex-picture[data-params][id]");
    var out = [];
    for (var i = 0; i < figs.length; i++) {
      var names = figs[i].getAttribute("data-params").split(/\s+/);
      if (names.indexOf(name) >= 0) out.push(figs[i]);
    }
    return out;
  }

  function schedulePictures(name) {
    if (!pictureEndpoint) return;
    var figs = picturesUsing(name);
    if (!figs.length) return;
    figs.forEach(function (f) { dirty[f.id] = true; });
    if (timer) clearTimeout(timer);
    timer = setTimeout(flushPictures, DEBOUNCE_MS);
  }

  function pictureURL(fig) {
    var names = fig.getAttribute("data-params").split(/\s+/).filter(Boolean);
    var q = "node=" + encodeURIComponent(fig.id);
    names.forEach(function (n) {
      if (params[n]) q += "&" + encodeURIComponent(n) + "=" + encodeURIComponent(String(params[n].value));
    });
    return pictureEndpoint + (pictureEndpoint.indexOf("?") >= 0 ? "&" : "?") + q;
  }

  function flushPictures() {
    timer = null;
    var ids = Object.keys(dirty);
    dirty = {};
    ids.forEach(function (id) {
      var fig = document.getElementById(id);
      if (fig) fetchPicture(fig);
    });
  }

  function fetchPicture(fig) {
    var id = fig.id;
    var my = (seq[id] || 0) + 1;
    seq[id] = my;
    fig.setAttribute("aria-busy", "true");
    fetch(pictureURL(fig), { credentials: "same-origin", headers: { "Accept": "image/svg+xml" } })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.text();
      })
      .then(function (text) {
        if (seq[id] !== my) return; // 늦게 온 옛 응답
        var svg = parseSVG(text);
        if (!svg) throw new Error("SVG 아님");
        replacePicture(fig, svg);
        fig.classList.add("htex-picture-live");
        fig.classList.remove("htex-picture-failed");
        fig.removeAttribute("data-htex-error");
      })
      .catch(function (err) {
        if (seq[id] !== my) return;
        fig.classList.add("htex-picture-failed");
        fig.setAttribute("data-htex-error", String(err && err.message || err));
      })
      .then(function () {
        if (seq[id] === my) fig.removeAttribute("aria-busy");
      });
  }

  /* 그림 주소의 응답은 호스트가 만든 것이지만, 한 번 더 걸러서 넣는다. */
  function parseSVG(text) {
    var doc;
    try { doc = new DOMParser().parseFromString(text, "image/svg+xml"); } catch (e) { return null; }
    var root = doc && doc.documentElement;
    if (!root || root.namespaceURI !== SVG_NS || root.localName !== "svg") return null;
    if (doc.getElementsByTagName("parsererror").length) return null;
    scrub(root);
    return document.importNode(root, true);
  }

  var BAD_TAGS = { script: 1, iframe: 1, object: 1, embed: 1, animate: 1, set: 1, handler: 1, listener: 1 };
  function scrub(el) {
    var all = [el].concat(Array.prototype.slice.call(el.getElementsByTagName("*")));
    for (var i = 0; i < all.length; i++) {
      var n = all[i];
      if (BAD_TAGS[(n.localName || "").toLowerCase()]) { if (n.parentNode) n.parentNode.removeChild(n); continue; }
      var attrs = Array.prototype.slice.call(n.attributes || []);
      for (var j = 0; j < attrs.length; j++) {
        var an = attrs[j].name.toLowerCase();
        var av = attrs[j].value;
        if (an.indexOf("on") === 0) n.removeAttribute(attrs[j].name);
        else if ((an === "href" || an === "xlink:href" || an === "src") && !/^#/.test(av.trim())) n.removeAttribute(attrs[j].name);
      }
    }
  }

  function replacePicture(fig, svg) {
    var old = null;
    for (var c = fig.firstElementChild; c; c = c.nextElementSibling) {
      if (c.localName === "svg" || c.localName === "pre") { old = c; break; }
    }
    if (old) fig.replaceChild(svg, old);
    else fig.insertBefore(svg, fig.firstChild);
  }

  /* ------------------------------------------------------------------ 미리보기 */
  var pop = null;           // 미리보기 창
  var popFor = null;        // 지금 미리보기를 띄운 링크
  var showTimer = null, hideTimer = null, pressTimer = null;
  var suppressClick = null;
  var fragCache = {};       // 조각 주소 → Promise<string|null>
  var popSeq = 0;

  var LINK_SELECTOR = "a.htex-ref, .htex-cite a[href^='#'], .htex-fnref a[href^='#']";

  function isPreviewLink(a) {
    if (!a || !a.matches || !a.matches(LINK_SELECTOR)) return false;
    if (a.closest(".htex-preview")) return false;
    return true;
  }

  function ensurePop() {
    if (pop) return pop;
    pop = document.createElement("div");
    pop.className = "htex-preview htex-doc-preview";
    pop.id = "htex-preview";
    pop.setAttribute("role", "tooltip");
    pop.hidden = true;
    pop.addEventListener("mouseenter", function () { clearTimeout(hideTimer); });
    pop.addEventListener("mouseleave", function () { scheduleHide(); });
    document.body.appendChild(pop);
    return pop;
  }

  /* 같은 문서 대상 → 미리보기로 보일 노드 (복제본) */
  function sameDocContent(id) {
    var target = document.getElementById(id);
    if (!target) return null;
    var block;
    var row = target.closest("tr.htex-eqrow");
    if (row) {
      var disp = row.closest(".htex-display");
      block = disp.cloneNode(true);
      var rows = block.querySelectorAll("tr.htex-eqrow");
      var idx = Array.prototype.indexOf.call(disp.querySelectorAll("tr.htex-eqrow"), row);
      for (var i = 0; i < rows.length; i++) if (i !== idx) rows[i].parentNode.removeChild(rows[i]);
      return stripIds(block);
    }
    var heading = target.closest("h1,h2,h3,h4,h5");
    if (heading && heading.parentNode && heading.parentNode.localName === "section") {
      var sec = heading.parentNode;
      block = document.createElement("section");
      block.className = sec.className;
      block.appendChild(heading.cloneNode(true));
      var n = 0;
      for (var c = heading.nextElementSibling; c && n < 2; c = c.nextElementSibling, n++) block.appendChild(c.cloneNode(true));
      if (n === 2 && heading.parentNode.children.length > 3) {
        var more = document.createElement("p");
        more.textContent = "…";
        block.appendChild(more);
      }
      return stripIds(block);
    }
    var host = target.closest("li.htex-item, li.htex-step, div.htex-item, .htex-theorem, .htex-proof, figure.htex-float, .htex-display, .htex-biblist>li, .htex-footnotes li, p, figure, details, .htex-transclusion, pre, blockquote");
    if (!host) host = target;
    if (host.localName === "li" || (host.localName === "div" && host.classList.contains("htex-item"))) {
      var list = host.parentNode;
      var wrapper = document.createElement(list && /^(ol|ul|dl)$/.test(list.localName) ? list.localName : "ul");
      if (list && list.className) wrapper.className = list.className;
      if (wrapper.localName === "ol" && host.getAttribute("data-step")) wrapper.setAttribute("start", host.getAttribute("data-step"));
      else if (wrapper.localName === "ol" && list) {
        var pos = Array.prototype.indexOf.call(list.children, host) + 1;
        var st = parseInt(list.getAttribute("start") || "1", 10);
        wrapper.setAttribute("start", String(st + pos - 1));
      }
      wrapper.appendChild(host.cloneNode(true));
      return stripIds(wrapper);
    }
    return stripIds(host.cloneNode(true));
  }

  function stripIds(node) {
    if (node.removeAttribute) node.removeAttribute("id");
    var all = node.querySelectorAll ? node.querySelectorAll("[id]") : [];
    for (var i = 0; i < all.length; i++) all[i].removeAttribute("id");
    var named = node.querySelectorAll ? node.querySelectorAll("a[name]") : [];
    for (var j = 0; j < named.length; j++) named[j].removeAttribute("name");
    // 미리보기 안 컨트롤은 탭 순서에서 뺀다
    var focusables = node.querySelectorAll ? node.querySelectorAll("a[href], input, button, summary, [tabindex]") : [];
    for (var k = 0; k < focusables.length; k++) focusables[k].setAttribute("tabindex", "-1");
    return node;
  }

  function hashOf(a) {
    var h = a.getAttribute("href") || "";
    var i = h.indexOf("#");
    if (i < 0) return "";
    try { return decodeURIComponent(h.slice(i + 1)); } catch (e) { return h.slice(i + 1); }
  }

  function isSameDocLink(a) {
    var h = a.getAttribute("href") || "";
    if (h.charAt(0) === "#") return true;
    if (a.hasAttribute("data-doc")) {
      try {
        var u = new URL(h, document.baseURI);
        var here = new URL(document.baseURI);
        return u.origin === here.origin && u.pathname === here.pathname && u.search === here.search;
      } catch (e) { return false; }
    }
    return false;
  }

  function fragmentContent(a) {
    if (!fragmentEndpoint) return null;
    var href = a.getAttribute("href") || "";
    var label = a.getAttribute("data-label") || hashOf(a);
    if (!label) return null;
    var docURL;
    try { docURL = new URL(href, document.baseURI); } catch (e) { return null; }
    docURL.hash = "";
    var ep;
    try { ep = new URL(fragmentEndpoint, document.baseURI); } catch (e) { return null; }
    // 웹 서버의 조각 주소는 자기 출처 문서만 다룬다: 다른 출처 문서는 요청하지 않는다
    if (/^https?:$/.test(ep.protocol) && /^https?:$/.test(docURL.protocol) && docURL.origin !== ep.origin) return null;
    var doc = (docURL.origin === ep.origin && /^https?:$/.test(docURL.protocol)) ? docURL.pathname + docURL.search : docURL.href;
    ep.searchParams.set("doc", doc);
    ep.searchParams.set("label", label);
    var key = ep.href;
    if (!fragCache[key]) {
      fragCache[key] = fetch(key, { credentials: "same-origin", headers: { "Accept": "text/html" } })
        .then(function (r) { return r.ok ? r.text() : null; })
        .catch(function () { return null; })
        .then(function (t) { if (t == null) delete fragCache[key]; return t; });
    }
    return fragCache[key];
  }

  function htmlToNode(text) {
    var doc = new DOMParser().parseFromString(text, "text/html");
    var bad = doc.querySelectorAll("script, iframe, object, embed, link, meta, style, base, form");
    for (var i = 0; i < bad.length; i++) bad[i].parentNode.removeChild(bad[i]);
    var all = doc.body.querySelectorAll("*");
    for (var k = 0; k < all.length; k++) {
      var attrs = Array.prototype.slice.call(all[k].attributes);
      for (var j = 0; j < attrs.length; j++) {
        var n = attrs[j].name.toLowerCase();
        if (n.indexOf("on") === 0 || (n === "style" && /url\(|expression/i.test(attrs[j].value))) all[k].removeAttribute(attrs[j].name);
        else if ((n === "href" || n === "src" || n === "xlink:href") && /^\s*(javascript|data|vbscript):/i.test(attrs[j].value)) all[k].removeAttribute(attrs[j].name);
      }
    }
    var frag = document.createElement("div");
    var kids = Array.prototype.slice.call(doc.body.childNodes);
    for (var q = 0; q < kids.length; q++) frag.appendChild(document.importNode(kids[q], true));
    // 미리보기 값은 지금의 매개변수 값으로 맞춘다
    var ps = frag.querySelectorAll(".htex-param[data-param]");
    for (var m = 0; m < ps.length; m++) {
      var p = params[ps[m].getAttribute("data-param")];
      if (p) ps[m].textContent = formatNumber(p.value, p.decimals);
    }
    return stripIds(frag);
  }

  function status(text) {
    var s = document.createElement("p");
    s.className = "htex-preview-status";
    s.textContent = text;
    return s;
  }

  function showPreview(a) {
    clearTimeout(hideTimer);
    clearTimeout(showTimer);
    if (popFor === a && pop && !pop.hidden) return;
    var content = null, promise = null;
    if (isSameDocLink(a)) {
      var id = hashOf(a);
      if (!id) return;
      content = sameDocContent(id);
      if (!content) return;
    } else if (a.hasAttribute("data-doc")) {
      promise = fragmentContent(a);
      if (!promise) return;
    } else {
      return;
    }
    var my = ++popSeq;
    var p = ensurePop();
    if (popFor && popFor !== a) popFor.removeAttribute("aria-describedby");
    popFor = a;
    p.textContent = "";
    p.appendChild(content || status("불러오는 중…"));
    open(p, a);
    if (promise) {
      promise.then(function (text) {
        if (my !== popSeq || popFor !== a) return;
        p.textContent = "";
        if (text) p.appendChild(htmlToNode(text));
        else { hidePreview(); return; }
        place(p, a);
      });
    }
  }

  function open(p, a) {
    p.classList.remove("htex-preview-shown");
    p.classList.toggle("htex-no-motion", reduceMotion);
    p.hidden = false;
    a.setAttribute("aria-describedby", p.id);
    place(p, a);
    if (reduceMotion) p.classList.add("htex-preview-shown");
    else requestAnimationFrame(function () { p.classList.add("htex-preview-shown"); });
  }

  /* 링크 아래(자리가 없으면 위)에, 화면 안에 들어오게 */
  function place(p, a) {
    var margin = 8, gap = 6;
    var vw = document.documentElement.clientWidth || window.innerWidth;
    var vh = document.documentElement.clientHeight || window.innerHeight;
    var rects = a.getClientRects();
    var r = rects.length ? rects[0] : a.getBoundingClientRect();
    p.style.left = "0px"; p.style.top = "0px";
    p.style.maxHeight = "";
    var w = p.offsetWidth, h = p.offsetHeight;
    var below = vh - r.bottom - gap - margin, above = r.top - gap - margin;
    var top;
    if (h <= below || below >= above) {
      top = r.bottom + gap;
      if (h > below) { p.style.maxHeight = Math.max(80, below) + "px"; h = p.offsetHeight; }
    } else {
      if (h > above) { p.style.maxHeight = Math.max(80, above) + "px"; h = p.offsetHeight; }
      top = r.top - gap - h;
    }
    var left = Math.min(Math.max(margin, r.left), Math.max(margin, vw - w - margin));
    top = Math.min(Math.max(margin, top), Math.max(margin, vh - h - margin));
    p.style.left = Math.round(left) + "px";
    p.style.top = Math.round(top) + "px";
  }

  function hidePreview() {
    clearTimeout(showTimer); clearTimeout(hideTimer);
    popSeq++;
    if (!pop || pop.hidden) { popFor = null; return; }
    pop.hidden = true;
    pop.classList.remove("htex-preview-shown");
    pop.textContent = "";
    if (popFor) popFor.removeAttribute("aria-describedby");
    popFor = null;
  }

  function scheduleShow(a, delay) {
    clearTimeout(showTimer);
    showTimer = setTimeout(function () { showPreview(a); }, delay);
  }
  function scheduleHide() {
    clearTimeout(showTimer);
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hidePreview, HIDE_DELAY_MS);
  }

  function linkFrom(ev) {
    var t = ev.target;
    if (!t || !t.closest) t = t && t.parentElement;
    var a = t && t.closest ? t.closest("a") : null;
    return isPreviewLink(a) ? a : null;
  }

  function setupPreviews() {
    document.addEventListener("mouseover", function (ev) {
      var a = linkFrom(ev);
      if (a) {
        if (a === popFor) clearTimeout(hideTimer);
        else scheduleShow(a, HOVER_DELAY_MS);
      }
    });
    document.addEventListener("mouseout", function (ev) {
      var a = linkFrom(ev);
      if (!a) return;
      var to = ev.relatedTarget;
      if (to && (a.contains(to) || (pop && pop.contains(to)))) return;
      if (a === popFor) scheduleHide(); else clearTimeout(showTimer);
    });
    document.addEventListener("focusin", function (ev) {
      var a = linkFrom(ev);
      if (a) showPreview(a);
    });
    document.addEventListener("focusout", function (ev) {
      var a = linkFrom(ev);
      if (a && a === popFor) scheduleHide();
    });
    document.addEventListener("keydown", function (ev) {
      if ((ev.key === "Escape" || ev.key === "Esc") && pop && !pop.hidden) {
        hidePreview();
        ev.stopPropagation();
      }
    });
    // 길게 누르기 (터치)
    var pressStart = null;
    document.addEventListener("touchstart", function (ev) {
      var a = linkFrom(ev);
      if (!a) {
        if (pop && !pop.hidden && !(ev.target && pop.contains(ev.target))) hidePreview();
        return;
      }
      var t = ev.touches[0];
      pressStart = { x: t.clientX, y: t.clientY, a: a };
      clearTimeout(pressTimer);
      pressTimer = setTimeout(function () {
        suppressClick = a;
        showPreview(a);
      }, LONG_PRESS_MS);
    }, { passive: true });
    document.addEventListener("touchmove", function (ev) {
      if (!pressStart) return;
      var t = ev.touches[0];
      if (Math.abs(t.clientX - pressStart.x) > 10 || Math.abs(t.clientY - pressStart.y) > 10) {
        clearTimeout(pressTimer); pressStart = null;
      }
    }, { passive: true });
    document.addEventListener("touchend", function () { clearTimeout(pressTimer); pressStart = null; }, { passive: true });
    document.addEventListener("touchcancel", function () { clearTimeout(pressTimer); pressStart = null; }, { passive: true });
    document.addEventListener("contextmenu", function (ev) {
      // 길게 누르기로 미리보기를 띄웠으면 브라우저의 링크 메뉴는 막는다
      if (suppressClick && linkFrom(ev) === suppressClick) ev.preventDefault();
    });
    document.addEventListener("click", function (ev) {
      var a = linkFrom(ev);
      if (a && suppressClick === a) { ev.preventDefault(); suppressClick = null; return; }
      suppressClick = null;
      if (pop && !pop.hidden && !(ev.target && pop.contains(ev.target))) hidePreview();
    }, true);
    window.addEventListener("scroll", function () { if (popFor && pop && !pop.hidden) place(pop, popFor); }, { passive: true });
    window.addEventListener("resize", function () { if (popFor && pop && !pop.hidden) place(pop, popFor); });
  }

  /* ------------------------------------------------------------------ 시작 */
  function init() {
    pictureEndpoint = meta("htex-picture-endpoint");
    fragmentEndpoint = meta("htex-fragment-endpoint");
    document.documentElement.classList.add("htex-js");
    injectStyle();
    setupSliders();
    setupPreviews();
  }

  window.HTEX = {
    version: "2.0",
    setParam: function (name, value) { return setParam(name, value, null); },
    getParams: getParams,
    closePreview: hidePreview,
    _formatNumber: formatNumber,
    _niceStep: niceStep
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
