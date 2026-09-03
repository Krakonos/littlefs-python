"""Filesystem operations performed through :class:`littlefs.path.LittleFSPath`."""
import pytest

pytest.importorskip("pathlib_abc", reason="the pathlib-style API requires pathlib-abc (Python 3.9+)")

from littlefs import LittleFS, LittleFSPath  # noqa: E402
from littlefs.errors import LittleFSError  # noqa: E402
from littlefs.lfs import LFSStat  # noqa: E402


@pytest.fixture(scope="function")
def fs():
    fs = LittleFS(block_size=128, block_count=64)
    yield fs


@pytest.fixture(scope="function")
def root(fs):
    yield fs.root


@pytest.fixture(scope="function")
def tree(root):
    """A small nested tree::

    /top.txt
    /pkg/mod.py
    /pkg/notes.txt
    /pkg/sub/deep.py
    """
    (root / "top.txt").write_text("top")
    (root / "pkg").mkdir()
    (root / "pkg" / "mod.py").write_text("mod")
    (root / "pkg" / "notes.txt").write_text("notes")
    (root / "pkg" / "sub").mkdir()
    (root / "pkg" / "sub" / "deep.py").write_text("deep")
    yield root


# -- directories ----------------------------------------------------------------
def test_mkdir_and_is_dir(root):
    path = root / "data"
    assert not path.exists()
    path.mkdir()
    assert path.exists()
    assert path.is_dir()
    assert not path.is_file()


def test_mkdir_existing_raises(root):
    path = root / "data"
    path.mkdir()
    with pytest.raises((FileExistsError, LittleFSError)):
        path.mkdir()


def test_mkdir_exist_ok(root):
    path = root / "data"
    path.mkdir()
    path.mkdir(exist_ok=True)
    assert path.is_dir()


def test_mkdir_exist_ok_on_a_file_still_raises(root):
    path = root / "file.txt"
    path.write_text("x")
    with pytest.raises((FileExistsError, LittleFSError)):
        path.mkdir(exist_ok=True)


def test_mkdir_missing_parent_raises(root):
    with pytest.raises((FileNotFoundError, LittleFSError)):
        (root / "a" / "b" / "c").mkdir()


def test_mkdir_parents(root):
    deep = root / "a" / "b" / "c"
    deep.mkdir(parents=True)
    assert deep.is_dir()
    assert (root / "a").is_dir()
    assert (root / "a" / "b").is_dir()


def test_mkdir_parents_exist_ok(root):
    deep = root / "a" / "b"
    deep.mkdir(parents=True)
    with pytest.raises((FileExistsError, LittleFSError)):
        deep.mkdir(parents=True)
    deep.mkdir(parents=True, exist_ok=True)


def test_rmdir(root):
    path = root / "empty"
    path.mkdir()
    path.rmdir()
    assert not path.exists()


def test_iterdir(root):
    (root / "dir").mkdir()
    (root / "dir" / "a.txt").write_text("a")
    (root / "dir" / "b.txt").write_text("b")
    (root / "dir" / "sub").mkdir()
    children = sorted((root / "dir").iterdir())
    assert [p.name for p in children] == ["a.txt", "b.txt", "sub"]
    assert [str(p) for p in children] == ["/dir/a.txt", "/dir/b.txt", "/dir/sub"]
    assert all(p.fs is root.fs for p in children)


def test_iterdir_on_a_file_raises_not_a_directory(root):
    path = root / "file.txt"
    path.write_text("x")
    with pytest.raises(NotADirectoryError):
        path.iterdir()


def test_iterdir_on_a_missing_path_raises_file_not_found(root):
    with pytest.raises(FileNotFoundError):
        (root / "nope").iterdir()


def test_iterdir_allows_mutation_while_iterating(root):
    # The directory listing is materialised before the first yield, so the
    # directory handle is closed and the tree can be modified during iteration.
    (root / "dir").mkdir()
    for name in ("a.txt", "b.txt", "c.txt"):
        (root / "dir" / name).write_text(name)
    for child in (root / "dir").iterdir():
        child.unlink()
    assert list((root / "dir").iterdir()) == []


# -- files ----------------------------------------------------------------------
def test_write_read_text(root):
    path = root / "hello.txt"
    path.write_text("héllo")
    assert path.read_text() == "héllo"
    assert path.is_file()
    assert not path.is_dir()


def test_write_read_bytes(root):
    path = root / "blob.bin"
    assert path.write_bytes(b"\x00\x01\x02") == 3
    assert path.read_bytes() == b"\x00\x01\x02"


def test_write_bytes_truncates(root):
    path = root / "blob.bin"
    path.write_bytes(b"0123456789")
    path.write_bytes(b"ab")
    assert path.read_bytes() == b"ab"


def test_write_text_rejects_bytes(root):
    with pytest.raises(TypeError):
        (root / "f.txt").write_text(b"bytes")


def test_read_missing_file_raises(root):
    with pytest.raises((FileNotFoundError, LittleFSError)):
        (root / "nope.txt").read_bytes()


def test_open_context_manager(root):
    path = root / "f.txt"
    with path.open("w") as fh:
        fh.write("line\n")
    with path.open("r") as fh:
        assert fh.read() == "line\n"


def test_open_binary(root):
    path = root / "f.bin"
    with path.open("wb") as fh:
        fh.write(b"\xde\xad")
    with path.open("rb") as fh:
        assert fh.read() == b"\xde\xad"


def test_open_append(root):
    path = root / "f.txt"
    path.write_text("a")
    with path.open("a") as fh:
        fh.write("b")
    assert path.read_text() == "ab"


def test_touch(root):
    path = root / "t.txt"
    path.touch()
    assert path.is_file()
    assert path.read_bytes() == b""
    path.touch()  # exist_ok=True by default


def test_touch_does_not_truncate(root):
    path = root / "t.txt"
    path.write_text("keep")
    path.touch()
    assert path.read_text() == "keep"


def test_touch_exist_ok_false(root):
    path = root / "t.txt"
    path.touch()
    with pytest.raises((FileExistsError, LittleFSError)):
        path.touch(exist_ok=False)


def test_unlink(root):
    path = root / "gone.txt"
    path.write_text("x")
    path.unlink()
    assert not path.exists()


def test_unlink_missing_raises(root):
    with pytest.raises((FileNotFoundError, LittleFSError)):
        (root / "nope.txt").unlink()


def test_unlink_missing_ok(root):
    (root / "nope.txt").unlink(missing_ok=True)


def test_rename(root):
    src = root / "src.txt"
    src.write_text("data")
    dst = src.rename(root / "dst.txt")
    assert not src.exists()
    assert dst.read_text() == "data"
    assert str(dst) == "/dst.txt"
    assert dst.fs is root.fs


def test_rename_accepts_a_string(root):
    src = root / "src.txt"
    src.write_text("data")
    assert src.rename("/dst.txt").read_text() == "data"


def test_rename_overwrites_the_destination(root):
    src = root / "src.txt"
    src.write_text("new")
    dst = root / "dst.txt"
    dst.write_text("old")
    src.rename(dst)
    assert dst.read_text() == "new"
    assert not src.exists()


def test_replace_is_rename(root):
    src = root / "src.txt"
    src.write_text("new")
    dst = root / "dst.txt"
    dst.write_text("old")
    src.replace(dst)
    assert dst.read_text() == "new"


# -- stat / info ----------------------------------------------------------------
def test_stat(root):
    path = root / "s.txt"
    path.write_text("12345")
    stat = path.stat()
    assert stat.size == 5
    assert stat.name == "s.txt"
    assert stat.type == LFSStat.TYPE_REG


def test_stat_missing_raises(root):
    with pytest.raises((FileNotFoundError, LittleFSError)):
        (root / "nope").stat()


def test_info_on_a_file(root):
    path = root / "f.txt"
    path.write_text("x")
    assert path.info.exists()
    assert path.info.is_file()
    assert not path.info.is_dir()
    assert not path.info.is_symlink()


def test_info_on_a_directory(root):
    path = root / "d"
    path.mkdir()
    assert path.info.exists()
    assert path.info.is_dir()
    assert not path.info.is_file()


def test_info_on_a_missing_path(root):
    path = root / "nope"
    assert not path.info.exists()
    assert not path.info.is_dir()
    assert not path.info.is_file()


def test_info_is_cached_but_exists_is_fresh(root):
    # The PathInfo protocol explicitly permits cached results, and the ABC's
    # glob/walk rely on it. The exists()/is_dir()/is_file() methods on the path
    # itself always perform a fresh lookup.
    path = root / "later.txt"
    info = path.info
    assert path.info is info  # one info object per path
    assert not info.exists()
    path.write_text("x")
    assert not info.exists()  # still the cached answer
    assert path.exists()  # fresh lookup
    assert path.is_file()
    assert root.joinpath("later.txt").info.exists()  # a fresh path, fresh info


# -- glob / rglob / walk --------------------------------------------------------
def test_glob(tree):
    assert sorted(str(p) for p in tree.glob("*.txt")) == ["/top.txt"]
    assert sorted(str(p) for p in tree.glob("pkg/*.py")) == ["/pkg/mod.py"]


def test_glob_recursive(tree):
    assert sorted(str(p) for p in tree.glob("**/*.py")) == ["/pkg/mod.py", "/pkg/sub/deep.py"]


def test_glob_matches_directories(tree):
    assert sorted(str(p) for p in tree.glob("*")) == ["/pkg", "/top.txt"]


def test_glob_question_mark(root):
    (root / "a1.txt").write_text("")
    (root / "a12.txt").write_text("")
    assert sorted(str(p) for p in root.glob("a?.txt")) == ["/a1.txt"]


def test_glob_character_class(root):
    (root / "a.txt").write_text("")
    (root / "b.txt").write_text("")
    (root / "c.txt").write_text("")
    assert sorted(str(p) for p in root.glob("[ab].txt")) == ["/a.txt", "/b.txt"]


def test_glob_from_a_subdirectory(tree):
    assert sorted(str(p) for p in (tree / "pkg").glob("*.py")) == ["/pkg/mod.py"]


def test_glob_no_match(tree):
    assert list(tree.glob("*.rs")) == []


def test_glob_absolute_pattern_is_rejected(tree):
    with pytest.raises(NotImplementedError):
        list(tree.glob("/*.txt"))


@pytest.mark.parametrize(
    "traverse",
    [
        lambda path: path.glob("*"),
        lambda path: path.glob("**/*"),
        lambda path: path.glob("*.txt"),
        lambda path: path.rglob("*"),
        lambda path: path.walk(),
    ],
    ids=["glob", "glob-recursive", "glob-pattern", "rglob", "walk"],
)
def test_traversing_a_non_directory_yields_nothing(root, traverse):
    # Like pathlib, traversing something that is not a listable directory yields
    # nothing rather than raising. This only works because iterdir() raises
    # OSError subclasses, which the ABC's globber and walk() catch.
    a_file = root / "file.txt"
    a_file.write_text("x")

    assert list(traverse(a_file)) == []
    assert list(traverse(root / "missing")) == []


def test_walk_on_error_callback(root):
    path = root / "file.txt"
    path.write_text("x")
    errors = []
    assert list(path.walk(on_error=errors.append)) == []
    assert [type(exc) for exc in errors] == [NotADirectoryError]


def test_glob_results_keep_the_handle(tree):
    matches = list(tree.rglob("*.py"))
    assert matches
    assert all(p.fs is tree.fs for p in matches)


def test_rglob(tree):
    assert sorted(str(p) for p in tree.rglob("*.py")) == ["/pkg/mod.py", "/pkg/sub/deep.py"]
    assert sorted(str(p) for p in tree.rglob("*.txt")) == ["/pkg/notes.txt", "/top.txt"]


def test_rglob_from_a_subdirectory(tree):
    assert sorted(str(p) for p in (tree / "pkg").rglob("*.py")) == ["/pkg/mod.py", "/pkg/sub/deep.py"]


def test_walk(tree):
    walked = [(str(top), sorted(dirs), sorted(files)) for top, dirs, files in tree.walk()]
    assert walked == [
        ("/", ["pkg"], ["top.txt"]),
        ("/pkg", ["sub"], ["mod.py", "notes.txt"]),
        ("/pkg/sub", [], ["deep.py"]),
    ]


def test_walk_bottom_up(tree):
    walked = [str(top) for top, _dirs, _files in tree.walk(top_down=False)]
    assert walked == ["/pkg/sub", "/pkg", "/"]


def test_walk_an_empty_directory(root):
    (root / "empty").mkdir()
    assert [(str(t), d, f) for t, d, f in (root / "empty").walk()] == [("/empty", [], [])]


# -- copy -----------------------------------------------------------------------
def test_copy_a_file(root):
    src = root / "src.txt"
    src.write_text("payload")
    dst = src.copy(root / "dst.txt")
    assert dst.read_text() == "payload"
    assert src.read_text() == "payload"
    assert str(dst) == "/dst.txt"


def test_copy_a_tree(tree):
    copied = (tree / "pkg").copy(tree / "pkg2")
    assert sorted(str(p) for p in copied.rglob("*")) == [
        "/pkg2/mod.py",
        "/pkg2/notes.txt",
        "/pkg2/sub",
        "/pkg2/sub/deep.py",
    ]
    assert (copied / "sub" / "deep.py").read_text() == "deep"


def test_copy_into(root):
    src = root / "src.txt"
    src.write_text("payload")
    (root / "bucket").mkdir()
    copied = src.copy_into(root / "bucket")
    assert str(copied) == "/bucket/src.txt"
    assert copied.read_text() == "payload"


def test_a_relative_path_reaches_the_same_file(root, fs):
    (root / "logs").mkdir()
    (root / "logs" / "boot.txt").write_text("ready")
    relative = LittleFSPath("logs/boot.txt", fs=fs)

    assert relative.read_text() == "ready"
    relative.write_text("changed")
    assert (root / "logs" / "boot.txt").read_text() == "changed"
    # ...while remaining a different path object, as in pathlib.
    assert relative != root / "logs" / "boot.txt"


def test_dot_segments_are_resolved_by_littlefs(root, fs):
    (root / "a").mkdir()
    (root / "b.txt").write_text("b")

    assert LittleFSPath("a/../b.txt", fs=fs).read_text() == "b"
    assert LittleFSPath("./b.txt", fs=fs).read_text() == "b"
    # Above the root is an error rather than being clamped to it.
    with pytest.raises((OSError, LittleFSError)):
        LittleFSPath("../b.txt", fs=fs).read_text()


def test_copy_onto_the_same_file_by_another_path_is_refused(root, fs):
    (root / "notes.txt").write_text("important")
    # Different path, same file: comparing the paths would not catch this, so
    # copy() has to resolve them.
    with pytest.raises(OSError):
        LittleFSPath("notes.txt", fs=fs).copy(root / "notes.txt")
    assert (root / "notes.txt").read_text() == "important"


def test_copy_onto_itself_is_refused(root):
    src = root / "src.txt"
    src.write_text("payload")
    with pytest.raises(OSError):
        src.copy(root / "src.txt")


def test_copy_to_another_filesystem(root):
    src = root / "src.txt"
    src.write_text("payload")
    other = LittleFS(block_size=128, block_count=64)
    # Same path string, different filesystem: this must be allowed.
    copied = src.copy(other.root / "src.txt")
    assert copied.fs is other
    assert copied.read_text() == "payload"


# -- symlinks -------------------------------------------------------------------
def test_symlinks_are_unsupported(root):
    assert not root.is_symlink()
    with pytest.raises(NotImplementedError):
        root.readlink()
    with pytest.raises(NotImplementedError):
        (root / "link").symlink_to("/target")


# -- end-to-end -----------------------------------------------------------------
def test_end_to_end_roundtrip():
    """Build a tree, glob it, read it back, and mutate it through the path API."""
    fs = LittleFS(block_size=512, block_count=256)
    root = fs.root

    (root / "logs").mkdir()
    for day in range(3):
        (root / "logs" / f"day{day}.log").write_text(f"entry {day}\n")
    (root / "logs" / "archive").mkdir()
    (root / "logs" / "archive" / "old.log").write_text("ancient\n")

    # The filesystem is really populated, as seen through the low-level API.
    assert sorted(fs.listdir("/logs")) == ["archive", "day0.log", "day1.log", "day2.log"]

    found = sorted(root.rglob("*.log"))
    assert [str(p) for p in found] == [
        "/logs/archive/old.log",
        "/logs/day0.log",
        "/logs/day1.log",
        "/logs/day2.log",
    ]
    assert [p.read_text() for p in found] == ["ancient\n", "entry 0\n", "entry 1\n", "entry 2\n"]

    # Mutate: rename one, drop another, then re-glob.
    (root / "logs" / "day0.log").rename(root / "logs" / "first.log")
    (root / "logs" / "day2.log").unlink()
    assert sorted(p.name for p in root.rglob("*.log")) == sorted(["first.log", "day1.log", "old.log"])

    # Tear the tree down through the path API.
    for path in sorted(root.rglob("*"), key=lambda p: len(str(p)), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    assert list(root.iterdir()) == []
