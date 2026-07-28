# YOLO 识别接入主项目方案

> 编写：2026-07-27 | 计划实施：2026-07-28
> 目标：将训练好的 YOLO 模型接入 FH6Auto 主项目，替代模板匹配做"超抽选车"识别

---

## 1. 背景与目标

### 1.1 现状

主项目 `vision.py`（111KB）用 **cv2.matchTemplate** 做所有视觉识别。核心函数 `find_new_consumable_car_strict`（vision.py L775-1137，362 行）用灰度匹配 + 边缘匹配 + NMS + 多尺度 + NEW 角标颜色验证 + 连续帧确认 等一大堆策略拼出"找到带 NEW 角标的目标车卡"这个判断。

痛点：
- 模板匹配对缩放、光照、抗锯齿极敏感，需要大量阈值调参
- 362 行逻辑复杂，维护困难，新方案（scheme 3/4）接入成本高
- 现有代码在"有 NEW 但角度偏"或"车卡部分遮挡"时容易漏检

### 1.2 YOLO 优势

训练好的 YOLO26s 模型（mAP50=0.988）直接输出 7 个类别的检测框：
- new_tag（NEW 角标）
- class_s2829 / class_s1702（等级标签）
- revuelto_with_new / revuelto_no_new（方案1 车卡 ± NEW）
- madmike_with_new / madmike_no_new（方案2 车卡 ± NEW）

一帧推理就能拿到"哪个位置有目标车卡 + 有没有 NEW"，无需多尺度搜索、无需颜色验证、无需连续帧确认。

### 1.3 目标

- **第一阶段**：只替换 `find_new_consumable_car_strict`（超抽选车识别），用 YOLO 推理替代模板匹配
- **保留模板匹配做 fallback**：config.json 开关控制，可随时切回
- **验证稳定后**再逐步扩展到 `find_skill_car_strict` 等其他识别函数

---

## 2. ONNX 模型规格

### 2.1 模型文件

- 训练产物：`yolo_tool/models/best.onnx`（或 `best_s.onnx`）
- 部署位置：`forza_test_tool/onnx_models/yolo_best.onnx`（跟 OCR 模型放一起）
- 文件大小：约 37MB（s 模型）

### 2.2 I/O 规格（已验证）

```
输入：
  name:  "images"
  shape: [1, 3, 640, 640]  (NCHW)
  dtype: float32
  含义:  RGB, 归一化 0-1, 640x640

输出：
  name:  "output0"
  shape: [1, 300, 6]  (batch, max_detections, 6)
  dtype: float32
  每行:  [x1, y1, x2, y2, conf, class_id]
  坐标空间: 640x640 输入空间（需要还原到原图分辨率）
  NMS: 已内置（ultralytics 导出时包含）
```

### 2.3 类别定义（与 classes.json 一致）

```python
CLASS_NAMES = {
    0: "new_tag",
    1: "class_s2829",
    2: "class_s1702",
    3: "revuelto_with_new",
    4: "revuelto_no_new",
    5: "madmike_with_new",
    6: "madmike_no_new",
}

# 方案 -> 目标车卡类映射
SCHEME_TARGETS = {
    1: {  # 方案1 - Revuelto
        "with_new": 3,     # revuelto_with_new
        "no_new": 4,       # revuelto_no_new
        "class_tag": 1,    # class_s2829
    },
    2: {  # 方案2 - Mad Mike
        "with_new": 5,     # madmike_with_new
        "no_new": 6,       # madmike_no_new
        "class_tag": 2,    # class_s1702
    },
}
```

### 2.4 游戏画面规格

- 截图来源：`capture.py` 的 `PrintWindow` 后台截图
- 分辨率：1600x900（窗口客户区，已验证）
- 色彩：BGR（cv2/numpy 原生格式）

---

## 3. 架构设计

### 3.1 新增文件

```
forza_test_tool/
  yolo_detector.py        ← 新增：YOLO ONNX 推理引擎
  onnx_models/
    yolo_best.onnx         ← 新增：训练好的模型（部署模型.bat 拷入）
```

### 3.2 修改文件

```
forza_test_tool/
  vision.py               ← VisionMixin 加 find_target_car_yolo 方法
  cj_logic.py             ← 调用处加 use_yolo 开关分支
  config.json             ← 加 use_yolo 字段
  recognition_config.py   ← 加 cj.yolo_target_car profile（可选）
  yolo_tool/
    部署模型.bat           ← 新增：拷贝 best.onnx 到主项目 onnx_models/
```

### 3.3 数据流

```
游戏画面 (1600x900 BGR)
  ↓ letterbox 到 640x640
  ↓ BGR→RGB, /255, HWC→CHW, 加 batch 维
  ↓ ONNX 推理 (DirectML/CPU)
  ↓ 输出 [1,300,6] = [x1,y1,x2,y2,conf,class_id] (640 空间)
  ↓ 过滤 conf > threshold
  ↓ 坐标还原到 1600x900 (反 letterbox)
  ↓ 按 scheme 找目标车卡
  ↓ 返回 (x, y) 点击坐标 或 None
```

### 3.4 依赖

- `onnxruntime-directml`：**已在 requirements.txt**（OCR 在用），DirectML 后端支持任意 GPU
- `opencv-python`、`numpy`：已有
- **无新增依赖**

---

## 4. yolo_detector.py 完整实现骨架

```python
"""
YOLO 目标检测引擎（ONNX 推理）

用法：
    from yolo_detector import YoloDetector
    det = YoloDetector()
    det.init()
    boxes = det.detect(screen_bgr)           # 全部检测框
    result = det.find_target_car(screen_bgr, scheme=1)  # 高层：找目标车卡
"""

import os
import cv2
import numpy as np
import onnxruntime as ort

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 常量
# ============================================================

MODEL_PATH = os.path.join(BASE_DIR, "onnx_models", "yolo_best.onnx")
INPUT_SIZE = 640

CLASS_NAMES = {
    0: "new_tag",
    1: "class_s2829",
    2: "class_s1702",
    3: "revuelto_with_new",
    4: "revuelto_no_new",
    5: "madmike_with_new",
    6: "madmike_no_new",
}

SCHEME_TARGETS = {
    1: {"with_new": 3, "no_new": 4, "class_tag": 1},
    2: {"with_new": 5, "no_new": 6, "class_tag": 2},
}


# ============================================================
# 预处理 / 后处理
# ============================================================

def letterbox(img, target_size=INPUT_SIZE):
    """
    等比缩放 + 填充到 target_size x target_size。
    返回 (letterboxed_image, scale, pad_x, pad_y)
    """
    h, w = img.shape[:2]
    scale = min(target_size / w, target_size / h)
    new_w = int(w * scale)
    new_h = int(h * scale)
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    pad_x = (target_size - new_w) // 2
    pad_y = (target_size - new_h) // 2
    canvas = np.full((target_size, target_size, 3), 114, dtype=np.uint8)
    canvas[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = resized
    return canvas, scale, pad_x, pad_y


def unletterbox(boxes_640, scale, pad_x, pad_y):
    """将 640 空间的 [x1,y1,x2,y2] 还原到原图坐标"""
    boxes = boxes_640.copy().astype(np.float32)
    boxes[:, 0] = (boxes[:, 0] - pad_x) / scale
    boxes[:, 1] = (boxes[:, 1] - pad_y) / scale
    boxes[:, 2] = (boxes[:, 2] - pad_x) / scale
    boxes[:, 3] = (boxes[:, 3] - pad_y) / scale
    return boxes


def preprocess(img_bgr):
    """
    BGR 图像 -> ONNX 输入张量 [1,3,640,640] float32
    返回 (tensor, scale, pad_x, pad_y)
    """
    lb, scale, pad_x, pad_y = letterbox(img_bgr)
    rgb = cv2.cvtColor(lb, cv2.COLOR_BGR2RGB)
    normalized = rgb.astype(np.float32) / 255.0
    chw = normalized.transpose(2, 0, 1)          # HWC -> CHW
    nchw = np.expand_dims(chw, axis=0)           # 加 batch 维
    return nchw, scale, pad_x, pad_y


# ============================================================
# YoloDetector
# ============================================================

class YoloDetector:
    """YOLO ONNX 推理引擎，仿 OCREngine 模式。"""

    def __init__(self, model_path=None, conf_threshold=0.25):
        self.model_path = model_path or MODEL_PATH
        self.conf_threshold = conf_threshold
        self.session = None
        self.input_name = None
        self._available = False

    def init(self):
        """加载 ONNX 模型。DirectML 优先，CPU 兜底。"""
        if not os.path.isfile(self.model_path):
            print(f"[YoloDetector] 模型不存在: {self.model_path}")
            self._available = False
            return False

        try:
            # 尝试 DirectML（任意 GPU）
            providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
            self.session = ort.InferenceSession(
                self.model_path, providers=providers
            )
            self.input_name = self.session.get_inputs()[0].name
            self._available = True

            # 检查实际启用的 provider
            active = self.session.get_providers()
            print(f"[YoloDetector] 已加载 {os.path.basename(self.model_path)}，后端: {active}")
            return True
        except Exception as e:
            print(f"[YoloDetector] 加载失败: {e}")
            self._available = False
            return False

    @property
    def available(self):
        return self._available

    def detect(self, img_bgr, conf=None):
        """
        对一张图做检测。

        参数:
            img_bgr: numpy 数组, BGR, 任意分辨率
            conf: 置信度阈值 (默认用 self.conf_threshold)

        返回: list of dict, 每个元素:
            {
                "class_id": int,
                "name": str,
                "conf": float,
                "x1": int, "y1": int, "x2": int, "y2": int,  # 原图坐标
                "cx": int, "cy": int,  # 框中心
            }
        """
        if not self._available:
            return []

        conf = conf if conf is not None else self.conf_threshold

        # 预处理
        tensor, scale, pad_x, pad_y = preprocess(img_bgr)

        # 推理
        outputs = self.session.run(None, {self.input_name: tensor})
        raw = outputs[0]  # [1, 300, 6]

        # 过滤置信度
        mask = raw[0, :, 4] > conf
        filtered = raw[0, mask]  # [N, 6]

        if len(filtered) == 0:
            return []

        # 坐标还原
        boxes_640 = filtered[:, :4]     # [N, 4] = x1,y1,x2,y2 in 640 space
        confs = filtered[:, 4]          # [N]
        class_ids = filtered[:, 5].astype(int)  # [N]

        boxes_orig = unletterbox(boxes_640, scale, pad_x, pad_y)

        # 裁剪到原图范围
        h, w = img_bgr.shape[:2]
        boxes_orig[:, [0, 2]] = np.clip(boxes_orig[:, [0, 2]], 0, w)
        boxes_orig[:, [1, 3]] = np.clip(boxes_orig[:, [1, 3]], 0, h)

        results = []
        for i in range(len(filtered)):
            x1, y1, x2, y2 = boxes_orig[i].astype(int)
            cid = int(class_ids[i])
            results.append({
                "class_id": cid,
                "name": CLASS_NAMES.get(cid, f"class_{cid}"),
                "conf": round(float(confs[i]), 3),
                "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                "cx": (x1 + x2) // 2,
                "cy": (y1 + y2) // 2,
            })
        return results

    def find_target_car(self, img_bgr, scheme, conf=None):
        """
        高层接口：在超抽选车画面找到目标车卡的点击位置。

        参数:
            img_bgr: 游戏截图 BGR
            scheme: 1 或 2（方案编号）
            conf: 置信度阈值

        返回:
            找到目标车卡（有 NEW 优先）:
                {"x": int, "y": int, "has_new": bool, "conf": float, "box": (x1,y1,x2,y2)}
            未找到:
                None
        """
        if scheme not in SCHEME_TARGETS:
            return None

        targets = SCHEME_TARGETS[scheme]
        detections = self.detect(img_bgr, conf=conf)

        # 优先找 with_new
        with_new = [d for d in detections if d["class_id"] == targets["with_new"]]
        if with_new:
            best = max(with_new, key=lambda d: d["conf"])
            return {
                "x": best["cx"],
                "y": best["cy"],
                "has_new": True,
                "conf": best["conf"],
                "box": (best["x1"], best["y1"], best["x2"], best["y2"]),
            }

        # 没有 with_new，报告 no_new 的位置（调用方可决定是否等待）
        no_new = [d for d in detections if d["class_id"] == targets["no_new"]]
        if no_new:
            best = max(no_new, key=lambda d: d["conf"])
            return {
                "x": best["cx"],
                "y": best["cy"],
                "has_new": False,
                "conf": best["conf"],
                "box": (best["x1"], best["y1"], best["x2"], best["y2"]),
            }

        return None
```

---

## 5. vision.py 修改点

### 5.1 新增方法（加在 VisionMixin 类内，find_new_consumable_car_strict 之前）

```python
# === YOLO 识别 ===

def find_target_car_yolo(self, screen_bgr=None):
    """
    用 YOLO 模型找目标车卡（替代 find_new_consumable_car_strict）。
    返回 (x, y) 点击坐标，或 None。
    """
    if not hasattr(self, '_yolo_detector') or not self._yolo_detector.available:
        return None

    if screen_bgr is None:
        screen_bgr = self.capture_region()
    if screen_bgr is None:
        return None

    scheme = self.config.get("current_scheme", 0) + 1  # config 是 0-based
    result = self._yolo_detector.find_target_car(screen_bgr, scheme)

    if result is None:
        return None

    # 只返回有 NEW 的车卡（与 find_new_consumable_car_strict 行为一致）
    if not result["has_new"]:
        return None

    return (result["x"], result["y"])
```

### 5.2 YoloDetector 初始化（在 VisionMixin 的初始化路径中）

找到 VisionMixin 被初始化的地方（通常在 main.py 的 Bot 类 `__init__`），加：

```python
# YOLO 检测器懒加载
self._yolo_detector = None

def _ensure_yolo(self):
    """懒加载 YOLO 检测器"""
    if self._yolo_detector is None:
        from yolo_detector import YoloDetector
        self._yolo_detector = YoloDetector()
        self._yolo_detector.init()
    return self._yolo_detector
```

`find_target_car_yolo` 开头改为：
```python
det = self._ensure_yolo()
if not det.available:
    return None
```

---

## 6. cj_logic.py 修改点

### 6.1 调用处加开关

找到 `wait_for_new_consumable_car_strict` 的调用处（cj_logic.py 中 `pos_target = self.wait_for_new_consumable_car_strict(timeout=3.0, interval=0.2)`）。

在 **wait_for_new_consumable_car_strict 方法本身**（vision.py 中）加 YOLO 分支：

```python
def wait_for_new_consumable_car_strict(self, timeout=3.0, interval=0.2, region=None):
    """等待超抽目标车出现，返回 (x, y) 或 None"""
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not self.is_running:
            return None

        screen = self.capture_region(region=region)
        if screen is None:
            time.sleep(interval)
            continue

        # === YOLO 路径 ===
        if self.config.get("use_yolo", False):
            det = self._ensure_yolo()
            if det.available:
                pos = self.find_target_car_yolo(screen)
                if pos:
                    return pos
                time.sleep(interval)
                continue
            # YOLO 不可用，降级到模板匹配

        # === 模板匹配路径（原有逻辑不变） ===
        pos = self.find_new_consumable_car_strict(region=region)
        if pos:
            return pos
        time.sleep(interval)

    return None
```

### 6.2 为什么改 wait_for_* 而不是 find_*

`wait_for_new_consumable_car_strict` 是循环调用者，在里面加 YOLO 分支可以：
- 一次性覆盖所有调用点（cj_logic.py 里所有调 wait_for 的地方自动走 YOLO）
- 保留原有的超时/重试逻辑
- YOLO 不可用时自动降级到模板匹配

---

## 7. config.json 变更

```json
{
  "use_yolo": false,
  "yolo_conf": 0.25,
  ...其他原有字段...
}
```

- `use_yolo`: 是否启用 YOLO 识别（默认 false，安全上线后再切 true）
- `yolo_conf`: YOLO 置信度阈值（默认 0.25，可调）

在 `config.py` 的配置加载逻辑中确保这两个字段有默认值。

---

## 8. 模型部署

### 8.1 部署模型.bat（yolo_tool 目录新增）

```bat
@echo off
setlocal
cd /d "%~dp0"
title 部署 YOLO 模型到主项目

set "SRC=%~dp0dist\FH6_YOLO_Training_Kit\models\best.onnx"
set "DST=%~dp0..\onnx_models\yolo_best.onnx"

if not exist "%SRC%" (
    echo [X] 没找到训练好的模型: %SRC%
    echo     先双击「一键训练.bat」训练一轮。
    pause
    exit /b 1
)

copy /Y "%SRC%" "%DST%" >nul
echo [OK] 已部署: %DST%
echo     主项目 config.json 设 "use_yolo": true 即可启用。
pause
```

### 8.2 部署流程

```
1. yolo_tool\一键训练.bat 训练（已有 best.onnx）
2. yolo_tool\部署模型.bat 拷贝到主项目 onnx_models\yolo_best.onnx
3. 主项目 config.json 设 "use_yolo": true
4. 启动 FH6Auto，超抽选车时走 YOLO 识别
```

---

## 9. 测试计划

### 9.1 单元测试（无需游戏）

```python
# test_yolo_detector.py
from yolo_detector import YoloDetector
import cv2

det = YoloDetector()
assert det.init(), "模型加载失败"

# 用 raw 里的截图测试
img = cv2.imread("yolo_tool/raw/scheme_1_wheelspin/20260727_103229_788.png")
boxes = det.detect(img)
assert len(boxes) > 0, "应该检测到目标"

# 高层接口
result = det.find_target_car(img, scheme=1)
assert result is not None
assert result["has_new"] == True
print(f"目标车卡位置: ({result['x']}, {result['y']}), conf={result['conf']}")
```

### 9.2 对比测试（YOLO vs 模板匹配）

```python
# 遍历 raw/ 所有图，同时跑 YOLO 和模板匹配，对比结果
import pathlib
for img_path in pathlib.Path("yolo_tool/raw").rglob("*.png"):
    img = cv2.imread(str(img_path))
    yolo_result = det.find_target_car(img, scheme=1)
    # template_result = ... (调 vision 的方法)
    print(f"{img_path.name}: YOLO={yolo_result}")
```

### 9.3 真机验证

1. config.json 设 `"use_yolo": true`
2. 启动 FH6Auto，进入超抽流程
3. 观察：
   - YOLO 是否正确识别目标车卡（看 debug 截图）
   - 点击位置是否准确（框中心 vs 实际车卡中心）
   - 识别速度（DirectML 应 < 50ms/帧）
   - 误检/漏检率（跑 10 轮超抽看成功率）
4. 如果有问题，`"use_yolo": false` 一键切回模板匹配

### 9.4 性能预期

| 指标 | 模板匹配（现状） | YOLO（预期） |
|---|---|---|
| 单帧识别耗时 | 100-300ms（多尺度搜索） | 10-50ms（DirectML）/ 100ms（CPU） |
| 识别准确率 | 依赖阈值调参，波动大 | mAP50=0.988，稳定 |
| 代码量 | 362 行 | ~50 行（detect + find_target_car） |
| 新方案接入成本 | 需要新模板+调参 | 只需标注+重训 |

---

## 10. 回滚方案

### 10.1 一键回滚

config.json 设 `"use_yolo": false` -> 立即切回模板匹配，无需改代码。

### 10.2 完全移除

删除以下文件/改动即可完全移除 YOLO：
- 删 `yolo_detector.py`
- 删 `onnx_models/yolo_best.onnx`
- vision.py 删 `find_target_car_yolo` 和 `_ensure_yolo`
- vision.py 的 `wait_for_new_consumable_car_strict` 删 YOLO 分支
- config.json 删 `use_yolo` / `yolo_conf`

---

## 11. 风险与对策

| 风险 | 概率 | 对策 |
|---|---|---|
| DirectML 在某些显卡上不工作 | 低 | 代码自动降级到 CPU；CPU 推理约 100ms 仍可接受 |
| YOLO 在真实游戏画面上表现差（训练数据少） | 中 | use_yolo 开关随时切回；继续标注补数据重训 |
| ONNX 模型文件损坏/缺失 | 低 | init() 返回 False，自动降级到模板匹配 |
| 点击位置不准（框中心 ≠ 可点击区域） | 中 | find_target_car 返回框中心，如不准可调整为框上 1/3 处 |
| 游戏画面分辨率变化 | 低 | letterbox 预处理适配任意分辨率 |
| 模型版本与类别不匹配 | 低 | CLASS_NAMES 硬编码，classes.json 可交叉验证 |

---

## 12. 后续扩展（第一阶段验证通过后）

### 12.1 替换 find_skill_car_strict

vision.py 的 `find_skill_car_strict`（L2058-2278，220 行）也是模板匹配，可用 YOLO 的 class_s2829 / class_s1702 检测替代。

### 12.2 替换 find_skill_car_from_like_tag

`find_skill_car_from_like_tag`（L1858-1928）找"带点赞标签的技能车"--如果标注数据加入"点赞标签"类别，YOLO 可覆盖。

### 12.3 实时检测叠加

在标注工作台的实时预览上叠加 YOLO 检测框，做"所见即所得"的识别验证。

### 12.4 自动标注闭环

游戏跑着 -> 自动截图 -> YOLO 推理 -> 低置信度的自动标注 + 存图 -> 人工修正 -> 增量训练 -> 模型更新 -> 部署。形成数据飞轮。

---

## 13. 实施清单（一次搞定版）

明天按以下顺序执行，每步完成后验证：

- [ ] 1. 创建 `forza_test_tool/yolo_detector.py`（按第 4 节骨架，完整实现）
- [ ] 2. 创建 `yolo_tool/部署模型.bat`（按第 8 节）
- [ ] 3. 运行部署模型.bat，把 best.onnx 拷到 `onnx_models/yolo_best.onnx`
- [ ] 4. 单元测试：`python -c "from yolo_detector import YoloDetector; d=YoloDetector(); d.init(); print(d.detect(cv2.imread('test.png')))"` 用 raw 里的截图
- [ ] 5. 修改 `vision.py`：加 `_ensure_yolo` + `find_target_car_yolo`（第 5 节）
- [ ] 6. 修改 `vision.py`：在 `wait_for_new_consumable_car_strict` 加 YOLO 分支（第 6 节）
- [ ] 7. 修改 `config.json`：加 `"use_yolo": false`（先关着）
- [ ] 8. 修改 `config.py`：确保 use_yolo / yolo_conf 有默认值
- [ ] 9. 启动 FH6Auto 确认不报错（use_yolo=false 应完全无影响）
- [ ] 10. config.json 设 `"use_yolo": true`，真机验证超抽选车
- [ ] 11. 跑 10 轮超抽对比成功率
- [ ] 12. 更新 README

---

*本方案基于 2026-07-27 的代码状态和模型训练成果编写。ONNX I/O 已验证，类映射已确认，API 契约（返回 (x,y) 点击坐标）已从 cj_logic.py 调用链确认。*


---

## 14. 实施记录（2026-07-28，与原方案的差异）

实际接入按咩咩确认的修正版执行：

1. **接入点改为 ind_new_consumable_car_strict 顶部**（非第 6 节的 wait_for_* 重写）。
   原方案的重写会丢掉现有保护：15s 绝对超时、连续帧空间一致性确认（2 帧/70px）、
   强候选保守回退、可中断 sleep。改后 wait_for_* 一行未动，三个调用点
   （cj_logic:409、race_logic:121、race_logic_xbox:207）自动走 YOLO，
   连续帧确认顺带防 YOLO 闪检。
2. **_find_new_car_yolo 返回 (handled, pos) 三态**：检测器不可用/方案不支持/推理异常
   → handled=False 落回模板匹配；YOLO 接管后信任其结果（未找到不再双重跑模板）。
3. **兼容 meta**：YOLO 命中时写 last_strict_car_meta（四项分数=yolo_conf）+
   last_strict_car_click_points。cj_logic 的 _verify_target_point_b600 硬校验：
   conf>=0.72 直接过，低于时走原有等级标签灰度二次校验兜底。
4. **多候选按视觉顺序（左→右、上→下）取第一个**，与模板路径列优先策略一致。
5. **build.bat / build.yml 追加 --hidden-import yolo_detector**（懒加载 import，
   PyInstaller 静态扫描不到，漏了 exe 里会 import 失败）。
6. **find_skill_car_from_like_tag 已删除**（方法本体 + combo 降级调用，咩咩确认方案a）。
7. 默认配置字段加在 **main.py 的 load_config 底本字典**（非 config.py）。
8. 模型随 onnx_models 打包进 exe（+36.4MB，咩咩确认接受），exe 总计 152.4MB。

验证：单元测试 25 图（17 with_new / 4 no_new / 4 miss 均为过渡帧）；
集成冒烟测试通过；回归测试 5/6（唯一失败为 dev 历史遗留的过期测试）。
Steam 版已编译到 dist/dev/FH6Auto.exe，待真机实测。
