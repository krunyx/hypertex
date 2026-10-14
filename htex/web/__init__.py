"""웹 폴백 (명세 원칙 5, 2절 웹 폴백). (담당: G, 2단계)

일반 브라우저에서 HyperTeX 문서를 읽게 하는 두 가지 방법과 그 둘이 함께 쓰는 상호작용 스크립트.

- serve(root, host, port): 표준 라이브러리 http.server 기반 개발·열람용 서버 (htex/web/server.py).
  .htex/.tex 를 그때그때 HTML로 바꿔 주고, 그림 주소·조각 주소·interact.js 를 제공한다.
- build(root, out): 정적 사이트 (htex/web/build.py). 문서마다 .html, 정적 파일 복사, 목록 index.html.
- interact.js: docs/interaction-protocol.md 5절의 상호작용 스크립트. 전용 뷰어(F)도 같은 파일을 쓴다.
  INTERACT_JS_PATH 로 파일 위치를, interact_js() 로 내용을 얻는다.
- render_fragment(tree, label, ...): 라벨 블록 하나의 HTML 조각 (조각 주소 응답 본문). 뷰어도 쓸 수 있다.

계약은 docs/interaction-protocol.md. 외부 패키지 없음.
"""
from __future__ import annotations

from .common import INTERACT_JS_PATH, interact_js
from .fragment import render_fragment

__all__ = ["INTERACT_JS_PATH", "interact_js", "render_fragment", "serve", "make_server", "build"]


def serve(*args, **kwargs):
    from .server import serve as _serve
    return _serve(*args, **kwargs)


def make_server(*args, **kwargs):
    from .server import make_server as _make
    return _make(*args, **kwargs)


def build(*args, **kwargs):
    from .build import build as _build
    return _build(*args, **kwargs)
