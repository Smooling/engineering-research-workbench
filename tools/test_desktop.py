"""Desktop lifecycle regressions without requiring a GUI or user workspace."""
from __future__ import annotations

import sys
import os
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import client
from app.desktop import DesktopController, SingleInstance
from app.windows_frame import work_area_bounds, resize_hit_test
from ctypes import wintypes


class DesktopTests(unittest.TestCase):
    def test_local_readiness_bypasses_system_proxy_and_urllib_opener(self):
        class HealthHandler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                data = json.dumps({"ok": True, "version": "test"}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1", "http_proxy": "http://127.0.0.1:1", "NO_PROXY": "", "no_proxy": ""}), patch("urllib.request.urlopen", side_effect=OSError("proxy unavailable")):
                self.assertEqual(client._health(f"http://127.0.0.1:{server.server_port}"), {"ok": True, "version": "test"})
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_native_resize_edges_and_corners_on_negative_monitor(self):
        bounds = wintypes.RECT(-1920, -100, -720, 700)
        points = [("w",-1919,300,10),("e",-722,300,11),("n",-1300,-99,12),("s",-1300,698,15),
                  ("nw",-1918,-98,13),("ne",-722,-98,14),("sw",-1918,698,16),("se",-722,698,17)]
        for name,x,y,expected in points:
            with self.subTest(edge=name):
                self.assertEqual(resize_hit_test(x,y,bounds,9,15),expected)
        self.assertIsNone(resize_hit_test(-1300,300,bounds,9,15))
        self.assertIsNone(resize_hit_test(-1930,300,bounds,9,15))
        self.assertEqual(resize_hit_test(-1904,-99,bounds,18,30),13)

    def setUp(self):
        self.window = Mock()
        self.saved = []
        self.controller = DesktopController("Test", Path("."), {"width":1200,"height":800,"maximized":False},
                                            lambda state: self.saved.append(dict(state)))
        self.controller.window = self.window
        self.controller._window_ready.set()

    def test_hide_retains_window_and_server_lifecycle(self):
        self.controller.tray_available = True
        self.controller.hide()
        self.window.hide.assert_called_once()
        self.window.destroy.assert_not_called()
        self.assertTrue(self.controller.hidden)
        self.assertFalse(self.controller.quitting)
        self.assertEqual(len(self.saved), 1)

    def test_tray_failure_falls_back_to_taskbar(self):
        self.controller.hide()
        self.window.minimize.assert_called_once()
        self.window.hide.assert_not_called()
        self.assertFalse(self.controller.hidden)

    def test_dirty_editor_cancel_keeps_window_reachable(self):
        self.window.evaluate_js.return_value = True
        self.controller._request_editor_exit = Mock(return_value=False)
        self.assertFalse(self.controller.request_quit())
        self.window.show.assert_called_once()
        self.window.destroy.assert_not_called()
        self.assertFalse(self.controller.quitting)
        self.window.create_confirmation_dialog.assert_not_called()

    def test_dirty_editor_confirm_exits(self):
        self.window.evaluate_js.return_value = True
        self.controller._request_editor_exit = Mock(return_value=True)
        self.assertTrue(self.controller.request_quit())
        self.window.destroy.assert_called_once()
        self.assertTrue(self.controller.quitting)
        self.assertTrue(self.controller.on_closing())

    def test_editor_exit_acknowledgement_requires_current_token(self):
        self.controller._exit_token = 'pending-exit'
        self.assertFalse(self.controller.resolve_exit('stale-exit', True))
        self.assertFalse(self.controller._exit_event.is_set())
        self.assertTrue(self.controller.resolve_exit('pending-exit', True))
        self.assertTrue(self.controller._exit_event.is_set())
        self.assertTrue(self.controller._exit_approved)

    def test_unavailable_page_requires_exit_confirmation(self):
        self.window.evaluate_js.side_effect = RuntimeError("page not responding")
        self.window.create_confirmation_dialog.return_value = False
        self.assertFalse(self.controller.request_quit())
        self.window.destroy.assert_not_called()

    def test_maximized_dimensions_do_not_replace_normal_dimensions(self):
        self.controller.on_maximized()
        self.controller.on_resized(1920,1080)
        self.assertEqual(self.controller.state["width"],1200)
        self.controller.on_restored()
        self.controller.on_resized(1300,850)
        self.assertEqual(self.controller.state["width"],1300)

    def test_show_before_window_ready_is_deferred(self):
        self.controller._window_ready.clear()
        self.controller.show()
        self.window.show.assert_not_called()
        self.assertTrue(self.controller._show_pending)

    def test_atomic_state_roundtrip_and_invalid_state(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(client.paths,"DATA_ROOT",Path(directory)):
            state = {"width":1200,"height":800,"maximized":True,"close_action":"quit"}
            client._save_window_state(state)
            self.assertEqual(client._load_window_state(),state)
            self.assertFalse((Path(directory)/"window-state.json.tmp").exists())
            (Path(directory)/"window-state.json").write_text('{"width":-1}')
            self.assertEqual(client._load_window_state()["width"],0)

    def test_minimize_keeps_taskbar_entry_even_with_tray(self):
        self.controller.tray_available = True
        self.controller.minimize()
        self.controller.on_minimized()
        self.window.minimize.assert_called_once()
        self.window.hide.assert_not_called()

    def test_close_behavior_is_saved_and_applied(self):
        self.controller.tray_available = True
        self.controller.set_close_action("tray")
        self.controller.request_close()
        self.window.hide.assert_called_once()
        self.window.destroy.assert_not_called()
        self.window.evaluate_js.return_value = False
        self.controller.set_close_action("quit")
        self.assertEqual(self.saved[-1]["close_action"],"quit")
        self.controller.request_close()
        self.window.destroy.assert_called_once()

    def test_invalid_close_behavior_is_rejected(self):
        with self.assertRaises(ValueError):
            self.controller.set_close_action("unknown")

    def test_maximize_reserves_taskbar_on_either_monitor(self):
        self.assertEqual(work_area_bounds(wintypes.RECT(0,0,1920,1080),wintypes.RECT(0,0,1920,1032)),(0,0,1920,1032))
        self.assertEqual(work_area_bounds(wintypes.RECT(-1920,0,0,1080),wintypes.RECT(-1880,0,0,1080)),(40,0,1880,1080))
        self.assertEqual(work_area_bounds(wintypes.RECT(1920,-400,4480,1040),wintypes.RECT(1920,-360,4480,1040)),(0,40,2560,1400))

    @unittest.skipUnless(sys.platform == "win32", "Windows named event integration")
    def test_named_event_activates_single_instance_and_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            first = SingleInstance(Path(directory))
            activated = threading.Event()
            try:
                first.listen(activated.set)
                second = SingleInstance(Path(directory))
                try:
                    self.assertTrue(first.primary)
                    self.assertFalse(second.primary)
                    self.assertTrue(activated.wait(3))
                finally:
                    second.close()
            finally:
                first.close()
            third = SingleInstance(Path(directory))
            try:
                self.assertTrue(third.primary)
            finally:
                third.close()

    def test_restart_uses_same_source_entry_and_arguments(self):
        with patch.object(client.paths,"FROZEN",False):
            arguments=client._launch_arguments(["--background","--data-dir","C:/Test Data"])
            self.assertEqual(Path(arguments[1]).name,"client.py")
            self.assertEqual(arguments[-1],"C:/Test Data")
        with patch.object(client.paths,"FROZEN",True):
            self.assertEqual(client._launch_arguments(["--background"]),[sys.executable,"--background"])

    def test_frozen_restart_unpacks_independent_resources(self):
        with patch.object(client.paths,"FROZEN",True), patch.dict(client.os.environ,{"ERW_TEST":"retained"}):
            environment=client._restart_environment()
            self.assertEqual(environment["PYINSTALLER_RESET_ENVIRONMENT"],"1")
            self.assertEqual(environment["ERW_TEST"],"retained")

    def test_fallback_origin_is_stable_until_service_config_changes(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(client.paths,"DATA_ROOT",Path(directory)):
            client._remember_service_port("127.0.0.1",8765,18769)
            self.assertEqual(client._preferred_service_port("127.0.0.1",8765),18769)
            self.assertEqual(client._preferred_service_port("127.0.0.1",8766),8766)
            self.assertEqual(client._preferred_service_port("0.0.0.0",8765),8765)


if __name__ == "__main__":
    unittest.main()
