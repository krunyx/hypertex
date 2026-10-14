"""HyperTeX 전용 뷰어 (명세 8절). (담당: F)

- core: Qt 없는 부분 (주소, 가져오기, 캐시, 히스토리, 조각·그림 응답). 테스트의 중심.
- app: PySide6 + QtWebEngine 창. `python -m htex view [파일|주소]`.
"""
from .core import History, TreeCache, ViewerCore, ViewerError, classify_input

__all__ = ["History", "TreeCache", "ViewerCore", "ViewerError", "classify_input"]
