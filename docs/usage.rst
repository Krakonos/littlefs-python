=====
Usage
=====

littlefs-python offers four interfaces to the underlying littlefs library:

- A C-Style API which exposes all functions from the library using a minimal
  wrapper, written in Cython, to access the functions.
- A pythonic high-level API which offers convenient functions similar to
  the ones known from the :mod:`os` standard library module.
- A :mod:`pathlib`-style API, which navigates the filesystem with path objects
  instead of path strings. See :ref:`doc-pathlib-api`.
- A command line tool, available as ``littlefs-python``. See :ref:`doc-cli`
  for more information.

These API's can be mixed and matched if required.

C-Style API
===========

The C-Style API tries to map functions from the C library to python with as little
intermediate logic as possible. The possibility to provide customized :func:`read`,
:func:`prog`, :func:`erase` and :func:`sync` functions to littlefs was a main goal
for the api.

All methods and relevant classes for this API are available in the :mod:`littlefs.lfs`
module. The methods where named the same as in the littlfs library, leaving out the `lfs_`
prefix. Because direct access to C structs is not possible from python, wrapper classes
are provided for the commonly used structs:

- :class:`~littlefs.lfs.LFSFilesystem` is a wrapper around the :c:type:`lfs_t` struct.
- :class:`~littlefs.lfs.LFSFile` is a wrapper around the :c:type:`lfs_file_t` struct.
- :class:`~littlefs.lfs.LFSDirectory` is a wrapper around the :c:type:`lfs_dir_t` struct.
- :class:`~littlefs.lfs.LFSConfig` is a wrapper around the :c:type:`lfs_config_t` struct.

All these wrappers have a :attr:`_impl` attribute which contains the actual data. Note that
this attribute is not accessible from python.
The :class:`~littlefs.lfs.LFSConfig` class exposes most of the internal fields from the
:attr:`_impl` as properties to provide read access to the configuration.


Pythonic API
============

While the pythonic API is working for basic operations like reading and writing files,
creating and listing directories and some other functionality, it's by no means finished.
Currently the usage is best explained in the :ref:`doc-examples` section.


.. _doc-pathlib-api:

Pathlib-style API
=================

.. warning::
   This API is **provisional** and may still change; see :mod:`littlefs.path`
   for what that rests on.

:attr:`~littlefs.LittleFS.root` returns the filesystem root as a
:class:`~littlefs.path.LittleFSPath`, which behaves like a :class:`pathlib.Path`:

.. code:: python

    from littlefs import LittleFS

    fs = LittleFS(block_size=512, block_count=256)

    logs = fs.root / 'logs'
    logs.mkdir()
    (logs / 'boot.txt').write_text('ready\n')

    for path in fs.root.rglob('*.txt'):
        print(path, '->', path.read_text())

Every path derived from :attr:`~littlefs.LittleFS.root` -- via ``/``,
:attr:`~pathlib.PurePath.parent`, :meth:`~littlefs.path.LittleFSPath.iterdir`, glob
results and so on -- stays bound to the same filesystem, so all I/O is routed through it.
The bound handle is available as :attr:`~littlefs.path.LittleFSPath.fs`.

This interface requires Python 3.9 or later.
On Python 3.8, importing :mod:`littlefs.path` or accessing
:attr:`~littlefs.LittleFS.root` raises :exc:`ImportError`; the rest of the package is
unaffected.

Model
-----

Pure path handling (``/``, :attr:`~pathlib.PurePath.parts`,
:attr:`~pathlib.PurePath.name`, :attr:`~pathlib.PurePath.stem`,
:attr:`~pathlib.PurePath.suffix`, :attr:`~pathlib.PurePath.parent`,
:meth:`~pathlib.PurePath.with_suffix`, :meth:`~pathlib.PurePath.relative_to`,
:meth:`~pathlib.PurePath.full_match`, ...) never touches the filesystem and comes
straight from the ABCs, as do ``glob``, ``rglob``, ``walk`` and ``copy``. Everything
else delegates to the bound handle:

.. csv-table::
   :header: Path method, LittleFS method
   :widths: 30, 30

   ":meth:`~littlefs.path.LittleFSPath.open`, ``read_text``, ``read_bytes``, ``write_text``, ``write_bytes``, :meth:`~littlefs.path.LittleFSPath.touch`", ":meth:`~littlefs.LittleFS.open`"
   ":meth:`~littlefs.path.LittleFSPath.stat`, :meth:`~littlefs.path.LittleFSPath.exists`, :meth:`~littlefs.path.LittleFSPath.is_file`, :meth:`~littlefs.path.LittleFSPath.is_dir`, :attr:`~littlefs.path.LittleFSPath.info`", ":meth:`~littlefs.LittleFS.stat`"
   ":meth:`~littlefs.path.LittleFSPath.iterdir`", ":meth:`~littlefs.LittleFS.scandir`"
   ":meth:`~littlefs.path.LittleFSPath.mkdir`", ":meth:`~littlefs.LittleFS.mkdir` / :meth:`~littlefs.LittleFS.makedirs`"
   ":meth:`~littlefs.path.LittleFSPath.rmdir`, :meth:`~littlefs.path.LittleFSPath.unlink`", ":meth:`~littlefs.LittleFS.rmdir` / :meth:`~littlefs.LittleFS.remove`"
   ":meth:`~littlefs.path.LittleFSPath.rename`, :meth:`~littlefs.path.LittleFSPath.replace`", ":meth:`~littlefs.LittleFS.rename`"

Things to be aware of, mostly consequences of what littlefs itself supports:

- littlefs resolves every path from the filesystem root, so a *relative* path reaches
  the same file as its absolute equivalent:

  .. code:: python

      (fs.root / 'logs' / 'boot.txt').write_text('ready\n')

      LittleFSPath('logs/boot.txt', fs=fs).read_text()   # 'ready\n' -- the same file

  The two are still distinct *paths*, though. As in :mod:`pathlib`, equality compares
  the path itself, so ``LittleFSPath('logs/boot.txt', fs=fs)`` does not equal
  ``fs.root / 'logs' / 'boot.txt'`` and hashes differently. Operations that ask
  whether two paths lead to one file, such as
  :meth:`~littlefs.path.LittleFSPath.copy`, do resolve them and will refuse to copy
  a file onto itself.
- ``.`` and ``..`` are resolved by littlefs, not by the path object, so
  ``'a/../b'`` reaches ``/b``. Going above the root (``'../x'``) is an error rather
  than being clamped to it.
- ``rename`` overwrites an existing destination, so ``replace`` is an alias of it.
- There are no symbolic links: ``is_symlink()`` is always ``False``, and ``readlink()``
  and ``symlink_to()`` raise :exc:`NotImplementedError`.
- There are no modification times, so :meth:`~littlefs.path.LittleFSPath.touch` only
  creates missing files and never updates an existing one.
- :attr:`~littlefs.path.LittleFSPath.info` caches its lookup, as the ``PathInfo``
  protocol permits and the ABC's ``glob``/``walk`` rely on. Use
  :meth:`~littlefs.path.LittleFSPath.exists`,
  :meth:`~littlefs.path.LittleFSPath.is_file` and
  :meth:`~littlefs.path.LittleFSPath.is_dir` when an up-to-date answer is needed.
- A :class:`~littlefs.path.LittleFSPath` is deliberately **not** :class:`os.PathLike`:
  a path inside an image has no meaning on the host filesystem, and implementing
  ``__fspath__`` would let the ABCs' file-opening helper silently operate on the host
  filesystem instead.

