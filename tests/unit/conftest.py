"""pytest 공통 설정."""
from __future__ import annotations


def pytest_make_parametrize_id(config, val, argname):
    """긴 매개변수 값은 테스트 이름을 짧게 만든다.

    윈도는 환경 변수 하나가 32,767자를 넘을 수 없는데, pytest 는 테스트 이름을 PYTEST_CURRENT_TEST 에 넣는다.
    거대한 입력(긴 TikZ 경로, 상한 시험용 바이트열)을 매개변수로 쓰는 테스트가 윈도에서 깨지지 않게 한다."""
    if isinstance(val, (str, bytes)) and len(val) > 60:
        head = val[:40]
        return f"{head!r}…len{len(val)}"
    return None
