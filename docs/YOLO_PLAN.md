# FH6Auto YOLO 识别方案 v3

> 版本: v3.0 | 日期: 2026-07-24
> 核心思路：单模型，按车辆外观打标签，训练集累积管理

---

## 一、类别设计

### 1.1 类别表

```
class 0: new_tag               NEW 角标（所有方案通用，外观一致）
class 1: class_s2829           S2829 等级标签
class 2: class_s1702           S1702 等级标签
class 3: revuelto_with_new     方案1 车卡 + 带 NEW
class 4: revuelto_no_new       方案1 车卡 + 不带 NEW
class 5: madmike_with_new      方案2 车卡 + 带 NEW
class 6: madmike_no_new        方案2 车卡 + 不带 NEW
```

### 1.2 类别命名规则

```
{车辆标识}_{状态}

状态只有两种：
  with_new   — 车卡右下角有 NEW 角标（超抽界面）
  no_new     — 车卡没有 NEW 角标（删车/买车界面）

等级标签：
  class_{标签文字}  — 如 class_s2829, class_s1702, class_b600
```

### 1.3 加车/加方案/换车操作

| 操作 | 动作 |
|------|------|
| 加新方案（新车） | classes.json 加 2 个类（with_new + no_new）+ 等级标签类 + 截图标注 + 重训 |
| 方案换车 | 删旧车类的标注数据 + 加新车类 + 重训 |
| 删方案 | 从训练集中移除该方案的所有数据 + 重训 |
| 加新等级标签 | classes.json 加 1 个类 + 截图标注 + 重训 |

---

## 二、类别配置 `config/classes.json`

```json
{
  "version": 1,
  "classes": {
    "0": {"name": "new_tag",            "description": "NEW 角标",                    "persistent": true},
    "1": {"name": "class_s2829",        "description": "S2829 等级标签",              "scheme": 1},
    "2": {"name": "class_s1702",        "description": "S1702 等级标签",              "scheme": 2},
    "3": {"name": "revuelto_with_new",  "description": "Revuelto 车卡 + 带 NEW",      "scheme": 1, "vehicle": "revuelto"},
    "4": {"name": "revuelto_no_new",    "description": "Revuelto 车卡 + 不带 NEW",    "scheme": 1, "vehicle": "revuelto"},
    "5": {"name": "madmike_with_new",   "description": "Mad Mike 车卡 + 带 NEW",      "scheme": 2, "vehicle": "madmike"},
    "6": {"name": "madmike_no_new",     "description": "Mad Mike 车卡 + 不带 NEW",    "scheme": 2, "vehicle": "madmike"}
  },
  "next_class_id": 7
}
```

**加方案3（保时捷）时，改这个文件：**
```json
"7": {"name": "class_b600",           "description": "B600 等级标签",              "scheme": 3},
"8": {"name": "porsche_with_new",     "description": "Porsche 车卡 + 带 NEW",      "scheme": 3, "vehicle": "porsche"},
"9": {"name": "porsche_no_new",       "description": "Porsche 车卡 + 不带 NEW",    "scheme": 3, "vehicle": "porsche"}
```

然后同步改 `dataset.yaml` 的 names，补截图标注，重训。

---

## 三、方案配置 `config/schemes.json`

```json
{
  "schemes": {
    "scheme_1": {
      "name": "方案1 - Revuelto",
      "vehicle": "revuelto",
      "wheelspin_class": "revuelto_with_new",
      "delete_class": "revuelto_no_new",
      "buy_class": "revuelto_no_new",
      "class_tag": "class_s2829",
      "reference_templates": {
        "newCC": "images/scheme_1/newCC.png",
        "removecarobject": "images/scheme_1/removecarobject.png",
        "consumablecar": "images/scheme_1/consumablecar.png",
        "class_tag": "images/scheme_1/classS2829.png"
      }
    },
    "scheme_2": {
      "name": "方案2 - Mad Mike",
      "vehicle": "madmike",
      "wheelspin_class": "madmike_with_new",
      "delete_class": "madmike_no_new",
      "buy_class": "madmike_no_new",
      "class_tag": "class_s1702",
      "reference_templates": {
        "newCC": "images/scheme_2/newCC.png",
        "removecarobject": "images/scheme_2/removecarobject.png",
        "consumablecar": "images/scheme_2/consumablecar.png",
        "class_tag": "images/scheme_2/classS1702.png"
      }
    }
  }
}
```

**推理时的匹配逻辑：**
```
当前方案 = scheme_1，当前阶段 = 超抽
  → 目标类 = revuelto_with_new (class 3)
  → 校验类 = class_s2829 (class 1)
  → YOLO 检测出所有 boxes
  → 找 class 3 的 boxes
  → 每个候选检查附近有没有 class 1 的 box
  → 返回匹配的那个

当前方案 = scheme_1，当前阶段 = 删车
  → 目标类 = revuelto_no_new (class 4)
  → 找 class 4 的 boxes，附近不能有 new_tag (class 0)
  → 返回第一个
```

---

## 四、训练集管理

### 4.1 目录结构

```
data/
├── dataset.yaml              ← YOLO 数据集配置（自动生成）
├── classes.json              ← 类别定义
├── schemes.json              ← 方案配置
│
├── raw/                      ← 原始截图（按来源组织，保留不删除）
│   ├── scheme_1_wheelspin/   ← 方案1超抽界面
│   ├── scheme_1_delete/      ← 方案1删车界面
│   ├── scheme_2_wheelspin/
│   ├── scheme_2_delete/
│   └── ...
│
├── images/
│   ├── train/                ← 训练图片（从 raw 复制/链接）
│   └── val/                  ← 验证图片
│
└── labels/
    ├── train/                ← 训练标注（YOLO txt 格式）
    └── val/                  ← 验证标注
```

### 4.2 训集累积规则

```
原始截图永远保留在 raw/ 不删（作为历史记录）

训练集操作：
  加新车 → raw/ 新增目录 + 标注 + 合并到 images/labels
  换旧车 → 从 images/labels 中移除旧车类的标注文件
           （raw/ 中的旧截图保留，万一要回退）
  删方案 → 从 images/labels 中移除该方案所有标注
```

### 4.3 自动维护脚本

```python
# scripts/rebuild_dataset.py
"""
根据 classes.json 和 raw/ 目录，自动重建 images/ 和 labels/ 目录。
- 新增的类自动从 raw/ 中提取对应标注
- 删除的类自动从训练集中过滤
- 自动划分 train/val（8:2）
- 自动生成 dataset.yaml
"""

import json, os, shutil, random
from pathlib import Path

def rebuild(classes_json, raw_dir, output_dir, val_ratio=0.2):
    with open(classes_json, "r", encoding="utf-8") as f:
        classes = json.load(f)["classes"]

    active_class_names = {v["name"] for v in classes.values()}

    images_train = Path(output_dir) / "images" / "train"
    images_val = Path(output_dir) / "images" / "val"
    labels_train = Path(output_dir) / "labels" / "train"
    labels_val = Path(output_dir) / "labels" / "val"
    for d in [images_train, images_val, labels_train, labels_val]:
        d.mkdir(parents=True, exist_ok=True)

    # 收集所有有标注的图片
    all_samples = []
    for label_file in Path(raw_dir).rglob("*.txt"):
        img_file = label_file.with_suffix(".png")
        if not img_file.exists():
            continue
        # 读取标注，过滤掉已删除的类
        filtered_lines = []
        with open(label_file, "r") as f:
            for line in f:
                cls_id = int(line.strip().split()[0])
                cls_name = classes.get(str(cls_id), {}).get("name")
                if cls_name in active_class_names:
                    filtered_lines.append(line.strip())
        if filtered_lines:
            all_samples.append((img_file, filtered_lines))

    # 划分 train/val
    random.shuffle(all_samples)
    split_idx = int(len(all_samples) * (1 - val_ratio))
    train_samples = all_samples[:split_idx]
    val_samples = all_samples[split_idx:]

    for samples, img_dir, lbl_dir in [
        (train_samples, images_train, labels_train),
        (val_samples, images_val, labels_val),
    ]:
        for img_file, labels in samples:
            shutil.copy2(img_file, img_dir / img_file.name)
            with open(lbl_dir / (img_file.stem + ".txt"), "w") as f:
                f.write("\n".join(labels) + "\n")

    # 生成 dataset.yaml
    names = {int(k): v["name"] for k, v in sorted(classes.items(), key=lambda x: int(x[0]))}
    yaml_content = f"path: {os.path.abspath(output_dir)}\n"
    yaml_content += "train: images/train\nval: images/val\n\nnames:\n"
    for idx, name in names.items():
        yaml_content += f"  {idx}: {name}\n"
    with open(Path(output_dir) / "dataset.yaml", "w") as f:
        f.write(yaml_content)

    print(f"重建完成: {len(train_samples)} 训练 + {len(val_samples)} 验证")
    print(f"活跃类别: {active_class_names}")
```

**使用方式：**
```bash
# 加了新车的截图和标注后，一条命令重建数据集
python scripts/rebuild_dataset.py

# 然后拷贝 data/ 到 GPU 机器训练
```

---

## 五、截图采集与标注

### 5.1 采集

```bash
# 进入游戏对应界面后运行
python scripts/collect.py scheme_1_wheelspin    # 方案1超抽界面，自动截图30分钟
python scripts/collect.py scheme_1_delete       # 方案1删车界面
```

### 5.2 标注

```bash
# 1. 用现有模板自动预标注（覆盖 70-80%）
python scripts/auto_label.py --scheme scheme_1 --stage wheelspin

# 2. 用 LabelImg 手动修正
labelImg data/raw/scheme_1_wheelspin data/classes.txt

# 3. 重建数据集
python scripts/rebuild_dataset.py
```

### 5.3 标注时注意事项

同一张截图里可能有多个类需要标：
- 车卡本身 → 标 `revuelto_with_new`（class 3）
- NEW 角标 → 标 `new_tag`（class 0）
- 等级标签 → 标 `class_s2829`（class 1）

三个框可以重叠（YOLO 支持），标注时一张图标完所有可见元素。

---

## 六、训练

### 6.1 环境（GPU 机器）

```bash
conda create -n yolo python=3.11 -y
conda activate yolo
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install ultralytics
```

### 6.2 首次训练

```bash
yolo detect train \
    model=yolo26n.pt \
    data=data/dataset.yaml \
    epochs=100 \
    imgsz=640 \
    batch=16 \
    device=0 \
    patience=30 \
    project=models/runs \
    name=v1
```

### 6.3 增量训练（加新车/换车后）

```bash
# 在上次最佳模型基础上继续训练
yolo detect train \
    model=models/runs/v1/weights/best.pt \
    data=data/dataset.yaml \
    epochs=50 \
    imgsz=640 \
    batch=16 \
    device=0 \
    patience=20 \
    project=models/runs \
    name=v2_add_porsche
```

### 6.4 导出

```bash
yolo export model=models/runs/v2_add_porsche/weights/best.pt format=onnx simplify=True
```

---

## 七、推理集成（后期）

```python
# yolo_recognizer.py — 集成到主项目
from ultralytics import YOLO
import cv2

class YoloRecognizer:
    def __init__(self, model_path="models/best.pt"):
        self.model = YOLO(model_path)

    def detect(self, screen_bgr, conf=0.25):
        """返回所有检测结果"""
        results = self.model(screen_bgr, conf=conf, verbose=False)
        boxes = []
        for r in results:
            for box in r.boxes:
                cls_id = int(box.cls[0])
                conf_val = float(box.conf[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                boxes.append({
                    "class_id": cls_id,
                    "class_name": self.model.names[cls_id],
                    "conf": conf_val,
                    "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                    "cx": (x1 + x2) / 2, "cy": (y1 + y2) / 2,
                })
        return boxes

    def find_target(self, screen_bgr, target_class, verify_class=None, conf=0.25):
        """
        找目标车辆。
        target_class: 目标类名，如 "revuelto_with_new"
        verify_class: 校验类名，如 "class_s2829"（检查附近有没有）
        """
        boxes = self.detect(screen_bgr, conf=conf)
        targets = [b for b in boxes if b["class_name"] == target_class]
        if not targets:
            return None

        if verify_class:
            verifiers = [b for b in boxes if b["class_name"] == verify_class]
            for t in targets:
                for v in verifiers:
                    # 校验标签在车卡附近（右下角区域）
                    dx = v["cx"] - t["cx"]
                    dy = v["cy"] - t["cy"]
                    if -50 <= dx <= 100 and -20 <= dy <= 100:
                        return (int(t["cx"]), int(t["cy"]))
            return None

        best = max(targets, key=lambda b: b["conf"])
        return (int(best["cx"]), int(best["cy"]))
```

**主项目集成（加开关）：**
```python
# cj_logic.py 中
if self.config.get("use_yolo", False):
    target_class = self.schemes[scheme]["wheelspin_class"]  # "revuelto_with_new"
    verify_class = self.schemes[scheme]["class_tag"]         # "class_s2829"
    pos = self.yolo.find_target(screen_bgr, target_class, verify_class)
else:
    pos = self.wait_for_new_consumable_car_strict(timeout=3.0, interval=0.2)
```

---

## 八、项目结构

```
yolo_tool/
├── README.md
├── requirements.txt
├── setup.bat
│
├── config/
│   ├── classes.json              ← 类别定义（加车改这里）
│   └── schemes.json              ← 方案映射（加方案改这里）
│
├── scripts/
│   ├── collect.py                ← 截图采集
│   ├── auto_label.py             ← 模板预标注
│   ├── rebuild_dataset.py        ← 重建训练集（过滤已删除类 + 划分 train/val）
│   ├── train.py                  ← 训练封装脚本
│   ├── export_onnx.py            ← 导出 ONNX
│   └── validate.py               ← 验证模型效果
│
├── data/                         ← 数据集（.gitignore）
│   ├── raw/                      ← 原始截图（永不删除）
│   ├── images/{train,val}/
│   ├── labels/{train,val}/
│   └── dataset.yaml              ← 自动生成
│
├── models/                       ← 训练产物（.gitignore）
│   └── runs/
│
└── test/
    ├── test_inference.py
    └── test_images/
```

---

## 九、完整工作流示例

### 场景：从零开始，两个方案

```
1. 创建 yolo_tool/ 项目骨架
2. 游戏中截图：
   - 方案1超抽界面 → data/raw/scheme_1_wheelspin/ （~100张）
   - 方案1删车界面 → data/raw/scheme_1_delete/    （~80张）
   - 方案2超抽界面 → data/raw/scheme_2_wheelspin/ （~100张）
   - 方案2删车界面 → data/raw/scheme_2_delete/    （~80张）
3. 标注（预标注 + 手动修正，~4-6小时）
4. python rebuild_dataset.py
5. 拷贝 data/ 到 GPU 机器
6. 训练 yolo26n 100 epochs（~30分钟）
7. 导出 best.pt
8. 拷贝回部署机器，集成到主项目
```

### 场景：加方案3（保时捷）

```
1. classes.json 加 3 个类：
   - class_b600 (class 7)
   - porsche_with_new (class 8)
   - porsche_no_new (class 9)
2. schemes.json 加 scheme_3 配置
3. 截图：scheme_3_wheelspin + scheme_3_delete （~180张）
4. 标注（~2-3小时）
5. rebuild_dataset.py
6. 在旧模型基础上增量训练 50 epochs
7. 导出 → 部署
```

### 场景：方案1换车（Revuelto → 保时捷）

```
1. classes.json：
   - 删除 class 3 (revuelto_with_new)、class 4 (revuelto_no_new)
   - 新增 class 3 (porsche_with_new)、class 4 (porsche_no_new)
     （复用 slot，不增加类总数）
2. schemes.json 改 scheme_1 的 vehicle 和类名映射
3. rebuild_dataset.py（自动过滤掉旧 revuelto 标注）
4. 截图新车 + 标注
5. rebuild_dataset.py（合并新车数据）
6. 增量训练 50 epochs
7. 导出 → 部署
```

---

## 十、FAQ

**Q: YOLO 能区分不同车辆的缩略图吗？**
A: 能。每辆车的缩略图外观不同（车型、颜色、角度），YOLO 通过训练学习这些视觉差异。这就是目标检测的基本能力。

**Q: 训练集越来越大怎么办？**
A: YOLO 训练集几千张完全没问题。目前 2 方案 ~400 张，加到 10 方案也就 ~2000 张，YOLO26n 训练 2000 张 100 epochs 在 GPU 上 ~1 小时。

**Q: 类别数增长会影响速度吗？**
A: 几乎不影响。YOLO 推理时间 99% 在 backbone，分类头的计算量可忽略。10 类和 3 类的差距 <0.1ms。

**Q: 旧车数据删了以后想回退怎么办？**
A: raw/ 目录永远不删。rebuild_dataset.py 根据 classes.json 的当前类自动过滤。想回退就改回 classes.json 重新 rebuild。

**Q: 能不能用上游的模型直接跑？**
A: 不建议。上游的模型是按他们的车辆训练的，你的方案车辆不同。但可以参考他们的标注方式和训练参数。
