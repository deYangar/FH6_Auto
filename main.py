import sys
import os
import ctypes

# ====== DPI Awareness（必须在所有 UI 操作之前设置）======
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ====== 【修复 OMP 冲突的核心代码】======
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
# =======================================
import json
import time
import ctypes
import tkinter as tk
import customtkinter as ctk
ctk.deactivate_automatic_dpi_awareness()
ctk.set_widget_scaling(1.0)
ctk.set_window_scaling(1.0)
import cv2
import pyautogui
import pydirectinput
from pynput import keyboard
from PIL import Image, ImageGrab
import win32gui
import threading
import fh6_backend
import focus_hook_manager

from config import (
    APP_DIR, INTERNAL_DIR, USER_CONFIG_FILE, LOG_FILE,
    CACHE_DIR, TEMPLATE_CACHE_FILE, TEMPLATE_META_FILE, CURRENT_VERSION,
    auto_extract_configs, auto_extract_images, get_img_path, get_asset_path,
    set_scheme_dir
)
from constants import DIK_CODES, MATCH_THRESHOLD
from input_handler import InputMixin
from vision import VisionMixin
from recovery import RecoveryMixin
from race_logic import RaceMixin
from buy_logic import BuyMixin
from cj_logic import CJMixin
from sell_logic import SellMixin
from anti_cheat import AntiCheatMixin
from filter_nav import (
    FilterNavMixin,
    DEFAULT_SELL_FILTER_SCHEME1, DEFAULT_SELL_FILTER_SCHEME2, DEFAULT_RACE_FILTER,
)

pyautogui.FAILSAFE = False
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class FH_UltimateBot(
    InputMixin, VisionMixin, RecoveryMixin,
    RaceMixin, BuyMixin, CJMixin, SellMixin, AntiCheatMixin,
    FilterNavMixin,
    ctk.CTk
):
    def __init__(self):
        super().__init__()
        #窗口相关
        self.title(f"FH6Auto v{CURRENT_VERSION}")
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
        self.diagnostic_trace = None  # 诊断会话（None=未开启）
        self.bg_input = None    # <--- 【后台化】后台输入管理器
        self.focus_hook_info = None
        self.protocol("WM_DELETE_WINDOW", self.on_app_close)

        self.race_counter = 0
        self.car_counter = 0
        self.cj_counter = 0
        self.sc_count = 0
        self.global_loop_current = 0

        self.template_cache = {}
        self.scaled_template_cache = {}
        self.file_template_cache = {}
        self.last_positions = {}
        self.edge_template_cache = {}
        self.scaled_edge_template_cache = {}

        # 【新增】反检测心跳状态初始化
        self._init_anti_cheat_state()

        self.init_regions()
        self._log_buffer = []  # 提前初始化，避免后台线程竞态

        # 【优化加载速度】:将IO提取与图像缓存的加载/生成放到后台线程,避免阻塞主界面启动
        # 增加模型释放步骤
        def background_init():
            auto_extract_images()

            self.prepare_template_cache()
        threading.Thread(target=background_init, daemon=True).start()

        #加载配置文件
        auto_extract_configs()
        self.load_config()
        _scheme_idx = self.config.get("current_scheme", 0)
        set_scheme_dir(f"scheme_{_scheme_idx + 1}")

        self.setup_ui()
        self.start_hotkey_listener()
        self.update_skill_grid()
        self.center_window()
        self.after(1200, self.auto_focus_hook_on_start)
        self.after(2000, self.check_for_updates)

        self.log("免责声明:本脚本仅供 Python 自动化技术交流与学习使用。请勿用于商业盈利或破坏游戏平衡,因使用本脚本造成的账号封禁等损失,由使用者自行承担。")
        self.log("工具运行目录不要有中文")
        self.log("默认刷图车辆:【斯巴鲁Impreza 22B-STi Version】【调校S2  900】【保持默认涂装】【收藏车辆】")
        self.log("方案2采用【斯巴鲁Impreza 22B-STi Version】来跑图，采用【1974 马自达 #123 Mad Mike 808 Wagon】来抽奖，适合有通行证的玩家使用。没有车辆通行证的玩家请勿选择")
        self.log("游戏设置为【自动转向】【自动挡】,游戏语言设置为【简体中文】")
        self.log("大部分以图像识别作为引导,减少机器盲目操作的风险,但仍无法完全避免,使用前请做好准备")


    def ui_call(self, func, *args, **kwargs):
        try:
            self.after(0, lambda: func(*args, **kwargs))
        except Exception:
            pass

    def _open_releases_page(self):
        """点击版本号打开 GitHub Releases 页面。"""
        import webbrowser
        webbrowser.open("https://github.com/deYangar/FH6_Auto/releases")

    def check_for_updates(self):
        """检查 GitHub Releases 是否有新版本。"""
        import urllib.request, ssl, re
        def _check():
            try:
                # 直接抓 releases 页面 HTML（不走 API，无速率限制）
                url = "https://github.com/deYangar/FH6_Auto/releases"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                try:
                    ctx = ssl.create_default_context()
                    with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                        html = resp.read().decode("utf-8", errors="ignore")
                except Exception:
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                        html = resp.read().decode("utf-8", errors="ignore")

                # 从 HTML 中提取最新 release tag（如 v1.2.0.0）
                # 页面标题或 release 卡片中会有 tag
                m = re.search(r'/deYangar/FH6_Auto/releases/tag/(v?[\d.]+)', html)
                if not m:
                    m = re.search(r'<span[^>]*>\s*(v[\d.]+)\s*</span>', html)
                if not m:
                    self.ui_call(lambda: self.log("[更新检查] 未找到版本号"))
                    return

                latest_tag = m.group(1)
                latest_ver = latest_tag.lstrip("v").strip()
                cur_ver = CURRENT_VERSION.strip()

                def _ver_tuple(v):
                    parts = []
                    for p in v.split("."):
                        try:
                            parts.append(int(p))
                        except Exception:
                            parts.append(0)
                    return tuple(parts)

                is_newer = _ver_tuple(latest_ver) > _ver_tuple(cur_ver)
                release_url = "https://github.com/deYangar/FH6_Auto/releases"
                if is_newer:
                    self.ui_call(lambda: self._on_update_found(latest_tag, release_url, ""))
                else:
                    self.ui_call(lambda: self._on_up_to_date())
            except Exception as e:
                # 写文件日志 + UI 日志双保险
                try:
                    import traceback
                    with open(os.path.join(os.path.dirname(sys.executable), "update_debug.log"), "w", encoding="utf-8") as f:
                        f.write(f"{e}\n\n{traceback.format_exc()}")
                except Exception:
                    pass
                self.ui_call(lambda _err=str(e): self.log(f"[更新检查] 失败: {_err}"))
        threading.Thread(target=_check, daemon=True).start()

    def _on_up_to_date(self):
        """已是最版本：右上角显示“最新版”。"""
        try:
            self.version_label.configure(text=f"v{CURRENT_VERSION} ✓ 最新版", text_color="#27AE60")
        except Exception:
            pass

    def _on_update_found(self, latest_tag, release_url, body):
        """有新版本：右上角闪烁提示 + 弹对话框。"""
        try:
            self._update_release_url = release_url
            self._update_blinking = True
            self._blink_update_label(latest_tag)
        except Exception:
            pass
        import webbrowser
        msg = f"发现新版本 {latest_tag}！\n\n"
        if body:
            msg += body[:500] + "\n\n"
        msg += "点击确定后将在浏览器打开下载页面。"
        from tkinter import messagebox
        result = messagebox.showinfo("发现新版本", msg, parent=self)
        if result == "ok":
            webbrowser.open(release_url)

    def _blink_update_label(self, latest_tag):
        """右上角版本标签闪烁提示。"""
        if not self._update_blinking:
            return
        try:
            current_text = self.version_label.cget("text")
            if "🔔" in current_text:
                self.version_label.configure(
                    text=f"🔔 新版本 {latest_tag} 可用!",
                    text_color="#E74C3C"
                )
            else:
                self.version_label.configure(
                    text=f"v{CURRENT_VERSION} (有新版 {latest_tag})",
                    text_color="#E67E22"
                )
        except Exception:
            pass
        self.after(600, lambda: self._blink_update_label(latest_tag))

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
            "移除车辆": 0.0,
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
            if iv > 4:
                iv = 4
            entry_widget.delete(0, "end")
            entry_widget.insert(0, str(iv))
        except Exception:
            entry_widget.delete(0, "end")
            entry_widget.insert(0, str(default_value))

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

    def load_config(self):
        # 1. 直接使用内置字典作为"绝对底本"(最安全,无视打包丢文件问题)
        self.config = {
            "current_scheme": 0,
            "schemes": [],
            "class_image": "classS2829.png",
            "race_count": 99,
            "buy_count": 30,
            "cj_count": 30,
            "chk_1": True,
            "chk_2": True,
            "chk_3": True,
            "next_1": 2,
            "next_2": 3,
            "next_3": 4,
            "global_loops": 10,
            "skill_dirs": ["up", "up", "up", "right", "right"],
            "share_code": "167982162",
            "auto_restart": False,
            "restart_cmd": "start steam://run/2483190",
            "race_timeout": 600,
            "stuck_timeout": 60,
            "debug_screenshots": False,
            "focus_hook_enabled": False,
            "cj_mode": 2,
            "auto_close_game": False,
            "auto_shutdown": False,
            "diagnostic_mode": False,
            "sell_count": 30,
            "chk_4": True,
            "next_4": 1
        }
        ext_path = USER_CONFIG_FILE
        # 2. 读取用户的 config.json,并与底本合并(自动补全缺失项)
        if os.path.exists(ext_path):
            try:
                with open(ext_path, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                    self.config.update(user_config)
            except Exception as e:
                self.log(f"用户 config.json 损坏,已自动恢复默认配置。原因: {e}", level="WARN")

        # 3. 方案迁移：旧配置没有 schemes 结构时自动迁移
        if not self.config.get("schemes"):
            scheme_1 = {
                "name": "方案1 - 无通行证用Revuelto刷超抽",
                "class_image": self.config.get("class_image", "classS2829.png"),
                "race_count": self.config.get("race_count", 99),
                "buy_count": self.config.get("buy_count", 30),
                "cj_count": self.config.get("cj_count", 30),
                "sell_count": self.config.get("sell_count", 30),
                "skill_dirs": self.config.get("skill_dirs", ["up", "up", "up", "right", "right"]),
                "share_code": self.config.get("share_code", "167982162"),
                "cj_mode": self.config.get("cj_mode", 2),
                "chk_1": self.config.get("chk_1", True),
                "chk_2": self.config.get("chk_2", True),
                "chk_3": self.config.get("chk_3", True),
                "chk_4": self.config.get("chk_4", True),
                "next_1": self.config.get("next_1", 2),
                "next_2": self.config.get("next_2", 3),
                "next_3": self.config.get("next_3", 4),
                "next_4": self.config.get("next_4", 1),
            }
            schemes = [scheme_1]
            # 检查是否有方案2的图片目录（同时检查外置和内置目录，避免后台解压竞态）
            scheme_2_ext = os.path.join(APP_DIR, "images", "scheme_2")
            scheme_2_int = os.path.join(INTERNAL_DIR, "images", "scheme_2")
            if os.path.isdir(scheme_2_ext) or os.path.isdir(scheme_2_int):
                scheme_2 = dict(scheme_1)
                scheme_2["name"] = "方案2 - （需要有通行证）Mad Mike 马自达超抽"
                scheme_2["class_image"] = "classS1702.png"
                scheme_2["skill_dirs"] = ["right", "right", "up", "up", "up"]
                scheme_2["buy_count"] = 45
                scheme_2["cj_count"] = 45
                scheme_2["sell_count"] = 45
                schemes.append(scheme_2)
            self.config["schemes"] = schemes
            self.config["current_scheme"] = 0

        # 3.5 筛选导航字段迁移 (v1.2.10.0)：老配置补齐 sell_filter / race_filter
        #     默认值来自 v1.2.9.0 固定按键序列的反推（方案1: 2/6/14/28，方案2: 7/10/32/5，选车: 35/19）
        for _i, _s in enumerate(self.config.get("schemes", [])):
            if not isinstance(_s.get("sell_filter"), list) or not _s.get("sell_filter"):
                _s["sell_filter"] = list(
                    DEFAULT_SELL_FILTER_SCHEME2 if _i == 1 else DEFAULT_SELL_FILTER_SCHEME1
                )
            if not isinstance(_s.get("race_filter"), list) or not _s.get("race_filter"):
                _s["race_filter"] = list(DEFAULT_RACE_FILTER)

        # 确保顶层 class_image 与当前方案同步
        _idx = self.config.get("current_scheme", 0)
        _schemes = self.config.get("schemes", [])
        if 0 <= _idx < len(_schemes):
            self.config["class_image"] = _schemes[_idx].get("class_image", "classS2829.png")

        # 4. 将最新、最完整的配置重新写回外置文件
        try:
            with open(ext_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.log(f"配置文件写入失败: {e}", level="ERROR")

    def save_config(self):
        # 每个配置项独立 try/except，避免单项失败导致后续全部不保存
        def _save_int(key, entry_widget, min_val=None, default=None):
            try:
                val = int(entry_widget.get())
                if min_val is not None:
                    val = max(min_val, val)
                self.config[key] = val
            except (ValueError, TypeError):
                if default is not None and key not in self.config:
                    self.config[key] = default

        def _save_str(key, entry_widget, filter_digits=False):
            try:
                val = entry_widget.get()
                if filter_digits:
                    val = "".join(c for c in val if c.isdigit())
                self.config[key] = val
            except Exception:
                pass

        _save_int("race_count", self.entry_race)
        _save_int("buy_count", self.entry_car)
        _save_int("cj_count", self.entry_cj)
        _save_int("global_loops", self.entry_global_loop)

        if hasattr(self, "entry_stuck_timeout"):
            _save_int("stuck_timeout", self.entry_stuck_timeout, min_val=10, default=60)
        _save_str("share_code", self.entry_share, filter_digits=True)
        if hasattr(self, "entry_sharecode_timeout"):
            _save_int("sharecode_timeout", self.entry_sharecode_timeout, min_val=1, default=10)
        _save_int("next_1", self.entry_next1)
        _save_int("next_2", self.entry_next2)
        _save_int("next_3", self.entry_next3)
        if hasattr(self, "entry_next4"):
            _save_int("next_4", self.entry_next4)
        if hasattr(self, "entry_sc"):
            _save_int("sell_count", self.entry_sc)

        self.config["chk_1"] = self.var_chk1.get()
        self.config["chk_2"] = self.var_chk2.get()
        self.config["chk_3"] = self.var_chk3.get()
        if hasattr(self, "var_chk4"):
            self.config["chk_4"] = self.var_chk4.get()
        self.config["auto_restart"] = self.var_auto_restart.get()
        self.config["debug_screenshots"] = self.var_debug_mode.get()
        self.config["focus_hook_enabled"] = self.var_focus_hook.get()
        self.config["use_directml"] = self.var_directml.get()
        self.config["restart_cmd"] = self.le_restart_cmd.get().strip()
        if hasattr(self, "opt_cj_mode"):
            cj_mode_val = self.opt_cj_mode.get()
            self.config["cj_mode"] = 2 if "模式2" in cj_mode_val else 1
        if hasattr(self, "var_auto_close"):
            self.config["auto_close_game"] = self.var_auto_close.get()
        if hasattr(self, "var_auto_shutdown"):
            self.config["auto_shutdown"] = self.var_auto_shutdown.get()
        if hasattr(self, "var_debug_mode"):
            self.config["diagnostic_mode"] = self.var_debug_mode.get()
        # 同步当前方案
        self._sync_to_current_scheme()
        try:
            with open(USER_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.log(f"保存配置失败: {e}")

    # ====== 方案管理 ======

    def _sync_to_current_scheme(self):
        """将当前顶层配置同步到当前方案"""
        idx = self.config.get("current_scheme", 0)
        schemes = self.config.get("schemes", [])
        if idx < 0 or idx >= len(schemes):
            return
        scheme = schemes[idx]
        for k in [
            "class_image", "race_count", "buy_count", "cj_count",
            "sell_count", "skill_dirs", "share_code", "cj_mode",
            "chk_1", "chk_2", "chk_3", "chk_4",
            "next_1", "next_2", "next_3", "next_4"
        ]:
            if k in self.config:
                scheme[k] = self.config[k]

    def refresh_scheme_menu(self):
        """刷新方案下拉菜单"""
        schemes = self.config.get("schemes", [])
        values = [s.get("name", f"方案{i+1}") for i, s in enumerate(schemes)]
        if hasattr(self, "scheme_menu"):
            self.scheme_menu.configure(values=values if values else ["方案1"])
            idx = self.config.get("current_scheme", 0)
            if 0 <= idx < len(values):
                self.scheme_menu.set(values[idx])

    def on_scheme_switch(self, choice):
        """方案下拉菜单切换回调"""
        schemes = self.config.get("schemes", [])
        target_idx = -1
        for i, s in enumerate(schemes):
            if s.get("name", f"方案{i+1}") == choice:
                target_idx = i
                break
        if target_idx < 0 or target_idx == self.config.get("current_scheme", 0):
            return
        self.switch_scheme(target_idx)

    def switch_scheme(self, idx):
        """切换到指定方案"""
        schemes = self.config.get("schemes", [])
        if idx < 0 or idx >= len(schemes):
            return
        # 保存当前方案
        self._sync_to_current_scheme()
        # 切换
        self.config["current_scheme"] = idx
        scheme = schemes[idx]
        # 同步方案到顶层配置
        for k, v in scheme.items():
            self.config[k] = v
        # 更新图片目录
        set_scheme_dir(f"scheme_{idx + 1}")
        # 清除内存模板缓存
        self.template_cache.clear()
        self.scaled_template_cache.clear()
        if hasattr(self, "template_gray_cache"):
            self.template_gray_cache.clear()
        if hasattr(self, "template_transparent_cache"):
            self.template_transparent_cache.clear()
        # 应用到 UI
        self.apply_scheme_to_ui(scheme)
        # 保存
        self.save_config()
        self.log(f"已切换到方案: {scheme.get('name', f'方案{idx+1}')}")

    def apply_scheme_to_ui(self, scheme):
        """将方案数据应用到 UI 控件"""
        if hasattr(self, "entry_race"):
            self.entry_race.delete(0, "end")
            self.entry_race.insert(0, str(scheme.get("race_count", 99)))
        if hasattr(self, "entry_car"):
            self.entry_car.delete(0, "end")
            self.entry_car.insert(0, str(scheme.get("buy_count", 30)))
        if hasattr(self, "entry_cj"):
            self.entry_cj.delete(0, "end")
            self.entry_cj.insert(0, str(scheme.get("cj_count", 30)))
        if hasattr(self, "entry_sc"):
            self.entry_sc.delete(0, "end")
            self.entry_sc.insert(0, str(scheme.get("sell_count", 30)))
        if hasattr(self, "entry_share"):
            self.entry_share.delete(0, "end")
            self.entry_share.insert(0, str(scheme.get("share_code", "167982162")))
        if hasattr(self, "entry_next1"):
            self.entry_next1.delete(0, "end")
            self.entry_next1.insert(0, str(scheme.get("next_1", 2)))
        if hasattr(self, "entry_next2"):
            self.entry_next2.delete(0, "end")
            self.entry_next2.insert(0, str(scheme.get("next_2", 3)))
        if hasattr(self, "entry_next3"):
            self.entry_next3.delete(0, "end")
            self.entry_next3.insert(0, str(scheme.get("next_3", 4)))
        if hasattr(self, "entry_next4"):
            self.entry_next4.delete(0, "end")
            self.entry_next4.insert(0, str(scheme.get("next_4", 1)))
        if hasattr(self, "var_chk1"):
            self.var_chk1.set(scheme.get("chk_1", True))
        if hasattr(self, "var_chk2"):
            self.var_chk2.set(scheme.get("chk_2", True))
        if hasattr(self, "var_chk3"):
            self.var_chk3.set(scheme.get("chk_3", True))
        if hasattr(self, "var_chk4"):
            self.var_chk4.set(scheme.get("chk_4", True))
        if hasattr(self, "opt_cj_mode"):
            cj_mode = scheme.get("cj_mode", 2)
            if cj_mode == 2:
                self.opt_cj_mode.set("模式2: 从设计与喷涂开始")
            else:
                self.opt_cj_mode.set("模式1: 从我的车辆开始")
        self.config["skill_dirs"] = scheme.get("skill_dirs", ["up", "up", "up", "right", "right"])
        if hasattr(self, "update_skill_grid"):
            self.update_skill_grid()
        if hasattr(self, "lbl_race"):
            self.lbl_race.configure(text=f"执行: 0 / {scheme.get('race_count', 99)}")
        if hasattr(self, "lbl_car"):
            self.lbl_car.configure(text=f"执行: 0 / {scheme.get('buy_count', 30)}")
        if hasattr(self, "lbl_cj"):
            self.lbl_cj.configure(text=f"执行: 0 / {scheme.get('cj_count', 30)}")
        if hasattr(self, "lbl_sc"):
            self.lbl_sc.configure(text=f"执行: 0 / {scheme.get('sell_count', 30)}")

    def new_scheme(self):
        """新建方案"""
        schemes = self.config.get("schemes", [])
        new_idx = len(schemes)
        current_idx = self.config.get("current_scheme", 0)
        if 0 <= current_idx < len(schemes):
            base = dict(schemes[current_idx])
        else:
            base = {}
        base["name"] = f"方案{new_idx + 1}"
        schemes.append(base)
        # 创建图片目录，从当前方案复制图片
        scheme_dir = os.path.join(APP_DIR, "images", f"scheme_{new_idx + 1}")
        os.makedirs(scheme_dir, exist_ok=True)
        current_dir = os.path.join(APP_DIR, "images", f"scheme_{current_idx + 1}")
        if os.path.isdir(current_dir):
            import shutil
            for f in os.listdir(current_dir):
                src = os.path.join(current_dir, f)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(scheme_dir, f))
        self.refresh_scheme_menu()
        self.switch_scheme(new_idx)

    def delete_scheme(self):
        """删除当前方案"""
        schemes = self.config.get("schemes", [])
        if len(schemes) <= 1:
            self.log("至少保留一个方案")
            return
        idx = self.config.get("current_scheme", 0)
        # 删除图片目录
        scheme_dir = os.path.join(APP_DIR, "images", f"scheme_{idx + 1}")
        if os.path.isdir(scheme_dir):
            try:
                import shutil
                shutil.rmtree(scheme_dir)
            except Exception as e:
                self.log(f"删除方案图片目录失败: {e}")
        schemes.pop(idx)
        new_idx = min(idx, len(schemes) - 1)
        self.config["current_scheme"] = new_idx
        for k, v in schemes[new_idx].items():
            self.config[k] = v
        set_scheme_dir(f"scheme_{new_idx + 1}")
        self.template_cache.clear()
        self.scaled_template_cache.clear()
        if hasattr(self, "template_gray_cache"):
            self.template_gray_cache.clear()
        if hasattr(self, "template_transparent_cache"):
            self.template_transparent_cache.clear()
        self.refresh_scheme_menu()
        self.apply_scheme_to_ui(schemes[new_idx])
        self.save_config()
        self.log(f"已删除方案，切换到: {schemes[new_idx].get('name', f'方案{new_idx+1}')}")

    def rename_scheme(self):
        """重命名当前方案"""
        import tkinter.simpledialog as sd
        idx = self.config.get("current_scheme", 0)
        schemes = self.config.get("schemes", [])
        if idx < 0 or idx >= len(schemes):
            return
        old_name = schemes[idx].get("name", f"方案{idx+1}")
        new_name = sd.askstring("重命名方案", "输入新名称:", initialvalue=old_name, parent=self)
        if new_name and new_name.strip():
            schemes[idx]["name"] = new_name.strip()
            self.refresh_scheme_menu()
            self.save_config()
            self.log(f"方案已重命名为: {new_name.strip()}")

    # ====== 方案管理结束 ======

    def is_debug_screenshots_enabled(self):
        if hasattr(self, "var_debug_screenshots"):
            try:
                return bool(self.var_debug_screenshots.get())
            except Exception:
                pass
        return bool(self.config.get("debug_screenshots", False))

    def is_diagnostic_mode_enabled(self):
        if hasattr(self, "var_diagnostic_mode"):
            try:
                return bool(self.var_diagnostic_mode.get())
            except Exception:
                pass
        return bool(self.config.get("diagnostic_mode", False))

    def capture_diagnostic_snapshot(self, name, *, region=None, image_bgr=None,
                                    reason=None, level="WARN", threshold=None,
                                    score=None, meta=None):
        """结构化诊断截图：保存 PNG + 写入 JSONL metadata。

        仅在调试截图或诊断模式开启时写入，否则直接返回。
        """
        if not self.is_debug_screenshots_enabled() and not self.is_diagnostic_mode_enabled():
            return None

        import json as _json
        try:
            if image_bgr is None:
                image_bgr = self.capture_region(region)
            if image_bgr is None:
                return None

            debug_miss_dir = os.path.join(APP_DIR, "debug", "miss")
            os.makedirs(debug_miss_dir, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            ms = int(time.time() * 1000) % 1000
            safe_name = str(name).replace("/", "_").replace("\\", "_").replace(" ", "_")
            score_str = f"_{score:.3f}" if score is not None else ""
            fname = f"{ts}_{safe_name}{score_str}.png"
            fpath = os.path.join(debug_miss_dir, fname)
            cv2.imwrite(fpath, image_bgr)

            # 写 JSONL 条目
            entry = {
                "timestamp": ts,
                "millis": ms,
                "name": name,
                "reason": reason,
                "level": level,
                "threshold": threshold,
                "score": round(score, 4) if score is not None else None,
                "region": list(region) if region else None,
                "screenshot": fname,
                "screen_mean": round(float(image_bgr.mean()), 2),
            }
            if meta and isinstance(meta, dict):
                entry["meta"] = meta

            jsonl_path = os.path.join(APP_DIR, "debug", "diagnostic.jsonl")
            os.makedirs(os.path.dirname(jsonl_path), exist_ok=True)
            with open(jsonl_path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(entry, ensure_ascii=False) + "\n")

            # 同时记录到诊断会话 trace（如果开启）
            trace = getattr(self, "diagnostic_trace", None)
            if trace:
                trace["capture_count"] += 1
                trace["captures"].append({
                    "ts": ts,
                    "kind": "capture",
                    "name": name,
                    "level": str(level or "WARN").upper(),
                    "reason": reason,
                    "file": fpath,
                    "region": list(region) if region else None,
                    "meta": meta or {},
                })

            return fpath
        except Exception:
            return None

    def is_focus_hook_enabled(self):
        return bool(self.config.get("focus_hook_enabled", False))

    def on_debug_mode_toggle(self):
        self.save_config()
        if self.var_debug_mode.get():
            self.log("调试模式已开启：调试截图 + 诊断模式")
        else:
            self.log("调试模式已关闭")

    def on_focus_hook_toggle(self):
        self.save_config()
        if self.var_focus_hook.get():
            self.log("Focus Hook 已启用：将尝试自动Hook游戏窗口使其始终为焦点")
            if self.game_hwnd:
                self.ensure_focus_hook()
            else:
                self.check_and_focus_game()
        else:
            self.log("Focus Hook 已关闭：正在卸载已注入 Hook。")
            self.unload_focus_hook()

    def ensure_focus_hook(self, pid=None):
        if not self.is_focus_hook_enabled():
            return False
        try:
            if pid is None:
                if not self.game_hwnd:
                    return False
                pid_obj = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(self.game_hwnd, ctypes.byref(pid_obj))
                pid = int(pid_obj.value)
            if self.focus_hook_info and self.focus_hook_info.get("pid") == int(pid):
                return True
            if self.focus_hook_info:
                self.unload_focus_hook()
            info = focus_hook_manager.hook_process(pid)
            self.focus_hook_info = info
            self.log(f"🪝 Focus Hook 已注入 | PID={pid} | {info['bits']}位 | {info['dll_name']}")
            return True
        except Exception as e:
            self.log(f"⚠️ Focus Hook 注入失败: {e}")
            return False

    def unload_focus_hook(self):
        info = self.focus_hook_info
        if not info:
            return
        try:
            ok = focus_hook_manager.unhook_process(info["pid"], info["dll_name"])
            if ok:
                self.log(f"🪝 Focus Hook 已卸载 | PID={info['pid']} | {info['dll_name']}")
            else:
                self.log(f"🪝 Focus Hook 未找到已加载模块，可能已随游戏退出: {info['dll_name']}")
        except Exception as e:
            self.log(f"⚠️ Focus Hook 卸载失败: {e}")
        finally:
            self.focus_hook_info = None

    def auto_focus_hook_on_start(self):
        if self.is_focus_hook_enabled():
            self.log("Focus Hook 配置已启用，启动后自动尝试 Hook 游戏窗口。")
            self.check_and_focus_game()

    def on_app_close(self):
        try:
            self.stop_all()
        except Exception:
            pass
        try:
            self.unload_focus_hook()
        except Exception:
            pass
        self.destroy()

    def setup_ui(self):
        self.configure(fg_color="#0F141B")

        # ====== 方案切换栏 ======
        self.scheme_bar = ctk.CTkFrame(self, fg_color="#18202B", height=40, corner_radius=8)
        self.scheme_bar.pack(fill="x", padx=16, pady=(8, 0))
        self.scheme_bar.pack_propagate(False)
        ctk.CTkLabel(
            self.scheme_bar,
            text="当前方案:",
            font=ctk.CTkFont(weight="bold", size=14),
            text_color="#F1C40F"
        ).pack(side="left", padx=(12, 8))
        self.scheme_menu = ctk.CTkOptionMenu(
            self.scheme_bar,
            values=["方案1"],
            width=220,
            height=28,
            command=self.on_scheme_switch
        )
        self.scheme_menu.pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            self.scheme_bar, text="新建", width=60, height=28,
            command=self.new_scheme
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            self.scheme_bar, text="删除", width=60, height=28,
            fg_color="#C0392B", hover_color="#A93226",
            command=self.delete_scheme
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            self.scheme_bar, text="重命名", width=70, height=28,
            command=self.rename_scheme
        ).pack(side="left", padx=4)

        # 版本标签（右侧）
        self.version_label = ctk.CTkLabel(
            self.scheme_bar,
            text=f"v{CURRENT_VERSION}",
            font=ctk.CTkFont(size=12),
            text_color="#7F8C8D",
            cursor="hand2"
        )
        self.version_label.pack(side="right", padx=(0, 16))
        self.version_label.bind("<Button-1>", lambda e: self._open_releases_page())
        self._update_blinking = False

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
        box_race.configure(height=300)
        self.entry_share = ctk.CTkEntry(box_race, width=128, height=30, justify="center", placeholder_text="蓝图数字代码")
        self.entry_share.insert(0, self.config.get("share_code", "167982162"))
        self.entry_share.pack(pady=(2, 4))

        # DirectML 加速选项
        self.var_directml = ctk.BooleanVar(value=self.config.get("use_directml", True))
        self.chk_directml = ctk.CTkCheckBox(box_race, text="DirectML加速OCR\n会占用少量显存", variable=self.var_directml, width=160, font=ctk.CTkFont(size=13))
        self.chk_directml.pack(pady=(2, 4))

        # Xbox 版本专属：分享码输入超时设置
        if hasattr(self, 'input_share_code_foreground'):
            timeout_frame = ctk.CTkFrame(box_race, fg_color="transparent")
            timeout_frame.pack(pady=(0, 8))
            ctk.CTkLabel(timeout_frame, text="输入前等待(秒):", font=ctk.CTkFont(size=14), text_color="#8899AA").pack(side="left", padx=(0, 6))
            self.entry_sharecode_timeout = ctk.CTkEntry(timeout_frame, width=44, height=26, justify="center")
            self.entry_sharecode_timeout.insert(0, str(self.config.get("sharecode_timeout", 10)))
            self.entry_sharecode_timeout.pack(side="left")

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
            width=340,
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

        # ====== 超级抽奖模式选择 ======
        saved_cj_mode = self.config.get("cj_mode", 2)
        self.opt_cj_mode = ctk.CTkOptionMenu(
            left_cj,
            values=["模式1: 从我的车辆开始", "模式2: 从设计与喷涂开始"],
            width=140,
            height=26,
            corner_radius=6,
        )
        if saved_cj_mode == 2:
            self.opt_cj_mode.set("模式2: 从设计与喷涂开始")
        else:
            self.opt_cj_mode.set("模式1: 从我的车辆开始")
        self.opt_cj_mode.pack(pady=(0, 6))
        # ==============================

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
            self.config_frame, self.var_chk3, self.config.get("next_3", 4)
        )

        # ====== 卖车卡片 ======
        self.var_chk4 = ctk.BooleanVar(value=self.config.get("chk_4", True))
        box_sell, self.btn_sell, self.entry_sc, self.lbl_sc = create_box(
            self.config_frame,
            "4. 移除车辆",
            "开始",
            lambda: self.start_pipeline("sell"),
            "#C0392B",
            self.config.get("sell_count", 30),
        )
        self.next_frame4, self.entry_next4, self.chk4 = create_next_step(
            self.config_frame, self.var_chk4, self.config.get("next_4", 1)
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
        ctk.CTkLabel(self.global_settings_frame, text="单局跑图超时检测:").pack(side="left", padx=(0, 5))
        self.entry_stuck_timeout = ctk.CTkEntry(self.global_settings_frame, width=68, height=28, justify="center", corner_radius=6)
        self.entry_stuck_timeout.insert(0, str(self.config.get("stuck_timeout", 60)))
        self.entry_stuck_timeout.pack(side="left", padx=(0, 16))
        self.entry_stuck_timeout.bind("<FocusOut>", lambda e: self.save_config())
        self.entry_stuck_timeout.bind("<Return>", lambda e: self.save_config())
        self.var_auto_restart = ctk.BooleanVar(value=self.config.get("auto_restart", True))
        self.cb_auto_restart = ctk.CTkCheckBox(self.global_settings_frame, text="闪退自动重启", variable=self.var_auto_restart)
        self.cb_auto_restart.pack(side="left", padx=(4, 12))

        self.var_focus_hook = ctk.BooleanVar(value=self.config.get("focus_hook_enabled", False))
        self.cb_focus_hook = ctk.CTkCheckBox(
            self.global_settings_frame,
            text="Hook游戏窗口使其始终为焦点",
            variable=self.var_focus_hook,
            command=self.on_focus_hook_toggle,
        )
        self.cb_focus_hook.pack(side="left", padx=(0, 16))
        # ====== 任务完成自动关游戏/关机 ======
        self.var_auto_close = ctk.BooleanVar(value=self.config.get("auto_close_game", False))
        self.cb_auto_close = ctk.CTkCheckBox(
            self.global_settings_frame,
            text="任务完成关游戏",
            variable=self.var_auto_close,
            command=self.save_config,
        )
        self.cb_auto_close.pack(side="left", padx=(0, 12))
        self.var_auto_shutdown = ctk.BooleanVar(value=self.config.get("auto_shutdown", False))
        self.cb_auto_shutdown = ctk.CTkCheckBox(
            self.global_settings_frame,
            text="任务完成关机",
            variable=self.var_auto_shutdown,
            command=self.save_config,
        )
        self.cb_auto_shutdown.pack(side="left", padx=(0, 16))
        # ====== 调试模式（调试截图 + 诊断模式合一） ======
        self.var_debug_mode = ctk.BooleanVar(value=self.config.get("debug_screenshots", False) or self.config.get("diagnostic_mode", False))
        self.cb_debug_mode = ctk.CTkCheckBox(
            self.global_settings_frame,
            text="调试模式",
            variable=self.var_debug_mode,
            command=self.on_debug_mode_toggle,
        )
        self.cb_debug_mode.pack(side="left", padx=(0, 12))
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

        self.entry_next1.bind("<FocusOut>", lambda e: self.normalize_step_entry(self.entry_next1, 2))
        self.entry_next2.bind("<FocusOut>", lambda e: self.normalize_step_entry(self.entry_next2, 3))
        self.entry_next3.bind("<FocusOut>", lambda e: self.normalize_step_entry(self.entry_next3, 1))
        if hasattr(self, "entry_next4"):
            self.entry_next4.bind("<FocusOut>", lambda e: self.normalize_step_entry(self.entry_next4, 1))


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

        # ====== 日志级别筛选 + 导出 ======
        log_toolbar = ctk.CTkFrame(self.bottom_frame, fg_color="transparent")
        log_toolbar.pack(side="left", fill="y", padx=(0, 6))
        ctk.CTkLabel(log_toolbar, text="级别", font=ctk.CTkFont(size=12)).pack(side="top", pady=(2, 0))
        self.log_level_var = ctk.StringVar(value="ALL")
        self.log_level_menu = ctk.CTkOptionMenu(
            log_toolbar,
            values=["ALL", "INFO", "WARN", "ERROR", "DEBUG"],
            variable=self.log_level_var,
            width=80,
            height=24,
            font=ctk.CTkFont(size=12),
            command=self._apply_log_filter,
        )
        self.log_level_menu.pack(side="top", pady=(2, 4))
        self.btn_export_log = ctk.CTkButton(
            log_toolbar,
            text="导出",
            width=80,
            height=24,
            font=ctk.CTkFont(size=12),
            command=self._export_log,
        )
        self.btn_export_log.pack(side="top", pady=(0, 2))

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
        # 右键菜单：复制 / 复制全部 / 导出日志
        self._log_menu = tk.Menu(self, tearoff=0)
        self._log_menu.add_command(label="复制选中", command=self._copy_log_selection)
        self._log_menu.add_command(label="复制全部", command=self._copy_log_all)
        self._log_menu.add_separator()
        self._log_menu.add_command(label="导出日志到文件", command=self._export_log)
        self.log_box.bind("<Button-3>", self._show_log_menu)

        # 日志缓冲（用于级别筛选）
        self._log_buffer = []

        # 刷新方案下拉菜单
        self.refresh_scheme_menu()

    def _show_log_menu(self, event):
        try:
            self._log_menu.post(event.x_root, event.y_root)
        except Exception:
            pass

    def _copy_log_selection(self):
        try:
            self.log_box.configure(state="normal")
            sel = self.log_box.get("sel.first", "sel.last")
            self.log_box.configure(state="disabled")
            if sel:
                self.clipboard_clear()
                self.clipboard_append(sel)
        except Exception:
            pass

    def _copy_log_all(self):
        try:
            self.log_box.configure(state="normal")
            text = self.log_box.get("1.0", "end-1c")
            self.log_box.configure(state="disabled")
            if text:
                self.clipboard_clear()
                self.clipboard_append(text)
        except Exception:
            pass

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
        sell_total = totals.get("移除车辆", 0.0)

        active_task = getattr(self, "active_task_name", "")
        if active_task == "循环跑图":
            race_total += task_elapsed
        elif active_task == "批量买车":
            buy_total += task_elapsed
        elif active_task == "超级抽奖":
            cj_total += task_elapsed
        elif active_task == "移除车辆":
            sell_total += task_elapsed

        try:
            self.lbl_runtime_task_time.configure(text=self.format_elapsed(task_elapsed))
            self.lbl_runtime_total_time.configure(text=self.format_elapsed(total_elapsed))
            self.lbl_runtime_totals.configure(
                text=(
                    f"跑图 {self.format_elapsed(race_total)} | "
                    f"买车 {self.format_elapsed(buy_total)} | "
                    f"超抽 {self.format_elapsed(cj_total)} | "
                    f"卖车 {self.format_elapsed(sell_total)}"
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
                progress_text = f"{current_val} / {max_val}"
                self.ui_call(self.lbl_runtime_progress.configure, text=progress_text)

                # 同步更新顶部三个任务卡片上的“执行: x / y”。旧逻辑只更新运行面板，
                # 导致上方卡片一直停在“执行: 0 / 99”。
                label_map = {
                    "循环跑图": getattr(self, "lbl_race", None),
                    "批量买车": getattr(self, "lbl_car", None),
                    "超级抽奖": getattr(self, "lbl_cj", None),
                    "移除车辆": getattr(self, "lbl_sc", None),
                }
                target_label = label_map.get(task_name)
                if target_label:
                    self.ui_call(target_label.configure, text=f"执行: {current_val} / {max_val}")
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
                # 不在停止/完成时清零任务进度和大循环计数，避免刚完成的计数被待机状态覆盖成 0/0。
                # 新任务开始时 start_pipeline 会重新初始化并刷新这些值。
                self.lbl_runtime_task_time.configure(text="00:00:00")
                self.lbl_runtime_total_time.configure(text="00:00:00")
                self.lbl_runtime_totals.configure(text="跑图 00:00:00 | 买车 00:00:00 | 超抽 00:00:00 | 卖车 00:00:00")
                self.btn_runtime_pause.configure(state="disabled", text="暂停 F9", fg_color="#F1C40F", hover_color="#D4AC0D", text_color="#111827")
                self.btn_runtime_stop.configure(state="disabled")
                self.btn_stop.configure(text="等待指令 (F8)", fg_color="#222B36", hover_color="#2F3B4A")
        except Exception:
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

    def log(self, message, level=None):
        # 自动推断日志级别
        if level:
            resolved_level = str(level).upper()
        else:
            text = str(message or "")
            upper_text = text.upper()
            # ERROR: 真正的错误、异常中断
            if (upper_text.startswith("[ERROR]") or "异常" in text or "中断" in text
                    or "失败" in text and "点击" not in text
                    or "无法" in text
                    or "拒绝" in text
                    or "连续 3 次" in text):
                resolved_level = "ERROR"
            # WARN: 未找到、跳过、放弃、超时、黑屏、输入无效
            elif (upper_text.startswith("[WARN]") or "未找到" in text or "未命中" in text
                    or "未识别" in text or "不足" in text
                    or "超时" in text or "放弃" in text
                    or "跳过" in text or "黑屏" in text
                    or "全黑" in text or "截图异常" in text
                    or "未生效" in text or "刷完" in text
                    or "丢失" in text or "卡死" in text
                    or "无效" in text):
                resolved_level = "WARN"
            # DEBUG: 匹配分数、坐标、调试截图路径、内部状态
            elif (upper_text.startswith("[DEBUG]") or "[Calibration]" in text
                    or "[Diagnostic]" in text or "[GrayMatch]" in text
                    or "[ImageMatch]" in text or "[AlphaMatch]" in text
                    or "[StrictCar]" in text or "[Capture]" in text
                    or "[BuyScroll]" in text or "[DownScroll]" in text
                    or "[LoadTemplate]" in text or "[ScaledTpl" in text
                    or "[CarSelect" in text or "[UpgradeDebug]" in text
                    or "[Safety]" in text or "[BuyNewUsed]" in text
                    or "最佳缩放" in text or "截图均值" in text
                    or "debug" in text.lower() and "保存" in text):
                resolved_level = "DEBUG"
            else:
                resolved_level = "INFO"

        curr_time = time.strftime("%H:%M:%S")
        if resolved_level == "INFO":
            full_msg = f"[{curr_time}] {message}"
        else:
            full_msg = f"[{curr_time}] [{resolved_level}] {message}"

        # 缓存日志用于级别筛选
        self._log_buffer.append((resolved_level, full_msg))
        if len(self._log_buffer) > 2000:
            self._log_buffer = self._log_buffer[-1500:]

        # 诊断日志写入文件
        self.record_diagnostic_log(resolved_level, message, ts=time.strftime("%Y-%m-%d %H:%M:%S"))

        # 节流刷新（v1.2.10.1）：每 100ms 批量渲染一次，避免高频日志塞爆 Tk 事件队列
        self._log_pending.append((resolved_level, full_msg))
        if not self._log_flush_scheduled:
            self._log_flush_scheduled = True
            try:
                self.after(100, self._flush_logs)
            except Exception:
                self._log_flush_scheduled = False

    def _flush_logs(self):
        """批量渲染待处理日志（UI 线程，100ms 节流）"""
        self._log_flush_scheduled = False
        pending = self._log_pending
        self._log_pending = []
        try:
            if pending:
                current_filter = getattr(self, "log_level_var", None)
                filter_level = current_filter.get() if current_filter else "ALL"
                if filter_level != "ALL":
                    pending = [(lvl, msg) for lvl, msg in pending if lvl == filter_level]
                if pending:
                    self.log_box.configure(state="normal")
                    self.log_box.insert("end", "".join(msg + "\n" for _, msg in pending))
                    self._log_line_count = getattr(self, "_log_line_count", 0) + len(pending)
                    if self._log_line_count > getattr(self, "_log_trim_threshold", 1200):
                        keep_lines = getattr(self, "_log_keep_lines", 800)
                        self.log_box.delete("1.0", f"end-{keep_lines + 1}lines")
                        self._log_line_count = keep_lines
                    self.log_box.see("end")
                    self.log_box.configure(state="disabled")
        except Exception:
            pass
        # 渲染期间新到的消息再约一轮（不丢日志）
        if self._log_pending and not self._log_flush_scheduled:
            self._log_flush_scheduled = True
            try:
                self.after(100, self._flush_logs)
            except Exception:
                self._log_flush_scheduled = False

    def _apply_log_filter(self, choice=None):
        """根据级别筛选重新渲染日志框。"""
        filter_level = self.log_level_var.get()
        def rebuild():
            try:
                self.log_box.configure(state="normal")
                self.log_box.delete("1.0", "end")
                for lvl, msg in self._log_buffer:
                    if filter_level == "ALL" or lvl == filter_level:
                        self.log_box.insert("end", msg + "\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
            except Exception:
                pass
        self.ui_call(rebuild)

    def _export_log(self):
        """导出当前日志到文件。"""
        try:
            export_dir = os.path.join(APP_DIR, "debug_logs")
            os.makedirs(export_dir, exist_ok=True)
            filename = f"log_{time.strftime('%Y%m%d_%H%M%S')}.txt"
            filepath = os.path.join(export_dir, filename)
            with open(filepath, "w", encoding="utf-8-sig") as f:
                for lvl, msg in self._log_buffer:
                    f.write(msg + "\n")
            self.log(f"日志已导出到: {filepath}")
        except Exception as e:
            self.log(f"导出日志失败: {e}", level="ERROR")

    def record_diagnostic_log(self, level, message, ts=None):
        """写入诊断日志到 JSONL 文件（仅诊断模式开启时）。"""
        trace = getattr(self, "diagnostic_trace", None)
        if not trace:
            return
        event = {
            "ts": ts or time.strftime("%Y-%m-%d %H:%M:%S"),
            "kind": "log",
            "level": str(level or "INFO").upper(),
            "message": str(message or ""),
        }
        try:
            with open(trace["logs_path"], "a", encoding="utf-8-sig") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            return
        trace["log_count"] += 1
        trace["log_levels"][event["level"]] = trace["log_levels"].get(event["level"], 0) + 1

    def start_diagnostic_trace_session(self, session_name):
        """启动诊断会话，创建报告目录和 JSONL 文件。"""
        if not bool(self.config.get("diagnostic_mode", False)):
            self.diagnostic_trace = None
            return
        report_dir = os.path.join(APP_DIR, "diagnostic_reports", f"{time.strftime('%Y%m%d_%H%M%S')}_{session_name}")
        os.makedirs(report_dir, exist_ok=True)
        captures_dir = os.path.join(report_dir, "captures")
        os.makedirs(captures_dir, exist_ok=True)
        self.diagnostic_trace = {
            "session_name": session_name,
            "report_dir": report_dir,
            "events_path": os.path.join(report_dir, "events.jsonl"),
            "logs_path": os.path.join(report_dir, "logs.jsonl"),
            "captures_dir": captures_dir,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "event_count": 0,
            "hit_count": 0,
            "miss_count": 0,
            "log_count": 0,
            "log_levels": {},
            "capture_count": 0,
            "capture_keys": set(),
            "captures": [],
        }
        self.log(f"[Diagnostic] 已开启诊断记录: {report_dir}", level="DEBUG")

    def finish_diagnostic_trace_session(self):
        """结束诊断会话，生成文本报告。"""
        trace = getattr(self, "diagnostic_trace", None)
        if not trace:
            return
        summary = {
            "session_name": trace["session_name"],
            "started_at": trace["started_at"],
            "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "event_count": trace["event_count"],
            "hit_count": trace["hit_count"],
            "miss_count": trace["miss_count"],
            "log_count": trace["log_count"],
            "log_levels": dict(trace["log_levels"]),
            "capture_count": trace["capture_count"],
        }
        try:
            with open(os.path.join(trace["report_dir"], "summary.json"), "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log(f"[Diagnostic] 诊断摘要写入失败: {e}", level="ERROR")
        # 生成可读报告
        try:
            lines = [
                "FH6Auto 诊断记录报告",
                f"会话: {summary['session_name']}",
                f"开始时间: {summary['started_at']}",
                f"结束时间: {summary['finished_at']}",
                "",
                "一、整体结果",
                f"- 总识图次数: {summary['event_count']}",
                f"- 命中次数: {summary['hit_count']}",
                f"- 未命中次数: {summary['miss_count']}",
                f"- 日志条数: {summary['log_count']}",
                f"- 失败截图数: {summary['capture_count']}",
                "",
                "二、日志等级统计",
            ]
            for lvl in ["INFO", "WARN", "ERROR", "DEBUG"]:
                lines.append(f"- {lvl}: {summary['log_levels'].get(lvl, 0)}")
            lines.append("")
            lines.append("三、关键截图")
            if trace["captures"]:
                for idx, cap in enumerate(trace["captures"], 1):
                    lines.append(f"{idx}. [{cap.get('level', '-')}] {cap.get('name', '-')} -> {os.path.basename(cap.get('file', '-'))}")
                    if cap.get("reason"):
                        lines.append(f"   原因: {cap['reason']}")
            else:
                lines.append("- 本次没有生成截图。")
            lines.append("")
            lines.append("四、运行日志")
            # 读取日志文件
            logs = []
            if os.path.exists(trace["logs_path"]):
                with open(trace["logs_path"], "r", encoding="utf-8-sig") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            logs.append(json.loads(line))
                        except Exception:
                            continue
            if logs:
                for idx, le in enumerate(logs, 1):
                    lines.append(f"{idx}. [{le.get('ts', '-')}] [{le.get('level', 'INFO')}] {le.get('message', '')}")
            else:
                lines.append("- 无日志记录。")
            report_txt = os.path.join(trace["report_dir"], "report.txt")
            with open(report_txt, "w", encoding="utf-8-sig") as f:
                f.write("\n".join(lines))
        except Exception as e:
            self.log(f"[Diagnostic] 生成报告失败: {e}", level="ERROR")
        self.log(f"[Diagnostic] 诊断报告已保存: {trace['report_dir']}")
        self.diagnostic_trace = None

    def start_pipeline(self, start_step):
        if self.is_running:
            return

        self.is_running = True
        self.save_config()
        self.start_anti_cheat_heartbeat()

        # OCR 加速选项
        self.use_directml = self.var_directml.get()

        self.reset_run_stats()
        self.update_running_state("running")
        self.update_timer()
        self.update_running_ui("初始化中...")
        self.race_counter = 0
        self.car_counter = 0
        self.cj_counter = 0
        self.sc_count = 0
        self.global_loop_current = 0

        def runner():
            task_finished_normally = False
            self.start_diagnostic_trace_session(f"pipeline_{start_step}")
            if not self.check_and_focus_game():
                self.finish_diagnostic_trace_session()
                self.stop_all()
                return

            steps = ["race", "buy", "cj", "sell"]
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
                    elif step_name == "sell":
                        success = self.find_and_remove_consumable_car(int(self.entry_sc.get()))
                except Exception as e:
                    import traceback
                    self.log(f"执行模块 {step_name} 时异常: {e}")
                    self.log(f"[TRACEBACK]\n{traceback.format_exc()}")
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
                        try: next_idx = max(0, min(4, int(self.entry_next1.get()) - 1))
                        except Exception: next_idx = 1
                    else: break
                elif curr_idx == 1:
                    if self.var_chk2.get():
                        try: next_idx = max(0, min(4, int(self.entry_next2.get()) - 1))
                        except Exception: next_idx = 2
                    else: break
                elif curr_idx == 2:
                    if self.var_chk3.get():
                        try: next_idx = max(0, min(4, int(self.entry_next3.get()) - 1))
                        except Exception: next_idx = 3
                    else: break
                elif curr_idx == 3:
                    if self.var_chk4.get():
                        try: next_idx = max(0, min(3, int(self.entry_next4.get()) - 1))
                        except Exception: next_idx = 0
                    else: break

                if next_idx <= curr_idx:
                    self.global_loop_current += 1

                    if self.global_loop_current > total_loops:
                        self.log("达到设定的总循环次数,任务圆满结束。")
                        task_finished_normally = True
                        break

                    self.log(f"开启新一轮大循环 ({self.global_loop_current}/{total_loops})")

                    self.ui_call(self.lbl_runtime_loop.configure, text=f"{self.global_loop_current} / {total_loops}")

                    # 等待游戏画面恢复（过场/加载可能黑屏）
                    self.log("等待游戏画面恢复...")
                    for _ in range(30):
                        if not self.is_running:
                            break
                        screen = self.capture_region(self.regions.get("全界面"))
                        if screen is not None and screen.mean() > 10:
                            break
                        time.sleep(1.0)
                    time.sleep(2.0)

                    self.race_counter = 0
                    self.car_counter = 0
                    self.cj_counter = 0
                    self.sc_count = 0

                curr_idx = next_idx

            # ====== 任务完成后自动关游戏/关机 ======
            if task_finished_normally and self.is_running:
                if self.var_auto_close.get():
                    self.log("【任务圆满完成】已开启自动关游戏，30秒后强制关闭游戏...")
                    for _ in range(30):
                        if not self.is_running: break
                        time.sleep(1)
                    if self.is_running:
                        try:
                            os.system('taskkill /F /IM forzahorizon6.exe /T')
                            self.log("已强行关闭游戏进程。")
                            time.sleep(2)
                        except Exception as e:
                            self.log(f"关闭游戏失败: {e}")
                if self.var_auto_shutdown.get() and self.is_running:
                    self.log("【任务圆满完成】触发自动关机！系统将在 3 分钟后关闭！")
                    self.log("提示：如需取消关机，请按 Win+R 键，输入 shutdown -a 并回车。")
                    os.system("shutdown -s -f -t 180")
            # ==============================================
            self.stop_all()

        self.current_thread = threading.Thread(target=runner, daemon=True)
        self.current_thread.start()

    def stop_all(self):
        if not self.is_running:
            return

        self.is_running = False
        self.is_paused = False  # <--- 【新增】彻底停止时必须解除暂停锁
        self.stop_anti_cheat_heartbeat()
        self.finish_diagnostic_trace_session()

        # 清理 OCR 引擎
        if hasattr(self, 'stop_ocr_engine'):
            self.stop_ocr_engine()

        for key in list(DIK_CODES.keys()) + ["w", "e", "y", "enter", "esc", "up", "down", "left", "right", "space", "backspace"]:
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


if __name__ == "__main__":
    app = FH_UltimateBot()
    app.mainloop()
