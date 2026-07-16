# -*- coding: utf-8 -*-
"""
PP-OCRv6 tiny ONNX OCR 引擎（仅 rec，无 det）

针对 Forza Horizon 6 比赛结果画面优化：
- 直接裁剪 "挑战完成/失败" 文字区域
- 只跑 rec 模型，跳过 det，更快更准
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

# 比赛结果文字在屏幕中的位置（比例）
# "挑战完成！" / "挑战失败" 出现在左上角偏下
TEXT_REGION = {
    "y_start": 0.14,
    "y_end": 0.30,
    "x_start": 0.02,
    "x_end": 0.26,
}

REC_IMG_H = 48
REC_MAX_W = 320


class OCREngine:
    """PP-OCRv6 tiny rec-only ONNX 推理引擎"""

    def __init__(self, log_func=None, use_directml=False):
        self.log = log_func or (lambda msg: None)
        self.session = None
        self.chars = None
        self.use_directml = use_directml

    def init(self):
        """加载 ONNX 模型和字符字典"""
        import time as _time
        t0 = _time.time()

        # 限制 CPU 线程数，避免抢占游戏资源
        import os as _os
        _half_cpus = max(1, (_os.cpu_count() or 4) // 2)
        so = ort.SessionOptions()
        so.intra_op_num_threads = _half_cpus
        so.inter_op_num_threads = _half_cpus

        if self.use_directml:
            try:
                self.session = ort.InferenceSession(
                    REC_MODEL,
                    sess_options=so,
                    providers=["DmlExecutionProvider", "CPUExecutionProvider"]
                )
                self.log("[OCR] 使用 DirectML 加速")
            except Exception as e:
                self.log(f"[OCR] DirectML 不可用 ({e})，回退 CPU")
                self.session = ort.InferenceSession(
                    REC_MODEL,
                    sess_options=so,
                    providers=["CPUExecutionProvider"]
                )
        else:
            self.session = ort.InferenceSession(
                REC_MODEL,
                sess_options=so,
                providers=["CPUExecutionProvider"]
            )
            self.log("[OCR] 使用 CPU（单线程）")

        # 加载字符字典
        import yaml
        with open(REC_YML, "r", encoding="utf-8") as f:
            yml = yaml.safe_load(f)
        self.chars = yml["PostProcess"]["character_dict"]

        elapsed = _time.time() - t0
        self.log(f"[OCR] 初始化完成，{len(self.chars)} 字符，耗时 {elapsed:.2f}s")

    def _preprocess(self, crop):
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

    def detect(self, image):
        """
        检测比赛结果

        Args:
            image: BGR numpy array（完整游戏截图）

        Returns:
            dict: {"status": "win|fail|unknown", "text": "..."}
        """
        if self.session is None:
            self.init()

        if image is None:
            return {"status": "error", "error": "图片为空"}

        h, w = image.shape[:2]
        # 裁剪目标文字区域
        y1 = int(h * TEXT_REGION["y_start"])
        y2 = int(h * TEXT_REGION["y_end"])
        x1 = int(w * TEXT_REGION["x_start"])
        x2 = int(w * TEXT_REGION["x_end"])
        crop = image[y1:y2, x1:x2]

        if crop.size == 0:
            return {"status": "error", "error": "裁剪区域为空"}

        # rec 推理
        inp = self._preprocess(crop)
        out = self.session.run(None, {"x": inp})
        text = self._decode_ctc(out[0])

        # 判定 win/fail
        status = "unknown"
        if "挑战完成" in text or "完成" in text:
            status = "win"
        elif "挑战失败" in text or "失败" in text:
            status = "fail"
        elif "完成" in text:
            status = "win"
        elif "失败" in text:
            status = "fail"

        return {"status": status, "text": text}

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
