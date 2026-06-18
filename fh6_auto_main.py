import sys
import os
# ====== 【修复 OMP 冲突的核心代码】 ======
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
# =======================================
import json
import time
import shutil
import ctypes
import subprocess
# ====== 【新增】:启动前置环境检测 (防闪退机制) ======
def check_windows_dependencies():
    if sys.platform != "win32":
        return
    missing_dlls = []
    # OpenCV(cv2) 等图像识别库强依赖微软 VC++ 2015-2022 运行库
    required_dlls = ["vcruntime140.dll", "msvcp140.dll", "vcruntime140_1.dll"]

    for dll in required_dlls:
        try:
            # 尝试静默加载该运行库,如果系统里没有,就会触发 OSError
            ctypes.WinDLL(dll)
        except OSError:
            missing_dlls.append(dll)

    if missing_dlls:
        msg = (
            f"警告:系统缺失以下关键运行库,大概率会导致程序闪退或图像识别失败:\n\n"
            f"{', '.join(missing_dlls)}\n\n"
            f"这是因为您的电脑缺少微软 C++ 运行环境。\n"
            f"请搜索下载【微软常用运行库合集】或【VC++ 2015-2022】安装后重试。\n\n"
            f'点击"确定"强行继续运行(如果闪退请安装运行库)。'
        )
        # 0x30 = MB_ICONWARNING (黄色警告图标), 0x0 = MB_OK (只有确定按钮)
        ctypes.windll.user32.MessageBoxW(0, msg, "缺少运行库拦截提示", 0x30 | 0x0)
# 在导入耗性能的大型模块前,第一时间执行拦截检测
check_windows_dependencies()
# ===================================================
# 【极其关键】:必须在任何 UI 库导入之前设置 DPI 感知
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Win 8.1+
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()  # Win Vista+
    except Exception:
        pass

import customtkinter as ctk
ctk.deactivate_automatic_dpi_awareness()
ctk.set_widget_scaling(1.0)
ctk.set_window_scaling(1.0)
import cv2
import numpy as np
import pyautogui
import pydirectinput
from pynput import keyboard
from PIL import Image, ImageGrab
import win32gui
import pickle
import threading
import fh6_backend



# ==========================================
# --- 路径与资源策略 ---
# assets: 只读内置,禁止本地覆盖
# images: 打包进 exe,启动时若外部无 images 则自动释放;识图优先读外部 images
# ==========================================
def get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_internal_dir():
    if hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return get_app_dir()


APP_DIR = get_app_dir()
INTERNAL_DIR = get_internal_dir()
# 【新增 config 目录路径】
CONFIG_DIR = os.path.join(APP_DIR, "config")
USER_CONFIG_FILE = os.path.join(APP_DIR, "config.json")      # <--- 全面替换为 config.json
LOG_FILE = os.path.join(APP_DIR, "bot_log.txt")
CACHE_DIR = os.path.join(APP_DIR, "cache")
TEMPLATE_CACHE_FILE = os.path.join(CACHE_DIR, "template_cache.pkl")
TEMPLATE_META_FILE = os.path.join(CACHE_DIR, "template_meta.json")
CURRENT_VERSION = "1.1.6.3"
def auto_extract_configs():
    os.makedirs(CONFIG_DIR, exist_ok=True)

    # 向下兼容,自动重命名并迁移老版本 bot_config
    old_configs = [
        os.path.join(APP_DIR, "bot_config.json"),
        os.path.join(APP_DIR, "bot-config.json"),
        os.path.join(CONFIG_DIR, "bot-config.json"),
        os.path.join(CONFIG_DIR, "bot_config.json"),
        os.path.join(CONFIG_DIR, "config.json")
    ]
    for old_path in old_configs:
        if os.path.exists(old_path):
            try:
                if not os.path.exists(USER_CONFIG_FILE):
                    shutil.move(old_path, USER_CONFIG_FILE)
                else:
                    os.remove(old_path)
            except Exception:
                pass
def auto_extract_images(folder_name="images"):
    internal_dir = os.path.join(INTERNAL_DIR, folder_name)
    external_dir = os.path.join(APP_DIR, folder_name)

    if not os.path.isdir(internal_dir):
        print(f"[auto_extract_images] 内置目录不存在: {internal_dir}")
        return

    try:
        os.makedirs(external_dir, exist_ok=True)

        for root, dirs, files in os.walk(internal_dir):
            rel_path = os.path.relpath(root, internal_dir)
            target_root = external_dir if rel_path == "." else os.path.join(external_dir, rel_path)
            os.makedirs(target_root, exist_ok=True)

            for file in files:
                src_file = os.path.join(root, file)
                dst_file = os.path.join(target_root, file)

                # 只在外部不存在时释放,保留用户自定义替换
                if not os.path.exists(dst_file):
                    shutil.copy2(src_file, dst_file)

    except Exception as e:
        print(f"[auto_extract_images] 释放 images 失败: {e}")


def get_img_path(filename):
    basename = os.path.basename(filename)

    # 优先读取程序目录外部 images(允许用户替换)
    ext_path = os.path.join(APP_DIR, "images", basename)
    if os.path.exists(ext_path):
        return ext_path

    # 外部没有则读取内置 images
    int_path = os.path.join(INTERNAL_DIR, "images", basename)
    if os.path.exists(int_path):
        return int_path

    return filename


def get_asset_path(*parts):
    """
    assets 只允许读取内置资源:
    - 打包后:_MEIPASS/assets
    - 开发环境:项目目录/assets
    """
    asset_path = os.path.join(INTERNAL_DIR, "assets", *parts)
    if os.path.exists(asset_path):
        return asset_path

    dev_asset_path = os.path.join(get_app_dir(), "assets", *parts)
    if os.path.exists(dev_asset_path):
        return dev_asset_path

    return None


# ==========================================
# --- Ctypes 硬件级键盘模拟结构体定义 ---
# ==========================================
SendInput = ctypes.windll.user32.SendInput
PUL = ctypes.POINTER(ctypes.c_ulong)


class KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL),
    ]


class HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_short),
        ("wParamH", ctypes.c_ushort),
    ]


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL),
    ]


class Input_I(ctypes.Union):
    _fields_ = [
        ("ki", KeyBdInput),
        ("mi", MouseInput),
        ("hi", HardwareInput),
    ]


class Input(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("ii", Input_I),
    ]


# --- 硬件扫描码 (Scan Codes) 包含数字 0-9 ---
DIK_CODES = {
    # control
    "esc": (0x01, False),
    "enter": (0x1C, False),
    "space": (0x39, False),
    "backspace": (0x0E, False),
    "tab": (0x0F, False),
    "lshift": (0x2A, False),
    "rshift": (0x36, False),
    "lctrl": (0x1D, False),
    "rctrl": (0x1D, True),
    "lalt": (0x38, False),
    "ralt": (0x38, True),
    "capslock": (0x3A, False),

    # letters
    "a": (0x1E, False),
    "b": (0x30, False),
    "c": (0x2E, False),
    "d": (0x20, False),
    "e": (0x12, False),
    "f": (0x21, False),
    "g": (0x22, False),
    "h": (0x23, False),
    "i": (0x17, False),
    "j": (0x24, False),
    "k": (0x25, False),
    "l": (0x26, False),
    "m": (0x32, False),
    "n": (0x31, False),
    "o": (0x18, False),
    "p": (0x19, False),
    "q": (0x10, False),
    "r": (0x13, False),
    "s": (0x1F, False),
    "t": (0x14, False),
    "u": (0x16, False),
    "v": (0x2F, False),
    "w": (0x11, False),
    "x": (0x2D, False),
    "y": (0x15, False),
    "z": (0x2C, False),

    # number row
    "1": (0x02, False),
    "2": (0x03, False),
    "3": (0x04, False),
    "4": (0x05, False),
    "5": (0x06, False),
    "6": (0x07, False),
    "7": (0x08, False),
    "8": (0x09, False),
    "9": (0x0A, False),
    "0": (0x0B, False),

    # arrows / navigation
    "up": (0xC8, True),
    "down": (0xD0, True),
    "left": (0xCB, True),
    "right": (0xCD, True),
    "pageup": (0xC9, True),
    "pagedown": (0xD1, True),
    "home": (0xC7, True),
    "end": (0xCF, True),
    "insert": (0xD2, True),
    "delete": (0xD3, True),

    # function keys
    "f1": (0x3B, False),
    "f2": (0x3C, False),
    "f3": (0x3D, False),
    "f4": (0x3E, False),
    "f5": (0x3F, False),
    "f6": (0x40, False),
    "f7": (0x41, False),
    "f8": (0x42, False),
    "f9": (0x43, False),
    "f10": (0x44, False),
    "f11": (0x57, False),
    "f12": (0x58, False),
}

# --- 全局配置 ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")
MATCH_THRESHOLD = 0.8
pyautogui.FAILSAFE = False


class FH_UltimateBot(ctk.CTk):
    def __init__(self):
        super().__init__()
        #窗口相关
        self.title(f"FH6Auto by YSTO v{CURRENT_VERSION}")
        self.geometry("1360x760")
        self.minsize(1180, 700)
        self.attributes("-topmost", False)
        self.attributes("-alpha", 0.98)
        self.resizable(True, True)

        try:
            icon_path = get_asset_path("icon.ico")
            if icon_path:
                self.iconbitmap(icon_path)
        except Exception:
            pass

        self.is_running = False
        self.current_thread = None
        self.is_paused = False  # <--- 【新增】全局暂停状态
        self.game_hwnd = None   # <--- 【后台化】游戏窗口句柄
        self.bg_input = None    # <--- 【后台化】后台输入管理器

        self.race_counter = 0
        self.car_counter = 0
        self.cj_counter = 0
        self.global_loop_current = 0

        self.template_cache = {}
        self.scaled_template_cache = {}
        self.file_template_cache = {}
        self.last_positions = {}
        self.edge_template_cache = {}
        self.scaled_edge_template_cache = {}

        self.init_regions()

        # 【优化加载速度】:将IO提取与图像缓存的加载/生成放到后台线程,避免阻塞主界面启动
        # 增加模型释放步骤
        def background_init():
            auto_extract_images()

            self.prepare_template_cache()
            #self.use_ocr = self.config.get("use_ocr", True)
            #if self.use_ocr:
            #    self.init_ocr_engine()
        threading.Thread(target=background_init, daemon=True).start()

        #加载配置文件
        auto_extract_configs()
        self.load_config()

        self.setup_ui()
        self.start_hotkey_listener()
        self.update_skill_grid()
        self.center_window()

        self.log("免责声明:本脚本仅供 Python 自动化技术交流与学习使用。请勿用于商业盈利或破坏游戏平衡,因使用本脚本造成的账号封禁等损失,由使用者自行承担。")
        self.log("工具运行目录不要有中文")
        self.log("默认刷图车辆:【斯巴鲁Impreza 22B-STi Version】【调校S2  900】【保持默认涂装】【收藏车辆】")
        self.log("启动前先将键盘设置为【英文键盘】")
        self.log("游戏设置为【自动转向】【自动挡】,游戏语言设置为【简体中文】")
        self.log("大部分以图像识别作为引导,减少机器盲目操作的风险,但仍无法完全避免,使用前请做好准备")

    # ==========================================
    # --- UI 安全调度 ---
    # ==========================================
    def ui_call(self, func, *args, **kwargs):
        try:
            self.after(0, lambda: func(*args, **kwargs))
        except Exception:
            pass

    def center_window(self):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        gx, gy, gw, gh = self.regions["全界面"]
        x = gx + (gw - w) // 2
        y = gy + (gh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def format_elapsed(self, seconds):
        seconds = max(0, int(seconds))
        hrs = seconds // 3600
        mins = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"

    def reset_run_stats(self):
        self.start_time = time.time()
        self.active_task_name = "初始化"
        self.active_task_started_at = self.start_time
        self.task_time_totals = {
            "循环跑图": 0.0,
            "批量买车": 0.0,
            "超级抽奖": 0.0,
            "测试启动": 0.0,
            "F3测图": 0.0,
        }

    def finalize_active_task_time(self):
        task_name = getattr(self, "active_task_name", "")
        started_at = getattr(self, "active_task_started_at", None)
        if task_name in getattr(self, "task_time_totals", {}) and started_at:
            self.task_time_totals[task_name] += max(0.0, time.time() - started_at)
        self.active_task_started_at = time.time()

    def normalize_step_entry(self, entry_widget, default_value):
        try:
            v = "".join(c for c in entry_widget.get() if c.isdigit())
            if v == "":
                v = str(default_value)
            iv = int(v)
            if iv < 1:
                iv = 1
            if iv > 3:
                iv = 3
            entry_widget.delete(0, "end")
            entry_widget.insert(0, str(iv))
        except Exception:
            entry_widget.delete(0, "end")
            entry_widget.insert(0, str(default_value))
    # ==========================================
    # --- 初始化全局 Region ---
    # ==========================================
    def init_regions(self):
        sw, sh = pyautogui.size()
        self.update_regions_by_window(0, 0, sw, sh)

    def update_regions_by_window(self, x, y, w, h):
        self.regions = {
            "全界面": (x, y, w, h),
            "左上": (x, y, w // 2, h // 2),
            "右上": (x + w // 2, y, w // 2, h // 2),
            "左下": (x, y + h // 2, w // 2, h // 2),
            "右下": (x + w // 2, y + h // 2, w // 2, h // 2),
            "上": (x, y, w, h // 2),
            "下": (x, y + h // 2, w, h // 2),
            "左": (x, y, w // 2, h),
            "右": (x + w // 2, y, w // 2, h),
            "中间": (x + w // 4, y + h // 4, w // 2, h // 2),
        }

    # ==========================================
    # --- 配置管理 ---
    # ==========================================
    def load_config(self):
        # 1. 直接使用内置字典作为"绝对底本"(最安全,无视打包丢文件问题)
        self.config = {
            "race_count": 99,
            "buy_count": 30,
            "cj_count": 30,
            "chk_1": True,
            "chk_2": True,
            "chk_3": True,
            "next_1": 2,
            "next_2": 3,
            "next_3": 1,
            "global_loops": 10,
            "skill_dirs": ["right", "up", "up", "up", "left"],
            "share_code": "890169683",
            "auto_restart": False,
            "restart_cmd": "start steam://run/2483190",
            "race_timeout": 300
        }
        ext_path = USER_CONFIG_FILE
        # 2. 读取用户的 config.json,并与底本合并(自动补全缺失项)
        if os.path.exists(ext_path):
            try:
                with open(ext_path, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                    self.config.update(user_config)
            except Exception as e:
                self.log(f"用户 config.json 损坏,已自动恢复默认配置。")

        # 3. 将最新、最完整的配置重新写回外置文件
        try:
            with open(ext_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception:
            pass


    def save_config(self):
        try:
            self.config["race_count"] = int(self.entry_race.get())
            self.config["buy_count"] = int(self.entry_car.get())
            self.config["cj_count"] = int(self.entry_cj.get())
            self.config["global_loops"] = int(self.entry_global_loop.get())
            if hasattr(self, "entry_race_timeout"):
                self.config["race_timeout"] = max(60, int(self.entry_race_timeout.get()))
            self.config["share_code"] = "".join(c for c in self.entry_share.get() if c.isdigit())
            #self.config["base_width"] = int(self.entry_base_w.get())
            self.config["next_1"] = int(self.entry_next1.get())
            self.config["next_2"] = int(self.entry_next2.get())
            self.config["next_3"] = int(self.entry_next3.get())
        except Exception:
            pass

        self.config["chk_1"] = self.var_chk1.get()
        self.config["chk_2"] = self.var_chk2.get()
        self.config["chk_3"] = self.var_chk3.get()
        self.config["auto_restart"] = self.var_auto_restart.get()
        self.config["restart_cmd"] = self.le_restart_cmd.get().strip()
        try:
            with open(USER_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.log(f"保存配置失败: {e}")

    # ==========================================
    # --- UI 布局设计 ---
    # ==========================================
    def setup_ui(self):
        self.configure(fg_color="#0F141B")

        self.top_container = ctk.CTkFrame(self, fg_color="transparent")
        self.top_container.pack(fill="x", padx=16, pady=(16, 8))

        self.config_frame = ctk.CTkFrame(self.top_container, fg_color="transparent")
        self.config_frame.pack(fill="x")

        def create_box(parent, title, btn_text, btn_cmd, btn_color, def_val):
            frame = ctk.CTkFrame(
                parent,
                width=170,
                height=255,
                corner_radius=8,
                fg_color="#171D26",
                border_width=1,
                border_color="#2A3442",
            )
            frame.pack_propagate(False)
            frame.pack(side="left", padx=(0, 10), fill="y")

            ctk.CTkLabel(
                frame,
                text=title,
                font=ctk.CTkFont(weight="bold", size=18),
            ).pack(pady=(18, 12))

            btn = ctk.CTkButton(
                frame,
                text=btn_text,
                fg_color=btn_color,
                hover_color=btn_color,
                command=btn_cmd,
                width=124,
                height=36,
                corner_radius=8,
            )
            btn.pack(pady=(4, 10), padx=10)

            entry = ctk.CTkEntry(frame, width=86, height=32, justify="center", corner_radius=6)
            entry.insert(0, str(def_val))
            entry.pack(pady=(4, 8))

            lbl = ctk.CTkLabel(
                frame,
                text=f"执行: 0 / {def_val}",
                text_color="#A0A0A0",
                font=ctk.CTkFont(size=14),
            )
            lbl.pack(pady=(4, 8))
            return frame, btn, entry, lbl

        def create_next_step(parent, var_checked, def_step, box_h=255):
            frame = ctk.CTkFrame(
                parent,
                width=96,
                height=box_h,
                corner_radius=8,
                fg_color="#131923",
                border_width=1,
                border_color="#263140",
            )
            frame.pack(side="left", padx=(0, 10), fill="y")
            frame.pack_propagate(False)

            ctk.CTkLabel(
                frame,
                text="下一步骤",
                font=ctk.CTkFont(size=15, weight="bold"),
                text_color="#5DADE2",
            ).pack(pady=(48, 10))

            entry = ctk.CTkEntry(frame, width=56, height=32, justify="center", corner_radius=6)
            entry.insert(0, str(def_step))
            entry.pack(pady=6)

            chk = ctk.CTkCheckBox(frame, text="继续", variable=var_checked, width=62)
            chk.pack(pady=8)

            return frame, entry, chk

        self.var_chk1 = ctk.BooleanVar(value=self.config["chk_1"])
        self.var_chk2 = ctk.BooleanVar(value=self.config["chk_2"])
        self.var_chk3 = ctk.BooleanVar(value=self.config["chk_3"])

        box_race, self.btn_race, self.entry_race, self.lbl_race = create_box(
            self.config_frame,
            "1. 循环跑图",
            "开始",
            lambda: self.start_pipeline("race"),
            "#1F6AA5",
            self.config.get("race_count", 99),
        )
        self.entry_share = ctk.CTkEntry(box_race, width=128, height=30, justify="center", placeholder_text="蓝图数字代码")
        self.entry_share.insert(0, self.config.get("share_code", "890169683"))
        self.entry_share.pack(pady=(2, 8))

        self.next_frame1, self.entry_next1, self.chk1 = create_next_step(
            self.config_frame, self.var_chk1, self.config.get("next_1", 2)
        )

        box_car, self.btn_car, self.entry_car, self.lbl_car = create_box(
            self.config_frame,
            "2. 批量买车",
            "开始",
            lambda: self.start_pipeline("buy"),
            "#2EA043",
            self.config.get("buy_count", 30),
        )
        self.next_frame2, self.entry_next2, self.chk2 = create_next_step(
            self.config_frame, self.var_chk2, self.config.get("next_2", 3)
        )

        self.box_cj = ctk.CTkFrame(
            self.config_frame,
            width=318,
            height=255,
            corner_radius=8,
            fg_color="#171D26",
            border_width=1,
            border_color="#2A3442",
        )
        self.box_cj.pack_propagate(False)
        self.box_cj.pack(side="left", padx=(0, 10), fill="y")

        top_cj = ctk.CTkFrame(self.box_cj, fg_color="transparent")
        top_cj.pack(fill="x", pady=(12, 6))

        left_cj = ctk.CTkFrame(top_cj, fg_color="transparent")
        left_cj.pack(side="left", padx=(12, 6))

        ctk.CTkLabel(left_cj, text="3. 超级抽奖", font=ctk.CTkFont(weight="bold", size=18)).pack(pady=(2, 10))

        self.btn_cj = ctk.CTkButton(
            left_cj,
            text="开始",
            width=112,
            height=36,
            corner_radius=8,
            fg_color="#8E44AD",
            hover_color="#8E44AD",
            command=lambda: self.start_pipeline("cj"),
        )
        self.btn_cj.pack(pady=(2, 8))

        self.entry_cj = ctk.CTkEntry(left_cj, width=86, height=32, justify="center", corner_radius=6)
        self.entry_cj.insert(0, str(self.config.get("cj_count", 30)))
        self.entry_cj.pack(pady=4)

        self.lbl_cj = ctk.CTkLabel(
            left_cj,
            text=f"执行: 0 / {self.config.get('cj_count', 30)}",
            text_color="#A0A0A0",
            font=ctk.CTkFont(size=14),
        )
        self.lbl_cj.pack(pady=(2, 6))

        dir_frame = ctk.CTkFrame(left_cj, fg_color="transparent")
        dir_frame.pack(pady=4)

        for text, val in [("↑", "up"), ("↓", "down"), ("←", "left"), ("→", "right")]:
            ctk.CTkButton(
                dir_frame,
                text=text,
                width=30,
                height=28,
                corner_radius=6,
                command=lambda x=val: self.add_skill_dir(x),
            ).pack(side="left", padx=2)

        ctk.CTkButton(
            left_cj,
            text="清除矩阵",
            width=90,
            height=28,
            corner_radius=6,
            fg_color="#C0392B",
            hover_color="#A93226",
            command=self.clear_skill_dir,
        ).pack(pady=(7, 4))

        self.grid_frame = ctk.CTkFrame(top_cj, fg_color="transparent")
        self.grid_frame.pack(side="right", padx=(4, 12))

        self.grid_labels = [[None] * 4 for _ in range(4)]
        for r in range(4):
            for c in range(4):
                lbl = ctk.CTkLabel(
                    self.grid_frame,
                    text="",
                    width=27,
                    height=27,
                    corner_radius=5,
                    fg_color="#334155",
                )
                lbl.grid(row=r, column=c, padx=3, pady=3)
                self.grid_labels[r][c] = lbl
        ctk.CTkLabel(
            self.grid_frame,
            text="技能树",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#A0A0A0",
        ).grid(row=4, column=0, columnspan=4, pady=(8, 0))

        self.next_frame3, self.entry_next3, self.chk3 = create_next_step(
            self.config_frame, self.var_chk3, self.config.get("next_3", 1)
        )
        # ====== 抽离到底部的全局设置栏 (放在上方) ======
        # 【修改1】把 self.top_container 改成了 self
        self.global_settings_frame = ctk.CTkFrame(self, fg_color="#18202B", height=48, corner_radius=8)
        # 【修改2】加上了 padx=18,让它和上下边缘对齐
        self.global_settings_frame.pack(fill="x", padx=16, pady=(10, 0))
        self.global_settings_frame.pack_propagate(False)
        ctk.CTkLabel(
            self.global_settings_frame,
            text="循环与守护设置",
            font=ctk.CTkFont(weight="bold", size=15),
            text_color="#F1C40F"
        ).pack(side="left", padx=(16, 18))
        ctk.CTkLabel(self.global_settings_frame, text="大循环:").pack(side="left", padx=(0, 5))
        self.entry_global_loop = ctk.CTkEntry(self.global_settings_frame, width=62, height=28, justify="center", corner_radius=6)
        self.entry_global_loop.insert(0, str(self.config.get("global_loops", 10)))
        self.entry_global_loop.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(self.global_settings_frame, text="单局超时:").pack(side="left", padx=(0, 5))
        self.entry_race_timeout = ctk.CTkEntry(self.global_settings_frame, width=68, height=28, justify="center", corner_radius=6)
        self.entry_race_timeout.insert(0, str(self.config.get("race_timeout", 300)))
        self.entry_race_timeout.pack(side="left", padx=(0, 16))
        self.var_auto_restart = ctk.BooleanVar(value=self.config.get("auto_restart", True))
        self.cb_auto_restart = ctk.CTkCheckBox(self.global_settings_frame, text="闪退自动重启", variable=self.var_auto_restart)
        self.cb_auto_restart.pack(side="left", padx=(4, 16))
        ctk.CTkLabel(self.global_settings_frame, text="启动命令:").pack(side="left", padx=(0, 5))
        self.le_restart_cmd = ctk.CTkEntry(self.global_settings_frame, height=28, corner_radius=6)
        self.le_restart_cmd.insert(0, self.config.get("restart_cmd", "start steam://run/2483190"))
        self.le_restart_cmd.pack(side="left", fill="x", expand=True, padx=(0, 14))
        # ====== 【新增】:测试自动开机流程按钮 ======
        self.btn_test_boot = ctk.CTkButton(
            self.global_settings_frame,
            text="测试启动流程",
            fg_color="#8E44AD",
            hover_color="#7D3C98",
            width=110,
            height=28,
            command=self.start_test_boot
        )
        #self.btn_test_boot.pack(side="left", padx=(0, 20))

        # =================================


        # ====== 运行监控栏 ======
        self.runtime_frame = ctk.CTkFrame(self, fg_color="#18202B", height=64, corner_radius=8)
        self.runtime_frame.pack(fill="x", padx=16, pady=(8, 0))
        self.runtime_frame.pack_propagate(False)

        self.lbl_run_state = ctk.CTkLabel(
            self.runtime_frame,
            text="待机",
            width=74,
            height=34,
            corner_radius=7,
            fg_color="#222B36",
            text_color="#C9D1D9",
            font=ctk.CTkFont(size=15, weight="bold"),
        )
        self.lbl_run_state.pack(side="left", padx=(14, 12), pady=12)

        def make_runtime_label(title, value="--"):
            frame = ctk.CTkFrame(self.runtime_frame, fg_color="transparent")
            frame.pack(side="left", padx=(0, 18), pady=8)
            ctk.CTkLabel(frame, text=title, text_color="#8B949E", font=ctk.CTkFont(size=11)).pack(anchor="w")
            lbl = ctk.CTkLabel(frame, text=value, text_color="#F0F6FC", font=ctk.CTkFont(size=14, weight="bold"))
            lbl.pack(anchor="w")
            return lbl

        self.lbl_runtime_task = make_runtime_label("当前任务", "等待中")
        self.lbl_runtime_progress = make_runtime_label("任务进度", "0 / 0")
        self.lbl_runtime_loop = make_runtime_label("大循环", "0 / 0")
        self.lbl_runtime_task_time = make_runtime_label("本任务耗时", "00:00:00")
        self.lbl_runtime_total_time = make_runtime_label("总运行时间", "00:00:00")
        self.lbl_runtime_totals = make_runtime_label("模块累计", "跑图 00:00:00 | 买车 00:00:00 | 超抽 00:00:00")

        self.btn_runtime_pause = ctk.CTkButton(
            self.runtime_frame,
            text="暂停 F9",
            width=78,
            height=34,
            corner_radius=7,
            fg_color="#F1C40F",
            hover_color="#D4AC0D",
            text_color="#111827",
            font=ctk.CTkFont(weight="bold"),
            command=self.toggle_pause,
            state="disabled",
        )
        self.btn_runtime_pause.pack(side="right", padx=(0, 8), pady=12)

        self.btn_runtime_stop = ctk.CTkButton(
            self.runtime_frame,
            text="停止 F8",
            width=78,
            height=34,
            corner_radius=7,
            fg_color="#DA3633",
            hover_color="#B02A37",
            font=ctk.CTkFont(weight="bold"),
            command=self.stop_all,
            state="disabled",
        )
        self.btn_runtime_stop.pack(side="right", padx=(0, 12), pady=12)

        #ctk.CTkLabel(self.global_settings_frame, text="图片原宽(不要修改):").pack(side="left", padx=(10, 5))
        #self.entry_base_w = ctk.CTkEntry(self.global_settings_frame, width=70, height=28, justify="center")
        #self.entry_base_w.insert(0, str(self.config.get("base_width", 2560)))
        #self.entry_base_w.pack(side="left", padx=(0, 20))

        self.entry_next1.bind("<FocusOut>", lambda e: self.normalize_step_entry(self.entry_next1, 2))
        self.entry_next2.bind("<FocusOut>", lambda e: self.normalize_step_entry(self.entry_next2, 3))
        self.entry_next3.bind("<FocusOut>", lambda e: self.normalize_step_entry(self.entry_next3, 1))


        self.bottom_frame = ctk.CTkFrame(self, fg_color="transparent", height=260)
        self.bottom_frame.pack(fill="both", expand=True, padx=16, pady=(10, 16))

        self.btn_stop = ctk.CTkButton(
            self.bottom_frame,
            text="等待指令 (F8)",
            fg_color="#222B36",
            hover_color="#2F3B4A",
            width=156,
            height=60,
            corner_radius=8,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self.stop_all,
        )
        self.btn_stop.pack(side="left", fill="y", padx=(0, 10))

        self.log_box = ctk.CTkTextbox(
            self.bottom_frame,
            state="disabled",
            wrap="word",
            corner_radius=8,
            height=220,
            fg_color="#171D26",
            border_width=1,
            border_color="#2A3442",
            font=ctk.CTkFont(size=15),
        )
        self.log_box.pack(side="left", fill="both", expand=True)
        #ocr加载

    def update_timer(self):
        if not self.is_running:
            return

        now = time.time()
        total_elapsed = now - getattr(self, "start_time", now)
        task_elapsed = now - getattr(self, "active_task_started_at", now)
        totals = getattr(self, "task_time_totals", {})
        race_total = totals.get("循环跑图", 0.0)
        buy_total = totals.get("批量买车", 0.0)
        cj_total = totals.get("超级抽奖", 0.0)

        active_task = getattr(self, "active_task_name", "")
        if active_task == "循环跑图":
            race_total += task_elapsed
        elif active_task == "批量买车":
            buy_total += task_elapsed
        elif active_task == "超级抽奖":
            cj_total += task_elapsed

        try:
            self.lbl_runtime_task_time.configure(text=self.format_elapsed(task_elapsed))
            self.lbl_runtime_total_time.configure(text=self.format_elapsed(total_elapsed))
            self.lbl_runtime_totals.configure(
                text=(
                    f"跑图 {self.format_elapsed(race_total)} | "
                    f"买车 {self.format_elapsed(buy_total)} | "
                    f"超抽 {self.format_elapsed(cj_total)}"
                )
            )
        except Exception: pass

        if self.is_running:
            self.after(1000, self.update_timer)

    def update_running_ui(self, task_name="", current_val=0, max_val=0):
        try:
            if task_name:
                old_task = getattr(self, "active_task_name", "")
                if old_task != task_name:
                    self.finalize_active_task_time()
                    self.active_task_name = task_name
                self.ui_call(self.lbl_runtime_task.configure, text=task_name)
            if max_val > 0:
                self.ui_call(self.lbl_runtime_progress.configure, text=f"{current_val} / {max_val}")
        except Exception:
            pass

    def update_running_state(self, state):
        try:
            if state == "running":
                self.lbl_run_state.configure(text="运行中", fg_color="#238636", text_color="#FFFFFF")
                self.btn_runtime_pause.configure(state="normal", text="暂停 F9", fg_color="#F1C40F", hover_color="#D4AC0D", text_color="#111827")
                self.btn_runtime_stop.configure(state="normal")
                self.btn_stop.configure(text="停止任务 (F8)", fg_color="#DA3633", hover_color="#B02A37")
            elif state == "paused":
                self.lbl_run_state.configure(text="已暂停", fg_color="#9A6700", text_color="#FFFFFF")
                self.btn_runtime_pause.configure(state="normal", text="继续 F9", fg_color="#2EA043", hover_color="#238636", text_color="#FFFFFF")
            else:
                self.lbl_run_state.configure(text="待机", fg_color="#222B36", text_color="#C9D1D9")
                self.lbl_runtime_task.configure(text="等待中")
                self.lbl_runtime_progress.configure(text="0 / 0")
                self.lbl_runtime_loop.configure(text="0 / 0")
                self.lbl_runtime_task_time.configure(text="00:00:00")
                self.lbl_runtime_total_time.configure(text="00:00:00")
                self.lbl_runtime_totals.configure(text="跑图 00:00:00 | 买车 00:00:00 | 超抽 00:00:00")
                self.btn_runtime_pause.configure(state="disabled", text="暂停 F9", fg_color="#F1C40F", hover_color="#D4AC0D", text_color="#111827")
                self.btn_runtime_stop.configure(state="disabled")
                self.btn_stop.configure(text="等待指令 (F8)", fg_color="#222B36", hover_color="#2F3B4A")
        except Exception:
            pass

    # ==========================================
    # --- 核心操作与流程控制 ---
    # ==========================================
    def hw_key_down(self, key):
        # 【后台化】通过 PostMessage 发送按键
        if self.bg_input:
            self.bg_input.key_down(key)
        else:
            # 兜底：原硬件级输入
            if key not in DIK_CODES:
                return
            scan_code, extended = DIK_CODES[key]
            flags = 0x0008 | (0x0001 if extended else 0)
            extra = ctypes.c_ulong(0)
            ii_ = Input_I()
            ii_.ki = KeyBdInput(0, scan_code, flags, 0, ctypes.pointer(extra))
            x = Input(ctypes.c_ulong(1), ii_)
            SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

    def hw_key_up(self, key):
        # 【后台化】通过 PostMessage 发送按键
        if self.bg_input:
            self.bg_input.key_up(key)
        else:
            # 兜底：原硬件级输入
            if key not in DIK_CODES:
                return
            scan_code, extended = DIK_CODES[key]
            flags = 0x000A | (0x0001 if extended else 0)
            extra = ctypes.c_ulong(0)
            ii_ = Input_I()
            ii_.ki = KeyBdInput(0, scan_code, flags, 0, ctypes.pointer(extra))
            x = Input(ctypes.c_ulong(1), ii_)
            SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

    def hw_press(self, key, delay=0.08):
        self.check_pause()
        if not self.is_running:
            return
        if self.bg_input:
            self.bg_input.press(key, delay=delay)
        else:
            self.hw_key_down(key)
            time.sleep(delay)
            self.hw_key_up(key)
    #副屏支持
    def hw_mouse_move(self, x, y):
        # 【后台化】不再移动物理鼠标，PostMessage 点击直接指定客户区坐标
        # 保留空函数以兼容旧代码调用
        pass
    def game_click(self, pos, double=False):
        self.check_pause()
        if not self.is_running or not pos:
            return
        x, y = int(pos[0]), int(pos[1])

        # 【后台化】使用 PostMessage 在窗口内点击，坐标已经是屏幕绝对坐标
        # 需要转换为窗口客户区相对坐标
        if self.game_hwnd and self.bg_input:
            try:
                gx, gy, gw, gh = self.regions["全界面"]
                rel_x = x - gx
                rel_y = y - gy
                self.bg_input.click(rel_x, rel_y, double=double)
                return
            except Exception:
                pass

        # 兜底：原硬件级点击方式
        self.hw_mouse_move(x, y)
        time.sleep(0.2)
        for _ in range(2 if double else 1):
            pydirectinput.mouseDown()
            time.sleep(0.1)
            pydirectinput.mouseUp()
            time.sleep(0.1)
        time.sleep(0.1)

    def move_to_game_coord(self, x, y):
        """
        【后台化】不再需要移动物理鼠标，此操作在后台模式下无意义
        保留函数以兼容旧代码调用
        """
        pass

    def add_skill_dir(self, direction):
        self.config["skill_dirs"].append(direction)
        self.update_skill_grid()
        self.save_config()

    def clear_skill_dir(self):
        self.config["skill_dirs"].clear()
        self.update_skill_grid()
        self.save_config()

    def update_skill_grid(self):
        for r in range(4):
            for c in range(4):
                self.grid_labels[r][c].configure(fg_color="#333333")

        curr_r, curr_c = 3, 0
        self.grid_labels[curr_r][curr_c].configure(fg_color="#3498DB")
        valid_dirs = []

        for d in self.config["skill_dirs"]:
            if d == "up":
                curr_r -= 1
            elif d == "down":
                curr_r += 1
            elif d == "left":
                curr_c -= 1
            elif d == "right":
                curr_c += 1

            if 0 <= curr_r < 4 and 0 <= curr_c < 4:
                self.grid_labels[curr_r][curr_c].configure(fg_color="#3498DB")
                valid_dirs.append(d)
            else:
                break

        self.config["skill_dirs"] = valid_dirs

    def log(self, message):
        curr_time = time.strftime("%H:%M:%S")
        full_msg = f"[{curr_time}] {message}"

        def write_ui():
            try:
                # 写入下方大界面的日志
                self.log_box.configure(state="normal")
                self.log_box.insert("end", full_msg + "\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
            except Exception:
                pass
        self.ui_call(write_ui)
    def start_pipeline(self, start_step):
        if self.is_running:
            return

        self.is_running = True
        self.save_config()

        self.reset_run_stats()
        self.update_running_state("running")
        self.update_timer()
        self.update_running_ui("初始化中...")
        self.race_counter = 0
        self.car_counter = 0
        self.cj_counter = 0
        self.global_loop_current = 0

        def runner():
            if not self.check_and_focus_game():
                self.stop_all()
                return

            steps = ["race", "buy", "cj"]
            curr_idx = steps.index(start_step)

            try:
                total_loops = int(self.entry_global_loop.get())
            except Exception:
                total_loops = self.config.get("global_loops", 10)
            self.global_loop_current = 1
            self.ui_call(self.lbl_runtime_loop.configure, text=f"{self.global_loop_current} / {total_loops}")

            # 【新增】:全局连续失败计数器
            continuous_failures = 0
            # 【你可以修改这里】:设置全局允许的最大连续恢复次数(比如 3 次)
            MAX_RECOVERIES = 10

            while self.is_running:
                step_name = steps[curr_idx]
                success = False

                try:
                    if step_name == "race":
                        success = self.logic_race(int(self.entry_race.get()))
                    elif step_name == "buy":
                        success = self.logic_buy_car(int(self.entry_car.get()))
                    elif step_name == "cj":
                        success = self.logic_super_wheelspin(int(self.entry_cj.get()))
                except Exception as e:
                    self.log(f"执行模块 {step_name} 时异常: {e}")
                    success = False

                if not self.is_running:
                    break

                if not success:
                    continuous_failures += 1

                    # 检查是否超过最大容忍次数
                    if continuous_failures > MAX_RECOVERIES:
                        self.log(f"!!! 警告:连续 {continuous_failures} 次触发断点恢复仍未能解决问题!")
                        self.log("为防止游戏陷入死循环,强制终止当前所有任务,请人工检查游戏状态。")
                        break # 直接跳出 while,停止脚本

                    self.log(f"正在进行全局恢复 (第 {continuous_failures}/{MAX_RECOVERIES} 次允许的重试)...")

                    if self.attempt_recovery():
                        continue # 恢复成功,回到 while 顶部再次尝试这个任务
                    else:
                        self.log("致命错误:连退回菜单/重启也失败了,彻底停止。")
                        break
                else:
                    # 只要这一个大步骤成功跑完了,就把连续失败次数清零,奖励它继续跑!
                    continuous_failures = 0
                #v1.0.1
                # ====== 核心流转与无限循环逻辑 ======
                next_idx = curr_idx + 1 # 默认前往下一步
                if curr_idx == 0:
                    if self.var_chk1.get():
                        try: next_idx = max(0, min(3, int(self.entry_next1.get()) - 1))
                        except Exception: next_idx = 1
                    else: break
                elif curr_idx == 1:
                    if self.var_chk2.get():
                        try: next_idx = max(0, min(3, int(self.entry_next2.get()) - 1))
                        except Exception: next_idx = 2
                    else: break
                elif curr_idx == 2:
                    if self.var_chk3.get():
                        try: next_idx = max(0, min(2, int(self.entry_next3.get()) - 1))
                        except Exception: next_idx = 0
                    else: break

                if next_idx <= curr_idx:
                    self.global_loop_current += 1

                    if self.global_loop_current > total_loops:
                        self.log("达到设定的总循环次数,任务圆满结束。")
                        break

                    self.log(f"开启新一轮大循环 ({self.global_loop_current}/{total_loops})")

                    self.ui_call(self.lbl_runtime_loop.configure, text=f"{self.global_loop_current} / {total_loops}")

                    self.race_counter = 0
                    self.car_counter = 0
                    self.cj_counter = 0

                curr_idx = next_idx

            self.stop_all()

        self.current_thread = threading.Thread(target=runner, daemon=True)
        self.current_thread.start()

    def stop_all(self):
        if not self.is_running:
            return

        self.is_running = False
        self.is_paused = False  # <--- 【新增】彻底停止时必须解除暂停锁

        for key in DIK_CODES.keys():
            self.hw_key_up(key)

        for key in ["w", "e", "y", "enter", "esc", "up", "down", "left", "right", "space", "backspace"]:
            self.hw_key_up(key)

        try:
            pydirectinput.mouseUp()
        except Exception:
            pass

        self.finalize_active_task_time()
        self.ui_call(self.update_running_state, "idle")
        self.log("!!! 任务已停止,所有物理按键状态已强制重置")
    def start_test_boot(self):
        """独立运行的测试开机流程"""
        if self.is_running:
            self.log("已有任务正在运行,请先点击停止后再测试启动流程!")
            return

        self.is_running = True
        self.save_config()
        self.reset_run_stats()
        self.update_running_state("running")
        self.update_running_ui("测试启动")
        self.update_timer()

        self.log("====== 开始独立测试自动开机与识别流程 ======")

        def test_runner():
            success = self.restart_game_and_boot(force_test=True)
            if success:
                self.log("测试结束:自动开机、A/B/C状态机识别并到达菜单完美跑通!")
            else:
                self.log("测试结束:自动开机流程失败,请检查截图或日志。")
            self.stop_all() # 测试完毕自动停止脚本,自动恢复回大窗口状态

        self.current_thread = threading.Thread(target=test_runner, daemon=True)
        self.current_thread.start()
    # ==========================================
    # --- 【新增】暂停与恢复逻辑 ---
    # ==========================================
    def toggle_pause(self):
        if not self.is_running:
            return

        self.is_paused = not self.is_paused

        if self.is_paused:
            self.log("⏸ 任务已暂停 (按 F9 或点击按钮恢复)")
            # 强制松开所有可能按住的按键,防止车自己开走或UI乱跳
            for key in ["w", "e", "y", "enter", "esc", "up", "down", "left", "right", "space", "backspace"]:
                self.hw_key_up(key)
            try:
                pydirectinput.mouseUp()
            except Exception:
                pass
            self.ui_call(self.update_running_state, "paused")
        else:
            self.log("▶ 任务已恢复")
            self.ui_call(self.update_running_state, "running")

    def check_pause(self):
        """核心阻塞器:任何动作前调用此方法,如果是暂停状态,将在此无限等待"""
        while self.is_paused and self.is_running:
            time.sleep(0.1)


    def start_hotkey_listener(self):
        def hotkey_thread():
            def on_press(k):
                if k == keyboard.Key.f8:
                    self.stop_all()
                elif k == keyboard.Key.f9:  # <--- 【新增】F9 快捷键
                    self.toggle_pause()
                elif k == keyboard.Key.f3:  # <--- 【新增】F3 测试找图
                    self.start_test_find_image()

            with keyboard.Listener(on_press=on_press) as listener:
                listener.join()

        threading.Thread(target=hotkey_thread, daemon=True).start()


    # ==========================================
    # --- 逻辑保障 ---
    # ==========================================
    # 【新增】:强制切换英文键盘与关闭中文状态
    def set_english_input(self):
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return
            # 策略1:尝试切美式键盘
            hkl = ctypes.windll.user32.LoadKeyboardLayoutW("00000409", 1)
            ctypes.windll.user32.PostMessageW(hwnd, 0x0050, 0, hkl)
            # 策略2:底层强制关闭当前中文输入法的中文状态(绝杀)
            WM_IME_CONTROL = 0x0283
            IMC_SETOPENSTATUS = 0x0006
            ctypes.windll.user32.SendMessageW(hwnd, WM_IME_CONTROL, IMC_SETOPENSTATUS, 0)

            self.log("已自动切换英文键盘/关闭中文输入法状态。")
        except Exception as e:
            self.log(f"自动防中文输入设置失败: {e}")
    def check_and_focus_game(self):
        self.log("检查游戏进程 (forzahorizon6.exe)...")
        try:
            CREATE_NO_WINDOW = 0x08000000
            cmd = 'tasklist /FI "IMAGENAME eq forzahorizon6.exe" /NH /FO CSV'
            output = subprocess.check_output(cmd, shell=True, text=True, creationflags=CREATE_NO_WINDOW)

            if "forzahorizon6.exe" not in output.lower():
                self.log("未发现 forzahorizon6.exe 进程!(请确保游戏已运行)")
                return False

            target_pid = None
            for line in output.strip().split("\n"):
                parts = line.split('","')
                if len(parts) >= 2 and "forzahorizon6.exe" in parts[0].lower():
                    target_pid = int(parts[1].replace('"', ""))
                    break

            if not target_pid:
                self.log("找到进程但无法解析PID!")
                return False

            hwnds = []

            def foreach_window(hwnd, lParam):
                if ctypes.windll.user32.IsWindowVisible(hwnd):
                    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        window_pid = ctypes.c_ulong()
                        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
                        if window_pid.value == target_pid:
                            hwnds.append(hwnd)
                return True

            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            ctypes.windll.user32.EnumWindows(EnumWindowsProc(foreach_window), 0)

            if hwnds:
                hwnd = hwnds[0]
                if ctypes.windll.user32.IsIconic(hwnd):
                    ctypes.windll.user32.ShowWindow(hwnd, 9)
                else:
                    ctypes.windll.user32.ShowWindow(hwnd, 5)

                # 【后台化】不再强制前台窗口,保持后台运行
                # ctypes.windll.user32.SetForegroundWindow(hwnd)
                # time.sleep(0.5)
                # ====== 【新增】:强制关闭中文输入法 ======
                # 【后台化】PostMessage 不受输入法影响,跳过
                # self.set_english_input()
                # ==========================================
                try:
                    # 1. 更新识图区域为游戏实际窗口区域(识图必须在游戏窗口内)
                    client_rect = win32gui.GetClientRect(hwnd)
                    pt = win32gui.ClientToScreen(hwnd, (0, 0))
                    gx, gy = pt[0], pt[1]
                    gw, gh = client_rect[2], client_rect[3]
                    # ====== 【核心修复】:拦截启动小窗/防作弊闪屏 ======
                    # 如果窗口宽度和高度太小,说明绝对不是正常的游戏主画面
                    if gw < 1000 or gh < 600:
                        self.log(f"拦截到过小窗口 ({gw}x{gh}),判定为启动闪屏,等待主窗口加载...")
                        return False
                    # ====================================================
                    self.update_regions_by_window(gx, gy, gw, gh)

                    # 【后台化】保存窗口句柄并创建后台输入管理器
                    self.game_hwnd = hwnd
                    if self.bg_input:
                        self.bg_input.stop()
                    self.bg_input = fh6_backend.BackgroundInputManager(hwnd)
                    self.bg_input.start()
                    self.log(f"🖥️ 后台模式已激活 | hwnd=0x{hwnd:X} | 客户区={gw}x{gh}")

                    # 2. 获取该窗口所在的物理显示器边界
                    MONITOR_DEFAULTTONEAREST = 2
                    hMonitor = ctypes.windll.user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
                    class RECT(ctypes.Structure):
                        _fields_ = [
                            ("left", ctypes.c_long),
                            ("top", ctypes.c_long),
                            ("right", ctypes.c_long),
                            ("bottom", ctypes.c_long)
                        ]
                    class MONITORINFO(ctypes.Structure):
                        _fields_ = [
                            ("cbSize", ctypes.c_ulong),
                            ("rcMonitor", RECT),
                            ("rcWork", RECT),
                            ("dwFlags", ctypes.c_ulong)
                        ]
                    mi = MONITORINFO()
                    mi.cbSize = ctypes.sizeof(MONITORINFO)

                    if ctypes.windll.user32.GetMonitorInfoW(hMonitor, ctypes.byref(mi)):
                        mx = mi.rcMonitor.left
                        my = mi.rcMonitor.top
                        mw = mi.rcMonitor.right - mi.rcMonitor.left
                        mh = mi.rcMonitor.bottom - mi.rcMonitor.top
                    else:
                        # 兜底:如果获取不到屏幕边界,就用游戏窗口边界
                        mx, my, mw, mh = gx, gy, gw, gh

                except Exception as e:
                    self.log(f"获取窗口坐标失败: {e}")

                time.sleep(1.0)
                return True

        except Exception as e:
            self.log(f"检查进程异常: {e}")
            return False

        return False

    def restart_game_and_boot(self, force_test=False):
        # 除非点击了测试按钮(force_test),否则检查设置里是否允许自动重启
        if not force_test:
            auto_restart = getattr(self, "var_auto_restart", None)
            if auto_restart is None or not auto_restart.get():
                self.log("未开启自动重启,任务结束。")
                return False

        self.log("触发启动机制!正在拉起游戏...")
        try:
            cmd_widget = getattr(self, "le_restart_cmd", None)
            cmd_str = cmd_widget.get() if cmd_widget else self.config.get("restart_cmd", "start steam://run/2483190")
            os.system(cmd_str)
        except Exception as e:
            self.log(f"执行启动命令失败: {e}")
            return False

        self.log("等待游戏进程出现 (最多60秒)...")
        process_found = False
        for _ in range(120):
            if hasattr(self, "check_pause"): self.check_pause()
            if not self.is_running: return False
            if self.check_and_focus_game():
                process_found = True
                break
            time.sleep(1)

        if not process_found:
            self.log("未检测到游戏进程,启动失败。")
            return False

        self.log("游戏进程已启动,进入动态识别阶段 (限制5分钟)...")
        start_time = time.time()

        passed_screen_1 = False      # 记录是否已经按过画面1的回车
        last_continue_time = 0       # 记录最后一次看到/点击"继续按钮"的时间戳

        while self.is_running and time.time() - start_time < 300:
            if hasattr(self, "check_pause"): self.check_pause()

            # ==============================
            # 画面1:寻找左下角 horizon6.png -> 按回车
            # ==============================
            if not passed_screen_1:
                pos_h6 = None

                # 策略A:透明图识别
                pos_h6 = self.find_image_transparent("horizon6.png", region=self.regions["全界面"], threshold=0.60, fast_mode=False)

                # 策略B:边缘轮廓识别兜底!
                if not pos_h6:
                    try:
                        screen_bgr = self.capture_region(self.regions["全界面"])
                        tpl_bgr, _ = self.load_template("horizon6.png")
                        if tpl_bgr is not None:
                            screen_edge = self.to_edge_image(screen_bgr)
                            tpl_edge = self.to_edge_image(tpl_bgr)

                            for scale in self.get_scales_to_try(fast_mode=False):
                                t_e = tpl_edge if scale == 1.0 else cv2.resize(tpl_edge, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                                h, w = t_e.shape[:2]
                                if h > screen_edge.shape[0] or w > screen_edge.shape[1] or h < 5 or w < 5: continue

                                res = cv2.matchTemplate(screen_edge, t_e, cv2.TM_CCOEFF_NORMED)
                                _, max_val, _, max_loc = cv2.minMaxLoc(res)

                                if max_val >= 0.40:
                                    self.log(f"[轮廓黑科技] 无视背景命中!得分: {max_val:.2f} 缩放: {scale:.2f}")
                                    pos_h6 = (max_loc[0] + w//2 + self.regions["全界面"][0], max_loc[1] + h//2 + self.regions["全界面"][1])
                                    break
                    except Exception:
                        pass

                if pos_h6:
                    self.log("✅ 成功识别到 画面1 (horizon6.png),按下【回车键】...")
                    time.sleep(1)
                    for _ in range(2):
                        self.hw_press("enter")
                        time.sleep(1)
                    passed_screen_1 = True
                    # 激活画面2的倒计时机制,如果在后续的寻找中一直没看到画面2,也会在30秒后尝试进菜单
                    last_continue_time = time.time()
                    self.log("已确认画面1,强制等待 10 秒等待画面2加载...")
                    time.sleep(10) # 等待10秒
                    continue
                else:
                    self.log("未找到画面1。正在使用全比例深度扫描...")

            # ==============================
            # 画面2:寻找右下角 continue-b 或 continue-w -> 死磕点击
            # ==============================
            # 只有在通过了画面1的前提下,才去寻找画面2
            if passed_screen_1:
                pos_continue = self.find_any_image_gray(["continue-b.png", "continue-w.png"], threshold=0.75)
                if pos_continue:
                    self.log("识别到 画面2 (继续按钮),进行点击...")
                    self.game_click(pos_continue)

                    # 【核心逻辑】:只要点击了,就刷新时间戳!
                    last_continue_time = time.time()

                    time.sleep(3.0) # 点击后过3秒再试,只要有就继续点
                    continue

                # ==============================
                # 状态转化:进入漫游与菜单呼出
                # ==============================
                # 如果当前时间 距离【最后一次点击画面2的时间】已经超过了 30秒,且期间再也没找到过
                time_since_last_seen = time.time() - last_continue_time
                if time_since_last_seen >= 30.0:
                    self.log("✅ 已经连续 30 秒未再发现继续按钮,判定为漫游载入完毕!开始尝试进入菜单...")

                    if getattr(self, "enter_menu")():
                        self.log("🎉 验证成功:已成功进入游戏主菜单!启动流程完美结束。")
                        return True
                    else:
                        self.log("普通进入菜单失败(可能还在黑屏或有新弹窗),重置 30秒倒计时,继续观察...")
                        # 如果没进成功,重置时间戳,脚本会继续找画面2,或者再等30秒重试进菜单
                        last_continue_time = time.time()

            time.sleep(1.0) # 每次总循环休息1秒,防止CPU占用过高

        self.log("自动启动超时(5分钟),放弃抢救。")
        return False

    def handle_vramne_restart(self):
        self.log("!!! 检测到 VRAMNE.png。已禁用强杀游戏进程,脚本将停止并交由人工处理。")
        return False


    def check_vramne_during_race(self):
        try:
            pos_vram = self.find_image_gray(
                "VRAMNE.png",
                region=self.regions["全界面"],
                threshold=0.70,
                fast_mode=True
            )
            if pos_vram:
                return self.handle_vramne_restart()
            return None
        except Exception as e:
            self.log(f"检测到显存不足: {e}")
            return None
    def attempt_recovery(self):
        self.log("任务执行异常中断,准备执行断点恢复流程...")
        if not self.check_and_focus_game():
            # 游戏没开或者进程没了,直接走重启流程
            if not self.restart_game_and_boot():
                return False
        else:
            # 进程还在,使用【高级状态机】尝试动态退回
            if not self.advanced_enter_menu():
                self.log("高级动态退回失败。已禁用强杀游戏进程,停止脚本并保留游戏运行状态。")
                return False
        self.log("环境重置成功!即将从中断处继续剩余任务。")
        return True

    def wait_for_freeroam(self):
        self.log("验证漫游状态...")
        for i in range(100):
            if not self.is_running:
                return False

            if self.find_image("anna.png", region=self.regions["左下"], threshold=0.5):
                self.log("验证成功:已确认处于游戏漫游界面。")
                return True

            self.log(f"重试返回漫游界面({i + 1}/100)")
            self.hw_press("esc")

            for _ in range(20):
                if not self.is_running:
                    return False
                time.sleep(0.1)

        self.log("多次尝试验证漫游界面失败,尝试进入菜单。")
        return True

    def recover_to_menu(self):
        self.log("开始尝试退回主菜单...")
        return self.enter_menu()

    def is_in_menu(self):
        return self.find_image_gray(
            "collectionjournal.png",
            region=self.regions["左"],
            threshold=0.70,
            fast_mode=True
        )
    def enter_menu(self):
        self.log("正在尝试进入主菜单...")
        # 连续尝试 60 次,大概花费 40~60 秒
        for i in range(60):
            if not self.is_running:
                return False


            pos_menu = self.find_image_gray("collectionjournal.png", region=self.regions["左"], threshold=0.70, fast_mode=True)

            if pos_menu:
                self.log(f"成功定位到菜单锚点!({i + 1}/60)")
                time.sleep(0.5)
                return True

            self.log(f"未在主菜单... ({i + 1}/60)")
            self.hw_press("esc")
            # 给游戏一点动画加载时间
            time.sleep(1.0)

        self.log("60 次尝试均未进入菜单,请检查游戏状态。")
        return False
    def advanced_enter_menu(self):
        """
        高级状态机退回:专门用于故障恢复。
        能够识别中途的特定弹窗、中间过渡画面,并执行点击,没找到目标才按 ESC。
        """
        self.log("正在使用【高级恢复模式】尝试退回主菜单...")

        # ==========================================
        # 动态读取 images/obstacles/ 里的所有图片
        # ==========================================
        obstacles_dir = os.path.join("images", "obstacles")
        dynamic_obstacles = []

        # 检查文件夹是否存在
        if os.path.exists(obstacles_dir):
            for file in os.listdir(obstacles_dir):
                # 只要是 png 或 jpg 格式的图片,统统加进来
                if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                    # 拼成 "obstacles/文件名.png",这样 find_any_image_gray 就能正确找到路径
                    dynamic_obstacles.append(f"obstacles/{file}")

        if not dynamic_obstacles:
            self.log("提示:images/obstacles/ 文件夹为空或不存在,将只使用 ESC 退回。")
        # 连续尝试 80 次,处理较长的随机过程
        for i in range(80):
            if hasattr(self, "check_pause"): self.check_pause() # 兼容暂停功能
            if not self.is_running:
                return False

            # 1. 终极判断:是不是已经在菜单了?
            if self.is_in_menu():
                self.log(f"成功定位到菜单锚点!(尝试次数: {i + 1})")
                time.sleep(0.5)
                return True

            # 2. 致命错误排查 (检测到显存不足,强制休息 10 分钟)
            if self.find_image_gray("VRAMNE.png", region=self.regions["全界面"], threshold=0.75, fast_mode=True):
                self.log("!!! 严重警告: 检测到显存不足 (VRAMNE.png) 报错!")
                self.log("已禁用强杀游戏进程,停止恢复流程并交由人工处理。")
                return False

            # 3. 动态扫描所有可能的弹窗 / 需要点击的中间图片
            pos_obs = self.find_any_image_gray(dynamic_obstacles, region=self.regions["全界面"], threshold=0.75, fast_mode=True)
            if pos_obs:
                self.log(f"退回途中检测到已知图片/弹窗,点击推进... ({i+1}/80)")
                self.game_click(pos_obs)
                time.sleep(1.5) # 给画面跳转留出动画时间
                continue # 点击后,跳过本轮,不要按 ESC

            # 4. 如果既没进菜单,也没看到特定的图片,说明处于常规界面,按 ESC 退回
            self.log(f"未在主菜单且无已知特定图片,按下 ESC... ({i + 1}/80)")
            self.hw_press("esc")
            time.sleep(1.2) # 给游戏一点动画加载时间

        self.log("80 次动态尝试均未进入菜单,高级退回失败。")
        return False
    # ==========================================
    # --- 图像寻找 ---
    # ==========================================
    def load_template(self, template_path):
        actual_path = get_img_path(template_path)
        cache_key = actual_path

        if cache_key in self.template_cache:
            return self.template_cache[cache_key], actual_path

        tpl = cv2.imread(actual_path, cv2.IMREAD_COLOR)
        if tpl is not None:
            self.template_cache[cache_key] = tpl
        return tpl, actual_path
    def load_template_gray(self, template_path):
        actual_path = get_img_path(template_path)
        cache_key = ("gray", actual_path)
        if not hasattr(self, "template_gray_cache"):
            self.template_gray_cache = {}
        if cache_key in self.template_gray_cache:
            return self.template_gray_cache[cache_key]
        tpl = cv2.imread(actual_path, cv2.IMREAD_GRAYSCALE)
        if tpl is not None:
            self.template_gray_cache[cache_key] = tpl
        return tpl
    def get_images_root_dir(self):
        ext_dir = os.path.join(APP_DIR, "images")
        if os.path.isdir(ext_dir):
            return ext_dir

        int_dir = os.path.join(INTERNAL_DIR, "images")
        if os.path.isdir(int_dir):
            return int_dir

        return None

    def get_template_meta(self):
        images_dir = self.get_images_root_dir()
        meta_data = {}
        if not images_dir:
            return meta_data

        for root, _, files in os.walk(images_dir):
            for file in files:
                if not file.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
                    continue

                path = os.path.join(root, file)
                rel_path = os.path.relpath(path, images_dir).replace("\\", "/")

                try:
                    stat = os.stat(path)
                    meta_data[rel_path] = {
                        "mtime": stat.st_mtime,
                        "size": stat.st_size,
                    }
                except Exception:
                    pass

        return meta_data

    def is_template_cache_valid(self):
        if not os.path.exists(TEMPLATE_CACHE_FILE) or not os.path.exists(TEMPLATE_META_FILE):
            return False

        try:
            with open(TEMPLATE_META_FILE, "r", encoding="utf-8") as f:
                old_meta = json.load(f)
        except Exception:
            return False

        new_meta = self.get_template_meta()
        return old_meta == new_meta

    def build_template_file_cache(self):
        self.log("开始构建模板缓存文件...")
        os.makedirs(CACHE_DIR, exist_ok=True)

        images_dir = self.get_images_root_dir()
        if not images_dir:
            self.log("未找到 images 目录,无法构建模板缓存。")
            return False

        cache_data = {}
        meta_data = self.get_template_meta()

        scales = self.get_scales_to_try(fast_mode=False)

        for rel_path in meta_data.keys():
            img_path = os.path.join(images_dir, rel_path)
            tpl = cv2.imread(img_path, cv2.IMREAD_COLOR)
            if tpl is None:
                continue

            cache_data[rel_path] = {}
            for scale in scales:
                try:
                    if scale == 1.0:
                        scaled = tpl.copy()
                    else:
                        scaled = cv2.resize(tpl, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

                    cache_data[rel_path][str(round(scale, 3))] = scaled
                except Exception:
                    continue

        try:
            with open(TEMPLATE_CACHE_FILE, "wb") as f:
                pickle.dump(cache_data, f, protocol=pickle.HIGHEST_PROTOCOL)

            with open(TEMPLATE_META_FILE, "w", encoding="utf-8") as f:
                json.dump(meta_data, f, ensure_ascii=False, indent=2)

            self.log("模板缓存文件构建完成。")
            return True
        except Exception as e:
            self.log(f"写入模板缓存失败: {e}")
            return False

    def load_template_file_cache(self):
        try:
            with open(TEMPLATE_CACHE_FILE, "rb") as f:
                self.file_template_cache = pickle.load(f)
            self.log("模板缓存文件加载成功。")
            return True
        except Exception as e:
            self.log(f"加载模板缓存失败: {e}")
            self.file_template_cache = {}
            return False

    def prepare_template_cache(self):
        os.makedirs(CACHE_DIR, exist_ok=True)

        if self.is_template_cache_valid():
            if self.load_template_file_cache():
                return

        self.log("模板缓存不存在或已失效,开始后台重建(这可能需要几秒钟)...")
        if self.build_template_file_cache():
            self.template_cache.clear()
            self.scaled_template_cache.clear()
            self.load_template_file_cache()

    def capture_region(self, region=None, mask_areas=None):
        # 【后台化】使用 PrintWindow 后台截图
        if not self.game_hwnd or not win32gui.IsWindow(self.game_hwnd):
            # 兜底：如果窗口句柄失效，回退到原方式
            try:
                if region:
                    x, y, w, h = region
                    bbox = (int(x), int(y), int(x + w), int(y + h))
                    screen = ImageGrab.grab(bbox=bbox, all_screens=True)
                else:
                    screen = ImageGrab.grab(all_screens=True)
            except Exception:
                screen = pyautogui.screenshot(region=region)
            screen_bgr = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)
        else:
            # 获取窗口客户区左上角屏幕坐标，用于 region 裁剪
            wx, wy = 0, 0
            try:
                pt = win32gui.ClientToScreen(self.game_hwnd, (0, 0))
                wx, wy = pt[0], pt[1]
            except Exception:
                pass
            screen_bgr = fh6_backend.capture_window(
                self.game_hwnd, region=region, window_offset=(wx, wy)
            )
            if screen_bgr is None:
                return None

        # 对指定区域打黑块，避免重复识别同一个目标
        if mask_areas:
            for rect in mask_areas:
                try:
                    mx1, my1, mx2, my2 = rect
                    mx1 = max(0, int(mx1))
                    my1 = max(0, int(my1))
                    mx2 = min(screen_bgr.shape[1], int(mx2))
                    my2 = min(screen_bgr.shape[0], int(my2))
                    if mx2 > mx1 and my2 > my1:
                        screen_bgr[my1:my2, mx1:mx2] = 0
                except Exception:
                    pass

        return screen_bgr

    def get_scales_to_try(self, fast_mode=True):
        full_region = self.regions.get("全界面")
        curr_w = full_region[2] if full_region else pyautogui.size()[0]
        # 你的图主要是按 2560 截的,就优先围绕 2560 计算
        primary_base = 2560
        primary_scale = curr_w / primary_base
        scales = []
        def add_scale(s):
            s = round(float(s), 3)
            if 0.45 <= s <= 1.8 and s not in scales:
                scales.append(s)
        # 先加"最可能正确"的比例及其微调
        add_scale(primary_scale)
        add_scale(primary_scale * 0.98)
        add_scale(primary_scale * 1.02)
        add_scale(primary_scale * 0.95)
        add_scale(primary_scale * 1.05)
        add_scale(primary_scale * 0.92)
        add_scale(primary_scale * 1.08)
        # 再兼容其它来源
        for bw in [1920, 1600]:
            s = curr_w / bw
            add_scale(s)
            add_scale(s * 0.98)
            add_scale(s * 1.02)
        # 最后兜底常用比例
        for s in [1.0, 0.95, 1.05, 0.9, 1.1, 0.85, 1.15, 0.8, 0.75, 0.7]:
            add_scale(s)
        if fast_mode:
            return scales[:8]
        return scales

    def get_scaled_template(self, template_path, scale):
        actual_path = get_img_path(template_path)
        images_dir = self.get_images_root_dir()

        if images_dir and os.path.exists(actual_path):
            try:
                rel_key = os.path.relpath(actual_path, images_dir).replace("\\", "/")
            except Exception:
                rel_key = os.path.basename(actual_path)
        else:
            rel_key = os.path.basename(actual_path)

        mem_key = (actual_path, round(scale, 3))
        if mem_key in self.scaled_template_cache:
            return self.scaled_template_cache[mem_key], actual_path

        scale_key = str(round(scale, 3))
        if rel_key in self.file_template_cache:
            tpl = self.file_template_cache[rel_key].get(scale_key)
            if tpl is not None:
                self.scaled_template_cache[mem_key] = tpl
                return tpl, actual_path

        template_orig, actual_path = self.load_template(template_path)
        if template_orig is None:
            return None, actual_path

        try:
            if scale == 1.0:
                tpl = template_orig.copy()
            else:
                tpl = cv2.resize(template_orig, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

            self.scaled_template_cache[mem_key] = tpl
            return tpl, actual_path
        except Exception:
            return None, actual_path

    def find_image_in_screen(self, screen_bgr, template_path, region=None, threshold=0.75, fast_mode=True):
        try:
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)

            for scale in scales_to_try:
                tpl_c, actual_path = self.get_scaled_template(template_path, scale)
                if tpl_c is None:
                    continue

                h, w = tpl_c.shape[:2]
                if h < 5 or w < 5:
                    continue
                if h > screen_bgr.shape[0] or w > screen_bgr.shape[1]:
                    continue

                res = cv2.matchTemplate(screen_bgr, tpl_c, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)

                if max_val >= threshold:
                    pos = (
                        max_loc[0] + w // 2 + (region[0] if region else 0),
                        max_loc[1] + h // 2 + (region[1] if region else 0),
                    )
                    self.last_positions[template_path] = pos
                    # 【新增】:在基础图像查找中增加详细日志返回
                    self.log(f"[ImageMatch] 命中: {template_path} | 得分: {max_val:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                    return pos

            return None

        except Exception as e:
            self.log(f"find_image_in_screen 异常: {e}")
            return None

    def find_image(self, template_path, region=None, threshold=0.75, fast_mode=True):
        if not self.is_running:
            return None

        try:
            screen_bgr = self.capture_region(region)
            return self.find_image_in_screen(
                screen_bgr,
                template_path,
                region=region,
                threshold=threshold,
                fast_mode=fast_mode
            )
        except Exception as e:
            self.log(f"查找图片时发生异常: {e}")
            return None

    def find_any_image(self, image_list, region=None, threshold=MATCH_THRESHOLD, fast_mode=True):
        if not self.is_running:
            return None

        try:
            screen_bgr = self.capture_region(region)
            for img_path in image_list:
                pos = self.find_image_in_screen(
                    screen_bgr,
                    img_path,
                    region=region,
                    threshold=threshold,
                    fast_mode=fast_mode
                )
                if pos:
                    return pos
            return None
        except Exception as e:
            self.log(f"find_any_image 异常: {e}")
            return None

    def find_image_with_element(self, main_path, sub_path, region=None, threshold=0.85, fast_mode=True):
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)
            for scale in scales_to_try:
                # 1. 结合新架构缓存直接读取缩放好的图像
                main_tpl_c, _ = self.get_scaled_template(main_path, scale)
                sub_tpl_c, _ = self.get_scaled_template(sub_path, scale)
                if main_tpl_c is None or sub_tpl_c is None:
                    continue
                h_m, w_m = main_tpl_c.shape[:2]
                if h_m < 5 or w_m < 5 or h_m > screen_bgr.shape[0] or w_m > screen_bgr.shape[1]:
                    continue
                # 2. 一阶匹配:寻找全屏符合的主目标
                res_main = cv2.matchTemplate(screen_bgr, main_tpl_c, cv2.TM_CCOEFF_NORMED)
                loc = np.where(res_main >= threshold)
                checked = set() # 【关键优化】:坐标去重,解决几十万次无效循环造成的卡顿
                for pt in zip(*loc[::-1]):
                    x, y = pt
                    # 过滤相邻 10 个像素内的重复识别点
                    key = (x // 10, y // 10)
                    if key in checked:
                        continue
                    checked.add(key)
                    # 3. 旧代码的核心精髓:在主图区域四周略微扩大 5 像素的范围内找元素
                    sub_roi = screen_bgr[
                        max(0, y - 5):min(screen_bgr.shape[0], y + h_m + 5),
                        max(0, x - 5):min(screen_bgr.shape[1], x + w_m + 5),
                    ]
                    if sub_tpl_c.shape[0] > sub_roi.shape[0] or sub_tpl_c.shape[1] > sub_roi.shape[1]:
                        continue
                                        # 4. 二阶匹配:验证提取范围内是否包含子元素
                    res_sub = cv2.matchTemplate(sub_roi, sub_tpl_c, cv2.TM_CCOEFF_NORMED)
                    sub_score = cv2.minMaxLoc(res_sub)[1]
                    if sub_score >= threshold:
                        # 【新增】:在组合图像查找中增加详细日志返回
                        main_score = res_main[y, x]
                        self.log(f"[ComboMatch] 命中: {main_path}+{sub_path} | 主图得分: {main_score:.3f} | 元素得分: {sub_score:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                        return (
                            x + w_m // 2 + (region[0] if region else 0),
                            y + h_m // 2 + (region[1] if region else 0),
                        )
            return None
        except Exception as e:
            self.log(f"find_image_with_element 异常: {e}")
            return None
    def find_image_with_element_stable(
        self,
        main_path,
        sub_path,
        region=None,
        main_threshold=0.60,
        verify_threshold=0.72,
        sub_threshold=0.70,
        max_candidates=15
    ):
        if not self.is_running:
            return None

        try:
            screen = pyautogui.screenshot(region=region)
            screen_gray = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2GRAY)

            main_tpl = self.load_template_gray(main_path)
            sub_tpl = self.load_template_gray(sub_path)

            if main_tpl is None or sub_tpl is None:
                return None

            h_m, w_m = main_tpl.shape[:2]
            h_s, w_s = sub_tpl.shape[:2]

            if h_m > screen_gray.shape[0] or w_m > screen_gray.shape[1]:
                return None

            res_main = cv2.matchTemplate(screen_gray, main_tpl, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(res_main >= main_threshold)

            if len(xs) == 0:
                return None

            candidates = [(float(res_main[y, x]), x, y) for x, y in zip(xs, ys)]
            candidates.sort(key=lambda t: t[0], reverse=True)

            checked = set()
            checked_count = 0

            for main_score, x, y in candidates:
                key = (x // 8, y // 8)
                if key in checked:
                    continue
                checked.add(key)

                checked_count += 1
                if checked_count > max_candidates:
                    break

                pad = 8
                x1 = max(0, x - pad)
                y1 = max(0, y - pad)
                x2 = min(screen_gray.shape[1], x + w_m + pad)
                y2 = min(screen_gray.shape[0], y + h_m + pad)

                sub_roi = screen_gray[y1:y2, x1:x2]
                if sub_roi.shape[0] < h_s or sub_roi.shape[1] < w_s:
                    continue

                res_sub = cv2.matchTemplate(sub_roi, sub_tpl, cv2.TM_CCOEFF_NORMED)
                sub_score = cv2.minMaxLoc(res_sub)[1]

                if main_score >= verify_threshold and sub_score >= sub_threshold:
                    cx = x + w_m // 2
                    cy = y + h_m // 2
                    if region:
                        cx += region[0]
                        cy += region[1]
                    # 【新增】:打印稳定版组合匹配的详细得分
                    self.log(f"[StableMatch] 命中: {main_path}+{sub_path} | 主图: {main_score:.3f} (需>{verify_threshold}) | 元素: {sub_score:.3f} (需>{sub_threshold})")
                    return (cx, cy)

            return None

        except Exception as e:
            self.log(f"find_image_with_element_stable 识别报错: {e}")
            return None
    def find_image_with_element_multi(self, main_path, sub_path, region=None, fast_mode=True,
        main_threshold=0.60, like_threshold=0.75, final_threshold=0.72, mask_areas=None):
        if not self.is_running:
            return None

        try:
            screen_bgr = self.capture_region(region, mask_areas=mask_areas)
            screen_gray = self.to_gray_image(screen_bgr)
            screen_edge = self.to_edge_image(screen_bgr)

            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)

            for scale in scales_to_try:
                main_tpl_c, _ = self.get_scaled_template(main_path, scale)
                sub_tpl_c, _ = self.get_scaled_template(sub_path, scale)

                if main_tpl_c is None or sub_tpl_c is None:
                    continue

                main_tpl_gray = self.to_gray_image(main_tpl_c)
                main_tpl_edge = self.to_edge_image(main_tpl_c)

                h_m, w_m = main_tpl_c.shape[:2]
                if h_m < 5 or w_m < 5:
                    continue
                if h_m > screen_bgr.shape[0] or w_m > screen_bgr.shape[1]:
                    continue

                # 用彩色主模板先找候选,门槛放低
                res_main = cv2.matchTemplate(screen_bgr, main_tpl_c, cv2.TM_CCOEFF_NORMED)
                # 不再只靠 >= main_threshold 硬切,改成取前 N 个高分候选
                flat = res_main.ravel()
                if flat.size == 0:
                    continue
                top_k = min(80, flat.size)   # 可调,先 80
                idxs = np.argpartition(flat, -top_k)[-top_k:]
                points = []
                for idx in idxs:
                    y, x = np.unravel_index(idx, res_main.shape)
                    score = res_main[y, x]
                    # 给一个很低的底线,防止垃圾点太多
                    if score < max(0.55, main_threshold - 0.12):
                        continue
                    points.append((x, y, score))
                # 先按 y、x 排序,保证视觉顺序
                points.sort(key=lambda p: (p[1], p[0]))

                checked_points = set()

                for pt in points:
                    x, y, base_score = pt

                    # 去重,避免同一辆车计算多次
                    key = (x // 10, y // 10)
                    if key in checked_points:
                        continue
                    checked_points.add(key)

                    roi_bgr = screen_bgr[y:y + h_m, x:x + w_m]
                    roi_gray = screen_gray[y:y + h_m, x:x + w_m]
                    roi_edge = screen_edge[y:y + h_m, x:x + w_m]

                    if roi_bgr.shape[:2] != main_tpl_c.shape[:2]:
                        continue

                    # 四维打分系统 (抗 HDR 核心)
                    color_score = self.match_template_score(roi_bgr, main_tpl_c)
                    gray_score = self.match_template_score(roi_gray, main_tpl_gray)
                    edge_score = self.match_template_score(roi_edge, main_tpl_edge)

                    roi_center = self.crop_center_ratio(roi_bgr, ratio=0.6)
                    tpl_center = self.crop_center_ratio(main_tpl_c, ratio=0.6)
                    center_score = self.match_template_score(roi_center, tpl_center)

                    # 标签匹配 (NEW 标签或作者点赞标签)
                    pad = 5
                    sub_roi = screen_bgr[
                        max(0, y - pad):min(screen_bgr.shape[0], y + h_m + pad),
                        max(0, x - pad):min(screen_bgr.shape[1], x + w_m + pad),
                    ]
                    like_score = self.match_template_score(sub_roi, sub_tpl_c)

                    if like_score < like_threshold:
                        continue

                    # 综合计算总分
                    final_score = (
                        color_score * 0.30 +
                        gray_score * 0.20 +
                        edge_score * 0.20 +
                        center_score * 0.15 +
                        like_score * 0.15
                    )

                    curr_pos = (
                        x + w_m // 2 + (region[0] if region else 0),
                        y + h_m // 2 + (region[1] if region else 0),
                    )

                    # 只要及格,立刻返回(因为已经排过序了,第一个及格的一定是左上角的第一个目标)
                    if final_score >= final_threshold:
                        self.log(
                            f"[MultiMatch] 锁定目标: {main_path}+{sub_path} | "
                            f"综合: {final_score:.3f} | 彩色: {color_score:.3f} | "
                            f"灰度: {gray_score:.3f} | 边缘: {edge_score:.3f} | "
                            f"中心: {center_score:.3f} | 标签: {like_score:.3f}"
                        )
                        return curr_pos

            return None

        except Exception as e:
            self.log(f"find_image_with_element_multi 异常: {e}")
            return None

    def find_image_with_element_fast(self, main_path, sub_path, region=None, threshold=0.70, sub_threshold=0.70):
        if not self.is_running:
            return None

        try:
            screen = pyautogui.screenshot(region=region)
            screen_gray = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2GRAY)

            main_tpl = self.load_template_gray(main_path)
            sub_tpl = self.load_template_gray(sub_path)

            if main_tpl is None or sub_tpl is None:
                return None

            h_m, w_m = main_tpl.shape[:2]
            h_s, w_s = sub_tpl.shape[:2]

            if h_m > screen_gray.shape[0] or w_m > screen_gray.shape[1]:
                return None

            res_main = cv2.matchTemplate(screen_gray, main_tpl, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res_main >= threshold)

            checked = set()

            for pt in zip(*loc[::-1]):
                x, y = pt

                # 去重,避免相邻重复点太多
                key = (x // 10, y // 10)
                if key in checked:
                    continue
                checked.add(key)

                x1 = max(0, x - 5)
                y1 = max(0, y - 5)
                x2 = min(screen_gray.shape[1], x + w_m + 5)
                y2 = min(screen_gray.shape[0], y + h_m + 5)

                sub_roi = screen_gray[y1:y2, x1:x2]

                if sub_roi.shape[0] < h_s or sub_roi.shape[1] < w_s:
                    continue

                res_sub = cv2.matchTemplate(sub_roi, sub_tpl, cv2.TM_CCOEFF_NORMED)
                _, max_val_sub, _, _ = cv2.minMaxLoc(res_sub)

                if max_val_sub >= sub_threshold:
                    cx = x + w_m // 2
                    cy = y + h_m // 2
                    if region:
                        cx += region[0]
                        cy += region[1]
                    # 【新增】:打印快速匹配模式得分
                    main_score = res_main[y, x]
                    self.log(f"[FastMatch] 命中: {main_path}+{sub_path} | 主图: {main_score:.3f} (需>{threshold}) | 元素: {max_val_sub:.3f} (需>{sub_threshold})")
                    return (cx, cy)

            return None

        except Exception as e:
            self.log(f"find_image_with_element_fast 异常: {e}")
            return None

    def wait_for_image_with_element_multi(self, main_path, sub_path, region=None, fast_mode=True,
        main_threshold=0.60, like_threshold=0.75,
        final_threshold=0.72, timeout=30, interval=0.4):
        start = time.time()

        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_with_element_multi(
                main_path=main_path,
                sub_path=sub_path,
                region=region,
                fast_mode=fast_mode,
                main_threshold=main_threshold,
                like_threshold=like_threshold,
                final_threshold=final_threshold
            )
            if pos:
                return pos

            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)

        return None

    def load_template_transparent(self, template_path):
        """专门加载带有 Alpha 透明通道的图片"""
        actual_path = get_img_path(template_path)
        cache_key = ("transparent", actual_path)
        if not hasattr(self, "template_transparent_cache"):
            self.template_transparent_cache = {}
        if cache_key in self.template_transparent_cache:
            return self.template_transparent_cache[cache_key]

        # 注意这里的 cv2.IMREAD_UNCHANGED,它会保留透明通道 (BGRA)
        tpl = cv2.imread(actual_path, cv2.IMREAD_UNCHANGED)
        if tpl is not None:
            self.template_transparent_cache[cache_key] = tpl
        return tpl
    def find_image_transparent(self, template_path, region=None, threshold=0.70, fast_mode=True):
        """带透明通道的匹配:彻底无视透明背景,只匹配图像主体"""
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            tpl_bgra = self.load_template_transparent(template_path)

            if tpl_bgra is None:
                return None
            # 如果图片没有透明通道(不是4通道),降级为普通匹配
            if tpl_bgra.shape[2] != 4:
                return self.find_image_in_screen(screen_bgr, template_path, region, threshold, fast_mode)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)
            for scale in scales_to_try:
                # 对带有透明通道的原图进行缩放
                if scale == 1.0:
                    tpl_scaled = tpl_bgra.copy()
                else:
                    tpl_scaled = cv2.resize(tpl_bgra, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                h, w = tpl_scaled.shape[:2]
                if h < 5 or w < 5 or h > screen_bgr.shape[0] or w > screen_bgr.shape[1]:
                    continue
                # 分离出 BGR 色彩层 和 Alpha 透明遮罩层
                tpl_bgr = tpl_scaled[:, :, :3]
                alpha_mask = tpl_scaled[:, :, 3]
                                # 核心魔法:带 mask 的匹配!透明区域不参与算分!
                res = cv2.matchTemplate(screen_bgr, tpl_bgr, cv2.TM_CCOEFF_NORMED, mask=alpha_mask)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val >= threshold:
                    # 【新增】:带透明通道的匹配日志
                    self.log(f"[AlphaMatch] 命中(无视背景): {template_path} | 得分: {max_val:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                    return (
                        max_loc[0] + w // 2 + (region[0] if region else 0),
                        max_loc[1] + h // 2 + (region[1] if region else 0),
                    )
            return None
        except Exception as e:
            self.log(f"find_image_transparent 异常: {e}")
            return None
    def wait_for_image_transparent(self, template_path, region=None, threshold=0.70, timeout=30, interval=0.4, fast_mode=True):
        """等待带有透明背景的图片"""
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_transparent(template_path, region, threshold, fast_mode)
            if pos:
                return pos
            time.sleep(interval)
        return None
    def wait_for_image_with_element_stable(
        self,
        main_path,
        sub_path,
        region=None,
        main_threshold=0.60,
        verify_threshold=0.72,
        sub_threshold=0.70,
        max_candidates=15,
        timeout=3,
        interval=0.2
    ):
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_with_element_stable(
                main_path=main_path,
                sub_path=sub_path,
                region=region,
                main_threshold=main_threshold,
                verify_threshold=verify_threshold,
                sub_threshold=sub_threshold,
                max_candidates=max_candidates
            )
            if pos:
                return pos
            time.sleep(interval)
        return None
    def wait_for_image_with_element_fast(
        self,
        main_path,
        sub_path,
        region=None,
        threshold=0.70,
        sub_threshold=0.70,
        timeout=4,
        interval=0.25
    ):
        start = time.time()

        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_with_element_fast(
                main_path=main_path,
                sub_path=sub_path,
                region=region,
                threshold=threshold,
                sub_threshold=sub_threshold
            )
            if pos:
                return pos

            time.sleep(interval)

        return None

    # ==========================================
    # --- 【终极安全锁 V5.1】:排他 + 右下角调校精准狙击 + 强制从左到右 ---
    # ==========================================
    def find_image_ultimate_safe(self, main_path, anti_path, region=None, main_threshold=0.80, anti_threshold=0.65, mask_areas=None):
        if not self.is_running: return None
        try:
            screen_bgr = self.capture_region(region, mask_areas=mask_areas)
            screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)

            scales_to_try = self.get_scales_to_try(fast_mode=True)

            for scale in scales_to_try:
                main_tpl_bgr, _ = self.get_scaled_template(main_path, scale)
                anti_tpl_bgr = None
                if anti_path:
                    anti_tpl_bgr, _ = self.get_scaled_template(anti_path, scale)
                if main_tpl_bgr is None:
                    continue
                if anti_path and anti_tpl_bgr is None:
                    continue

                main_tpl_gray = cv2.cvtColor(main_tpl_bgr, cv2.COLOR_BGR2GRAY)
                h_m, w_m = main_tpl_bgr.shape[:2]
                h_a, w_a = anti_tpl_bgr.shape[:2]

                if h_m < 10 or w_m < 10 or h_m > screen_bgr.shape[0] or w_m > screen_bgr.shape[1]:
                    continue

                # 1. 基础彩色初筛
                res_main = cv2.matchTemplate(screen_bgr, main_tpl_bgr, cv2.TM_CCOEFF_NORMED)
                loc = np.where(res_main >= main_threshold)


                points = list(zip(*loc[::-1]))
                # 强制按 X 坐标(从左到右)优先排序,无视上下排
                points.sort(key=lambda p: (p[1] // 50, p[0]))

                checked = set()
                for pt in points:
                    x, y = pt
                    if (x // 10, y // 10) in checked: continue
                    checked.add((x // 10, y // 10))

                    base_score = res_main[y, x]

                    roi_bgr = screen_bgr[y:y+h_m, x:x+w_m]
                    roi_gray = screen_gray[y:y+h_m, x:x+w_m]
                    if roi_bgr.shape[:2] != main_tpl_bgr.shape[:2]: continue

                    # ==================================
                    # 防线 1: 排他校验
                    # ==================================
                    if anti_path and anti_tpl_bgr is not None:
                        h_a, w_a = anti_tpl_bgr.shape[:2]
                        pad_anti = 10
                        roi_y1, roi_y2 = max(0, y - pad_anti), min(screen_bgr.shape[0], y + h_m + pad_anti)
                        roi_x1, roi_x2 = max(0, x - pad_anti), min(screen_bgr.shape[1], x + w_m + pad_anti)
                        anti_roi = screen_bgr[roi_y1:roi_y2, roi_x1:roi_x2]
                        if anti_roi.shape[0] >= h_a and anti_roi.shape[1] >= w_a:
                            res_anti = cv2.matchTemplate(anti_roi, anti_tpl_bgr, cv2.TM_CCOEFF_NORMED)
                            _, anti_score, _, _ = cv2.minMaxLoc(res_anti)
                            if anti_score >= anti_threshold:
                                self.log(f"[排他拦截]: 发现排除图 ({anti_score:.2f}),放弃该目标。")
                                continue

                    # ==================================
                    # 防线 2: 顶部文字
                    # ==================================
                    top_h = int(h_m * 0.25)
                    tpl_top = main_tpl_gray[:top_h, :]

                    score_top = 0.0
                    pad_slide = 5
                    if top_h > pad_slide*2 and w_m > pad_slide*2:
                        tpl_top_core = tpl_top[pad_slide:-pad_slide, pad_slide:-pad_slide]
                        search_top = roi_gray[:int(h_m * 0.35), :]
                        if search_top.shape[0] >= tpl_top_core.shape[0] and search_top.shape[1] >= tpl_top_core.shape[1]:
                            res_top = cv2.matchTemplate(search_top, tpl_top_core, cv2.TM_CCOEFF_NORMED)
                            _, score_top, _, _ = cv2.minMaxLoc(res_top)

                    # ==================================
                    # 防线 3: 【右下角】
                    # ==================================
                    bottom_h = int(h_m * 0.25)
                    right_w = int(w_m * 0.35)
                    tpl_pi_box = main_tpl_bgr[h_m - bottom_h:, w_m - right_w:]

                    score_bot = 0.0
                    if bottom_h > pad_slide*2 and right_w > pad_slide*2:
                        tpl_pi_core = tpl_pi_box[pad_slide:-pad_slide, pad_slide:-pad_slide]
                        search_y1 = h_m - int(h_m * 0.35)
                        search_x1 = w_m - int(w_m * 0.45)
                        search_bot = roi_bgr[search_y1:, search_x1:]

                        if search_bot.shape[0] >= tpl_pi_core.shape[0] and search_bot.shape[1] >= tpl_pi_core.shape[1]:
                            res_bot = cv2.matchTemplate(search_bot, tpl_pi_core, cv2.TM_CCOEFF_NORMED)
                            _, score_bot, _, _ = cv2.minMaxLoc(res_bot)

                    if base_score >= 0.76 and score_top >= 0.75 and score_bot >= 0.85:
                        self.log(f"[终极安全-通过]: 锁定目标!总分:{base_score:.3f} | 顶部车名:{score_top:.2f} | 右下调校:{score_bot:.2f}")
                        return (x + w_m // 2 + (region[0] if region else 0), y + h_m // 2 + (region[1] if region else 0))
                    else:
                        pass # 静默拦截,继续寻找下一个坐标

            return None
        except Exception as e:
            self.log(f"ultimate_safe 异常: {e}")
            return None
    def wait_for_image_ultimate_safe(self, main_path, anti_path, region=None, main_threshold=0.80, anti_threshold=0.65, timeout=3, interval=0.2, mask_areas=None):
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_ultimate_safe(main_path, anti_path, region, main_threshold, anti_threshold, mask_areas=mask_areas)
            if pos: return pos
            time.sleep(interval)
        return None

    def find_new_tag_by_color(self, screen_bgr, tag_tpl, scale):
        try:
            h_s, w_s = screen_bgr.shape[:2]
            hsv = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2HSV)
            # "全新"标签是高亮黄色,先用颜色把候选范围从整屏压到很小。
            mask = cv2.inRange(hsv, np.array([22, 80, 160]), np.array([42, 255, 255]))
            kernel = np.ones((3, 3), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            candidates = []
            tag_h, tag_w = tag_tpl.shape[:2]
            card_w = max(180, int(267 * scale))
            card_h = max(130, int(198 * scale))

            for cnt in contours:
                x, y, w, h = cv2.boundingRect(cnt)
                area = w * h
                if area < 80 or area > 6000:
                    continue
                if w < 12 or h < 8 or w > 90 or h > 70:
                    continue
                if w / max(h, 1) < 0.6:
                    continue

                pad = max(8, int(12 * scale))
                x1 = max(0, x - pad)
                y1 = max(0, y - pad)
                x2 = min(w_s, x + w + pad)
                y2 = min(h_s, y + h + pad)
                tag_roi = screen_bgr[y1:y2, x1:x2]
                tag_score = self.match_template_score(tag_roi, tag_tpl)
                if tag_score < 0.52:
                    continue

                card_x = int((x + w / 2) - card_w * 0.78)
                card_y = int((y + h / 2) - card_h * 0.78)
                card_x = max(0, min(card_x, w_s - card_w))
                card_y = max(0, min(card_y, h_s - card_h))
                center_x = card_x + card_w // 2
                center_y = card_y + card_h // 2

                candidates.append((tag_score, card_x, card_y, card_w, card_h, center_x, center_y, x, y, w, h))

            if not candidates:
                return []

            candidates.sort(key=lambda item: (-item[0], item[8], item[7]))
            return candidates
        except Exception as e:
            self.log(f"find_new_tag_by_color 异常: {e}")
            return []

    def validate_new_tag_grid_fallback(self, screen_bgr, tx, ty, tw, th):
        try:
            h_s, w_s = screen_bgr.shape[:2]
            if tx < int(w_s * 0.20) or ty < int(h_s * 0.18) or ty > int(h_s * 0.92):
                return None

            # 标签左上方应该是白色车辆卡片主体。
            wx1 = max(0, tx - 145)
            wy1 = max(0, ty - 105)
            wx2 = max(0, tx - 12)
            wy2 = max(0, ty - 8)
            white_roi = screen_bgr[wy1:wy2, wx1:wx2]
            if white_roi.size == 0:
                return None
            white_mask = (
                (white_roi[:, :, 0] > 185) &
                (white_roi[:, :, 1] > 185) &
                (white_roi[:, :, 2] > 185)
            )
            white_ratio = float(np.count_nonzero(white_mask)) / max(1, white_mask.size)
            if white_ratio < 0.18:
                return None

            # 标签左下方通常能看到橙色车型信息条或等级条;标签贴近底部时要向上覆盖一点。
            ox1 = max(0, tx - 190)
            oy1 = max(0, ty - 12)
            ox2 = min(w_s, tx + 85)
            oy2 = min(h_s, ty + th + 44)
            orange_roi = screen_bgr[oy1:oy2, ox1:ox2]
            if orange_roi.size == 0:
                return None
            hsv = cv2.cvtColor(orange_roi, cv2.COLOR_BGR2HSV)
            orange_mask = cv2.inRange(hsv, np.array([8, 80, 140]), np.array([32, 255, 255]))
            orange_ratio = float(np.count_nonzero(orange_mask)) / max(1, orange_mask.size)
            if orange_ratio < 0.035:
                return None

            click_x = max(0, min(w_s - 1, tx - 60))
            click_y = max(0, min(h_s - 1, ty - 42))
            return click_x, click_y, white_ratio, orange_ratio
        except Exception as e:
            self.log(f"validate_new_tag_grid_fallback 异常: {e}")
            return None

    def find_new_consumable_car_strict(self, region=None):
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            scales = []
            for s in [1.0, 0.98, 1.02, 0.95, 1.05]:
                if s not in scales:
                    scales.append(s)
            for s in self.get_scales_to_try(fast_mode=False):
                if s not in scales:
                    scales.append(s)

            for scale in scales:
                main_tpl, _ = self.get_scaled_template("newCC.png", scale)
                tag_tpl, _ = self.get_scaled_template("newcartag.png", scale)
                class_tpl, _ = self.get_scaled_template("classB600.png", scale)
                if main_tpl is None or tag_tpl is None or class_tpl is None:
                    continue

                h_m, w_m = main_tpl.shape[:2]
                h_t, w_t = tag_tpl.shape[:2]
                h_c, w_c = class_tpl.shape[:2]
                if h_m < 20 or w_m < 20 or h_m > screen_bgr.shape[0] or w_m > screen_bgr.shape[1]:
                    continue
                if h_t < 8 or w_t < 12 or h_t > screen_bgr.shape[0] or w_t > screen_bgr.shape[1]:
                    continue
                if h_c < 8 or w_c < 20 or h_c > screen_bgr.shape[0] or w_c > screen_bgr.shape[1]:
                    continue

                tag_res = cv2.matchTemplate(screen_bgr, tag_tpl, cv2.TM_CCOEFF_NORMED)
                loc = np.where(tag_res >= 0.72)
                tag_points = list(zip(*loc[::-1]))
                if not tag_points:
                    _, max_tag, _, max_loc = cv2.minMaxLoc(tag_res)
                    if max_tag >= 0.64:
                        tag_points = [max_loc]

                checked_tags = set()
                tag_candidates = []
                for tx, ty in tag_points:
                    if tx < int(screen_bgr.shape[1] * 0.20) or ty < int(screen_bgr.shape[0] * 0.18) or ty > int(screen_bgr.shape[0] * 0.90):
                        continue
                    tag_key = (tx // 18, ty // 14)
                    if tag_key in checked_tags:
                        continue
                    checked_tags.add(tag_key)
                    tag_candidates.append((ty, tx, float(tag_res[ty, tx])))

                tag_candidates.sort()
                if not tag_candidates:
                    self.log(f"[StrictCar] 缩放 {scale:.3f} 未找到全新标签候选。")
                    continue

                for ty, tx, tag_score in tag_candidates:
                    # 验证 2:全新标签下方/左下方必须能找到目标等级 B600。
                    cx1 = max(0, int(tx - w_c * 1.45))
                    cy1 = max(0, int(ty - h_c * 0.25))
                    cx2 = min(screen_bgr.shape[1], int(tx + w_t + w_c * 0.40))
                    cy2 = min(screen_bgr.shape[0], int(ty + h_t + h_c * 1.70))
                    class_search = screen_bgr[cy1:cy2, cx1:cx2]
                    if class_search.shape[0] < h_c or class_search.shape[1] < w_c:
                        continue

                    class_res = cv2.matchTemplate(class_search, class_tpl, cv2.TM_CCOEFF_NORMED)
                    _, class_score, _, class_loc = cv2.minMaxLoc(class_res)
                    if class_score < 0.58:
                        self.log(
                            f"[StrictCar] 全新通过但等级不符: NEW:{tag_score:.3f} "
                            f"B600:{class_score:.3f} 缩放:{scale:.3f}"
                        )
                        continue

                    class_x = cx1 + class_loc[0]
                    class_y = cy1 + class_loc[1]

                    # 验证 3:以全新标签为锚点,只向左上方缩放搜索目标车辆卡片。
                    sx1 = max(0, int(tx - w_m * 1.12))
                    sy1 = max(0, int(ty - h_m * 1.08))
                    sx2 = min(screen_bgr.shape[1], int(tx - w_m * 0.05 + w_t))
                    sy2 = min(screen_bgr.shape[0], int(ty - h_m * 0.05 + h_t))
                    search = screen_bgr[sy1:sy2, sx1:sx2]
                    if search.shape[0] < h_m or search.shape[1] < w_m:
                        continue

                    near_res = cv2.matchTemplate(search, main_tpl, cv2.TM_CCOEFF_NORMED)
                    _, near_score, _, near_loc = cv2.minMaxLoc(near_res)
                    card_x = sx1 + near_loc[0]
                    card_y = sy1 + near_loc[1]

                    tag_rel_x = tx - card_x
                    tag_rel_y = ty - card_y
                    if not (int(w_m * 0.62) <= tag_rel_x <= int(w_m * 1.08) and int(h_m * 0.55) <= tag_rel_y <= int(h_m * 1.08)):
                        self.log(
                            f"[StrictCar] 标签附近目标车位置不符: NEW:{tag_score:.3f} "
                            f"近邻:{near_score:.3f} 相对:({tag_rel_x},{tag_rel_y}) 缩放:{scale:.3f}"
                        )
                        continue

                    if near_score >= 0.56:
                        self.log(
                            f"[StrictCar] 全新+B600+目标车通过: NEW:{tag_score:.3f} B600:{class_score:.3f} "
                            f"目标:{near_score:.3f} 标签相对:({tag_rel_x},{tag_rel_y}) "
                            f"等级:({class_x},{class_y}) 缩放:{scale:.3f}"
                        )
                        return (card_x + w_m // 2 + (region[0] if region else 0), card_y + h_m // 2 + (region[1] if region else 0))

                    self.log(
                        f"[StrictCar] 标签附近目标车分数不足: NEW:{tag_score:.3f} "
                        f"目标:{near_score:.3f} 相对:({tag_rel_x},{tag_rel_y}) 缩放:{scale:.3f}"
                    )

            return None
        except Exception as e:
            self.log(f"find_new_consumable_car_strict 异常: {e}")
            return None

    def wait_for_new_consumable_car_strict(self, timeout=3, interval=0.2):
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_new_consumable_car_strict(region=self.regions["全界面"])
            if pos:
                return pos
            time.sleep(interval)
        return None

    def find_image_smart(self, template_path, primary_region=None, fallback_region=None, threshold=0.75, fast_mode=True):
        if primary_region:
            pos = self.find_image(template_path, region=primary_region, threshold=threshold, fast_mode=fast_mode)
            if pos:
                return pos

        if fallback_region:
            return self.find_image(template_path, region=fallback_region, threshold=threshold, fast_mode=fast_mode)

        return None
    def to_gray_image(self, img):
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    def to_edge_image(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        edge = cv2.Canny(blur, 50, 150)
        return edge
    def crop_center_ratio(self, img, ratio=0.6):
        h, w = img.shape[:2]
        ch = int(h * ratio)
        cw = int(w * ratio)
        y1 = max(0, (h - ch) // 2)
        x1 = max(0, (w - cw) // 2)
        return img[y1:y1 + ch, x1:x1 + cw]
    def find_image_gray(self, template_path, region=None, threshold=0.75, fast_mode=True, invert_mode=False):
        """
        纯灰度UI查找,支持多分辨率缩放 + 可选翻转模式
        参数:
            template_path (str): 模板图片路径
            region (tuple|list|None): 搜索区域,格式通常为 (x, y, w, h),None 表示全屏/默认区域
            threshold (float): 匹配阈值,范围通常 0~1,越高越严格
            fast_mode (bool): 是否使用快速缩放搜索模式,True=较少缩放比,False=更多缩放比
            invert_mode (bool): 是否启用翻转模式,True 时会同时匹配原图和反相图(白底黑字 / 黑底白字都能识别)
        返回:
            tuple|None:
                - 找到时返回匹配中心点坐标 (x, y)
                - 找不到返回 None
        """
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)

            # 【新增】模板只读取一次,避免每个 scale 都重复加载
            tpl_gray_raw = self.load_template_gray(template_path)
            if tpl_gray_raw is None:
                return None

            for scale in scales_to_try:
                # 【改动】从原始模板复制,避免反复 resize 污染
                tpl_gray = tpl_gray_raw
                if scale != 1.0:
                    tpl_gray = cv2.resize(tpl_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

                h, w = tpl_gray.shape[:2]
                if h < 5 or w < 5 or h > screen_gray.shape[0] or w > screen_gray.shape[1]:
                    continue

                # ==============================
                # 原图匹配
                # ==============================
                res = cv2.matchTemplate(screen_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val >= threshold:
                    self.log(f"[GrayMatch] 命中: {template_path} | 模式: 原图 | 灰度得分: {max_val:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                    return (
                        max_loc[0] + w // 2 + (region[0] if region else 0),
                        max_loc[1] + h // 2 + (region[1] if region else 0),
                    )

                # ==============================
                # 【新增】翻转模式:反相模板匹配
                # ==============================
                if invert_mode:
                    tpl_inv = 255 - tpl_gray
                    res_inv = cv2.matchTemplate(screen_gray, tpl_inv, cv2.TM_CCOEFF_NORMED)
                    _, max_val_inv, _, max_loc_inv = cv2.minMaxLoc(res_inv)
                    if max_val_inv >= threshold:
                        self.log(f"[GrayMatch] 命中: {template_path} | 模式: 反相 | 灰度得分: {max_val_inv:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                        return (
                            max_loc_inv[0] + w // 2 + (region[0] if region else 0),
                            max_loc_inv[1] + h // 2 + (region[1] if region else 0),
                        )

            return None
        except Exception as e:
            self.log(f"find_image_gray 异常: {e}")
            return None
    def find_any_image_gray(self, image_list, region=None, threshold=0.75, fast_mode=True, invert_mode=False):
        """
        纯灰度多图查找,支持多分辨率缩放 + 可选翻转模式
        参数:
            image_list (list): 模板图片路径列表,如 ["a.png", "b.png", "c.png"]
            region (tuple|list|None): 搜索区域,格式通常为 (x, y, w, h),None 表示全屏/默认区域
            threshold (float): 匹配阈值,范围通常 0~1,越高越严格
            fast_mode (bool): 是否使用快速缩放搜索模式,True=较少缩放比,False=更多缩放比
            invert_mode (bool): 是否启用翻转模式,True 时会同时匹配原图和反相图(白底黑字 / 黑底白字都能识别)
        返回:
            tuple|None:
                - 找到任意一张时返回匹配中心点坐标 (x, y)
                - 都找不到返回 None
        """
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)

            for img_path in image_list:
                # 【新增】模板只读取一次
                tpl_gray_raw = self.load_template_gray(img_path)
                if tpl_gray_raw is None:
                    continue

                for scale in scales_to_try:
                    # 【改动】从原始模板复制
                    tpl_gray = tpl_gray_raw
                    if scale != 1.0:
                        tpl_gray = cv2.resize(tpl_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

                    h, w = tpl_gray.shape[:2]
                    if h < 5 or w < 5 or h > screen_gray.shape[0] or w > screen_gray.shape[1]:
                        continue

                    # ==============================
                    # 原图匹配
                    # ==============================
                    res = cv2.matchTemplate(screen_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(res)
                    if max_val >= threshold:
                        self.log(f"[GrayMatchAny] 命中: {img_path} | 模式: 原图 | 灰度得分: {max_val:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                        return (
                            max_loc[0] + w // 2 + (region[0] if region else 0),
                            max_loc[1] + h // 2 + (region[1] if region else 0),
                        )

                    # ==============================
                    # 【新增】翻转模式:反相模板匹配
                    # ==============================
                    if invert_mode:
                        tpl_inv = 255 - tpl_gray
                        res_inv = cv2.matchTemplate(screen_gray, tpl_inv, cv2.TM_CCOEFF_NORMED)
                        _, max_val_inv, _, max_loc_inv = cv2.minMaxLoc(res_inv)
                        if max_val_inv >= threshold:
                            self.log(f"[GrayMatchAny] 命中: {img_path} | 模式: 反相 | 灰度得分: {max_val_inv:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                            return (
                                max_loc_inv[0] + w // 2 + (region[0] if region else 0),
                                max_loc_inv[1] + h // 2 + (region[1] if region else 0),
                            )

            return None
        except Exception as e:
            self.log(f"find_any_image_gray 异常: {e}")
            return None

    def wait_for_any_image_gray(self, image_list, region=None, threshold=0.75, timeout=30, interval=0.3, fast_mode=True, invert_mode=False):
        """
        等待多张灰度图中的任意一张出现
        参数:
            image_list (list): 模板图片路径列表,如 ["a.png", "b.png", "c.png"]
            region (tuple|list|None): 搜索区域,格式通常为 (x, y, w, h),None 表示全屏/默认区域
            threshold (float): 匹配阈值,范围通常 0~1,越高越严格
            timeout (int|float): 最长等待时间,单位秒
            interval (int|float): 每次检测失败后的等待间隔,单位秒
            fast_mode (bool): 是否使用快速缩放搜索模式,True=较少缩放比,False=更多缩放比
            invert_mode (bool): 是否启用翻转模式,True 时会同时匹配原图和反相图
        返回:
            tuple|None:
                - 超时前找到时返回匹配中心点坐标 (x, y)
                - 超时未找到返回 None
        """
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_any_image_gray(
                image_list,
                region=region,
                threshold=threshold,
                fast_mode=fast_mode,
                invert_mode=invert_mode   # 【新增】
            )
            if pos:
                return pos

            # 安全等待机制,防止卡死
            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)
        return None
    def wait_for_image_gray(self, template_path, region=None, threshold=0.75, timeout=30, interval=0.3, fast_mode=True, invert_mode=False):
        """
        等待单张灰度图出现
        参数:
            template_path (str): 模板图片路径
            region (tuple|list|None): 搜索区域,格式通常为 (x, y, w, h),None 表示全屏/默认区域
            threshold (float): 匹配阈值,范围通常 0~1,越高越严格
            timeout (int|float): 最长等待时间,单位秒
            interval (int|float): 每次检测失败后的等待间隔,单位秒
            fast_mode (bool): 是否使用快速缩放搜索模式,True=较少缩放比,False=更多缩放比
            invert_mode (bool): 是否启用翻转模式,True 时会同时匹配原图和反相图
        返回:
            tuple|None:
                - 超时前找到时返回匹配中心点坐标 (x, y)
                - 超时未找到返回 None
        """
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_gray(
                template_path,
                region=region,
                threshold=threshold,
                fast_mode=fast_mode,
                invert_mode=invert_mode   # 【新增】
            )
            if pos:
                return pos

            # 安全等待机制
            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)
        return None

    def find_any_image_transparent(self, image_list, region=None, threshold=0.70, fast_mode=True):
        """查找多张带透明通道的图片中的任意一张"""
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)

            for template_path in image_list:
                tpl_bgra = self.load_template_transparent(template_path)
                if tpl_bgra is None:
                    continue

                # 如果图片没有透明通道,降级为普通匹配
                if tpl_bgra.shape[2] != 4:
                    pos = self.find_image_in_screen(screen_bgr, template_path, region, threshold, fast_mode)
                    if pos: return pos
                    continue

                for scale in scales_to_try:
                    if scale == 1.0:
                        tpl_scaled = tpl_bgra.copy()
                    else:
                        tpl_scaled = cv2.resize(tpl_bgra, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

                    h, w = tpl_scaled.shape[:2]
                    if h < 5 or w < 5 or h > screen_bgr.shape[0] or w > screen_bgr.shape[1]:
                        continue

                    tpl_bgr = tpl_scaled[:, :, :3]
                    alpha_mask = tpl_scaled[:, :, 3]

                    res = cv2.matchTemplate(screen_bgr, tpl_bgr, cv2.TM_CCOEFF_NORMED, mask=alpha_mask)
                    _, max_val, _, max_loc = cv2.minMaxLoc(res)

                    if max_val >= threshold:
                        # 【新增】:多张带透明通道的匹配日志
                        self.log(f"[AlphaMatchAny] 命中(无视背景): {template_path} | 得分: {max_val:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                        return (
                            max_loc[0] + w // 2 + (region[0] if region else 0),
                            max_loc[1] + h // 2 + (region[1] if region else 0),
                        )
            return None
        except Exception as e:
            self.log(f"find_any_image_transparent 异常: {e}")
            return None

    def wait_for_any_image_transparent(self, image_list, region=None, threshold=0.70, timeout=30, interval=0.4, fast_mode=True):
        """等待带有透明背景的多张图片中的任意一张出现"""
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_any_image_transparent(image_list, region, threshold, fast_mode)
            if pos:
                return pos

            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)
        return None
    def wait_for_any_image(self, image_list, region=None, threshold=0.75, timeout=30, interval=0.4, fast_mode=True, log_text=None):
        start = time.time()

        while self.is_running and time.time() - start < timeout:
            try:
                screen_bgr = self.capture_region(region)
                for img_path in image_list:
                    pos = self.find_image_in_screen(
                        screen_bgr,
                        img_path,
                        region=region,
                        threshold=threshold,
                        fast_mode=fast_mode
                    )
                    if pos:
                        return pos
            except Exception as e:
                self.log(f"wait_for_any_image 异常: {e}")

            if log_text:
                self.log(log_text)

            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)

        return None

    def wait_for_image(self, template_path, region=None, threshold=0.75, timeout=30, interval=0.4, fast_mode=True, log_text=None):
        return self.wait_for_any_image(
            [template_path],
            region=region,
            threshold=threshold,
            timeout=timeout,
            interval=interval,
            fast_mode=fast_mode,
            log_text=log_text
        )

    def wait_for_buy_and_used_car(self, timeout=20):
        targets = ["BNandUC.png"]
        checks = [
            ("gray", lambda: self.wait_for_any_image_gray(targets, region=self.regions["左"], threshold=0.68, timeout=timeout, interval=0.25, fast_mode=False)),
            ("full", lambda: self.wait_for_any_image(targets, region=self.regions["全界面"], threshold=0.65, timeout=timeout, interval=0.25, fast_mode=False)),
            ("fast", lambda: self.wait_for_any_image(targets, region=self.regions["左"], threshold=0.70, timeout=timeout, interval=0.25, fast_mode=True)),
        ]

        for label, fn in checks:
            pos = fn()
            if pos:
                self.log(f"[BuyNewUsed] 命中模式: {label}")
                return pos
        return None

    def wait_for_image_with_element(self, main_path, sub_path, region=None, threshold=0.85, timeout=30, interval=0.4, fast_mode=True):
        start = time.time()

        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_with_element(
                main_path,
                sub_path,
                region=region,
                threshold=threshold,
                fast_mode=fast_mode
            )
            if pos:
                return pos

            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)

        return None

    def match_template_score(self, src, tpl):
        try:
            if tpl is None or src is None:
                return 0.0
            th, tw = tpl.shape[:2]
            sh, sw = src.shape[:2]
            if th < 5 or tw < 5 or th > sh or tw > sw:
                return 0.0
            res = cv2.matchTemplate(src, tpl, cv2.TM_CCOEFF_NORMED)
            return cv2.minMaxLoc(res)[1]
        except Exception:
            return 0.0
    #===============================
    #---测试函数-----
    #===============================
    def start_test_find_image(self):
        """F3测试:直接反复调用原 find_image_with_element_multi(),最多找12个目标,只移动鼠标不点击"""
        if self.is_running:
            self.log("已有任务正在运行,无法执行 F3 测试找图。")
            return

        self.is_running = True
        self.is_paused = False
        self.save_config()

        self.reset_run_stats()
        self.update_running_state("running")
        self.update_running_ui("F3测图", 0, 12)
        self.ui_call(self.lbl_runtime_loop.configure, text="测试模式")
        self.update_timer()

        self.log("====== 开始 F3 测试原二阶找图 ======")

        def test_runner():
            try:
                if not self.check_and_focus_game():
                    self.log("未能聚焦游戏窗口,测试结束。")
                    return

                found_positions = []
                mask_areas = []

                for i in range(15):
                    if not self.is_running:
                        return
                    self.check_pause()

                    pos = self.find_image_with_element_multi(
                        "newCC.png",
                        "newcartag.png",
                        region=self.regions["全界面"],
                        main_threshold=0.70,
                        like_threshold=0.70,
                        final_threshold=0.70,
                        fast_mode=True,
                        mask_areas=mask_areas
                    )

                    if not pos:
                        self.log(f"第 {i + 1} 次查找:未找到新的目标,测试结束。")
                        break

                    x, y = int(pos[0]), int(pos[1])

                    duplicated = False
                    for old_x, old_y in found_positions:
                        if abs(x - old_x) <= 80 and abs(y - old_y) <= 80:
                            duplicated = True
                            break

                    region_x, region_y, _, _ = self.regions["全界面"]
                    local_x = x - region_x
                    local_y = y - region_y

                    block_w = 210
                    block_h = 120
                    mask_areas.append((
                        local_x - block_w // 2,
                        local_y - block_h // 2,
                        local_x + block_w // 2,
                        local_y + block_h // 2
                    ))

                    if duplicated:
                        self.log(f"F3测试:识别到重复目标 ({x}, {y}),已扩大遮罩,继续寻找。")
                        continue

                    found_positions.append((x, y))
                    self.update_running_ui("F3测试找图", len(found_positions), 12)
                    self.log(f"F3测试:找到第 {len(found_positions)} 个目标 -> ({x}, {y})")
                    self.hw_mouse_move(x, y)
                    time.sleep(0.5)

                self.log(f"F3测试完成,共找到 {len(found_positions)} 个目标。")

            except Exception as e:
                self.log(f"F3测试异常: {e}")
            finally:
                self.stop_all()

        self.current_thread = threading.Thread(target=test_runner, daemon=True)
        self.current_thread.start()
    # ==========================================
    # --- 模块:跑图前置与循环跑图 ---
    # ==========================================
    def logic_race(self, target_count):
        if self.race_counter >= target_count:
            return True

        self.update_running_ui("循环跑图", self.race_counter, target_count)

        self.log("准备验证/进入菜单...")
        if not self.enter_menu():
            return False

        self.log("切换到创意中心...")
        for _ in range(4):
            self.hw_press("pagedown", delay=0.15)
            time.sleep(0.3)

        time.sleep(0.8)


        pos_el = self.wait_for_image_gray(
            "eventlab.png",
            region=self.regions["全界面"],
            threshold=0.7,
            timeout=5,
            interval=0.25,
            fast_mode=True
        )

        if not pos_el:
            self.log("未找到 eventlab")
            return False

        self.game_click(pos_el)
        time.sleep(1.2)

        pos_yg = self.wait_for_image_gray(
            "playenent.png",
            region=self.regions["中间"],
            threshold=0.75,
            timeout=40,
            interval=0.3,
            fast_mode=True
        )
        if not pos_yg:
            self.log("未找到游玩赛事")
            return False

        self.game_click(pos_yg)
        time.sleep(1.5)

        self.hw_press("backspace")
        time.sleep(0.8)
        self.hw_press("up")
        time.sleep(0.4)
        self.hw_press("enter")
        time.sleep(0.8)

        code_text = "".join(c for c in self.entry_share.get() if c.isdigit())
        for char in code_text:
            if not self.is_running:
                return False
            if char in DIK_CODES:
                self.hw_press(char, delay=0.05)
                time.sleep(0.05)

        time.sleep(0.4)
        self.hw_press("enter")
        time.sleep(0.8)
        self.hw_press("down")
        time.sleep(0.3)
        self.hw_press("enter")
        time.sleep(1.5)

        pos_ck = self.wait_for_image_gray(
            "VEI.png",
            region=self.regions["下"],
            threshold=0.75,
            timeout=20,
            interval=1.0,
            fast_mode=True
        )
        if not pos_ck:
            self.log("链接超时")
            return False

        self.hw_press("enter")
        time.sleep(2.0)
        self.hw_press("enter")
        time.sleep(2.0)

        pos_target = self.wait_for_image_with_element_multi(
            "skillcar.png",
            "liketag.png",
            region=self.regions["全界面"],
            fast_mode=True,
            main_threshold=0.75,
            like_threshold=0.7,
            final_threshold=0.7,
            timeout=2,
            interval=0.25
        )
        if not pos_target:
            self.log("组合识别未命中,尝试仅使用 skillcar.png 兜底识别...")
            pos_target = self.wait_for_image(
                "skillcar.png",
                region=self.regions["全界面"],
                threshold=0.68,
                timeout=2,
                interval=0.25,
                fast_mode=False
            )

        if not pos_target:
            self.log("未找到带 liketag 的目标车辆,重新选品牌...")
            self.hw_press("backspace")
            time.sleep(1.2)

            found_brand = False
            for _ in range(3):
                if not self.is_running:
                    return False

                pos_brand = self.wait_for_image_gray("skillcarbrand.png", region=self.regions["全界面"], threshold=0.8, timeout=1.2, interval=0.2, fast_mode=True)
                if pos_brand:
                    self.game_click(pos_brand)
                    time.sleep(1.2)
                    found_brand = True
                    break

                self.hw_press("up")
                time.sleep(0.4)

            if not found_brand:
                self.log("三次尝试未找到刷图车辆品牌。")
                return False

            for _ in range(20):
                if not self.is_running:
                    return False

                pos_target = self.wait_for_image_with_element_multi(
                    "skillcar.png",
                    "liketag.png",
                    region=self.regions["全界面"],
                    main_threshold=0.75,
                    like_threshold=0.7,
                    final_threshold=0.7,
                    timeout=2,
                    interval=0.25,
                    fast_mode=True
                )
                if not pos_target:
                    self.log("组合识别未命中,尝试仅使用 skillcar.png 兜底识别...")
                    pos_target = self.wait_for_image(
                        "skillcar.png",
                        region=self.regions["全界面"],
                        threshold=0.68,
                        timeout=1.0,
                        interval=0.2,
                        fast_mode=False
                    )
                if pos_target:
                    break

                for _ in range(4):
                    self.hw_press("right", delay=0.08)
                    time.sleep(0.08)
                time.sleep(0.4)

        if not pos_target:
            self.log("翻页未能找到带有 liketag 的刷图车辆!")
            return False

        self.game_click(pos_target)
        time.sleep(0.5)
        self.hw_press("enter")
        time.sleep(4.0)

        self.log("前置完成,开始循环跑图!")

        while self.race_counter < target_count:
            if not self.is_running:
                return False

            self.log(f"跑图 {self.race_counter + 1}/{target_count}: 找赛事起点...")

            pos = None
            for _ in range(120):
                if not self.is_running:
                    return False

                pos = self.wait_for_any_image_gray(
                    ["start.png", "startw.png"],
                    region=self.regions["左下"],
                    threshold=0.75,
                    timeout=0.7,
                    interval=0.2,
                    fast_mode=True
                )
                if pos:
                    break

                self.hw_press("down")
                time.sleep(0.25)

            if not pos:
                self.log("找不到赛事起点,退出跑图。")
                return False

            self.game_click(pos)
            time.sleep(4.0)
            self.hw_key_down("w")
            self.hw_key_down("up")

            # 初始化各类计时器
            race_start_time = time.time()  # 新增:记录跑图发车时间
            last_like_chk = time.time()
            last_chk = 0
            finished = False
            timeout_triggered = False      # 新增:标记是否触发了120秒超时

            driving_keys_held = True # <--- 【新增】标记油门状态
            try:
                race_timeout = max(60, int(self.config.get("race_timeout", 300)))
            except Exception:
                race_timeout = 300

            while self.is_running:
                # ====== 【新增】跑图专用暂停处理逻辑 ======
                if self.is_paused:
                    if driving_keys_held: # 刚进入暂停,松开油门
                        self.hw_key_up("w")
                        self.hw_key_up("up")
                        driving_keys_held = False
                    self.check_pause() # 阻塞在此处
                    # 从暂停中恢复,如果还没跑完,重新按下油门
                    if self.is_running:
                        self.hw_key_down("w")
                        self.hw_key_down("up")
                        driving_keys_held = True

                    # 避免恢复瞬间触发超时,重置计时器
                    race_start_time = time.time()
                    last_like_chk = time.time()
                    last_chk = time.time()
                    continue
                # =========================================
                now = time.time()

                # 【新增逻辑】:超时防卡死检测
                if now - race_start_time > race_timeout:
                    self.log(f"跑图超时(已超过{race_timeout}秒)!触发强制重开赛事逻辑...")
                    timeout_triggered = True
                    break

                # 每隔3秒处理一次跑图中的特殊界面/异常
                if now - last_like_chk >= 3.0:
                    vram_result = self.check_vramne_during_race()
                    if vram_result is True:
                        self.log("VRAM恢复完成,结束当前跑图流程,交给外层重新恢复。")
                        return False
                    elif vram_result is False:
                        self.log("VRAM恢复失败。")
                        return False
                    pos_like = self.find_any_image_gray(
                        ["likeauthor.png", "dislikeauthor.png"],
                        region=self.regions["中间"],
                        threshold=0.70
                    )
                    if pos_like:
                        self.log("识别到点赞作界面,执行回车确认!")
                        self.hw_press("enter")
                    last_like_chk = now

                # 每1秒检测一次重新开始(正常完赛)
                if now - last_chk >= 1.0:
                    found_restart = self.find_image_gray("restart.png", region=self.regions["下"], threshold=0.75, fast_mode=True)
                    if found_restart:
                        finished = True
                        break
                    last_chk = now

                time.sleep(0.3)

            # 无论正常结束还是超时,都必须先松开油门和方向
            self.hw_key_up("w")
            self.hw_key_up("up")

            if not self.is_running:
                return False

            # ====== 【新增】:执行超时重置操作 ======
            if timeout_triggered:
                time.sleep(0.5)
                self.hw_press("esc")
                time.sleep(1.5)  # 等待菜单动画加载

                # 寻找并点击 restarta.png
                pos_restarta = self.wait_for_image_gray("restarta.png", region=self.regions["全界面"], threshold=0.70, timeout=4.0, interval=0.3, fast_mode=True)
                if pos_restarta:
                    self.log("找到 restarta.png,点击重开赛事...")
                    self.game_click(pos_restarta)
                    time.sleep(1.0)
                    self.hw_press("enter")  # 地平线重开赛事通常有确认弹窗,按一次回车确认
                    time.sleep(4.0)         # 等待黑屏重加载动画
                else:
                    self.log("未找到 restarta.png,尝试直接继续...")

                # 【关键】:直接跳过下方的结算流程,回到最外层 while 重新找 start.png(并且本次不计入 race_counter)
                continue
            # ========================================

            if not finished:
                return False

            if self.race_counter == target_count - 1:
                self.hw_press("enter")
                time.sleep(2.0)
            else:
                self.hw_press("x")
                time.sleep(0.8)
                self.hw_press("enter")
                time.sleep(2.0)

            self.race_counter += 1
            self.update_running_ui("循环跑图", self.race_counter, target_count)

        return True

    # ==========================================
    # --- 模块:买车 ---
    # ==========================================
    def logic_buy_car(self, target_count):
        if self.car_counter >= target_count:
            return True

        self.update_running_ui("批量买车", self.car_counter, target_count)

        self.log("准备验证/进入菜单...")
        if not self.enter_menu():
            return False

        pos_collectionjournal = self.wait_for_image_transparent(
            "collectionjournal.png",
            region=self.regions["左"],
            threshold=0.7,
            timeout=30,
            interval=0.4,
            fast_mode=True
        )
        if not pos_collectionjournal:
            self.log("未找到收集簿")
            return False

        self.game_click(pos_collectionjournal, double=True)
        time.sleep(1.0)


        pos_masterexplorer = self.wait_for_image(
            "masterexplorer.png",
            region=self.regions["全界面"],
            threshold=0.75,
            timeout=30,
            interval=0.4,
            fast_mode=True
        )
        if not pos_masterexplorer:
            self.log("未找到探索")
            return False

        self.game_click(pos_masterexplorer, double=True)
        time.sleep(0.6)

        pos_carcollection = self.wait_for_image_transparent(
            "carcollection.png",
            region=self.regions["全界面"],
            threshold=0.75,
            timeout=30,
            interval=0.3,
            fast_mode=True
        )
        if not pos_carcollection:
            self.log("未找到车辆收集")
            return False

        self.game_click(pos_carcollection, double=True)
        time.sleep(1.0)

        self.hw_press("backspace")
        time.sleep(0.5)

        brand_pos = None
        for _ in range(5):
            if not self.is_running:
                return False


            brand_pos = self.wait_for_any_image_gray(
                ["CCbrand.png"],
                region=self.regions["全界面"],
                threshold=0.75,
                timeout=0.8,
                interval=0.2,
                fast_mode=True
            )
            if brand_pos:
                break

            self.hw_press("up")
            time.sleep(0.25)

        if not brand_pos:
            self.log("未找到品牌")
            return False

        self.game_click(brand_pos)
        time.sleep(0.8)
        self.hw_press("down")
        time.sleep(0.4)

        pos_22b = self.wait_for_image(
            "consumablecar.png",
            region=self.regions["全界面"],
            threshold=0.90,
            timeout=8,
            interval=0.3,
            fast_mode=False
        )
        if not pos_22b:
            self.log("未找到消耗品车辆")
            return False

        self.game_click(pos_22b, double=True)
        time.sleep(1.0)

        while self.car_counter < target_count:
            if not self.is_running:
                return False

            self.hw_press("space")
            time.sleep(0.6)
            self.move_to_game_coord(5, 5)
            self.hw_press("down")
            time.sleep(0.2)
            self.move_to_game_coord(5, 5)
            self.hw_press("enter")
            time.sleep(0.6)
            self.move_to_game_coord(5, 5)
            self.hw_press("enter")
            time.sleep(0.6)
            self.move_to_game_coord(5, 5)
            self.hw_press("enter")
            time.sleep(0.7)

            self.car_counter += 1
            self.update_running_ui("批量买车", self.car_counter, target_count)

        for _ in range(5):
            if not self.is_running:
                return False
            self.hw_press("esc")
            time.sleep(0.8)

        return True
    # ==========================================
    # --- 模块:抽奖 ---
    # ==========================================
    def logic_super_wheelspin(self, target_count):
        if self.cj_counter >= target_count:
            return True

        self.update_running_ui("超级抽奖", self.cj_counter, target_count)
        # 【新增】:初始化记忆页码
        if not hasattr(self, 'memory_car_page'):
            self.memory_car_page = 0
        self.log("准备验证/进入菜单...")
        if not self.enter_menu():
            return False

        self.log("进入车辆与收藏...")
        self.hw_press("pagedown", delay=0.15)
        time.sleep(1.0)

        pos_buycar = self.wait_for_buy_and_used_car(timeout=15)
        if not pos_buycar:
            self.log("未识别到 购买新车与二手车")
            return False

        self.game_click(pos_buycar)
        time.sleep(0.8)
        self.hw_press("enter")
        time.sleep(5)


        pos_bs = self.wait_for_any_image_gray(
            ["buyandsell-w.png", "buyandsell-b.png"],
            region=self.regions["左"],
            threshold=0.75,
            timeout=60,
            interval=0.5,
            fast_mode=True
        )
        if not pos_bs:
            self.log("未找到购买与出售")
            return False

        self.game_click(pos_bs)
        time.sleep(1.0)
        self.hw_press("pagedown", delay=0.15)
        self.log("进入车辆界面...")
        time.sleep(0.5)

        while self.cj_counter < target_count:
            if not self.is_running:
                return False
            self.log("进入我的车辆.")
            self.hw_press("enter")
            time.sleep(2.0)
            self.hw_press("backspace")
            time.sleep(1.0)

            brand_pos = None
            for _ in range(30):
                if not self.is_running:
                    return False

                brand_pos = self.wait_for_any_image_gray(
                    ["CCbrand.png"],
                    region=self.regions["全界面"],
                    threshold=0.75,
                    timeout=0.8,
                    interval=0.2,
                    fast_mode=True
                )
                if brand_pos:
                    break

                self.hw_press("up")
                time.sleep(0.25)

            if not brand_pos:
                self.log("选品牌失败")
                return False

            self.game_click(brand_pos)
            time.sleep(1.0)
            jump_pages = max(0, self.memory_car_page - 1)

            if jump_pages > 0:
                self.log(f"智能记忆触发:快速跳过前 {jump_pages} 页...")
                for _ in range(jump_pages):
                    if not self.is_running: return False
                    for _ in range(4):
                        self.hw_press("right", delay=0.06)
                        time.sleep(0.1)
                    time.sleep(0.15) # 给一点点动画缓冲时间
            pos_target = None
            found_car = False
            current_page = jump_pages # 记录当前所在的真实页码

            # 最大翻页次数扣除已经跳过的页数
            for _ in range(85 - jump_pages):
                if not self.is_running:
                    return False
                pos_target = self.wait_for_new_consumable_car_strict(timeout=1.5, interval=0.2)

                if pos_target:
                    self.game_click(pos_target)
                    found_car = True
                    # 记住这次找到车是在哪一页
                    self.memory_car_page = current_page
                    self.log(f"锁定目标车辆!已记录当前页码: {current_page}")
                    break

                # 翻下一页
                for _ in range(4):
                    self.hw_press("right", delay=0.06)
                    time.sleep(0.1)
                time.sleep(0.4)
                current_page += 1
            if not found_car:
                self.log("列表中未找到目标车辆,重置记忆页码。")
                self.memory_car_page = 0 # 没找到说明车刷完了,清零记忆
                return False
            time.sleep(1.2)
            self.log("尝试寻找'上车'按钮...")

            pos_rc = None
            pos_rc = self.wait_for_image_gray("rc.png", region=self.regions["全界面"], threshold=0.70, timeout=0.5, interval=0.1, fast_mode=True)

            if pos_rc:
                self.log("点击上车")
                self.game_click(pos_rc)
                time.sleep(2.0)  # 点击后等待上车加载
            else:
                self.log("回车上车")
                self.hw_press("enter")
                time.sleep(1.0)
                self.hw_press("enter")
                time.sleep(1.0)


            pos_sjy = None
            for _ in range(20):
                if not self.is_running:
                    return False

                pos_sjy = self.find_any_image_gray(["UandT-w.png", "UandT-b.png"], region=self.regions["左下"], threshold=0.68)
                if not pos_sjy:
                    pos_sjy = self.find_any_image_gray(["UandT-w.png", "UandT-b.png"], region=self.regions["全界面"], threshold=0.62, fast_mode=False)
                if pos_sjy:
                    break

                self.hw_press("esc")
                time.sleep(0.5)

            if not pos_sjy:
                self.log("找不到升级页面")
                return False

            self.game_click(pos_sjy)
            time.sleep(0.5)

            pos_cls = self.wait_for_any_image_gray(
                ["clsldcnw.png", "clsldcnb.png"],
                region=self.regions["全界面"],
                threshold=0.62,
                timeout=8,
                interval=0.25,
                fast_mode=False
            )
            if not pos_cls:
                self.log("未找到车辆专精,可能未成功进入目标车辆升级页面或选中了非目标车辆。")
                return False
            self.game_click(pos_cls)
            time.sleep(1.5)

            pos_exp = self.wait_for_any_image(
                ["EXPwU.png"],
                region=self.regions["左"],
                threshold=0.75,
                timeout=1.5,
                interval=0.3,
                fast_mode=True
            )

            if pos_exp:
                self.log("该车辆技能已点过,跳过计数")
            else:
                time.sleep(1.0)
                self.hw_press("enter")
                time.sleep(1.5)

                for dk in self.config["skill_dirs"]:
                    if not self.is_running:
                        return False
                    self.hw_press(dk)
                    time.sleep(0.2)
                    self.hw_press("enter")
                    time.sleep(1.2)

                spne_found = self.find_image_gray("SPNE.png", region=self.regions["全界面"], threshold=0.70)

                if spne_found:
                    self.log("已无技能点或技能已点完,提前结束抽奖!")
                    time.sleep(1.0)
                    self.hw_press("enter")
                    time.sleep(0.8)
                    self.hw_press("esc")
                    time.sleep(1.0)
                    self.hw_press("esc")
                    time.sleep(1.0)
                    self.hw_press("esc")
                    time.sleep(1.0)
                    return True
                self.cj_counter += 1
                self.update_running_ui("超级抽奖", self.cj_counter, target_count)

            self.hw_press("esc")
            time.sleep(1.2)
            self.hw_press("esc")
            time.sleep(0.8)
            self.hw_press("up", delay=0.15)
            time.sleep(0.8)
        self.hw_press("esc")
        time.sleep(1.2)
        self.hw_press("esc")
        time.sleep(1.2)
        return True
if __name__ == "__main__":
    app = FH_UltimateBot()
    app.mainloop()
