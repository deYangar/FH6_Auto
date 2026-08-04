import os
import json
import time
import cv2
import numpy as np
from config import APP_DIR


class CJMixin:
    """超级抽奖业务逻辑"""

    # 两套内置方案的技能路径最终都落在技能树右上节点。使用归一化坐标，
    # 只看节点本身，不受车辆、动态虚化背景和具体 16:9 分辨率影响。
    _MASTERY_FINAL_NODE_ROI = (0.285, 0.170, 0.350, 0.275)
    _MASTERY_COMPLETE_MIN_PINK_RATIO = 0.15
    _MASTERY_POPUP_HEADER_ROI = (0.315, 0.425, 0.685, 0.510)
    _MASTERY_POPUP_MIN_LIME_RATIO = 0.25
    _MASTERY_HOME_DOWN_PRESSES = 6
    _MASTERY_HOME_LEFT_PRESSES = 6
    _MASTERY_LOCAL_RETRIES = 2
    _MASTERY_LOCKED_HINTS = (
        "无法使用额外加成", "未解锁", "尚未解锁", "先解锁", "需要先解锁", "必须先解锁", "相邻的加成",
        "cannotuseperk", "perkunavailable", "notunlocked", "unlockfirst", "mustunlock", "unlockanadjacent",
    )

    @classmethod
    def _mastery_final_node_pink_ratio(cls, image):
        """计算最终节点 ROI 内 FH6 已购买粉色的像素占比。"""
        if image is None or getattr(image, "size", 0) == 0:
            return 0.0
        h, w = image.shape[:2]
        x1r, y1r, x2r, y2r = cls._MASTERY_FINAL_NODE_ROI
        x1, x2 = int(w * x1r), int(w * x2r)
        y1, y2 = int(h * y1r), int(h * y2r)
        roi = image[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
        if roi.size == 0:
            return 0.0
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        pink = cv2.inRange(hsv, np.array((145, 120, 120)), np.array((179, 255, 255)))
        return float(cv2.countNonZero(pink)) / float(pink.shape[0] * pink.shape[1])

    def _mastery_completion_state(self, image=None):
        """返回 (最终超级抽奖节点是否已购买, 粉色像素占比)。"""
        if image is None:
            image = self.capture_region(self.regions["全界面"])
        ratio = self._mastery_final_node_pink_ratio(image)
        return ratio >= self._MASTERY_COMPLETE_MIN_PINK_RATIO, ratio

    @classmethod
    def _mastery_popup_lime_ratio(cls, image):
        """计算中心弹窗标题区域内 FH6 荧光绿的像素占比。"""
        if image is None or getattr(image, "size", 0) == 0:
            return 0.0
        h, w = image.shape[:2]
        x1r, y1r, x2r, y2r = cls._MASTERY_POPUP_HEADER_ROI
        roi = image[
            int(h * y1r):int(h * y2r),
            int(w * x1r):int(w * x2r),
        ]
        if roi.size == 0:
            return 0.0
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        lime = cv2.inRange(hsv, np.array((30, 180, 200)), np.array((50, 255, 255)))
        return float(cv2.countNonZero(lime)) / float(lime.shape[0] * lime.shape[1])

    def _wait_for_mastery_complete(self, timeout=2.0, interval=0.25):
        deadline = time.time() + timeout
        best_ratio = 0.0
        while getattr(self, "is_running", True) and time.time() < deadline:
            complete, ratio = self._mastery_completion_state()
            best_ratio = max(best_ratio, ratio)
            if complete:
                return True, ratio
            time.sleep(interval)
        return False, best_ratio

    def _detect_mastery_popup_state(self):
        """返回 (locked/points/unknown/None, OCR 文本, 荧光绿占比)。"""
        try:
            image = self.capture_region(self.regions["全界面"])
            if image is None:
                return None, "", 0.0
            lime_ratio = self._mastery_popup_lime_ratio(image)
            if lime_ratio < self._MASTERY_POPUP_MIN_LIME_RATIO:
                return None, "", lime_ratio

            engine = self.get_ocr_engine()
            text = ""
            if engine is not None:
                text = engine.detect_text_in_region(image, {
                    "y_start": 0.40,
                    "y_end": 0.60,
                    "x_start": 0.30,
                    "x_end": 0.70,
                })
            normalized = "".join(str(text).lower().split())
            if any(hint in normalized for hint in ("不够", "不足", "notenough")):
                return "points", str(text), lime_ratio
            if any(hint in normalized for hint in self._MASTERY_LOCKED_HINTS):
                return "locked", str(text), lime_ratio
            return "unknown", str(text), lime_ratio
        except Exception as e:
            self.log(f"技能树弹窗检查异常: {e}", level="WARN")
            return None, "", 0.0

    def _detect_mastery_locked_popup(self):
        """兼容接口：返回未解锁/未知中心弹窗的诊断文本。"""
        status, text, lime_ratio = self._detect_mastery_popup_state()
        if status in ("locked", "unknown"):
            return text or f"中心技能弹窗颜色命中(lime_ratio={lime_ratio:.3f})"
        return ""

    def _handle_mastery_popup(self, step):
        """处理一次购买后的弹窗，返回 stop/retry/failed；无弹窗返回 None。"""
        status, text, lime_ratio = self._detect_mastery_popup_state()
        if status is None:
            return None
        if status == "points":
            self._finish_mastery_points_exhausted()
            return "stop"
        if status == "unknown" and self.find_image_gray(
            "SPNE.png", region=self.regions["全界面"], threshold=0.70
        ):
            self._finish_mastery_points_exhausted()
            return "stop"
        diagnostic = text or f"中心技能弹窗颜色命中(lime_ratio={lime_ratio:.3f})"
        if self._dismiss_locked_mastery_popup(step, diagnostic):
            return "retry"
        return "failed"

    def _wait_for_mastery_popup_closed(self, timeout=2.5, interval=0.15):
        deadline = time.time() + timeout
        while getattr(self, "is_running", True) and time.time() < deadline:
            image = self.capture_region(self.regions["全界面"])
            if image is None:
                time.sleep(interval)
                continue
            if self._mastery_popup_lime_ratio(image) < self._MASTERY_POPUP_MIN_LIME_RATIO:
                return True
            time.sleep(interval)
        return False

    def _dismiss_locked_mastery_popup(self, step, text):
        """用 Enter 关闭未解锁弹窗，随后由调用方归位并从头重放技能路径。"""
        self.log(f"检测到技能前置未解锁，关闭弹窗后归位重试: step={step}, OCR={text}", level="WARN")
        self._save_upgrade_debug(
            "mastery_locked_popup",
            note="技能点按键序列未完整生效，OCR 检测到前置技能未解锁弹窗",
            extra={"step": step, "ocr_text": text},
        )
        self.hw_press("enter", delay=0.12, use_send=True)
        if self._wait_for_mastery_popup_closed():
            return True
        self.log("未解锁弹窗按 Enter 后仍未关闭，交给全局恢复。", level="WARN")
        return False

    def _home_mastery_cursor(self):
        """利用技能树边界把任意焦点确定性归位到左下角初始节点。"""
        self.log(
            f"技能树焦点归位: Down×{self._MASTERY_HOME_DOWN_PRESSES} "
            f"Left×{self._MASTERY_HOME_LEFT_PRESSES}"
        )
        for key, count in (
            ("down", self._MASTERY_HOME_DOWN_PRESSES),
            ("left", self._MASTERY_HOME_LEFT_PRESSES),
        ):
            for _ in range(count):
                if not self.is_running:
                    return False
                self.hw_press(key, delay=0.10, use_send=True)
                time.sleep(0.12)
        return True

    def _begin_cj_mastery(self):
        """标记当前已装备车辆尚未完成加点，供全局恢复后直接重试当前车。"""
        self._cj_mastery_in_progress = True
        self._cj_mastery_attempted = False

    def _clear_cj_mastery_state(self, reason):
        was_in_progress = bool(getattr(self, "_cj_mastery_in_progress", False))
        self._cj_mastery_in_progress = False
        self._cj_mastery_attempted = False
        if was_in_progress:
            self.log(f"当前车辆加点流程已完成/结束: {reason}")

    def _finish_mastery_points_exhausted(self):
        self.log("已无技能点，提前结束抽奖!")
        self._clear_cj_mastery_state("技能点不足")
        time.sleep(1.0)
        self.hw_press("enter", delay=0.12, use_send=True)
        time.sleep(0.8)
        for _ in range(3):
            self.hw_press("esc")
            time.sleep(1.0)
        return True

    def _wait_for_cj_vehicle_menu(self, timeout=6.0, hard_timeout=None, min_brightness=5.0):
        """通过设计与喷涂或升级与调校入口确认车辆主菜单。"""
        start = time.time()
        interaction_deadline = start + timeout
        hard_timeout = timeout if hard_timeout is None else max(timeout, hard_timeout)
        hard_deadline = start + hard_timeout
        last_brightness = None
        dark_logged = False

        while self.is_running and time.time() < interaction_deadline and time.time() < hard_deadline:
            now = time.time()
            image = self.capture_region(self.regions["全界面"])
            if image is None:
                interaction_deadline = min(hard_deadline, now + timeout)
                if not dark_logged:
                    self.log("车辆菜单加载期间后台截图暂不可用，暂停计算有效等待时间。", level="WARN")
                    dark_logged = True
            else:
                last_brightness = float(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).mean())
                if last_brightness < min_brightness:
                    interaction_deadline = min(hard_deadline, now + timeout)
                    if not dark_logged:
                        self.log(
                            f"车辆菜单仍在黑屏/过场中，暂停计算有效等待时间: "
                            f"brightness={last_brightness:.1f}"
                        )
                        dark_logged = True
                else:
                    pos = self.find_any_image_gray(
                        ["DandP.png", "UandT-w.png", "UandT-b.png"],
                        region=self.regions["全界面"],
                        threshold=0.68,
                        fast_mode=False,
                    )
                    if pos:
                        if dark_logged:
                            self.log(
                                f"车辆菜单画面已恢复并确认: pos={pos} "
                                f"brightness={last_brightness:.1f}"
                            )
                        return pos

            time.sleep(0.25)

        self.log(
            f"等待车辆菜单确认超时: brightness={last_brightness} "
            f"elapsed={time.time() - start:.1f}s",
            level="WARN",
        )
        return None

    def _enter_cj_vehicle_menu(self):
        """沿正常任务路径从暂停菜单进入车辆主菜单，不选择或更换车辆。"""
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
        time.sleep(5.0)

        pos_bs = self.wait_for_any_image_gray(
            ["buyandsell-w.png", "buyandsell-b.png"],
            region=self.regions["左"],
            threshold=0.75,
            timeout=60,
            interval=0.5,
            fast_mode=True,
        )
        if not pos_bs:
            self.log("未找到购买与出售")
            return False

        self.game_click(pos_bs)
        time.sleep(1.0)
        self.hw_press("pagedown", delay=0.15)
        self.log("进入车辆界面...")
        if self._wait_for_cj_vehicle_menu(timeout=20.0, hard_timeout=60.0):
            return True

        still_pos_bs = self.find_any_image_gray(
            ["buyandsell-w.png", "buyandsell-b.png"],
            region=self.regions["左"],
            threshold=0.75,
            fast_mode=True,
        )
        if still_pos_bs:
            self.log("仍停留在购买与出售页面，重发一次 PageDown 进入车辆菜单。", level="WARN")
            self.hw_press("pagedown", delay=0.15)
            if self._wait_for_cj_vehicle_menu(timeout=20.0, hard_timeout=60.0):
                return True

        self.log("未确认进入车辆菜单，无法继续当前车辆流程。", level="WARN")
        return False

    def _open_current_vehicle_mastery(self, pos_sjy=None, from_recovery=False):
        """进入当前已装备车辆的专精页面，不包含任何选车操作。"""
        if pos_sjy is None:
            if from_recovery:
                self.log("全局恢复确认仍处于加点流程，准备重试当前已装备车辆。")
                if not self._enter_cj_vehicle_menu():
                    self.log("当前车辆加点重试失败：无法进入车辆菜单。", level="WARN")
                    return False
            pos_sjy = self._wait_for_uandt_ready(
                timeout=16.0,
                stable_frames=3,
                min_brightness=42.0,
                press_esc_when_missing=not from_recovery,
            )

        if not pos_sjy:
            self.log("找不到稳定可交互的升级页面")
            return False

        self._save_upgrade_debug(
            "before_uandt_click",
            pos_uandt=pos_sjy,
            note="菜单已稳定，准备鼠标点击升级与调校",
        )
        self.game_click(pos_sjy, clicks=1, hold=0.12, gap=0.10, use_send=True)
        time.sleep(1.2)
        self._save_upgrade_debug(
            "after_uandt_click",
            pos_uandt=pos_sjy,
            note="已用 SendMessage 鼠标点击升级与调校，准备查找车辆专精",
        )

        pos_cls = self.wait_for_any_image_gray(
            ["clsldcnw.png", "clsldcnb.png"],
            region=self.regions["全界面"],
            threshold=0.62,
            timeout=5,
            interval=0.25,
            fast_mode=False,
        )
        if not pos_cls:
            self.log("稳定后鼠标点击升级与调校仍未找到车辆专精，改用 Down+Enter 兜底后复查。")
            self.hw_press("down")
            time.sleep(0.25)
            self.hw_press("enter")
            time.sleep(1.2)
            self._save_upgrade_debug(
                "after_uandt_key_fallback",
                pos_uandt=pos_sjy,
                note="鼠标点击未进入，已用 Down+Enter 兜底，准备复查车辆专精",
            )
            pos_cls = self.wait_for_any_image_gray(
                ["clsldcnw.png", "clsldcnb.png"],
                region=self.regions["全界面"],
                threshold=0.62,
                timeout=5,
                interval=0.25,
                fast_mode=False,
            )
        if not pos_cls:
            self.log("未找到车辆专精,可能未成功进入当前车辆升级页面或升级与调校点击未生效。")
            return False

        self._save_upgrade_debug(
            "before_mastery_click",
            pos_uandt=pos_sjy,
            pos_cls=pos_cls,
            note="准备点击车辆专精",
        )
        self.game_click(pos_cls, clicks=1, hold=0.12, gap=0.10, use_send=True)
        time.sleep(1.5)
        self._save_upgrade_debug(
            "after_mastery_click",
            pos_uandt=pos_sjy,
            pos_cls=pos_cls,
            note="已点击车辆专精，准备判断技能是否已点",
        )
        return True

    def _send_mastery_path_once(self):
        """归位后发送一次完整技能路径，返回 sent/retry/stop/failed。"""
        if not self._home_mastery_cursor():
            return "failed"

        self._cj_mastery_attempted = True
        time.sleep(0.4)
        self.hw_press("enter", delay=0.12, use_send=True)
        time.sleep(1.2)

        popup_result = self._handle_mastery_popup("root")
        if popup_result is not None:
            return popup_result

        for step_index, dk in enumerate(self.config["skill_dirs"], 1):
            if not self.is_running:
                return "failed"
            self.hw_press(dk, delay=0.12, use_send=True)
            time.sleep(0.2)
            self.hw_press("enter", delay=0.12, use_send=True)
            time.sleep(1.2)

            popup_result = self._handle_mastery_popup(step_index)
            if popup_result is not None:
                return popup_result
        return "sent"

    def _run_current_vehicle_mastery(self, target_count, pos_sjy=None, from_recovery=False):
        """执行当前车辆加点，返回 (本次是否成功, 是否应结束整个超抽步骤)。"""
        if not self._open_current_vehicle_mastery(pos_sjy=pos_sjy, from_recovery=from_recovery):
            return False, False

        mastery_complete, pink_ratio = self._mastery_completion_state()
        attempted = bool(getattr(self, "_cj_mastery_attempted", False))

        if mastery_complete:
            if from_recovery and attempted:
                self.cj_counter += 1
                self._clear_cj_mastery_state("恢复后确认最终节点已购买")
                self.update_running_ui("超级抽奖", self.cj_counter, target_count)
                self.log(
                    f"恢复后确认最终节点已购买，补记超级抽奖计数 +1: "
                    f"{self.cj_counter}/{target_count} pink_ratio={pink_ratio:.3f}"
                )
            else:
                self.log(f"该车辆最终超级抽奖节点已购买，跳过计数 pink_ratio={pink_ratio:.3f}")
                self._clear_cj_mastery_state("进入页面时最终节点已购买")
            return True, False

        best_ratio = pink_ratio
        total_attempts = self._MASTERY_LOCAL_RETRIES + 1
        for path_attempt in range(1, total_attempts + 1):
            if path_attempt > 1:
                self.log(f"技能路径本地归位重试: {path_attempt}/{total_attempts}", level="WARN")

            path_result = self._send_mastery_path_once()
            if path_result == "stop":
                return True, True
            if path_result == "failed":
                return False, False
            if path_result == "retry":
                if path_attempt < total_attempts:
                    continue
                break

            mastery_complete, pink_ratio = self._wait_for_mastery_complete(timeout=2.0)
            best_ratio = max(best_ratio, pink_ratio)
            if mastery_complete:
                self.cj_counter += 1
                self._clear_cj_mastery_state("最终节点购买成功")
                self.update_running_ui("超级抽奖", self.cj_counter, target_count)
                self.log(
                    f"最终节点颜色确认成功，超级抽奖计数 +1: "
                    f"{self.cj_counter}/{target_count} pink_ratio={pink_ratio:.3f}"
                )
                return True, False
            if path_attempt < total_attempts:
                self.log(
                    f"技能路径结束但最终节点未购买，将归位后从头重试: "
                    f"pink_ratio={pink_ratio:.3f}",
                    level="WARN",
                )

        self.log(
            f"技能路径本地重试 {total_attempts} 次后最终节点仍未购买，触发全局恢复: "
            f"pink_ratio={best_ratio:.3f}",
            level="WARN",
        )
        self._save_upgrade_debug(
            "mastery_final_node_not_purchased",
            note="归位并重放技能路径后最终节点颜色仍未通过，禁止计数并触发全局恢复",
            extra={"pink_ratio": best_ratio, "path_attempts": total_attempts},
        )
        return False, False

    def _leave_current_vehicle_mastery(self, resume_vehicle_menu=False):
        self.hw_press("esc")
        time.sleep(1.2)
        self.hw_press("esc")
        time.sleep(0.8)

        if not self._wait_for_cj_vehicle_menu(timeout=2.0, hard_timeout=4.0):
            self.log("退出车辆专精后仍未回到车辆主菜单，补发一次 Esc。", level="WARN")
            self.hw_press("esc")
            time.sleep(1.0)
            if not self._wait_for_cj_vehicle_menu(timeout=3.0, hard_timeout=6.0):
                self.log("退出车辆专精后无法确认车辆主菜单。", level="WARN")
                return False

        if resume_vehicle_menu:
            self._cj_resume_vehicle_menu = True
            self.log("当前车辆复核完成，已回到车辆菜单，将直接继续设计与喷涂选车。")
            return True
        self.hw_press("up", delay=0.15)
        time.sleep(0.8)
        return True

    def retry_current_vehicle_mastery_after_recovery(self, target_count):
        """全局恢复后只重试当前已装备车辆，绝不重新进入选车循环。"""
        if not getattr(self, "_cj_mastery_in_progress", False):
            return True, False
        success, stop_task = self._run_current_vehicle_mastery(
            target_count,
            from_recovery=True,
        )
        if success and not stop_task:
            left_mastery = self._leave_current_vehicle_mastery(
                resume_vehicle_menu=self.cj_counter < target_count,
            )
            if not left_mastery:
                return False, False
        return success, stop_task

    def _is_boarding_transition(self, min_dark_mean=8.0):
        """判断是否已经离开上车按钮菜单，进入上车/车辆切换过场。

        选车后按 Enter 有时会直接触发“上车”，画面进入黑屏加载/过场，此时 rc.png 不会出现，
        不能再按“没找到上车按钮”判失败。
        """
        try:
            img = self.capture_region(self.regions["全界面"])
            if img is None:
                return False
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            mean_val = float(gray.mean())
            std_val = float(gray.std())
            if mean_val <= min_dark_mean:
                self.log(f"检测到上车/切车黑屏过场: brightness={mean_val:.2f}, std={std_val:.2f}，视为已上车")
                return True
            return False
        except Exception as e:
            self.log(f"检测上车过场异常: {e}")
            return False

    def _save_point_debug(self, root_name, log_tag, stage, points=None, note="", extra=None):
        """
        通用调试截图（v1.2.10.4 从 _save_car_select_debug/_save_upgrade_debug 抽取）：
        全屏原图 + 标注图（每个点画圆圈+标签）+ meta.json。

        points: [(pos, label, color), ...]，pos 为屏幕坐标（自动换算窗口客户区坐标）。
        """
        if hasattr(self, "is_debug_screenshots_enabled") and not self.is_debug_screenshots_enabled():
            return
        try:
            debug_root = os.path.join(APP_DIR, root_name)
            os.makedirs(debug_root, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
            safe_stage = str(stage).replace(" ", "_")
            out_dir = os.path.join(debug_root, f"{stamp}_{safe_stage}")
            os.makedirs(out_dir, exist_ok=True)

            img = self.capture_region(self.regions["全界面"])
            meta = {
                "stage": stage,
                "note": note,
                "points": {label: (list(pos) if pos else None) for pos, label, _ in (points or [])},
                "extra": extra or {},
            }
            if img is not None:
                annotated = img.copy()
                gx, gy, _, _ = self.regions["全界面"]
                for pos, label, color in (points or []):
                    if not pos:
                        continue
                    x, y = int(pos[0] - gx), int(pos[1] - gy)
                    cv2.circle(annotated, (x, y), 18, color, 3)
                    cv2.putText(annotated, label, (max(5, x - 70), max(25, y - 25)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                cv2.imwrite(os.path.join(out_dir, "screen_annotated.png"), annotated)
                cv2.imwrite(os.path.join(out_dir, "screen_raw.png"), img)
            with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            self.log(f"[{log_tag}] {stage} 已保存: {out_dir}")
        except Exception as e:
            self.log(f"[{log_tag}] 保存失败({stage}): {e}")

    def _save_upgrade_debug(self, stage, pos_uandt=None, pos_cls=None, note="", extra=None):
        """上车后"升级与调校/车辆专精"阶段调试截图（签名兼容，转发通用方法）"""
        self._save_point_debug("debug_upgrade_flow", "UpgradeDebug", stage,
            points=[(pos_uandt, "UandT_click", (0, 0, 255)), (pos_cls, "mastery_click", (0, 255, 0))],
            note=note, extra=extra)

    def _wait_for_uandt_ready(self, timeout=12.0, stable_frames=3, min_brightness=42.0, press_esc_when_missing=False):
        """等待"升级与调校"所在车辆菜单真正加载稳定。

        加载暗屏阶段模板可能提前命中，但菜单还不可交互；必须亮度足够且连续多帧命中同一位置。
        press_esc_when_missing=True 时，适用于"上车"后仍停在收藏/详情层，需要 Esc 退回车辆主菜单的场景。
        """
        start = time.time()
        interaction_deadline = start + timeout
        hard_deadline = start + max(90.0, timeout + 45.0)
        stable = 0
        last_pos = None
        dark_logged = False
        last_brightness = 0.0
        last_seen = None
        last_esc_at = 0.0
        slow_mode = False  # 黑屏恢复后切换为慢速 Esc 模式（3s 间隔）

        while time.time() < interaction_deadline and time.time() < hard_deadline:
            if not self.is_running:
                return None

            img = self.capture_region(self.regions["全界面"])
            if img is not None:
                last_brightness = float(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).mean())

            pos = self.find_any_image_gray(["UandT-w.png", "UandT-b.png"], region=self.regions["左下"], threshold=0.72)
            if not pos:
                pos = self.find_any_image_gray(["UandT-w.png", "UandT-b.png"], region=self.regions["全界面"], threshold=0.72, fast_mode=False)

            if pos:
                last_seen = pos
                if last_brightness < min_brightness:
                    stable = 0
                    if not dark_logged:
                        self.log(f"检测到升级与调校但画面仍偏暗/加载中，等待稳定 brightness={last_brightness:.1f}")
                        dark_logged = True
                elif last_pos and abs(pos[0] - last_pos[0]) <= 8 and abs(pos[1] - last_pos[1]) <= 8:
                    stable += 1
                else:
                    stable = 1
                last_pos = pos

                if stable >= stable_frames:
                    self.log(f"升级与调校菜单已稳定: pos={pos} brightness={last_brightness:.1f} stable={stable}")
                    return pos
            else:
                stable = 0
                # 检测黑屏：亮度极低时标记，画面恢复后切换慢速 Esc 模式
                if last_brightness < 5.0:
                    # 黑屏加载不消耗真正的菜单交互时间，但仍受 hard_deadline 约束。
                    interaction_deadline = min(hard_deadline, time.time() + timeout)
                    if not slow_mode:
                        self.log(f"检测到画面暗屏 brightness={last_brightness:.1f}，恢复后将切换慢速 Esc 模式")
                        slow_mode = True
                        last_esc_at = 0  # 重置，等画面亮起后重新计时
                elif slow_mode and last_esc_at == 0 and last_brightness >= min_brightness:
                    self.log(f"画面已恢复 brightness={last_brightness:.1f}，进入慢速 Esc 模式（3s间隔）")
                    last_esc_at = time.time()
                    interaction_deadline = min(hard_deadline, time.time() + timeout)

                esc_interval = 3.0 if slow_mode else 1.2

                # 上车后如果仍在车辆收藏/详情层，升级与调校不可见；加载完成后按 Esc 回到车辆主菜单。
                if press_esc_when_missing and last_brightness >= min_brightness and time.time() - last_esc_at >= esc_interval:
                    self.log(f"上车后尚未看到升级与调校，画面已亮起，按 Esc 尝试退回车辆菜单 brightness={last_brightness:.1f}")
                    self.hw_press("esc")
                    last_esc_at = time.time()
                    interaction_deadline = min(hard_deadline, time.time() + timeout)
                    if slow_mode:
                        time.sleep(3.0)
                    else:
                        time.sleep(0.6)

            time.sleep(0.35)

        self.log(
            f"等待升级与调校菜单稳定超时: last_seen={last_seen} "
            f"brightness={last_brightness:.1f} stable={stable} elapsed={time.time() - start:.1f}s"
        )
        return None

    def _detect_selected_card_focus(self):
        """通过黄色选中/价格区域估算当前焦点车卡位置。返回绝对坐标 (x, y)。"""
        try:
            img = self.capture_region(self.regions["全界面"])
            if img is None:
                return None
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            # Forza 当前选中车卡常见黄色价格/焦点块；排除小“全新”标签靠面积过滤。
            mask = cv2.inRange(hsv, np.array([18, 80, 120]), np.array([38, 255, 255]))
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            candidates = []
            for c in contours:
                x, y, w, h = cv2.boundingRect(c)
                area = w * h
                if area < 1800 or w < 60 or h < 18:
                    continue
                # 车卡底部区域，过滤顶部背景和小标签
                if y < int(img.shape[0] * 0.30) or y > int(img.shape[0] * 0.90):
                    continue
                candidates.append((area, x, y, w, h))
            if not candidates:
                return None
            candidates.sort(reverse=True)
            _, x, y, w, h = candidates[0]
            gx, gy, _, _ = self.regions["全界面"]
            return (gx + x + w // 2, gy + y + h // 2)
        except Exception as e:
            self.log(f"检测当前焦点车卡失败: {e}")
            return None

    def _verify_target_point_b600(self, pos_target, threshold=0.72):
        """二次硬校验：目标点击点附近必须仍能匹配到等级标签。

        防止全新标签/车辆图片局部相似时，把 C466/D 等级的新车误当作目标 22B 上车。
        """
        try:
            if not pos_target:
                return False
            strict_meta = getattr(self, "last_strict_car_meta", None) or {}
            strict_class_score = float(strict_meta.get("class_score", 0.0) or 0.0)
            # 严格识别阶段是在点击/hover 前完成的，可信度最高；点击后选中框会改变局部外观，
            # 不能用 hover 后的小区域匹配反过来否定前面的高置信等级标签。
            # YOLO 分支用独立低门槛：其等级标签类实测 conf 0.5~0.7（比模板灰度分低），
            # 且已有车型分类 + NEW 角标双重交叉验证，>=0.50 即安全过硬校验，
            # 避免每次再跑一遍冗余模板匹配。模板路径保持原阈值。
            if str(strict_meta.get("source", "")) == "yolo":
                class_gate = 0.50
            else:
                class_gate = threshold
            if strict_class_score >= class_gate:
                _cls_img = self.config.get("class_image", "classS2829.png")
                self.log(f"[Safety] 严格识别阶段等级标签分数通过二次校验: {strict_class_score:.3f} >= {class_gate:.2f} (source={strict_meta.get('source', 'template')})")
                return True

            x, y = int(pos_target[0]), int(pos_target[1])
            region = (max(0, x - 160), max(0, y - 100), 320, 200)
            _cls_img = self.config.get("class_image", "classS2829.png")
            pos = self.find_image_gray(_cls_img, region=region, threshold=threshold, fast_mode=False)
            if pos:
                return True
            self.log(f"[Safety] 目标点附近未通过 {_cls_img} 二次校验，拒绝上车: pos={pos_target} threshold={threshold} strict_class_score={strict_class_score:.3f}")
            self._save_car_select_debug(
                "b600_verify_failed",
                pos_target=pos_target,
                note="目标点附近未找到等级标签，疑似误识别车型，已拒绝上车",
                extra={"verify_region": region, "threshold": threshold, "strict_meta": strict_meta}
            )
            return False
        except Exception as e:
            self.log(f"[Safety] 等级标签二次校验异常，拒绝上车: {e}")
            return False

    def _keyboard_select_target_card(self, pos_target):
        """鼠标后台点击不生效时，用方向键从当前焦点移动到目标车卡并 Enter。"""
        focus_pos = self._detect_selected_card_focus()
        if not focus_pos or not pos_target:
            self.log("键盘兜底选车失败: 无法定位当前焦点或目标点")
            return False

        dx = pos_target[0] - focus_pos[0]
        dy = pos_target[1] - focus_pos[1]
        # FH6 车辆网格间距，按 1600x900 UI 估算；四舍五入得到需要移动的格数。
        col_step = 275
        row_step = 210
        move_x = int(round(dx / col_step))
        move_y = int(round(dy / row_step))
        self.log(f"键盘兜底选车: 当前焦点={focus_pos}, 目标={pos_target}, dx={dx}, dy={dy}, 移动=({move_x},{move_y})")

        key_x = "right" if move_x > 0 else "left"
        for _ in range(abs(move_x)):
            if not self.is_running:
                return False
            self.hw_press(key_x, delay=0.08)
            time.sleep(0.18)

        key_y = "down" if move_y > 0 else "up"
        for _ in range(abs(move_y)):
            if not self.is_running:
                return False
            self.hw_press(key_y, delay=0.08)
            time.sleep(0.18)

        time.sleep(0.3)
        self._save_car_select_debug(
            "after_keyboard_focus_move",
            pos_target=pos_target,
            note="鼠标点击未出现上车按钮，已用方向键移动焦点到目标车附近，准备按 Enter",
            extra={"focus_pos": list(focus_pos), "move_x": move_x, "move_y": move_y}
        )
        self.hw_press("enter")
        time.sleep(1.0)
        return True

    def _save_car_select_debug(self, stage, pos_target=None, pos_rc=None, note="", extra=None):
        """超级抽奖"识别到车 -> 点击选车 -> 上车按钮"阶段调试截图（签名兼容，转发通用方法）"""
        self._save_point_debug("debug_car_select", "CarSelectDebug", stage,
            points=[(pos_target, "target_click", (0, 0, 255)), (pos_rc, "rc_button", (0, 255, 0))],
            note=note, extra=extra)

    def logic_super_wheelspin(self, target_count):
        if self.cj_counter >= target_count:
            return True

        self.update_running_ui("超级抽奖", self.cj_counter, target_count)

        # ====== 任务内锁定，每次进入任务强制重置详情状态锁 ======
        self.detail_state_confirmed = False

        # 【新增】:初始化记忆页码
        if not hasattr(self, 'memory_car_page'):
            self.memory_car_page = 0
        resume_vehicle_menu = bool(getattr(self, "_cj_resume_vehicle_menu", False))
        self._cj_resume_vehicle_menu = False
        if resume_vehicle_menu and self._wait_for_cj_vehicle_menu(timeout=4.0):
            self.log("全局恢复后的当前车辆复核已完成，直接从车辆菜单继续选车。")
        else:
            if resume_vehicle_menu:
                self.log("车辆菜单续跑锚点未命中，改从主菜单按正常路径重新进入。", level="WARN")
            if not self._enter_cj_vehicle_menu():
                return False

        while self.cj_counter < target_count:
            if not self.is_running:
                return False
            # ====== 根据下拉框判断进入方式 ======
            # runner 线程不能读取 Tk 控件；启动时已固化到 _run_settings/config。
            cj_mode = int(getattr(self, "_run_settings", {}).get(
                "cj_mode", self.config.get("cj_mode", 1)
            ))
            cj_mode_str = "模式2" if cj_mode == 2 else "模式1"

            if "模式1" in cj_mode_str:
                self.log("进入我的车辆.")
                self.hw_press("enter")
                time.sleep(2.0)
            else:
                self.log("进入设计与喷涂.")
                pos_dp = self.wait_for_image_gray("DandP.png", region=self.regions["全界面"], threshold=0.70, timeout=5, interval=0.3, fast_mode=True)
                if pos_dp:
                    self.game_click(pos_dp)
                    time.sleep(0.5)
                else:
                    self.log("未找到设计与喷涂")
                    return False
                pos_choose = self.wait_for_image_gray("choosecar.png", region=self.regions["全界面"], threshold=0.70, timeout=5, interval=0.3, fast_mode=True)
                if pos_choose:
                    self.game_click(pos_choose)
                    time.sleep(2.0)
                else:
                    self.log("未找到选择车辆(choosecar.png)")
                    return False
            # ====== 选品牌 + 翻页找车 ======
            brand_retry_done = False
            while True:
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
                time.sleep(0.8)
                # 后台点击品牌有时只把焦点停在品牌项上，未真正进入车辆列表。
                # 如果 CCbrand 仍可见，说明还在制造商列表，补 Enter 确认进入。
                for retry in range(3):
                    if not self.is_running:
                        return False
                    still_brand = self.find_image_gray(
                        "CCbrand.png",
                        region=self.regions["全界面"],
                        threshold=0.75,
                        fast_mode=True
                    )
                    if not still_brand:
                        break
                    self.log(f"品牌仍停留在制造商列表，补 Enter 进入车辆列表 ({retry + 1}/3)")
                    self.hw_press("enter")
                    time.sleep(1.0)
                jump_pages = self.memory_car_page

                if jump_pages > 0:
                    self.log(f"智能记忆触发:快速跳过前 {jump_pages} 页...")
                    for _ in range(jump_pages):
                        if not self.is_running: return False
                        for _ in range(4):
                            self.hw_press("right", delay=0.10)
                            time.sleep(0.22)
                        time.sleep(0.45) # 给翻页动画更充足缓冲，避免列表还在滑动时识别/点击
                pos_target = None
                found_car = False
                current_page = jump_pages # 记录当前所在的真实页码

                # 最多看 3 页（第 0/1/2 页），每页的顺序：搜索 → P切换重搜 → 不行就翻下一页
                max_pages = 5
                for page_idx in range(max_pages):
                    if not self.is_running:
                        return False
                    pos_target = self.wait_for_new_consumable_car_strict(timeout=3.0, interval=0.2)

                    if pos_target:
                        self.detail_state_confirmed = True
                        self._save_car_select_debug(
                            "before_target_sendmessage_click",
                            pos_target=pos_target,
                            note="识别到目标车；车库卡片直接使用 SendMessage 同步强点击选中",
                            extra={"current_page": current_page, "clicks": 1, "hold": 0.22, "gap": 0.18, "use_send": True, "single_point": True, "dblclk": False}
                        )
                        click_points = getattr(self, "last_strict_car_click_points", [pos_target])
                        click_points_to_try = [(int(p[0]), int(p[1])) for p in click_points[:1]]
                        self.log(f"SendMessage 主点强点车卡: {click_points_to_try}")
                        for idx, click_point in enumerate(click_points_to_try, start=1):
                            if not self.is_running:
                                return False
                            self.log(
                                f"[CarSelect] SendMessage 强点候选点 {idx}/{len(click_points_to_try)} "
                                f"坐标={click_point} clicks=1 hold=0.22 gap=0.18"
                            )
                            self._save_car_select_debug(
                                f"before_send_point_{idx}",
                                pos_target=click_point,
                                note=f"准备 SendMessage 强点候选点 {idx}",
                                extra={"current_page": current_page, "point_index": idx, "all_points": [list(p) for p in click_points_to_try]}
                            )
                            self.game_click(click_point, clicks=1, hold=0.22, gap=0.18, use_send=True)
                            time.sleep(0.35)
                            self._save_car_select_debug(
                                f"after_send_point_{idx}",
                                pos_target=click_point,
                                note=f"已 SendMessage 强点候选点 {idx}",
                                extra={"current_page": current_page, "point_index": idx, "all_points": [list(p) for p in click_points_to_try]}
                            )
                        time.sleep(0.5)
                        if not self._verify_target_point_b600(pos_target, threshold=0.72):
                            self.log("当前候选不满足目标等级标签硬条件，判定本屏/本批无可安全处理目标，结束超抽步骤。")
                            return True
                        self._save_car_select_debug(
                            "before_enter_select",
                            pos_target=pos_target,
                            note="主点强点结束，等级标签二次校验通过，准备按 Enter 选择当前焦点车卡",
                            extra={"current_page": current_page, "all_points": [list(p) for p in click_points_to_try]}
                        )
                        # 强点会 hover/选中车卡，但当前界面仍需要 Enter 选择，才会进入“上车”菜单。
                        self.hw_press("enter")
                        time.sleep(1.0)
                        self._save_car_select_debug(
                            "after_enter_select",
                            pos_target=pos_target,
                            note="已补 Enter，准备检查上车按钮",
                            extra={"current_page": current_page, "all_points": [list(p) for p in click_points_to_try]}
                        )
                        found_car = True
                        # 记住这次找到车是在哪一页
                        self.memory_car_page = current_page
                        self.log(f"锁定目标车辆!已记录当前页码: {current_page} SendMessage强点+Enter 点={pos_target}")
                        break

                    # 翻下一页
                    for _ in range(4):
                        self.hw_press("right", delay=0.10)
                        time.sleep(0.22)
                    time.sleep(0.65)
                    current_page += 1
                if not found_car:
                    if not brand_retry_done:
                        self.log("5 页未找到满足条件的车辆，重新进入选品牌重试...")
                        brand_retry_done = True
                        self.memory_car_page = 0
                        continue  # 内层 while 继续，重新选品牌
                    else:
                        self.log("重新选品牌后仍 5 页未找到，车辆已刷完，结束超抽步骤。")
                        self.memory_car_page = 0
                        return True
                break  # found_car=True，跳出内层 while，继续升级流程
            # ====== 选品牌 + 翻页找车 结束 ======
            # 成功找到车 → 重置 retry 计数器（下一轮没找到时允许重试）
            brand_retry_done = False

            already_boarding = self._is_boarding_transition()
            if already_boarding:
                self._save_car_select_debug(
                    "after_enter_boarding_transition",
                    pos_target=pos_target,
                    note="Enter 后已进入上车/切车过场，跳过 rc.png 上车按钮搜索",
                    extra={"current_page": current_page, "already_boarding": True}
                )
                time.sleep(4.5)
            else:
                time.sleep(1.2)
            self.log("尝试寻找'上车'按钮...")

            pos_rc = None
            mode2 = ("模式2" in cj_mode_str)
            if not already_boarding:
                if mode2:
                    # ===== 模式2: 从设计与喷漆进入 =====
                    # 上游逻辑: game_click(pos_target) → sleep(0.5) → Enter → sleep(1.0) → 进入升级循环
                    # fork 逻辑: SendMessage 点车 + line 475 的 Enter 已等价上游 game_click + Enter
                    # 所以这里不需要再补 Enter，直接交给 _wait_for_uandt_ready 走升级循环即可。
                    self._save_car_select_debug(
                        "mode2_after_enter_select",
                        pos_target=pos_target,
                        pos_rc=None,
                        note="模式2: 选车后不补 Enter，直接进入升级循环",
                        extra={"current_page": current_page}
                    )
                else:
                    # ===== 模式1: 原逻辑 - 找 rc.png 按钮 =====
                    pos_rc = self.wait_for_image_gray("rc.png", region=self.regions["全界面"], threshold=0.70, timeout=0.5, interval=0.1, fast_mode=True)
            self._save_car_select_debug(
                "after_rc_search",
                pos_target=pos_target,
                pos_rc=pos_rc,
                note="已完成上车按钮识别",
                extra={"current_page": current_page, "rc_found": bool(pos_rc), "mode2": mode2}
            )

            if already_boarding:
                self.log("Enter 已触发上车/切车过场，跳过 rc.png 点击，继续等待车辆菜单。")
            elif mode2:
                # 模式2 对齐上游: 选车+Enter 后直接交给 _wait_for_uandt_ready 循环按 ESC找“升级与调校”。
                self.log("模式2: 跳过 rc.png 搜索，直接等待“升级与调校”菜单。")
            elif pos_rc:
                self.log(f"点击上车: {pos_rc}")
                self.game_click(pos_rc)
                time.sleep(0.8)
                self._save_car_select_debug(
                    "after_rc_click",
                    pos_target=pos_target,
                    pos_rc=pos_rc,
                    note="已点击上车按钮，等待进入车辆",
                    extra={"current_page": current_page}
                )
                time.sleep(4.2)  # 点击后等待上车/菜单完全加载，避免过早点升级与调校
            else:
                # 对齐上游: 没找到 rc.png 就直接双 Enter 上车
                self.log("未找到上车按钮，按上游逻辑双 Enter 上车。")
                self.hw_press("enter")
                time.sleep(1.0)
                self.hw_press("enter")
                time.sleep(2.0)
                self._save_car_select_debug(
                    "after_double_enter_boarding",
                    pos_target=pos_target,
                    pos_rc=None,
                    note="未找到 rc.png，已双 Enter 上车",
                    extra={"current_page": current_page}
                )

            # 选车和上车逻辑到此为止。后续若失败，全局恢复只会重试这辆当前车的加点。
            self._begin_cj_mastery()
            pos_sjy = self._wait_for_uandt_ready(
                timeout=16.0,
                stable_frames=3,
                min_brightness=42.0,
                press_esc_when_missing=True,
            )
            if not pos_sjy:
                self.log("找不到稳定可交互的升级页面")
                return False
            mastery_success, stop_task = self._run_current_vehicle_mastery(
                target_count,
                pos_sjy=pos_sjy,
            )
            if not mastery_success:
                return False
            if stop_task:
                return True
            if not self._leave_current_vehicle_mastery():
                return False
        self.hw_press("esc")
        time.sleep(1.2)
        self.hw_press("esc")
        time.sleep(1.2)
        return True
