from pathlib import Path
import unittest
from unittest import mock

import server
from backend_startup import (
    API_SCHEMA_VERSION,
    BACKEND_DEBUG,
    BACKEND_HOST,
    DEVELOPMENT_PORT,
    INSTANCE_TOKEN_HEADER,
    SERVICE_IDENTITY,
    BackendIdentity,
    development_startup_config,
    parse_backend_startup_args,
)


class BackendStartupTests(unittest.TestCase):
    def test_default_development_startup_is_local_and_not_debug(self):
        config = development_startup_config({})
        self.assertEqual(config.host, BACKEND_HOST)
        self.assertEqual(config.host, "127.0.0.1")
        self.assertEqual(config.port, DEVELOPMENT_PORT)
        self.assertEqual(config.port, 5001)
        self.assertFalse(config.debug)
        self.assertFalse(BACKEND_DEBUG)
        self.assertTrue(config.instance_token)
        self.assertIsNone(config.parent_pid)

    def test_explicit_port_token_and_resource_paths_are_parsed(self):
        config = parse_backend_startup_args(
            [
                "--port",
                "53123",
                "--instance-token",
                "runner-secret",
                "--resource-root",
                "/tmp/logosgo-resources",
                "--katago-executable",
                "/tmp/logosgo-katago",
                "--parent-pid",
                "12345",
            ],
            environ={},
        )
        self.assertEqual(config.port, 53123)
        self.assertEqual(config.instance_token, "runner-secret")
        self.assertEqual(config.resource_root, Path("/tmp/logosgo-resources"))
        self.assertEqual(config.katago_executable, Path("/tmp/logosgo-katago"))
        self.assertEqual(config.parent_pid, 12345)

    def test_environment_is_supported_and_cli_wins(self):
        config = parse_backend_startup_args(
            ["--port", "53124", "--instance-token", "cli-token"],
            environ={
                "LOGOSGO_PORT": "53120",
                "LOGOSGO_INSTANCE_TOKEN": "environment-token",
                "LOGOSGO_RESOURCE_ROOT": "/tmp/environment-resources",
            },
        )
        self.assertEqual(config.port, 53124)
        self.assertEqual(config.instance_token, "cli-token")
        self.assertEqual(
            config.resource_root,
            Path("/tmp/environment-resources"),
        )

    def test_invalid_port_and_empty_token_fail_clearly(self):
        for arguments in (
            ["--port", "0"],
            ["--port", "70000"],
            ["--port", "not-a-port"],
            ["--instance-token", "   "],
            ["--parent-pid", "1"],
            ["--parent-pid", "not-a-pid"],
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(SystemExit):
                    parse_backend_startup_args(arguments, environ={})

    def test_identity_is_stable_but_does_not_expose_token(self):
        identity = BackendIdentity("private-runner-token")
        self.assertEqual(identity.instance_id, BackendIdentity("private-runner-token").instance_id)
        self.assertNotIn("private-runner-token", identity.instance_id)
        self.assertTrue(identity.verify("private-runner-token"))
        self.assertFalse(identity.verify("wrong-token"))
        self.assertFalse(identity.verify(None))

    def test_health_reports_identity_and_verifies_instance_token(self):
        with server.app.test_client() as client:
            anonymous = client.get("/health")
            verified = client.get(
                "/health",
                headers={
                    INSTANCE_TOKEN_HEADER: server.STARTUP_CONFIG.instance_token,
                },
            )
        self.assertEqual(anonymous.status_code, 200)
        payload = anonymous.get_json()
        self.assertEqual(payload["service"], SERVICE_IDENTITY)
        self.assertEqual(payload["api_schema_version"], API_SCHEMA_VERSION)
        self.assertTrue(payload["ready"])
        self.assertFalse(payload["token_verified"])
        self.assertNotIn("resource_root", payload)
        self.assertNotIn("private", str(payload).lower())
        self.assertIsNone(anonymous.headers.get("Access-Control-Allow-Origin"))
        self.assertTrue(verified.get_json()["token_verified"])
        self.assertEqual(verified.get_json()["instance_id"], payload["instance_id"])

    def test_health_does_not_start_either_katago_process(self):
        self.assertIsNone(server.katago_client._process)
        self.assertIsNone(server.position_katago_client._process)

    def test_shutdown_requires_instance_token_and_schedules_graceful_stop(self):
        with mock.patch.object(server.threading, "Thread") as thread:
            with server.app.test_client() as client:
                denied = client.post("/shutdown")
                accepted = client.post(
                    "/shutdown",
                    headers={
                        INSTANCE_TOKEN_HEADER: server.STARTUP_CONFIG.instance_token,
                    },
                )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.get_json()["status"], "shutting_down")
        thread.assert_called_once()
        self.assertTrue(thread.call_args.kwargs["daemon"])
        thread.return_value.start.assert_called_once_with()

    def test_katago_runtime_logs_are_outside_immutable_resources(self):
        expected = str(server.RUNTIME_PATHS.writable.logs)
        self.assertEqual(server.katago_client.working_directory, expected)
        self.assertEqual(server.position_katago_client.working_directory, expected)
        self.assertFalse(
            server.RUNTIME_PATHS.writable.logs.is_relative_to(
                server.RUNTIME_PATHS.resource_root
            )
        )
        with server.app.test_client() as client:
            response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(server.katago_client._process)
        self.assertIsNone(server.position_katago_client._process)

    def test_run_backend_forces_localhost_and_disables_reloader(self):
        with mock.patch.object(server.app, "run") as run:
            server.run_backend()
        run.assert_called_once_with(
            host="127.0.0.1",
            port=server.STARTUP_CONFIG.port,
            debug=False,
            use_reloader=False,
        )


if __name__ == "__main__":
    unittest.main()
