"""
YOLO 目标检测引擎（ONNX 推理）

替代模板匹配，用于超抽选车的目标车卡识别。
模型：YOLO26s 训练产物（mAP50=0.988），内置 NMS，7 个类别。

用法：
    from yolo_detector import YoloDetector
    det = YoloDetector()
    det.init()
    boxes = det.detect(screen_bgr)                      # 全部检测框
    result = det.find_target_car(screen_bgr, scheme=1)  # 高层：找目标车卡点击位置
"""

import os
import cv2
import numpy as np
import onnxruntime as ort

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

from config import APP_DIR, INTERNAL_DIR

# ============================================================
# 常量
# ============================================================

def _resolve_model_path():
    """模型解析（与 images 同模式）：优先外部 APP_DIR/onnx_models/（用户自训模型直接替换即生效），
    不存在时回退内置 INTERNAL_DIR/onnx_models/。首次启动会自动释放到外部目录（main.py 中 auto_extract_images("onnx_models")）。"""
    ext_path = os.path.join(APP_DIR, "onnx_models", "yolo_best.onnx")
    if os.path.isfile(ext_path):
        return ext_path
    int_path = os.path.join(INTERNAL_DIR, "onnx_models", "yolo_best.onnx")
    if os.path.isfile(int_path):
        return int_path
    return ext_path

MODEL_PATH = _resolve_model_path()
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

# 方案 -> 目标车卡类映射（config 的 current_scheme 是 0-based，调用前 +1）
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

TAG_CLASS_ID = 0  # new_tag（"全新"角标）

# 调试标注颜色 (BGR)
CLASS_COLORS = {
    0: (0, 215, 255),   # new_tag - 橙黄
    1: (255, 100, 100), # class_s2829 - 蓝
    2: (255, 0, 255),   # class_s1702 - 紫红
    3: (0, 255, 0),     # revuelto_with_new - 绿
    4: (0, 140, 0),     # revuelto_no_new - 暗绿
    5: (0, 255, 255),   # madmike_with_new - 黄
    6: (0, 140, 140),   # madmike_no_new - 暗黄
}


def box_containment(inner, outer):
    """inner 框落在 outer 框内的面积占比（0~1）。

    角标（inner）相对车卡（outer）很小，用「角标被车卡包含的比例」
    比 IoU 更能表达「角标在这张卡内」这一语义。
    """
    ix1 = max(inner[0], outer[0])
    iy1 = max(inner[1], outer[1])
    ix2 = min(inner[2], outer[2])
    iy2 = min(inner[3], outer[3])
    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    inner_area = max(1, (inner[2] - inner[0]) * (inner[3] - inner[1]))
    return (iw * ih) / inner_area


def sort_column_first(items, tolerance=50):
    """列优先排序：每列内上→下，列间左→右（与 vision._sort_column_first 同语义）。

    x 坐标差在 tolerance 内视为同一列。朴素的 (cx, cy) 排序在同一列
    两张卡中心 x 抖动 1~2px 时会错序（下行排到上行前面），跨帧还会来回
    跳导致连续帧确认永远不收敛，必须按容差分组。
    """
    if not items:
        return items
    ordered = sorted(items, key=lambda d: d["cx"])
    columns = []
    current = []
    col_x = None
    for d in ordered:
        if col_x is None or abs(d["cx"] - col_x) <= tolerance:
            current.append(d)
            if col_x is None:
                col_x = d["cx"]
        else:
            columns.append(current)
            current = [d]
            col_x = d["cx"]
    if current:
        columns.append(current)
    result = []
    for col in columns:
        col.sort(key=lambda d: d["cy"])
        result.extend(col)
    return result


def draw_detections(img_bgr, detections, chosen=None, rejected=None):
    """在截图上绘制全部检测框 + 置信度，返回标注图副本。

    - 各类别用 CLASS_COLORS 颜色
    - rejected（未通过 NEW 交叉验证的 with_new 候选）：红框 + 红叉
    - chosen：红色粗框 + 中心红点 + NEW 角标橙色高亮
    """
    out = img_bgr.copy()
    for d in detections:
        c = CLASS_COLORS.get(d["class_id"], (200, 200, 200))
        cv2.rectangle(out, (d["x1"], d["y1"]), (d["x2"], d["y2"]), c, 2)
        label = f'{d["name"]} {d["conf"]:.2f}'
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        ty = max(th + 4, d["y1"] - 2)
        cv2.rectangle(out, (d["x1"], ty - th - 4), (d["x1"] + tw + 4, ty), c, -1)
        cv2.putText(out, label, (d["x1"] + 2, ty - 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)
    for rej in (rejected or []):
        b = rej["box"]
        cv2.rectangle(out, (b[0], b[1]), (b[2], b[3]), (0, 0, 255), 2)
        cx, cy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
        cv2.line(out, (cx - 18, cy - 18), (cx + 18, cy + 18), (0, 0, 255), 4)
        cv2.line(out, (cx - 18, cy + 18), (cx + 18, cy - 18), (0, 0, 255), 4)
        cv2.putText(out, f"REJECT {rej['conf']:.2f}", (b[0] + 2, b[3] - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
    if chosen:
        b = chosen["box"]
        cv2.rectangle(out, (b[0], b[1]), (b[2], b[3]), (0, 0, 255), 4)
        cv2.circle(out, (chosen["x"], chosen["y"]), 10, (0, 0, 255), -1)
        if chosen.get("tag_box"):
            t = chosen["tag_box"]
            cv2.rectangle(out, (t[0], t[1]), (t[2], t[3]), (0, 215, 255), 3)
    return out


# ============================================================
# 预处理 / 后处理
# ============================================================

def letterbox(img, target_size=INPUT_SIZE):
    """等比缩放 + 灰边填充到 target_size x target_size（ultralytics 默认：114 灰边、居中）。

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
    """将 640 输入空间的 [x1,y1,x2,y2] 还原到原图坐标。"""
    boxes = boxes_640.copy().astype(np.float32)
    boxes[:, 0] = (boxes[:, 0] - pad_x) / scale
    boxes[:, 1] = (boxes[:, 1] - pad_y) / scale
    boxes[:, 2] = (boxes[:, 2] - pad_x) / scale
    boxes[:, 3] = (boxes[:, 3] - pad_y) / scale
    return boxes


def preprocess(img_bgr):
    """BGR 图像 -> ONNX 输入张量 [1,3,640,640] float32（RGB, 归一化 0-1）。

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
    """YOLO ONNX 推理引擎（仿 OCREngine 的懒加载模式）。"""

    def __init__(self, model_path=None, conf_threshold=0.25):
        self.model_path = model_path or MODEL_PATH
        self.conf_threshold = conf_threshold
        self.session = None
        self.input_name = None
        self._available = False
        self.last_error = None   # init() 失败原因（供调用方写 UI 日志）
        self.providers = []      # init() 成功后的实际推理后端

    def init(self):
        """加载 ONNX 模型。DirectML 优先，CPU 兜底。失败原因记入 self.last_error。"""
        self.last_error = None
        if not os.path.isfile(self.model_path):
            self.last_error = f"模型不存在: {self.model_path}"
            print(f"[YoloDetector] {self.last_error}")
            self._available = False
            return False

        try:
            providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
            self.session = ort.InferenceSession(
                self.model_path, providers=providers
            )
            self.input_name = self.session.get_inputs()[0].name
            self._available = True
            self.providers = self.session.get_providers()
            print(f"[YoloDetector] 已加载 {self.model_path}，后端: {self.providers}")
            return True
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            print(f"[YoloDetector] 加载失败: {self.last_error}")
            self._available = False
            return False

    @property
    def available(self):
        return self._available

    def detect(self, img_bgr, conf=None):
        """对一张图做检测。

        参数:
            img_bgr: numpy 数组, BGR, 任意分辨率
            conf: 置信度阈值（默认用 self.conf_threshold）

        返回: list of dict:
            {"class_id", "name", "conf", "x1", "y1", "x2", "y2", "cx", "cy"}
            坐标为原图空间整数。
        """
        if not self._available:
            return []

        conf = conf if conf is not None else self.conf_threshold

        tensor, scale, pad_x, pad_y = preprocess(img_bgr)
        outputs = self.session.run(None, {self.input_name: tensor})
        raw = outputs[0]  # [1, 300, 6] = [x1,y1,x2,y2,conf,class_id]，640 空间

        mask = raw[0, :, 4] > conf
        filtered = raw[0, mask]  # [N, 6]
        if len(filtered) == 0:
            return []

        boxes_640 = filtered[:, :4]
        confs = filtered[:, 4]
        class_ids = filtered[:, 5].astype(int)

        boxes_orig = unletterbox(boxes_640, scale, pad_x, pad_y)

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
                "x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2),
                "cx": int((x1 + x2) // 2),
                "cy": int((y1 + y2) // 2),
            })
        return results

    def find_target_car(self, img_bgr, scheme, conf=None,
                        min_tag_overlap=0.5, rescue_tag_conf=0.5,
                        tag_conf_floor=0.3):
        """高层接口：在选车画面找到「带全新角标」的目标车卡点击位置。

        核心规则（2026-07-28 修复：分类结果必须与 NEW 角标交叉验证）：
        - with_new 候选：同一卡片区域内必须存在 new_tag 检测框
          （角标被卡片包含 >= min_tag_overlap，tag conf >= tag_conf_floor），否则拒绝。
          分类器单独说了不算——防止 with_new 误分类点到非全新车。
        - no_new 候选：若有高置信 new_tag 覆盖（>= rescue_tag_conf），救回采用
          （分类器漏标但角标真实存在）。
        - 候选排序：列优先（每列上→下、列间左→右，x 容差 50px 分组），与模板
          路径 _sort_column_first 一致；不用朴素 (cx,cy) 排序——同列卡片中心 x
          抖动 1~2px 就会错序/跨帧跳变，破坏连续帧确认。

        阈值解耦（2026-07-28 v2）：车卡候选过阈用调用方传入的 conf（UI 滑条）；
        new_tag 交叉验证用独立的 tag_conf_floor（默认 0.3）——实测真角标
        conf 0.47~0.92、假角标 <=0.20，0.3 落在区分间隙中间。避免 UI 调高
        置信度后真角标（如 0.47）被过滤、导致真全新车被误拒。

        返回 dict（永不为 None）：
            {
              "chosen": None | {"x","y","conf","box","class_id","name","has_new",
                                "tag_box","tag_conf","rescued"},
              "detections": [...],   # 本帧全部检测框（调试标注用）
              "rejected": [ {"box","conf","name","reason"}, ... ],
              "diag": {"with_new","no_new","tags","best_containment"},
            }
        scheme 不支持时 chosen=None、detections=[]。
        """
        result = {"chosen": None, "detections": [], "rejected": [], "diag": {}}
        if scheme not in SCHEME_TARGETS:
            return result

        targets = SCHEME_TARGETS[scheme]
        base_conf = conf if conf is not None else self.conf_threshold
        # 推理阈值取两者最低：车卡按 base_conf 筛，角标按 tag_conf_floor 筛
        detections = self.detect(img_bgr, conf=min(base_conf, tag_conf_floor))
        result["detections"] = detections
        tags = [d for d in detections
                if d["class_id"] == TAG_CLASS_ID and d["conf"] >= tag_conf_floor]
        diag = {
            "with_new": sum(1 for d in detections
                            if d["class_id"] == targets["with_new"] and d["conf"] >= base_conf),
            "no_new": sum(1 for d in detections
                          if d["class_id"] == targets["no_new"] and d["conf"] >= base_conf),
            "tags": len(tags),
            "best_containment": 0.0,  # 车卡与 new_tag 最大重叠率（诊断：区分“角标不在卡上” vs “在卡上但置信低”）
        }

        def _best_tag(box, floor):
            """找与该卡片重叠最好、置信最高的 new_tag。"""
            best = None
            for t in tags:
                if t["conf"] < floor:
                    continue
                tbox = (t["x1"], t["y1"], t["x2"], t["y2"])
                if box_containment(tbox, box) >= min_tag_overlap:
                    if best is None or t["conf"] > best["conf"]:
                        best = t
            return best

        cands = [d for d in detections
                 if d["class_id"] in (targets["with_new"], targets["no_new"])
                 and d["conf"] >= base_conf]
        cands = sort_column_first(cands, tolerance=50)

        for d in cands:
            box = (d["x1"], d["y1"], d["x2"], d["y2"])
            # 诊断：统计车卡与 new_tag 的最大重叠率（不管置信度）
            for t in tags:
                cont = box_containment((t["x1"], t["y1"], t["x2"], t["y2"]), box)
                if cont > diag["best_containment"]:
                    diag["best_containment"] = cont
            is_with = d["class_id"] == targets["with_new"]
            floor = tag_conf_floor if is_with else rescue_tag_conf
            tag = _best_tag(box, floor)
            if tag is None:
                if is_with:
                    result["rejected"].append({
                        "box": box, "conf": d["conf"], "name": d["name"],
                        "reason": "with_new 分类过阈但同区域无 new_tag 交叉验证",
                    })
                continue
            result["chosen"] = {
                "x": d["cx"], "y": d["cy"], "conf": d["conf"], "box": box,
                "class_id": d["class_id"], "name": d["name"], "has_new": True,
                "tag_box": (tag["x1"], tag["y1"], tag["x2"], tag["y2"]),
                "tag_conf": tag["conf"],
                "rescued": not is_with,
            }
            break

        result["diag"] = diag
        return result
