# -*- coding: utf-8 -*-
"""验证假设：no_new 车卡框是否比 with_new 短（不含底部信息栏），
导致真实角标落在框外、交叉验证包含率=0、救回路径永远不触发。"""
import os, sys, cv2
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BASE)
from yolo_detector import YoloDetector, box_containment

det = YoloDetector(conf_threshold=0.10); det.init()

for f in ["debug/PixPin_2026-07-28_11-31-34.png", "debug/PixPin_2026-07-28_11-31-44.png"]:
    img = cv2.imread(os.path.join(BASE, f))
    dets = det.detect(img, conf=0.25)
    print(f"\n=== {os.path.basename(f)} ===")
    for cid, name in [(5, "with_new"), (6, "no_new")]:
        boxes = [d for d in dets if d["class_id"] == cid]
        if boxes:
            hs = [d["y2"] - d["y1"] for d in boxes]
            ws = [d["x2"] - d["x1"] for d in boxes]
            print(f"{name:9s} x{len(boxes)}  h: min={min(hs)} max={max(hs)}  w: min={min(ws)} max={max(ws)}")
    tags = [d for d in dets if d["class_id"] == 0 and d["conf"] >= 0.5]
    no_new = [d for d in dets if d["class_id"] == 6]
    # 模拟：把 with_new 卡片的框换成同类 no_new 的平均高度，看角标包含率
    if tags and no_new:
        avg_h = sum(d["y2"] - d["y1"] for d in no_new) / len(no_new)
        avg_h_with = sum(d["y2"] - d["y1"] for d in dets if d["class_id"] == 5) / max(1, len([d for d in dets if d["class_id"] == 5]))
        print(f"avg_h: no_new={avg_h:.1f}  with_new={avg_h_with:.1f}")
        for t in tags[:4]:
            tbox = (t["x1"], t["y1"], t["x2"], t["y2"])
            for d in [d for d in dets if d["class_id"] in (5, 6)]:
                cbox = (d["x1"], d["y1"], d["x2"], d["y2"])
                cont = box_containment(tbox, cbox)
                if cont > 0.05:
                    print(f"  tag({t['x1']},{t['y1']},{t['x2']},{t['y2']}) conf={t['conf']:.2f} vs {d['name']} cont={cont:.2f}")
