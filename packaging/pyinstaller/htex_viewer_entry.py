"""PyInstaller 실행 파일의 진입점. htex.__main__.gui_main 을 부른다.

- 리눅스에서 HTEX_NO_SANDBOX=1 이면 QtWebEngine 샌드박스를 끈다(컨테이너·일부 배포판용).
  기본은 샌드박스를 켠 채로 둔다.
- 스킴 등록(register_schemes)은 htex.viewer.app.run 이 QApplication 전에 한다.
  여기서는 QApplication 을 만들지 않는다.
"""
import json
import os
import sys


def _main() -> int:
    if sys.platform.startswith("linux") and os.environ.get("HTEX_NO_SANDBOX") == "1":
        flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
        if "--no-sandbox" not in flags:
            os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (flags + " --no-sandbox").strip()
    if os.environ.get("HTEX_SMOKE_OUT"):
        _install_smoke(os.environ["HTEX_SMOKE_OUT"])
    # 실행 파일 안에서 --serve 등 콘솔 명령도 쓸 수 있게: 첫 인수가 htex 하위 명령이면 CLI 로.
    from htex.__main__ import gui_main, main
    if len(sys.argv) > 1 and sys.argv[1] in ("parse", "html", "serve", "build", "view"):
        return main(sys.argv[1:])
    return gui_main(sys.argv[1:])


def _install_smoke(out: str) -> None:
    """빌드 확인용 (packaging/smoke_test.py, CI). HTEX_SMOKE_OUT=결과 경로 접두어 이면
    첫 문서를 다 불러온 뒤 창 스크린숏(<접두어>.png)과 상태(<접두어>.json)를 남기고 끝낸다.

    뷰어 코드 구조(창·탭·QApplication 하위 클래스)에 기대지 않도록 QApplication.exec 자체를 감싸고,
    화면의 첫 QWebEngineView 를 찾는다. QApplication 을 여기서 만들지는 않는다."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    timeout_ms = int(os.environ.get("HTEX_SMOKE_TIMEOUT_MS", "20000"))
    orig_exec = QApplication.exec

    def find_view(app):
        from PySide6.QtWebEngineWidgets import QWebEngineView
        views = [w for w in app.allWidgets() if isinstance(w, QWebEngineView) and w.isVisible()]
        return views[0] if views else None

    def smoke_exec(*_args):
        # QApplication.exec 는 정적 메서드라 app.exec() 로 불러도 인수가 오지 않을 수 있다
        app = QApplication.instance()
        state = {"loaded": False, "hooked": None, "done": False}

        def write(res):
            if state["done"]:
                return
            state["done"] = True
            with open(out + ".json", "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False)
            app.exit(0 if res.get("ok") else 3)

        def finish():
            view = find_view(app)
            if view is None:
                return write({"ok": False, "error": "no web view"})
            win = view.window()

            def got(js_state):
                win.grab().save(out + ".png")
                write({"ok": bool(state["loaded"]), "title": view.title(), "url": view.url().toString(),
                       "js": js_state, "frozen": bool(getattr(sys, "frozen", False))})
            view.page().runJavaScript(
                "JSON.stringify({htex: typeof window.HTEX, math: document.querySelectorAll('math').length,"
                " svg: document.querySelectorAll('svg').length})", 0, got)

        def poll():
            view = find_view(app)
            if view is None or state["hooked"] is view:
                return
            state["hooked"] = view

            def on_load(ok):
                if ok and not state["loaded"]:
                    state["loaded"] = True
                    QTimer.singleShot(1500, finish)     # 상호작용 스크립트·그림이 자리 잡을 시간
            view.loadFinished.connect(on_load)

        t = QTimer(app)
        t.timeout.connect(poll)
        t.start(50)
        QTimer.singleShot(timeout_ms, finish)
        return orig_exec()

    QApplication.exec = smoke_exec


if __name__ == "__main__":
    sys.exit(_main())
