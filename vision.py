import os
import json
import time
import pickle
import cv2
import numpy as np
import pyautogui
from PIL import ImageGrab
import win32gui
import fh6_backend
from config import APP_DIR, INTERNAL_DIR, CACHE_DIR, TEMPLATE_CACHE_FILE, TEMPLATE_META_FILE, get_img_path
from constants import MATCH_THRESHOLD


class VisionMixin:
    """图像识别引擎：模板匹配、边缘检测、多尺度适配"""

    def _save_strict_car_simple(self, stage, screen_bgr=None, meta=None, anno=None):
        """轻量版严格识别失败调试截图：存原图 + 标注图 + meta，用于跳过复杂几何信息的场景。
        anno: dict，可含以下字段，用于在标注图上画识别框：
          - tag_boxes: [(x, y, w, h, score), ...]   全新标签候选（黄框）
          - class_boxes: [(x, y, w, h, score), ...] B600 等级候选（青框）
          - card_boxes: [(x, y, w, h, score), ...]  车型主模板候选（绿框）
          - max_tag_loc: (x, y, w, h, score)         整幅最高全新分数点（紫框）
          - title: 额外额额外额额顶部标题文本
        """
        if hasattr(self, "is_debug_screenshots_enabled") and not self.is_debug_screenshots_enabled():
            return
        try:
            import os, time, json
            import cv2
            from config import APP_DIR
            debug_root = os.path.join(APP_DIR, "debug_strict_car")
            os.makedirs(debug_root, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
            out_dir = os.path.join(debug_root, f"{stamp}_{stage}")
            os.makedirs(out_dir, exist_ok=True)
            if screen_bgr is None:
                screen_bgr = self.capture_region(self.regions["全界面"])
            cv2.imwrite(os.path.join(out_dir, "screen_raw.png"), screen_bgr)

            annotated = screen_bgr.copy()
            anno = anno or {}
            # 黄框：全新标签候选
            for box in anno.get("tag_boxes", []) or []:
                x, y, w, h, score = box
                cv2.rectangle(annotated, (int(x), int(y)), (int(x + w), int(y + h)), (0, 255, 255), 2)
                cv2.putText(annotated, f"NEW:{score:.2f}", (int(x), max(0, int(y) - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
            # 青框：B600 等级候选
            for box in anno.get("class_boxes", []) or []:
                x, y, w, h, score = box
                cv2.rectangle(annotated, (int(x), int(y)), (int(x + w), int(y + h)), (255, 255, 0), 2)
                cv2.putText(annotated, f"B600:{score:.2f}", (int(x), max(0, int(y) - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 2)
            # 绿框：主车型模板候选
            for box in anno.get("card_boxes", []) or []:
                x, y, w, h, score = box
                cv2.rectangle(annotated, (int(x), int(y)), (int(x + w), int(y + h)), (0, 255, 0), 2)
                cv2.putText(annotated, f"CAR:{score:.2f}", (int(x), max(0, int(y) - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
            # 紫框：整幅最高全新匹配点（即使低于阈值也画）
            mt = anno.get("max_tag_loc")
            if mt:
                x, y, w, h, score = mt
                cv2.rectangle(annotated, (int(x), int(y)), (int(x + w), int(y + h)), (255, 0, 255), 2)
                cv2.putText(annotated, f"MAX_NEW:{score:.2f}", (int(x), max(0, int(y) - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 0, 255), 2)
            # 额外标题
            title = anno.get("title")
            if title:
                cv2.putText(annotated, str(title), (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            cv2.imwrite(os.path.join(out_dir, "screen_annotated.png"), annotated)
            with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta or {}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def load_template(self, template_path):
        actual_path = get_img_path(template_path)
        cache_key = actual_path

        if cache_key in self.template_cache:
            return self.template_cache[cache_key], actual_path

        tpl = cv2.imread(actual_path, cv2.IMREAD_COLOR)
        if tpl is not None:
            self.template_cache[cache_key] = tpl
        return tpl, actual_path
    def load_template_gray(self, template_path):
        actual_path = get_img_path(template_path)
        cache_key = ("gray", actual_path)
        if not hasattr(self, "template_gray_cache"):
            self.template_gray_cache = {}
        if cache_key in self.template_gray_cache:
            return self.template_gray_cache[cache_key]
        tpl = cv2.imread(actual_path, cv2.IMREAD_GRAYSCALE)
        if tpl is not None:
            self.template_gray_cache[cache_key] = tpl
        return tpl
    def get_images_root_dir(self):
        ext_dir = os.path.join(APP_DIR, "images")
        if os.path.isdir(ext_dir):
            return ext_dir

        int_dir = os.path.join(INTERNAL_DIR, "images")
        if os.path.isdir(int_dir):
            return int_dir

        return None

    def get_template_meta(self):
        images_dir = self.get_images_root_dir()
        meta_data = {}
        if not images_dir:
            return meta_data

        for root, _, files in os.walk(images_dir):
            for file in files:
                if not file.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
                    continue

                path = os.path.join(root, file)
                rel_path = os.path.relpath(path, images_dir).replace("\\", "/")

                try:
                    stat = os.stat(path)
                    meta_data[rel_path] = {
                        "mtime": stat.st_mtime,
                        "size": stat.st_size,
                    }
                except Exception:
                    pass

        return meta_data

    def is_template_cache_valid(self):
        if not os.path.exists(TEMPLATE_CACHE_FILE) or not os.path.exists(TEMPLATE_META_FILE):
            return False

        try:
            with open(TEMPLATE_META_FILE, "r", encoding="utf-8") as f:
                old_meta = json.load(f)
        except Exception:
            return False

        new_meta = self.get_template_meta()
        return old_meta == new_meta

    def build_template_file_cache(self):
        self.log("开始构建模板缓存文件...")
        os.makedirs(CACHE_DIR, exist_ok=True)

        images_dir = self.get_images_root_dir()
        if not images_dir:
            self.log("未找到 images 目录,无法构建模板缓存。")
            return False

        cache_data = {}
        meta_data = self.get_template_meta()

        scales = self.get_scales_to_try(fast_mode=False)

        for rel_path in meta_data.keys():
            img_path = os.path.join(images_dir, rel_path)
            tpl = cv2.imread(img_path, cv2.IMREAD_COLOR)
            if tpl is None:
                continue

            cache_data[rel_path] = {}
            for scale in scales:
                try:
                    if scale == 1.0:
                        scaled = tpl.copy()
                    else:
                        scaled = cv2.resize(tpl, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

                    cache_data[rel_path][str(round(scale, 3))] = scaled
                except Exception:
                    continue

        try:
            with open(TEMPLATE_CACHE_FILE, "wb") as f:
                pickle.dump(cache_data, f, protocol=pickle.HIGHEST_PROTOCOL)

            with open(TEMPLATE_META_FILE, "w", encoding="utf-8") as f:
                json.dump(meta_data, f, ensure_ascii=False, indent=2)

            self.log("模板缓存文件构建完成。")
            return True
        except Exception as e:
            self.log(f"写入模板缓存失败: {e}")
            return False

    def load_template_file_cache(self):
        try:
            with open(TEMPLATE_CACHE_FILE, "rb") as f:
                self.file_template_cache = pickle.load(f)
            self.log("模板缓存文件加载成功。")
            return True
        except Exception as e:
            self.log(f"加载模板缓存失败: {e}")
            self.file_template_cache = {}
            return False

    def prepare_template_cache(self):
        os.makedirs(CACHE_DIR, exist_ok=True)

        if self.is_template_cache_valid():
            if self.load_template_file_cache():
                return

        self.log("模板缓存不存在或已失效,开始后台重建(这可能需要几秒钟)...")
        if self.build_template_file_cache():
            self.template_cache.clear()
            self.scaled_template_cache.clear()
            self.load_template_file_cache()

    def capture_region(self, region=None, mask_areas=None):
        # 【后台化】使用 PrintWindow 后台截图
        if not self.game_hwnd or not win32gui.IsWindow(self.game_hwnd):
            # 兜底：如果窗口句柄失效，回退到原方式
            try:
                if region:
                    x, y, w, h = region
                    bbox = (int(x), int(y), int(x + w), int(y + h))
                    screen = ImageGrab.grab(bbox=bbox, all_screens=True)
                else:
                    screen = ImageGrab.grab(all_screens=True)
            except Exception:
                screen = pyautogui.screenshot(region=region)
            screen_bgr = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)
        else:
            # 获取窗口客户区左上角屏幕坐标，用于 region 裁剪
            wx, wy = 0, 0
            try:
                pt = win32gui.ClientToScreen(self.game_hwnd, (0, 0))
                wx, wy = pt[0], pt[1]
            except Exception:
                pass
            screen_bgr = fh6_backend.capture_window(
                self.game_hwnd, region=region, window_offset=(wx, wy)
            )
            if screen_bgr is None:
                return None

        # 对指定区域打黑块，避免重复识别同一个目标
        if mask_areas:
            for rect in mask_areas:
                try:
                    mx1, my1, mx2, my2 = rect
                    mx1 = max(0, int(mx1))
                    my1 = max(0, int(my1))
                    mx2 = min(screen_bgr.shape[1], int(mx2))
                    my2 = min(screen_bgr.shape[0], int(my2))
                    if mx2 > mx1 and my2 > my1:
                        screen_bgr[my1:my2, mx1:mx2] = 0
                except Exception:
                    pass

        return screen_bgr

    def get_scales_to_try(self, fast_mode=True):
        full_region = self.regions.get("全界面")
        curr_w = full_region[2] if full_region else pyautogui.size()[0]
        # 你的图主要是按 2560 截的,就优先围绕 2560 计算
        primary_base = 2560
        primary_scale = curr_w / primary_base
        scales = []
        def add_scale(s):
            s = round(float(s), 3)
            if 0.45 <= s <= 1.8 and s not in scales:
                scales.append(s)
        # 先加"最可能正确"的比例及其微调
        add_scale(primary_scale)
        add_scale(primary_scale * 0.98)
        add_scale(primary_scale * 1.02)
        add_scale(primary_scale * 0.95)
        add_scale(primary_scale * 1.05)
        add_scale(primary_scale * 0.92)
        add_scale(primary_scale * 1.08)
        # 再兼容其它来源
        for bw in [1920, 1600]:
            s = curr_w / bw
            add_scale(s)
            add_scale(s * 0.98)
            add_scale(s * 1.02)
        # 最后兜底常用比例
        for s in [1.0, 0.95, 1.05, 0.9, 1.1, 0.85, 1.15, 0.8, 0.75, 0.7]:
            add_scale(s)
        if fast_mode:
            return scales[:8]
        return scales

    def get_scaled_template(self, template_path, scale):
        actual_path = get_img_path(template_path)
        images_dir = self.get_images_root_dir()

        if images_dir and os.path.exists(actual_path):
            try:
                rel_key = os.path.relpath(actual_path, images_dir).replace("\\", "/")
            except Exception:
                rel_key = os.path.basename(actual_path)
        else:
            rel_key = os.path.basename(actual_path)

        mem_key = (actual_path, round(scale, 3))
        if mem_key in self.scaled_template_cache:
            return self.scaled_template_cache[mem_key], actual_path

        scale_key = str(round(scale, 3))
        if rel_key in self.file_template_cache:
            tpl = self.file_template_cache[rel_key].get(scale_key)
            if tpl is not None:
                self.scaled_template_cache[mem_key] = tpl
                return tpl, actual_path

        template_orig, actual_path = self.load_template(template_path)
        if template_orig is None:
            return None, actual_path

        try:
            if scale == 1.0:
                tpl = template_orig.copy()
            else:
                tpl = cv2.resize(template_orig, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

            self.scaled_template_cache[mem_key] = tpl
            return tpl, actual_path
        except Exception:
            return None, actual_path

    def find_image_in_screen(self, screen_bgr, template_path, region=None, threshold=0.75, fast_mode=True):
        try:
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)

            for scale in scales_to_try:
                tpl_c, actual_path = self.get_scaled_template(template_path, scale)
                if tpl_c is None:
                    continue

                h, w = tpl_c.shape[:2]
                if h < 5 or w < 5:
                    continue
                if h > screen_bgr.shape[0] or w > screen_bgr.shape[1]:
                    continue

                res = cv2.matchTemplate(screen_bgr, tpl_c, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)

                if max_val >= threshold:
                    pos = (
                        max_loc[0] + w // 2 + (region[0] if region else 0),
                        max_loc[1] + h // 2 + (region[1] if region else 0),
                    )
                    self.last_positions[template_path] = pos
                    # 【新增】:在基础图像查找中增加详细日志返回
                    self.log(f"[ImageMatch] 命中: {template_path} | 得分: {max_val:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                    return pos

            return None

        except Exception as e:
            self.log(f"find_image_in_screen 异常: {e}")
            return None

    def find_image(self, template_path, region=None, threshold=0.75, fast_mode=True):
        if not self.is_running:
            return None

        try:
            screen_bgr = self.capture_region(region)
            return self.find_image_in_screen(
                screen_bgr,
                template_path,
                region=region,
                threshold=threshold,
                fast_mode=fast_mode
            )
        except Exception as e:
            self.log(f"查找图片时发生异常: {e}")
            return None

    def find_any_image(self, image_list, region=None, threshold=MATCH_THRESHOLD, fast_mode=True):
        if not self.is_running:
            return None

        try:
            screen_bgr = self.capture_region(region)
            for img_path in image_list:
                pos = self.find_image_in_screen(
                    screen_bgr,
                    img_path,
                    region=region,
                    threshold=threshold,
                    fast_mode=fast_mode
                )
                if pos:
                    return pos
            return None
        except Exception as e:
            self.log(f"find_any_image 异常: {e}")
            return None

    def find_image_with_element(self, main_path, sub_path, region=None, threshold=0.85, fast_mode=True):
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)
            for scale in scales_to_try:
                # 1. 结合新架构缓存直接读取缩放好的图像
                main_tpl_c, _ = self.get_scaled_template(main_path, scale)
                sub_tpl_c, _ = self.get_scaled_template(sub_path, scale)
                if main_tpl_c is None or sub_tpl_c is None:
                    continue
                h_m, w_m = main_tpl_c.shape[:2]
                if h_m < 5 or w_m < 5 or h_m > screen_bgr.shape[0] or w_m > screen_bgr.shape[1]:
                    continue
                # 2. 一阶匹配:寻找全屏符合的主目标
                res_main = cv2.matchTemplate(screen_bgr, main_tpl_c, cv2.TM_CCOEFF_NORMED)
                loc = np.where(res_main >= threshold)
                checked = set() # 【关键优化】:坐标去重,解决几十万次无效循环造成的卡顿
                for pt in zip(*loc[::-1]):
                    x, y = pt
                    # 过滤相邻 10 个像素内的重复识别点
                    key = (x // 10, y // 10)
                    if key in checked:
                        continue
                    checked.add(key)
                    # 3. 旧代码的核心精髓:在主图区域四周略微扩大 5 像素的范围内找元素
                    sub_roi = screen_bgr[
                        max(0, y - 5):min(screen_bgr.shape[0], y + h_m + 5),
                        max(0, x - 5):min(screen_bgr.shape[1], x + w_m + 5),
                    ]
                    if sub_tpl_c.shape[0] > sub_roi.shape[0] or sub_tpl_c.shape[1] > sub_roi.shape[1]:
                        continue
                                        # 4. 二阶匹配:验证提取范围内是否包含子元素
                    res_sub = cv2.matchTemplate(sub_roi, sub_tpl_c, cv2.TM_CCOEFF_NORMED)
                    sub_score = cv2.minMaxLoc(res_sub)[1]
                    if sub_score >= threshold:
                        # 【新增】:在组合图像查找中增加详细日志返回
                        main_score = res_main[y, x]
                        self.log(f"[ComboMatch] 命中: {main_path}+{sub_path} | 主图得分: {main_score:.3f} | 元素得分: {sub_score:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                        return (
                            x + w_m // 2 + (region[0] if region else 0),
                            y + h_m // 2 + (region[1] if region else 0),
                        )
            return None
        except Exception as e:
            self.log(f"find_image_with_element 异常: {e}")
            return None
    def find_image_with_element_stable(
        self,
        main_path,
        sub_path,
        region=None,
        main_threshold=0.60,
        verify_threshold=0.72,
        sub_threshold=0.70,
        max_candidates=15
    ):
        if not self.is_running:
            return None

        try:
            screen = pyautogui.screenshot(region=region)
            screen_gray = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2GRAY)

            main_tpl = self.load_template_gray(main_path)
            sub_tpl = self.load_template_gray(sub_path)

            if main_tpl is None or sub_tpl is None:
                return None

            h_m, w_m = main_tpl.shape[:2]
            h_s, w_s = sub_tpl.shape[:2]

            if h_m > screen_gray.shape[0] or w_m > screen_gray.shape[1]:
                return None

            res_main = cv2.matchTemplate(screen_gray, main_tpl, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(res_main >= main_threshold)

            if len(xs) == 0:
                return None

            candidates = [(float(res_main[y, x]), x, y) for x, y in zip(xs, ys)]
            candidates.sort(key=lambda t: t[0], reverse=True)

            checked = set()
            checked_count = 0

            for main_score, x, y in candidates:
                key = (x // 8, y // 8)
                if key in checked:
                    continue
                checked.add(key)

                checked_count += 1
                if checked_count > max_candidates:
                    break

                pad = 8
                x1 = max(0, x - pad)
                y1 = max(0, y - pad)
                x2 = min(screen_gray.shape[1], x + w_m + pad)
                y2 = min(screen_gray.shape[0], y + h_m + pad)

                sub_roi = screen_gray[y1:y2, x1:x2]
                if sub_roi.shape[0] < h_s or sub_roi.shape[1] < w_s:
                    continue

                res_sub = cv2.matchTemplate(sub_roi, sub_tpl, cv2.TM_CCOEFF_NORMED)
                sub_score = cv2.minMaxLoc(res_sub)[1]

                if main_score >= verify_threshold and sub_score >= sub_threshold:
                    cx = x + w_m // 2
                    cy = y + h_m // 2
                    if region:
                        cx += region[0]
                        cy += region[1]
                    # 【新增】:打印稳定版组合匹配的详细得分
                    self.log(f"[StableMatch] 命中: {main_path}+{sub_path} | 主图: {main_score:.3f} (需>{verify_threshold}) | 元素: {sub_score:.3f} (需>{sub_threshold})")
                    return (cx, cy)

            return None

        except Exception as e:
            self.log(f"find_image_with_element_stable 识别报错: {e}")
            return None
    def find_image_with_element_multi(self, main_path, sub_path, region=None, fast_mode=True,
        main_threshold=0.60, like_threshold=0.75, final_threshold=0.72, mask_areas=None):
        if not self.is_running:
            return None

        try:
            screen_bgr = self.capture_region(region, mask_areas=mask_areas)
            screen_gray = self.to_gray_image(screen_bgr)
            screen_edge = self.to_edge_image(screen_bgr)

            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)

            sub_scales_to_try = self.get_scales_to_try(fast_mode=False)

            for scale in scales_to_try:
                main_tpl_c, _ = self.get_scaled_template(main_path, scale)

                if main_tpl_c is None:
                    continue

                main_tpl_gray = self.to_gray_image(main_tpl_c)
                main_tpl_edge = self.to_edge_image(main_tpl_c)

                h_m, w_m = main_tpl_c.shape[:2]
                if h_m < 5 or w_m < 5:
                    continue
                if h_m > screen_bgr.shape[0] or w_m > screen_bgr.shape[1]:
                    continue

                # 用彩色主模板先找候选,门槛放低
                res_main = cv2.matchTemplate(screen_bgr, main_tpl_c, cv2.TM_CCOEFF_NORMED)
                # 不再只靠 >= main_threshold 硬切,改成取前 N 个高分候选
                flat = res_main.ravel()
                if flat.size == 0:
                    continue
                top_k = min(80, flat.size)   # 可调,先 80
                idxs = np.argpartition(flat, -top_k)[-top_k:]
                points = []
                for idx in idxs:
                    y, x = np.unravel_index(idx, res_main.shape)
                    score = res_main[y, x]
                    # 给一个很低的底线,防止垃圾点太多
                    if score < max(0.55, main_threshold - 0.12):
                        continue
                    points.append((x, y, score))
                # 先按 y、x 排序,保证视觉顺序
                points.sort(key=lambda p: (p[1], p[0]))

                checked_points = set()

                for pt in points:
                    x, y, base_score = pt

                    # 去重,避免同一辆车计算多次
                    key = (x // 10, y // 10)
                    if key in checked_points:
                        continue
                    checked_points.add(key)

                    roi_bgr = screen_bgr[y:y + h_m, x:x + w_m]
                    roi_gray = screen_gray[y:y + h_m, x:x + w_m]
                    roi_edge = screen_edge[y:y + h_m, x:x + w_m]

                    if roi_bgr.shape[:2] != main_tpl_c.shape[:2]:
                        continue

                    # 四维打分系统 (抗 HDR 核心)
                    color_score = self.match_template_score(roi_bgr, main_tpl_c)
                    gray_score = self.match_template_score(roi_gray, main_tpl_gray)
                    edge_score = self.match_template_score(roi_edge, main_tpl_edge)

                    roi_center = self.crop_center_ratio(roi_bgr, ratio=0.6)
                    tpl_center = self.crop_center_ratio(main_tpl_c, ratio=0.6)
                    center_score = self.match_template_score(roi_center, tpl_center)

                    # 标签匹配 (NEW 标签或作者点赞标签)
                    # 主图卡片和子元素在 FH UI 中可能不是同一缩放比例：例如 skillcar=1.137，而 liketag=0.711。
                    # 因此子元素必须在主图附近独立尝试所有缩放，而不能强制复用 main scale。
                    pad = 5
                    sub_roi = screen_bgr[
                        max(0, y - pad):min(screen_bgr.shape[0], y + h_m + pad),
                        max(0, x - pad):min(screen_bgr.shape[1], x + w_m + pad),
                    ]
                    like_score = 0.0
                    like_scale = None
                    for sub_scale in sub_scales_to_try:
                        sub_tpl_c, _ = self.get_scaled_template(sub_path, sub_scale)
                        if sub_tpl_c is None:
                            continue
                        if sub_tpl_c.shape[0] > sub_roi.shape[0] or sub_tpl_c.shape[1] > sub_roi.shape[1]:
                            continue
                        curr_like = self.match_template_score(sub_roi, sub_tpl_c)
                        if curr_like > like_score:
                            like_score = curr_like
                            like_scale = sub_scale

                    if like_score < like_threshold:
                        continue

                    # 综合计算总分
                    final_score = (
                        color_score * 0.30 +
                        gray_score * 0.20 +
                        edge_score * 0.20 +
                        center_score * 0.15 +
                        like_score * 0.15
                    )

                    curr_pos = (
                        x + w_m // 2 + (region[0] if region else 0),
                        y + h_m // 2 + (region[1] if region else 0),
                    )

                    # 只要及格,立刻返回(因为已经排过序了,第一个及格的一定是左上角的第一个目标)
                    if final_score >= final_threshold:
                        self.log(
                            f"[MultiMatch] 锁定目标: {main_path}+{sub_path} | "
                            f"综合: {final_score:.3f} | 彩色: {color_score:.3f} | "
                            f"灰度: {gray_score:.3f} | 边缘: {edge_score:.3f} | "
                            f"中心: {center_score:.3f} | 标签: {like_score:.3f} | "
                            f"主缩放:{scale:.3f} 标签缩放:{(like_scale or 0):.3f}"
                        )
                        return curr_pos

            return None

        except Exception as e:
            self.log(f"find_image_with_element_multi 异常: {e}")
            return None

    def find_image_with_element_fast(self, main_path, sub_path, region=None, threshold=0.70, sub_threshold=0.70):
        if not self.is_running:
            return None

        try:
            screen = pyautogui.screenshot(region=region)
            screen_gray = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2GRAY)

            main_tpl = self.load_template_gray(main_path)
            sub_tpl = self.load_template_gray(sub_path)

            if main_tpl is None or sub_tpl is None:
                return None

            h_m, w_m = main_tpl.shape[:2]
            h_s, w_s = sub_tpl.shape[:2]

            if h_m > screen_gray.shape[0] or w_m > screen_gray.shape[1]:
                return None

            res_main = cv2.matchTemplate(screen_gray, main_tpl, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res_main >= threshold)

            checked = set()

            for pt in zip(*loc[::-1]):
                x, y = pt

                # 去重,避免相邻重复点太多
                key = (x // 10, y // 10)
                if key in checked:
                    continue
                checked.add(key)

                x1 = max(0, x - 5)
                y1 = max(0, y - 5)
                x2 = min(screen_gray.shape[1], x + w_m + 5)
                y2 = min(screen_gray.shape[0], y + h_m + 5)

                sub_roi = screen_gray[y1:y2, x1:x2]

                if sub_roi.shape[0] < h_s or sub_roi.shape[1] < w_s:
                    continue

                res_sub = cv2.matchTemplate(sub_roi, sub_tpl, cv2.TM_CCOEFF_NORMED)
                _, max_val_sub, _, _ = cv2.minMaxLoc(res_sub)

                if max_val_sub >= sub_threshold:
                    cx = x + w_m // 2
                    cy = y + h_m // 2
                    if region:
                        cx += region[0]
                        cy += region[1]
                    # 【新增】:打印快速匹配模式得分
                    main_score = res_main[y, x]
                    self.log(f"[FastMatch] 命中: {main_path}+{sub_path} | 主图: {main_score:.3f} (需>{threshold}) | 元素: {max_val_sub:.3f} (需>{sub_threshold})")
                    return (cx, cy)

            return None

        except Exception as e:
            self.log(f"find_image_with_element_fast 异常: {e}")
            return None

    def wait_for_image_with_element_multi(self, main_path, sub_path, region=None, fast_mode=True,
        main_threshold=0.60, like_threshold=0.75,
        final_threshold=0.72, timeout=30, interval=0.4):
        start = time.time()

        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_with_element_multi(
                main_path=main_path,
                sub_path=sub_path,
                region=region,
                fast_mode=fast_mode,
                main_threshold=main_threshold,
                like_threshold=like_threshold,
                final_threshold=final_threshold
            )
            if pos:
                return pos

            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)

        return None

    def load_template_transparent(self, template_path):
        """专门加载带有 Alpha 透明通道的图片"""
        actual_path = get_img_path(template_path)
        cache_key = ("transparent", actual_path)
        if not hasattr(self, "template_transparent_cache"):
            self.template_transparent_cache = {}
        if cache_key in self.template_transparent_cache:
            return self.template_transparent_cache[cache_key]

        # 注意这里的 cv2.IMREAD_UNCHANGED,它会保留透明通道 (BGRA)
        tpl = cv2.imread(actual_path, cv2.IMREAD_UNCHANGED)
        if tpl is not None:
            self.template_transparent_cache[cache_key] = tpl
        return tpl
    def find_image_transparent(self, template_path, region=None, threshold=0.70, fast_mode=True):
        """带透明通道的匹配:彻底无视透明背景,只匹配图像主体"""
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            tpl_bgra = self.load_template_transparent(template_path)

            if tpl_bgra is None:
                return None
            # 如果图片没有透明通道(不是4通道),降级为普通匹配
            if tpl_bgra.shape[2] != 4:
                return self.find_image_in_screen(screen_bgr, template_path, region, threshold, fast_mode)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)
            for scale in scales_to_try:
                # 对带有透明通道的原图进行缩放
                if scale == 1.0:
                    tpl_scaled = tpl_bgra.copy()
                else:
                    tpl_scaled = cv2.resize(tpl_bgra, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                h, w = tpl_scaled.shape[:2]
                if h < 5 or w < 5 or h > screen_bgr.shape[0] or w > screen_bgr.shape[1]:
                    continue
                # 分离出 BGR 色彩层 和 Alpha 透明遮罩层
                tpl_bgr = tpl_scaled[:, :, :3]
                alpha_mask = tpl_scaled[:, :, 3]
                                # 核心魔法:带 mask 的匹配!透明区域不参与算分!
                res = cv2.matchTemplate(screen_bgr, tpl_bgr, cv2.TM_CCOEFF_NORMED, mask=alpha_mask)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val >= threshold:
                    # 【新增】:带透明通道的匹配日志
                    self.log(f"[AlphaMatch] 命中(无视背景): {template_path} | 得分: {max_val:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                    return (
                        max_loc[0] + w // 2 + (region[0] if region else 0),
                        max_loc[1] + h // 2 + (region[1] if region else 0),
                    )
            return None
        except Exception as e:
            self.log(f"find_image_transparent 异常: {e}")
            return None
    def wait_for_image_transparent(self, template_path, region=None, threshold=0.70, timeout=30, interval=0.4, fast_mode=True):
        """等待带有透明背景的图片"""
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_transparent(template_path, region, threshold, fast_mode)
            if pos:
                return pos
            time.sleep(interval)
        return None
    def find_image_ultimate_safe(self, main_path, anti_path, region=None, main_threshold=0.80, anti_threshold=0.65, mask_areas=None):
        if not self.is_running: return None
        try:
            screen_bgr = self.capture_region(region, mask_areas=mask_areas)
            screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)

            scales_to_try = self.get_scales_to_try(fast_mode=True)

            for scale in scales_to_try:
                main_tpl_bgr, _ = self.get_scaled_template(main_path, scale)
                anti_tpl_bgr = None
                if anti_path:
                    anti_tpl_bgr, _ = self.get_scaled_template(anti_path, scale)
                if main_tpl_bgr is None:
                    continue
                if anti_path and anti_tpl_bgr is None:
                    continue

                main_tpl_gray = cv2.cvtColor(main_tpl_bgr, cv2.COLOR_BGR2GRAY)
                h_m, w_m = main_tpl_bgr.shape[:2]
                h_a, w_a = anti_tpl_bgr.shape[:2]

                if h_m < 10 or w_m < 10 or h_m > screen_bgr.shape[0] or w_m > screen_bgr.shape[1]:
                    continue

                # 1. 基础彩色初筛
                res_main = cv2.matchTemplate(screen_bgr, main_tpl_bgr, cv2.TM_CCOEFF_NORMED)
                loc = np.where(res_main >= main_threshold)


                points = list(zip(*loc[::-1]))
                # 强制按 X 坐标(从左到右)优先排序,无视上下排
                points.sort(key=lambda p: (p[1] // 50, p[0]))

                checked = set()
                for pt in points:
                    x, y = pt
                    if (x // 10, y // 10) in checked: continue
                    checked.add((x // 10, y // 10))

                    base_score = res_main[y, x]

                    roi_bgr = screen_bgr[y:y+h_m, x:x+w_m]
                    roi_gray = screen_gray[y:y+h_m, x:x+w_m]
                    if roi_bgr.shape[:2] != main_tpl_bgr.shape[:2]: continue

                    # ==================================
                    # 防线 1: 排他校验
                    # ==================================
                    if anti_path and anti_tpl_bgr is not None:
                        h_a, w_a = anti_tpl_bgr.shape[:2]
                        pad_anti = 10
                        roi_y1, roi_y2 = max(0, y - pad_anti), min(screen_bgr.shape[0], y + h_m + pad_anti)
                        roi_x1, roi_x2 = max(0, x - pad_anti), min(screen_bgr.shape[1], x + w_m + pad_anti)
                        anti_roi = screen_bgr[roi_y1:roi_y2, roi_x1:roi_x2]
                        if anti_roi.shape[0] >= h_a and anti_roi.shape[1] >= w_a:
                            res_anti = cv2.matchTemplate(anti_roi, anti_tpl_bgr, cv2.TM_CCOEFF_NORMED)
                            _, anti_score, _, _ = cv2.minMaxLoc(res_anti)
                            if anti_score >= anti_threshold:
                                self.log(f"[排他拦截]: 发现排除图 ({anti_score:.2f}),放弃该目标。")
                                continue

                    # ==================================
                    # 防线 2: 顶部文字
                    # ==================================
                    top_h = int(h_m * 0.25)
                    tpl_top = main_tpl_gray[:top_h, :]

                    score_top = 0.0
                    pad_slide = 5
                    if top_h > pad_slide*2 and w_m > pad_slide*2:
                        tpl_top_core = tpl_top[pad_slide:-pad_slide, pad_slide:-pad_slide]
                        search_top = roi_gray[:int(h_m * 0.35), :]
                        if search_top.shape[0] >= tpl_top_core.shape[0] and search_top.shape[1] >= tpl_top_core.shape[1]:
                            res_top = cv2.matchTemplate(search_top, tpl_top_core, cv2.TM_CCOEFF_NORMED)
                            _, score_top, _, _ = cv2.minMaxLoc(res_top)

                    # ==================================
                    # 防线 3: 【右下角】
                    # ==================================
                    bottom_h = int(h_m * 0.25)
                    right_w = int(w_m * 0.35)
                    tpl_pi_box = main_tpl_bgr[h_m - bottom_h:, w_m - right_w:]

                    score_bot = 0.0
                    if bottom_h > pad_slide*2 and right_w > pad_slide*2:
                        tpl_pi_core = tpl_pi_box[pad_slide:-pad_slide, pad_slide:-pad_slide]
                        search_y1 = h_m - int(h_m * 0.35)
                        search_x1 = w_m - int(w_m * 0.45)
                        search_bot = roi_bgr[search_y1:, search_x1:]

                        if search_bot.shape[0] >= tpl_pi_core.shape[0] and search_bot.shape[1] >= tpl_pi_core.shape[1]:
                            res_bot = cv2.matchTemplate(search_bot, tpl_pi_core, cv2.TM_CCOEFF_NORMED)
                            _, score_bot, _, _ = cv2.minMaxLoc(res_bot)

                    if base_score >= 0.76 and score_top >= 0.75 and score_bot >= 0.85:
                        self.log(f"[终极安全-通过]: 锁定目标!总分:{base_score:.3f} | 顶部车名:{score_top:.2f} | 右下调校:{score_bot:.2f}")
                        return (x + w_m // 2 + (region[0] if region else 0), y + h_m // 2 + (region[1] if region else 0))
                    else:
                        pass # 静默拦截,继续寻找下一个坐标

            return None
        except Exception as e:
            self.log(f"ultimate_safe 异常: {e}")
            return None
    def wait_for_image_ultimate_safe(self, main_path, anti_path, region=None, main_threshold=0.80, anti_threshold=0.65, timeout=3, interval=0.2, mask_areas=None):
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_ultimate_safe(main_path, anti_path, region, main_threshold, anti_threshold, mask_areas=mask_areas)
            if pos: return pos
            time.sleep(interval)
        return None

    def find_new_consumable_car_strict(self, region=None):
        """两步法识别目标车卡：
        Step 1: 全屏跑 newCC.png 找候选车卡（必须是 22B-STI 车图）
        Step 2: 每个候选内部固定位置验 NEW 角标 + B600 等级标签
        保留 multi-scale + gray/edge 兜底。
        """
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            scales = []
            for s in [1.0, 0.98, 1.02, 0.95, 1.05]:
                if s not in scales:
                    scales.append(s)
            for s in self.get_scales_to_try(fast_mode=False):
                if s not in scales:
                    scales.append(s)

            # 阈值常量
            MAIN_THRESHOLD = 0.85       # newCC 彩色主阈值
            MAIN_GRAY_THRESHOLD = 0.62  # 灰度兜底阈值
            MAIN_EDGE_THRESHOLD = 0.20  # 边缘兜底阈值
            MAIN_FALLBACK_MIN = 0.70    # 彩色低于此值直接跳过，不兜底
            TAG_THRESHOLD = 0.85        # NEW 角标内部验阈值
            CLS_THRESHOLD = 0.85        # B600 等级标签内部验阈值
            NMS_DIST = 80               # 候选去重间距（像素）
            TAG_PAD = 4                 # NEW/B600 内部搜索抗抖动（像素）
            CLS_PAD = 4

            # newCC 内部相对位置（实测：newcartag@220,142 / classB600@192,169 于 265x198 模板）
            TAG_REL_X_RATIO = 220.0 / 265.0
            TAG_REL_Y_RATIO = 142.0 / 198.0
            CLS_REL_X_RATIO = 192.0 / 265.0
            CLS_REL_Y_RATIO = 169.0 / 198.0

            best_candidate = None
            best_candidate_score = 0.0
            debug_saved = 0

            for scale in scales:
                main_tpl, _ = self.get_scaled_template("newCC.png", scale)
                tag_tpl, _ = self.get_scaled_template("newcartag.png", scale)
                class_tpl, _ = self.get_scaled_template("classB600.png", scale)
                if main_tpl is None or tag_tpl is None or class_tpl is None:
                    continue

                h_m, w_m = main_tpl.shape[:2]
                h_t, w_t = tag_tpl.shape[:2]
                h_c, w_c = class_tpl.shape[:2]
                if h_m < 20 or w_m < 20 or h_m > screen_bgr.shape[0] or w_m > screen_bgr.shape[1]:
                    continue
                if h_t < 8 or w_t < 12 or h_t > screen_bgr.shape[0] or w_t > screen_bgr.shape[1]:
                    continue
                if h_c < 8 or w_c < 20 or h_c > screen_bgr.shape[0] or w_c > screen_bgr.shape[1]:
                    continue

                # 按缩放计算内部相对位置
                tag_rel_x = int(w_m * TAG_REL_X_RATIO)
                tag_rel_y = int(h_m * TAG_REL_Y_RATIO)
                cls_rel_x = int(w_m * CLS_REL_X_RATIO)
                cls_rel_y = int(h_m * CLS_REL_Y_RATIO)

                # === Step 1: 全屏跑 newCC，找候选车卡 ===
                main_res = cv2.matchTemplate(screen_bgr, main_tpl, cv2.TM_CCOEFF_NORMED)
                locs = np.where(main_res >= MAIN_FALLBACK_MIN)
                raw_points = [(int(x), int(y), float(main_res[y, x])) for x, y in zip(*locs[::-1])]
                raw_points.sort(key=lambda b: -b[2])

                # NMS 去重
                candidates = []
                for px, py, ps in raw_points:
                    if all(abs(px - cx) > NMS_DIST or abs(py - cy) > NMS_DIST for cx, cy, _ in candidates):
                        candidates.append((px, py, ps))

                if not candidates:
                    if debug_saved < 3:
                        debug_saved += 1
                        _, max_main, _, max_loc = cv2.minMaxLoc(main_res)
                        self._save_strict_car_simple(
                            f"no_newcc_scale_{scale:.3f}",
                            screen_bgr=screen_bgr,
                            meta={
                                "reason": "全屏未找到 newCC 候选",
                                "scale": float(scale),
                                "max_newcc_score": float(max_main),
                                "main_threshold": float(MAIN_THRESHOLD),
                                "fallback_min": float(MAIN_FALLBACK_MIN),
                            },
                            anno={
                                "title": f"缩放{scale:.3f} 无 newCC 候选 (最高{max_main:.3f})",
                                "tag_boxes": [],
                                "class_boxes": [],
                                "max_tag_loc": (int(max_loc[0]), int(max_loc[1]), int(w_m), int(h_m), float(max_main)),
                            },
                        )
                    continue

                # === Step 2: 对每个候选车卡做内部验证 ===
                for car_x, car_y, car_score in candidates:
                    # --- 2a: 判断车卡是否可信（彩色优先，灰度+边缘兜底）---
                    is_card_valid = False
                    gray_score = 0.0
                    edge_score = 0.0

                    if car_score >= MAIN_THRESHOLD:
                        is_card_valid = True
                    elif car_score >= MAIN_FALLBACK_MIN:
                        # 灰度+边缘兜底
                        try:
                            patch = screen_bgr[car_y:car_y + h_m, car_x:car_x + w_m]
                            if patch.shape[:2] == main_tpl.shape[:2]:
                                tpl_gray = cv2.cvtColor(main_tpl, cv2.COLOR_BGR2GRAY)
                                cand_gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
                                _, gray_score, _, _ = cv2.minMaxLoc(
                                    cv2.matchTemplate(cand_gray, tpl_gray, cv2.TM_CCOEFF_NORMED))
                                tpl_edge = cv2.Canny(tpl_gray, 60, 160)
                                cand_edge = cv2.Canny(cand_gray, 60, 160)
                                _, edge_score, _, _ = cv2.minMaxLoc(
                                    cv2.matchTemplate(cand_edge, tpl_edge, cv2.TM_CCOEFF_NORMED))
                                if gray_score >= MAIN_GRAY_THRESHOLD and edge_score >= MAIN_EDGE_THRESHOLD:
                                    is_card_valid = True
                        except Exception:
                            pass

                    if not is_card_valid:
                        self.log(
                            f"[StrictCar] 车卡候选({car_x},{car_y}) 分数不足: "
                            f"car={car_score:.3f} gray={gray_score:.3f} edge={edge_score:.3f} scale={scale:.3f}"
                        )
                        continue

                    # --- 2b: 在车卡内部固定位置验 NEW 角标 ---
                    tx0 = car_x + tag_rel_x
                    ty0 = car_y + tag_rel_y
                    tx1 = max(0, tx0 - TAG_PAD)
                    ty1 = max(0, ty0 - TAG_PAD)
                    tx2 = min(screen_bgr.shape[1], tx0 + TAG_PAD + w_t)
                    ty2 = min(screen_bgr.shape[0], ty0 + TAG_PAD + h_t)
                    tag_search = screen_bgr[ty1:ty2, tx1:tx2]
                    if tag_search.shape[0] < h_t or tag_search.shape[1] < w_t:
                        continue
                    tag_res = cv2.matchTemplate(tag_search, tag_tpl, cv2.TM_CCOEFF_NORMED)
                    _, tag_score, _, _ = cv2.minMaxLoc(tag_res)

                    if tag_score < TAG_THRESHOLD:
                        self.log(
                            f"[StrictCar] 车卡({car_x},{car_y}) NEW 不足: "
                            f"tag={tag_score:.3f}<{TAG_THRESHOLD} car={car_score:.3f} scale={scale:.3f}"
                        )
                        continue

                    # --- 2c: 在车卡内部固定位置验 B600 等级 ---
                    cx0 = car_x + cls_rel_x
                    cy0 = car_y + cls_rel_y
                    cx1 = max(0, cx0 - CLS_PAD)
                    cy1 = max(0, cy0 - CLS_PAD)
                    cx2 = min(screen_bgr.shape[1], cx0 + CLS_PAD + w_c)
                    cy2 = min(screen_bgr.shape[0], cy0 + CLS_PAD + h_c)
                    cls_search = screen_bgr[cy1:cy2, cx1:cx2]
                    if cls_search.shape[0] < h_c or cls_search.shape[1] < w_c:
                        continue
                    cls_res = cv2.matchTemplate(cls_search, class_tpl, cv2.TM_CCOEFF_NORMED)
                    _, cls_score, _, _ = cv2.minMaxLoc(cls_res)

                    if cls_score < CLS_THRESHOLD:
                        self.log(
                            f"[StrictCar] 车卡({car_x},{car_y}) B600 不足: "
                            f"cls={cls_score:.3f}<{CLS_THRESHOLD} tag={tag_score:.3f} car={car_score:.3f} scale={scale:.3f}"
                        )
                        continue

                    # === 通过所有验证，记录候选 ===
                    effective_score = max(float(car_score), float(gray_score), float(edge_score))
                    self.log(
                        f"[StrictCar] 发现达标候选: car=({car_x},{car_y}) "
                        f"car={car_score:.3f} gray={gray_score:.3f} edge={edge_score:.3f} "
                        f"tag={tag_score:.3f} cls={cls_score:.3f} scale={scale:.3f}"
                    )

                    if effective_score > best_candidate_score:
                        best_candidate_score = effective_score
                        off_x = region[0] if region else 0
                        off_y = region[1] if region else 0
                        click_x = car_x + w_m // 2
                        click_y = car_y + h_m // 2

                        self.last_strict_car_meta = {
                            "tag_score": float(tag_score),
                            "class_score": float(cls_score),
                            "car_score": float(car_score),
                            "gray_score": float(gray_score),
                            "edge_score": float(edge_score),
                            "effective_score": float(effective_score),
                            "scale": float(scale),
                            "card_x": int(car_x),
                            "card_y": int(car_y),
                            "card_w": int(w_m),
                            "card_h": int(h_m),
                        }
                        self.last_strict_car_click_points = [
                            (int(click_x + off_x), int(click_y + off_y)),
                            (int(car_x + int(w_m * 0.5) + off_x), int(car_y + int(h_m * 0.4) + off_y)),
                            (int(car_x + int(w_m * 0.5) + off_x), int(car_y + int(h_m * 0.6) + off_y)),
                            (int(car_x + cls_rel_x + w_c // 2 + off_x), int(car_y + cls_rel_y + h_c // 2 + off_y)),
                        ]
                        best_candidate = (click_x + off_x, click_y + off_y, car_x, car_y,
                                          car_score, tag_score, cls_score, gray_score, edge_score, scale)

                        # 保存成功调试快照
                        if debug_saved < 5:
                            debug_saved += 1
                            self._save_strict_car_simple(
                                f"locked_scale_{scale:.3f}",
                                screen_bgr=screen_bgr,
                                meta=self.last_strict_car_meta,
                                anno={
                                    "title": f"锁定目标 car={car_score:.2f} tag={tag_score:.2f} b600={cls_score:.2f}",
                                    "tag_boxes": [(int(tx0), int(ty0), int(w_t), int(h_t), float(tag_score))],
                                    "class_boxes": [(int(cx0), int(cy0), int(w_c), int(h_c), float(cls_score))],
                                    "max_tag_loc": (int(car_x), int(car_y), int(w_m), int(h_m), float(car_score)),
                                },
                            )

            if best_candidate:
                x, y, car_x, car_y, car_score, tag_score, cls_score, gray_score, edge_score, scale = best_candidate
                self.log(
                    f"[StrictCar] 最终锁定目标车: car=({car_x},{car_y}) "
                    f"car={car_score:.3f} tag={tag_score:.3f} cls={cls_score:.3f} "
                    f"gray={gray_score:.3f} edge={edge_score:.3f} scale={scale:.3f}"
                )
                return (x, y)

            self.log("[StrictCar] 本帧未找到达标目标车。")
            # 保存最终失败快照
            if debug_saved < 5:
                self._save_strict_car_simple(
                    "final_no_target",
                    screen_bgr=screen_bgr,
                    meta={"reason": "所有缩放均未找到达标目标"},
                )
            return None
        except Exception as e:
            self.log(f"find_new_consumable_car_strict 异常: {e}")
            return None

    def wait_for_new_consumable_car_strict(self, timeout=3, interval=0.2):
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_new_consumable_car_strict(region=self.regions["全界面"])
            if pos:
                return pos
            time.sleep(interval)
        return None

    def to_gray_image(self, img):
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    def to_edge_image(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        edge = cv2.Canny(blur, 50, 150)
        return edge
    def crop_center_ratio(self, img, ratio=0.6):
        h, w = img.shape[:2]
        ch = int(h * ratio)
        cw = int(w * ratio)
        y1 = max(0, (h - ch) // 2)
        x1 = max(0, (w - cw) // 2)
        return img[y1:y1 + ch, x1:x1 + cw]
    def find_image_gray(self, template_path, region=None, threshold=0.75, fast_mode=True, invert_mode=False):
        """
        纯灰度UI查找,支持多分辨率缩放 + 可选翻转模式
        参数:
            template_path (str): 模板图片路径
            region (tuple|list|None): 搜索区域,格式通常为 (x, y, w, h),None 表示全屏/默认区域
            threshold (float): 匹配阈值,范围通常 0~1,越高越严格
            fast_mode (bool): 是否使用快速缩放搜索模式,True=较少缩放比,False=更多缩放比
            invert_mode (bool): 是否启用翻转模式,True 时会同时匹配原图和反相图(白底黑字 / 黑底白字都能识别)
        返回:
            tuple|None:
                - 找到时返回匹配中心点坐标 (x, y)
                - 找不到返回 None
        """
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)

            # 【新增】模板只读取一次,避免每个 scale 都重复加载
            tpl_gray_raw = self.load_template_gray(template_path)
            if tpl_gray_raw is None:
                return None

            for scale in scales_to_try:
                # 【改动】从原始模板复制,避免反复 resize 污染
                tpl_gray = tpl_gray_raw
                if scale != 1.0:
                    tpl_gray = cv2.resize(tpl_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

                h, w = tpl_gray.shape[:2]
                if h < 5 or w < 5 or h > screen_gray.shape[0] or w > screen_gray.shape[1]:
                    continue

                # ==============================
                # 原图匹配
                # ==============================
                res = cv2.matchTemplate(screen_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val >= threshold:
                    self.log(f"[GrayMatch] 命中: {template_path} | 模式: 原图 | 灰度得分: {max_val:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                    return (
                        max_loc[0] + w // 2 + (region[0] if region else 0),
                        max_loc[1] + h // 2 + (region[1] if region else 0),
                    )

                # ==============================
                # 【新增】翻转模式:反相模板匹配
                # ==============================
                if invert_mode:
                    tpl_inv = 255 - tpl_gray
                    res_inv = cv2.matchTemplate(screen_gray, tpl_inv, cv2.TM_CCOEFF_NORMED)
                    _, max_val_inv, _, max_loc_inv = cv2.minMaxLoc(res_inv)
                    if max_val_inv >= threshold:
                        self.log(f"[GrayMatch] 命中: {template_path} | 模式: 反相 | 灰度得分: {max_val_inv:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                        return (
                            max_loc_inv[0] + w // 2 + (region[0] if region else 0),
                            max_loc_inv[1] + h // 2 + (region[1] if region else 0),
                        )

            return None
        except Exception as e:
            self.log(f"find_image_gray 异常: {e}")
            return None
    def find_any_image_gray(self, image_list, region=None, threshold=0.75, fast_mode=True, invert_mode=False):
        """
        纯灰度多图查找,支持多分辨率缩放 + 可选翻转模式
        参数:
            image_list (list): 模板图片路径列表,如 ["a.png", "b.png", "c.png"]
            region (tuple|list|None): 搜索区域,格式通常为 (x, y, w, h),None 表示全屏/默认区域
            threshold (float): 匹配阈值,范围通常 0~1,越高越严格
            fast_mode (bool): 是否使用快速缩放搜索模式,True=较少缩放比,False=更多缩放比
            invert_mode (bool): 是否启用翻转模式,True 时会同时匹配原图和反相图(白底黑字 / 黑底白字都能识别)
        返回:
            tuple|None:
                - 找到任意一张时返回匹配中心点坐标 (x, y)
                - 都找不到返回 None
        """
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)

            for img_path in image_list:
                # 【新增】模板只读取一次
                tpl_gray_raw = self.load_template_gray(img_path)
                if tpl_gray_raw is None:
                    continue

                for scale in scales_to_try:
                    # 【改动】从原始模板复制
                    tpl_gray = tpl_gray_raw
                    if scale != 1.0:
                        tpl_gray = cv2.resize(tpl_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

                    h, w = tpl_gray.shape[:2]
                    if h < 5 or w < 5 or h > screen_gray.shape[0] or w > screen_gray.shape[1]:
                        continue

                    # ==============================
                    # 原图匹配
                    # ==============================
                    res = cv2.matchTemplate(screen_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(res)
                    if max_val >= threshold:
                        self.log(f"[GrayMatchAny] 命中: {img_path} | 模式: 原图 | 灰度得分: {max_val:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                        return (
                            max_loc[0] + w // 2 + (region[0] if region else 0),
                            max_loc[1] + h // 2 + (region[1] if region else 0),
                        )

                    # ==============================
                    # 【新增】翻转模式:反相模板匹配
                    # ==============================
                    if invert_mode:
                        tpl_inv = 255 - tpl_gray
                        res_inv = cv2.matchTemplate(screen_gray, tpl_inv, cv2.TM_CCOEFF_NORMED)
                        _, max_val_inv, _, max_loc_inv = cv2.minMaxLoc(res_inv)
                        if max_val_inv >= threshold:
                            self.log(f"[GrayMatchAny] 命中: {img_path} | 模式: 反相 | 灰度得分: {max_val_inv:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                            return (
                                max_loc_inv[0] + w // 2 + (region[0] if region else 0),
                                max_loc_inv[1] + h // 2 + (region[1] if region else 0),
                            )

            return None
        except Exception as e:
            self.log(f"find_any_image_gray 异常: {e}")
            return None

    def wait_for_any_image_gray(self, image_list, region=None, threshold=0.75, timeout=30, interval=0.3, fast_mode=True, invert_mode=False):
        """
        等待多张灰度图中的任意一张出现
        参数:
            image_list (list): 模板图片路径列表,如 ["a.png", "b.png", "c.png"]
            region (tuple|list|None): 搜索区域,格式通常为 (x, y, w, h),None 表示全屏/默认区域
            threshold (float): 匹配阈值,范围通常 0~1,越高越严格
            timeout (int|float): 最长等待时间,单位秒
            interval (int|float): 每次检测失败后的等待间隔,单位秒
            fast_mode (bool): 是否使用快速缩放搜索模式,True=较少缩放比,False=更多缩放比
            invert_mode (bool): 是否启用翻转模式,True 时会同时匹配原图和反相图
        返回:
            tuple|None:
                - 超时前找到时返回匹配中心点坐标 (x, y)
                - 超时未找到返回 None
        """
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_any_image_gray(
                image_list,
                region=region,
                threshold=threshold,
                fast_mode=fast_mode,
                invert_mode=invert_mode   # 【新增】
            )
            if pos:
                return pos

            # 安全等待机制,防止卡死
            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)
        return None
    def wait_for_image_gray(self, template_path, region=None, threshold=0.75, timeout=30, interval=0.3, fast_mode=True, invert_mode=False):
        """
        等待单张灰度图出现
        参数:
            template_path (str): 模板图片路径
            region (tuple|list|None): 搜索区域,格式通常为 (x, y, w, h),None 表示全屏/默认区域
            threshold (float): 匹配阈值,范围通常 0~1,越高越严格
            timeout (int|float): 最长等待时间,单位秒
            interval (int|float): 每次检测失败后的等待间隔,单位秒
            fast_mode (bool): 是否使用快速缩放搜索模式,True=较少缩放比,False=更多缩放比
            invert_mode (bool): 是否启用翻转模式,True 时会同时匹配原图和反相图
        返回:
            tuple|None:
                - 超时前找到时返回匹配中心点坐标 (x, y)
                - 超时未找到返回 None
        """
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_gray(
                template_path,
                region=region,
                threshold=threshold,
                fast_mode=fast_mode,
                invert_mode=invert_mode   # 【新增】
            )
            if pos:
                return pos

            # 安全等待机制
            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)
        return None

    def find_any_image_transparent(self, image_list, region=None, threshold=0.70, fast_mode=True):
        """查找多张带透明通道的图片中的任意一张"""
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)

            for template_path in image_list:
                tpl_bgra = self.load_template_transparent(template_path)
                if tpl_bgra is None:
                    continue

                # 如果图片没有透明通道,降级为普通匹配
                if tpl_bgra.shape[2] != 4:
                    pos = self.find_image_in_screen(screen_bgr, template_path, region, threshold, fast_mode)
                    if pos: return pos
                    continue

                for scale in scales_to_try:
                    if scale == 1.0:
                        tpl_scaled = tpl_bgra.copy()
                    else:
                        tpl_scaled = cv2.resize(tpl_bgra, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

                    h, w = tpl_scaled.shape[:2]
                    if h < 5 or w < 5 or h > screen_bgr.shape[0] or w > screen_bgr.shape[1]:
                        continue

                    tpl_bgr = tpl_scaled[:, :, :3]
                    alpha_mask = tpl_scaled[:, :, 3]

                    res = cv2.matchTemplate(screen_bgr, tpl_bgr, cv2.TM_CCOEFF_NORMED, mask=alpha_mask)
                    _, max_val, _, max_loc = cv2.minMaxLoc(res)

                    if max_val >= threshold:
                        # 【新增】:多张带透明通道的匹配日志
                        self.log(f"[AlphaMatchAny] 命中(无视背景): {template_path} | 得分: {max_val:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                        return (
                            max_loc[0] + w // 2 + (region[0] if region else 0),
                            max_loc[1] + h // 2 + (region[1] if region else 0),
                        )
            return None
        except Exception as e:
            self.log(f"find_any_image_transparent 异常: {e}")
            return None

    def wait_for_any_image(self, image_list, region=None, threshold=0.75, timeout=30, interval=0.4, fast_mode=True, log_text=None):
        start = time.time()

        while self.is_running and time.time() - start < timeout:
            try:
                screen_bgr = self.capture_region(region)
                for img_path in image_list:
                    pos = self.find_image_in_screen(
                        screen_bgr,
                        img_path,
                        region=region,
                        threshold=threshold,
                        fast_mode=fast_mode
                    )
                    if pos:
                        return pos
            except Exception as e:
                self.log(f"wait_for_any_image 异常: {e}")

            if log_text:
                self.log(log_text)

            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)

        return None

    def wait_for_image(self, template_path, region=None, threshold=0.75, timeout=30, interval=0.4, fast_mode=True, log_text=None):
        return self.wait_for_any_image(
            [template_path],
            region=region,
            threshold=threshold,
            timeout=timeout,
            interval=interval,
            fast_mode=fast_mode,
            log_text=log_text
        )

    def wait_for_buy_and_used_car(self, timeout=20):
        targets = ["BNandUC.png"]
        checks = [
            ("gray", lambda: self.wait_for_any_image_gray(targets, region=self.regions["左"], threshold=0.68, timeout=timeout, interval=0.25, fast_mode=False)),
            ("full", lambda: self.wait_for_any_image(targets, region=self.regions["全界面"], threshold=0.65, timeout=timeout, interval=0.25, fast_mode=False)),
            ("fast", lambda: self.wait_for_any_image(targets, region=self.regions["左"], threshold=0.70, timeout=timeout, interval=0.25, fast_mode=True)),
        ]

        for label, fn in checks:
            pos = fn()
            if pos:
                self.log(f"[BuyNewUsed] 命中模式: {label}")
                return pos
        return None

    def match_template_score(self, src, tpl):
        try:
            if tpl is None or src is None:
                return 0.0
            th, tw = tpl.shape[:2]
            sh, sw = src.shape[:2]
            if th < 5 or tw < 5 or th > sh or tw > sw:
                return 0.0
            res = cv2.matchTemplate(src, tpl, cv2.TM_CCOEFF_NORMED)
            return cv2.minMaxLoc(res)[1]
        except Exception:
            return 0.0
