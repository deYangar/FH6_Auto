"""YOLO 检测器单元测试：用 raw/ 截图验证模型加载、检测、高层接口。

用法（项目根目录）：
    python yolo_tool/test_detector.py
"""
import os
import sys
import time
import pathlib

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import cv2
from yolo_detector import YoloDetector, SCHEME_TARGETS

RAW = BASE / "yolo_tool" / "raw"

SCHEME_DIRS = {
    "scheme_1_wheelspin": 1,
    "scheme_2_wheelspin": 2,
}


def main():
    det = YoloDetector()
    assert det.init(), "模型加载失败"

    total = 0
    with_new_hits = 0
    no_new_hits = 0
    misses = 0
    times = []

    for dirname, scheme in SCHEME_DIRS.items():
        folder = RAW / dirname
        if not folder.is_dir():
            print(f"[SKIP] 目录不存在: {folder}")
            continue
        imgs = sorted(folder.glob("*.png"))
        print(f"\n=== {dirname} (scheme={scheme}, {len(imgs)} 张) ===")
        for p in imgs:
            img = cv2.imread(str(p))
            if img is None:
                print(f"  [X] 读取失败: {p.name}")
                continue
            t0 = time.perf_counter()
            result = det.find_target_car(img, scheme)
            dt = (time.perf_counter() - t0) * 1000
            times.append(dt)
            total += 1
            if result is None:
                misses += 1
                tag = "MISS"
            elif result["has_new"]:
                with_new_hits += 1
                tag = f"WITH_NEW pos=({result['x']},{result['y']}) conf={result['conf']}"
            else:
                no_new_hits += 1
                tag = f"NO_NEW   pos=({result['x']},{result['y']}) conf={result['conf']}"
            print(f"  [{tag}] {p.name}  ({dt:.0f}ms)")

    print("\n=== 汇总 ===")
    print(f"总图数: {total}")
    print(f"with_new: {with_new_hits}  no_new: {no_new_hits}  miss: {misses}")
    if times:
        print(f"单帧耗时: 平均 {sum(times)/len(times):.0f}ms, 最大 {max(times):.0f}ms, 最小 {min(times):.0f}ms")

    assert total > 0, "没有测试图片"
    assert with_new_hits + no_new_hits > 0, "一张都没检测到，模型或预处理有问题"
    print("\n[OK] 单元测试通过")


if __name__ == "__main__":
    main()
