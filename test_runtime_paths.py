from contextlib import nullcontext
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from runtime_paths import (
    RuntimePathError,
    katago_runtime_candidates,
    resolve_runtime_paths,
    runtime_names,
    writable_paths,
)


def make_resources(root: Path, *, nested: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    model = root / ("model/model.bin.gz" if nested else "model.bin.gz")
    config = root / ("config/analysis.cfg" if nested else "analysis.cfg")
    corpus = root / (
        "data/logosgo_corpus_full.csv" if nested else "logosgo_corpus_full.csv"
    )
    for path, content in (
        (model, b"model"),
        (config, b"config"),
        (corpus, b"label,text\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return root


def make_executable(path: Path, *, platform: str) -> Path:
    if platform == "windows" and path.suffix.lower() != ".exe":
        path = path.with_name(f"{path.name}.exe")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"MZ test executable" if platform == "windows" else b"test executable"
    )
    if platform != "windows" and os.name != "nt":
        path.chmod(0o755)
    return path


class RuntimePathTests(unittest.TestCase):
    def test_explicit_resource_root_has_highest_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            explicit = make_resources(base / "explicit")
            environment = make_resources(base / "environment")
            katago = make_executable(base / "katago", platform="windows")
            paths = resolve_runtime_paths(
                resource_root=explicit,
                katago_executable=katago,
                environ={
                    "LOGOSGO_RESOURCE_ROOT": str(environment),
                    "LOCALAPPDATA": str(base / "local"),
                },
                home=base / "home",
                temporary_root=base / "tmp",
                platform="windows",
            )
            self.assertEqual(paths.resource_root, explicit.resolve())
            self.assertEqual(paths.mode, "explicit")

    def test_development_fallback_uses_source_location_not_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source_root = make_resources(base / "source")
            source_file = source_root / "runtime_paths.py"
            source_file.write_text("# fixture\n", encoding="utf-8")
            katago = make_executable(base / "bin/katago", platform="windows")
            unrelated = base / "unrelated"
            unrelated.mkdir()
            previous = Path.cwd()
            try:
                os.chdir(unrelated)
                paths = resolve_runtime_paths(
                    source_file=source_file,
                    environ={"LOCALAPPDATA": str(base / "local")},
                    which=lambda name: str(katago) if name == "katago.exe" else None,
                    home=base / "home",
                    platform="windows",
                )
            finally:
                os.chdir(previous)
            self.assertEqual(paths.resource_root, source_root.resolve())
            self.assertEqual(paths.mode, "development")

    def test_resource_files_are_resolved_from_required_root(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = make_resources(base / "resources", nested=True)
            katago = make_executable(
                root / "KataGo/katago",
                platform="windows",
            )
            paths = resolve_runtime_paths(
                resource_root=root,
                environ={"LOCALAPPDATA": str(base / "local")},
                home=base / "home",
                platform="windows",
            )
            self.assertEqual(paths.model_file, (root / "model/model.bin.gz").resolve())
            self.assertEqual(paths.config_file, (root / "config/analysis.cfg").resolve())
            self.assertEqual(
                paths.corpus_file,
                (root / "data/logosgo_corpus_full.csv").resolve(),
            )
            self.assertTrue(paths.katago_executable.samefile(katago))

    def test_explicit_katago_path_does_not_require_path_lookup(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = make_resources(base / "resources")
            katago = make_executable(
                base / "helpers/katago",
                platform="windows",
            )
            paths = resolve_runtime_paths(
                resource_root=root,
                katago_executable=katago,
                environ={"LOCALAPPDATA": str(base / "local")},
                which=lambda name: self.fail("PATH lookup must not run"),
                platform="windows",
            )
            self.assertEqual(paths.katago_executable, katago.resolve())

    def test_writable_locations_are_outside_resource_root(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = writable_paths(
                home=base / "home",
                temporary_root=base / "tmp",
                platform="macos",
                environ={},
            )
            self.assertEqual(
                paths.application_support,
                base / "home/Library/Application Support/LogosGo",
            )
            self.assertEqual(paths.caches, base / "home/Library/Caches/LogosGo")
            self.assertEqual(paths.logs, base / "home/Library/Logs/LogosGo")
            self.assertEqual(paths.temporary, base / "tmp/LogosGo")
            self.assertFalse(paths.logs.exists())

    def test_windows_names_and_writable_locations_use_local_app_data(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            names = runtime_names("win32")
            paths = writable_paths(
                home=base / "Users/測試",
                platform="windows",
                environ={
                    "LOCALAPPDATA": str(base / "Users/測試/AppData/Local"),
                    "TEMP": str(base / "Temp Folder"),
                },
            )
            self.assertEqual(names.platform_identifier, "windows")
            self.assertEqual(names.backend_executable_name, "logosgo_backend.exe")
            self.assertEqual(names.katago_executable_name, "katago.exe")
            self.assertEqual(
                paths.application_support,
                base / "Users/測試/AppData/Local/LogosGo",
            )
            self.assertEqual(paths.caches, paths.application_support / "Cache")
            self.assertEqual(paths.logs, paths.application_support / "Logs")
            self.assertEqual(paths.temporary, base / "Temp Folder/LogosGo")

    def test_windows_local_app_data_has_safe_profile_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "Users/Test User"
            with self.assertLogs("runtime_paths", level="WARNING") as captured:
                paths = writable_paths(
                    home=home,
                    temporary_root=Path(directory) / "Temp",
                    platform="windows",
                    environ={},
                )
            self.assertEqual(
                paths.application_support,
                home / "AppData/Local/LogosGo",
            )
            self.assertIn("LOCALAPPDATA", " ".join(captured.output))

    def test_windows_katago_candidates_prefer_opencl_then_eigen(self):
        root = Path("C:/Program Files/LogosGo/runtime")
        candidates = katago_runtime_candidates(root, platform="windows")
        self.assertEqual(
            [(item.backend, item.executable.as_posix()) for item in candidates[:2]],
            [
                ("opencl", "C:/Program Files/LogosGo/runtime/katago/opencl/katago.exe"),
                ("eigen", "C:/Program Files/LogosGo/runtime/katago/eigen/katago.exe"),
            ],
        )

    def test_windows_packaged_layout_is_inferred_from_backend_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = make_resources(Path(directory) / "LogosGo/runtime", nested=True)
            opencl = root / "katago/opencl/katago.exe"
            opencl.parent.mkdir(parents=True)
            opencl.write_bytes(b"MZ")
            backend = root / "backend/logosgo_backend/logosgo_backend.exe"
            backend.parent.mkdir(parents=True)
            backend.write_bytes(b"MZ")
            paths = resolve_runtime_paths(
                executable_path=backend,
                frozen=True,
                environ={"LOCALAPPDATA": str(Path(directory) / "Local")},
                temporary_root=Path(directory) / "Temp",
                platform="windows",
            )
            self.assertEqual(paths.mode, "packaged")
            self.assertEqual(paths.platform_identifier, "windows")
            self.assertEqual(paths.resource_root, root.resolve())
            self.assertEqual(paths.katago_executable, opencl.resolve())
            self.assertEqual(paths.runtime_dependency_dir, (root / "katago").resolve())

    def test_packaged_layout_is_inferred_without_real_app(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "LogosGo.app/Contents"
            resources = make_resources(app / "Resources/LogosGo")
            katago = make_executable(
                app / "Helpers/KataGo/katago",
                platform="macos",
            )
            backend = make_executable(
                app / "Helpers/LogosGoBackend/backend",
                platform="macos",
            )
            # This test validates the macOS bundle layout even on Windows.
            # Windows cannot represent POSIX execute bits, so isolate that OS
            # primitive while retaining all path/discovery assertions.
            executable_access = (
                mock.patch("runtime_paths.os.access", return_value=True)
                if os.name == "nt"
                else nullcontext()
            )
            with executable_access:
                paths = resolve_runtime_paths(
                    executable_path=backend,
                    frozen=True,
                    environ={},
                    platform="macos",
                )
            self.assertEqual(paths.mode, "packaged")
            self.assertEqual(paths.resource_root, resources.resolve())
            self.assertEqual(paths.katago_executable, katago.resolve())

    def test_missing_explicit_root_fails_without_development_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            with self.assertRaisesRegex(RuntimePathError, "resource root"):
                resolve_runtime_paths(
                    resource_root=missing,
                    katago_executable=missing / "katago",
                    environ={},
                )

    def test_file_is_not_a_valid_resource_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "not-a-directory"
            root.write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(RuntimePathError, "不是目錄"):
                resolve_runtime_paths(resource_root=root, environ={})

    def test_missing_required_asset_names_the_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = make_resources(base / "resources")
            (root / "analysis.cfg").unlink()
            katago = make_executable(base / "katago", platform="windows")
            with self.assertRaisesRegex(RuntimePathError, "analysis.cfg"):
                resolve_runtime_paths(
                    resource_root=root,
                    katago_executable=katago,
                    environ={"LOCALAPPDATA": str(base / "local")},
                    platform="windows",
                )

    def test_missing_katago_is_actionable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = make_resources(Path(directory) / "resources")
            with self.assertRaisesRegex(RuntimePathError, "--katago-executable"):
                resolve_runtime_paths(
                    resource_root=root,
                    environ={},
                    which=lambda name: None,
                )

    def test_production_path_modules_contain_no_developer_home(self):
        project = Path(__file__).resolve().parent
        for relative in ("server.py", "runtime_paths.py", "backend_startup.py"):
            text = (project / relative).read_text(encoding="utf-8")
            self.assertNotIn("/Users/ouo1010", text, relative)

    def test_runtime_does_not_write_a_fixed_repository_temp_sgf(self):
        project = Path(__file__).resolve().parent
        for relative in ("server.py", "sgf_utils.py", "analysis_logic.py"):
            text = (project / relative).read_text(encoding="utf-8")
            self.assertNotIn("temp_upload.sgf", text, relative)


if __name__ == "__main__":
    unittest.main()
