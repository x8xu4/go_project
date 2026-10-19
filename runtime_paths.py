"""Portable runtime resource and writable-path resolution for LogosGo.

Resolution deliberately does not use the current working directory. Packaged
launchers should pass explicit paths; development falls back to this module's
source directory and the developer's PATH for KataGo only.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Callable, Mapping


RESOURCE_ROOT_ENV = "LOGOSGO_RESOURCE_ROOT"
KATAGO_EXECUTABLE_ENV = "LOGOSGO_KATAGO_EXECUTABLE"

_LOG = logging.getLogger(__name__)


class RuntimePathError(RuntimeError):
    """Raised when required runtime resources cannot be resolved safely."""


@dataclass(frozen=True)
class WritablePaths:
    application_support: Path
    caches: Path
    logs: Path
    temporary: Path

    def ensure_logs(self) -> Path:
        self.logs.mkdir(parents=True, exist_ok=True)
        return self.logs


@dataclass(frozen=True)
class RuntimePaths:
    resource_root: Path
    katago_executable: Path
    model_file: Path
    config_file: Path
    corpus_file: Path
    writable: WritablePaths
    mode: str
    platform_identifier: str
    backend_executable_name: str
    katago_executable_name: str
    runtime_dependency_dir: Path


@dataclass(frozen=True)
class RuntimeNames:
    platform_identifier: str
    backend_executable_name: str
    katago_executable_name: str


@dataclass(frozen=True)
class KataGoRuntimeCandidate:
    backend: str
    executable: Path


def platform_identifier(platform: str | None = None) -> str:
    """Return the small set of platform names used by packaging logic."""

    value = (platform or sys.platform).lower()
    if value in ("windows", "macos", "posix"):
        return value
    if value.startswith("win") or value == "nt":
        return "windows"
    if value == "darwin":
        return "macos"
    return "posix"


def runtime_names(platform: str | None = None) -> RuntimeNames:
    identifier = platform_identifier(platform)
    if identifier == "windows":
        return RuntimeNames(identifier, "logosgo_backend.exe", "katago.exe")
    return RuntimeNames(identifier, "logosgo-backend", "katago")


def writable_paths(
    *,
    home: str | os.PathLike[str] | None = None,
    temporary_root: str | os.PathLike[str] | None = None,
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> WritablePaths:
    identifier = platform_identifier(platform)
    env = os.environ if environ is None else environ
    home_path = Path(home).expanduser() if home is not None else Path.home()
    if temporary_root is not None:
        temp_path = Path(temporary_root)
    elif identifier == "windows":
        configured_temp = env.get("TEMP") or env.get("TMP")
        temp_path = Path(configured_temp) if configured_temp else Path(tempfile.gettempdir())
    else:
        temp_path = Path(tempfile.gettempdir())

    if identifier == "windows":
        configured_local = env.get("LOCALAPPDATA")
        if configured_local:
            local_app_data = Path(configured_local)
        else:
            local_app_data = home_path / "AppData/Local"
            _LOG.warning(
                "LOCALAPPDATA is unavailable; using Windows local-data fallback: %s",
                local_app_data,
            )
        application_support = local_app_data / "LogosGo"
        return WritablePaths(
            application_support=application_support,
            caches=application_support / "Cache",
            logs=application_support / "Logs",
            temporary=temp_path / "LogosGo",
        )

    if identifier == "macos":
        return WritablePaths(
            application_support=home_path / "Library/Application Support/LogosGo",
            caches=home_path / "Library/Caches/LogosGo",
            logs=home_path / "Library/Logs/LogosGo",
            temporary=temp_path / "LogosGo",
        )

    data_home = Path(env.get("XDG_DATA_HOME", home_path / ".local/share"))
    cache_home = Path(env.get("XDG_CACHE_HOME", home_path / ".cache"))
    state_home = Path(env.get("XDG_STATE_HOME", home_path / ".local/state"))
    return WritablePaths(
        application_support=data_home / "LogosGo",
        caches=cache_home / "LogosGo",
        logs=state_home / "LogosGo/Logs",
        temporary=temp_path / "LogosGo",
    )


def _expanded(path: str | os.PathLike[str]) -> Path:
    return Path(path).expanduser().resolve()


def _app_contents(executable_path: Path | None) -> Path | None:
    if executable_path is None:
        return None
    for candidate in (executable_path, *executable_path.parents):
        if candidate.name == "Contents":
            return candidate
    return None


def _windows_runtime_root(executable_path: Path | None) -> Path | None:
    if executable_path is None:
        return None
    candidates = [executable_path.parent / "runtime"]
    candidates.extend(
        candidate
        for candidate in (executable_path.parent, *executable_path.parents)
        if candidate.name.lower() == "runtime"
    )
    for candidate in candidates:
        if all(
            (candidate / relative).is_file()
            for relative in (
                "model/model.bin.gz",
                "config/analysis.cfg",
                "data/logosgo_corpus_full.csv",
            )
        ):
            return candidate.resolve()
    return None


def _required_file(root: Path, label: str, candidates: tuple[str, ...]) -> Path:
    for relative in candidates:
        candidate = root / relative
        if candidate.is_file():
            return candidate.resolve()
    choices = ", ".join(str(root / relative) for relative in candidates)
    raise RuntimePathError(
        f"找不到必要的 {label}；已檢查：{choices}。"
        "請確認 --resource-root 指向完整的 LogosGo runtime resources。"
    )


def _valid_executable(path: Path, *, platform: str | None = None) -> bool:
    if not path.is_file():
        return False
    if platform_identifier(platform) == "windows":
        return path.suffix.lower() in (".exe", ".com", ".bat", ".cmd")
    return os.access(path, os.X_OK)


def katago_runtime_candidates(
    resource_root: str | os.PathLike[str],
    *,
    platform: str | None = None,
) -> tuple[KataGoRuntimeCandidate, ...]:
    """Return deterministic package candidates without claiming they can run.

    Windows runtime selection is finalized by the native Runner after an actual
    OpenCL probe. Path discovery alone only encodes the required preference.
    """

    root = Path(resource_root)
    identifier = platform_identifier(platform)
    if identifier == "windows":
        return (
            KataGoRuntimeCandidate("opencl", root / "katago/opencl/katago.exe"),
            KataGoRuntimeCandidate("eigen", root / "katago/eigen/katago.exe"),
            KataGoRuntimeCandidate("unspecified", root / "katago/katago.exe"),
            KataGoRuntimeCandidate("unspecified", root / "KataGo/katago.exe"),
            KataGoRuntimeCandidate("unspecified", root / "bin/katago.exe"),
        )
    return (
        KataGoRuntimeCandidate("unspecified", root / "katago"),
        KataGoRuntimeCandidate("unspecified", root / "katago/katago"),
        KataGoRuntimeCandidate("unspecified", root / "KataGo/katago"),
        KataGoRuntimeCandidate("unspecified", root / "bin/katago"),
    )


def resolve_runtime_paths(
    *,
    resource_root: str | os.PathLike[str] | None = None,
    katago_executable: str | os.PathLike[str] | None = None,
    environ: Mapping[str, str] | None = None,
    source_file: str | os.PathLike[str] | None = None,
    executable_path: str | os.PathLike[str] | None = None,
    frozen: bool | None = None,
    which: Callable[[str], str | None] = shutil.which,
    home: str | os.PathLike[str] | None = None,
    temporary_root: str | os.PathLike[str] | None = None,
    platform: str | None = None,
) -> RuntimePaths:
    """Resolve immutable resources and writable locations with clear precedence.

    Resource root precedence:
      1. explicit argument
      2. LOGOSGO_RESOURCE_ROOT
      3. inferred ``Contents/Resources/LogosGo`` for a frozen .app helper
      4. this module's source directory for development only

    KataGo precedence:
      1. explicit argument
      2. LOGOSGO_KATAGO_EXECUTABLE
      3. known paths under the resource root / inferred app Helpers
      4. PATH, development mode only
    """

    env = os.environ if environ is None else environ
    names = runtime_names(platform)
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    source = _expanded(source_file or __file__)
    executable = (
        _expanded(executable_path)
        if executable_path is not None
        else (_expanded(sys.executable) if is_frozen else None)
    )
    contents = _app_contents(executable)
    windows_root = (
        _windows_runtime_root(executable)
        if names.platform_identifier == "windows"
        else None
    )

    if resource_root is not None:
        root = _expanded(resource_root)
        mode = "explicit"
    elif env.get(RESOURCE_ROOT_ENV):
        root = _expanded(env[RESOURCE_ROOT_ENV])
        mode = "environment"
    elif contents is not None:
        root = (contents / "Resources/LogosGo").resolve()
        mode = "packaged"
    elif windows_root is not None:
        root = windows_root
        mode = "packaged"
    elif is_frozen:
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root is None:
            raise RuntimePathError(
                "已凍結的 LogosGo backend 無法推導 resource root；"
                "請提供 --resource-root 或 LOGOSGO_RESOURCE_ROOT。"
            )
        root = (_expanded(bundle_root) / "Resources/LogosGo").resolve()
        mode = "packaged"
    else:
        root = source.parent.resolve()
        mode = "development"

    if not root.is_dir():
        raise RuntimePathError(
            f"LogosGo resource root 不存在或不是目錄：{root}"
        )

    model = _required_file(root, "model.bin.gz", ("model.bin.gz", "model/model.bin.gz"))
    config = _required_file(root, "analysis.cfg", ("analysis.cfg", "config/analysis.cfg"))
    corpus = _required_file(
        root,
        "logosgo_corpus_full.csv",
        ("logosgo_corpus_full.csv", "data/logosgo_corpus_full.csv"),
    )

    if katago_executable is not None:
        katago = _expanded(katago_executable)
    elif env.get(KATAGO_EXECUTABLE_ENV):
        katago = _expanded(env[KATAGO_EXECUTABLE_ENV])
    else:
        candidates = [
            candidate.executable
            for candidate in katago_runtime_candidates(
                root,
                platform=names.platform_identifier,
            )
        ]
        if contents is not None:
            candidates.insert(0, contents / "Helpers/KataGo/katago")
        katago = next(
            (
                candidate.resolve()
                for candidate in candidates
                if _valid_executable(candidate, platform=names.platform_identifier)
            ),
            None,
        )
        if katago is None and mode == "development":
            discovered = which(names.katago_executable_name)
            katago = _expanded(discovered) if discovered else None
        if katago is None:
            raise RuntimePathError(
                "找不到 KataGo executable；請提供 --katago-executable 或 "
                f"{KATAGO_EXECUTABLE_ENV}。"
            )

    if not _valid_executable(katago, platform=names.platform_identifier):
        raise RuntimePathError(
            f"KataGo executable 不存在或不可執行：{katago}"
        )

    return RuntimePaths(
        resource_root=root,
        katago_executable=katago,
        model_file=model,
        config_file=config,
        corpus_file=corpus,
        writable=writable_paths(
            home=home,
            temporary_root=temporary_root,
            platform=names.platform_identifier,
            environ=env,
        ),
        mode=mode,
        platform_identifier=names.platform_identifier,
        backend_executable_name=names.backend_executable_name,
        katago_executable_name=names.katago_executable_name,
        runtime_dependency_dir=(root / "katago").resolve(),
    )
