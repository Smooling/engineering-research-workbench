"""Port-conflict startup behavior without binding ports or opening browsers."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class ServerStartupTests(unittest.TestCase):
    def _setup_startup(self, *, available, existing=None, preferred=8765):
        patches = [
            patch.object(server.config, "init"),
            patch.object(server.config, "get_app", return_value={
                "host": "127.0.0.1", "port": 8765, "auto_open_browser": False}),
            patch("app.config.workspace_root", return_value=Path("/workbench").resolve()),
            patch.object(server, "_preferred_server_port", return_value=preferred),
            patch.object(server, "_port_available", return_value=available),
            patch.object(server, "_existing_workbench_url", return_value=existing),
            patch.object(server, "_free_port", return_value=49152),
            patch.object(server, "_remember_server_port"),
            patch.object(server, "build_server"),
        ]
        entered = [item.start() for item in patches]
        self.addCleanup(lambda: [item.stop() for item in reversed(patches)])
        return dict(zip(("init", "config", "workspace", "preferred", "available", "existing",
                         "free_port", "remember", "build"), entered))

    def test_reuses_healthy_same_workspace_without_binding_again(self):
        mocks = self._setup_startup(available=False, existing="http://127.0.0.1:8765")
        self.assertIsNone(server._start_or_reuse_server())
        mocks["build"].assert_not_called()
        mocks["remember"].assert_not_called()

    def test_uses_and_remembers_fallback_when_other_service_owns_port(self):
        mocks = self._setup_startup(available=False)
        listener = Mock()
        listener.server_address = ("127.0.0.1", 49152)
        mocks["build"].return_value = (listener, {}, "http://127.0.0.1:49152")
        result = server._start_or_reuse_server()
        self.assertEqual(result[0], listener)
        mocks["build"].assert_called_once_with(port_override=49152)
        mocks["remember"].assert_called_once_with("127.0.0.1", 8765, 49152)

    def test_starts_on_configured_port_when_available(self):
        mocks = self._setup_startup(available=True)
        listener = Mock()
        listener.server_address = ("127.0.0.1", 8765)
        mocks["build"].return_value = (listener, {}, "http://127.0.0.1:8765")
        result = server._start_or_reuse_server()
        self.assertEqual(result[0], listener)
        mocks["build"].assert_called_once_with(port_override=8765)
        mocks["remember"].assert_called_once_with("127.0.0.1", 8765, 8765)

    def test_bind_race_retries_on_fallback_port(self):
        mocks = self._setup_startup(available=True)
        listener = Mock()
        listener.server_address = ("127.0.0.1", 49152)
        conflict = OSError(10048, "address in use")
        mocks["build"].side_effect = [conflict, (listener, {}, "http://127.0.0.1:49152")]
        result = server._start_or_reuse_server()
        self.assertEqual(result[0], listener)
        self.assertEqual(mocks["build"].call_args_list,
                         [call(port_override=8765), call(port_override=49152)])


if __name__ == "__main__":
    unittest.main()
