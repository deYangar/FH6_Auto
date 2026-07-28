"""模板匹配引擎 — 多尺度 + NMS + classes.json 类名映射"""

import os
import json
import cv2
import numpy as np

# 每个阶段需要检测的模板
STAGE_TEMPLATES = {
    "wheelspin": ["newCC.png", "newcartag.png", "class.png"],   # class.png 动态替换
    "delete":    ["removecarobject.png"],
    "buy":       ["consumablecar.png"],
}

# 10 种高对比度颜色 (BGR)，按 class_id 分配
_DEFAULT_COLORS = [
    (0, 200, 0),      # 绿
    (0, 255, 255),     # 黄
    (255, 200, 0),     # 青
    (0, 128, 255),     # 橙
    (255, 0, 255),     # 品红
    (0, 255, 0),       # 亮绿
    (255, 255, 0),     # 天蓝
    (0, 0, 255),       # 红
    (255, 128, 0),     # 浅蓝
    (128, 0, 255),     # 紫
]


class TemplateMatcher:
    def __init__(self, images_root, classes_json=None):
        self.images_root = images_root
        self._tpl_cache = {}    # path → BGR image
        self._gray_cache = {}   # path → gray image

        # classes.json 映射
        self._classes = {}          # class_id → class_info dict
        self._tpl_to_class = {}     # template_filename → (class_id, class_name)
        self._class_colors = {}     # class_name → (B,G,R)

        # 自动查找 classes.json
        if classes_json is None:
            candidates = [
                os.path.join(os.path.dirname(images_root), "config", "classes.json"),
                os.path.join(os.path.dirname(images_root), "yolo_tool", "config", "classes.json"),
                os.path.join(os.path.dirname(os.path.dirname(images_root)), "config", "classes.json"),
            ]
            for c in candidates:
                if os.path.isfile(c):
                    classes_json = c
                    break
        self._load_classes(classes_json)

    def _load_classes(self, path):
        """加载 classes.json，建立 template → class 映射"""
        if not path or not os.path.isfile(path):
            print(f"[matcher] classes.json 未找到，使用旧模式 (car/class_tag)")
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            classes = data.get("classes", {})
            for cid_str, info in classes.items():
                cid = int(cid_str)
                name = info.get("name", f"class_{cid}")
                self._classes[cid] = info
                # template 文件名 → (class_id, class_name)
                tpl = info.get("template")
                if tpl:
                    self._tpl_to_class[tpl] = (cid, name)
                # 方案级映射：scheme_N/template.png → (class_id, class_name)
                scheme = info.get("scheme")
                if scheme and tpl:
                    scheme_key = f"scheme_{scheme}/{tpl}"
                    self._tpl_to_class[scheme_key] = (cid, name)
                # 按 class_id 分配颜色
                self._class_colors[name] = _DEFAULT_COLORS[cid % len(_DEFAULT_COLORS)]
            print(f"[matcher] 已加载 {len(self._classes)} 个类: {list(self._class_colors.keys())}")
        except Exception as e:
            print(f"[matcher] 加载 classes.json 失败: {e}")

    def get_class_info(self, tpl_name, scheme_name=None):
        """根据模板文件名返回 (class_id, class_name)。找不到返回 (None, None)
        
        Args:
            tpl_name: 模板文件名，如 "removecarobject.png"
            scheme_name: 方案名，如 "scheme_1"。传入时优先查方案级映射。
        """
        # 1. 方案级精确匹配（scheme_1/removecarobject.png）
        if scheme_name:
            scheme_key = f"{scheme_name}/{tpl_name}"
            if scheme_key in self._tpl_to_class:
                return self._tpl_to_class[scheme_key]
        # 2. 全局精确匹配
        if tpl_name in self._tpl_to_class:
            return self._tpl_to_class[tpl_name]
        # 3. 去后缀尝试（newCC_Mazda.png → newCC.png）
        if "_" in tpl_name:
            base = tpl_name.split("_")[0] + ".png"
            if scheme_name:
                scheme_key = f"{scheme_name}/{base}"
                if scheme_key in self._tpl_to_class:
                    return self._tpl_to_class[scheme_key]
            if base in self._tpl_to_class:
                return self._tpl_to_class[base]
        return None, None

    def get_color(self, class_name):
        """获取类别的显示颜色 (BGR)"""
        return self._class_colors.get(class_name, (200, 200, 200))

    @property
    def class_colors(self):
        """返回 {class_name: (B,G,R)} 字典，供 GUI 使用"""
        return dict(self._class_colors)

    def load_bgr(self, path):
        if path in self._tpl_cache:
            return self._tpl_cache[path]
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is not None:
            self._tpl_cache[path] = img
        return img

    def load_gray(self, path):
        if path in self._gray_cache:
            return self._gray_cache[path]
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is not None:
            self._gray_cache[path] = img
        return img

    def get_scheme_dir(self, scheme_name):
        """获取方案模板目录，如 images/scheme_1/"""
        return os.path.join(self.images_root, scheme_name)

    def detect(self, screen_bgr, scheme_name, stage, threshold=0.65, fast=True):
        """
        对截图运行当前方案+阶段的所有模板匹配。
        返回 [(class_name, x1, y1, x2, y2, score, tpl_name), ...]
        class_name 来自 classes.json（如 "revuelto_with_new"），
        找不到映射时回退到 "unknown_{tpl_name}"
        """
        scheme_dir = self.get_scheme_dir(scheme_name)
        if not os.path.isdir(scheme_dir):
            return []

        tpl_names = self._get_template_names(scheme_dir, stage)
        all_dets = []

        for tpl_name in tpl_names:
            tpl_path = os.path.join(scheme_dir, tpl_name)
            tpl_bgr = self.load_bgr(tpl_path)
            if tpl_bgr is None:
                continue

            # 从 classes.json 获取真实类名（带方案上下文）
            class_id, class_name = self.get_class_info(tpl_name, scheme_name)
            if class_name is None:
                class_name = f"unknown_{os.path.splitext(tpl_name)[0]}"

            dets = self._match_one(screen_bgr, tpl_bgr, tpl_name,
                                   class_name, threshold, fast)
            all_dets.extend(dets)

        # NMS 按类别去重
        return self._nms(all_dets, iou_thresh=0.3)

    def _get_template_names(self, scheme_dir, stage):
        """获取当前阶段需要的模板文件名列表"""
        if stage == "wheelspin":
            # 找 classXXX.png
            class_tpl = None
            for f in os.listdir(scheme_dir):
                if f.startswith("class") and f.endswith(".png"):
                    class_tpl = f
                    break
            names = ["newCC.png", "newcartag.png"]
            if class_tpl:
                names.append(class_tpl)
            return names
        elif stage == "delete":
            return ["removecarobject.png"]
        elif stage == "buy":
            return ["consumablecar.png"]
        return []

    def _match_one(self, screen, tpl, tpl_name, class_name, threshold, fast):
        """单个模板的多尺度匹配"""
        h_scr, w_scr = screen.shape[:2]
        h_tpl, w_tpl = tpl.shape[:2]
        if h_tpl > h_scr or w_tpl > w_scr or h_tpl < 5 or w_tpl < 5:
            return []

        # 计算缩放范围
        if fast:
            base_scale = w_scr / 1600.0
            scales = [base_scale * f for f in [0.92, 0.96, 1.0, 1.04, 1.08]]
            scales = [round(s, 3) for s in scales if 0.4 <= s <= 1.8]
        else:
            base_scale = w_scr / 1600.0
            factors = [0.80, 0.85, 0.90, 0.93, 0.96, 0.98, 1.0, 1.02, 1.04, 1.07, 1.10, 1.15, 1.20]
            scales = [round(base_scale * f, 3) for f in factors if 0.4 <= base_scale * f <= 1.8]

        best_score = 0
        best_loc = None
        best_scale = 1.0

        for scale in scales:
            sw = int(w_tpl * scale)
            sh = int(h_tpl * scale)
            if sw < 5 or sh < 5 or sw > w_scr or sh > h_scr:
                continue
            scaled = cv2.resize(tpl, (sw, sh), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(screen, scaled, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val > best_score:
                best_score = max_val
                best_loc = max_loc
                best_scale = scale

        if best_score < threshold or best_loc is None:
            return []

        sw = int(w_tpl * best_scale)
        sh = int(h_tpl * best_scale)
        x1, y1 = best_loc
        return [(class_name, x1, y1, x1 + sw, y1 + sh, best_score, tpl_name)]

    def detect_multi(self, screen_bgr, scheme_name, stage, threshold=0.65, fast=True):
        """检测同一模板的多个实例（用于删车场景找多辆车）"""
        scheme_dir = self.get_scheme_dir(scheme_name)
        if not os.path.isdir(scheme_dir):
            return []

        tpl_names = self._get_template_names(scheme_dir, stage)
        all_dets = []

        for tpl_name in tpl_names:
            tpl_path = os.path.join(scheme_dir, tpl_name)
            tpl_bgr = self.load_bgr(tpl_path)
            if tpl_bgr is None:
                continue

            class_id, class_name = self.get_class_info(tpl_name, scheme_name)
            if class_name is None:
                class_name = f"unknown_{os.path.splitext(tpl_name)[0]}"

            dets = self._match_multi(screen_bgr, tpl_bgr, tpl_name,
                                     class_name, threshold, fast)
            all_dets.extend(dets)

        return self._nms(all_dets, iou_thresh=0.3)

    def _match_multi(self, screen, tpl, tpl_name, class_name, threshold, fast):
        """单个模板的多实例多尺度匹配"""
        h_scr, w_scr = screen.shape[:2]
        h_tpl, w_tpl = tpl.shape[:2]
        if h_tpl > h_scr or w_tpl > w_scr or h_tpl < 5 or w_tpl < 5:
            return []

        if fast:
            base_scale = w_scr / 1600.0
            scales = [round(base_scale * f, 3) for f in [0.96, 1.0, 1.04]]
            scales = [s for s in scales if 0.4 <= s <= 1.8]
        else:
            base_scale = w_scr / 1600.0
            factors = [0.90, 0.96, 1.0, 1.04, 1.10]
            scales = [round(base_scale * f, 3) for f in factors if 0.4 <= base_scale * f <= 1.8]

        all_hits = []
        for scale in scales:
            sw = int(w_tpl * scale)
            sh = int(h_tpl * scale)
            if sw < 5 or sh < 5 or sw > w_scr or sh > h_scr:
                continue
            scaled = cv2.resize(tpl, (sw, sh), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(screen, scaled, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(res >= threshold)
            for y, x in zip(ys, xs):
                score = float(res[y, x])
                all_hits.append((class_name, x, y, x + sw, y + sh, score, tpl_name, scale))

        # 跨 scale NMS
        return [(c, x1, y1, x2, y2, s, n) for c, x1, y1, x2, y2, s, n, _ in
                self._nms(all_hits, iou_thresh=0.3)]

    def _nms(self, dets, iou_thresh=0.3):
        """按类别做 NMS"""
        if not dets:
            return []

        result = []
        categories = set(d[0] for d in dets)
        for cat in categories:
            cat_dets = [d for d in dets if d[0] == cat]
            cat_dets.sort(key=lambda d: -d[5])  # 按 score 降序
            keep = []
            for det in cat_dets:
                if not any(self._iou(det, kept) > iou_thresh for kept in keep):
                    keep.append(det)
            result.extend(keep)
        return result

    @staticmethod
    def _iou(a, b):
        x1 = max(a[1], b[1])
        y1 = max(a[2], b[2])
        x2 = min(a[3], b[3])
        y2 = min(a[4], b[4])
        inter = max(0, x2 - x1) * max(0, y2 - y1)
        area_a = (a[3] - a[1]) * (a[4] - a[2])
        area_b = (b[3] - b[1]) * (b[4] - b[2])
        union = area_a + area_b - inter
        return inter / union if union > 0 else 0
