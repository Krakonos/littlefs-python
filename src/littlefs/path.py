"""``pathlib``-style access to a littlefs filesystem.

This module implements the :mod:`pathlib` ABCs (``JoinablePath`` /
``ReadablePath`` / ``WritablePath``) from the `pathlib-abc
<https://pypi.org/project/pathlib-abc/>`_ package, so a littlefs image can be
navigated with the familiar :class:`pathlib.Path` API::

    from littlefs import LittleFS

    fs = LittleFS(block_size=512, block_count=256)
    (fs.root / "logs").mkdir()
    (fs.root / "logs" / "boot.txt").write_text("ready\\n")
    for path in fs.root.rglob("*.txt"):
        print(path, path.read_text())

Every path derived from :attr:`LittleFS.root` stays bound to the same
filesystem handle, so all I/O is routed through it.

.. note::
   ``pathlib-abc`` is pre-1.0 and its API is still under discussion for
   inclusion in CPython's :mod:`pathlib`. This module should be considered
   **provisional**: it may need to follow breaking changes in ``pathlib-abc``.
"""

import posixpath
from typing import IO, TYPE_CHECKING, Iterator, List, Optional, Union

try:
    from pathlib_abc import JoinablePath, ReadablePath, WritablePath, vfspath
except ImportError as exc:  # pragma: no cover - depends on the install environment
    raise ImportError(
        "littlefs.path requires the 'pathlib-abc' package, which is only "
        "available on Python 3.9 and later. Install it with "
        "`pip install pathlib-abc`."
    ) from exc

from .errors import LittleFSError
from . import lfs

if TYPE_CHECKING:
    from littlefs import LittleFS

__all__ = ["LittleFSPath", "LittleFSPathInfo"]


_ENOENT = int(LittleFSError.Error.LFS_ERR_NOENT)
_EEXIST = int(LittleFSError.Error.LFS_ERR_EXIST)
_ENOTDIR = int(LittleFSError.Error.LFS_ERR_NOTDIR)

# Segment types accepted when building a path.
_StrPath = Union[str, "LittleFSPath"]


def _stat_or_none(fs: "LittleFS", path: str) -> Optional[lfs.LFSStat]:
    """``fs.stat(path)``, or ``None`` if the path does not exist

    A missing path raises either :class:`LittleFSError` with ``LFS_ERR_NOENT`` or
    the builtin :class:`FileNotFoundError`, depending on the call; both mean the
    same thing here.
    """
    try:
        return fs.stat(path)
    except FileNotFoundError:
        return None
    except LittleFSError as exc:
        if exc.code == _ENOENT:
            return None
        raise


def _segment_to_str(segment: _StrPath) -> str:
    """Normalise a path segment to a string"""
    if isinstance(segment, str):
        return segment
    if isinstance(segment, JoinablePath):
        return vfspath(segment)
    # os.PathLike is deliberately not accepted: a host filesystem path means
    # nothing inside an image. TypeError is what lets ``__truediv__`` return
    # NotImplemented.
    raise TypeError(f"expected a str or LittleFSPath segment, not {type(segment).__name__}")


class LittleFSPathInfo:
    """File type information for a :class:`LittleFSPath`.

    Satisfies the ``PathInfo`` protocol from ``pathlib-abc``. One
    :meth:`LittleFS.stat` result is fetched on first use and then **cached**, as
    the protocol permits, which is what makes ``glob``/``walk`` cheap.

    The ``follow_symlinks`` arguments are accepted and ignored: littlefs has no
    symbolic links.
    """

    __slots__ = ("_fs", "_path", "_stat", "_stat_cached")

    def __init__(self, fs: Optional["LittleFS"], path: str, stat: Optional[lfs.LFSStat] = None) -> None:
        self._fs = fs
        self._path = path
        self._stat = stat
        # ``stat`` may be supplied by ``iterdir()``, which already learned the
        # file type while listing the parent directory.
        self._stat_cached = stat is not None

    def _lfs_stat(self) -> Optional[lfs.LFSStat]:
        if not self._stat_cached:
            if self._fs is None:
                raise ValueError(f"{self._path!r} is not bound to a LittleFS handle")
            self._stat = _stat_or_none(self._fs, self._path)
            self._stat_cached = True
        return self._stat

    def exists(self, *, follow_symlinks: bool = True) -> bool:
        """Whether this path exists"""
        return self._lfs_stat() is not None

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        """Whether this path is a directory"""
        stat = self._lfs_stat()
        return stat is not None and stat.type == lfs.LFSStat.TYPE_DIR

    def is_file(self, *, follow_symlinks: bool = True) -> bool:
        """Whether this path is a regular file"""
        stat = self._lfs_stat()
        return stat is not None and stat.type == lfs.LFSStat.TYPE_REG

    def is_symlink(self) -> bool:
        """Always ``False``: littlefs has no symbolic links"""
        return False

    def _file_id(self) -> tuple:
        """Identify the file this path names, for ``copy()``'s same-file check

        ``pathlib_abc``'s copy helpers fall back to comparing paths without this,
        which is not enough here: ``"notes.txt"`` and ``"/notes.txt"`` are one
        file but two unequal paths. There are no inode numbers, so the
        normalized absolute path stands in, with the handle included so copies
        between images stay allowed.
        """
        return (id(self._fs), posixpath.normpath(posixpath.join("/", self._path)))


class LittleFSPath(ReadablePath, WritablePath):
    """A path inside a littlefs filesystem, bound to its :class:`LittleFS` handle.

    Instances are normally obtained from :attr:`LittleFS.root` and combined with
    ``/``; the bound handle propagates to every derived path (``parent``, ``/``,
    ``with_suffix``, ``glob`` results, ...) through :meth:`with_segments`.

    Pure path behaviour (``parts``, ``name``, ``stem``, ``suffix``, ``parent``,
    ``relative_to``, ``full_match``, ...) and ``glob``/``rglob``/``walk``/
    ``copy`` come from the ``pathlib-abc`` ABCs. Everything that touches the
    filesystem delegates to the bound handle.

    littlefs resolves every path from the filesystem root, so a "relative" path
    reaches the same file as its absolute equivalent. :attr:`info` caches its
    lookup, while :meth:`exists`, :meth:`is_dir` and :meth:`is_file` always look
    afresh.
    """

    __slots__ = ("_fs", "_path", "_info")

    # Annotations only; the values live in __slots__.
    _fs: Optional["LittleFS"]
    _path: str
    _info: Optional[LittleFSPathInfo]

    #: littlefs is always POSIX: ``/`` separator, no alternative separator.
    parser = posixpath

    def __init__(self, *pathsegments: _StrPath, fs: Optional["LittleFS"] = None) -> None:
        if fs is None:
            # Inherit the handle when built from another bound path.
            fs = next((seg._fs for seg in pathsegments if isinstance(seg, LittleFSPath)), None)
        if fs is not None and not hasattr(fs, "stat"):
            # Common slip: passing the low-level ``littlefs.lfs.LFSFilesystem``
            # struct (a ``LittleFS`` handle's ``.fs`` attribute) instead of the
            # handle itself. Without this guard it fails much later, inside
            # ``stat()``, with a confusing AttributeError.
            raise TypeError(
                f"expected a high-level littlefs.LittleFS handle, got "
                f"{type(fs).__module__}.{type(fs).__qualname__}. If you have a "
                f"LittleFS `fs`, pass `fs` itself, not `fs.fs`."
            )
        self._fs = fs
        parts = [_segment_to_str(seg) for seg in pathsegments]
        # Plain posixpath joining, which importantly preserves a trailing
        # separator: the ABC's globber relies on ``joinpath("")`` yielding
        # ``"/dir/"`` so that it can concatenate the next pattern part onto it.
        self._path = posixpath.join(*parts) if parts else ""
        self._info = None

    # -- pure path surface ------------------------------------------------------
    def __vfspath__(self) -> str:
        """The string representation of this path"""
        return self._path

    def __str__(self) -> str:
        return self._path

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._path!r})"

    # NOTE: ``__fspath__`` is deliberately *not* implemented. ``pathlib_abc``'s
    # ``vfsopen()`` tries the builtin ``open()`` first, so an os.PathLike path
    # object would make ``read_text()``/``write_bytes()`` silently operate on the
    # host filesystem instead of the littlefs image.

    # The ABCs omit these, but relative_to() and copy() depend on __eq__.
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, LittleFSPath):
            return NotImplemented
        # The handle is part of the identity: the same string on two different
        # filesystems is not the same file.
        return self._path == other._path and self._fs is other._fs

    def __hash__(self) -> int:
        return hash((self._path, id(self._fs)))

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, LittleFSPath):
            return NotImplemented
        return self._path < other._path

    def __le__(self, other: object) -> bool:
        if not isinstance(other, LittleFSPath):
            return NotImplemented
        return self._path <= other._path

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, LittleFSPath):
            return NotImplemented
        return self._path > other._path

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, LittleFSPath):
            return NotImplemented
        return self._path >= other._path

    def with_segments(self, *pathsegments: _StrPath) -> "LittleFSPath":
        """Construct a new path of the same type, bound to the same handle"""
        return type(self)(*pathsegments, fs=self._fs)

    def as_posix(self) -> str:
        """The string representation of this path, always POSIX style"""
        return self._path

    def is_absolute(self) -> bool:
        """Whether this path starts at the filesystem root"""
        return self._path.startswith("/")

    @property
    def fs(self) -> "LittleFS":
        """The bound :class:`LittleFS` handle"""
        if self._fs is None:
            raise ValueError(f"{self!r} is not bound to a LittleFS handle")
        return self._fs

    # -- filesystem queries -----------------------------------------------------
    @property
    def info(self) -> LittleFSPathInfo:
        """A :class:`LittleFSPathInfo` for this path, created once and cached"""
        if self._info is None:
            self._info = LittleFSPathInfo(self._fs, self._path)
        return self._info

    def stat(self) -> lfs.LFSStat:
        """Return the :class:`littlefs.lfs.LFSStat` for this path

        Raises :class:`LittleFSError` if the path does not exist.
        """
        return self.fs.stat(self._path)

    def exists(self) -> bool:
        """Whether this path exists"""
        return _stat_or_none(self.fs, self._path) is not None

    def is_dir(self) -> bool:
        """Whether this path is a directory"""
        stat = _stat_or_none(self.fs, self._path)
        return stat is not None and stat.type == lfs.LFSStat.TYPE_DIR

    def is_file(self) -> bool:
        """Whether this path is a regular file"""
        stat = _stat_or_none(self.fs, self._path)
        return stat is not None and stat.type == lfs.LFSStat.TYPE_REG

    def is_symlink(self) -> bool:
        """Always ``False``: littlefs has no symbolic links"""
        return False

    def iterdir(self) -> Iterator["LittleFSPath"]:
        """Return an iterator over the children of this directory

        :exc:`NotADirectoryError` and :exc:`FileNotFoundError` are raised by this
        call rather than while iterating the result.
        """
        # ``scandir`` already reports each entry's type, so prime the children's
        # info caches with it and save a stat() apiece. Materialised here so the
        # directory handle is closed before anything is yielded: callers commonly
        # mutate the tree while iterating.
        try:
            entries: List[lfs.LFSStat] = list(self.fs.scandir(self._path))
        except LittleFSError as exc:
            # Translated to the builtins, as the rest of the high-level API
            # does. LittleFSError is not an OSError, so glob()/walk() would
            # otherwise never catch these.
            if exc.code == _ENOTDIR:
                raise NotADirectoryError(f"Not a directory: '{self._path}'") from exc
            if exc.code == _ENOENT:
                raise FileNotFoundError(f"No such file or directory: '{self._path}'") from exc
            raise
        return self._iter_entries(entries)

    def _iter_entries(self, entries: List[lfs.LFSStat]) -> Iterator["LittleFSPath"]:
        for entry in entries:
            child = self.with_segments(self._path, entry.name)
            child._info = LittleFSPathInfo(self._fs, child._path, stat=entry)
            yield child

    def rglob(self, pattern: str, *, recurse_symlinks: bool = True) -> Iterator["LittleFSPath"]:
        """Recursive :meth:`glob`, equivalent to ``glob("**/" + pattern)``"""
        return self.glob(f"**/{pattern}", recurse_symlinks=recurse_symlinks)

    def readlink(self) -> "LittleFSPath":
        """Always raises: littlefs has no symbolic links"""
        raise NotImplementedError("littlefs does not support symbolic links")

    # -- file I/O ---------------------------------------------------------------
    def open(
        self,
        mode: str = "r",
        buffering: int = -1,
        encoding: Optional[str] = None,
        errors: Optional[str] = None,
        newline: Optional[str] = None,
    ) -> IO:
        """Open this file, like :meth:`LittleFS.open`"""
        return self.fs.open(self._path, mode, buffering, encoding, errors, newline)

    def __open_reader__(self) -> IO:
        """Open this file for binary reading"""
        return self.fs.open(self._path, "rb")

    def __open_writer__(self, mode: str) -> IO:
        """Open this file for binary writing in ``'a'``, ``'w'`` or ``'x'`` mode"""
        return self.fs.open(self._path, mode + "b")

    def touch(self, exist_ok: bool = True) -> None:
        """Create this file if it does not exist

        littlefs records no modification time, so unlike
        :meth:`pathlib.Path.touch` this cannot refresh one: touching an existing
        file is a no-op.
        """
        try:
            with self.fs.open(self._path, "xb"):
                pass
        except FileExistsError:
            if not exist_ok:
                raise
        except LittleFSError as exc:
            if exc.code != _EEXIST or not exist_ok:
                raise

    # -- mutations --------------------------------------------------------------
    def mkdir(self, parents: bool = False, exist_ok: bool = False) -> None:
        """Create this directory.

        With *parents*, any missing parent directories are created as well; with
        *exist_ok*, an already existing directory is not an error.
        """
        if parents:
            self.fs.makedirs(self._path, exist_ok=exist_ok)
            return
        try:
            self.fs.mkdir(self._path)
        except FileExistsError:
            if exist_ok and self.is_dir():
                return
            raise
        except LittleFSError as exc:
            if exc.code == _EEXIST and exist_ok and self.is_dir():
                return
            raise

    def rmdir(self) -> None:
        """Remove this directory, which must be empty

        Delegates to :meth:`LittleFS.rmdir`, which -- unlike
        :meth:`pathlib.Path.rmdir` -- does not check that the target is really a
        directory.
        """
        self.fs.rmdir(self._path)

    def unlink(self, missing_ok: bool = False) -> None:
        """Remove this file"""
        try:
            self.fs.remove(self._path)
        except FileNotFoundError:
            if missing_ok:
                return
            raise
        except LittleFSError as exc:
            if exc.code == _ENOENT and missing_ok:
                return
            raise

    def rename(self, target: _StrPath) -> "LittleFSPath":
        """Rename this path to *target* and return the new path

        littlefs replaces an existing destination, so :meth:`replace` is an alias
        of this.
        """
        target_str = _segment_to_str(target)
        self.fs.rename(self._path, target_str)
        return self.with_segments(target_str)

    #: Alias of :meth:`rename`: littlefs already overwrites the destination.
    replace = rename

    def symlink_to(self, target: _StrPath, target_is_directory: bool = False) -> None:
        """Always raises: littlefs has no symbolic links"""
        raise NotImplementedError("littlefs does not support symbolic links")
