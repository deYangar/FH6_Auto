import time
import os
import json
import threading
import cv2
import numpy as np
from config import APP_DIR
from recognition_config import get_recognition_profile
from ocr_onnx import OCREngine
from constants import DIK_CODES


class RaceMixin:
    """循环跑图业务逻辑（Xbox 版）+ F3 测试找图"""

    # OCR 引擎（ONNX，延迟初始化）
    _ocr_engine = None

    def get_ocr_engine(self):
        """获取或创建 OCR 引擎"""
        if self._ocr_engine is None:
            use_dml = getattr(self, 'use_directml', False)
            self._ocr_engine = OCREngine(log_func=self.log, use_directml=use_dml)
            self._ocr_engine.init()
        return self._ocr_engine

    def stop_ocr_engine(self):
        """停止 OCR 引擎"""
        if self._ocr_engine is not None:
            self._ocr_engine = None
            self.log("[OCR] 引擎已释放")

    def ocr_detect_race_result(self):
        """
        用 OCR 检测当前比赛结果（win/fail）
        截图后发给 OCR 引擎，返回 'win' / 'fail' / 'unknown'
        """
        engine = self.get_ocr_engine()
        if engine is None or engine.session is None:
            self.log("OCR 引擎不可用")
            return None

        # 截图
        img = self.capture_region(self.regions["全界面"])
        if img is None:
            return None

        result = engine.detect(img)
        status = result.get("status")
        if status == "error":
            self.log(f"OCR 错误: {result.get('error', 'unknown')}", level="DEBUG")
            return None
        if status != "unknown":
            self.log(f"OCR 识别: {result.get('text', '')} -> {status}", level="DEBUG")
        return status

    def input_share_code_foreground(self, code_text):
        code_text = "".join(c for c in str(code_text) if c.isdigit())
        if not code_text:
            self.log("蓝图分享代码为空，无法搜索赛事。")
            return False

        self.log("分享码输入需要 Xbox 文本框焦点，临时切换到前台真实输入...")
        if not self.focus_game_for_foreground_input(timeout=2.0):
            return False

        # Backspace -> Up -> Enter 打开搜索框
        steps = [
            ("backspace", 0.08, 0.8),
            ("up", 0.08, 0.4),
            ("enter", 0.08, 1.2),
        ]
        for key, delay, wait_after in steps:
            if not self.foreground_press(key, delay=delay):
                self.log(f"分享码输入前置按键失败: {key}")
                return False
            time.sleep(wait_after)

        # Xbox 分享码输入前超时等待（搜索框打开后，输入数字前）
        try:
            wait_sec = max(1, int(self.config.get("sharecode_timeout", 10)))
        except (ValueError, TypeError):
            wait_sec = 10
        self.log(f"搜索框已打开，等待 {wait_sec}s 后开始输入...")
        deadline = time.time() + wait_sec
        while self.is_running and time.time() < deadline:
            time.sleep(0.5)
        if not self.is_running:
            return False

        # 用 backspace 清空输入框可能残留的内容
        for _ in range(10):
            self.foreground_press("backspace", delay=0.03)
        time.sleep(0.2)

        if not self.foreground_type_text(code_text, delay=0.05):
            self.log("分享码数字输入失败。")
            return False

        time.sleep(0.4)
        for key, delay, wait_after in [
            ("enter", 0.08, 0.8),
            ("down", 0.08, 0.3),
            ("enter", 0.08, 1.5),
        ]:
            if not self.foreground_press(key, delay=delay):
                self.log(f"分享码提交按键失败: {key}")
                return False
            time.sleep(wait_after)

        self.log(f"已通过前台真实输入提交分享码: {code_text}")
        return True

    def _save_race_car_debug(self, stage, note="", extra=None):
        """保存循环跑图选车阶段的组合识别调试记录。"""
        if hasattr(self, "is_debug_screenshots_enabled") and not self.is_debug_screenshots_enabled():
            return
        try:
            debug_root = os.path.join(APP_DIR, "debug_race_car_select")
            os.makedirs(debug_root, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
            out_dir = os.path.join(debug_root, f"{stamp}_{stage}")
            os.makedirs(out_dir, exist_ok=True)

            img = self.capture_region(self.regions["全界面"])
            meta = {
                "stage": stage,
                "note": note,
                "extra": extra or {},
            }
            if img is not None:
                cv2.imwrite(os.path.join(out_dir, "screen_raw.png"), img)

            with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            self.log(f"[RaceCarDebug] {stage} 已保存: {out_dir}")
        except Exception as e:
            self.log(f"[RaceCarDebug] 保存失败({stage}): {e}")

    def start_test_find_image(self):
        """F3测试:直接反复调用 find_new_consumable_car_strict()"""
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

        self.log("====== 开始 F3 测试找图 ======")

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

                    pos = self.wait_for_new_consumable_car_strict(timeout=3.0, interval=0.2)

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

                self.log(f"====== F3 测试完成:共找到 {len(found_positions)} 个目标 ======")
            except Exception as e:
                self.log(f"F3测试异常: {e}")
            finally:
                self.is_running = False
                self.update_running_state("idle")
                self.update_running_ui("空闲")
                self.stop_ocr_engine()

        t = threading.Thread(target=test_runner, daemon=True)
        t.start()

    def logic_race(self, target_count):
        if self.race_counter >= target_count:
            return True

        self.update_running_ui("循环跑图", self.race_counter, target_count)

        # ====== 任务内锁定 ======
        self.detail_state_confirmed = False

        # ====== 阶段1：进入主菜单 ======
        self.log("阶段1: 进入主菜单...")
        if not self.enter_menu():
            return False

        # ====== 阶段2：导航到 EventLab ======
        self.log("阶段2: 导航到 EventLab...")
        for _ in range(4):
            self.hw_press("pagedown", delay=0.15)
            time.sleep(0.3)
        time.sleep(0.8)

        pos_el = self.wait_for_image_gray(
            "eventlab.png",
            region=self.regions["全界面"],
            threshold=0.7, timeout=5, interval=0.25, fast_mode=True
        )
        if not pos_el:
            self.log("未找到 eventlab")
            return False

        self.game_click(pos_el)
        time.sleep(2.0)

        # 匹配 joinchallenge.png 并点击
        pos_jc = self.wait_for_image_gray(
            "joinchallenge.png",
            region=self.regions["全界面"],
            threshold=0.75, timeout=10, interval=0.3, fast_mode=True
        )
        if not pos_jc:
            self.log("未找到 joinchallenge")
            return False
        self.game_click(pos_jc)
        time.sleep(2.0)
        self.log("阶段2完成: 已进入 EventLab")

        # ====== 阶段3：搜索并进入 ======
        self.log("阶段3: 搜索赛事...")

        code_text = "".join(c for c in self.entry_share.get() if c.isdigit())
        self.log(f"输入分享码: {code_text}")

        if not self.input_share_code_foreground(code_text):
            return False
        self.log("阶段3完成: 分享码已输入")

        # ====== 阶段4：蓝图结果检测 ======
        self.log("阶段4: 检测蓝图结果...")
        blueprint_result = None
        blueprint_wait_deadline = time.time() + 20
        blueprint_last_wait_log = 0.0
        profile_nf = get_recognition_profile(self, "race.blueprint_not_found")
        profile_ready = get_recognition_profile(self, "race.blueprint_ready")
        while self.is_running and time.time() < blueprint_wait_deadline:
            now = time.time()
            if now - blueprint_last_wait_log >= 2.0:
                remaining = max(0.0, blueprint_wait_deadline - now)
                self.log(f"蓝图搜索结果待确认，继续等待... 剩余 {remaining:.1f}s", level="DEBUG")
                blueprint_last_wait_log = now

            if self.find_image_gray(
                "racenotfound.png",
                region=self.regions["全界面"],
                threshold=profile_nf["threshold"],
                fast_mode=profile_nf["fast_mode"],
                invert_mode=profile_nf["invert_mode"],
            ):
                return self.abort_invalid_blueprint_and_back_to_roam()

            blueprint_result = self.find_image_gray(
                "VEI.png",
                region=self.regions["下"],
                threshold=profile_ready["threshold"],
                fast_mode=profile_ready["fast_mode"],
                invert_mode=profile_ready["invert_mode"],
            )
            if blueprint_result:
                self.log("已识别到目标赛事信息")
                break
            time.sleep(0.25)

        if not blueprint_result:
            return self.abort_invalid_blueprint_and_back_to_roam()
        self.log("阶段4完成: 蓝图有效")

        # ====== 阶段5：进入赛事 ======
        self.hw_press("enter")
        time.sleep(2.0)
        self.log("阶段5完成: 已进入赛事，等待自动发车...")

        # ====== 阶段6：跑图循环 ======
        self.log("开始循环跑图!")

        while self.race_counter < target_count:
            if not self.is_running:
                return False

            is_last_lap = (self.race_counter == target_count - 1)

            # 每轮开始前强制清状态
            if self.bg_input:
                self.bg_input.release_all()

            self.log(f"跑图 {self.race_counter + 1}/{target_count}"
                     f"{' (末轮)' if is_last_lap else ''}: 等待赛事加载(15s)...")

            # 等待15秒（游戏展示车辆 ~5s 后自动发车 + 加载时间）
            wait_start = time.time()
            while time.time() - wait_start < 15:
                if not self.is_running:
                    return False
                if self.is_paused:
                    self.check_pause()
                time.sleep(0.5)

            # 开始驾驶：W + Up
            self.hw_key_down("w")
            self.hw_key_down("up")
            driving_keys_held = True

            # 初始化计时器
            race_start_time = time.time()
            last_vram_chk = time.time()
            finished = False
            timeout_triggered = False

            try:
                race_timeout = max(60, int(self.config.get("race_timeout", 300)))
            except Exception:
                race_timeout = 300

            while self.is_running:
                # 暂停处理
                if self.is_paused:
                    if driving_keys_held:
                        self.hw_key_up("w")
                        self.hw_key_up("up")
                        driving_keys_held = False
                    self.check_pause()
                    if self.is_running:
                        self.hw_key_down("w")
                        self.hw_key_down("up")
                        driving_keys_held = True
                    race_start_time = time.time()
                    last_vram_chk = time.time()
                    continue

                now = time.time()

                # 超时检测
                if now - race_start_time > race_timeout:
                    self.log(f"跑图超时(已超过{race_timeout}秒)!触发强制重开...")
                    timeout_triggered = True
                    break

                # 每3秒检查VRAM和点赞弹窗
                if now - last_vram_chk >= 3.0:
                    vram_result = self.check_vramne_during_race()
                    if vram_result is True:
                        self.log("VRAM恢复完成,结束当前跑图流程。")
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
                        self.log("识别到点赞界面,执行回车确认!")
                        self.hw_press("enter")
                    last_vram_chk = now

                # OCR 检测完赛状态
                if now - race_start_time > 10:  # 比赛开始 10s 后才检测
                    ocr_result = self.ocr_detect_race_result()
                    if ocr_result == "win" or ocr_result == "fail":
                        self.hw_key_up("w")
                        self.hw_key_up("up")
                        driving_keys_held = False

                        # 确定该按的键
                        if ocr_result == "win":
                            key = "enter" if is_last_lap else "esc"
                            self.log(f"OCR 检测到 WIN，按 {key.upper()}...")
                        else:
                            key = "esc" if is_last_lap else "enter"
                            self.log(f"OCR 检测到 FAIL，按 {key.upper()}...")

                        self.hw_press(key)

                        # 释放所有按键后等 1s 再验证
                        if self.bg_input:
                            self.bg_input.release_all()
                        time.sleep(1.0)

                        # 二次 OCR 验证
                        verify = self.ocr_detect_race_result()
                        if verify == ocr_result:
                            self.log(f"二次 OCR 仍为 {ocr_result}，按键可能未生效，重按 {key.upper()}...")
                            self.hw_press(key)
                            time.sleep(0.5)

                        finished = True
                        break

                time.sleep(1.0)  # OCR 检测间隔 1 秒

            # 确保按键释放
            self.hw_key_up("w")
            self.hw_key_up("up")
            if self.bg_input:
                self.bg_input.release_all()
                self.log("🧹 已强制释放所有按键")

            if not self.is_running:
                return False

            # 超时处理
            if timeout_triggered:
                time.sleep(0.5)
                self.hw_press("esc")
                time.sleep(1.5)
                pos_restarta = self.wait_for_image_gray(
                    "restarta.png",
                    region=self.regions["全界面"],
                    threshold=0.70, timeout=4.0, interval=0.3, fast_mode=True
                )
                if pos_restarta:
                    self.log("找到 restarta.png,点击重开赛事...")
                    self.game_click(pos_restarta)
                    time.sleep(1.0)
                    self.hw_press("enter")
                    time.sleep(4.0)
                else:
                    self.log("未找到 restarta.png,尝试直接继续...")
                continue

            if not finished:
                return False

            # 最后一轮退出后处理
            if is_last_lap:
                time.sleep(0.4)
                self.handle_author_prompt(release_drive_keys=False)
                if not self.is_running:
                    return False
                time.sleep(0.5)

            self.race_counter += 1
            self.update_running_ui("循环跑图", self.race_counter, target_count)
            self.log(f"循环跑图计数 +1: {self.race_counter}/{target_count}")

        return True

    # ==========================================
    # 以下为跑图流程辅助方法
    # ==========================================

    def abort_invalid_blueprint_and_back_to_roam(self):
        """蓝图搜索后识别到 racenotfound，判定该蓝图已失效，退回漫游。"""
        self.invalid_blueprint_abort = True
        self.log("该蓝图已失效", level="WARN")
        for _ in range(3):
            if not self.is_running:
                return False
            self.hw_press("esc")
            time.sleep(0.35)
        return False

    def handle_author_prompt(self, release_drive_keys=False):
        """检测并处理赛事评价弹窗（点赞/点踩作者）。"""
        profile = get_recognition_profile(self, "race.author_prompt")
        self.log(f"正在检测赛事评价弹窗（最多 {profile['timeout']:.1f}s）...", level="DEBUG")
        pos_author = self.wait_for_any_image_gray(
            ["likeauthor.png", "dislikeauthor.png"],
            region=self.regions["中间"],
            threshold=profile["threshold"],
            timeout=profile["timeout"],
            interval=profile["interval"],
            fast_mode=profile["fast_mode"],
            invert_mode=profile["invert_mode"],
        )
        if not pos_author:
            self.log("未出现赛事评价弹窗，继续后续流程。", level="DEBUG")
            return False

        if release_drive_keys:
            self.hw_key_up("w")
            self.hw_key_up("up")

        self.log("已识别赛事评价弹窗，执行点赞确认。")
        for _ in range(2):
            if not self.is_running:
                return True
            self.hw_press("enter")
            time.sleep(0.35)
        time.sleep(0.8)
        return True
