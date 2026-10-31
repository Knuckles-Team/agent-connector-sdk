"""Win32 ``LockFileEx`` implementation of the :mod:`scion_sdk.file_lock` primitives."""

from __future__ import annotations

import contextlib
import ctypes
import sys
from ctypes import wintypes

from scion_sdk._lock_unavailable import LockUnavailable

if sys.platform == "win32":
    import msvcrt

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # dwFlags for LockFileEx (winbase.h). Omitting LOCKFILE_EXCLUSIVE_LOCK
    # requests a SHARED lock; omitting LOCKFILE_FAIL_IMMEDIATELY blocks.
    _LOCKFILE_FAIL_IMMEDIATELY = 0x00000001
    _LOCKFILE_EXCLUSIVE_LOCK = 0x00000002
    _ERROR_LOCK_VIOLATION = 33
    _ERROR_IO_PENDING = 997

    class _OVERLAPPED(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_void_p),
            ("InternalHigh", ctypes.c_void_p),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    _kernel32.LockFileEx.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_OVERLAPPED),
    ]
    _kernel32.LockFileEx.restype = wintypes.BOOL

    _kernel32.UnlockFileEx.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_OVERLAPPED),
    ]
    _kernel32.UnlockFileEx.restype = wintypes.BOOL

    def _handle(fd: int) -> wintypes.HANDLE:
        # The ONLY use of msvcrt here: convert the CRT fd os.open() returned
        # into the real Win32 HANDLE the kernel32 locking API operates on.
        return wintypes.HANDLE(msvcrt.get_osfhandle(fd))

    def _overlapped(offset: int = 0) -> _OVERLAPPED:
        ov = _OVERLAPPED()
        ov.Offset = offset & 0xFFFFFFFF
        ov.OffsetHigh = 0
        ov.hEvent = None
        return ov

    def _flags(base: int, blocking: bool) -> int:
        return base if blocking else base | _LOCKFILE_FAIL_IMMEDIATELY

    def _lock(fd: int, flags: int) -> bool:
        blocking = not flags & _LOCKFILE_FAIL_IMMEDIATELY
        ov = _overlapped()
        # Lock 1 byte at offset 0 -- matches the POSIX branch's whole-file
        # advisory convention closely enough for every caller in this
        # ecosystem, which only ever locks a dedicated, otherwise-unused
        # ``*.lock``/``.mutex`` file. The range may extend past EOF (Win32
        # byte-range locks are explicitly documented to allow this), so no
        # "ensure the file is non-empty" workaround is needed here, unlike
        # the CRT's msvcrt.locking().
        ok = _kernel32.LockFileEx(_handle(fd), flags, 0, 1, 0, ctypes.byref(ov))
        if ok:
            return True
        err = ctypes.get_last_error()
        if not blocking and err in (_ERROR_LOCK_VIOLATION, _ERROR_IO_PENDING):
            return False
        raise OSError(
            err,
            f"LockFileEx failed: {ctypes.WinError(err).strerror}",
        )

    def lock_exclusive_nb(fd: int) -> None:
        """Non-blocking exclusive lock via ``LockFileEx``. Raises
        :class:`LockUnavailable` if held (matches POSIX ``LOCK_EX|LOCK_NB``).
        """
        if not _lock(fd, _flags(_LOCKFILE_EXCLUSIVE_LOCK, False)):
            raise LockUnavailable("LockFileEx: already exclusively locked by a peer")

    def lock_shared_nb(fd: int) -> None:
        """Non-blocking shared (reader) lock via ``LockFileEx``. Raises
        :class:`LockUnavailable` if EX-held. A TRUE held shared lock — Win32
        shared byte-range locks genuinely allow concurrent readers, so unlike
        the CRT-level ``msvcrt.locking`` (which has no shared mode at all),
        this does not need to probe-and-release; it matches POSIX
        ``LOCK_SH|LOCK_NB`` exactly, including that the caller is responsible
        for calling :func:`unlock` when done (see ``host_lock.py``'s
        ``lock_shared_nb(fd); ...; unlock(fd)`` pattern).
        """
        if not _lock(fd, _flags(0, False)):
            raise LockUnavailable("LockFileEx: already exclusively locked by a peer")

    def lock_exclusive(fd: int, *, blocking: bool = True) -> bool:
        """Exclusive lock via ``LockFileEx``. Blocking (default) waits
        forever at the KERNEL level — Microsoft's own documentation: "If the
        file handle was not opened for asynchronous I/O and the lock is not
        available, this call waits until the lock is granted ... unless
        LOCKFILE_FAIL_IMMEDIATELY is specified" — exactly like POSIX
        ``flock(LOCK_EX)``. No retry/poll loop, same as the POSIX branch.
        """
        return _lock(fd, _flags(_LOCKFILE_EXCLUSIVE_LOCK, blocking))

    def lock_shared(fd: int, *, blocking: bool = True) -> bool:
        """Held shared (reader) lock via ``LockFileEx`` — a TRUE concurrent
        multi-reader lock, not an emulation: Win32 shared byte-range locks
        "deny all processes write access ... but allow read access from all
        of them" (Microsoft docs), identical to POSIX ``LOCK_SH``. Blocking
        (default) waits forever at the kernel level, same as
        :func:`lock_exclusive`.
        """
        return _lock(fd, _flags(0, blocking))

    def unlock(fd: int) -> None:
        """Release any lock held on ``fd`` (idempotent / best-effort)."""
        ov = _overlapped()
        with contextlib.suppress(OSError):
            _kernel32.UnlockFileEx(_handle(fd), 0, 1, 0, ctypes.byref(ov))
