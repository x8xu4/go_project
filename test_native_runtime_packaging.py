from pathlib import Path
import os
import unittest


PROJECT_ROOT = Path(__file__).resolve().parent
PACKAGING_ROOT = PROJECT_ROOT / "packaging/macos"


class NativeRuntimePackagingTests(unittest.TestCase):
    def setUp(self):
        self.script = PACKAGING_ROOT / "build_native_runtime.sh"
        self.text = self.script.read_text(encoding="utf-8")

    def test_script_is_executable_and_requires_explicit_inputs(self):
        self.assertTrue(os.access(self.script, os.X_OK))
        for option in ("--katago", "--backend-dir", "--model", "--config", "--corpus"):
            with self.subTest(option=option):
                self.assertIn(option, self.text)

    def test_script_stages_expected_runtime_layout(self):
        for relative in (
            "backend",
            "katago/katago",
            "katago/lib",
            "model/model.bin.gz",
            "config/analysis.cfg",
            "data/logosgo_corpus_full.csv",
            "manifest/native-dependencies.tsv",
            "manifest/assets.sha256",
        ):
            with self.subTest(relative=relative):
                self.assertIn(relative, self.text)

    def test_script_recurses_rewrites_signs_and_verifies_native_dependencies(self):
        for command in (
            "otool -L",
            "install_name_tool -change",
            "install_name_tool -id",
            "install_name_tool -delete_rpath",
            "codesign --force --sign -",
            "codesign --verify --strict",
            "lipo -archs",
        ):
            with self.subTest(command=command):
                self.assertIn(command, self.text)

    def test_script_has_no_fixed_developer_machine_input_path(self):
        self.assertNotIn('KATAGO_SOURCE="/opt/', self.text)
        self.assertNotIn('BACKEND_SOURCE="/Users/', self.text)
        self.assertNotIn('MODEL_SOURCE="/Users/', self.text)
        self.assertIn("All inputs are copied", self.text)
        self.assertIn("binaries and assets are never edited", self.text)


if __name__ == "__main__":
    unittest.main()
