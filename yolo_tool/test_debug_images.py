# -*- coding: utf-8 -*-
"""用 debug/ 目录下的截图测试方案2（Mad Mike）选车识别。

输出：
  1. 每张图各类别的检测数量 + 置信度分布（低阈值 0.10 看全貌）
  2. find_target_car(scheme=2) 新逻辑（NEW 角标交叉验证）的选择结果
  3. 高阈值（0.5）演示：弱角标候选被拒绝、改选强角标车卡
  4. 标注图保存到 debug/yolo_test/
"""
import os
import sys
import glob
import cv2

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
sys.path.insert(0, ROOT)

from yolo_detector import YoloDetector, CLASS_NAMES, draw_detections  # noqa: E402

DEBUG_DIR = os.path.join(ROOT, "debug")
OUT_DIR = os.path.join(DEBUG_DIR, "yolo_test")


def fmt_result(res):
    chosen = res["chosen"]
    if not chosen:
        return "None"
    return (f"pos=({chosen['x']},{chosen['y']}) car={chosen['conf']:.3f} "
            f"tag={chosen['tag_conf']:.3f} cls={chosen['name']} "
            f"rescued={chosen['rescued']} box={chosen['box']}")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    det = YoloDetector(conf_threshold=0.10)
    if not det.init():
        print("模型加载失败")
        return 1

    imgs = [p for p in sorted(glob.glob(os.path.join(DEBUG_DIR, "*.png"))) if os.path.isfile(p)]
    print(f"共 {len(imgs)} 张测试图\n")

    for path in imgs:
        name = os.path.basename(path)
        img = cv2.imread(path)
        if img is None:
            print(f"[跳过] 无法读取: {name}")
            continue
        stem = os.path.splitext(name)[0]
        print(f"=== {name} ({img.shape[1]}x{img.shape[0]}) ===")

        dets = det.detect(img, conf=0.10)
        print(f"  检测总数(conf>=0.10): {len(dets)}")
        by_class = {}
        for d in dets:
            by_class.setdefault(d["class_id"], []).append(d["conf"])
        for cid in sorted(by_class):
            confs = sorted(by_class[cid], reverse=True)
            print(f"  [{cid}] {CLASS_NAMES.get(cid, '?'):22s} x{len(confs):2d}  "
                  f"conf: {', '.join(f'{c:.3f}' for c in confs)}")

        # 运行阈值 0.25（默认 yolo_conf）
        res25 = det.find_target_car(img, scheme=2, conf=0.25)
        print(f"  conf=0.25 选择: {fmt_result(res25)}")
        for rej in res25["rejected"]:
            print(f"    [拒绝] {rej['name']} conf={rej['conf']:.3f} box={rej['box']} —— {rej['reason']}")

        # 高阈值 0.5 演示（弱角标候选会被拒绝）
        res50 = det.find_target_car(img, scheme=2, conf=0.50)
        print(f"  conf=0.50 选择: {fmt_result(res50)}")
        for rej in res50["rejected"]:
            print(f"    [拒绝] {rej['name']} conf={rej['conf']:.3f} box={rej['box']} —— {rej['reason']}")

        # 标注图（运行阈值 0.25 的检测结果）
        dets25 = [d for d in dets if d["conf"] >= 0.25]
        anno = draw_detections(img, dets25, chosen=res25["chosen"], rejected=res25["rejected"])
        out_path = os.path.join(OUT_DIR, f"anno_{stem}.png")
        cv2.imwrite(out_path, anno)
        print(f"  标注图: {out_path}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
