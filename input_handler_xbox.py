import time
import ctypes
import pydirectinput
from constants import DIK_CODES, SendInput, Input, Input_I, KeyBdInput

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
SW_SHOW = 5
SW_RESTORE = 9


class InputMixin:
    """键盘鼠标输入封装（硬件级 + 后台 PostMessage）"""

    def _send_input_scan_key(self, key, down=True):
        key = key.lower()
        if key not in DIK_CODES:
            return False

        scan_code, extended = DIK_CODES[key]
        if extended and scan_code >= 0x80:
            scan_code &= 0x7F

        flags = KEYEVENTF_SCANCODE
        if extended:
            flags |= KEYEVENTF_EXTENDEDKEY
        if not down:
            flags |= KEYEVENTF_KEYUP

        extra = ctypes.c_ulong(0)
        ii_ = Input_I()
        ii_.ki = KeyBdInput(0, scan_code, flags, 0, ctypes.pointer(extra))
        x = Input(ctypes.c_ulong(1), ii_)
        return SendInput(1, ctypes.pointer(x), ctypes.sizeof(x)) == 1

    def _set_foreground_window_force(self, hwnd, timeout=2.0):
        if not hwnd or not ctypes.windll.user32.IsWindow(hwnd):
            return False

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        else:
            user32.ShowWindow(hwnd, SW_SHOW)

        current_thread = kernel32.GetCurrentThreadId()
        foreground = user32.GetForegroundWindow()

        pid = ctypes.c_ulong(0)
        target_thread = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        foreground_thread = 0
        if foreground:
            fg_pid = ctypes.c_ulong(0)
            foreground_thread = user32.GetWindowThreadProcessId(foreground, ctypes.byref(fg_pid))

        attached = []
        for tid in {target_thread, foreground_thread}:
            if tid and tid != current_thread:
                if user32.AttachThreadInput(current_thread, tid, True):
                    attached.append(tid)

        try:
            try:
                user32.AllowSetForegroundWindow(-1)
            except Exception:
                pass
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
            user32.SetFocus(hwnd)
        finally:
            for tid in attached:
                user32.AttachThreadInput(current_thread, tid, False)

        deadline = time.time() + timeout
        while time.time() < deadline:
            if user32.GetForegroundWindow() == hwnd:
                return True
            time.sleep(0.05)
        return user32.GetForegroundWindow() == hwnd

    def focus_game_for_foreground_input(self, timeout=2.0):
        hwnd = getattr(self, "game_hwnd", None)
        if not hwnd:
            self.log("无法前台输入: 尚未记录游戏窗口句柄。")
            return False

        if self.bg_input:
            self.bg_input.release_all()

        ok = self._set_foreground_window_force(hwnd, timeout=timeout)
        if not ok:
            self.log("无法将游戏窗口切到前台，已取消分享码真实输入。")
        return ok

    def foreground_press(self, key, delay=0.08):
        self.check_pause()
        if not self.is_running:
            return False
        if not self._send_input_scan_key(key, down=True):
            return False
        time.sleep(delay)
        self._send_input_scan_key(key, down=False)
        time.sleep(0.02)
        return True

    def foreground_hotkey(self, keys, delay=0.05):
        self.check_pause()
        if not self.is_running:
            return False

        pressed = []
        for key in keys:
            if not self._send_input_scan_key(key, down=True):
                break
            pressed.append(key)
            time.sleep(0.02)

        time.sleep(delay)
        for key in reversed(pressed):
            self._send_input_scan_key(key, down=False)
            time.sleep(0.02)

        return len(pressed) == len(keys)

    def foreground_type_text(self, text, delay=0.05):
        for char in str(text):
            if not self.is_running:
                return False
            key = char.lower()
            if key not in DIK_CODES:
                continue
            if not self.foreground_press(key, delay=delay):
                return False
            time.sleep(delay)
        return True

    def hw_key_down(self, key):
        # 【后台化】通过 PostMessage 发送按键
        if self.bg_input:
            self.bg_input.key_down(key)
        else:
            # 兜底：原硬件级输入
            self._send_input_scan_key(key, down=True)

    def hw_key_up(self, key):
        # 【后台化】通过 PostMessage 发送按键
        if self.bg_input:
            self.bg_input.key_up(key)
        else:
            # 兜底：原硬件级输入
            self._send_input_scan_key(key, down=False)

    def hw_press(self, key, delay=0.08, use_send=False):
        self.check_pause()
        if not self.is_running:
            return
        if self.bg_input:
            self.bg_input.press(key, delay=delay, use_send=use_send)
        else:
            self.hw_key_down(key)
            time.sleep(delay)
            self.hw_key_up(key)

    def hw_mouse_move(self, x, y):
        # 【后台化】不再移动物理鼠标，PostMessage 点击直接指定客户区坐标
        # 保留空函数以兼容旧代码调用
        pass

    def game_click(self, pos, double=False, confirm_key=None, move_away=False, clicks=None, hold=0.08, gap=0.08, use_send=False):
        """
        在指定坐标点击。
        confirm_key: 点击后额外发送的确认键（如 "enter"），用于游戏内需确认的按钮
        move_away: 点击后把游戏内鼠标悬停点移到左上角，防止 hover 提示遮挡识图。默认关闭，避免菜单/品牌选择被移开悬停点打断。
        clicks/hold/gap: 后台点击次数、按住时长、间隔。用于车卡“闪一下但没选中”的场景。
        use_send: 后台鼠标使用 SendMessage 同步发送，作为 PostMessage 点击不完全生效时的加强模式。
        """
        self.check_pause()
        if not self.is_running or not pos:
            return
        x, y = int(pos[0]), int(pos[1])

        if self.game_hwnd and self.bg_input:
            try:
                gx, gy, gw, gh = self.regions["全界面"]
                rel_x = x - gx
                rel_y = y - gy
                mode = "SendMessage" if use_send else "PostMessage"
                click_count = clicks if clicks is not None else (2 if double else 1)
                self.log(f"🖱️ 后台点击[{mode}] ({rel_x:.0f},{rel_y:.0f}) clicks={click_count} hold={hold:.2f} gap={gap:.2f} 确认键={confirm_key}")
                if confirm_key:
                    self.bg_input.click_with_confirm(rel_x, rel_y, confirm_key=confirm_key, double=double)
                else:
                    self.bg_input.click(rel_x, rel_y, double=double, use_send=use_send, clicks=clicks, hold=hold, gap=gap)
                if move_away:
                    # 等价恢复 AxeroYF/FH6 原版：点击后把鼠标悬停点移到左上角安全位置，避免 hover 提示遮挡后续识图。
                    # 但菜单/品牌选择不能默认移开，否则后台点击可能无法稳定提交选择。
                    self.bg_input.mouse_move(5, 5)
                    time.sleep(0.2)
                return
            except Exception as e:
                self.log(f"❌ 后台点击失败: {e}")

        # 兜底：原硬件级点击方式
        self.log(f"🖱️ 兜底硬件点击 ({x},{y})")
        self.hw_mouse_move(x, y)
        time.sleep(0.2)
        for _ in range(2 if double else 1):
            pydirectinput.mouseDown()
            time.sleep(0.1)
            pydirectinput.mouseUp()
            time.sleep(0.1)
        time.sleep(0.1)
        if confirm_key:
            self.hw_press(confirm_key, delay=0.1)

    def move_to_game_coord(self, x, y):
        """
        【后台化】不再需要移动物理鼠标，此操作在后台模式下无意义
        保留函数以兼容旧代码调用
        """
        pass
