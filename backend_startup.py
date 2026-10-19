"""Explicit startup configuration and instance identity for LogosGo backend."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import secrets
from typing import Mapping, Sequence


BACKEND_HOST = "127.0.0.1"
DEVELOPMENT_PORT = 5001
BACKEND_DEBUG = False
SERVICE_IDENTITY = "LogosGoBackend"
API_SCHEMA_VERSION = 1
INSTANCE_TOKEN_HEADER = "X-LogosGo-Instance"

PORT_ENV = "LOGOSGO_PORT"
INSTANCE_TOKEN_ENV = "LOGOSGO_INSTANCE_TOKEN"
RESOURCE_ROOT_ENV = "LOGOSGO_RESOURCE_ROOT"
KATAGO_EXECUTABLE_ENV = "LOGOSGO_KATAGO_EXECUTABLE"
PARENT_PID_ENV = "LOGOSGO_PARENT_PID"


class StartupConfigurationError(ValueError):
    pass


def _port(value: str | int) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise StartupConfigurationError(f"port 必須是整數：{value!r}") from exc
    if not 1 <= port <= 65535:
        raise StartupConfigurationError("port 必須介於 1 和 65535")
    return port


def _token(value: str | None) -> str:
    if value is None:
        return secrets.token_urlsafe(32)
    token = value.strip()
    if not token:
        raise StartupConfigurationError("instance token 不可為空")
    if len(token) > 512:
        raise StartupConfigurationError("instance token 過長")
    return token


def _optional_path(value: str | None) -> Path | None:
    return Path(value).expanduser() if value else None


def _optional_parent_pid(value: str | int | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        parent_pid = int(value)
    except (TypeError, ValueError) as exc:
        raise StartupConfigurationError(f"parent pid 必須是整數：{value!r}") from exc
    if parent_pid <= 1:
        raise StartupConfigurationError("parent pid 必須大於 1")
    return parent_pid


@dataclass(frozen=True)
class BackendStartupConfig:
    host: str
    port: int
    debug: bool
    instance_token: str
    resource_root: Path | None
    katago_executable: Path | None
    parent_pid: int | None


@dataclass(frozen=True)
class BackendIdentity:
    token: str

    @property
    def instance_id(self) -> str:
        return hashlib.sha256(self.token.encode("utf-8")).hexdigest()[:24]

    def verify(self, provided: str | None) -> bool:
        return (
            isinstance(provided, str)
            and bool(provided)
            and secrets.compare_digest(self.token, provided)
        )


def _environment_defaults(environ: Mapping[str, str]) -> BackendStartupConfig:
    return BackendStartupConfig(
        host=BACKEND_HOST,
        port=_port(environ.get(PORT_ENV, DEVELOPMENT_PORT)),
        debug=BACKEND_DEBUG,
        instance_token=_token(environ.get(INSTANCE_TOKEN_ENV)),
        resource_root=_optional_path(environ.get(RESOURCE_ROOT_ENV)),
        katago_executable=_optional_path(environ.get(KATAGO_EXECUTABLE_ENV)),
        parent_pid=_optional_parent_pid(environ.get(PARENT_PID_ENV)),
    )


def development_startup_config(
    environ: Mapping[str, str] | None = None,
) -> BackendStartupConfig:
    return _environment_defaults(os.environ if environ is None else environ)


def parse_backend_startup_args(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> BackendStartupConfig:
    env = os.environ if environ is None else environ
    defaults = _environment_defaults(env)
    parser = argparse.ArgumentParser(description="LogosGo local backend")
    parser.add_argument("--port", default=defaults.port)
    parser.add_argument("--instance-token", default=defaults.instance_token)
    parser.add_argument("--resource-root", default=defaults.resource_root)
    parser.add_argument(
        "--katago-executable",
        default=defaults.katago_executable,
    )
    parser.add_argument("--parent-pid", default=defaults.parent_pid)
    values = parser.parse_args(argv)
    try:
        return BackendStartupConfig(
            host=BACKEND_HOST,
            port=_port(values.port),
            debug=BACKEND_DEBUG,
            instance_token=_token(values.instance_token),
            resource_root=_optional_path(
                str(values.resource_root) if values.resource_root is not None else None
            ),
            katago_executable=_optional_path(
                str(values.katago_executable)
                if values.katago_executable is not None
                else None
            ),
            parent_pid=_optional_parent_pid(values.parent_pid),
        )
    except StartupConfigurationError as exc:
        parser.error(str(exc))
        raise AssertionError("argparse.error always exits")
