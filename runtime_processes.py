"""Small platform boundary for LogosGo child and parent process handling.

The Windows branches are source-preparation code. They are intentionally kept
behind pure, injectable decisions so they can be unit tested on macOS, but real
Win32 behavior remains a Phase 7C native-Windows validation requirement. The
Windows Runner's Job Object will remain the authoritative descendant-cleanup
mechanism for packaged builds.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import os
import signal
import subprocess
import threading
import time
from typing import Callable


WINDOWS_CREATE_NEW_PROCESS_GROUP = 0x00000200
WINDOWS_CREATE_NO_WINDOW = 0x08000000
WINDOWS_SYNCHRONIZE = 0x00100000
WINDOWS_INFINITE = 0xFFFFFFFF


def process_platform(os_name: str | None = None) -> str:
    return "windows" if (os_name or os.name).lower() == "nt" else "posix"


@dataclass(frozen=True)
class ChildProcessPolicy:
    platform_identifier: str
    creationflags: int = 0

    def popen_kwargs(self) -> dict[str, int]:
        return {"creationflags": self.creationflags} if self.creationflags else {}


def child_process_policy(
    *,
    os_name: str | None = None,
    hide_window: bool = False,
    new_process_group: bool = False,
) -> ChildProcessPolicy:
    """Build Popen flags without passing Windows-only kwargs on POSIX."""

    platform = process_platform(os_name)
    flags = 0
    if platform == "windows":
        if hide_window:
            flags |= getattr(subprocess, "CREATE_NO_WINDOW", WINDOWS_CREATE_NO_WINDOW)
        if new_process_group:
            flags |= getattr(
                subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                WINDOWS_CREATE_NEW_PROCESS_GROUP,
            )
    return ChildProcessPolicy(platform, flags)


def katago_popen_kwargs(*, os_name: str | None = None) -> dict[str, int]:
    """Hide KataGo's console on Windows without changing POSIX launch behavior."""

    return child_process_policy(os_name=os_name, hide_window=True).popen_kwargs()


def prepare_backend_process_group(
    *,
    os_name: str | None = None,
    set_process_group: Callable[[int, int], None] | None = None,
    log: Callable[[str], None] = print,
) -> None:
    """Preserve the macOS process group; Windows uses the Runner Job Object."""

    if process_platform(os_name) == "windows":
        return
    set_process_group = set_process_group or os.setpgid
    try:
        set_process_group(0, 0)
    except OSError as exc:
        log(f"建立 backend process group 失敗，將依賴正常終止：{exc}")


def _wait_for_posix_parent_exit(
    parent_pid: int,
    *,
    kill: Callable[[int, int], None] = os.kill,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    while True:
        try:
            kill(parent_pid, 0)
        except OSError:
            return
        sleep(1.0)


def _wait_for_windows_parent_exit(parent_pid: int) -> None:
    """Wait on a Windows process handle without using POSIX signal semantics."""

    if os.name != "nt":
        raise RuntimeError("Windows parent watcher can only run on Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int

    handle = kernel32.OpenProcess(WINDOWS_SYNCHRONIZE, False, parent_pid)
    if not handle:
        # The parent has already exited or cannot be opened. In either case the
        # child must fail closed instead of remaining orphaned.
        return
    try:
        kernel32.WaitForSingleObject(handle, WINDOWS_INFINITE)
    finally:
        kernel32.CloseHandle(handle)


def parent_wait_strategy(*, os_name: str | None = None) -> str:
    """Expose the selected strategy for diagnostics and pure unit tests."""

    return "windows_process_handle" if process_platform(os_name) == "windows" else "posix_pid_probe"


def start_parent_watchdog(
    parent_pid: int,
    on_parent_exit: Callable[[], None],
    *,
    os_name: str | None = None,
    thread_factory: Callable[..., threading.Thread] = threading.Thread,
) -> threading.Thread:
    """Start a daemon watcher and invoke ``on_parent_exit`` exactly once."""

    platform = process_platform(os_name)

    def watch() -> None:
        if platform == "windows":
            _wait_for_windows_parent_exit(parent_pid)
        else:
            _wait_for_posix_parent_exit(parent_pid)
        on_parent_exit()

    thread = thread_factory(target=watch, daemon=True)
    thread.start()
    return thread


def install_termination_handlers(
    handler: Callable[[int, object], None],
    *,
    os_name: str | None = None,
    register: Callable[[int, Callable[[int, object], None]], object] = signal.signal,
) -> tuple[int, ...]:
    """Install signals Python can safely handle on the current platform.

    A packaged Windows Runner should normally use the authenticated shutdown
    endpoint and a Job Object fallback. SIGBREAK is retained for development
    consoles created with ``CREATE_NEW_PROCESS_GROUP``.
    """

    signals = [signal.SIGTERM, signal.SIGINT]
    if process_platform(os_name) == "windows" and hasattr(signal, "SIGBREAK"):
        signals.append(signal.SIGBREAK)
    for value in signals:
        register(value, handler)
    return tuple(signals)
