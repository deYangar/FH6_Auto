import sys
import os
import shutil
import ctypes

def check_windows_dependencies():
    if sys.platform != "win32":
        return
    missing_dlls = []
    required_dlls = ["vcruntime140.dll", "msvcp140.dll", "vcruntime140_1.dll"]
    for dll in required_dlls:
        try:
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
        ctypes.windll.user32.MessageBoxW(0, msg, "缺少运行库拦截提示", 0x30 | 0x0)

check_windows_dependencies()

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

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
USER_CONFIG_FILE = os.path.join(APP_DIR, "config.json")
LOG_FILE = os.path.join(APP_DIR, "bot_log.txt")
CACHE_DIR = os.path.join(APP_DIR, "cache")
TEMPLATE_CACHE_FILE = os.path.join(CACHE_DIR, "template_cache.pkl")
TEMPLATE_META_FILE = os.path.join(CACHE_DIR, "template_meta.json")
CURRENT_VERSION = "1.2.11.2"

def auto_extract_configs():
    # 只从 APP_DIR 下的历史文件名迁移，不再使用 config/ 子目录
    old_configs = [
        os.path.join(APP_DIR, "bot_config.json"),
        os.path.join(APP_DIR, "bot-config.json"),
    ]
    for old_path in old_configs:
        if os.path.exists(old_path):
            try:
                if not os.path.exists(USER_CONFIG_FILE):
                    shutil.move(old_path, USER_CONFIG_FILE)
                else:
                    os.remove(old_path)
            except Exception as e:
                print(f"[config] 迁移旧配置文件失败: {e}")

def auto_extract_images(folder_name="images"):
    internal_dir = os.path.join(INTERNAL_DIR, folder_name)
    external_dir = os.path.join(APP_DIR, folder_name)
    if not os.path.isdir(internal_dir):
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
                if not os.path.exists(dst_file):
                    shutil.copy2(src_file, dst_file)
    except Exception as e:
        print(f"[auto_extract_images] 释放 images 失败: {e}")

_current_scheme_dir = None

def set_scheme_dir(scheme_dir):
    global _current_scheme_dir
    _current_scheme_dir = scheme_dir

def get_img_path(filename):
    basename = os.path.basename(filename)
    if _current_scheme_dir:
        # 先查外部 APP_DIR 的 scheme 目录
        scheme_path = os.path.join(APP_DIR, "images", _current_scheme_dir, basename)
        if os.path.exists(scheme_path):
            return scheme_path
        # 再查内置 INTERNAL_DIR 的 scheme 目录
        int_scheme_path = os.path.join(INTERNAL_DIR, "images", _current_scheme_dir, basename)
        if os.path.exists(int_scheme_path):
            return int_scheme_path
    # scheme 目录没找到，回退到根目录
    ext_path = os.path.join(APP_DIR, "images", basename)
    if os.path.exists(ext_path):
        return ext_path
    int_path = os.path.join(INTERNAL_DIR, "images", basename)
    if os.path.exists(int_path):
        return int_path
    return filename

def get_asset_path(*parts):
    asset_path = os.path.join(INTERNAL_DIR, "assets", *parts)
    if os.path.exists(asset_path):
        return asset_path
    dev_asset_path = os.path.join(get_app_dir(), "assets", *parts)
    if os.path.exists(dev_asset_path):
        return dev_asset_path
    return None
