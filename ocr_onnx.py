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
import cv2
import numpy as np
import onnxruntime as ort

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REC_MODEL = os.path.join(BASE_DIR, "onnx_models", "PP-OCRv6_tiny_rec_onnx", "inference.onnx")
REC_YML = os.path.join(BASE_DIR, "onnx_models", "PP-OCRv6_tiny_rec_onnx", "inference.yml")
DET_MODEL = os.path.join(BASE_DIR, "onnx_models", "PP-OCRv6_tiny_det_onnx", "inference.onnx")
DET_YML = os.path.join(BASE_DIR, "onnx_models", "PP-OCRv6_tiny_det_onnx", "inference.yml")

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
REC_MAX_W = 320

# detection 预处理参数（来自 inference.yml）
DET_MEAN = [0.485, 0.456, 0.406]
DET_STD = [0.229, 0.224, 0.225]
# detection 后处理参数（来自 inference.yml）
DET_THRESH = 0.2
DET_BOX_THRESH = 0.4
DET_UNCLIP_RATIO = 1.4
DET_MAX_CANDIDATES = 3000


class OCREngine:
    """PP-OCRv6 tiny det + rec ONNX 推理引擎"""

    def __init__(self, log_func=None, use_directml=False):
        self.log = log_func or (lambda msg: None)
        self.rec_session = None
        self.det_session = None
        self.chars = None
        self.use_directml = use_directml

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

        # 加载 recognition 模型
        self.rec_session = self._create_session(REC_MODEL)

        # 加载 detection 模型
        self.det_session = self._create_session(DET_MODEL)

        gpu_tag = "DirectML" if self.use_directml else "CPU"
        self.log(f"[OCR] det + rec 模型加载完成（{gpu_tag}）")

        # 加载字符字典
        import yaml
        with open(REC_YML, "r", encoding="utf-8") as f:
            yml = yaml.safe_load(f)
        self.chars = yml["PostProcess"]["character_dict"]

        elapsed = time.time() - t0
        self.log(f"[OCR] 初始化完成，{len(self.chars)} 字符，耗时 {elapsed:.2f}s")

    # ==========================================
    # Detection 预处理 + 后处理（DB 算法）
    # ==========================================

    def _det_preprocess(self, img):
        """detection 模型预处理：resize + normalize + toCHW"""
        h, w = img.shape[:2]
        # 限制最大尺寸，保持比例
        max_side = 960
        ratio = min(max_side / h, max_side / w, 1.0)
        new_h, new_w = int(h * ratio), int(w * ratio)
        # 确保尺寸为 32 的倍数
        new_h = max(32, (new_h // 32) * 32)
        new_w = max(32, (new_w // 32) * 32)
        resized = cv2.resize(img, (new_w, new_h))

        # normalize
        inp = resized.astype(np.float32) / 255.0
        inp = (inp - np.array(DET_MEAN)) / np.array(DET_STD)
        # to CHW
        inp = inp.transpose(2, 0, 1)
        inp = np.ascontiguousarray(inp[np.newaxis, ...], dtype=np.float32)
        return inp, (h, w, new_h, new_w)

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
        """rec 模型预处理：resize 到 48px 高，归一化"""
        h, w = crop.shape[:2]
        ratio = REC_IMG_H / h
        target_w = min(int(w * ratio), REC_MAX_W)
        target_w = max(4, (target_w // 4) * 4)

        resized = cv2.resize(crop, (target_w, REC_IMG_H))
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

    def detect(self, image):
        """
        完整 OCR 检测：detection 找文字区域 -> recognition 识别文字

        Args:
            image: BGR numpy array（完整游戏截图）

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
            det_inp, (orig_h, orig_w, new_h, new_w) = self._det_preprocess(image)
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

    def detect_text_in_region(self, image, region_ratio=None):
        """
        对指定区域跑 OCR，返回识别到的文字（不做 win/fail 判定）

        Args:
            image: BGR numpy array（完整截图）
            region_ratio: dict with y_start, y_end, x_start, x_end (0~1 比例)
                         None 表示全图

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
            det_inp, (orig_h, orig_w, new_h, new_w) = self._det_preprocess(image)
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
