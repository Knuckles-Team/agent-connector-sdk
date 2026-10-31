"""Cross-platform advisory file-lock primitives.

SCION-CONNECTOR-CONTROL-R014.2: moved from agent-utilities so connectors depend only on the SDK.

THIS IS THE CHOKEPOINT (R-07). Every caller in this ecosystem that needs an
advisory, cross-process, crash-safe file lock must import from here instead of
calling ``fcntl``/``msvcrt``/``ctypes`` directly. ``fcntl.flock`` is
**POSIX-only** and raises ``ImportError`` at *import* time on Windows (not at
lock time) — a bare ``import fcntl`` anywhere on the import path of a module
Windows needs to load (most visibly ``scripts/uv_workspace.py``, the mandated
workspace runner) breaks that module for every caller, before any lock is
ever taken. This module is the ONE place that branches on platform, built on
stdlib only (no new third-party dependency):

* :func:`lock_exclusive_nb` — non-blocking exclusive lock (the spawn/host guard).
* :func:`lock_shared_nb`    — non-blocking shared lock (the liveness probe).
* :func:`lock_exclusive`    — exclusive lock, blocking by default (leases, mutexes).
* :func:`lock_shared`       — held shared (reader) lock, blocking by default.
* :func:`unlock`            — release (all of the above).

**Full feature parity, not a degraded fallback.** Every guarantee below holds
on both platforms identically — advisory, cross-process, TRUE concurrent
shared/reader access, TRUE unbounded blocking, and released automatically
when the holder dies (including a crash) — because Windows has a real
byte-range-locking API with all of these properties; it is just a different
API than POSIX's, not a lesser one. There is no "Windows can't do this"
degradation anywhere in this module: only a different platform mechanism for
the identical feature.

* **POSIX:** ``fcntl.flock`` with ``LOCK_EX`` / ``LOCK_SH`` / ``LOCK_UN`` and
  ``LOCK_NB``. Auto-released by the kernel when the holder dies (the
  no-stale-PID property the lease/guard machinery depends on) — unchanged
  from before this module existed; this file does not alter POSIX behaviour
  or performance in any way, it only adds Windows support alongside it.
* **Windows:** the real Win32 byte-range locking API, ``LockFileEx`` /
  ``UnlockFileEx`` (via ``ctypes`` against ``kernel32.dll`` — stdlib only, no
  ``pywin32`` dependency), NOT the limited ``msvcrt.locking`` CRT wrapper
  (which has no shared-lock mode at all and whose own "blocking" mode gives
  up after ~10s and raises). ``msvcrt.get_osfhandle`` converts the CRT fd
  Python's ``os.open`` returns into the real Win32 ``HANDLE`` these APIs need
  — that conversion is the ONLY thing ``msvcrt`` is used for here. Verified
  against Microsoft's own documentation (Win32 "Locking and Unlocking Byte
  Ranges in Files"; ``LockFileEx`` reference), which states plainly:

  - A *shared* lock (``dwFlags`` without ``LOCKFILE_EXCLUSIVE_LOCK``) "denies
    all processes write access ... but allows read access from all of them"
    — i.e. TRUE concurrent multi-reader semantics, exactly like POSIX
    ``LOCK_SH``. :func:`lock_shared`/:func:`lock_shared_nb` use this
    directly; there is no probe-and-release emulation.
  - "If the file handle was not opened for asynchronous I/O and the lock is
    not available, this call waits until the lock is granted ... unless
    ``LOCKFILE_FAIL_IMMEDIATELY`` is specified" — i.e. TRUE unbounded kernel
    blocking on an ordinary (non-``FILE_FLAG_OVERLAPPED``) handle, exactly
    like POSIX ``flock`` without ``LOCK_NB``. No retry/poll loop is needed or
    used for :func:`lock_exclusive`/:func:`lock_shared`'s blocking mode.
  - ``LOCKFILE_FAIL_IMMEDIATELY`` makes the call return immediately on
    contention — exactly like POSIX ``LOCK_NB``.
  - "If a process terminates with a portion of a file locked ... the locks
    are unlocked by the operating system" — the same crash-release property
    POSIX ``flock`` provides, confirmed by Microsoft's own documentation
    (not assumed).
  - The lock range "may extend beyond the current end of the file", so
    (unlike the CRT's ``msvcrt.locking``) there is no need to pre-write a
    byte into a freshly created empty lock file before locking it.

A non-blocking acquire that LOSES raises :class:`LockUnavailable` (a subclass
of ``OSError``), so callers can keep their existing ``except (BlockingIOError,
OSError)`` arms unchanged across both platforms.

``sys.platform == "win32"`` is used as the branch guard precisely because mypy
special-cases that literal for platform narrowing: the ``ctypes``/Win32 branch
is only type-checked on Windows and the ``fcntl`` branch only on POSIX, so
neither set of platform-specific attributes trips the type-checker on the
other OS.
"""

from __future__ import annotations

import contextlib
import sys

from scion_sdk._lock_unavailable import LockUnavailable

_IS_WINDOWS = sys.platform == "win32"


if sys.platform != "win32":
    import fcntl

    def lock_exclusive_nb(fd: int) -> None:
        """Non-blocking exclusive lock. Raises :class:`LockUnavailable` if held."""
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:  # already locked by a peer
            raise LockUnavailable(str(exc)) from exc

    def lock_shared_nb(fd: int) -> None:
        """Non-blocking shared lock. Raises :class:`LockUnavailable` if EX-held."""
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            raise LockUnavailable(str(exc)) from exc

    def lock_exclusive(fd: int, *, blocking: bool = True) -> bool:
        """Exclusive lock. Blocking (default) waits forever, exactly like the
        bare ``fcntl.flock(fd, LOCK_EX)`` every caller used before this
        module existed — same kernel-side FIFO queuing, same performance.
        Non-blocking returns ``False`` on contention instead of raising.
        """
        if not blocking:
            try:
                lock_exclusive_nb(fd)
                return True
            except LockUnavailable:
                return False
        fcntl.flock(fd, fcntl.LOCK_EX)
        return True

    def lock_shared(fd: int, *, blocking: bool = True) -> bool:
        """Held shared (reader) lock. Blocking (default) waits forever, exactly
        like the bare ``fcntl.flock(fd, LOCK_SH)`` — true concurrent-reader
        semantics.
        """
        if not blocking:
            try:
                lock_shared_nb(fd)
                return True
            except LockUnavailable:
                return False
        fcntl.flock(fd, fcntl.LOCK_SH)
        return True

    def unlock(fd: int) -> None:
        """Release any lock held on ``fd`` (idempotent / best-effort)."""
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)

else:  # pragma: no cover - exercised only on Windows (or the import-fault sim)
    from scion_sdk._file_lock_windows import (  # noqa: F401 - public re-exports
        lock_exclusive,
        lock_exclusive_nb,
        lock_shared,
        lock_shared_nb,
        unlock,
    )
