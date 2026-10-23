"""Writing files so that a crash or a full disk never leaves a half-written one where a good one was."""
import errno
import os
import tempfile
from pathlib import Path


def _fsync_dir(directory: Path) -> None:
    """Make the new directory entry durable. Best effort: some platforms cannot open a directory."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_temp(directory: Path, data: bytes) -> Path:
    """Write `data` to a new hidden temporary file in `directory` (same file system as the final name) and sync it."""
    directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
    return Path(name)


def write_atomic(path: Path, data: bytes, *, exclusive: bool = False) -> None:
    """Replace `path` with `data` in one step. With `exclusive` it never replaces: if the file exists it raises
    FileExistsError and the existing file is untouched (calibrations are never edited in place)."""
    path = Path(path)
    tmp = write_temp(path.parent, data)
    try:
        if not exclusive:
            os.replace(tmp, path)
        else:
            try:
                os.link(tmp, path)                          # fails if `path` exists; the data is already complete
            except FileExistsError:
                raise
            except OSError as exc:
                if exc.errno not in (errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV, errno.ENOSYS, errno.EACCES):
                    raise
                # a file system without hard links (some network and exFAT volumes): exclusive create, written in place
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                    fh.flush()
                    os.fsync(fh.fileno())
    finally:
        tmp.unlink(missing_ok=True)
    _fsync_dir(path.parent)
