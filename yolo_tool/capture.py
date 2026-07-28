"""游戏窗口后台截图"""

import cv2
import numpy as np
import win32gui
import win32ui
import win32con
import ctypes

PW_RENDERFULLCONTENT = 3
_dpi_set = False


def _ensure_dpi_aware():
    """延迟设置 DPI 感知：首次截图前调用，避免影响 tkinter 字体缩放"""
    global _dpi_set
    if _dpi_set:
        return
    _dpi_set = True
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class GameCapture:
    def __init__(self):
        self.hwnd = None
        self._cache_dc = None
        self._cache_bmp = None
        self._cache_w = 0
        self._cache_h = 0

    @staticmethod
    def enable_dpi():
        """显式启用 DPI 感知 — GUI 初始化完成后调用"""
        _ensure_dpi_aware()

    def find_game_window(self):
        """查找 Forza Horizon 6 窗口句柄（按进程名 forzahorizon6.exe 匹配）"""
        # 不在这里启用 DPI — 留给 GUI 初始化后调用 enable_dpi()
        result = []

        def callback(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            # 精确匹配 Forza Horizon 6
            if "Forza Horizon 6" in title:
                result.append(hwnd)
            return True

        win32gui.EnumWindows(callback, None)
        if not result:
            # 兜底：按进程名查找
            import subprocess
            try:
                out = subprocess.check_output(
                    'tasklist /FI "IMAGENAME eq forzahorizon6.exe" /NH /FO CSV',
                    shell=True, text=True, stderr=subprocess.DEVNULL
                )
                if "forzahorizon6.exe" in out.lower():
                    # 找到了进程但没找到窗口，可能最小化了
                    pass
            except Exception:
                pass
        self.hwnd = result[0] if result else None
        return self.hwnd

    def get_window_rect(self):
        """获取窗口客户区在屏幕上的位置和大小"""
        if not self.hwnd or not win32gui.IsWindow(self.hwnd):
            return None
        try:
            left, top, right, bot = win32gui.GetClientRect(self.hwnd)
            w, h = right - left, bot - top
            if w <= 0 or h <= 0:
                return None
            pt = win32gui.ClientToScreen(self.hwnd, (0, 0))
            return (pt[0], pt[1], w, h)
        except Exception:
            return None

    def capture(self):
        """后台截图，返回 BGR numpy 数组，失败返回 None"""
        if not self.hwnd or not win32gui.IsWindow(self.hwnd):
            return None
        try:
            left, top, right, bot = win32gui.GetClientRect(self.hwnd)
            w, h = right - left, bot - top
            if w <= 0 or h <= 0:
                return None
            return self._print_window(w, h)
        except Exception:
            self._release_cache()
            return None

    def _print_window(self, w, h):
        """PrintWindow 后台截图，带 GDI 缓存"""
        try:
            hwnd_dc = win32gui.GetWindowDC(self.hwnd)
            if self._cache_dc and self._cache_w == w and self._cache_h == h:
                mfc_dc = self._cache_dc
                save_dc = mfc_dc.CreateCompatibleDC()
                save_dc.SelectObject(self._cache_bmp)
            else:
                self._release_cache()
                mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
                save_dc = mfc_dc.CreateCompatibleDC()
                bmp = win32ui.CreateBitmap()
                bmp.CreateCompatibleBitmap(mfc_dc, w, h)
                save_dc.SelectObject(bmp)
                self._cache_dc = mfc_dc
                self._cache_bmp = bmp
                self._cache_w = w
                self._cache_h = h

            import ctypes
            ok = ctypes.windll.user32.PrintWindow(
                self.hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT
            )
            if not ok:
                # PrintWindow 失败，释放缓存重试
                win32gui.ReleaseDC(self.hwnd, hwnd_dc)
                save_dc.DeleteDC()
                self._release_cache()
                return self._retry_capture(w, h)

            bmp_info = self._cache_bmp.GetInfo()
            bmp_str = self._cache_bmp.GetBitmapBits(True)
            img = np.frombuffer(bmp_str, dtype=np.uint8).reshape(h, w, 4)
            img_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

            win32gui.ReleaseDC(self.hwnd, hwnd_dc)
            save_dc.DeleteDC()
            return img_bgr
        except Exception:
            self._release_cache()
            return None

    def _retry_capture(self, w, h):
        """缓存失败后全新对象重试"""
        try:
            hwnd_dc = win32gui.GetWindowDC(self.hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()
            bmp = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(mfc_dc, w, h)
            save_dc.SelectObject(bmp)

            import ctypes
            ok = ctypes.windll.user32.PrintWindow(
                self.hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT
            )
            if not ok:
                win32gui.ReleaseDC(self.hwnd, hwnd_dc)
                save_dc.DeleteDC()
                mfc_dc.DeleteDC()
                return None

            bmp_info = bmp.GetInfo()
            bmp_str = bmp.GetBitmapBits(True)
            img = np.frombuffer(bmp_str, dtype=np.uint8).reshape(h, w, 4)
            img_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

            # 重建缓存
            self._cache_dc = mfc_dc
            self._cache_bmp = bmp
            self._cache_w = w
            self._cache_h = h

            win32gui.ReleaseDC(self.hwnd, hwnd_dc)
            save_dc.DeleteDC()
            return img_bgr
        except Exception:
            self._release_cache()
            return None

    def _release_cache(self):
        """释放 GDI 缓存"""
        try:
            if self._cache_bmp:
                win32gui.DeleteObject(self._cache_bmp.GetHandle())
        except Exception:
            pass
        try:
            if self._cache_dc:
                self._cache_dc.DeleteDC()
        except Exception:
            pass
        self._cache_dc = None
        self._cache_bmp = None
        self._cache_w = 0
        self._cache_h = 0

    def release(self):
        self._release_cache()
