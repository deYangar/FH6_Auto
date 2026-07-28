"""
export_onnx.py — 把 best.pt 导出为 ONNX

用法:
    python export_onnx.py                  # 自动找 models/runs 下最新的 best.pt
    python export_onnx.py path\\to\\best.pt

产物: models\\best.onnx
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def find_latest_best():
    runs = ROOT / "models" / "runs"
    if not runs.is_dir():
        return None
    cands = [p for p in runs.glob("*/weights/best.pt") if p.is_file()]
    if not cands:
        return None
    return max(cands, key=lambda p: p.stat().st_mtime)


def main():
    if len(sys.argv) > 1:
        pt = Path(sys.argv[1])
    else:
        pt = find_latest_best()
        if pt is None:
            print("❌ 没找到任何 models/runs/*/weights/best.pt，请先训练（双击「一键训练.bat」）")
            sys.exit(1)
        print(f"[i] 自动选择最新权重: {pt}")

    if not pt.is_file():
        print(f"❌ 权重文件不存在: {pt}")
        sys.exit(1)

    from ultralytics import YOLO

    print(f"[i] 导出中: {pt}")
    onnx_out = Path(YOLO(str(pt)).export(format="onnx", simplify=True, opset=12))

    final = ROOT / "models" / "best.onnx"
    final.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(onnx_out, final)
    print(f"\n✅ 导出完成: {final}")


if __name__ == "__main__":
    main()
