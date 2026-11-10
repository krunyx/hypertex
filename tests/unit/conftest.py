"""pytest 공통 설정."""
from __future__ import annotations

import os
import tempfile

# 화면 글자는 한국어 원문 기준으로 시험한다 (영어는 test_P_i18n.py 가 따로). 하위 프로세스도 물려받는다.
os.environ["HTEX_LANG"] = "ko"

# 뷰어 테스트가 실제 사용자 데이터(북마크·세션·설정)를 읽거나 쓰지 않게 (v0.8.1). macOS·윈도는 데이터 폴더가
# HOME·XDG 변수를 따르지 않으므로 HOME 만 바꾸는 것으로는 부족하다. 세션 복원은 기본으로 끈다
# (켜 두면 run() 을 부르는 테스트들이 서로의 탭을 다시 연다). 세션을 시험하는 테스트는 둘 다 직접 준다.
os.environ["HTEX_DATA_DIR"] = tempfile.mkdtemp(prefix="htex-test-data-")
os.environ["HTEX_VIEWER_SESSION"] = "0"


def pytest_make_parametrize_id(config, val, argname):
    """긴 매개변수 값은 테스트 이름을 짧게 만든다.

    윈도는 환경 변수 하나가 32,767자를 넘을 수 없는데, pytest 는 테스트 이름을 PYTEST_CURRENT_TEST 에 넣는다.
    거대한 입력(긴 TikZ 경로, 상한 시험용 바이트열)을 매개변수로 쓰는 테스트가 윈도에서 깨지지 않게 한다."""
    if isinstance(val, (str, bytes)) and len(val) > 60:
        head = val[:40]
        return f"{head!r}…len{len(val)}"
    return None
