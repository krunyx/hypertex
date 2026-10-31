"""L: 북마크 저장소, 시작 페이지 (Qt 없음)."""
from __future__ import annotations

import json

from htex.viewer.bookmarks import DEFAULT_BOOKMARKS, Bookmark, BookmarkStore, same_address
from htex.viewer.core import ViewerCore
from htex.viewer import startpage


def test_first_run_seeds_defaults_and_saves(tmp_path):
    path = tmp_path / "b" / "bookmarks.json"
    st = BookmarkStore.load(path)
    assert [b.url for b in st.bar] == [d["url"] for d in DEFAULT_BOOKMARKS]
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1 and len(data["bar"]) == len(DEFAULT_BOOKMARKS)


def test_deleted_defaults_do_not_come_back(tmp_path):
    path = tmp_path / "bookmarks.json"
    st = BookmarkStore.load(path)
    for b in list(st.bar):
        st.remove(b)
    assert BookmarkStore.load(path).bar == []


def test_add_find_folder_move_update(tmp_path):
    st = BookmarkStore.load(tmp_path / "b.json", seed=False)
    a = st.add("문서 A", "htex://ex.org/a.htex")
    assert st.add("다시", "htex://ex.org/a.htex/") is a          # 같은 주소면 하나 (끝의 / 무시)
    f = st.add_folder("논문")
    b = st.add("B", "/home/u/b.tex", folder=f)
    assert st.find("/home/u/b.tex") == (f, b) and st.contains("htex://ex.org/a.htex")
    st.update(b, title="B2", folder=None)                       # 폴더 → 북마크바
    assert st.parent_of(b) is None and st.bar[-1] is b and b.title == "B2"
    st.update(a, folder=f)
    assert f.children == [a]
    st.move(b, 0)
    assert st.bar[0] is b
    again = BookmarkStore.load(tmp_path / "b.json")
    assert [x.title for x in again.bar] == ["B2", "논문"] and again.bar[1].children[0].url == a.url


def test_change_listener_and_snapshot_is_copy(tmp_path):
    st = BookmarkStore.load(tmp_path / "b.json", seed=False)
    seen = []
    st.on_change(lambda: seen.append(len(st.bar)))
    st.add("x", "https://x.org/")
    snap = st.snapshot()
    snap[0].title = "바꿈"
    assert seen == [1] and st.bar[0].title == "x"


def test_broken_file_is_kept_aside(tmp_path):
    path = tmp_path / "bookmarks.json"
    path.write_text("{ 깨진", encoding="utf-8")
    st = BookmarkStore.load(path)
    assert st.bar == [] and (tmp_path / "bookmarks.json.broken").exists()


def test_from_json_rejects_bad_items_and_nested_folders():
    assert Bookmark.from_json({"title": "x"}) is None
    f = Bookmark.from_json({"title": "f", "children": [{"title": "a", "url": "u"},
                                                       {"title": "g", "children": []}]})
    assert f.is_folder and [c.url for c in f.children] == ["u"]
    assert same_address(" https://a.org/ ", "https://a.org") and not same_address("a", "b")


# ---------------------------------------------------------------- 시작 페이지
def test_start_page_lists_bookmarks_without_scripts():
    items = [Bookmark("웹", "https://krunyx.com/"), Bookmark("노트", "/home/u/n.htex"),
             Bookmark("폴더", children=[Bookmark("숨김", "https://x/")])]
    page = startpage.render(items, "dark")
    assert 'data-theme="dark"' in page and "<script" not in page
    assert startpage.open_url("/home/u/n.htex") in page and "https%3A%2F%2Fkrunyx.com%2F" in page
    assert "숨김" not in page                     # 폴더는 바로가기에 안 나온다
    assert 'action="htexapp://start/go"' in page


def test_start_requests_are_parsed():
    p = startpage.parse_request
    assert p("htexapp://start/go?q=htex%3A%2F%2Fa.org%2Fx.htex") == ("go", "htex://a.org/x.htex")
    assert p("htexapp://start/open?u=%2Fhome%2Fu%2Fx.tex") == ("open", "/home/u/x.tex")
    assert p("htexapp://start/action?do=open-file") == ("action", "open-file")
    assert p("htexapp://start/go?q=") is None and p("htexapp://start/") is None
    assert p("htexapp://picture/go?q=x") is None


def test_core_serves_start_page_only_to_the_viewer():
    core = ViewerCore()
    core.start_bookmarks = lambda: [Bookmark("타일", "https://t.org/")]
    r = core.respond("htexapp://start/")
    assert r.status == 200 and "타일" in r.text and "default-src 'none'" in r.headers["Content-Security-Policy"]
    assert core.respond("htexapp://start/", "https://evil.example").status == 403
    assert core.respond("htexapp://start/open?u=x").status == 404      # 창이 가로채는 주소
    assert core.display_address("htexapp://start/") == ""
    core.start_bookmarks = lambda: 1 / 0                                # 실패해도 뜬다
    assert core.respond("htexapp://start/").status == 200
