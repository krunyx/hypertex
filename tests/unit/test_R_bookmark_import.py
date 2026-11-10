"""R: 북마크 가져오기 (v0.8.1) — Chromium 프로필 JSON, HTML 북마크 파일, 중첩 폴더."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from htex.viewer import bookmark_import as bi
from htex.viewer.bookmarks import MAX_DEPTH, Bookmark, BookmarkStore


def chromium_doc() -> dict:
    return {"version": 1, "roots": {
        "bookmark_bar": {"type": "folder", "name": "북마크바", "children": [
            {"type": "url", "name": "arXiv", "url": "https://arxiv.org/"},
            {"type": "folder", "name": "물리", "children": [
                {"type": "url", "name": "INSPIRE", "url": "https://inspirehep.net/"},
                {"type": "folder", "name": "강의", "children": [
                    {"type": "url", "name": "노트", "url": "file:///Users/u/notes/qft.htex"}]}]},
            {"type": "url", "name": "북마크릿", "url": "javascript:alert(1)"},
            {"type": "url", "name": "설정", "url": "chrome://settings/"}]},
        "other": {"type": "folder", "name": "기타", "children": [
            {"type": "url", "name": "KISTEP", "url": "https://www.kistep.re.kr/"}]},
        "synced": {"type": "folder", "name": "모바일", "children": [
            {"type": "url", "name": "뉴스", "url": "https://news.example/"}]}}}


# ---------------------------------------------------------------- 주소
def test_clean_url_skips_browser_internal_and_turns_file_urls_into_paths():
    assert bi.clean_url("javascript:void(0)") is None
    assert bi.clean_url("chrome://settings") is None and bi.clean_url("about:blank") is None
    assert bi.clean_url("  https://a.org/x  ") == "https://a.org/x"
    assert bi.clean_url("htex://krunyx.com/a.htex") == "htex://krunyx.com/a.htex"
    if os.name != "nt":
        assert bi.clean_url("file:///Users/u/My%20Notes/a.htex") == "/Users/u/My Notes/a.htex"
    assert bi.clean_url("") is None


# ---------------------------------------------------------------- Chromium
def test_read_chromium_keeps_nested_folders_and_splits_bar_and_other(tmp_path):
    p = tmp_path / "Bookmarks"
    p.write_text(json.dumps(chromium_doc(), ensure_ascii=False), encoding="utf-8")
    got = bi.read_chromium(p)
    assert [b.title for b in got.bar] == ["arXiv", "물리"]           # 북마크릿·chrome:// 은 빠진다
    phys = got.bar[1]
    assert phys.is_folder and [c.title for c in phys.children] == ["INSPIRE", "강의"]
    lecture = phys.children[1]
    assert lecture.is_folder and lecture.children[0].url.endswith("qft.htex")
    assert [b.title for b in got.other] == ["KISTEP", "뉴스"]
    assert got.count == 5


def test_read_chromium_rejects_broken_file(tmp_path):
    p = tmp_path / "Bookmarks"
    p.write_text("{ 깨진", encoding="utf-8")
    with pytest.raises(ValueError):
        bi.read_chromium(p)
    p.write_text('{"roots": 3}', encoding="utf-8")
    with pytest.raises(ValueError):
        bi.read_chromium(p)


# ---------------------------------------------------------------- HTML
CHROME_EXPORT = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<!-- This is an automatically generated file. -->
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3 ADD_DATE="1" PERSONAL_TOOLBAR_FOLDER="true">북마크바</H3>
    <DL><p>
        <DT><A HREF="https://arxiv.org/" ADD_DATE="1">arXiv</A>
        <DT><H3 ADD_DATE="1">물리</H3>
        <DL><p>
            <DT><A HREF="https://inspirehep.net/">INSPIRE &amp; HEP</A>
            <DT><H3>강의</H3>
            <DL><p>
                <DT><A HREF="https://ocw.mit.edu/">MIT OCW</A>
            </DL><p>
        </DL><p>
        <DT><A HREF="javascript:x()">북마크릿</A>
    </DL><p>
    <DT><A HREF="https://www.kistep.re.kr/">KISTEP</A>
</DL><p>
"""

SAFARI_EXPORT = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<HTML><META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<Title>Bookmarks</Title><H1>Bookmarks</H1>
<DT><H3 FOLDED>Favorites</H3>
<DL><p>
<DT><A HREF="https://www.apple.com/">Apple</A>
</DL><p>
<DT><H3 FOLDED>Reading</H3>
<DL><p>
<DT><A HREF="https://example.org/">Example</A>
</DL><p>
</HTML>
"""


def test_read_html_chrome_export_uses_toolbar_flag():
    got = bi.read_html(CHROME_EXPORT)
    assert [b.title for b in got.bar] == ["arXiv", "물리"]
    phys = got.bar[1]
    assert [c.title for c in phys.children] == ["INSPIRE & HEP", "강의"]
    assert phys.children[1].children[0].url == "https://ocw.mit.edu/"
    assert [b.title for b in got.other] == ["KISTEP"]
    assert got.count == 4


def test_read_html_safari_export_finds_favorites_by_name():
    got = bi.read_html(SAFARI_EXPORT)
    assert [b.title for b in got.bar] == ["Apple"]
    assert [b.title for b in got.other] == ["Reading"] and got.other[0].children[0].title == "Example"


def test_read_html_without_toolbar_puts_everything_on_bar_and_rejects_empty():
    got = bi.read_html('<DL><DT><A HREF="https://a.org/">A</A><DT><A HREF="https://b.org/">B</A></DL>')
    assert [b.title for b in got.bar] == ["A", "B"] and got.other == []
    with pytest.raises(ValueError):
        bi.read_html("<html><body>nothing</body></html>")


def test_read_html_file_falls_back_to_cp949(tmp_path):
    p = tmp_path / "bm.html"
    p.write_bytes('<DL><DT><A HREF="https://a.org/">한글 이름</A></DL>'.encode("cp949"))
    assert bi.read_html_file(p).bar[0].title == "한글 이름"


# ---------------------------------------------------------------- 프로필 찾기
def test_find_profiles_reads_profile_names(tmp_path, monkeypatch):
    monkeypatch.setattr(bi, "_platform_key", lambda: "linux")
    root = tmp_path / ".config" / "google-chrome"
    for d in ("Default", "Profile 2", "System Profile"):
        (root / d).mkdir(parents=True)
    (root / "Default" / "Bookmarks").write_text("{}", encoding="utf-8")
    (root / "Profile 2" / "Bookmarks").write_text("{}", encoding="utf-8")
    (root / "System Profile" / "Bookmarks").write_text("{}", encoding="utf-8")
    (root / "Local State").write_text(json.dumps(
        {"profile": {"info_cache": {"Default": {"name": "개인"}, "Profile 2": {"name": "업무"}}}}),
        encoding="utf-8")
    edge = tmp_path / ".config" / "microsoft-edge" / "Default"
    edge.mkdir(parents=True)                         # Bookmarks 파일이 없으면 목록에 없다
    found = bi.find_profiles(tmp_path)
    assert [p.label for p in found] == ["Google Chrome — 개인", "Google Chrome — 업무"]
    assert found[0].path == root / "Default" / "Bookmarks"


# ---------------------------------------------------------------- 저장소에 들이기
def test_import_into_default_bar_goes_straight_onto_bar_and_is_idempotent(tmp_path):
    st = BookmarkStore.load(tmp_path / "bookmarks.json")              # 처음 실행: 기본 북마크 3개
    p = tmp_path / "Bookmarks"
    p.write_text(json.dumps(chromium_doc(), ensure_ascii=False), encoding="utf-8")
    got = bi.read_chromium(p)
    n = st.import_items(got.bar, got.other, "Google Chrome")
    assert n == 5
    titles = [b.title for b in st.bar]
    assert titles[-3:] == ["arXiv", "물리", "기타 북마크"]             # 기본 북마크 뒤에 그대로
    phys = st.bar[-2]
    assert phys.children[1].is_folder and st.folder_path(phys.children[1]) == "물리 › 강의"
    # 다시 가져와도 늘지 않는다
    assert st.import_items(got.bar, got.other, "Google Chrome") == 0
    assert [b.title for b in st.bar] == titles
    # 저장 후 다시 읽어도 중첩 폴더가 남는다
    again = BookmarkStore.load(tmp_path / "bookmarks.json")
    assert again.find("https://ocw.mit.edu/") is None
    assert again.find("https://inspirehep.net/")[0].title == "물리"
    assert len(list(again.iter_all())) == len(list(st.iter_all()))


def test_import_into_used_bar_goes_into_one_folder(tmp_path):
    st = BookmarkStore(path=None)
    st.add("내 것", "https://mine.example/")
    st.add("arXiv 중복", "https://arxiv.org")                        # 끝의 / 만 다른 같은 주소
    got = bi.read_html(CHROME_EXPORT)
    n = st.import_items(got.bar, got.other, "bookmarks")
    assert n == 3                                                     # arXiv 는 이미 있어서 건너뜀
    imp = st.bar[-1]
    assert imp.title == "bookmarks에서 가져옴" and imp.is_folder
    assert [c.title for c in imp.children] == ["물리", "기타 북마크"]
    assert st.depth_of(imp.children[0].children[1]) == 2              # 가져옴 › 물리 › 강의


def test_nested_store_operations():
    st = BookmarkStore(path=None)
    a = st.add_folder("A")
    b = st.add_folder("B", parent=a)
    x = st.add("x", "https://x.example/", folder=b)
    assert st.parent_of(x) is b and st.parent_of(b) is a and st.depth_of(b) == 1
    assert st.find("https://x.example")[0] is b
    assert [f.title for f in st.folders()] == ["A", "B"]
    st.update(x, folder=a)                                            # 위 폴더로 옮기기
    assert st.parent_of(x) is a and b.children == []
    assert st.remove(b) and st.folders() == [a]
    snap = st.snapshot()
    assert snap[0].children[0].url == "https://x.example/" and snap[0] is not a


def test_depth_is_limited():
    deep = {"title": "0", "children": []}
    cur = deep
    for i in range(1, MAX_DEPTH + 3):
        nxt = {"title": str(i), "children": [{"title": f"l{i}", "url": f"https://d/{i}"}]}
        cur["children"].append(nxt)
        cur = nxt
    b = Bookmark.from_json(deep)
    depth = 0
    while b is not None and b.children and any(c.is_folder for c in b.children):
        b = next(c for c in b.children if c.is_folder)
        depth += 1
    assert depth == MAX_DEPTH - 1
    # 가져오기는 너무 깊은 폴더의 북마크를 버리지 않고 위로 올린다
    items = [Bookmark("f0", children=[])]
    cur = items[0]
    for i in range(1, MAX_DEPTH + 3):
        nxt = Bookmark(f"f{i}", children=[Bookmark(f"l{i}", f"https://e/{i}")])
        cur.children.append(nxt)
        cur = nxt
    st = BookmarkStore(path=None)
    assert st.import_items(items, [], "x") == MAX_DEPTH + 2
    assert max(d for d, _ in st.iter_folders()) < MAX_DEPTH
