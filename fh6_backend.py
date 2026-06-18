# -*- coding: utf-8 -*-
"""
FH6_Auto 后台化补丁模块
提供 PrintWindow 后台截图 + PostMessage 后台输入

修复记录:
- 2026-06-18: 硬编码 scan code + extended flag，修复方向键卡死
- 2026-06-18: 修正 lParam (repeat count, prev state, trans state)
- 2026-06-18: _repeat_loop 递增 repeat count，key_up 清除计数
"""

import ctypes
import time
import threading
import numpy as np
import win32gui
import win32ui
import win32con
import win32api

PW_RENDERFULLCONTENT = 3

# VK 码映射
VK_MAP = {
    "esc": 0x1B, "enter": 0x0D, "space": 0x20, "backspace": 0x08, "tab": 0x09,
    "lshift": 0xA0, "rshift": 0xA1, "lctrl": 0xA2, "rctrl": 0xA3,
    "lalt": 0xA4, "ralt": 0xA5, "capslock": 0x14,
    "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45, "f": 0x46,
    "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A, "k": 0x4B, "l": 0x4C,
    "m": 0x4D, "n": 0x4E, "o": 0x4F, "p": 0x50, "q": 0x51, "r": 0x52,
    "s": 0x53, "t": 0x54, "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58,
    "y": 0x59, "z": 0x5A,
    "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34, "5": 0x35,
    "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39, "0": 0x30,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "pageup": 0x21, "pagedown": 0x22, "home": 0x24, "end": 0x23,
    "insert": 0x2D, "delete": 0x2E,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
    "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
    "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}

# 硬编码 scan code + extended flag（避免 MapVirtualKey 因键盘布局返回错误值）
# 格式: key -> (scan_code, is_extended)
SCAN_MAP = {
    "esc": (0x01, False), "enter": (0x1C, False), "space": (0x39, False),
    "backspace": (0x0E, False), "tab": (0x0F, False),
    "lshift": (0x2A, False), "rshift": (0x36, False),
    "lctrl": (0x1D, False), "rctrl": (0x1D, True),
    "lalt": (0x38, False), "ralt": (0x38, True),
    "capslock": (0x3A, False),
    "a": (0x1E, False), "b": (0x30, False), "c": (0x2E, False),
    "d": (0x20, False), "e": (0x12, False), "f": (0x21, False),
    "g": (0x22, False), "h": (0x23, False), "i": (0x17, False),
    "j": (0x24, False), "k": (0x25, False), "l": (0x26, False),
    "m": (0x32, False), "n": (0x31, False), "o": (0x18, False),
    "p": (0x19, False), "q": (0x10, False), "r": (0x13, False),
    "s": (0x1F, False), "t": (0x14, False), "u": (0x16, False),
    "v": (0x2F, False), "w": (0x11, False), "x": (0x2D, False),
    "y": (0x15, False), "z": (0x2C, False),
    "1": (0x02, False), "2": (0x03, False), "3": (0x04, False),
    "4": (0x05, False), "5": (0x06, False), "6": (0x07, False),
    "7": (0x08, False), "8": (0x09, False), "9": (0x0A, False),
    "0": (0x0B, False),
    "up": (0x48, True), "down": (0x50, True),
    "left": (0x4B, True), "right": (0x4D, True),
    "pageup": (0x49, True), "pagedown": (0x51, True),
    "home": (0x47, True), "end": (0x4F, True),
    "insert": (0x52, True), "delete": (0x53, True),
    "f1": (0x3B, False), "f2": (0x3C, False), "f3": (0x3D, False), "f4": (0x3E, False),
    "f5": (0x3F, False), "f6": (0x40, False), "f7": (0x41, False), "f8": (0x42, False),
    "f9": (0x43, False), "f10": (0x44, False), "f11": (0x57, False), "f12": (0x58, False),
}


def _build_lparam(scan, extended, repeat, prev_state, trans_state):
    """构造 WM_KEYDOWN/WM_KEYUP 的 lParam"""
    lp = repeat & 0xFFFF
    lp |= (scan & 0xFF) << 16
    if extended:
        lp |= 1 << 24
    if prev_state:
        lp |= 1 << 30
    if trans_state:
        lp |= 1 << 31
    return lp


class BackgroundInputManager:
    """后台输入管理器：用 PostMessage 发送键盘/鼠标事件"""

    def __init__(self, hwnd):
        self.hwnd = hwnd
        self._pressed_keys = set()
        self._repeat_counts = {}
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._repeat_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        for key in list(self._pressed_keys):
            self.key_up(key)

    def key_down(self, key):
        """按住按键（加入重复循环）"""
        self._pressed_keys.add(key.lower())
        self._send_key(key, down=True, is_repeat=False)

    def key_up(self, key):
        """释放按键"""
        self._pressed_keys.discard(key.lower())
        self._repeat_counts.pop(key.lower(), None)
        self._send_key(key, down=False)

    def press(self, key, delay=0.08):
        """单击按键（KEYDOWN + 可选 WM_CHAR + KEYUP）"""
        self._send_key(key, down=True, is_repeat=False, send_char=True)
        time.sleep(delay)
        self._send_key(key, down=False)
        time.sleep(0.02)

    def click(self, x, y, double=False, use_send=False):
        """在窗口客户区坐标 (x, y) 点击
        use_send=True 时用 SendMessage（同步，更可靠但可能阻塞）
        """
        lp = win32api.MAKELONG(int(x), int(y))
        sender = win32gui.SendMessage if use_send else win32gui.PostMessage

        sender(self.hwnd, win32con.WM_MOUSEMOVE, 0, lp)
        time.sleep(0.05)
        for _ in range(2 if double else 1):
            sender(self.hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lp)
            time.sleep(0.08)
            sender(self.hwnd, win32con.WM_LBUTTONUP, win32con.MK_LBUTTON, lp)
            time.sleep(0.08)

    def click_with_confirm(self, x, y, confirm_key="enter", double=False):
        """点击 + 发送确认键（用于游戏内需要 Enter/Space 确认的按钮）"""
        self.click(x, y, double=double, use_send=False)
        time.sleep(0.15)
        self.press(confirm_key, delay=0.1)
        time.sleep(0.15)

    def _send_key(self, key, down=True, is_repeat=False, send_char=False):
        key = key.lower()
        vk = VK_MAP.get(key)
        if vk is None:
            return

        scan, extended = SCAN_MAP.get(key, (0, False))

        if down:
            if is_repeat:
                # 重复 KEYDOWN: prev_state=1, trans=0
                self._repeat_counts[key] = self._repeat_counts.get(key, 0) + 1
                count = min(self._repeat_counts[key], 0xFFFF)
                lParam = _build_lparam(scan, extended, count, prev_state=1, trans_state=0)
            else:
                # 首次 KEYDOWN: prev_state=0, trans=0, repeat=1
                lParam = _build_lparam(scan, extended, 1, prev_state=0, trans_state=0)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, vk, lParam)
            # 数字/字母发 WM_CHAR（文本输入框需要）
            if send_char and (0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A):
                win32gui.PostMessage(self.hwnd, win32con.WM_CHAR, vk, lParam)
        else:
            # KEYUP: prev_state=1, trans=1, repeat=1
            lParam = _build_lparam(scan, extended, 1, prev_state=1, trans_state=1)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, vk, lParam)

    def _repeat_loop(self):
        """每 50ms 给所有按住的键重发 KEYDOWN"""
        while self._running:
            for key in list(self._pressed_keys):
                self._send_key(key, down=True, is_repeat=True)
            time.sleep(0.05)


def capture_window(hwnd, region=None, window_offset=(0, 0)):
    """后台截图窗口客户区（PrintWindow flag=3）"""
    left, top, right, bot = win32gui.GetClientRect(hwnd)
    w, h = right - left, bot - top
    if w <= 0 or h <= 0:
        return None

    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc_dc, w, h)
    save_dc.SelectObject(bmp)

    ok = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)

    if ok != 1:
        win32gui.DeleteObject(bmp.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)
        return None

    bmp_bits = bmp.GetBitmapBits(True)
    arr = np.frombuffer(bmp_bits, dtype=np.uint8).reshape((h, w, 4))
    screen_bgr = arr[:, :, :3].copy()

    win32gui.DeleteObject(bmp.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)

    if region:
        rx, ry, rw, rh = region
        wx, wy = window_offset
        rel_x = max(0, min(rx - wx, w))
        rel_y = max(0, min(ry - wy, h))
        rel_x2 = min(rel_x + rw, w)
        rel_y2 = min(rel_y + rh, h)
        if rel_x2 > rel_x and rel_y2 > rel_y:
            screen_bgr = screen_bgr[rel_y:rel_y2, rel_x:rel_x2]

    return screen_bgr
