# -*- coding: utf-8 -*-
"""
筛选面板 OCR 视觉导航（v1.2.10.0）

替代"固定按 N 下"的筛选导航：筛选列表内容因账号车辆拥有情况不同而变化
（品牌/车型/稀有度条目可能缺失或增减），固定按键数在其他账号上会错位。

本模块实时 OCR 可见列表，通过黄绿色高亮边框定位当前选中行，按文字目标导航，
自动适配任意账号的列表。

筛选面板几何（随游戏窗口同比例缩放）：
- 游戏窗口 1600x900 时，面板为窗口中心 555x540 的竖向长方形

用法（Mixin，依赖 bot 的 hw_press / capture_region / get_ocr_engine / log）：
    ok = self.open_and_apply_filter(["重复项", "S2", "顶级超跑", "全轮驱动"], label="删车筛选")
"""
import os
import time

import cv2
import numpy as np

from config import APP_DIR

# 筛选面板区域比例（相对游戏窗口，1600x900 下为居中 555x540）
FILTER_PANEL_REGION = {
    "x_start": (1600 - 555) / 2 / 1600,   # 0.3265625
    "x_end": (1600 + 555) / 2 / 1600,     # 0.6734375
    "y_start": (900 - 540) / 2 / 900,     # 0.2
    "y_end": (900 + 540) / 2 / 900,       # 0.8
}

# 默认筛选目标（老配置自动迁移用，来自 v1.2.9.0 固定按键序列的反推）
# 删车筛选 方案1 (Revuelto, S2 829): Y -> 2下(重复项) -> 6下(S2) -> 14下(顶级超跑) -> 28下(全轮驱动)
DEFAULT_SELL_FILTER_SCHEME1 = ["重复项", "S2", "顶级超跑", "全轮驱动"]
# 删车筛选 方案2 (Mad Mike 马自达, S1 702): Y -> 7下(S1) -> 10下(漂移赛车) -> 32下(后轮驱动) -> 5下(传奇)
DEFAULT_SELL_FILTER_SCHEME2 = ["S1", "漂移赛车", "后轮驱动", "传奇"]
# 跑图选车 (Mad Mike 808 Wagon): Y -> Enter(收藏) -> 35下(复古拉力赛车) -> 19下(传奇)
DEFAULT_RACE_FILTER = ["收藏", "复古拉力赛车", "传奇"]

# 按键节奏（与旧版固定导航验证过的节奏一致：delay=0.1 + gap=0.1，快了会丢按键）
_PRESS_DELAY = 0.06       # hw_press 按键持续时间（v1.2.10.5: 0.1 -> 0.06，逐键 OCR 校验+卡底容错兜底丢键）
_PRESS_GAP = 0.04         # 连续方向键之间的间隔（v1.2.10.5: 0.1 -> 0.04）
_PAGE_SETTLE = 0.3        # 翻页后等待列表渲染（v1.2.10.2: 0.5 -> 0.3，配合 0.7 页步长提速）
_TOGGLE_SETTLE = 0.8      # Enter 勾选后等待
_MAX_PAGES = 14           # 回顶搜索最大翻页数（_scroll_to_top 用）
_MAX_WALK_STEPS = 80      # 逐键搜索单轮最大步数（整表约 66 个可聚焦行 + 标题行，留余量）
_MAX_CORRECTION = 8       # 偏移校正最大扫描步数（单方向）
_CLICK_DIFF_THRESHOLD = 120.0  # 点击勾选验证：复选框区域平均像素差阈值（实测成功勾选差值 220~235，留足防误判余量）
FILTER_DET_MAX_SIDE = 416  # 筛选面板 OCR 的 det 长边上限（面板 555×540 缩到 ~416，菜单文字 28px→21px 足够识别，det 耗时 -40%）


def _norm_text(t):
    """文本归一化：去除所有空白，用于 OCR 模糊匹配"""
    return "".join(str(t).split())


class FilterNavMixin:
    """筛选面板 OCR 视觉导航"""

    # ============ 对外入口 ============

    def open_and_apply_filter(self, targets, label="筛选"):
        """
        打开筛选面板并依次勾选目标选项：Y 打开 -> X 重置 -> 逐个导航勾选 -> ESC 关闭。

        Args:
            targets: list[str]，按顺序勾选的选项文字（必须与游戏列表文字一致）
            label: 日志标签
        Returns:
            bool: 全部目标成功勾选返回 True；任一目标缺失/导航失败返回 False（面板已 ESC 关闭）
        """
        if not targets:
            self.log(f"[{label}] 筛选目标为空，跳过筛选")
            return True

        # 打开筛选面板（失败重试一次）
        if not self._wait_for_filter_panel(press_y=True):
            self.log(f"[{label}] 筛选面板未打开，重试一次", level="WARN")
            self.hw_press("esc")
            time.sleep(0.8)
            if not self._wait_for_filter_panel(press_y=True):
                self.log(f"[{label}] 筛选面板仍未打开，放弃", level="ERROR")
                return False

        # X 重置：清空残留勾选，保证每次状态确定
        self.hw_press("x")
        time.sleep(_TOGGLE_SETTLE)

        for i, target in enumerate(targets):
            if not self.is_running:
                return False
            if not self._toggle_filter_target(target, label):
                self.log(
                    f"[{label}] 目标选项缺失或导航失败: {target}，放弃筛选",
                    level="ERROR",
                )
                self.hw_press("esc")
                time.sleep(1.0)
                return False
            self.log(f"[{label}] ({i + 1}/{len(targets)}) 已勾选: {target}")

        self.hw_press("esc")
        time.sleep(1.0)
        self.log(f"[{label}] 完成，共勾选 {len(targets)} 项: {' + '.join(targets)}")
        return True

    def get_scheme_filter(self, key):
        """读取当前方案的筛选配置（list[str]），未配置返回 None"""
        idx = self.config.get("current_scheme", 0)
        schemes = self.config.get("schemes", [])
        if 0 <= idx < len(schemes):
            val = schemes[idx].get(key)
            if isinstance(val, list) and val:
                return [str(t) for t in val]
        return None

    # ============ 共享 OCR 检测 ============

    def ocr_detect_boarding(self, label="上车检测", enter_wait=4.0, esc_gap=0.7):
        """
        OCR 中心区域检测"上车"按钮并行动（v1.2.10.4 从三处重复代码抽取）：
        识别到 -> Enter 上车，等待 enter_wait 秒，返回 True；
        未识别 -> 车辆已在驾驶，ESC×2 退出，返回 False。

        中心区域比例换算自 1600×900 下 558×287 居中矩形。
        调用方：跑图选车（Steam/Xbox）、删车驾驶收藏车。
        """
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
            self.log(f"[{label}] OCR 识别到'上车'，按 Enter 上车 (text={text})")
            self.hw_press("enter")
            time.sleep(enter_wait)
            return True
        self.log(f"[{label}] OCR 未识别到'上车'，车辆已在驾驶 (text={text})")
        self.hw_press("esc")
        time.sleep(esc_gap)
        self.hw_press("esc")
        return False

    def ocr_detect_author_prompt(self):
        """
        OCR 检测赛事评价弹窗（v1.2.10.6 替代 likeauthor/dislikeauthor 图片匹配）。

        弹窗为居中三按钮（点赞/点踩/取消，默认高亮点赞），识别中央区域文字，
        出现"点踩"即判定弹窗存在。返回 OCR 文本（弹窗存在）或空字符串（不存在）。
        """
        engine = self.get_ocr_engine()
        img = self.capture_region(self.regions["全界面"])
        if img is None or engine is None:
            return ""
        text = engine.detect_text_in_region(img, {
            "y_start": 0.30,
            "y_end": 0.70,
            "x_start": 0.25,
            "x_end": 0.75,
        })
        return text if "点踩" in text else ""

    # ============ 面板打开检测 ============

    def _wait_for_filter_panel(self, press_y=True, timeout=3.0):
        """按 Y 打开筛选面板，等待面板出现（面板内识别到 >=5 行文字视为已打开）"""
        if press_y:
            self.hw_press("y")
            time.sleep(1.0)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.is_running:
                return False
            panel = self._capture_filter_panel()
            if panel is not None:
                lines = self._ocr_panel_lines(panel)
                if len(lines) >= 5:
                    return True
            time.sleep(0.5)
        return False

    # ============ 截图 / OCR ============

    def _capture_filter_panel(self):
        """截取筛选面板区域（BGR），失败返回 None"""
        img = self.capture_region(self.regions["全界面"])
        if img is None:
            return None
        h, w = img.shape[:2]
        x1 = int(w * FILTER_PANEL_REGION["x_start"])
        x2 = int(w * FILTER_PANEL_REGION["x_end"])
        y1 = int(h * FILTER_PANEL_REGION["y_start"])
        y2 = int(h * FILTER_PANEL_REGION["y_end"])
        panel = img[y1:y2, x1:x2]
        if panel.size == 0:
            return None
        return panel

    def _ocr_panel_lines(self, panel):
        """OCR 面板，返回行列表 [{"text","box"}, ...]（面板坐标系）"""
        engine = self.get_ocr_engine()
        if engine is None:
            return []
        try:
            lines = engine.detect_lines_in_region(panel, max_side=FILTER_DET_MAX_SIDE)
        except Exception as e:
            self.log(f"[FilterNav] OCR 行检测异常: {e}", level="ERROR")
            return []
        return self._clean_panel_lines(panel, lines)

    @staticmethod
    def _clean_panel_lines(panel, lines):
        """
        剔除面板顶部固定的"筛选"标题残片（随滚动始终在顶部，OCR 读数不稳定，
        会污染页指纹导致卡底检测失效）。保留滚动到顶部的完整行（高度正常）。
        """
        h = panel.shape[0]
        out = []
        for l in lines:
            x1, y1, x2, y2 = l["box"]
            if y1 < h * 0.04 and (y2 - y1) < 18:
                continue
            out.append(l)
        return out

    # ============ 高亮行检测 ============

    def _find_highlight_band(self, panel):
        """
        检测高亮行的 y 范围（面板坐标系）。

        高亮行特征：黄绿色荧光边框（H≈36, S>230, V≈254）+ 黑色底 + 白色文字，
        边框极细（~4px），上下两条边框夹住黑底行。
        黄色分类标题行（性能等级/车辆类型等）是黄色实底，内部亮度高，用内部亮度排除。

        算法：HSV 掩膜 -> 垂直膨胀合并上下边框 -> 粗定位带 ->
              原始掩膜精修出上下边框位置 -> 内部亮度最低者为高亮行。

        Returns: (y_top, y_bottom) 或 None
        """
        h, w = panel.shape[:2]
        hsv = cv2.cvtColor(panel, cv2.COLOR_BGR2HSV)
        # 黄绿色边框：H 20~50, S>80, V>140（实测边框 H≈36 S≈252 V≈254）
        mask = cv2.inRange(hsv, (20, 80, 140), (50, 255, 255))
        # 排除顶部"筛选"标题栏（也是黄色系）
        y_min = int(h * 0.045)
        mask[:y_min, :] = 0

        # 垂直膨胀：把上/下两条细边框合并成一个粗带（边框间距约 40px）
        k_h = max(20, int(h * 0.075))
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, k_h))
        dilated = cv2.dilate(mask, kernel, iterations=1)
        row_hits = np.count_nonzero(dilated, axis=1)
        thresh = max(20, int(w * 0.10))
        rows = np.where(row_hits > thresh)[0]
        if len(rows) == 0:
            return None

        # 聚合成粗带（允许 10px 间隙）
        bands = []
        start = prev = int(rows[0])
        for y in rows[1:]:
            y = int(y)
            if y - prev > 10:
                bands.append((start, prev))
                start = y
            prev = y
        bands.append((start, prev))

        # 精修：在每个粗带内用原始（未膨胀）掩膜找上/下边框，检查夹住的内部是否黑底
        v_ch = hsv[:, :, 2]
        fine_thresh = max(8, int(w * 0.02))
        best, best_v = None, 1e9
        max_row_h = int(h * 0.13)  # 单行最大高度约 70px
        for (t, b) in bands:
            seg = mask[max(0, t - 4): min(h, b + 4)]
            m_rows = np.where(np.count_nonzero(seg, axis=1) > fine_thresh)[0]
            if len(m_rows) < 2:
                continue
            top_edge = int(m_rows[0]) + max(0, t - 4)
            cutoff = top_edge + max_row_h
            m_near = m_rows[m_rows + max(0, t - 4) <= cutoff]
            bot_edge = int(m_near[-1]) + max(0, t - 4)
            it, ib = top_edge + 3, bot_edge - 3
            if ib - it < 8:
                continue
            inner = v_ch[it:ib, w // 5: w * 4 // 5]
            if inner.size == 0:
                continue
            mv = float(inner.mean())
            if mv < best_v:
                best, best_v = (top_edge - 2, bot_edge + 2), mv
        if best is not None and best_v < 130:
            return best
        return None

    def _pick_highlight_line(self, panel, lines):
        """
        在 OCR 行列表中定位高亮行下标。

        主策略：黄绿边框带与行框 y 重叠最大者。
        兜底：高亮行是黑底（整行平均亮度最低），白底普通行亮度高。

        Returns: 行下标或 None
        """
        if not lines:
            return None

        band = self._find_highlight_band(panel)
        if band is not None:
            top, bot = band
            best_i, best_ov = None, 0
            for i, l in enumerate(lines):
                _, y1, _, y2 = l["box"]
                ov = min(y2, bot) - max(y1, top)
                if ov > best_ov:
                    best_i, best_ov = i, ov
            if best_i is not None and best_ov > 0:
                return best_i

        # 兜底：全宽行带平均亮度最低者（黑底高亮行）
        gray = cv2.cvtColor(panel, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]
        best_i, best_score = None, 1e9
        for i, l in enumerate(lines):
            _, y1, _, y2 = l["box"]
            by1 = max(0, y1 - 2)
            by2 = min(h, y2 + 2)
            band_gray = gray[by1:by2, :]
            if band_gray.size == 0:
                continue
            score = float(band_gray.mean())
            if score < best_score:
                best_i, best_score = i, score
        if best_score < 120:
            return best_i
        return None

    # ============ 搜索与导航 ============

    @staticmethod
    def _text_matches(ocr_text, target_norm):
        """OCR 文字与归一化目标匹配：完全相等或目标是其子串（容忍 OCR 噪声）"""
        t = _norm_text(ocr_text)
        if not t:
            return False
        return t == target_norm or target_norm in t

    def _toggle_filter_target(self, target, label):
        """在当前打开的筛选面板中找到目标选项并勾选（Enter 切换复选框）"""
        # 第一轮：从当前位置向下搜索
        if self._search_and_focus(target, label):
            return True
        # 第二轮：目标可能在当前位置上方 —— 回顶部后再向下搜索
        self._scroll_to_top()
        return self._search_and_focus(target, label)

    def _scroll_to_top(self):
        """向上翻页直到画面不再变化（列表顶部）"""
        last_key = None
        for _ in range(_MAX_PAGES):
            if not self.is_running:
                return
            panel = self._capture_filter_panel()
            if panel is None:
                time.sleep(0.5)
                continue
            lines = self._ocr_panel_lines(panel)
            key = tuple(_norm_text(l["text"]) for l in lines)
            if key and key == last_key:
                return  # 画面不变，已到顶
            last_key = key
            for _ in range(10):
                self.hw_press("up", delay=_PRESS_DELAY)
                time.sleep(_PRESS_GAP)
            time.sleep(_PAGE_SETTLE)

    def _search_and_focus(self, target, label):
        """
        逐键搜索目标选项（每按 1 次下就 OCR 一次）。

        零过头原理：列表滚动时高亮贴着屏幕底边前进，目标行入屏的那一刻
        高亮正好落在它上面 -> 此时直接 Enter 即命中目标，不会扫过再回头。
        保险：Enter 后用复选框像素差验证，没命中再按一次 Enter 回滚误勾，降级点击。
        终止条件：
        - 画面不再变化 -> 列表到底（夹住），目标不存在
        - 整页文字绕回已见过的页面 -> 列表循环，目标不存在
        """
        target_n = _norm_text(target)
        seen_pages = set()
        last_page_key = None
        first_check = True
        stuck_count = 0  # 连续画面不变计数（容错偶尔丢键：单次不变只重试，连续两次才判到底）

        for step in range(_MAX_WALK_STEPS):
            if not self.is_running:
                return False
            panel = self._capture_filter_panel()
            if panel is None:
                time.sleep(0.3)
                continue
            lines = self._ocr_panel_lines(panel)
            if not lines:
                time.sleep(0.3)
                continue

            page_key = tuple(_norm_text(l["text"]) for l in lines)
            hl_idx = self._pick_highlight_line(panel, lines)

            # 卡底检测：画面不变 -> 可能丢键（重试一次）或真的到底了（连续两次不变）
            if page_key == last_page_key:
                stuck_count += 1
                if stuck_count >= 2:
                    self._save_filter_debug(panel, lines, hl_idx, f"{label}_{target}_stuck")
                    return False
                self.hw_press("down", delay=_PRESS_DELAY)
                time.sleep(_PRESS_GAP + 0.05)
                continue
            stuck_count = 0
            # 循环检测：整页绕回
            if page_key in seen_pages:
                return False
            seen_pages.add(page_key)
            last_page_key = page_key

            self._save_filter_debug(panel, lines, hl_idx, f"{label}_{target}_step{step}")

            # 目标在可见行中？
            tgt_idx = None
            for i, l in enumerate(lines):
                if self._text_matches(l["text"], target_n):
                    tgt_idx = i
                    break

            if tgt_idx is not None:
                # 1) 高亮行检测成功（未滚动页的黑底样式）：键盘移动 + Enter（已验证路径）
                if hl_idx is not None:
                    return self._move_highlight_and_toggle(
                        panel, lines, hl_idx, tgt_idx, target_n, label
                    )
                # 2) 目标是“本次按键刚入屏”：高亮贴底边 == 正好在目标行，直接 Enter
                #    （Enter 后用复选框像素差验证；没命中会自动回滚 + 降级点击）
                if not first_check:
                    self.log(f"[{label}] 目标刚入屏，高亮应在目标行，Enter 勾选: {target}")
                    return self._toggle_line(panel, lines[tgt_idx], label, enter_first=True)
                # 3) 搜索开始时目标已在屏（高亮位置未知）：点击勾选
                self.log(f"[{label}] 目标可见但高亮位置未知，改用点击勾选: {target}")
                return self._toggle_line(panel, lines[tgt_idx], label)

            first_check = False
            # 不在屏：按 1 次下（逐键检查，不会扫过目标）
            self.hw_press("down", delay=_PRESS_DELAY)
            time.sleep(_PRESS_GAP + 0.05)

        return False

    def _move_highlight_and_toggle(self, panel, lines, hl_idx, tgt_idx, target_n, label):
        """
        把高亮从 hl_idx 移动到 tgt_idx 并 Enter 勾选。

        行差 offset 包含不可聚焦的黄色标题行，实际按键会少几步 ->
        按完后 OCR 校验高亮文字，不符则小范围上/下扫描校正。
        """
        offset = tgt_idx - hl_idx
        if offset > 0:
            for _ in range(offset):
                self.hw_press("down", delay=_PRESS_DELAY)
                time.sleep(_PRESS_GAP)
        elif offset < 0:
            for _ in range(-offset):
                self.hw_press("up", delay=_PRESS_DELAY)
                time.sleep(_PRESS_GAP)
        time.sleep(0.3)

        # 校验高亮行文字
        if self._highlight_is_target(target_n):
            self.hw_press("enter")
            time.sleep(_TOGGLE_SETTLE)
            return True

        # 校正扫描：offset>0 时标题行被跳过 -> 高亮越过目标 -> 先向上找
        first_dir, second_dir = ("up", "down") if offset >= 0 else ("down", "up")
        for direction, max_steps in (
            (first_dir, _MAX_CORRECTION),
            (second_dir, _MAX_CORRECTION * 2),
        ):
            for _ in range(max_steps):
                self.hw_press(direction, delay=_PRESS_DELAY)
                time.sleep(_PRESS_GAP)
                if self._highlight_is_target(target_n):
                    self.hw_press("enter")
                    time.sleep(_TOGGLE_SETTLE)
                    return True
        self.log(f"[{label}] 高亮校正后仍未落在目标行: {target_n}", level="ERROR")
        return False

    def _toggle_line(self, panel, line, label, enter_first=False):
        """
        勾选目标行，全程用复选框区域（行右侧矩形条）像素差验证。

        enter_first=True：目标刚入屏、高亮应在该行 —— 先直接 Enter；没命中时
                          再按一次 Enter 回滚可能的误勾（高亮未移动，第二次 Enter
                          撤销第一次），然后降级点击。
        enter_first=False：高亮位置未知 —— 直接点击：PostMessage -> SendMessage
                          -> 盲 Enter（失败回滚）。
        """
        gx, gy, gw, gh = self.regions["全界面"]
        px0 = gx + int(gw * FILTER_PANEL_REGION["x_start"])
        py0 = gy + int(gh * FILTER_PANEL_REGION["y_start"])
        ph, pw = panel.shape[:2]
        x1, y1, x2, y2 = line["box"]
        cy = (y1 + y2) // 2
        ry1, ry2 = max(0, y1 - 3), min(ph, y2 + 3)
        rx1, rx2 = pw - 48, pw - 4  # 复选框在行右端

        def _cb_crop(img):
            if img is None or img.shape[0] != ph or img.shape[1] != pw:
                return None
            return img[ry1:ry2, rx1:rx2].astype(np.float32)

        before = _cb_crop(panel)
        if before is None or before.size == 0:
            return False

        # Enter 优先路径：高亮应在目标行
        if enter_first:
            self.hw_press("enter")
            time.sleep(0.6)
            after = _cb_crop(self._capture_filter_panel())
            if after is not None and after.shape == before.shape:
                diff = float(np.abs(after - before).mean())
                self.log(f"[{label}] Enter 行「{line['text']}」 复选框差值={diff:.1f}")
                if diff > _CLICK_DIFF_THRESHOLD:
                    return True
            # 没命中：再按一次 Enter 回滚可能的误勾，降级点击
            self.hw_press("enter")
            time.sleep(0.4)
            self.log(f"[{label}] Enter 未命中目标行，降级点击", level="WARN")

        click_x = px0 + pw // 2  # 行横跨整个面板，点水平中心即可
        click_y = py0 + cy

        for use_send in (False, True):
            if not self.is_running:
                return False
            self.game_click((click_x, click_y), use_send=use_send)
            time.sleep(0.5)
            after = _cb_crop(self._capture_filter_panel())
            if after is None or after.shape != before.shape:
                continue
            diff = float(np.abs(after - before).mean())
            self.log(f"[{label}] 点击行「{line['text']}」 use_send={use_send} 复选框差值={diff:.1f}")
            if diff > _CLICK_DIFF_THRESHOLD:
                return True

        # 最后手段：盲 Enter + 验证；未命中目标则再按一次 Enter 回滚可能的误勾
        self.hw_press("enter")
        time.sleep(0.6)
        after = _cb_crop(self._capture_filter_panel())
        if after is not None and after.shape == before.shape:
            diff = float(np.abs(after - before).mean())
            self.log(f"[{label}] 盲 Enter 验证 复选框差值={diff:.1f}")
            if diff > _CLICK_DIFF_THRESHOLD:
                return True
        self.hw_press("enter")
        time.sleep(0.5)
        self.log(f"[{label}] 点击/盲 Enter 均未验证成功，已回滚", level="WARN")
        return False

    def _highlight_is_target(self, target_n):
        """OCR 当前面板，判断高亮行文字是否为目标"""
        panel = self._capture_filter_panel()
        if panel is None:
            return False
        lines = self._ocr_panel_lines(panel)
        hl_idx = self._pick_highlight_line(panel, lines)
        if hl_idx is None:
            return False
        return self._text_matches(lines[hl_idx]["text"], target_n)

    # ============ 调试截图 ============

    def _save_filter_debug(self, panel, lines, hl_idx, name):
        """调试模式开启时保存标注后的面板截图"""
        try:
            enabled = False
            if hasattr(self, "is_debug_screenshots_enabled"):
                enabled = self.is_debug_screenshots_enabled()
            if not enabled:
                return
            out_dir = os.path.join(APP_DIR, "debug", "filter_nav")
            os.makedirs(out_dir, exist_ok=True)
            annotated = panel.copy()
            for i, l in enumerate(lines):
                x1, y1, x2, y2 = l["box"]
                color = (0, 255, 255) if i == hl_idx else (255, 200, 0)
                cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
                cv2.putText(
                    annotated, str(i), (max(0, x1 - 22), y2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
                )
            stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
            safe = "".join(c for c in name if c.isalnum() or c in "-_")
            # 原图（无标注，供颜色/样式分析）+ 标注图
            raw_path = os.path.join(out_dir, f"{stamp}_{safe}_raw.png")
            cv2.imencode(".png", panel)[1].tofile(raw_path)
            out_path = os.path.join(out_dir, f"{stamp}_{safe}.png")
            cv2.imencode(".png", annotated)[1].tofile(out_path)
        except Exception as e:
            self.log(f"[FilterNav] 调试截图保存失败: {e}", level="WARN")
