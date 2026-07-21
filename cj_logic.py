import os
import json
import time
import cv2
import numpy as np
from config import APP_DIR


class CJMixin:
    """超级抽奖业务逻辑"""

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
        stable = 0
        last_pos = None
        dark_logged = False
        last_brightness = 0.0
        last_seen = None
        last_esc_at = 0.0
        slow_mode = False  # 黑屏恢复后切换为慢速 Esc 模式（3s 间隔）

        while time.time() - start < timeout:
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
                    if not slow_mode:
                        self.log(f"检测到画面暗屏 brightness={last_brightness:.1f}，恢复后将切换慢速 Esc 模式")
                        slow_mode = True
                        last_esc_at = 0  # 重置，等画面亮起后重新计时
                elif slow_mode and last_esc_at == 0 and last_brightness >= min_brightness:
                    self.log(f"画面已恢复 brightness={last_brightness:.1f}，进入慢速 Esc 模式（3s间隔）")
                    last_esc_at = time.time()

                esc_interval = 3.0 if slow_mode else 1.2

                # 上车后如果仍在车辆收藏/详情层，升级与调校不可见；加载完成后按 Esc 回到车辆主菜单。
                if press_esc_when_missing and last_brightness >= min_brightness and time.time() - last_esc_at >= esc_interval:
                    self.log(f"上车后尚未看到升级与调校，画面已亮起，按 Esc 尝试退回车辆菜单 brightness={last_brightness:.1f}")
                    self.hw_press("esc")
                    last_esc_at = time.time()
                    if slow_mode:
                        time.sleep(3.0)
                    else:
                        time.sleep(0.6)

            time.sleep(0.35)

        self.log(f"等待升级与调校菜单稳定超时: last_seen={last_seen} brightness={last_brightness:.1f} stable={stable}")
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
            if strict_class_score >= threshold:
                _cls_img = self.config.get("class_image", "classS2829.png")
                self.log(f"[Safety] 使用严格识别阶段 {_cls_img} 分数通过二次校验: {strict_class_score:.3f} >= {threshold:.2f}")
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
            # ====== 根据下拉框判断进入方式 ======
            cj_mode_str = "模式1"
            if hasattr(self, "opt_cj_mode"):
                cj_mode_str = self.opt_cj_mode.get()

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
                jump_pages = max(0, self.memory_car_page - 1)

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

            pos_sjy = self._wait_for_uandt_ready(timeout=16.0, stable_frames=3, min_brightness=42.0, press_esc_when_missing=True)

            if not pos_sjy:
                self.log("找不到稳定可交互的升级页面")
                return False

            self._save_upgrade_debug(
                "before_uandt_click",
                pos_uandt=pos_sjy,
                note="菜单已稳定，准备鼠标点击升级与调校"
            )
            # 先等菜单稳定，再用鼠标点击。之前失败主要是暗屏加载期点太早。
            self.game_click(pos_sjy, clicks=1, hold=0.12, gap=0.10, use_send=True)
            time.sleep(1.2)
            self._save_upgrade_debug(
                "after_uandt_click",
                pos_uandt=pos_sjy,
                note="已用 SendMessage 鼠标点击升级与调校，准备查找车辆专精"
            )

            pos_cls = self.wait_for_any_image_gray(
                ["clsldcnw.png", "clsldcnb.png"],
                region=self.regions["全界面"],
                threshold=0.62,
                timeout=5,
                interval=0.25,
                fast_mode=False
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
                    note="鼠标点击未进入，已用 Down+Enter 兜底，准备复查车辆专精"
                )
                pos_cls = self.wait_for_any_image_gray(
                    ["clsldcnw.png", "clsldcnb.png"],
                    region=self.regions["全界面"],
                    threshold=0.62,
                    timeout=5,
                    interval=0.25,
                    fast_mode=False
                )
            if not pos_cls:
                self.log("未找到车辆专精,可能未成功进入目标车辆升级页面或升级与调校点击未生效。")
                return False
            self._save_upgrade_debug(
                "before_mastery_click",
                pos_uandt=pos_sjy,
                pos_cls=pos_cls,
                note="准备点击车辆专精"
            )
            self.game_click(pos_cls, clicks=1, hold=0.12, gap=0.10, use_send=True)
            time.sleep(1.5)
            self._save_upgrade_debug(
                "after_mastery_click",
                pos_uandt=pos_sjy,
                pos_cls=pos_cls,
                note="已点击车辆专精，准备判断技能是否已点"
            )

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

                # 只要已经进入专精并执行了技能路径，就计为本次超抽处理完成。
                # 旧逻辑在 SPNE 提前 return 前才加计数，导致成功处理车辆但计数不增加。
                self.cj_counter += 1
                self.update_running_ui("超级抽奖", self.cj_counter, target_count)
                self.log(f"超级抽奖计数 +1: {self.cj_counter}/{target_count}")

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
