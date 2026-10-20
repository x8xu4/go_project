from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parent
PACKAGING_ROOT = PROJECT_ROOT / "packaging/windows"
WINDOWS_RUNNER = PROJECT_ROOT / "flutter_application_1/windows/runner"


class WindowsPackagingPreparationTests(unittest.TestCase):
    def test_windows_runner_implements_backend_lifecycle_channel(self):
        manager = (WINDOWS_RUNNER / "backend_manager.cpp").read_text(
            encoding="utf-8"
        )
        window = (WINDOWS_RUNNER / "flutter_window.cpp").read_text(
            encoding="utf-8"
        )
        main = (WINDOWS_RUNNER / "main.cpp").read_text(encoding="utf-8")

        self.assertIn("BackendManager backend_manager", main)
        self.assertIn("backend_manager.Stop()", main)
        self.assertIn('"logosgo/backend"', window)
        self.assertIn('"getBackendConfiguration"', window)
        self.assertIn('"instanceToken"', window)
        self.assertIn("BACKEND_STARTUP_FAILED", window)
        self.assertIn("CreateProcessW", manager)
        self.assertIn("JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE", manager)
        self.assertIn("BCryptGenRandom", manager)
        self.assertIn("BCRYPT_SHA256_ALGORITHM", manager)
        self.assertIn("AssignProcessToJobObject", manager)
        self.assertIn("TerminateJobObject", manager)
        self.assertIn("SetHandleInformation", manager)
        self.assertIn("ERROR_INSUFFICIENT_BUFFER", manager)

    def test_windows_runner_uses_dynamic_port_and_authenticated_health(self):
        manager = (WINDOWS_RUNNER / "backend_manager.cpp").read_text(
            encoding="utf-8"
        )
        self.assertIn("address.sin_port = 0", manager)
        self.assertIn('L"/health"', manager)
        self.assertIn('L"/shutdown"', manager)
        self.assertIn('L"X-LogosGo-Instance"', manager)
        for field in (
            '"service"',
            '"api_schema_version"',
            '"ready"',
            '"token_verified"',
            '"instance_id"',
        ):
            with self.subTest(field=field):
                self.assertIn(field, manager)
        self.assertNotIn("localhost:5001", manager)
        self.assertIn(
            "received_instance_id == configuration_.instance_id", manager
        )

    def test_windows_runner_passes_the_complete_packaged_backend_contract(self):
        manager = (WINDOWS_RUNNER / "backend_manager.cpp").read_text(
            encoding="utf-8"
        )
        for argument in (
            'L"--port"',
            'L"--instance-token"',
            'L"--resource-root"',
            'L"--katago-executable"',
            'L"--parent-pid"',
        ):
            with self.subTest(argument=argument):
                self.assertIn(argument, manager)
        self.assertIn('executable_directory / L"runtime"', manager)
        self.assertIn('L"LogosGo" / L"Logs"', manager)
        self.assertIn("CREATE_NEW", manager)

    def test_windows_runner_probes_opencl_before_non_avx2_eigen(self):
        manager = (WINDOWS_RUNNER / "backend_manager.cpp").read_text(
            encoding="utf-8"
        )
        selection = manager[manager.index("bool BackendManager::SelectKataGo") :]
        self.assertLess(
            selection.index("layout.opencl_executable"),
            selection.index("layout.eigen_executable"),
        )
        self.assertIn("kKataGoReadyMarker", manager)
        self.assertIn("layout.model_file.wstring()", manager)
        self.assertIn("layout.config_file.wstring()", manager)
        self.assertNotIn("eigenavx2", manager.lower())

    def test_windows_runner_cmake_includes_native_dependencies(self):
        text = (WINDOWS_RUNNER / "CMakeLists.txt").read_text(encoding="utf-8")
        for requirement in (
            '"backend_manager.cpp"',
            '"bcrypt.lib"',
            '"winhttp.lib"',
            '"ws2_32.lib"',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, text)

    def test_windows_spec_is_onedir_and_has_no_macos_or_large_runtime_assets(self):
        text = (PACKAGING_ROOT / "backend.spec").read_text(encoding="utf-8")
        self.assertIn("COLLECT(", text)
        self.assertIn('name="logosgo_backend"', text)
        self.assertNotIn("target_arch", text)
        self.assertNotIn("codesign_identity", text)
        self.assertNotIn("BUNDLE(", text)
        self.assertNotIn("model.bin.gz", text)
        self.assertNotIn("analysis.cfg", text)
        self.assertNotIn("logosgo_corpus_full.csv", text)

    def test_windows_spec_covers_shared_production_modules(self):
        text = (PACKAGING_ROOT / "backend.spec").read_text(encoding="utf-8")
        for module in (
            "analysis_logic",
            "backend_startup",
            "directional_explanation",
            "explanation_classifier",
            "explanation_features",
            "logos_engine",
            "review_selection",
            "review_summary",
            "runtime_paths",
            "runtime_processes",
            "sgf_utils",
            "structured_explanation",
        ):
            with self.subTest(module=module):
                self.assertIn(f'"{module}"', text)

    def test_build_script_refuses_non_windows_and_uses_isolated_outputs(self):
        text = (PACKAGING_ROOT / "build_backend.ps1").read_text(encoding="utf-8")
        self.assertIn('$env:OS -ne "Windows_NT"', text)
        self.assertIn("packaging/windows/requirements-build.txt", text)
        self.assertIn('Join-Path $ScriptDirectory "build"', text)
        self.assertIn('Join-Path $ScriptDirectory "dist"', text)
        self.assertIn("logosgo_backend.exe", text)
        self.assertNotIn("flutter_application_1\\build", text)

    def test_windows_readme_freezes_backend_order_and_runner_contract(self):
        text = (PACKAGING_ROOT / "README.md").read_text(encoding="utf-8")
        selection = text[text.index("## KataGo selection contract") :]
        opencl = selection.index("OpenCL first")
        eigen = selection.index("non-AVX2 Eigen")
        self.assertLess(opencl, eigen)
        for requirement in (
            "CreateProcessW",
            "Job Object",
            "/health",
            "/shutdown",
            "logosgo/backend",
            "getBackendConfiguration",
            "%LOCALAPPDATA%",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, text)


if __name__ == "__main__":
    unittest.main()
