# -*- coding: utf-8 -*-
"""
离线验证 filter_nav：用 debug/1.png（真实筛选面板截图）测试
- OCR 逐行识别准确率
- 高亮行检测（黄绿边框 / 黑底兜底）
- 各默认目标的可见性与偏移计算

不启动 GUI、不按键，纯视觉验证。
"""
import io
import os
import sys
import cv2
import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from ocr_onnx import OCREngine
from filter_nav import (
    FilterNavMixin, FILTER_PANEL_REGION,
    DEFAULT_SELL_FILTER_SCHEME1, DEFAULT_SELL_FILTER_SCHEME2, DEFAULT_RACE_FILTER,
    _norm_text,
)

IMG_PATH = os.path.join("debug", "1.png")


class MockBot(FilterNavMixin):
    def __init__(self, img):
        self._img = img
        self.is_running = True
        self.config = {}
        h, w = img.shape[:2]
        self.regions = {"全界面": (0, 0, w, h)}
        self._engine = OCREngine(log_func=lambda m: None, use_directml=False)
        self._engine.init()

    def log(self, msg, level=None):
        print(f"[{level or 'INFO'}] {msg}" if level else f"[INFO] {msg}")

    def capture_region(self, region=None):
        return self._img

    def get_ocr_engine(self):
        return self._engine

    def is_debug_screenshots_enabled(self):
        return True

    def hw_press(self, key, delay=0.08, use_send=False):
        print(f"  (模拟按键: {key})")


def main():
    img = cv2.imdecode(np.fromfile(IMG_PATH, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        print(f"无法读取 {IMG_PATH}")
        return 1
    print(f"图片尺寸: {img.shape[1]}x{img.shape[0]}")

    bot = MockBot(img)

    # 1. 截取面板 + OCR 逐行
    panel = bot._capture_filter_panel()
    print(f"面板区域: {panel.shape[1]}x{panel.shape[0]}")
    lines = bot._ocr_panel_lines(panel)
    print(f"\n=== OCR 识别到 {len(lines)} 行 ===")
    for i, l in enumerate(lines):
        x1, y1, x2, y2 = l["box"]
        print(f"  [{i:2d}] y={y1:3d}-{y2:3d} x={x1:3d}-{x2:3d}  {l['text']}")

    # 2. 高亮行检测
    band = bot._find_highlight_band(panel)
    print(f"\n=== 高亮边框带: {band} ===")
    hl_idx = bot._pick_highlight_line(panel, lines)
    if hl_idx is not None:
        print(f"高亮行: [{hl_idx}] {lines[hl_idx]['text']}")
    else:
        print("高亮行: 未检测到!")

    # 3. 各默认目标可见性 + 偏移
    print("\n=== 目标定位（相对高亮行的行偏移）===")
    for label, targets in [
        ("删车筛选 方案1", DEFAULT_SELL_FILTER_SCHEME1),
        ("删车筛选 方案2", DEFAULT_SELL_FILTER_SCHEME2),
        ("跑图选车", DEFAULT_RACE_FILTER),
    ]:
        print(f"\n[{label}] {' -> '.join(targets)}")
        for t in targets:
            tn = _norm_text(t)
            found = None
            for i, l in enumerate(lines):
                if bot._text_matches(l["text"], tn):
                    found = i
                    break
            if found is None:
                print(f"  {t}: 不在当前可见页（需翻页搜索）")
            elif hl_idx is not None:
                print(f"  {t}: 可见于行 {found}，偏移 {found - hl_idx:+d}（+下/-上）")
            else:
                print(f"  {t}: 可见于行 {found}")

    # 4. 标注截图
    out_dir = os.path.join("debug", "filter_nav")
    os.makedirs(out_dir, exist_ok=True)
    annotated = panel.copy()
    for i, l in enumerate(lines):
        x1, y1, x2, y2 = l["box"]
        color = (0, 0, 255) if i == hl_idx else (255, 200, 0)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        cv2.putText(annotated, str(i), (max(0, x1 - 24), y2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    if band is not None:
        cv2.rectangle(annotated, (0, band[0]), (panel.shape[1], band[1]), (0, 255, 0), 3)
    out_path = os.path.join(out_dir, "offline_test.png")
    cv2.imencode(".png", annotated)[1].tofile(out_path)
    print(f"\n标注截图已保存: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
