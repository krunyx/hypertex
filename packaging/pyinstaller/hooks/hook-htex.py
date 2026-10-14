# PyInstaller 훅: htex 의 하위 모듈(지연 import 포함)과 .py 아닌 패키지 데이터(interact.js 등).
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = collect_submodules("htex")
datas = collect_data_files("htex", excludes=["**/__pycache__/**", "**/*.pyc"])
