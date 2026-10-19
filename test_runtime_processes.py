import signal
import unittest
from unittest import mock

from runtime_processes import (
    WINDOWS_CREATE_NEW_PROCESS_GROUP,
    WINDOWS_CREATE_NO_WINDOW,
    child_process_policy,
    install_termination_handlers,
    katago_popen_kwargs,
    parent_wait_strategy,
    prepare_backend_process_group,
    process_platform,
)


class RuntimeProcessTests(unittest.TestCase):
    def test_platform_and_parent_wait_strategy_are_explicit(self):
        self.assertEqual(process_platform("posix"), "posix")
        self.assertEqual(process_platform("nt"), "windows")
        self.assertEqual(parent_wait_strategy(os_name="posix"), "posix_pid_probe")
        self.assertEqual(
            parent_wait_strategy(os_name="nt"),
            "windows_process_handle",
        )

    def test_posix_child_launch_adds_no_windows_kwargs(self):
        self.assertEqual(katago_popen_kwargs(os_name="posix"), {})
        policy = child_process_policy(
            os_name="posix",
            hide_window=True,
            new_process_group=True,
        )
        self.assertEqual(policy.creationflags, 0)
        self.assertEqual(policy.popen_kwargs(), {})

    def test_windows_child_launch_flags_are_deterministic(self):
        policy = child_process_policy(
            os_name="nt",
            hide_window=True,
            new_process_group=True,
        )
        self.assertEqual(policy.platform_identifier, "windows")
        self.assertEqual(
            policy.creationflags,
            WINDOWS_CREATE_NO_WINDOW | WINDOWS_CREATE_NEW_PROCESS_GROUP,
        )
        self.assertEqual(policy.popen_kwargs(), {"creationflags": policy.creationflags})
        self.assertEqual(
            katago_popen_kwargs(os_name="nt"),
            {"creationflags": WINDOWS_CREATE_NO_WINDOW},
        )

    def test_backend_process_group_is_preserved_only_on_posix(self):
        set_group = mock.Mock()
        prepare_backend_process_group(
            os_name="posix",
            set_process_group=set_group,
        )
        set_group.assert_called_once_with(0, 0)

        set_group.reset_mock()
        prepare_backend_process_group(
            os_name="nt",
            set_process_group=set_group,
        )
        set_group.assert_not_called()

    def test_signal_registration_keeps_posix_contract(self):
        register = mock.Mock()
        handler = mock.Mock()
        installed = install_termination_handlers(
            handler,
            os_name="posix",
            register=register,
        )
        self.assertEqual(installed, (signal.SIGTERM, signal.SIGINT))
        self.assertEqual(
            register.call_args_list,
            [mock.call(signal.SIGTERM, handler), mock.call(signal.SIGINT, handler)],
        )


if __name__ == "__main__":
    unittest.main()
