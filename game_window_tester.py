# -*- coding: utf-8 -*-
"""
游戏窗口后台截图 & 输入测试工具
原理:PrintWindow(hwnd, dc, 3) 后台截图 + PostMessage 后台输入
支持:任意窗口选择、实时预览、按键/鼠标测试、DPI 感知、管理员权限检测
"""

import ctypes
import ctypes.wintypes
import sys
import os
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from collections import deque

# ─── DPI 感知(必须在创建任何窗口之前调用) ───
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-Monitor DPI Aware v2
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import win32gui
import win32ui
import win32con
import win32api
import numpy as np
from PIL import Image, ImageTk


# ─── 常量 ───
PW_RENDERFULLCONTENT = 3  # PrintWindow flag,Win10 1903+ 截 D3D/UE 窗口必需
WM_INPUT = 0x00FF
WM_MOUSEMOVE = 0x0200


def is_admin():
    """检测是否以管理员权限运行"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def elevate():
    """请求以管理员权限重新启动"""
    try:
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, " ".join(sys.argv), None, 1
        )
        if ret <= 32:
            messagebox.showerror("提权失败", "无法以管理员权限启动,请右键手动以管理员身份运行。")
        else:
            sys.exit(0)
    except Exception as e:
        messagebox.showerror("提权失败", str(e))


def enum_visible_windows():
    """枚举所有可见且有标题的窗口,返回 [(title, hwnd), ...]"""
    result = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title or not title.strip():
            return True
        # 过滤掉一些系统窗口
        cls = win32gui.GetClassName(hwnd)
        if cls in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman"):
            return True
        result.append((title, hwnd))
        return True

    win32gui.EnumWindows(callback, None)
    result.sort(key=lambda x: x[0].lower())
    return result


def print_window_screenshot(hwnd):
    """
    用 PrintWindow(hwnd, dc, 3) 后台截图
    返回 numpy.ndarray (H, W, 3) RGB,失败返回 None
    """
    try:
        left, top, right, bot = win32gui.GetClientRect(hwnd)
        w = right - left
        h = bot - top
        if w <= 0 or h <= 0:
            return None

        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bmp)

        # 核心:flag=3 截 D3D/硬件加速窗口
        ok = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)

        if ok == 1:
            bmp_bits = bmp.GetBitmapBits(True)
            arr = np.frombuffer(bmp_bits, dtype=np.uint8).reshape((h, w, 4))
            rgb = arr[:, :, [2, 1, 0]]  # BGRA -> RGB
        else:
            rgb = None

        win32gui.DeleteObject(bmp.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)
        return rgb
    except Exception as e:
        return None


def post_message_click(hwnd, x, y, dpi_scale=1.0):
    """
    后台发送鼠标左键点击,尝试多种方式。
    坐标需从逻辑像素转为物理像素。
    """
    px = int(x * dpi_scale)
    py = int(y * dpi_scale)
    lp = win32api.MAKELONG(px, py)

    # 方式1:PostMessage(异步,不阻塞)
    # 先发 WM_MOUSEMOVE,部分游戏需要鼠标移动事件才认后续点击
    win32gui.PostMessage(hwnd, WM_MOUSEMOVE, 0, lp)
    time.sleep(0.02)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lp)
    time.sleep(0.05)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, win32con.MK_LBUTTON, lp)

    return px, py


def send_message_click(hwnd, x, y, dpi_scale=1.0):
    """
    用 SendMessage(同步)发送鼠标点击。
    SendMessage 会等窗口处理完才返回,某些场景比 PostMessage 更可靠。
    """
    px = int(x * dpi_scale)
    py = int(y * dpi_scale)
    lp = win32api.MAKELONG(px, py)

    win32gui.SendMessage(hwnd, WM_MOUSEMOVE, 0, lp)
    time.sleep(0.02)
    win32gui.SendMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lp)
    time.sleep(0.05)
    win32gui.SendMessage(hwnd, win32con.WM_LBUTTONUP, win32con.MK_LBUTTON, lp)

    return px, py


def post_message_key(hwnd, vk_code):
    """后台发送键盘按键"""
    win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, vk_code, 0)
    time.sleep(0.05)
    win32gui.PostMessage(hwnd, win32con.WM_KEYUP, vk_code, 0)


# ─── 常用虚拟键码映射 ───
VK_MAP = {
    "W": 0x57, "A": 0x41, "S": 0x53, "D": 0x44,
    "E": 0x45, "Q": 0x51, "R": 0x52, "F": 0x46,
    "Space": 0x20, "Enter": 0x0D, "Esc": 0x1B,
    "Shift": 0x10, "Ctrl": 0x11, "Alt": 0x12,
    "Up": 0x26, "Down": 0x28, "Left": 0x25, "Right": 0x27,
    "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34, "5": 0x35,
    "Tab": 0x09,
}



class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("游戏窗口后台截图 & 输入测试器")
        self.root.geometry("960x780")
        self.root.minsize(800, 650)

        self.selected_hwnd = None
        self.selected_title = tk.StringVar(value="(未选择)")
        self.running = False  # 实时预览是否运行中
        self.preview_photo = None  # 保持引用防止 GC
        self.fps_var = tk.IntVar(value=5)
        self.log_lines = deque(maxlen=200)

        self._build_ui()
        self._log("工具已启动,请先选择目标窗口")
        if not is_admin():
            self._log("⚠ 未以管理员权限运行!若游戏以管理员启动,PostMessage 可能无效")

    def _build_ui(self):
        # ─── 顶部:窗口选择 ───
        frm_top = ttk.Frame(self.root, padding=8)
        frm_top.pack(fill=tk.X)

        ttk.Button(frm_top, text="🔄 刷新窗口列表", command=self._refresh_windows).pack(side=tk.LEFT)

        self.window_combo = ttk.Combobox(frm_top, state="readonly", width=60)
        self.window_combo.pack(side=tk.LEFT, padx=8, fill=tk.X, expand=True)
        self.window_combo.bind("<<ComboboxSelected>>", self._on_window_selected)

        self.lbl_status = ttk.Label(frm_top, text="状态: 未选择窗口")
        self.lbl_status.pack(side=tk.LEFT, padx=4)

        # ─── 截图预览区 ───
        frm_preview = ttk.LabelFrame(self.root, text="实时截图预览", padding=4)
        frm_preview.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self.canvas = tk.Canvas(frm_preview, bg="#1a1a2e", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # 截图画布点击事件(用于鼠标测试)
        self.canvas.bind("<Button-1>", self._on_canvas_click)

        # ─── 控制栏 ───
        frm_ctrl = ttk.Frame(self.root, padding=8)
        frm_ctrl.pack(fill=tk.X)

        self.btn_single = ttk.Button(frm_ctrl, text="📸 单次截图", command=self._single_screenshot)
        self.btn_single.pack(side=tk.LEFT, padx=4)

        self.btn_start = ttk.Button(frm_ctrl, text="▶ 实时预览", command=self._toggle_preview)
        self.btn_start.pack(side=tk.LEFT, padx=4)

        ttk.Label(frm_ctrl, text="FPS:").pack(side=tk.LEFT, padx=(16, 2))
        fps_spin = ttk.Spinbox(frm_ctrl, from_=1, to=30, textvariable=self.fps_var, width=4)
        fps_spin.pack(side=tk.LEFT)

        ttk.Separator(frm_ctrl, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        # ─── 按键测试 ───
        ttk.Label(frm_ctrl, text="按键:").pack(side=tk.LEFT)
        self.key_combo = ttk.Combobox(frm_ctrl, values=list(VK_MAP.keys()), state="readonly", width=8)
        self.key_combo.set("W")
        self.key_combo.pack(side=tk.LEFT, padx=4)
        ttk.Button(frm_ctrl, text="⌨ 发送", command=self._send_key).pack(side=tk.LEFT, padx=2)

        ttk.Separator(frm_ctrl, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        # ─── 鼠标测试 ───
        ttk.Label(frm_ctrl, text="鼠标 x:").pack(side=tk.LEFT)
        self.entry_x = ttk.Entry(frm_ctrl, width=5)
        self.entry_x.insert(0, "100")
        self.entry_x.pack(side=tk.LEFT, padx=2)
        ttk.Label(frm_ctrl, text="y:").pack(side=tk.LEFT)
        self.entry_y = ttk.Entry(frm_ctrl, width=5)
        self.entry_y.insert(0, "100")
        self.entry_y.pack(side=tk.LEFT, padx=2)

        # 点击方式选择
        self.click_method = tk.StringVar(value="PostMessage")
        ttk.Radiobutton(frm_ctrl, text="Post", variable=self.click_method, value="PostMessage").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Radiobutton(frm_ctrl, text="Send", variable=self.click_method, value="SendMessage").pack(side=tk.LEFT)
        ttk.Radiobutton(frm_ctrl, text="Both", variable=self.click_method, value="Both").pack(side=tk.LEFT)
        ttk.Button(frm_ctrl, text="🖱 发送", command=self._send_click).pack(side=tk.LEFT, padx=2)

        # ─── 日志区 ───
        frm_log = ttk.LabelFrame(self.root, text="日志", padding=4)
        frm_log.pack(fill=tk.X, padx=8, pady=(0, 8))

        self.log_text = scrolledtext.ScrolledText(frm_log, height=6, state=tk.DISABLED,
                                                   font=("Consolas", 9), bg="#0d1117", fg="#c9d1d9",
                                                   insertbackground="#c9d1d9", wrap=tk.WORD)
        self.log_text.pack(fill=tk.X)

        # 初始刷新窗口列表
        self._refresh_windows()

    def _log(self, msg):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self.log_lines.append(line)
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _refresh_windows(self):
        self.windows = enum_visible_windows()
        titles = [f"{title}" for title, _ in self.windows]
        self.window_combo["values"] = titles
        self._log(f"已刷新,发现 {len(self.windows)} 个可见窗口")

    def _on_window_selected(self, event=None):
        idx = self.window_combo.current()
        if idx < 0 or idx >= len(self.windows):
            return
        title, hwnd = self.windows[idx]
        self.selected_hwnd = hwnd
        self.selected_title.set(title)
        cls = win32gui.GetClassName(hwnd)
        dpi_scale = self._get_dpi_scale(hwnd)
        left, top, right, bot = win32gui.GetClientRect(hwnd)
        cw, ch = right - left, bot - top
        # 窗口屏幕位置（用于调试）
        wrect = win32gui.GetWindowRect(hwnd)
        self.lbl_status.config(text=f"hwnd=0x{hwnd:X} | {cw}x{ch} | DPI x{dpi_scale:.2f}")
        self._log(f"已选中: \"{title}\"")
        self._log(f"  hwnd=0x{hwnd:X}  class={cls}")
        self._log(f"  客户区={cw}x{ch}  窗口Rect={wrect}  DPI x{dpi_scale:.2f}")

    def _single_screenshot(self):
        if not self.selected_hwnd:
            messagebox.showwarning("提示", "请先选择目标窗口")
            return
        if not win32gui.IsWindow(self.selected_hwnd):
            self._log("❌ 目标窗口已不存在")
            return

        rgb = print_window_screenshot(self.selected_hwnd)
        if rgb is None:
            self._log("❌ PrintWindow 失败(返回 0),可能窗口最小化或不支持")
            self._show_black_warning()
            return

        mean_val = rgb.mean()
        self._log(f"✅ PrintWindow 成功 | 尺寸={rgb.shape[1]}x{rgb.shape[0]} | 均值={mean_val:.2f}")
        left, top, right, bot = win32gui.GetClientRect(self.selected_hwnd)
        self._log(f"   客户区 GetClientRect={right-left}x{bot-top} | 截图尺寸={rgb.shape[1]}x{rgb.shape[0]}")

        if mean_val < 5:
            self._log("⚠ 截图几乎全黑!可能原因: 独占全屏 / DRM保护 / 反作弊Hook GDI")
            self._show_black_warning()
        else:
            self._display_image(rgb)

    def _toggle_preview(self):
        if self.running:
            self.running = False
            self.btn_start.config(text="▶ 实时预览")
            self._log("实时预览已停止")
        else:
            if not self.selected_hwnd:
                messagebox.showwarning("提示", "请先选择目标窗口")
                return
            self.running = True
            self.btn_start.config(text="⏸ 停止预览")
            self._log("实时预览已启动")
            self._preview_loop()

    def _preview_loop(self):
        if not self.running:
            return
        if not self.selected_hwnd or not win32gui.IsWindow(self.selected_hwnd):
            self._log("❌ 目标窗口已关闭,停止预览")
            self.running = False
            self.btn_start.config(text="▶ 实时预览")
            return

        rgb = print_window_screenshot(self.selected_hwnd)
        if rgb is not None:
            mean_val = rgb.mean()
            if mean_val < 5:
                self._show_black_warning()
            else:
                self._display_image(rgb)

        fps = max(1, min(30, self.fps_var.get()))
        delay_ms = int(1000 / fps)
        self.root.after(delay_ms, self._preview_loop)

    def _display_image(self, rgb):
        """将 numpy RGB 数组显示到 canvas,等比缩放"""
        h, w = rgb.shape[:2]
        img = Image.fromarray(rgb)

        # 获取 canvas 尺寸
        self.root.update_idletasks()
        cw = max(self.canvas.winfo_width(), 100)
        ch = max(self.canvas.winfo_height(), 100)

        # 等比缩放
        scale = min(cw / w, ch / h)
        new_w = max(int(w * scale), 1)
        new_h = max(int(h * scale), 1)
        img = img.resize((new_w, new_h), Image.LANCZOS)

        self.preview_photo = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(cw // 2, ch // 2, image=self.preview_photo, anchor=tk.CENTER)

        # 存储缩放比例用于点击坐标换算
        self._scale = scale
        self._offset_x = (cw - new_w) // 2
        self._offset_y = (ch - new_h) // 2
        self._img_w = w
        self._img_h = h

    def _show_black_warning(self):
        self.canvas.delete("all")
        cw = max(self.canvas.winfo_width(), 100)
        ch = max(self.canvas.winfo_height(), 100)
        self.canvas.create_rectangle(0, 0, cw, ch, fill="#2d0a0a", outline="")
        self.canvas.create_text(
            cw // 2, ch // 2,
            text="⚠ 截图全黑\n\n可能原因:\n· 窗口已最小化\n· 独占全屏模式\n· DRM/反作弊Hook GDI\n· PrintWindow 返回失败",
            fill="#ff6b6b", font=("微软雅黑", 14), justify=tk.CENTER
        )

    def _get_dpi_scale(self, hwnd):
        """获取目标窗口的 DPI 缩放因子"""
        try:
            hdc = win32gui.GetDC(hwnd)
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
            win32gui.ReleaseDC(hwnd, hdc)
            return dpi / 96.0
        except Exception:
            return 1.0

    def _do_click(self, x, y):
        """根据选择的点击方式发送鼠标点击"""
        method = self.click_method.get()
        dpi_scale = self._get_dpi_scale(self.selected_hwnd)
        left, top, right, bot = win32gui.GetClientRect(self.selected_hwnd)
        cw, ch = right - left, bot - top

        self._log(f"🖱 点击 逻辑({x},{y}) | 客户区={cw}x{ch} | DPI x{dpi_scale:.2f} | 方式={method}")

        if method == "PostMessage":
            px, py = post_message_click(self.selected_hwnd, x, y, dpi_scale)
            self._log(f"  → PostMessage 物理({px},{py}) WM_MOUSEMOVE+LBUTTONDOWN/UP")
        elif method == "SendMessage":
            px, py = send_message_click(self.selected_hwnd, x, y, dpi_scale)
            self._log(f"  → SendMessage 物理({px},{py}) WM_MOUSEMOVE+LBUTTONDOWN/UP")
        else:  # Both
            px1, py1 = post_message_click(self.selected_hwnd, x, y, dpi_scale)
            self._log(f"  → PostMessage 物理({px1},{py1})")
            time.sleep(0.1)
            px2, py2 = send_message_click(self.selected_hwnd, x, y, dpi_scale)
            self._log(f"  → SendMessage 物理({px2},{py2})")

    def _on_canvas_click(self, event):
        """点击预览图 → 换算成窗口客户区坐标 → 发送后台点击"""
        if not self.selected_hwnd or not hasattr(self, "_scale"):
            return
        x = int((event.x - self._offset_x) / self._scale)
        y = int((event.y - self._offset_y) / self._scale)
        if x < 0 or y < 0 or x >= self._img_w or y >= self._img_h:
            return
        self._do_click(x, y)

    def _send_key(self):
        if not self.selected_hwnd:
            messagebox.showwarning("提示", "请先选择目标窗口")
            return
        key = self.key_combo.get()
        vk = VK_MAP.get(key)
        if vk is None:
            self._log(f"❌ 未知按键: {key}")
            return
        post_message_key(self.selected_hwnd, vk)
        self._log(f"⌨ 已发送 WM_KEYDOWN/UP: {key} (VK=0x{vk:02X})")

    def _send_click(self):
        if not self.selected_hwnd:
            messagebox.showwarning("提示", "请先选择目标窗口")
            return
        try:
            x = int(self.entry_x.get())
            y = int(self.entry_y.get())
        except ValueError:
            self._log("❌ 坐标必须是整数")
            return
        self._do_click(x, y)

    def run(self):
        self.root.mainloop()


def main():
    # 管理员权限检测 & 自动提权
    if not is_admin():
        ans = messagebox.askyesno(
            "需要管理员权限",
            "游戏通常以管理员权限运行,普通权限无法发送 PostMessage。\n\n是否以管理员权限重新启动?\n(选\"否\"继续运行,但输入功能可能无效)"
        )
        if ans:
            elevate()
            return

    app = App()
    app.run()


if __name__ == "__main__":
    main()
