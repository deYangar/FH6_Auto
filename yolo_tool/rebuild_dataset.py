"""
rebuild_dataset.py — 从 raw/ 构建 YOLO 训练数据集
用法:
    python rebuild_dataset.py                  默认构建（有清单则沿用，新图进训练集）
    python rebuild_dataset.py --fresh-split    强制重新划分 train/val 并刷新清单
    python rebuild_dataset.py --val-ratio 0.2 --seed 42

目录约定（脚本所在目录即项目根）:
    raw/<任意子目录>/*.png + *.txt   原始图片与同名 YOLO 标注
    config/classes.json              类别定义
    data/                            构建产物（images / labels / dataset.yaml / split_manifest.json）

划分规则:
    1. 首次构建：按子目录分层抽样（每个子目录按比例进验证集，避免某方案/类别整组缺席）
    2. 划分结果写入 data/split_manifest.json，之后验证集固定不变，
       新增图片默认进训练集 → 多轮训练指标可严格对比
    3. 想彻底重划分：--fresh-split
"""

import argparse
import datetime
import json
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IMG_EXTS = {".png", ".jpg", ".jpeg", ".bmp"}


def find_raw_dir():
    """定位 raw 目录（优先脚本同级 raw/，兼容旧版 data/raw/ 布局）"""
    for cand in (ROOT / "raw", ROOT / "data" / "raw"):
        if cand.is_dir():
            return cand
    print("❌ 找不到 raw/ 目录。请把带标注的图片放在脚本同级的 raw/<子目录>/ 下。")
    sys.exit(1)


def load_classes():
    for p in (ROOT / "config" / "classes.json", ROOT.parent / "config" / "classes.json"):
        if p.is_file():
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    print("❌ 找不到 config/classes.json")
    sys.exit(1)


def collect_samples(raw_dir: Path):
    """收集所有「图片 + 同名 txt 标注」的样本"""
    samples = []
    for img_path in sorted(raw_dir.rglob("*")):
        if img_path.suffix.lower() not in IMG_EXTS:
            continue
        label_path = img_path.with_suffix(".txt")
        if not label_path.is_file():
            continue
        lines = [l.strip() for l in label_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        if not lines:
            continue
        ok = True
        for line in lines:
            parts = line.split()
            if len(parts) < 5:
                ok = False
                break
            try:
                int(parts[0])
                for x in parts[1:5]:
                    float(x)
            except ValueError:
                ok = False
                break
        if not ok:
            print(f"  ⚠️ 标注格式错误，跳过: {label_path}")
            continue
        rel = img_path.relative_to(raw_dir)
        samples.append({
            "img": img_path,
            "label": label_path,
            "rel": rel.as_posix(),          # 如 scheme_1_wheelspin/xxx.png，清单用它做键
            "tag": rel.parent.as_posix(),   # 如 scheme_1_wheelspin；直接放 raw/ 下则为 "."
        })
    return samples


def stratified_split(samples, val_ratio, seed):
    """按子目录分层抽样，返回 val 集合（rel 路径）"""
    val_keys = set()
    by_tag = {}
    for s in samples:
        by_tag.setdefault(s["tag"], []).append(s)
    for tag, group in sorted(by_tag.items()):
        rng = random.Random(f"{seed}:{tag}")
        rng.shuffle(group)
        n_val = round(len(group) * val_ratio) if len(group) >= 2 else 0
        for s in group[:n_val]:
            val_keys.add(s["rel"])
    if not val_keys and samples:
        # 极端情况：每组都只有 1 张 → 全局兜底抽一张
        rng = random.Random(seed)
        val_keys.add(rng.choice(samples)["rel"])
    return val_keys


def load_manifest(out: Path):
    p = out / "split_manifest.json"
    if p.is_file():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            print("  ⚠️ split_manifest.json 损坏，将重新划分")
    return None


def save_manifest(out: Path, val_keys, val_ratio, seed, note):
    p = out / "split_manifest.json"
    data = {
        "version": 1,
        "val_ratio": val_ratio,
        "seed": seed,
        "note": note,
        "updated": datetime.datetime.now().isoformat(timespec="seconds"),
        "val": sorted(val_keys),
    }
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def run_rebuild(raw_dir=None, output_dir=None, val_ratio=0.2, seed=42, fresh_split=False):
    """构建数据集，返回 dataset.yaml 的 Path"""
    raw = Path(raw_dir) if raw_dir else find_raw_dir()
    out = Path(output_dir) if output_dir else ROOT / "data"

    print(f"📁 项目根目录: {ROOT}")
    print(f"📁 原始数据:   {raw}")
    print(f"📁 输出目录:   {out}")

    classes_data = load_classes()
    classes = classes_data.get("classes", {})
    names = {int(k): v["name"] for k, v in classes.items()}
    print(f"📋 类别数:     {len(names)}")

    samples = collect_samples(raw)
    if not samples:
        print("❌ 没有找到有效的「图片+标注」对。请检查 raw/ 下图片与 .txt 是否同名同目录。")
        sys.exit(1)
    print(f"📊 找到 {len(samples)} 张有效图片")

    # ---------- 决定划分 ----------
    manifest = None if fresh_split else load_manifest(out)
    if manifest is not None:
        known_val = set(manifest.get("val", []))
        existing = {s["rel"] for s in samples}
        val_keys = known_val & existing
        new_files = [s["rel"] for s in samples if s["rel"] not in known_val]
        gone = len(known_val - existing)
        note = manifest.get("note", "")
        print(f"📌 沿用已有划分清单: 验证集固定 {len(val_keys)} 张")
        if new_files:
            print(f"   新增 {len(new_files)} 张图片 → 全部进训练集")
        if gone:
            print(f"   清单中 {gone} 张图片已不在 raw/，忽略")
        if fresh_split:
            print("   （--fresh-split：本次为强制重划分）")
    else:
        val_keys = stratified_split(samples, val_ratio, seed)
        new_files = []
        note = "首次分层划分（按子目录比例抽样）"
        print(f"📌 首次构建：按子目录分层抽样，划分清单已固定")

    # ---------- 清理旧产物并复制 ----------
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        d = out / sub
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)

    train_samples = [s for s in samples if s["rel"] not in val_keys]
    val_samples = [s for s in samples if s["rel"] in val_keys]
    print(f"   训练集: {len(train_samples)} 张")
    print(f"   验证集: {len(val_samples)} 张")

    class_counts = Counter()
    for split_name, split_samples in (("train", train_samples), ("val", val_samples)):
        for s in split_samples:
            # 文件名加子目录前缀避免不同子目录同名冲突
            prefix = s["tag"].replace("/", "_").replace("\\", "_")
            new_name = s["img"].name if prefix == "." else f"{prefix}_{s['img'].name}"

            dst_img = out / "images" / split_name / new_name
            shutil.copy2(s["img"], dst_img)

            dst_label = out / "labels" / split_name / (dst_img.stem + ".txt")
            shutil.copy2(s["label"], dst_label)

            for line in s["label"].read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    class_counts[int(line.split()[0])] += 1

    # ---------- 清单与 yaml ----------
    save_manifest(out, val_keys, val_ratio, seed, note)

    yaml_lines = [
        f"path: {out.resolve().as_posix()}",
        "train: images/train",
        "val: images/val",
        "",
        f"nc: {len(names)}",
        "names:",
    ]
    for idx in sorted(names):
        yaml_lines.append(f"  {idx}: {names[idx]}")
    yaml_path = out / "dataset.yaml"
    yaml_path.write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")

    print("\n📈 各类标注数:")
    for cid in sorted(names):
        count = class_counts.get(cid, 0)
        bar = "█" * min(count, 50)
        print(f"  class {cid} ({names[cid]:22s}): {count:4d} {bar}")
    print(f"  {'总计':30s}: {sum(class_counts.values()):4d}")
    print(f"\n✅ 数据集构建完成: {yaml_path}")
    print(f"   划分清单: {out / 'split_manifest.json'}（验证集已固定，重划分用 --fresh-split）")
    return yaml_path


def main():
    parser = argparse.ArgumentParser(description="构建 YOLO 训练数据集")
    parser.add_argument("--raw-dir", default=None, help="原始数据目录（默认自动查找 raw/）")
    parser.add_argument("--output", default=None, help="输出目录（默认脚本同级 data/）")
    parser.add_argument("--val-ratio", type=float, default=0.2, help="验证集比例（默认 0.2，仅首次划分生效）")
    parser.add_argument("--seed", type=int, default=42, help="随机种子（默认 42，仅首次划分生效）")
    parser.add_argument("--fresh-split", action="store_true", help="强制重新划分 train/val 并刷新清单")
    args = parser.parse_args()
    run_rebuild(args.raw_dir, args.output, args.val_ratio, args.seed, args.fresh_split)


if __name__ == "__main__":
    main()
