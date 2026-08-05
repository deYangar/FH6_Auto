# -*- coding: utf-8 -*-
"""filter_nav._toggle_line 三阶段状态机回归测试。

覆盖：
- 阶段 1 鼠标点击成功路径（采样稳定 + 像素差 > 阈值）
- 阶段 2 盲 Enter 成功路径
- 阶段 3 预检（P1 修复）：点击实际成功但验证漏判 + 阶段 2 双 Enter 翻转后，
  阶段 3 必须识别"已勾选"并直接返回 True，不再第三次 toggle
- 阶段 3 move 兜底路径：前两阶段全部无效（按键丢失）时走 _move_highlight_and_toggle
"""
import unittest
from unittest.mock import patch

import numpy as np

from filter_nav import FilterNavMixin


_PANEL_W, _PANEL_H = 555, 540
# 目标行 box（面板坐标系），复选框验证区域 = 行右端 [pw-48, pw-4]
_BOX = (10, 100, 200, 140)
_CB_Y1, _CB_Y2 = 100 - 3, 140 + 3
_CB_X1, _CB_X2 = _PANEL_W - 48, _PANEL_W - 4
_CB_UNCHECKED, _CB_CHECKED = 30, 200  # 未勾选/勾选时的复选框像素值


def _make_panel(cb_value):
    """构造面板：整面深灰，复选框区域为指定像素值（模拟勾选状态）。"""
    panel = np.full((_PANEL_H, _PANEL_W, 3), 30, dtype=np.uint8)
    panel[_CB_Y1:_CB_Y2, _CB_X1:_CB_X2] = cb_value
    return panel


class _ScriptedToggle(FilterNavMixin):
    """按脚本返回截图的测试替身：每次 _capture_filter_panel 弹出一张预置面板。"""

    def __init__(self, panel_seq):
        self.regions = {"全界面": (0, 0, 1600, 900)}
        self.is_running = True
        self.panel_seq = list(panel_seq)
        self.clicks = 0
        self.enter_count = 0
        self.moved = False
        self.messages = []

    def _capture_filter_panel(self):
        if self.panel_seq:
            return self.panel_seq.pop(0)
        return None

    def game_click(self, _pos, **_kwargs):
        self.clicks += 1

    def hw_press(self, key, **_kwargs):
        if key == "enter":
            self.enter_count += 1

    def _move_highlight_and_toggle(self, *_args, **_kwargs):
        self.moved = True
        return True

    def _ocr_panel_lines(self, panel):
        return [{"text": "目标", "box": _BOX}]

    def _pick_highlight_line(self, _panel, _lines):
        return 0

    def _save_filter_debug(self, *_args, **_kwargs):
        pass

    def log(self, message, level=None):
        self.messages.append((level, message))


class ToggleLinePhaseTests(unittest.TestCase):
    def _run(self, seq, label="筛选"):
        bot = _ScriptedToggle(seq)
        panel = _make_panel(_CB_UNCHECKED)
        line = {"text": "目标", "box": _BOX}
        with patch("filter_nav.time.sleep"):
            result = bot._toggle_line(panel, line, label)
        return result, bot

    def test_phase1_click_success(self):
        """阶段 1：点击后采样稳定且像素差>阈值 → 直接成功，不按键。"""
        result, bot = self._run([_make_panel(_CB_CHECKED), _make_panel(_CB_CHECKED)])
        self.assertTrue(result)
        self.assertEqual(1, bot.clicks)
        self.assertEqual(0, bot.enter_count)
        self.assertFalse(bot.moved)

    def test_phase2_blind_enter_success(self):
        """阶段 2：点击无效（采样稳定但无变化）→ 盲 Enter 勾选成功。"""
        result, bot = self._run(
            [_make_panel(_CB_UNCHECKED), _make_panel(_CB_UNCHECKED),
             _make_panel(_CB_CHECKED)]
        )
        self.assertTrue(result)
        self.assertEqual(1, bot.enter_count)
        self.assertFalse(bot.moved)

    def test_phase3_preexisting_check_returns_true_without_third_toggle(self):
        """P1 回归：点击成功但采样不稳漏判 + 阶段2双Enter翻转 → 阶段3预检识别已勾选。

        状态推演：阶段1点击后实际已勾选(但3次采样都不稳定→漏判)；
        阶段2第一次Enter取消勾选(验证失败)、第二次Enter又勾选；
        阶段3若再按Enter会第三次toggle变成未勾选。预检必须直接返回True。
        """
        # 采样序列：3 张过渡图(相邻差大→不稳定) + 阶段2验证(未勾选) + 阶段3预检(已勾选)
        seq = [
            _make_panel(80),   # sample0：勾选动画过渡
            _make_panel(140),  # sample1：仍在变化 → 不稳定
            _make_panel(180),  # sample2：仍在变化 → 不稳定
            _make_panel(_CB_UNCHECKED),  # 阶段2第一次Enter后：取消勾选 → 验证失败
            _make_panel(_CB_CHECKED),    # 阶段3预检：第二次Enter后又勾选 → 已勾选
        ]
        result, bot = self._run(seq)
        self.assertTrue(result)
        self.assertEqual(2, bot.enter_count, "阶段3不得再按Enter（第三次toggle）")
        self.assertFalse(bot.moved, "预检命中后不应走 _move_highlight_and_toggle")

    def test_phase3_falls_back_to_move_highlight(self):
        """阶段 3 move 兜底：点击无效 + Enter 全部丢失 → 走 _move_highlight_and_toggle。"""
        seq = [
            _make_panel(_CB_UNCHECKED),  # sample0
            _make_panel(_CB_UNCHECKED),  # sample1：稳定但无变化 → 阶段1失败
            _make_panel(_CB_UNCHECKED),  # 阶段2第一次Enter后（无效）
            _make_panel(_CB_UNCHECKED),  # 阶段3预检：仍未勾选 → 走move
        ]
        result, bot = self._run(seq)
        self.assertTrue(result)
        self.assertTrue(bot.moved)
        self.assertEqual(2, bot.enter_count)


if __name__ == "__main__":
    unittest.main()
