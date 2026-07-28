"""
FH6 截图采集工具 — 纯预览 + 保存
无模板匹配，只做游戏窗口截图 + 实时预览 + 批量保存
"""

import os
import sys
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

import cv2
import numpy as np
from PIL import Image, ImageTk

# 路径处理
if getattr(sys, 'frozen', False):
    _APP_DIR = os.path.dirname(sys.executable)
else:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))

PROJECT_ROOT = os.path.dirname(_APP_DIR)

from capture import GameCapture


class CaptureApp:
    def __init__(self, root):
        self.root = root
        self.root.title("FH6 截图采集")
        self.root.geometry("1280x800")
        self.root.minsize(960, 600)

        # 状态
        self.running = False
        self.paused = False
        self.fps_var = tk.StringVar(value="FPS: --")
        self.status_var = tk.StringVar(value="就绪")
        self.count_var = tk.StringVar(value="已保存: 0")

        # 采集目录：优先 exe 旁边 data/raw，其次上层 yolo_tool/data/raw
        self.data_dir = os.path.join(_APP_DIR, "data", "raw")
        if not os.path.isdir(os.path.dirname(self.data_dir)):
            alt = os.path.join(PROJECT_ROOT, "yolo_tool", "data", "raw")
            if os.path.isdir(os.path.dirname(alt)):
                self.data_dir = alt
        os.makedirs(self.data_dir, exist_ok=True)
        self.save_count = 0

        # 标签（文件夹名）
        self.tag_var = tk.StringVar(value="scheme_1_wheelspin")

        # 引擎
        self.capture = GameCapture()
        self._thread = None
        self._lock = threading.Lock()
        self._latest_frame = None

        self._build_ui()

    def _build_ui(self):
        # 主布局
        self.main_frame = ttk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 左侧面板
        self.ctrl_frame = ttk.LabelFrame(self.main_frame, text="控制", width=240)
        self.ctrl_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 5))
        self.ctrl_frame.pack_propagate(False)

        # 右侧画布
        self.canvas_frame = ttk.Frame(self.main_frame)
        self.canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._build_controls()
        self._build_canvas()

    def _build_controls(self):
        f = self.ctrl_frame

        # --- 标签输入 ---
        ttk.Label(f, text="保存到目录:").pack(anchor=tk.W, padx=10, pady=(10, 0))
        tag_entry = ttk.Entry(f, textvariable=self.tag_var, width=24)
        tag_entry.pack(fill=tk.X, padx=10, pady=2)
        ttk.Label(f, text="例: scheme_1_wheelspin", foreground="gray",
                  font=("", 8)).pack(anchor=tk.W, padx=10)

        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=10)

        # --- 控制按钮 ---
        self.btn_start = ttk.Button(f, text="▶ 连接游戏", command=self.start)
        self.btn_start.pack(fill=tk.X, padx=10, pady=2)

        self.btn_stop = ttk.Button(f, text="■ 断开", command=self.stop, state=tk.DISABLED)
        self.btn_stop.pack(fill=tk.X, padx=10, pady=2)

        self.btn_pause = ttk.Button(f, text="⏸ 暂停", command=self.toggle_pause, state=tk.DISABLED)
        self.btn_pause.pack(fill=tk.X, padx=10, pady=2)

        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=10)

        # --- 保存按钮 ---
        self.btn_save = ttk.Button(f, text="📸 保存当前帧 (S)", command=self.save_frame, state=tk.DISABLED)
        self.btn_save.pack(fill=tk.X, padx=10, pady=2)

        self.btn_save5 = ttk.Button(f, text="📸 连续保存 5 帧", command=self.save_multi, state=tk.DISABLED)
        self.btn_save5.pack(fill=tk.X, padx=10, pady=2)

        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=10)

        # --- 信息 ---
        ttk.Label(f, textvariable=self.fps_var, font=("", 10)).pack(anchor=tk.W, padx=10)
        ttk.Label(f, textvariable=self.count_var, font=("", 10)).pack(anchor=tk.W, padx=10, pady=2)

        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=10)
        ttk.Label(f, textvariable=self.status_var, foreground="gray",
                  wraplength=200).pack(anchor=tk.W, padx=10, pady=5)

        # --- 快捷键提示 ---
        ttk.Label(f, text="快捷键:\n  S — 保存一帧\n  空格 — 暂停/继续\n  Q — 断开",
                  foreground="gray", font=("", 8)).pack(anchor=tk.W, padx=10, pady=(20, 0))

        # 绑定快捷键
        self.root.bind("<s>", lambda e: self.save_frame())
        self.root.bind("<S>", lambda e: self.save_frame())
        self.root.bind("<space>", lambda e: self.toggle_pause())
        self.root.bind("<q>", lambda e: self.stop())
        self.root.bind("<Q>", lambda e: self.stop())

    def _build_canvas(self):
        self.canvas = tk.Canvas(self.canvas_frame, bg="#1e1e1e")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self._tk_img = None

    # ==========================================
    # 启动 / 停止
    # ==========================================

    def start(self):
        if self.running:
            return
        self.capture.enable_dpi()
        hwnd = self.capture.find_game_window()
        if not hwnd:
            messagebox.showwarning("未找到游戏", "未检测到 Forza Horizon 窗口。\n请先启动游戏。")
            return

        self.running = True
        self.paused = False
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.btn_pause.config(state=tk.NORMAL)
        self.btn_save.config(state=tk.NORMAL)
        self.btn_save5.config(state=tk.NORMAL)
        self.status_var.set("已连接，采集中...")
        self._log(f"已连接游戏窗口 (hwnd={hwnd})")

        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        self._refresh_gui()

    def stop(self):
        self.running = False
        self.paused = False
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        self.btn_pause.config(state=tk.DISABLED)
        self.btn_save.config(state=tk.DISABLED)
        self.btn_save5.config(state=tk.DISABLED)
        self.btn_pause.config(text="⏸ 暂停")
        self.status_var.set("已断开")

    def toggle_pause(self):
        if not self.running:
            return
        self.paused = not self.paused
        if self.paused:
            self.btn_pause.config(text="▶ 继续")
            self.status_var.set("已暂停")
        else:
            self.btn_pause.config(text="⏸ 暂停")
            self.status_var.set("采集中...")

    # ==========================================
    # 采集循环
    # ==========================================

    def _capture_loop(self):
        frame_count = 0
        fps_timer = time.time()

        while self.running:
            if self.paused:
                time.sleep(0.1)
                continue

            frame = self.capture.capture()
            if frame is None:
                time.sleep(0.5)
                continue

            with self._lock:
                self._latest_frame = frame

            frame_count += 1
            elapsed = time.time() - fps_timer
            if elapsed >= 1.0:
                self.fps_var.set(f"FPS: {frame_count / elapsed:.1f}")
                frame_count = 0
                fps_timer = time.time()

            time.sleep(0.05)  # ~20 FPS

    def _refresh_gui(self):
        if not self.running:
            return

        with self._lock:
            frame = self._latest_frame

        if frame is not None:
            self._display_frame(frame)

        self.root.after(80, self._refresh_gui)

    def _display_frame(self, frame_bgr):
        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()
        if canvas_w < 10 or canvas_h < 10:
            return

        h, w = frame_bgr.shape[:2]
        scale = min(canvas_w / w, canvas_h / h)
        new_w = int(w * scale)
        new_h = int(h * scale)

        resized = cv2.resize(frame_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        self._tk_img = ImageTk.PhotoImage(img)

        self.canvas.delete("all")
        x_off = (canvas_w - new_w) // 2
        y_off = (canvas_h - new_h) // 2
        self.canvas.create_image(x_off, y_off, anchor=tk.NW, image=self._tk_img)

        # 信息
        self.canvas.create_text(10, 10, anchor=tk.NW,
                                text=f"{w}×{h} | {scale:.2f}x",
                                fill="white", font=("", 9))

    # ==========================================
    # 保存
    # ==========================================

    def save_frame(self):
        with self._lock:
            frame = self._latest_frame

        if frame is None:
            return

        tag = self.tag_var.get().strip()
        if not tag:
            tag = "unsorted"

        save_dir = os.path.join(self.data_dir, tag)
        os.makedirs(save_dir, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        img_path = os.path.join(save_dir, f"{ts}.png")
        cv2.imwrite(img_path, frame)

        self.save_count += 1
        self.count_var.set(f"已保存: {self.save_count}")
        self.status_var.set(f"已保存: {ts}.png")
        self._log(f"保存: {img_path}")

    def save_multi(self):
        def _save():
            for i in range(5):
                if not self.running:
                    break
                self.save_frame()
                if i < 4:
                    time.sleep(0.3)
        threading.Thread(target=_save, daemon=True).start()

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {msg}")


def main():
    root = tk.Tk()
    app = CaptureApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
