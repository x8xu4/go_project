from pathlib import Path
import os
import plistlib
import unittest


PROJECT_ROOT = Path(__file__).resolve().parent
PACKAGING_ROOT = PROJECT_ROOT / "packaging/macos"
FLUTTER_MACOS = PROJECT_ROOT / "flutter_application_1/macos"


class AppPackagingTests(unittest.TestCase):
    def test_build_pipeline_is_executable_and_assembles_all_layers(self):
        script = PACKAGING_ROOT / "build_app.sh"
        text = script.read_text(encoding="utf-8")

        self.assertTrue(os.access(script, os.X_OK))
        for requirement in (
            "build_backend.sh",
            "build_native_runtime.sh",
            "generate_app_icons.sh",
            '" build macos --release',
            "LogosGoRuntime",
            "codesign --verify --deep --strict",
            "lipo -archs",
            "-thin arm64",
            "otool -L",
            "install_name_tool -delete_rpath",
            "model/model.bin.gz",
            "config/analysis.cfg",
            "data/logosgo_corpus_full.csv",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, text)

    def test_icon_generator_preserves_master_and_builds_expected_sizes(self):
        script = PACKAGING_ROOT / "generate_app_icons.sh"
        text = script.read_text(encoding="utf-8")
        self.assertTrue(os.access(script, os.X_OK))
        self.assertIn("logosgo_icon_master.png", text)
        self.assertIn("16 32 64 128 256 512 1024", text)
        self.assertNotIn("rm ", text)

    def test_release_entitlements_disable_app_sandbox(self):
        entitlements = plistlib.loads(
            (FLUTTER_MACOS / "Runner/Release.entitlements").read_bytes()
        )
        self.assertNotIn("com.apple.security.app-sandbox", entitlements)
        self.assertEqual(entitlements, {})

    def test_runner_owns_backend_lifecycle_and_flutter_bridge(self):
        app_delegate = (FLUTTER_MACOS / "Runner/AppDelegate.swift").read_text(
            encoding="utf-8"
        )
        window = (FLUTTER_MACOS / "Runner/MainFlutterWindow.swift").read_text(
            encoding="utf-8"
        )
        for evidence in (
            "SecRandomCopyBytes",
            'environment["LOGOSGO_INSTANCE_TOKEN"] = token',
            "allocateLoopbackPort",
            "/health",
            '"--parent-pid"',
            "startupTimeout",
            "applicationWillTerminate",
        ):
            self.assertIn(evidence, app_delegate)
        self.assertIn('name: "logosgo/backend"', window)
        self.assertIn('call.method == "getBackendConfiguration"', window)

    def test_metadata_is_logosgo_specific_and_arm64_macos_26(self):
        config = (FLUTTER_MACOS / "Runner/Configs/AppInfo.xcconfig").read_text(
            encoding="utf-8"
        )
        self.assertIn("PRODUCT_NAME = LogosGo", config)
        self.assertIn("PRODUCT_BUNDLE_IDENTIFIER = com.logosgo.desktop", config)
        self.assertIn("ARCHS = arm64", config)
        self.assertIn("MACOSX_DEPLOYMENT_TARGET = 26.0", config)
        self.assertNotIn("com.example", config)


if __name__ == "__main__":
    unittest.main()
