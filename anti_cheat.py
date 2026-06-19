import ctypes
import time
import threading
import cv2


class AntiCheatMixin:
    """反检测心跳检测：监控 PrintWindow 截图健康与输入有效性"""

    def _init_anti_cheat_state(self):
        self._anti_cheat_running = False
        self._heartbeat_thread = None
        self._last_screenshot_mean = None
        self._consecutive_black_screens = 0
        self._input_failure_count = 0

    def start_anti_cheat_heartbeat(self):
        """启动后台心跳线程，定期检测环境健康"""
        if self._anti_cheat_running:
            return
        self._anti_cheat_running = True
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()
        self.log("🛡️ 反检测心跳已启动")

    def stop_anti_cheat_heartbeat(self):
        self._anti_cheat_running = False
        self.log("🛡️ 反检测心跳已停止")

    def _heartbeat_loop(self):
        """每 10 秒执行一次检测"""
        while self._anti_cheat_running and getattr(self, "is_running", False):
            time.sleep(10)
            if not getattr(self, "is_running", False):
                continue
            try:
                self._check_print_window_health()
            except Exception:
                pass

    def _check_print_window_health(self):
        """检测 PrintWindow 是否还能正常截图"""
        if not self.game_hwnd or not ctypes.windll.user32.IsWindow(self.game_hwnd):
            return
        screen = self.capture_region(self.regions.get("全界面"))
        if screen is None:
            self._consecutive_black_screens += 1
            self.log(f"⚠️ PrintWindow 返回空 ({self._consecutive_black_screens}/3)")
        else:
            mean_val = screen.mean()
            if mean_val < 3.0:
                self._consecutive_black_screens += 1
                self.log(f"⚠️ 截图几乎全黑，均值={mean_val:.2f} ({self._consecutive_black_screens}/3)")
            else:
                if self._consecutive_black_screens > 0:
                    self.log(f"✅ PrintWindow 恢复正常，均值={mean_val:.2f}")
                self._consecutive_black_screens = 0

        if self._consecutive_black_screens >= 3:
            self.log("🚨 连续 3 次截图异常！可能原因：窗口最小化 / 独占全屏 / 反作弊拦截 GDI")
            self._consecutive_black_screens = 0

    def verify_input_effective(self, expected_change_region=None, timeout=3.0):
        """
        在"已知安全状态"下验证输入是否生效：
        发送一个输入前后各截一次图，对比差异。
        若差异极小，说明 PostMessage 可能已被过滤。
        """
        if not self.is_running:
            return True
        try:
            region = expected_change_region or self.regions.get("全界面")
            before = self.capture_region(region)
            if before is None:
                return True

            self.hw_press("down", delay=0.1)
            time.sleep(0.3)
            self.hw_press("up", delay=0.1)
            time.sleep(0.3)

            after = self.capture_region(region)
            if after is None:
                return True

            diff = cv2.absdiff(before, after)
            non_zero = cv2.countNonZero(cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY))
            total_pixels = before.shape[0] * before.shape[1]
            change_ratio = non_zero / total_pixels if total_pixels > 0 else 0

            if change_ratio < 0.001:
                self._input_failure_count += 1
                self.log(f"⚠️ 输入可能未生效，画面变化率={change_ratio:.4f} ({self._input_failure_count}/3)")
            else:
                if self._input_failure_count > 0:
                    self.log(f"✅ 输入检测恢复正常，变化率={change_ratio:.4f}")
                self._input_failure_count = 0

            if self._input_failure_count >= 3:
                self.log("🚨 连续 3 次检测到输入无效！PostMessage 可能被反作弊过滤，建议人工检查")
                self._input_failure_count = 0
                return False
            return True
        except Exception:
            return True
