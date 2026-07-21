# -*- coding: utf-8 -*-
"""
PP-OCRv6 tiny ONNX OCR 引擎（det + rec 完整流程）

针对 Forza Horizon 6 比赛结果画面优化：
- detection 模型自动找到画面中的文字区域
- recognition 模型识别文字内容
- onnxruntime 纯推理，无需 paddlepaddle
- Python 3.14 兼容，可直接打包进 PyInstaller

用法：
    from ocr_onnx import OCREngine
    engine = OCREngine()
    engine.init()
    result = engine.detect(screen_image)  # BGR numpy array
    # result = {"status": "win|fail|unknown", "text": "挑战完成！"}
"""
import os
import time
import threading
import cv2
import numpy as np
import onnxruntime as ort

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# OCR 模型变体："small" 识别率更高（v1.2.10.5 起默认） / "tiny" 更快；
# small 模型缺失时自动回退 tiny。OCREngine(variant=...) 可单独覆盖（双引擎场景）。
OCR_MODEL_VARIANT = "small"


def _pick_model_dir(kind, variant=None):
    """选择 det/rec 模型目录。优先级：构造器指定 variant -> OCR_MODEL_VARIANT -> tiny。
    返回 (目录, 实际变体名)。"""
    base = os.path.join(BASE_DIR, "onnx_models")
    candidates = []
    if variant and variant not in candidates:
        candidates.append(variant)
    if OCR_MODEL_VARIANT not in candidates:
        candidates.append(OCR_MODEL_VARIANT)
    if "tiny" not in candidates:
        candidates.append("tiny")
    for v in candidates:
        d = os.path.join(base, f"PP-OCRv6_{v}_{kind}_onnx")
        if os.path.isfile(os.path.join(d, "inference.onnx")):
            return d, v
    return os.path.join(base, f"PP-OCRv6_{candidates[-1]}_{kind}_onnx"), candidates[-1]

# 比赛结果文字在屏幕中的位置（比例）
# "挑战完成！" / "挑战失败" 出现在左上角偏下
# 当 detection 模型不可用时，回退到固定区域裁剪
TEXT_REGION = {
    "y_start": 0.14,
    "y_end": 0.30,
    "x_start": 0.02,
    "x_end": 0.26,
}

REC_IMG_H = 48
REC_MAX_W = 240  # v1.2.10.1: 320 -> 240（菜单文字行最长约 13 个汉字，240px 宽足够，rec 耗时 -20~25%）

# detection 预处理参数（来自 inference.yml）
DET_MEAN = [0.485, 0.456, 0.406]
DET_STD = [0.229, 0.224, 0.225]
DET_MAX_SIDE = 960  # det 输入默认长边上限（只缩不放）；调用方可传 max_side 覆盖（如筛选面板传 416）
# detection 后处理参数（来自 inference.yml）
DET_THRESH = 0.2
DET_BOX_THRESH = 0.4
DET_UNCLIP_RATIO = 1.4
DET_MAX_CANDIDATES = 3000


class OCREngine:
    """PP-OCRv6 tiny det + rec ONNX 推理引擎"""

    def __init__(self, log_func=None, use_directml=False, variant=None):
        self.log = log_func or (lambda msg: None)
        self.rec_session = None
        self.det_session = None
        self.chars = None
        self.use_directml = use_directml
        self.variant = variant  # None = 用模块默认 OCR_MODEL_VARIANT
        self.rec_img_h = REC_IMG_H
        # det 预处理缓冲缓存：按 (h, w) 复用 resize 输出 + 归一化 CHW 缓冲，
        # 省掉每次调用的内存分配 + transpose 拷贝（同尺寸输入高频调用时累积可观）
        self._det_bufs = {}
        self._det_buf_lock = threading.Lock()
        self._det_mean = np.array(DET_MEAN, dtype=np.float32)
        self._det_std = np.array(DET_STD, dtype=np.float32)

    def _create_session(self, model_path):
        """创建 ONNX session，带 CPU 限流和 DirectML 选项"""
        import os as _os
        _half_cpus = max(1, (_os.cpu_count() or 4) // 2)
        so = ort.SessionOptions()
        so.intra_op_num_threads = _half_cpus
        so.inter_op_num_threads = _half_cpus

        if self.use_directml:
            try:
                sess = ort.InferenceSession(
                    model_path,
                    sess_options=so,
                    providers=["DmlExecutionProvider", "CPUExecutionProvider"]
                )
                return sess
            except Exception as e:
                self.log(f"[OCR] DirectML 不可用 ({e})，回退 CPU")

        return ort.InferenceSession(
            model_path,
            sess_options=so,
            providers=["CPUExecutionProvider"]
        )

    def init(self):
        """加载 detection + recognition ONNX 模型和字符字典"""
        t0 = time.time()

        rec_dir, rec_v = _pick_model_dir("rec", self.variant)
        det_dir, det_v = _pick_model_dir("det", self.variant)

        # 加载 recognition 模型
        self.rec_session = self._create_session(os.path.join(rec_dir, "inference.onnx"))

        # 加载 detection 模型
        self.det_session = self._create_session(os.path.join(det_dir, "inference.onnx"))

        gpu_tag = "DirectML" if self.use_directml else "CPU"

        # 加载字符字典（不同变体字典可能不同，必须随模型配套读取）
        import yaml
        with open(os.path.join(rec_dir, "inference.yml"), "r", encoding="utf-8") as f:
            yml = yaml.safe_load(f)
        self.chars = yml["PostProcess"]["character_dict"]
        # rec 输入高度从 yml 读取（不同变体可能不同），缺失用默认 48
        shape = (yml.get("Global") or {}).get("rec_image_shape")
        if isinstance(shape, (list, tuple)) and len(shape) >= 2:
            self.rec_img_h = int(shape[-2])

        elapsed = time.time() - t0
        self.log(f"[OCR] det({det_v}) + rec({rec_v}) 模型加载完成（{gpu_tag}），{len(self.chars)} 字符，耗时 {elapsed:.2f}s")

    # ==========================================
    # Detection 预处理 + 后处理（DB 算法）
    # ==========================================

    def _det_preprocess(self, img, max_side=None):
        """detection 模型预处理：resize + normalize + toCHW（缓冲复用，零分配）"""
        h, w = img.shape[:2]
        # 限制最大尺寸，保持比例（只缩不放）
        ms = max_side if max_side else DET_MAX_SIDE
        ratio = min(ms / h, ms / w, 1.0)
        new_h, new_w = int(h * ratio), int(w * ratio)
        # 确保尺寸为 32 的倍数
        new_h = max(32, (new_h // 32) * 32)
        new_w = max(32, (new_w // 32) * 32)

        with self._det_buf_lock:
            key = (new_h, new_w)
            bufs = self._det_bufs.get(key)
            if bufs is None:
                bufs = (
                    np.empty((new_h, new_w, 3), dtype=np.uint8),       # resize 输出缓冲
                    np.empty((1, 3, new_h, new_w), dtype=np.float32),  # 归一化 CHW 输入缓冲
                )
                self._det_bufs[key] = bufs
            resized, chw = bufs
            cv2.resize(img, (new_w, new_h), dst=resized)
            # 逐通道写入 CHW 缓冲：/255 -> -mean -> /std，全程 in-place 无分配
            chw3 = chw[0]
            for c in range(3):
                np.divide(resized[:, :, c], 255.0, out=chw3[c], dtype=np.float32)
                chw3[c] -= self._det_mean[c]
                chw3[c] /= self._det_std[c]
            return chw, (h, w, new_h, new_w)

    def _det_postprocess(self, pred, orig_h, orig_w, resized_h, resized_w):
        """DB 后处理：从 score map 提取文字框"""
        # pred shape: (1, 1, H, W) -> (H, W)
        if pred.ndim == 4:
            score = pred[0, 0]
        elif pred.ndim == 3:
            score = pred[0]
        else:
            score = pred

        # 二值化
        binary = (score > DET_THRESH).astype(np.uint8)
        # 找轮廓
        contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

        if len(contours) == 0:
            return []

        # 缩放因子
        sx = orig_w / resized_w
        sy = orig_h / resized_h

        boxes = []
        for contour in contours[:DET_MAX_CANDIDATES]:
            # 跳过太小的轮廓
            if cv2.contourArea(contour) < 10:
                continue

            # 最小外接矩形
            rect = cv2.minAreaRect(contour)
            box = cv2.boxPoints(rect)

            # 检查 score
            cx = int(np.mean(box[:, 0]))
            cy = int(np.mean(box[:, 1]))
            cx = min(max(cx, 0), score.shape[1] - 1)
            cy = min(max(cy, 0), score.shape[0] - 1)
            if score[cy, cx] < DET_BOX_THRESH:
                continue

            # unclip：扩大框
            box = self._unclip(box, DET_UNCLIP_RATIO)

            # 缩放回原图坐标
            box[:, 0] *= sx
            box[:, 1] *= sy

            # 裁剪为整数
            box = np.clip(box, [0, 0], [orig_w - 1, orig_h - 1])
            x_min = int(np.min(box[:, 0]))
            y_min = int(np.min(box[:, 1]))
            x_max = int(np.max(box[:, 0]))
            y_max = int(np.max(box[:, 1]))

            # 跳过太小的框
            if x_max - x_min < 5 or y_max - y_min < 5:
                continue

            boxes.append((x_min, y_min, x_max, y_max))

        # 按 y 坐标排序（从上到下）
        boxes.sort(key=lambda b: b[1])
        return boxes

    def _unclip(self, box, ratio=1.4):
        """简单 unclip：向外扩展多边形"""
        cx = np.mean(box[:, 0])
        cy = np.mean(box[:, 1])
        expanded = np.zeros_like(box, dtype=np.float32)
        for i in range(4):
            dx = box[i, 0] - cx
            dy = box[i, 1] - cy
            expanded[i, 0] = box[i, 0] + dx * (ratio - 1)
            expanded[i, 1] = box[i, 1] + dy * (ratio - 1)
        return expanded

    # ==========================================
    # Recognition 预处理 + 后处理（CTC 解码）
    # ==========================================

    def _rec_preprocess(self, crop):
        """rec 模型预处理：resize 到模型输入高（默认 48px），归一化"""
        h, w = crop.shape[:2]
        ratio = self.rec_img_h / h
        target_w = min(int(w * ratio), REC_MAX_W)
        target_w = max(4, (target_w // 4) * 4)

        resized = cv2.resize(crop, (target_w, self.rec_img_h))
        inp = resized.astype(np.float32) / 255.0
        inp = (inp - 0.5) / 0.5
        return np.ascontiguousarray(inp.transpose(2, 0, 1)[np.newaxis, ...], dtype=np.float32)

    def _decode_ctc(self, pred):
        """CTC 解码"""
        if pred.ndim == 3:
            pred = pred[0]
        text = []
        last_idx = -1
        for i in range(pred.shape[0]):
            idx = int(np.argmax(pred[i]))
            if idx != last_idx and idx != 0:  # 0 = CTC blank
                if idx - 1 < len(self.chars):
                    text.append(self.chars[idx - 1])
            last_idx = idx
        return "".join(text)

    # ==========================================
    # 完整 det + rec 流程
    # ==========================================

    def detect(self, image, max_side=None):
        """
        完整 OCR 检测：detection 找文字区域 -> recognition 识别文字

        Args:
            image: BGR numpy array（完整游戏截图）
            max_side: det 输入长边上限（None 用默认 960，只缩不放）

        Returns:
            dict: {"status": "win|fail|unknown", "text": "...", "boxes": [...]}
        """
        if self.rec_session is None or self.det_session is None:
            self.init()

        if image is None:
            return {"status": "error", "error": "图片为空"}

        h, w = image.shape[:2]

        # ====== 1. Detection：找文字区域（失败回退固定区域） ======
        boxes = None
        try:
            det_inp, (orig_h, orig_w, new_h, new_w) = self._det_preprocess(image, max_side)
            det_out = self.det_session.run(None, {"x": det_inp})
            boxes = self._det_postprocess(det_out[0], orig_h, orig_w, new_h, new_w)
        except Exception as e:
            self.log(f"[OCR] detection 异常，回退固定区域: {e}")

        if not boxes:
            # detection 没找到文字或异常，回退到固定区域
            y1 = int(h * TEXT_REGION["y_start"])
            y2 = int(h * TEXT_REGION["y_end"])
            x1 = int(w * TEXT_REGION["x_start"])
            x2 = int(w * TEXT_REGION["x_end"])
            boxes = [(x1, y1, x2, y2)]

        # ====== 2. Recognition：逐个识别 ======
        all_texts = []
        for (x1, y1, x2, y2) in boxes:
            # 边界校验
            x1, y1 = max(0, int(x1)), max(0, int(y1))
            x2, y2 = min(w, int(x2)), min(h, int(y2))
            if x2 <= x1 or y2 <= y1:
                continue
            crop = image[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            inp = self._rec_preprocess(crop)
            try:
                out = self.rec_session.run(None, {"x": inp})
                text = self._decode_ctc(out[0])
                if text.strip():
                    all_texts.append(text.strip())
            except Exception as e:
                self.log(f"[OCR] rec 推理异常 (crop={crop.shape}): {e}")
                continue

        combined = " ".join(all_texts)

        # 判定 win/fail
        status = "unknown"
        if "挑战完成" in combined or "完成" in combined:
            status = "win"
        elif "挑战失败" in combined or "失败" in combined:
            status = "fail"
        elif "完成" in combined:
            status = "win"
        elif "失败" in combined:
            status = "fail"

        if status != "unknown":
            self.log(f"[OCR] 识别到 {len(boxes)} 个区域，文字: {combined}")

        return {"status": status, "text": combined, "boxes": boxes}

    def detect_text_in_region(self, image, region_ratio=None, max_side=None):
        """
        对指定区域跑 OCR，返回识别到的文字（不做 win/fail 判定）

        Args:
            image: BGR numpy array（完整截图）
            region_ratio: dict with y_start, y_end, x_start, x_end (0~1 比例)
                         None 表示全图
            max_side: det 输入长边上限（None 用默认 960，只缩不放）

        Returns:
            str: 识别到的文字（空格分隔各区域）
        """
        if self.rec_session is None or self.det_session is None:
            self.init()
        if image is None:
            return ""

        h, w = image.shape[:2]
        if region_ratio:
            y1 = int(h * region_ratio.get("y_start", 0))
            y2 = int(h * region_ratio.get("y_end", 1))
            x1 = int(w * region_ratio.get("x_start", 0))
            x2 = int(w * region_ratio.get("x_end", 1))
            image = image[y1:y2, x1:x2]
            if image.size == 0:
                return ""
            h, w = image.shape[:2]

        # detection（失败则对整个裁剪区域跑 rec）
        boxes = None
        try:
            det_inp, (orig_h, orig_w, new_h, new_w) = self._det_preprocess(image, max_side)
            det_out = self.det_session.run(None, {"x": det_inp})
            boxes = self._det_postprocess(det_out[0], orig_h, orig_w, new_h, new_w)
        except Exception as e:
            self.log(f"[OCR] detection 异常: {e}")

        if not boxes:
            # detection 失败，直接对整个裁剪区域跑 rec
            boxes = [(0, 0, w, h)]

        all_texts = []
        for (bx1, by1, bx2, by2) in boxes:
            bx1, by1 = max(0, int(bx1)), max(0, int(by1))
            bx2, by2 = min(w, int(bx2)), min(h, int(by2))
            if bx2 <= bx1 or by2 <= by1:
                continue
            crop = image[by1:by2, bx1:bx2]
            if crop.size == 0:
                continue
            inp = self._rec_preprocess(crop)
            try:
                out = self.rec_session.run(None, {"x": inp})
                text = self._decode_ctc(out[0])
                if text.strip():
                    all_texts.append(text.strip())
            except Exception as e:
                self.log(f"[OCR] rec 推理异常 (crop={crop.shape}): {e}")
                continue

        return " ".join(all_texts)

    def detect_lines_in_region(self, image, region_ratio=None, max_side=None):
        """
        对指定区域跑 OCR，返回逐行结果（文字 + 坐标）

        与 detect_text_in_region 的区别：保留每行的文字框坐标，
        供筛选导航等需要"按行定位"的场景使用（v1.2.10.0+）。

        Args:
            image: BGR numpy array（完整截图）
            region_ratio: dict with y_start, y_end, x_start, x_end (0~1 比例)
                         None 表示全图
            max_side: det 输入长边上限（None 用默认 960，只缩不放）

        Returns:
            list[dict]: 按 y 从上到下排序，每项 {"text": str, "box": (x1, y1, x2, y2)}
                        坐标相对于 region 裁剪后的图像
        """
        if self.rec_session is None or self.det_session is None:
            self.init()
        if image is None:
            return []

        h, w = image.shape[:2]
        if region_ratio:
            y1 = int(h * region_ratio.get("y_start", 0))
            y2 = int(h * region_ratio.get("y_end", 1))
            x1 = int(w * region_ratio.get("x_start", 0))
            x2 = int(w * region_ratio.get("x_end", 1))
            image = image[y1:y2, x1:x2]
            if image.size == 0:
                return []
            h, w = image.shape[:2]

        # detection
        boxes = None
        try:
            det_inp, (orig_h, orig_w, new_h, new_w) = self._det_preprocess(image, max_side)
            det_out = self.det_session.run(None, {"x": det_inp})
            boxes = self._det_postprocess(det_out[0], orig_h, orig_w, new_h, new_w)
        except Exception as e:
            self.log(f"[OCR] detection 异常: {e}")

        if not boxes:
            return []

        # 逐框识别
        items = []  # (text, (x1, y1, x2, y2))
        for (bx1, by1, bx2, by2) in boxes:
            bx1, by1 = max(0, int(bx1)), max(0, int(by1))
            bx2, by2 = min(w, int(bx2)), min(h, int(by2))
            if bx2 <= bx1 or by2 <= by1:
                continue
            crop = image[by1:by2, bx1:bx2]
            if crop.size == 0:
                continue
            inp = self._rec_preprocess(crop)
            try:
                out = self.rec_session.run(None, {"x": inp})
                text = self._decode_ctc(out[0])
                if text.strip():
                    items.append((text.strip(), (bx1, by1, bx2, by2)))
            except Exception as e:
                self.log(f"[OCR] rec 推理异常 (crop={crop.shape}): {e}")
                continue

        # 同行合并：垂直重叠超过 50% 的框视为同一行（如 "GT 赛车" 被拆成两个框）
        items.sort(key=lambda it: (it[1][1] + it[1][3]) / 2)
        lines = []
        for text, box in items:
            merged = False
            for line in lines:
                lx1, ly1, lx2, ly2 = line["box"]
                oy1 = max(ly1, box[1])
                oy2 = min(ly2, box[3])
                min_h = min(ly2 - ly1, box[3] - box[1])
                if min_h > 0 and (oy2 - oy1) / min_h > 0.5:
                    if box[0] < lx1:
                        line["text"] = text + line["text"]
                    else:
                        line["text"] = line["text"] + text
                    line["box"] = (
                        min(lx1, box[0]), min(ly1, box[1]),
                        max(lx2, box[2]), max(ly2, box[3]),
                    )
                    merged = True
                    break
            if not merged:
                lines.append({"text": text, "box": box})

        lines.sort(key=lambda l: l["box"][1])
        return lines

    def detect_from_path(self, image_path):
        """从文件路径加载图片并检测"""
        img = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return {"status": "error", "error": f"无法读取图片: {image_path}"}
        return self.detect(img)


# 测试入口
if __name__ == "__main__":
    engine = OCREngine(log_func=print)
    engine.init()

    debug_dir = os.path.join(BASE_DIR, "debug")
    for name in ["PixPin_2026-07-16_16-32-09.png", "PixPin_2026-07-16_16-38-41.png"]:
        path = os.path.join(debug_dir, name)
        if not os.path.exists(path):
            continue
        print(f"\n=== {name} ===")
        result = engine.detect_from_path(path)
        print(f"  状态: {result['status']}")
        print(f"  文字: {repr(result.get('text', ''))}")
        print(f"  框数: {len(result.get('boxes', []))}")
