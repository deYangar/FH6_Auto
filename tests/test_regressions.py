import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import main
from anti_cheat import AntiCheatMixin
from config import set_scheme_dir
from fh6_backend import BackgroundInputManager
from sell_logic import SellMixin
from vision import VisionMixin


class _DummyHeartbeat(AntiCheatMixin):
    def __init__(self):
        self.messages = []
        self.is_running = True
        self._init_anti_cheat_state()

    def log(self, message, level=None):
        self.messages.append((level, message))


class ThreadLifecycleTests(unittest.TestCase):
    def test_capture_cache_release_is_imported_for_pipeline_cleanup(self):
        self.assertTrue(callable(main.release_capture_cache))

    def test_stopped_heartbeat_does_not_revive_on_next_run(self):
        heartbeat = _DummyHeartbeat()
        heartbeat.start_anti_cheat_heartbeat()
        old_thread = heartbeat._heartbeat_thread

        heartbeat.stop_anti_cheat_heartbeat()
        heartbeat.is_running = True
        time.sleep(0.05)

        self.assertFalse(old_thread.is_alive())

    def test_background_input_thread_is_joined(self):
        manager = BackgroundInputManager(0)
        manager.start()
        old_thread = manager._thread

        manager.stop()

        self.assertFalse(old_thread.is_alive())


class RecognitionOrderingTests(unittest.TestCase):
    def test_visual_first_car_wins_over_higher_score_next_car(self):
        vision = object.__new__(VisionMixin)
        candidates = [
            (510, 200, 0.99, "next-car"),
            (205, 420, 0.86, "lower-current-column"),
            (210, 190, 0.82, "visual-first"),
        ]

        ordered = vision._sort_column_first(candidates, tolerance=70)

        self.assertEqual("visual-first", ordered[0][3])
        self.assertEqual("next-car", ordered[-1][3])

    def test_strict_matcher_selects_first_visible_new_car(self):
        set_scheme_dir("scheme_1")
        template = cv2.imread("images/scheme_1/newCC.png")
        height, width = template.shape[:2]
        screen = np.full((700, 1000, 3), 32, dtype=np.uint8)
        screen[120:120 + height, 100:100 + width] = template
        screen[120:120 + height, 520:520 + width] = template

        vision = object.__new__(VisionMixin)
        vision.is_running = True
        vision.regions = {"全界面": (0, 0, 1000, 700)}
        vision.config = {"class_image": "classS2829.png"}
        vision.template_cache = {}
        vision.scaled_template_cache = {}
        vision.file_template_cache = {}
        vision.edge_template_cache = {}
        vision.scaled_edge_template_cache = {}
        vision.capture_region = lambda region=None, mask_areas=None: screen.copy()
        vision.log = lambda *args, **kwargs: None
        vision.is_debug_screenshots_enabled = lambda: False

        position = vision.find_new_consumable_car_strict(vision.regions["全界面"])

        self.assertIsNotNone(position)
        self.assertLess(position[0], 450, "不应跳过左侧当前车而选择下一辆")


class _DummySellFocus(SellMixin):
    def __init__(self, remove_position):
        self.regions = {"中间": (0, 0, 100, 100)}
        self.remove_position = remove_position
        self.events = []

    def log(self, message, level=None):
        self.events.append(("log", message))

    def hw_press(self, key, **kwargs):
        self.events.append(("key", key))

    def wait_for_image_gray(self, *args, **kwargs):
        self.events.append(("detect", args[0]))
        return self.remove_position


class SellFocusFallbackTests(unittest.TestCase):
    @patch("sell_logic.time.sleep", return_value=None)
    def test_template_miss_checks_current_focus_before_navigation(self, _sleep):
        seller = _DummySellFocus((50, 50))

        position = seller._try_open_focused_remove_menu()

        self.assertEqual((50, 50), position)
        key_events = [event for event in seller.events if event[0] == "key"]
        self.assertEqual([("key", "enter")], key_events)
        self.assertNotIn(("key", "right"), key_events)


if __name__ == "__main__":
    unittest.main()
