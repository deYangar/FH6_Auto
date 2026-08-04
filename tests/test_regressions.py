import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import main
from anti_cheat import AntiCheatMixin
from cj_logic import CJMixin
from config import set_scheme_dir
from fh6_backend import BackgroundInputManager
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


class BackgroundInputIsolationTests(unittest.TestCase):
    @patch("fh6_backend.time.sleep", return_value=None)
    @patch("fh6_backend.win32gui.PostMessage")
    @patch("fh6_backend.win32gui.SendMessage")
    @patch(
        "fh6_backend._read_interfering_modifier_state",
        side_effect=[(True, True), (False, False)],
    )
    def test_sync_press_waits_for_alt_or_win_release(
        self, modifier_state, send_message, post_message, _sleep
    ):
        manager = BackgroundInputManager(
            123,
            modifier_settle=0,
            modifier_poll_interval=0.001,
        )

        sent = manager.press("enter", delay=0, use_send=True)

        self.assertTrue(sent)
        self.assertEqual(2, modifier_state.call_count)
        self.assertEqual(1, manager.modifier_waits)
        self.assertEqual(2, send_message.call_count)
        post_message.assert_not_called()


class _DummyMasteryOCR(CJMixin):
    def __init__(self, text):
        self.text = text
        self.regions = {"全界面": (0, 0, 1600, 900)}

    def get_ocr_engine(self):
        return self

    def capture_region(self, _region):
        image = np.zeros((900, 1600, 3), dtype=np.uint8)
        if "车辆熟练度" not in self.text:
            x1r, y1r, x2r, y2r = self._MASTERY_POPUP_HEADER_ROI
            image[
                int(900 * y1r):int(900 * y2r),
                int(1600 * x1r):int(1600 * x2r),
            ] = (0, 255, 190)
        return image

    def detect_text_in_region(self, _image, _region):
        return self.text

    def log(self, *_args, **_kwargs):
        pass


class MasteryPopupTests(unittest.TestCase):
    def test_locked_mastery_popup_is_detected(self):
        bot = _DummyMasteryOCR("必须先解锁相邻的加成")

        self.assertEqual("必须先解锁相邻的加成", bot._detect_mastery_locked_popup())

    def test_locked_mastery_popup_title_is_sufficient(self):
        bot = _DummyMasteryOCR("无法使用额外加成")

        self.assertEqual("无法使用额外加成", bot._detect_mastery_locked_popup())

    def test_normal_mastery_text_is_not_treated_as_popup(self):
        bot = _DummyMasteryOCR("车辆熟练度 购买额外加成")

        self.assertEqual("", bot._detect_mastery_locked_popup())


class _DummyMasteryState(CJMixin):
    def __init__(self):
        self.config = {"skill_dirs": []}
        self.cj_counter = 0
        self.is_running = True
        self.messages = []
        self.opened_from_recovery = None
        self.left_mastery = False

    def log(self, message, level=None):
        self.messages.append((level, message))

    def update_running_ui(self, *_args):
        pass

    def _open_current_vehicle_mastery(self, pos_sjy=None, from_recovery=False):
        self.opened_from_recovery = from_recovery
        return True

    def _mastery_completion_state(self, image=None):
        return True, 0.32

    def _leave_current_vehicle_mastery(self, resume_vehicle_menu=False):
        self.left_mastery = True
        self._cj_resume_vehicle_menu = resume_vehicle_menu
        return True


class _DummyMasteryPath(CJMixin):
    def __init__(self):
        self.config = {"skill_dirs": ["up", "right"]}
        self.is_running = True
        self.pressed = []

    def log(self, *_args, **_kwargs):
        pass

    def hw_press(self, key, **kwargs):
        self.pressed.append((key, kwargs))
        return True

    def _handle_mastery_popup(self, _step):
        return None


class _DummyLocalMasteryRetry(_DummyMasteryState):
    def __init__(self):
        super().__init__()
        self.path_results = ["retry", "sent"]
        self.path_calls = 0

    def _mastery_completion_state(self, image=None):
        return False, 0.0

    def _send_mastery_path_once(self):
        result = self.path_results[self.path_calls]
        self.path_calls += 1
        return result

    def _wait_for_mastery_complete(self, timeout=2.0, interval=0.25):
        return True, 0.32


class _FakeClock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class _DummyUandTWait(CJMixin):
    def __init__(self, clock):
        self.clock = clock
        self.is_running = True
        self.regions = {"全界面": (0, 0, 1600, 900), "左下": (0, 450, 800, 450)}
        self.escaped = False

    def capture_region(self, _region):
        brightness = 0 if self.clock.now < 8.0 else 100
        return np.full((20, 20, 3), brightness, dtype=np.uint8)

    def find_any_image_gray(self, *_args, **_kwargs):
        return (120, 560) if self.escaped else None

    def hw_press(self, key, **_kwargs):
        if key == "esc":
            self.escaped = True

    def log(self, *_args, **_kwargs):
        pass


class _DummyRecoveryRoute(CJMixin):
    def __init__(self):
        self.regions = {"全界面": (0, 0, 1600, 900)}
        self.route_calls = 0
        self.clicks = []

    def _enter_cj_vehicle_menu(self):
        self.route_calls += 1
        return True

    def _wait_for_uandt_ready(self, **_kwargs):
        return (150, 540)

    def wait_for_any_image_gray(self, *_args, **_kwargs):
        return (130, 760)

    def game_click(self, position, **_kwargs):
        self.clicks.append(position)

    def _save_upgrade_debug(self, *_args, **_kwargs):
        pass

    def log(self, *_args, **_kwargs):
        pass


class _DummyVehicleMenuRoute(CJMixin):
    def __init__(self):
        self.regions = {"全界面": (0, 0, 1600, 900), "左": (0, 0, 800, 900)}
        self.keys = []
        self.clicks = []
        self.vehicle_menu_timeout = None
        self.vehicle_menu_hard_timeout = None

    def enter_menu(self):
        return True

    def hw_press(self, key, **_kwargs):
        self.keys.append(key)

    def wait_for_buy_and_used_car(self, timeout=15):
        return (315, 514)

    def wait_for_any_image_gray(self, *_args, **_kwargs):
        return (311, 144)

    def _wait_for_cj_vehicle_menu(self, timeout=6.0, hard_timeout=None):
        self.vehicle_menu_timeout = timeout
        self.vehicle_menu_hard_timeout = hard_timeout
        return (132, 562)

    def game_click(self, position, **_kwargs):
        self.clicks.append(position)

    def log(self, *_args, **_kwargs):
        pass


class _DummyVehicleMenuWait(CJMixin):
    def __init__(self, clock, dark_until):
        self.clock = clock
        self.dark_until = dark_until
        self.is_running = True
        self.regions = {"全界面": (0, 0, 1600, 900)}

    def capture_region(self, _region):
        brightness = 0 if self.clock.now < self.dark_until else 100
        return np.full((20, 20, 3), brightness, dtype=np.uint8)

    def find_any_image_gray(self, *_args, **_kwargs):
        return (132, 562) if self.clock.now >= self.dark_until else None

    def log(self, *_args, **_kwargs):
        pass


class _DummyVehicleMenuRetry(_DummyVehicleMenuRoute):
    def __init__(self):
        super().__init__()
        self.vehicle_menu_results = [None, (132, 562)]

    def _wait_for_cj_vehicle_menu(self, timeout=6.0, hard_timeout=None):
        self.vehicle_menu_timeout = timeout
        self.vehicle_menu_hard_timeout = hard_timeout
        return self.vehicle_menu_results.pop(0)

    def find_any_image_gray(self, *_args, **_kwargs):
        return (311, 144)


class _DummyMasteryLeave(CJMixin):
    def __init__(self, menu_results):
        self.menu_results = list(menu_results)
        self.keys = []
        self.messages = []

    def hw_press(self, key, **_kwargs):
        self.keys.append(key)

    def _wait_for_cj_vehicle_menu(self, **_kwargs):
        return self.menu_results.pop(0)

    def log(self, message, level=None):
        self.messages.append((level, message))


class _DummyLockedPopupDismiss(CJMixin):
    def __init__(self):
        self.keys = []

    def hw_press(self, key, **kwargs):
        self.keys.append((key, kwargs))

    def _wait_for_mastery_popup_closed(self, timeout=2.5, interval=0.15):
        return True

    def _save_upgrade_debug(self, *_args, **_kwargs):
        pass

    def log(self, *_args, **_kwargs):
        pass


class MasteryCompletionTests(unittest.TestCase):
    def test_final_node_gray_is_not_complete(self):
        image = np.full((900, 1600, 3), 48, dtype=np.uint8)

        ratio = CJMixin._mastery_final_node_pink_ratio(image)

        self.assertEqual(0.0, ratio)

    def test_final_node_pink_is_complete_at_multiple_16_by_9_resolutions(self):
        for width, height in ((1600, 900), (2560, 1440)):
            image = np.full((height, width, 3), 48, dtype=np.uint8)
            x1r, y1r, x2r, y2r = CJMixin._MASTERY_FINAL_NODE_ROI
            image[
                int(height * y1r):int(height * y2r),
                int(width * x1r):int(width * x2r),
            ] = (180, 0, 255)

            ratio = CJMixin._mastery_final_node_pink_ratio(image)

            self.assertGreater(ratio, CJMixin._MASTERY_COMPLETE_MIN_PINK_RATIO)

    def test_center_lime_popup_is_detected_without_background_dependency(self):
        image = np.full((900, 1600, 3), 48, dtype=np.uint8)
        x1r, y1r, x2r, y2r = CJMixin._MASTERY_POPUP_HEADER_ROI
        image[
            int(900 * y1r):int(900 * y2r),
            int(1600 * x1r):int(1600 * x2r),
        ] = (0, 255, 190)

        ratio = CJMixin._mastery_popup_lime_ratio(image)

        self.assertGreater(ratio, CJMixin._MASTERY_POPUP_MIN_LIME_RATIO)

    def test_recovery_retries_current_vehicle_and_counts_completed_attempt_once(self):
        bot = _DummyMasteryState()
        bot._begin_cj_mastery()
        bot._cj_mastery_attempted = True

        success, stop_task = bot.retry_current_vehicle_mastery_after_recovery(5)

        self.assertTrue(success)
        self.assertFalse(stop_task)
        self.assertTrue(bot.opened_from_recovery)
        self.assertTrue(bot.left_mastery)
        self.assertEqual(1, bot.cj_counter)
        self.assertFalse(bot._cj_mastery_in_progress)
        self.assertTrue(bot._cj_resume_vehicle_menu)

    def test_recovery_does_not_count_vehicle_that_was_already_complete(self):
        bot = _DummyMasteryState()
        bot._begin_cj_mastery()

        success, stop_task = bot.retry_current_vehicle_mastery_after_recovery(5)

        self.assertTrue(success)
        self.assertFalse(stop_task)
        self.assertEqual(0, bot.cj_counter)
        self.assertFalse(bot._cj_mastery_in_progress)

    @patch("cj_logic.time.sleep", return_value=None)
    def test_mastery_path_homes_cursor_before_buying(self, _sleep):
        bot = _DummyMasteryPath()

        result = bot._send_mastery_path_once()

        keys = [key for key, _kwargs in bot.pressed]
        self.assertEqual("sent", result)
        self.assertEqual(["down"] * 6 + ["left"] * 6, keys[:12])
        self.assertEqual(["enter", "up", "enter", "right", "enter"], keys[12:])
        self.assertTrue(all(kwargs.get("use_send") for _key, kwargs in bot.pressed))

    def test_locked_popup_result_replays_full_path_locally(self):
        bot = _DummyLocalMasteryRetry()
        bot._begin_cj_mastery()

        success, stop_task = bot._run_current_vehicle_mastery(5)

        self.assertTrue(success)
        self.assertFalse(stop_task)
        self.assertEqual(2, bot.path_calls)
        self.assertEqual(1, bot.cj_counter)
        self.assertFalse(bot._cj_mastery_in_progress)

    def test_black_loading_does_not_consume_uandt_interaction_timeout(self):
        clock = _FakeClock()
        bot = _DummyUandTWait(clock)

        with patch("cj_logic.time.time", side_effect=clock.time), patch(
            "cj_logic.time.sleep", side_effect=clock.sleep
        ):
            position = bot._wait_for_uandt_ready(
                timeout=5.0,
                stable_frames=2,
                min_brightness=42.0,
                press_esc_when_missing=True,
            )

        self.assertEqual((120, 560), position)
        self.assertGreater(clock.now, 8.0)
        self.assertTrue(bot.escaped)

    @patch("cj_logic.time.sleep", return_value=None)
    def test_recovery_uses_full_route_to_vehicle_menu_before_mastery(self, _sleep):
        bot = _DummyRecoveryRoute()

        opened = bot._open_current_vehicle_mastery(from_recovery=True)

        self.assertTrue(opened)
        self.assertEqual(1, bot.route_calls)
        self.assertEqual([(150, 540), (130, 760)], bot.clicks)

    @patch("cj_logic.time.sleep", return_value=None)
    def test_vehicle_menu_route_matches_normal_navigation_sequence(self, _sleep):
        bot = _DummyVehicleMenuRoute()

        entered = bot._enter_cj_vehicle_menu()

        self.assertTrue(entered)
        self.assertEqual(["pagedown", "enter", "pagedown"], bot.keys)
        self.assertEqual([(315, 514), (311, 144)], bot.clicks)
        self.assertEqual(20.0, bot.vehicle_menu_timeout)
        self.assertEqual(60.0, bot.vehicle_menu_hard_timeout)

    def test_black_loading_does_not_consume_vehicle_menu_timeout(self):
        clock = _FakeClock()
        bot = _DummyVehicleMenuWait(clock, dark_until=12.0)

        with patch("cj_logic.time.time", side_effect=clock.time), patch(
            "cj_logic.time.sleep", side_effect=clock.sleep
        ):
            position = bot._wait_for_cj_vehicle_menu(timeout=5.0, hard_timeout=30.0)

        self.assertEqual((132, 562), position)
        self.assertGreaterEqual(clock.now, 12.0)

    @patch("cj_logic.time.sleep", return_value=None)
    def test_vehicle_menu_route_retries_pagedown_when_source_page_remains(self, _sleep):
        bot = _DummyVehicleMenuRetry()

        entered = bot._enter_cj_vehicle_menu()

        self.assertTrue(entered)
        self.assertEqual(["pagedown", "enter", "pagedown", "pagedown"], bot.keys)
        self.assertEqual([], bot.vehicle_menu_results)

    @patch("cj_logic.time.sleep", return_value=None)
    def test_leaving_mastery_retries_escape_until_vehicle_menu_is_visible(self, _sleep):
        bot = _DummyMasteryLeave([None, (132, 562)])

        left = bot._leave_current_vehicle_mastery()

        self.assertTrue(left)
        self.assertEqual(["esc", "esc", "esc", "up"], bot.keys)
        self.assertEqual([], bot.menu_results)

    def test_locked_popup_is_closed_with_synchronous_enter(self):
        bot = _DummyLockedPopupDismiss()

        dismissed = bot._dismiss_locked_mastery_popup(2, "无法使用额外加成")

        self.assertTrue(dismissed)
        self.assertEqual("enter", bot.keys[0][0])
        self.assertTrue(bot.keys[0][1]["use_send"])


class RecognitionOrderingTests(unittest.TestCase):
    def test_yolo_empty_streak_is_scoped_to_one_page_wait(self):
        clock = _FakeClock()
        vision = object.__new__(VisionMixin)
        vision.is_running = True
        vision.config = {}
        vision.regions = {"全界面": (0, 0, 1600, 900)}
        vision._yolo_empty_streak = 28
        vision._yolo_empty_start = -180.0
        vision.calls = 0
        vision.log = lambda *_args, **_kwargs: None

        def find_no_target(region=None):
            vision.calls += 1
            if vision._yolo_empty_streak == 0:
                vision._yolo_empty_start = clock.time()
            vision._yolo_empty_streak += 1
            return None

        vision.find_new_consumable_car_strict = find_no_target
        with patch("vision.time.time", side_effect=clock.time), patch(
            "vision.time.sleep", side_effect=clock.sleep
        ):
            position = vision.wait_for_new_consumable_car_strict(timeout=3.0, interval=0.5)

        self.assertIsNone(position)
        self.assertGreaterEqual(vision.calls, 6)
        self.assertLess(clock.now, 15.0)

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
        # use_yolo=False：本测试验证模板匹配路径的排序行为；
        # 默认开启的 YOLO 分支会对合成截图推理返回空，与本测试目标无关。
        vision.config = {"class_image": "classS2829.png", "use_yolo": False}
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

# 注：原 SellFocusFallbackTests 已于 2026-08-04 删除——其守护的
# _try_open_focused_remove_menu 兜底逻辑在 v1.2.11.3 (4a6bfd9) 已因
# "只验证 remove 按钮会误删非目标车辆" 被有意移除，测试成为孤儿。


if __name__ == "__main__":
    unittest.main()
