import ctypes
import time
import subprocess
import win32gui
import json
import os
import cv2
import fh6_backend
from config import APP_DIR


class RecoveryMixin:
    """故障恢复与游戏状态管理"""

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
                            title_buf = ctypes.create_unicode_buffer(length + 1)
                            ctypes.windll.user32.GetWindowTextW(hwnd, title_buf, length + 1)
                            hwnds.append((hwnd, title_buf.value))
                return True

            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            ctypes.windll.user32.EnumWindows(EnumWindowsProc(foreach_window), 0)

            if hwnds:
                preferred = [item for item in hwnds if item[1].strip() == "Forza Horizon 6"]
                if not preferred:
                    preferred = [item for item in hwnds if "Forza Horizon 6" in item[1]]
                hwnd, window_title = (preferred or hwnds)[0]
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
                    if hasattr(self, "ensure_focus_hook"):
                        self.ensure_focus_hook(target_pid)

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
        # 保存最终截图供调试
        try:
            screen_bgr = self.capture_region(self.regions.get("全界面"))
            if screen_bgr is not None:
                debug_path = self.capture_diagnostic_snapshot(
                    "enter_menu_failed",
                    region=self.regions.get("全界面"),
                    image_bgr=screen_bgr,
                    reason="60次尝试均未进入菜单",
                    level="ERROR",
                    meta={"screen_mean": round(float(screen_bgr.mean()), 2)}
                )
                if debug_path:
                    self.log(f"[Debug] 最终截图已保存: {debug_path} | 截图均值: {screen_bgr.mean():.1f}")
        except Exception:
            pass
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
