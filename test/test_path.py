"""Pure-path (no I/O) behaviour of :class:`littlefs.path.LittleFSPath`."""
import pytest

pytest.importorskip("pathlib_abc", reason="the pathlib-style API requires pathlib-abc (Python 3.9+)")

from pathlib_abc import JoinablePath, PathInfo, ReadablePath, WritablePath, vfspath  # noqa: E402

from littlefs import LittleFS, LittleFSPath  # noqa: E402


@pytest.fixture(scope="function")
def fs():
    fs = LittleFS(block_size=128, block_count=64)
    yield fs


@pytest.fixture(scope="function")
def root(fs):
    yield fs.root


def test_implements_the_abcs(root):
    # The path ABCs are inherited; PathInfo is satisfied structurally.
    assert isinstance(root, JoinablePath)
    assert isinstance(root, ReadablePath)
    assert isinstance(root, WritablePath)
    assert isinstance(root.info, PathInfo)


def test_root_is_slash(root):
    assert str(root) == "/"
    assert vfspath(root) == "/"
    assert root.name == ""
    assert root.anchor == "/"
    assert root.is_absolute()


def test_truediv_builds_absolute_path(root):
    path = root / "a" / "b" / "c.txt"
    assert str(path) == "/a/b/c.txt"
    assert isinstance(path, LittleFSPath)


def test_joinpath(root):
    assert str(root.joinpath("a", "b")) == "/a/b"
    assert str((root / "a").joinpath("b", "c")) == "/a/b/c"


def test_absolute_segment_resets_the_path(root):
    assert str(root / "a" / "/b") == "/b"


def test_bare_relative_paths_are_preserved(fs):
    # littlefs resolves every path from the root, so a relative path behaves
    # like its absolute equivalent, but the string is kept as given.
    path = LittleFSPath("a/b", fs=fs)
    assert str(path) == "a/b"
    assert not path.is_absolute()


def test_derived_paths_keep_the_handle(root, fs):
    assert root.fs is fs
    assert (root / "a" / "b").fs is fs
    assert (root / "a").parent.fs is fs
    assert (root / "a" / "f.txt").with_suffix(".bin").fs is fs


def test_unbound_path_rejects_filesystem_access():
    path = LittleFSPath("/a")
    with pytest.raises(ValueError, match="not bound to a LittleFS handle"):
        path.fs


def test_low_level_struct_is_rejected(fs):
    # Passing the low-level LFSFilesystem struct (a LittleFS handle's `.fs`)
    # instead of the handle itself must fail fast with a clear message.
    with pytest.raises(TypeError, match="high-level littlefs.LittleFS handle"):
        LittleFSPath("/", fs=fs.fs)


def test_invalid_segment_type(root):
    with pytest.raises(TypeError):
        root / 42


def test_name_stem_suffix(root):
    path = root / "dir" / "archive.tar.gz"
    assert path.name == "archive.tar.gz"
    assert path.stem == "archive.tar"
    assert path.suffix == ".gz"
    assert path.suffixes == [".tar", ".gz"]


def test_parts_and_parent(root):
    path = root / "a" / "b" / "c"
    assert path.parts == ("/", "a", "b", "c")
    assert str(path.parent) == "/a/b"
    assert [str(p) for p in path.parents] == ["/a/b", "/a", "/"]
    assert str(root.parent) == "/"  # the root is its own parent


def test_with_name_stem_suffix(root):
    path = root / "a" / "file.txt"
    assert str(path.with_name("other.bin")) == "/a/other.bin"
    assert str(path.with_suffix(".md")) == "/a/file.md"
    assert str(path.with_stem("renamed")) == "/a/renamed.txt"


def test_relative_to(root):
    path = root / "a" / "b" / "c"
    assert str(path.relative_to(root / "a")) == "b/c"
    assert path.is_relative_to(root / "a")
    assert not path.is_relative_to(root / "x")
    with pytest.raises(ValueError):
        path.relative_to(root / "x")


def test_full_match(root):
    assert (root / "a" / "x.py").full_match("/a/*.py")
    assert (root / "a" / "x.py").full_match("**/*.py")
    assert not (root / "a" / "x.py").full_match("/a/*.txt")


def test_str_and_as_posix(root):
    path = root / "a" / "b"
    assert str(path) == "/a/b"
    assert path.as_posix() == "/a/b"


def test_is_not_os_pathlike(root, tmp_path):
    # LittleFSPath must NOT implement __fspath__: pathlib_abc's vfsopen() tries
    # the builtin open() first, so an os.PathLike path object would make
    # read_text()/write_bytes() silently operate on the *host* filesystem.
    assert not hasattr(root, "__fspath__")

    host_file = tmp_path / "host.txt"
    host_file.write_text("host content")
    leaked = LittleFSPath(host_file.as_posix(), fs=root.fs)
    with pytest.raises(Exception) as excinfo:
        leaked.read_text()
    assert "host content" not in str(excinfo.value)


def test_equality_and_hash(fs):
    assert (fs.root / "x") == (fs.root / "x")
    assert hash(fs.root / "x") == hash(fs.root / "x")
    assert (fs.root / "x") != (fs.root / "y")
    assert (fs.root / "x") != "/x"


def test_equality_includes_the_filesystem(fs):
    # The same string on two different filesystems is not the same file. This is
    # what lets copy() write to the same path on another image.
    other = LittleFS(block_size=128, block_count=64)
    assert (fs.root / "x") != (other.root / "x")


def test_repr(root):
    assert repr(root / "a") == "LittleFSPath('/a')"


def test_sorting(root):
    paths = [root / "c", root / "a", root / "b"]
    assert [p.name for p in sorted(paths)] == ["a", "b", "c"]


def test_subclass_keeps_its_type(fs):
    class MyPath(LittleFSPath):
        __slots__ = ()

    path = MyPath("/", fs=fs) / "a" / "b"
    assert isinstance(path, MyPath)
    assert isinstance(path.parent, MyPath)
    assert path.fs is fs
