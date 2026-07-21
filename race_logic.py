# -*- coding: utf-8 -*-
import time
import os
import json
import threading
import cv2
from constants import DIK_CODES
from config import APP_DIR
from recognition_config import get_recognition_profile
from ocr_onnx import OCREngine
from filter_nav import DEFAULT_RACE_FILTER


class RaceMixin:
    """循环跑图业务逻辑 + F3 测试找图"""

    # OCR 引擎（ONNX，延迟初始化）
    _ocr_engine = None

    def get_ocr_engine(self):
        """获取或创建 OCR 引擎（DirectML 切换时自动重建）"""
        use_dml = getattr(self, 'use_directml', False)
        if self._ocr_engine is not None:
            # DirectML 状态变了，重建引擎
            if self._ocr_engine.use_directml != use_dml:
                self.log(f"OCR: DirectML 状态变更 ({self._ocr_engine.use_directml} → {use_dml})，重建引擎...")
                self._ocr_engine = None
        if self._ocr_engine is None:
            self._ocr_engine = OCREngine(log_func=self.log, use_directml=use_dml)
            self._ocr_engine.init()
        return self._ocr_engine

    def ocr_detect_race_result(self, is_last_lap):
        """
        用 OCR 检测画面底部 1/5 区域的按钮文字
        根据按钮布局 + 是否末轮决定该按的键

        按钮布局：
          成功: Esc重试  Enter继续
          失败: Esc退出  Enter重试

        决策：
          非末轮 → 按「重试」
            成功时重试=Esc, 失败时重试=Enter
          末轮 → 按「退出」或「继续」
            成功时继续=Enter, 失败时退出=Esc

        返回 'enter' / 'esc' / None
        """
        engine = self.get_ocr_engine()
        if engine is None or engine.rec_session is None:
            self.log("OCR 引擎不可用")
            return None

        img = self.capture_region(self.regions["全界面"])
        if img is None:
            return None

        text = engine.detect_text_in_region(img, {
            "y_start": 0.9,
            "y_end": 1.0,
            "x_start": 0,
            "x_end": 1.0,
        })

        if not text:
            return None

        # 判断画面类型：成功 or 失败
        is_win_screen = "继续" in text or "续" in text
        is_fail_screen = "退出" in text or "出" in text

        if not is_win_screen and not is_fail_screen:
            return None

        if is_win_screen:
            # 成功: Esc=重试, Enter=继续
            if is_last_lap:
                self.log(f"OCR 成功末轮: {text} → Enter(继续)")
                return "enter"
            else:
                self.log(f"OCR 成功非末轮: {text} → Esc(重试)")
                return "esc"
        else:
            # 失败: Esc=退出, Enter=重试
            if is_last_lap:
                self.log(f"OCR 失败末轮: {text} → Esc(退出)")
                return "esc"
            else:
                self.log(f"OCR 失败非末轮: {text} → Enter(重试)")
                return "enter"

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
                "best": {},
            }
            annotated = img.copy() if img is not None else None

            if img is not None:
                gx, gy, _, _ = self.regions["全界面"]
                for name, color in [("skillcar.png", (0, 0, 255)), ("liketag.png", (0, 255, 0))]:
                    best = None
                    for scale in self.get_scales_to_try(fast_mode=False):
                        tpl, _ = self.get_scaled_template(name, scale)
                        if tpl is None or tpl.shape[0] > img.shape[0] or tpl.shape[1] > img.shape[1]:
                            continue
                        res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
                        _, score, _, loc = cv2.minMaxLoc(res)
                        if best is None or score > best["score"]:
                            best = {
                                "score": float(score),
                                "scale": float(scale),
                                "x": int(loc[0]),
                                "y": int(loc[1]),
                                "w": int(tpl.shape[1]),
                                "h": int(tpl.shape[0]),
                            }
                    meta["best"][name] = best
                    if best:
                        cv2.rectangle(
                            annotated,
                            (best["x"], best["y"]),
                            (best["x"] + best["w"], best["y"] + best["h"]),
                            color,
                            3,
                        )
                        cv2.putText(
                            annotated,
                            f"{name} {best['score']:.3f} s={best['scale']:.3f}",
                            (max(5, best["x"]), max(25, best["y"] - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.65,
                            color,
                            2,
                        )

                best_main = meta["best"].get("skillcar.png")
                if best_main:
                    best_like_near = None
                    x, y, w, h = best_main["x"], best_main["y"], best_main["w"], best_main["h"]
                    pad = 12
                    rx1 = max(0, y - pad)
                    ry1 = max(0, x - pad)
                    rx2 = min(img.shape[0], y + h + pad)
                    ry2 = min(img.shape[1], x + w + pad)
                    roi = img[rx1:rx2, ry1:ry2]
                    for scale in self.get_scales_to_try(fast_mode=False):
                        tpl, _ = self.get_scaled_template("liketag.png", scale)
                        if tpl is None or tpl.shape[0] > roi.shape[0] or tpl.shape[1] > roi.shape[1]:
                            continue
                        res = cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED)
                        _, score, _, loc = cv2.minMaxLoc(res)
                        if best_like_near is None or score > best_like_near["score"]:
                            best_like_near = {
                                "score": float(score),
                                "scale": float(scale),
                                "x": int(loc[0]),
                                "y": int(loc[1]),
                                "abs_x": int(ry1 + loc[0]),
                                "abs_y": int(rx1 + loc[1]),
                                "w": int(tpl.shape[1]),
                                "h": int(tpl.shape[0]),
                            }
                    meta["best"]["liketag_near_skillcar"] = best_like_near
                    if best_like_near:
                        ax, ay = best_like_near["abs_x"], best_like_near["abs_y"]
                        aw, ah = best_like_near["w"], best_like_near["h"]
                        cv2.rectangle(annotated, (ax, ay), (ax + aw, ay + ah), (0, 255, 255), 3)
                        cv2.putText(
                            annotated,
                            f"liketag near {best_like_near['score']:.3f} s={best_like_near['scale']:.3f}",
                            (max(5, ax), min(img.shape[0] - 10, ay + ah + 24)),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.65,
                            (0, 255, 255),
                            2,
                        )

                cv2.imwrite(os.path.join(out_dir, "screen_annotated.png"), annotated)
                cv2.imwrite(os.path.join(out_dir, "screen_raw.png"), img)

            with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            self.log(f"[RaceCarDebug] {stage} 已保存: {out_dir}")
        except Exception as e:
            self.log(f"[RaceCarDebug] 保存失败({stage}): {e}")

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

                self.log(f"F3测试完成,共找到 {len(found_positions)} 个目标。")

            except Exception as e:
                self.log(f"F3测试异常: {e}")
            finally:
                self.stop_all()

        self.current_thread = threading.Thread(target=test_runner, daemon=True)
        self.current_thread.start()

    # ==========================================
    # --- 辅助：从主菜单导航到 EventLab 并进入赛事 ---
    # ==========================================
    def _navigate_to_eventlab_and_enter(self):
        """阶段2~5: 进入主菜单 → EventLab → 分享码 → 蓝图检测 → 进入赛事
        Returns True on success, False on failure."""
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
        self.hw_press("backspace")
        time.sleep(0.8)
        self.hw_press("up")
        time.sleep(0.4)
        self.hw_press("enter")
        time.sleep(0.8)

        code_text = "".join(c for c in self.entry_share.get() if c.isdigit())
        self.log(f"输入分享码: {code_text}")
        for char in code_text:
            if not self.is_running:
                return False
            if char in DIK_CODES:
                self.hw_press(char, delay=0.15)
                time.sleep(0.15)

        time.sleep(0.4)
        self.hw_press("enter")
        time.sleep(0.8)
        self.hw_press("down")
        time.sleep(0.3)
        self.hw_press("enter")
        time.sleep(1.5)
        self.log("阶段3完成: 分享码已输入")

        # ====== 阶段4：蓝图结果检测（OCR 下 1/5 区域） ======
        self.log("阶段4: 检测蓝图结果（OCR）...")
        blueprint_wait_deadline = time.time() + 20
        blueprint_last_wait_log = 0.0
        profile_nf = get_recognition_profile(self, "race.blueprint_not_found")
        engine = self.get_ocr_engine()
        while self.is_running and time.time() < blueprint_wait_deadline:
            now = time.time()
            if now - blueprint_last_wait_log >= 2.0:
                remaining = max(0.0, blueprint_wait_deadline - now)
                self.log(f"蓝图搜索结果待确认，继续等待... 剩余 {remaining:.1f}s")
                blueprint_last_wait_log = now

            if self.find_image_gray(
                "racenotfound.png",
                region=self.regions["全界面"],
                threshold=profile_nf["threshold"],
                fast_mode=profile_nf["fast_mode"],
                invert_mode=profile_nf["invert_mode"],
            ):
                return self.abort_invalid_blueprint_and_back_to_roam()

            img = self.capture_region(self.regions["全界面"])
            if img is not None:
                try:
                    text = engine.detect_text_in_region(img, {
                        "y_start": 0.9,
                        "y_end": 1.0,
                        "x_start": 0,
                        "x_end": 1.0,
                    })
                except Exception as e:
                    self.log(f"OCR 异常，跳过: {e}")
                    text = ""
                if "挑战选项" in text or "挑战" in text:
                    self.log(f"OCR 识别到比赛入口: {text}")
                    break

            time.sleep(0.5)

        if not self.is_running:
            return False
        if time.time() >= blueprint_wait_deadline:
            return self.abort_invalid_blueprint_and_back_to_roam()
        self.log("阶段4完成: 蓝图有效")

        # ====== 阶段5：进入赛事 ======
        self.hw_press("enter")
        time.sleep(2.0)
        self.log("阶段5完成: 已进入赛事，等待自动发车...")
        return True

    # ==========================================
    # --- 模块:跑图（新版 v2 - 适配游戏更新）---
    # ==========================================
    def logic_race(self, target_count):
        if self.race_counter >= target_count:
            return True

        self.update_running_ui("循环跑图", self.race_counter, target_count)

        # ====== 任务内锁定 ======
        self.detail_state_confirmed = False

        # ====== 预热 OCR 引擎 ======
        self.log("预热 OCR 引擎...")
        self.get_ocr_engine()

        # ====== 阶段0：选车 ======
        self.log("阶段0: 进入选车...")
        # 先检测是否已在主菜单，没在才按 ESC
        if not self.find_image_gray("collectionjournal.png", region=self.regions["左"], threshold=0.70, fast_mode=True):
            self.hw_press("esc")
            time.sleep(1.0)
            for _ in range(5):
                if not self.is_running:
                    return False
                if self.find_image_gray("collectionjournal.png", region=self.regions["左"], threshold=0.70, fast_mode=True):
                    break
                time.sleep(1.0)
        self.hw_press("pagedown", delay=0.15)
        time.sleep(1.0)

        pos_cc = self.wait_for_image_gray(
            "changecar.png",
            region=self.regions["全界面"],
            threshold=0.75, timeout=5, interval=0.25, fast_mode=True
        )
        if not pos_cc:
            self.log("未找到 changecar")
            return False
        self.game_click(pos_cc)
        time.sleep(1.0)

        # ====== 选车：OCR 视觉导航筛选（v1.2.10.0，适配不同账号的车辆列表）======
        race_filter = self.get_scheme_filter("race_filter") or DEFAULT_RACE_FILTER
        self.log(f"使用 OCR 视觉导航选车: {' + '.join(race_filter)}")
        if not self.open_and_apply_filter(race_filter, label="跑图选车"):
            self.log("跑图选车筛选失败", level="ERROR")
            return False
        self.hw_press("enter")  # 选中筛出的车辆
        time.sleep(1.0)

        # OCR 检测"上车"（中心区域，比例换算自 1600*900 下 558*287 居中矩形）
        ocr_engine = self.get_ocr_engine()
        img = self.capture_region(self.regions["全界面"])
        text = ""
        if img is not None and ocr_engine:
            text = ocr_engine.detect_text_in_region(img, {
                "y_start": 0.34,
                "y_end": 0.66,
                "x_start": 0.325,
                "x_end": 0.675,
            })
        if "上车" in text:
            self.log(f"OCR 识别到'上车'，按 Enter 上车 (text={text})")
            self.hw_press("enter")
            time.sleep(4.0)
            self.log("选车完成,等待5秒后开始跑图...")
            time.sleep(5.0)
        else:
            self.log(f"OCR 未识别到'上车'，车辆已在驾驶 (text={text})")
            self.hw_press("esc")
            time.sleep(0.7)
            self.hw_press("esc")
            time.sleep(1.0)

        # ====== 阶段1~5：进入主菜单→EventLab→分享码→蓝图→进入赛事 ======
        if not self._navigate_to_eventlab_and_enter():
            return False

        # ====== 阶段7：跑图循环 ======
        self.log("开始循环跑图!")

        recovery_eventlab = False

        while self.race_counter < target_count:
            if not self.is_running:
                return False

            # 检测到异常退出，重新走 EventLab 流程恢复
            if recovery_eventlab:
                recovery_eventlab = False
                self.log("检测到异常退出跑图，重新走 EventLab 流程...")
                if not self._navigate_to_eventlab_and_enter():
                    return False
                self.log("已恢复进入赛事，继续跑图")
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
                    try:
                        ocr_result = self.ocr_detect_race_result(is_last_lap)
                    except Exception as e:
                        import traceback
                        self.log(f"[ERROR] OCR 检测异常，跳过本轮: {e}")
                        self.log(f"[OCR-TRACEBACK]\n{traceback.format_exc()}")
                        ocr_result = None
                    if ocr_result in ("enter", "esc"):
                        self.hw_key_up("w")
                        self.hw_key_up("up")
                        driving_keys_held = False

                        self.log(f"比赛结束，按 {ocr_result.upper()}...")
                        self.hw_press(ocr_result)

                        # 释放所有按键后等 1s 再验证
                        if self.bg_input:
                            self.bg_input.release_all()
                        time.sleep(1.0)

                        # 二次 OCR 验证：如果还能检测到，说明按键没生效，再按一次
                        verify = self.ocr_detect_race_result(is_last_lap)
                        if verify == ocr_result:
                            self.log(f"二次 OCR 仍为 {ocr_result}，按键可能未生效，重按 {ocr_result.upper()}...")
                            self.hw_press(ocr_result)
                            time.sleep(0.5)

                        finished = True
                        break

                time.sleep(0.5)  # OCR 检测间隔 0.5 秒（v1.2.10.2: 1.0 -> 0.5，完赛响应更快）

                # 卡死检测：超过设定秒数未检测到比赛结果，尝试恢复
                stuck_timeout = max(10, int(self.config.get("stuck_timeout", 60)))
                if now - race_start_time > stuck_timeout:
                    self.log(f"已 {stuck_timeout} 秒未检测到比赛结果，尝试按 ESC 检查主菜单...")
                    self.hw_key_up("w")
                    self.hw_key_up("up")
                    driving_keys_held = False
                    if self.bg_input:
                        self.bg_input.release_all()
                    time.sleep(0.5)
                    self.hw_press("esc")
                    time.sleep(1.5)
                    # 检查是否在主菜单
                    pos_menu = self.find_image_gray(
                        "collectionjournal.png",
                        region=self.regions["左"],
                        threshold=0.70, fast_mode=True
                    )
                    if pos_menu:
                        self.log("检测到主菜单，从 EventLab 重新进入赛事...")
                        recovery_eventlab = True
                        break
                    else:
                        self.log("未检测到主菜单，恢复驾驶继续跑图...")
                        self.hw_key_down("w")
                        self.hw_key_down("up")
                        driving_keys_held = True
                        race_start_time = time.time()
                        last_vram_chk = time.time()

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

            # 卡死恢复：跳过计数，重新走 EventLab
            if recovery_eventlab:
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
