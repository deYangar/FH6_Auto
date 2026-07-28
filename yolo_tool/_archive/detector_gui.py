"""
YOLO 数据工具 — 实时检测可视化 GUI
用于验证模板匹配效果、采集训练截图
"""

import os
import sys
import time
import json
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime

import cv2
import numpy as np
from PIL import Image, ImageTk

# 路径处理：兼容脚本模式和 PyInstaller 打包模式
if getattr(sys, 'frozen', False):
    # PyInstaller 打包后，exe 所在目录（yolo_tool/dist/ 或 yolo_tool/）
    _APP_DIR = os.path.dirname(sys.executable)
else:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))

# images/ 目录在 forza_test_tool/images/（exe 上两级）
# 尝试多种相对路径
def _find_images_root():
    candidates = [
        os.path.join(os.path.dirname(_APP_DIR), "images"),      # yolo_tool/images（exe在yolo_tool/下）
        os.path.join(os.path.dirname(os.path.dirname(_APP_DIR)), "images"),  # forza_test_tool/images（exe在dist/下）
        os.path.join(_APP_DIR, "images"),                        # 同级 images
    ]
    for p in candidates:
        if os.path.isdir(p) and any(d.startswith("scheme_") for d in os.listdir(p) if os.path.isdir(os.path.join(p, d))):
            return p
    return candidates[0]  # 兜底

IMAGES_ROOT = _find_images_root()
PROJECT_ROOT = os.path.dirname(IMAGES_ROOT)

from capture import GameCapture
from matcher import TemplateMatcher


class DetectorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("FH6 YOLO 数据工具 — 实时检测")
        self.root.geometry("1280x800")
        self.root.minsize(960, 600)

        # 状态
        self.running = False
        self.paused = False
        self.current_scheme = tk.StringVar(value="scheme_1")
        self.current_stage = tk.StringVar(value="wheelspin")
        self.threshold = tk.DoubleVar(value=0.70)
        self.fps_var = tk.StringVar(value="FPS: --")
        self.status_var = tk.StringVar(value="就绪")
        self.dets_var = tk.StringVar(value="检测结果: -")

        # 引擎
        self.capture = GameCapture()
        self.matcher = TemplateMatcher(IMAGES_ROOT)
        self._thread = None
        self._lock = threading.Lock()
        self._latest_frame = None     # 原始 BGR
        self._latest_dets = []        # 检测结果
        self._latest_annotated = None # 画了框的 BGR

        # 采集目录（放在 images 同级的 yolo_data/raw/ 下）
        self.data_dir = os.path.join(PROJECT_ROOT, "yolo_data", "raw")

        # 方案列表（扫描 images/ 目录）
        self.schemes = self._scan_schemes()

        self._build_ui()
        self._update_scheme_menu()

    # ==========================================
    # UI 构建
    # ==========================================

    def _build_ui(self):
        # 主布局：左侧控制面板 + 右侧画布
        self.main_frame = ttk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 左侧面板
        self.ctrl_frame = ttk.LabelFrame(self.main_frame, text="控制", width=240)
        self.ctrl_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 5))
        self.ctrl_frame.pack_propagate(False)

        # 右侧画布区域
        self.canvas_frame = ttk.Frame(self.main_frame)
        self.canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._build_controls()
        self._build_canvas()

    def _build_controls(self):
        f = self.ctrl_frame

        # --- 方案选择 ---
        ttk.Label(f, text="方案:").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.scheme_menu = ttk.Combobox(f, textvariable=self.current_scheme,
                                        state="readonly", width=20)
        self.scheme_menu.pack(fill=tk.X, padx=10, pady=2)
        self.scheme_menu.bind("<<ComboboxSelected>>", self._on_scheme_change)

        # --- 阶段选择 ---
        ttk.Label(f, text="阶段:").pack(anchor=tk.W, padx=10, pady=(10, 0))
        stage_frame = ttk.Frame(f)
        stage_frame.pack(fill=tk.X, padx=10, pady=2)
        for stage, label in [("wheelspin", "超抽选车"), ("delete", "删车选车"), ("buy", "买车选车")]:
            rb = ttk.Radiobutton(stage_frame, text=label,
                                 variable=self.current_stage, value=stage,
                                 command=self._on_stage_change)
            rb.pack(anchor=tk.W)

        # --- 分隔线 ---
        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=10)

        # --- 控制按钮 ---
        btn_frame = ttk.Frame(f)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)

        self.btn_start = ttk.Button(btn_frame, text="▶ 开始", command=self.start)
        self.btn_start.pack(fill=tk.X, pady=2)

        self.btn_stop = ttk.Button(btn_frame, text="■ 停止", command=self.stop, state=tk.DISABLED)
        self.btn_stop.pack(fill=tk.X, pady=2)

        self.btn_pause = ttk.Button(btn_frame, text="⏸ 暂停", command=self.toggle_pause, state=tk.DISABLED)
        self.btn_pause.pack(fill=tk.X, pady=2)

        # --- 分隔线 ---
        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=10)

        # --- 阈值滑块 ---
        ttk.Label(f, text="匹配阈值:").pack(anchor=tk.W, padx=10)
        self.thresh_label = ttk.Label(f, text="0.70")
        self.thresh_label.pack(anchor=tk.W, padx=10)
        thresh_scale = ttk.Scale(f, from_=0.50, to=0.95,
                                 variable=self.threshold,
                                 command=self._on_thresh_change)
        thresh_scale.pack(fill=tk.X, padx=10, pady=2)

        # --- 分隔线 ---
        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=10)

        # --- 保存按钮 ---
        self.btn_save = ttk.Button(f, text="📸 保存当前帧", command=self.save_frame, state=tk.DISABLED)
        self.btn_save.pack(fill=tk.X, padx=10, pady=2)

        self.btn_save_multi = ttk.Button(f, text="📸 保存多帧 (5张)", command=self.save_multi_frames, state=tk.DISABLED)
        self.btn_save_multi.pack(fill=tk.X, padx=10, pady=2)

        # --- 分隔线 ---
        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=10)

        # --- 信息显示 ---
        ttk.Label(f, textvariable=self.fps_var, font=("", 10)).pack(anchor=tk.W, padx=10)
        ttk.Label(f, textvariable=self.dets_var, font=("", 9)).pack(anchor=tk.W, padx=10, pady=2)

        # --- 状态栏 ---
        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=10)
        ttk.Label(f, textvariable=self.status_var, foreground="gray",
                  wraplength=200).pack(anchor=tk.W, padx=10, pady=5)

    def _build_canvas(self):
        self.canvas = tk.Canvas(self.canvas_frame, bg="#1e1e1e")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self._canvas_img_id = None
        self._tk_img = None

    # ==========================================
    # 方案 / 阶段
    # ==========================================

    def _scan_schemes(self):
        """扫描 images/ 目录获取方案列表"""
        schemes = []
        if os.path.isdir(IMAGES_ROOT):
            for d in sorted(os.listdir(IMAGES_ROOT)):
                if d.startswith("scheme_") and os.path.isdir(os.path.join(IMAGES_ROOT, d)):
                    schemes.append(d)
        return schemes

    def _update_scheme_menu(self):
        self.scheme_menu["values"] = self.schemes
        if self.schemes and self.current_scheme.get() not in self.schemes:
            self.current_scheme.set(self.schemes[0])

    def _on_scheme_change(self, event=None):
        self._log(f"切换方案: {self.current_scheme.get()}")

    def _on_stage_change(self):
        self._log(f"切换阶段: {self.current_stage.get()}")

    def _on_thresh_change(self, val):
        self.thresh_label.config(text=f"{float(val):.2f}")

    # ==========================================
    # 启动 / 停止 / 暂停
    # ==========================================

    def start(self):
        if self.running:
            return
        # 先启用 DPI 感知（UI 已初始化完成，不影响控件缩放）
        self.capture.enable_dpi()
        # 查找游戏窗口
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
        self.btn_save_multi.config(state=tk.NORMAL)
        self._log(f"已连接游戏窗口 (hwnd={hwnd})")
        self.status_var.set("检测中...")

        # 启动采集+检测线程
        self._thread = threading.Thread(target=self._detect_loop, daemon=True)
        self._thread.start()
        # 启动 GUI 刷新
        self._refresh_gui()

    def stop(self):
        self.running = False
        self.paused = False
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        self.btn_pause.config(state=tk.DISABLED)
        self.btn_save.config(state=tk.DISABLED)
        self.btn_save_multi.config(state=tk.DISABLED)
        self.btn_pause.config(text="⏸ 暂停")
        self.status_var.set("已停止")

    def toggle_pause(self):
        self.paused = not self.paused
        if self.paused:
            self.btn_pause.config(text="▶ 继续")
            self.status_var.set("已暂停")
        else:
            self.btn_pause.config(text="⏸ 暂停")
            self.status_var.set("检测中...")

    # ==========================================
    # 采集 + 检测循环
    # ==========================================

    def _detect_loop(self):
        """后台线程：持续截图 + 模板匹配"""
        frame_count = 0
        fps_timer = time.time()
        fps_value = 0

        while self.running:
            if self.paused:
                time.sleep(0.1)
                continue

            # 截图
            frame = self.capture.capture()
            if frame is None:
                time.sleep(0.5)
                continue

            # 匹配
            scheme = self.current_scheme.get()
            stage = self.current_stage.get()
            thresh = self.threshold.get()

            dets = self.matcher.detect(frame, scheme, stage,
                                       threshold=thresh, fast=True)

            # 画框
            annotated = self._draw_detections(frame.copy(), dets)

            # 更新共享状态
            with self._lock:
                self._latest_frame = frame
                self._latest_dets = dets
                self._latest_annotated = annotated

            # FPS
            frame_count += 1
            elapsed = time.time() - fps_timer
            if elapsed >= 1.0:
                fps_value = frame_count / elapsed
                frame_count = 0
                fps_timer = time.time()
                self.fps_var.set(f"FPS: {fps_value:.1f}")

            # 检测结果统计（显示真实类名）
            cats = {}
            for d in dets:
                class_name = d[0]
                cats[class_name] = cats.get(class_name, 0) + 1
            parts = [f"{k}×{v}" for k, v in cats.items()]
            self.dets_var.set(f"检测: {' '.join(parts) if parts else '无'}")

            # 控制帧率 (~10 FPS)
            time.sleep(0.05)

    def _draw_detections(self, frame, dets):
        """在帧上画检测框，使用 classes.json 的真实类名和颜色"""
        for det in dets:
            class_name, x1, y1, x2, y2, score, tpl_name = det
            color = self.matcher.get_color(class_name)
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

            # 画框
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

            # 标签：类名 + 置信度
            label = f"{class_name} {score:.2f}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(frame, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
            cv2.putText(frame, label, (x1 + 2, y1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)

        return frame

    # ==========================================
    # GUI 刷新
    # ==========================================

    def _refresh_gui(self):
        """定时刷新画布（主线程）"""
        if not self.running:
            return

        with self._lock:
            annotated = self._latest_annotated

        if annotated is not None:
            self._display_frame(annotated)

        self.root.after(80, self._refresh_gui)  # ~12 FPS 刷新

    def _display_frame(self, frame_bgr):
        """将 BGR 帧缩放到画布大小并显示"""
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

        # 画布上显示缩放比例
        self.canvas.create_text(10, 10, anchor=tk.NW,
                                text=f"缩放: {scale:.2f}x | 原始: {w}×{h}",
                                fill="white", font=("", 9))

    # ==========================================
    # 保存截图
    # ==========================================

    def save_frame(self):
        """保存当前帧 + 检测结果为训练数据（YOLO txt 格式）"""
        with self._lock:
            frame = self._latest_frame
            dets = list(self._latest_dets)

        if frame is None:
            messagebox.showinfo("无数据", "没有可保存的帧")
            return

        scheme = self.current_scheme.get()
        stage = self.current_stage.get()
        tag = f"{scheme}_{stage}"

        # 创建保存目录
        save_dir = os.path.join(self.data_dir, tag)
        os.makedirs(save_dir, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        img_name = f"{ts}.png"
        img_path = os.path.join(save_dir, img_name)

        # 保存原图
        cv2.imwrite(img_path, frame)

        # 生成 YOLO 标签 — 使用 matcher 的 class_id 直接映射
        h, w = frame.shape[:2]
        label_lines = []
        for det in dets:
            class_name, x1, y1, x2, y2, score, tpl_name = det
            # 通过 matcher 的 get_class_info 反查 class_id（带方案上下文）
            cls_id, _ = self.matcher.get_class_info(tpl_name, scheme)
            if cls_id is None:
                self._log(f"跳过未知类: {class_name} (tpl={tpl_name})")
                continue
            cx = ((x1 + x2) / 2) / w
            cy = ((y1 + y2) / 2) / h
            bw = (x2 - x1) / w
            bh = (y2 - y1) / h
            label_lines.append(f"{cls_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")

        label_path = img_path.replace(".png", ".txt")
        with open(label_path, "w") as f:
            f.write("\n".join(label_lines) + "\n" if label_lines else "")

        # 保存检测结果图（带框）
        with self._lock:
            annotated = self._latest_annotated
        if annotated is not None:
            anno_path = os.path.join(save_dir, f"{ts}_annotated.png")
            cv2.imwrite(anno_path, annotated)

        self.status_var.set(f"已保存: {img_name} ({len(label_lines)} 个标注)")
        self._log(f"保存: {img_path} | 标注: {len(label_lines)} 个")

    def save_multi_frames(self):
        """连续保存 5 帧（间隔 0.5s）"""
        def _save():
            for i in range(5):
                if not self.running:
                    break
                self.save_frame()
                if i < 4:
                    time.sleep(0.5)

        threading.Thread(target=_save, daemon=True).start()

    # _get_class_id 已移除 — 标注直接用 matcher.get_class_info(tpl_name) 反查 class_id

    # ==========================================
    # 日志
    # ==========================================

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {msg}")


def main():
    global IMAGES_ROOT
    import argparse
    parser = argparse.ArgumentParser(description="FH6 YOLO 实时检测工具")
    _default_images = IMAGES_ROOT
    parser.add_argument("--images", default=_default_images, help="模板图片根目录")
    args = parser.parse_args()
    IMAGES_ROOT = args.images

    root = tk.Tk()
    app = DetectorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
