# -*- coding: utf-8 -*-
"""
FH6_Auto 后台化补丁模块
提供 PrintWindow 后台截图 + PostMessage 后台输入
"""

import ctypes
import time
import threading
import numpy as np
import win32gui
import win32ui
import win32con
import win32api

PW_RENDERFULLCONTENT = 3  # PrintWindow flag, Win10 1903+ 截 D3D/UE 窗口必需

# VK 码映射（用于 PostMessage WM_KEYDOWN/WM_KEYUP）
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


class BackgroundInputManager:
    """后台输入管理器：用 PostMessage 发送键盘/鼠标事件，不移动物理光标"""

    def __init__(self, hwnd):
        self.hwnd = hwnd
        self._pressed_keys = set()
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
        """后台按下按键（加入持续按住集合）"""
        self._pressed_keys.add(key.lower())
        self._send_key(key, down=True)

    def key_up(self, key):
        """后台释放按键"""
        self._pressed_keys.discard(key.lower())
        self._send_key(key, down=False)

    def press(self, key, delay=0.08):
        """单击按键"""
        self._send_key(key, down=True)
        time.sleep(delay)
        self._send_key(key, down=False)
        time.sleep(0.02)  # 额外缓冲，防止游戏消息队列堆积

    def click(self, x, y, double=False):
        """
        在窗口客户区坐标 (x, y) 点击
        坐标是相对于窗口客户区左上角的（与游戏内坐标一致）
        """
        lp = win32api.MAKELONG(int(x), int(y))
        win32gui.PostMessage(self.hwnd, win32con.WM_MOUSEMOVE, 0, lp)
        time.sleep(0.02)
        for _ in range(2 if double else 1):
            win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lp)
            time.sleep(0.05)
            win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONUP, win32con.MK_LBUTTON, lp)
            time.sleep(0.05)

    def _send_key(self, key, down=True):
        vk = VK_MAP.get(key.lower())
        if vk is None:
            return
        scan = win32api.MapVirtualKey(vk, 0)  # VK -> scan code
        if down:
            # WM_KEYDOWN: repeat=1, scan, prev=0, trans=0
            lParam = (scan << 16) | 1
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, vk, lParam)
            # 文本输入需要 WM_CHAR（数字/字母直接发 ASCII）
            if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
                win32gui.PostMessage(self.hwnd, win32con.WM_CHAR, vk, lParam)
        else:
            # WM_KEYUP: repeat=1, scan, prev=1, trans=1
            lParam = (scan << 16) | (1 << 30) | (1 << 31) | 1
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, vk, lParam)

    def _repeat_loop(self):
        """每 50ms 给所有按住的键重发 KEYDOWN，模拟持续按住"""
        while self._running:
            for key in list(self._pressed_keys):
                self._send_key(key, down=True)
            time.sleep(0.05)


def capture_window(hwnd, region=None, window_offset=(0, 0)):
    """
    后台截图窗口客户区（PrintWindow flag=3）

    Args:
        hwnd: 目标窗口句柄
        region: (x, y, w, h) 屏幕绝对坐标区域，None 则截全客户区
        window_offset: (wx, wy) 窗口客户区左上角屏幕坐标

    Returns:
        numpy.ndarray: BGR 格式图像 (OpenCV 默认)，失败返回 None
    """
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
    screen_bgr = arr[:, :, :3].copy()  # BGRA -> BGR

    win32gui.DeleteObject(bmp.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)

    # 如果指定了 region，裁剪出对应区域
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
