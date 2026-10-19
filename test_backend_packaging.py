from pathlib import Path
import os
import unittest


PROJECT_ROOT = Path(__file__).resolve().parent
PACKAGING_ROOT = PROJECT_ROOT / "packaging/macos"


class BackendPackagingTests(unittest.TestCase):
    def test_spec_is_onedir_and_keeps_large_runtime_assets_external(self):
        text = (PACKAGING_ROOT / "backend.spec").read_text(encoding="utf-8")

        self.assertIn("COLLECT(", text)
        self.assertNotIn("BUNDLE(", text)
        self.assertNotIn("model.bin.gz", text)
        self.assertNotIn("analysis.cfg", text)
        self.assertNotIn("logosgo_corpus_full.csv", text)

    def test_spec_explicitly_covers_all_production_local_modules(self):
        text = (PACKAGING_ROOT / "backend.spec").read_text(encoding="utf-8")
        required_modules = {
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
        }

        for module in required_modules:
            with self.subTest(module=module):
                self.assertIn(f'"{module}"', text)

    def test_runtime_and_build_requirements_are_separate(self):
        runtime = (PACKAGING_ROOT / "requirements-backend.txt").read_text(
            encoding="utf-8"
        )
        build = (PACKAGING_ROOT / "requirements-build.txt").read_text(
            encoding="utf-8"
        )
        runtime_packages = {
            line.split("==", 1)[0]
            for line in runtime.splitlines()
            if line and not line.startswith("#")
        }

        self.assertIn("Flask==3.1.3", runtime)
        self.assertIn("pandas==2.3.3", runtime)
        self.assertNotIn("PyInstaller", runtime_packages)
        self.assertNotIn("matplotlib", {name.lower() for name in runtime_packages})
        self.assertIn("PyInstaller==6.22.3", build)

    def test_build_script_uses_isolated_clean_output_directories(self):
        script = PACKAGING_ROOT / "build_backend.sh"
        text = script.read_text(encoding="utf-8")

        self.assertTrue(os.access(script, os.X_OK))
        self.assertIn('WORK_DIR="${SCRIPT_DIR}/build"', text)
        self.assertIn('DIST_DIR="${SCRIPT_DIR}/dist"', text)
        self.assertIn('rm -rf "${WORK_DIR}" "${DIST_DIR}"', text)
        self.assertNotIn("flutter_application_1/build", text)


if __name__ == "__main__":
    unittest.main()
