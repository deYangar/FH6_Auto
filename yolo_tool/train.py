"""
train.py — FH6 YOLO 训练（自动构建数据集 + 自动设备选择 + 自动导出 ONNX）

用法:
    python train.py [model] [epochs] [imgsz] [batch] [--device auto|0|cpu] [--no-export]

示例:
    python train.py                            # yolo26s.pt, 100 epochs, 640, batch 自动
    python train.py yolo26s.pt 50              # 50 epochs
    python train.py models\\best.pt 50 640 16  # 基于上次结果增量训练

产物统一为 models\\best.pt / models\\best.onnx（一键训练下次自动基于 best.pt 续训）。
"""

import argparse
import datetime
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def main():
    ap = argparse.ArgumentParser(
        description="FH6 YOLO 训练",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    ap.add_argument("model", nargs="?", default="yolo26s.pt", help="预训练权重或上次的 best.pt")
    ap.add_argument("epochs", nargs="?", type=int, default=100, help="训练轮数（默认 100）")
    ap.add_argument("imgsz", nargs="?", type=int, default=640, help="输入尺寸（默认 640）")
    ap.add_argument("batch", nargs="?", type=int, default=-1, help="批次大小（默认 -1=自动: GPU 16 / CPU 8）")
    ap.add_argument("--device", default="auto", help="训练设备: auto / 0 / cpu（默认 auto）")
    ap.add_argument("--no-export", action="store_true", help="训练完不导出 ONNX")
    ap.add_argument("--lr0", type=float, default=None, help="初始学习率（默认: 续训 0.0002 / 从零 auto）")
    args = ap.parse_args()

    import torch

    cuda = torch.cuda.is_available()
    if args.device == "auto":
        device = 0 if cuda else "cpu"
    elif str(args.device).lower() == "cpu":
        device = "cpu"
    else:
        device = int(args.device)
    batch = args.batch if args.batch > 0 else (16 if cuda else 8)

    print("=" * 50)
    print("  FH6 YOLO 训练")
    print(f"  模型:   {args.model}")
    print(f"  Epochs: {args.epochs} | ImgSz: {args.imgsz} | Batch: {batch}")
    if cuda and device != "cpu":
        print(f"  设备:   GPU ({torch.cuda.get_device_name(0)})")
    else:
        print("  设备:   CPU")
    print("=" * 50)

    if not Path(args.model).exists():
        print(f"\n[i] 本地没有 {args.model}，Ultralytics 会自动从 GitHub 下载预训练权重。")
        print("    若下载卡住或失败：手动下载该权重文件放到本目录，或改用本地已有的 .pt。")

    # 续训判定：本地存在的权重且不是官方预训练命名（yolo26s.pt / yolo11n.pt 等）
    is_finetune = (
        Path(args.model).is_file()
        and not re.match(r"(?i)^yolo(?:v?\d+|11)[nsmxl]*\.pt$", Path(args.model).name)
    )

    # ---------- 1. 构建数据集 ----------
    print("\n[1/3] 构建数据集 ...")
    from rebuild_dataset import run_rebuild

    yaml_path = run_rebuild()

    # ---------- 2. 训练 ----------
    print("\n[2/3] 开始训练 ...")
    from ultralytics import YOLO

    name = "v" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    model = YOLO(args.model)
    train_kwargs = dict(
        data=str(yaml_path),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=batch,
        device=device,
        patience=30,
        project=str(ROOT / "models" / "runs"),
        name=name,
        exist_ok=False,
        pretrained=True,
        seed=42,
        deterministic=True,
        plots=True,
        verbose=True,
        # 关闭 AMP：ultralytics 的 AMP 体检会硬编码下载 yolo26n.pt，
        # 本工具只用 s 模型；且小数据集训练 AMP 无实质加速，fp32 更稳
        amp=False,
    )
    if args.lr0 is not None:
        # 手动指定 lr：固定 AdamW，不用 auto
        train_kwargs.update(optimizer="AdamW", lr0=args.lr0)
        print(f"  [i] 手动学习率 lr0={args.lr0}")
    elif is_finetune:
        # 续训模式：已收敛的权重经不起默认 lr 猛踹（上轮续训 ep7-18 崩盘教训），
        # 降一个量级微调，warmup 也缩短
        train_kwargs.update(optimizer="AdamW", lr0=0.0002, warmup_epochs=1.0)
        print("  [i] 续训模式：lr0=0.0002 / warmup 1 轮（防震荡，--lr0 可覆盖）")
    else:
        train_kwargs.update(optimizer="auto")
    results = model.train(**train_kwargs)

    save_dir = Path(results.save_dir)
    best = save_dir / "weights" / "best.pt"
    models_dir = ROOT / "models"
    models_dir.mkdir(exist_ok=True)
    # models\best.pt = 最新权重：部署直接用，下次一键训练自动基于它续训
    best_copy = models_dir / "best.pt"
    shutil.copy2(best, best_copy)

    # ---------- 3. 导出 ONNX ----------
    onnx_final = None
    if args.no_export:
        print("\n[i] 已跳过 ONNX 导出（--no-export）")
    else:
        print("\n[3/3] 导出 ONNX ...")
        onnx_out = Path(YOLO(str(best)).export(format="onnx", simplify=True, opset=12))
        onnx_final = models_dir / "best.onnx"
        shutil.copy2(onnx_out, onnx_final)

    print("\n" + "=" * 50)
    print("  训练完成！")
    print(f"  运行目录:   {save_dir}")
    print(f"  最佳权重:   {best}")
    print(f"  models\\best.pt 已更新（下次一键训练自动基于它续训）")
    if onnx_final:
        print(f"  ONNX:       {onnx_final}")
    print("=" * 50)


if __name__ == "__main__":
    main()
