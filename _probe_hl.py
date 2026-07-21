# -*- coding: utf-8 -*-
"""page6 逐行全特征扫描：找出高亮行(多功能英雄车?)的唯一区别"""
import io, sys, cv2, numpy as np
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from ocr_onnx import OCREngine

engine = OCREngine(log_func=lambda m: None, use_directml=False)
engine.init()
img = cv2.imdecode(np.fromfile(r"debug\debug\filter_nav\20260721_121744_126_删车筛选_全轮驱动_page6_raw.png", dtype=np.uint8), cv2.IMREAD_COLOR)
h, w = img.shape[:2]
hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
lines = engine.detect_lines_in_region(img)

print(f"{'行':>2} {'y范围':>10} {'文字':<14} {'行均V':>6} {'文字对比std':>10} {'左缘彩像':>8} {'右缘彩像':>8} {'勾选框V':>7}")
for i, l in enumerate(lines):
    x1, y1, x2, y2 = l["box"]
    ry1, ry2 = max(0, y1 - 6), min(h, y2 + 6)
    row = img[ry1:ry2, 10:w-10]
    row_v = hsv[ry1:ry2, 10:w-10, 2]
    mean_v = float(row_v.mean())
    std_v = float(row_v.std())
    # 左缘 10px 条：彩色像素(S>50)占比 + 主色相
    left = hsv[ry1:ry2, 2:12]
    lm = left[:, :, 1] > 50
    left_sat = f"{lm.mean()*100:.0f}%H{int(left[:,:,0][lm].mean()) if lm.any() else 0}"
    # 右缘 10px
    right = hsv[ry1:ry2, w-12:w-2]
    rm = right[:, :, 1] > 50
    right_sat = f"{rm.mean()*100:.0f}%H{int(right[:,:,0][rm].mean()) if rm.any() else 0}"
    # 复选框区域平均亮度 (x 515-545)
    cb = hsv[ry1:ry2, 512:548, 2]
    cb_v = float(cb.mean())
    print(f"{i:>2} {y1:>4}-{y2:<4} {l['text']:<14} {mean_v:6.1f} {std_v:10.1f} {left_sat:>8} {right_sat:>8} {cb_v:7.1f}")
