"""Countdown deadlines and native notifications without a user workspace."""
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.focus_timer import FocusTimer
from app.desktop import DesktopController
from app.desktop_notification import FocusReminder


class FakeTimer:
    def __init__(self, seconds, callback, args):
        self.seconds, self.callback, self.args = seconds, callback, args
        self.canceled = False
    def start(self):
        pass
    def cancel(self):
        self.canceled = True
    def fire(self):
        self.callback(*self.args)


class FocusTimerTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.complete = Mock()
        self.created = []
        def factory(*args, **kwargs):
            timer = FakeTimer(*args, **kwargs)
            self.created.append(timer)
            return timer
        self.timer = FocusTimer(self.complete, clock=lambda:self.now, timer_factory=factory)
    def tearDown(self):
        self.timer.close()

    def test_deadline_does_not_depend_on_page_ticks(self):
        self.timer.configure(60, '专注', running=True)
        self.now += 54.25
        self.assertEqual(self.timer.snapshot()['seconds'], 6)
        self.now += 5.75
        self.created[-1].fire()
        self.created[-1].fire()
        self.complete.assert_called_once_with('专注', 60, 1)
        self.assertFalse(self.timer.snapshot()['running'])

    def test_pause_resume_and_stale_callbacks(self):
        self.timer.configure(60, '专注', running=True)
        old = self.created[-1]
        self.now += 19.5
        paused = self.timer.pause()
        self.assertEqual(paused['remaining'], 40.5)
        self.now += 100
        old.fire()
        self.complete.assert_not_called()
        self.assertEqual(self.timer.snapshot()['remaining'], 40.5)
        self.timer.configure(paused['remaining'], '专注', 60, running=True)
        self.now += 40.5
        self.created[-1].fire()
        self.complete.assert_called_once()

    def test_reset_mode_change_and_exit_cancel_pending_notification(self):
        self.timer.configure(60, '专注', running=True)
        old = self.created[-1]
        self.timer.configure(300, '休息')
        old.fire()
        self.assertEqual(self.timer.snapshot()['mode'], '休息')
        self.complete.assert_not_called()
        self.timer.configure(1, '休息', running=True)
        current = self.created[-1]
        self.timer.close()
        current.fire()
        self.complete.assert_not_called()

    def test_expiry_at_pause_boundary_completes_once(self):
        self.timer.configure(2, '休息', running=True)
        self.now += 2
        self.timer.pause()
        self.created[-1].fire()
        self.complete.assert_called_once()

    def test_invalid_inputs_do_not_replace_a_running_timer(self):
        self.timer.configure(60, '专注', running=True)
        for seconds in [0, -1, float('nan'), 14401, True, '60']:
            with self.assertRaises(ValueError):
                self.timer.configure(seconds, '专注')
        self.assertTrue(self.timer.snapshot()['running'])

    def test_real_background_thread_fires_without_webview(self):
        completed = threading.Event()
        timer = FocusTimer(lambda *args:completed.set())
        try:
            timer.configure(.04, '专注', running=True)
            self.assertTrue(completed.wait(2))
        finally:
            timer.close()

    def test_hidden_window_receives_native_notification_even_if_page_unavailable(self):
        controller = DesktopController('测试工作台', Path('.'), {}, Mock())
        controller.hidden = True
        controller.window = Mock()
        controller.window.evaluate_js.side_effect = RuntimeError('WebView suspended')
        controller._window_ready.set()
        controller.focus_reminder = Mock()
        try:
            controller._focus_completed('专注', 60, 1)
            controller.focus_reminder.notify.assert_called_once()
            self.assertEqual(controller.focus_reminder.notify.call_args.args[0], '专注')
            self.assertIn('专注时间已结束', controller.focus_reminder.notify.call_args.args[1])
            controller.window.show.assert_not_called()
            controller.quitting = True
            controller._focus_completed('休息', 60, 2)
            self.assertEqual(controller.focus_reminder.notify.call_count, 1)
        finally:
            controller.focus_timer.close()

    def test_reminder_theme_can_arrive_before_native_window_creation(self):
        window = Mock(native=None)
        reminder = FocusReminder(window, '测试工作台', Mock())
        reminder.set_theme('dark')
        self.assertEqual(reminder.theme, 'dark')
        self.assertIsNone(reminder.form)
        reminder.close()
        self.assertTrue(reminder._closed)

    def test_closed_popup_defers_disposal_until_event_processing_finishes(self):
        reminder = FocusReminder(Mock(), '测试工作台', Mock())
        popup, font = Mock(), Mock()
        reminder.form, reminder.pending_count, reminder._fonts = popup, 2, [font]
        reminder._queue_release = Mock()
        reminder._disposed(popup)
        popup.Dispose.assert_not_called()
        font.Dispose.assert_not_called()
        reminder._queue_release.assert_called_once_with(popup, [font])
        self.assertIsNone(reminder.form)
        self.assertEqual(reminder.pending_count, 0)
        reminder._disposed(popup)
        self.assertEqual(reminder._queue_release.call_count, 1)


if __name__ == '__main__':
    unittest.main()
