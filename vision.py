import os
import json
import time
import pickle
import cv2
import numpy as np
import pyautogui
from PIL import ImageGrab
import win32gui
from concurrent.futures import ThreadPoolExecutor
import fh6_backend

# 禁用 OpenCV 内部多线程，由 ThreadPoolExecutor 接管并行
cv2.setNumThreads(1)
from config import APP_DIR, INTERNAL_DIR, CACHE_DIR, TEMPLATE_CACHE_FILE, TEMPLATE_META_FILE, get_img_path

# ==========================================
# 调试工具
# ==========================================
DEBUG_MISS_DIR = os.path.join(APP_DIR, "debug", "miss")
DEBUG_ACTION_DIR = os.path.join(APP_DIR, "debug", "actions")

def _save_debug_screenshot(screen_bgr, tag, score=None, extra=None):
    """保存调试截图到 debug/ 目录"""
    try:
        os.makedirs(DEBUG_MISS_DIR, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        safe_tag = tag.replace("/", "_").replace("\\", "_").replace(" ", "_")
        score_str = f"_{score:.3f}" if score is not None else ""
        fname = f"{ts}_{safe_tag}{score_str}.png"
        path = os.path.join(DEBUG_MISS_DIR, fname)
        cv2.imwrite(path, screen_bgr)
        return path
    except Exception:
        return None

def _save_action_screenshot(screen_bgr, action, pos=None, tag=None):
    """保存操作截图到 debug/actions/ 目录，标记点击位置"""
    try:
        os.makedirs(DEBUG_ACTION_DIR, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        annotated = screen_bgr.copy()
        if pos is not None:
            px, py = int(pos[0]), int(pos[1])
            cv2.drawCircle(annotated, (px, py), 20, (0, 0, 255), 2)
            cv2.drawCircle(annotated, (px, py), 3, (0, 0, 255), -1)
            cv2.putText(annotated, f"({px},{py})", (px + 25, py), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        safe_tag = (tag or action).replace("/", "_").replace("\\", "_").replace(" ", "_")
        fname = f"{ts}_{action}_{safe_tag}.png"
        path = os.path.join(DEBUG_ACTION_DIR, fname)
        cv2.imwrite(path, annotated)
        return path
    except Exception:
        return None
from constants import MATCH_THRESHOLD
from recognition_config import get_recognition_profile


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
        except Exception as e:
            if hasattr(self, 'log'):
                self.log(f"[Debug] 严格识别调试截图保存失败: {e}", level="DEBUG")

    def load_template(self, template_path):
        """加载彩色模板图（BGR），带内存缓存，返回 (template, actual_path)。"""
        actual_path = get_img_path(template_path)
        cache_key = actual_path

        if cache_key in self.template_cache:
            return self.template_cache[cache_key], actual_path

        tpl = cv2.imread(actual_path, cv2.IMREAD_COLOR)
        if tpl is not None:
            self.template_cache[cache_key] = tpl
            self.log(f"[LoadTemplate] {template_path} -> {actual_path} shape={tpl.shape}")
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

                    # PNG 压缩存储，体积缩小 ~4x
                    ok, buf = cv2.imencode('.png', scaled)
                    if ok:
                        cache_data[rel_path][str(round(scale, 3))] = buf.tobytes()
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
            except Exception as e:
                if hasattr(self, 'log'):
                    self.log(f"ClientToScreen 获取窗口坐标失败: {e}", level="WARN")
            screen_bgr = fh6_backend.capture_window(
                self.game_hwnd, region=region, window_offset=(wx, wy)
            )
            if screen_bgr is None:
                self.log(f"[Capture] PrintWindow 失败 | hwnd={self.game_hwnd} | region={region}")
                return None
            # 黑屏/白屏检测
            mean_val = screen_bgr.mean()
            if mean_val < 5.0:
                self.log(f"[Capture] ⚠️ 截图疑似黑屏 | 均值={mean_val:.1f} | hwnd={self.game_hwnd} | 尺寸={screen_bgr.shape[:2]}")
                self.capture_diagnostic_snapshot("black_screen", image_bgr=screen_bgr, reason="截图均值<5.0", level="ERROR", meta={"mean": round(float(mean_val), 2), "hwnd": self.game_hwnd})
            elif mean_val > 250.0:
                self.log(f"[Capture] ⚠️ 截图疑似白屏 | 均值={mean_val:.1f} | hwnd={self.game_hwnd} | 尺寸={screen_bgr.shape[:2]}")
                self.capture_diagnostic_snapshot("white_screen", image_bgr=screen_bgr, reason="截图均值>250.0", level="ERROR", meta={"mean": round(float(mean_val), 2), "hwnd": self.game_hwnd})

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
            if 0.35 <= s <= 1.8 and s not in scales:
                scales.append(s)
        # 先加"最可能正确"的比例及其微调
        add_scale(primary_scale)
        add_scale(primary_scale * 0.95)
        add_scale(primary_scale * 1.05)
        add_scale(1.0)
        # 宽范围覆盖：0.05 步长，确保不同来源的模板都能匹配
        for s in [0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.05, 1.1, 1.15, 1.2, 1.3, 1.5]:
            add_scale(s)
        if fast_mode:
            return scales  # ~22 个比例，覆盖 0.4~1.5，兼顾速度与覆盖
        # 非快速模式：补充更精细的微调
        add_scale(primary_scale * 0.98)
        add_scale(primary_scale * 1.02)
        add_scale(primary_scale * 0.92)
        add_scale(primary_scale * 1.08)
        for bw in [1920, 1600]:
            s = curr_w / bw
            add_scale(s)
            add_scale(s * 0.98)
            add_scale(s * 1.02)
        for s in [0.35, 0.38, 0.42, 0.48, 0.52, 0.58, 0.62, 0.68, 0.72, 0.78, 0.82, 0.88, 0.92, 1.25, 1.35, 1.4, 1.6, 1.7, 1.8]:
            add_scale(s)
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
            raw = self.file_template_cache[rel_key].get(scale_key)
            if raw is not None:
                # PNG bytes -> ndarray
                if isinstance(raw, (bytes, bytearray)):
                    buf = np.frombuffer(raw, dtype=np.uint8)
                    tpl = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                else:
                    # 向后兼容：旧缓存直接存了 ndarray
                    tpl = raw
                if tpl is not None:
                    self.scaled_template_cache[mem_key] = tpl
                    if scale == 1.0:
                        self.log(f"[ScaledTpl-CACHE] {template_path} rel_key={rel_key} shape={tpl.shape}")
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

    def _sort_column_first(self, points, x_idx=0, y_idx=1, tolerance=50):
        """按列优先排序：先从上到下扫第一列，再第二列，以此类推。
        x 坐标在 tolerance 范围内视为同一列。
        """
        if not points:
            return points
        sorted_by_x = sorted(points, key=lambda p: p[x_idx])
        columns = []
        current_col = []
        col_x = None
        for p in sorted_by_x:
            px = p[x_idx]
            if col_x is None or abs(px - col_x) <= tolerance:
                current_col.append(p)
                if col_x is None:
                    col_x = px
            else:
                columns.append(current_col)
                current_col = [p]
                col_x = px
        if current_col:
            columns.append(current_col)
        result = []
        for col in columns:
            col.sort(key=lambda p: p[y_idx])
            result.extend(col)
        return result

    def find_image_in_screen(self, screen_bgr, template_path, region=None, threshold=0.75, fast_mode=True):
        try:
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)
            best_score = 0.0
            best_scale = 0.0

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
                if max_val > best_score:
                    best_score = max_val
                    best_scale = scale

                if max_val >= threshold:
                    pos = (
                        max_loc[0] + w // 2 + (region[0] if region else 0),
                        max_loc[1] + h // 2 + (region[1] if region else 0),
                    )
                    self.last_positions[template_path] = pos
                    self.log(f"[ImageMatch] 命中: {template_path} | 得分: {max_val:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                    return pos

            self.log(f"[ImageMatch] 未命中: {template_path} | 最高分: {best_score:.3f} (阈值 {threshold}) | 最佳缩放: {best_scale:.3f} | 截图均值: {screen_bgr.mean():.1f} | 区域: {region}")
            self.capture_diagnostic_snapshot(template_path, region=region, image_bgr=screen_bgr, reason="未命中", level="WARN", threshold=threshold, score=best_score, meta={"best_scale": round(best_scale, 3)})
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
        """组合匹配（基础彩色模式）- 委托给 find_combo"""
        return self.find_combo(
            main_path, sub_path, region=region,
            main_threshold=threshold, sub_threshold=threshold, final_threshold=threshold,
            use_gray_only=False, use_four_dim=False, sub_independent_scale=False,
            fast_mode=fast_mode
        )
    def find_image_with_element_stable(
        self, main_path, sub_path, region=None,
        main_threshold=0.60, verify_threshold=0.72, sub_threshold=0.70, max_candidates=15
    ):
        """组合匹配（灰度稳定模式）- 委托给 find_combo，含多尺度+IoU NMS"""
        return self.find_combo(
            main_path, sub_path, region=region,
            main_threshold=main_threshold, sub_threshold=sub_threshold, final_threshold=verify_threshold,
            use_gray_only=True, use_four_dim=False, sub_independent_scale=False,
            fast_mode=True, max_candidates=max_candidates
        )
    def find_image_with_element_multi(self, main_path, sub_path, region=None, fast_mode=True,
        main_threshold=0.60, like_threshold=0.75, final_threshold=0.72, mask_areas=None):
        """组合匹配（四维多维度模式）- 委托给 find_combo，含灰度预筛+IoU NMS"""
        return self.find_combo(
            main_path, sub_path, region=region,
            main_threshold=main_threshold, sub_threshold=like_threshold, final_threshold=final_threshold,
            use_gray_only=False, use_four_dim=True, sub_independent_scale=True,
            fast_mode=fast_mode, mask_areas=mask_areas
        )
    def find_image_with_element_fast(self, main_path, sub_path, region=None, threshold=0.70, sub_threshold=0.70):
        """组合匹配（灰度快速模式）- 委托给 find_combo，含多尺度+IoU NMS"""
        return self.find_combo(
            main_path, sub_path, region=region,
            main_threshold=threshold, sub_threshold=sub_threshold, final_threshold=threshold,
            use_gray_only=True, use_four_dim=False, sub_independent_scale=False,
            fast_mode=True
        )
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
            if screen_bgr is None:
                self.log(f"[AlphaMatch] 截图失败: {template_path} | region={region}")
                return None
            tpl_bgra = self.load_template_transparent(template_path)

            if tpl_bgra is None:
                self.log(f"[AlphaMatch] 模板加载失败: {template_path}")
                self.capture_diagnostic_snapshot(f"no_template_{template_path}", region=region, image_bgr=screen_bgr, reason="模板加载失败", level="ERROR")
                return None
            if tpl_bgra.shape[2] != 4:
                self.log(f"[AlphaMatch] 降级为普通匹配: {template_path} (无 Alpha 通道)")
                return self.find_image_in_screen(screen_bgr, template_path, region, threshold, fast_mode)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)
            best_score = 0.0
            best_scale = 0.0
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
                if max_val > best_score:
                    best_score = max_val
                    best_scale = scale
                if max_val >= threshold:
                    self.log(f"[AlphaMatch] 命中(无视背景): {template_path} | 得分: {max_val:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                    return (
                        max_loc[0] + w // 2 + (region[0] if region else 0),
                        max_loc[1] + h // 2 + (region[1] if region else 0),
                    )
            self.log(f"[AlphaMatch] 未命中: {template_path} | 最高分: {best_score:.3f} (阈值 {threshold}) | 最佳缩放: {best_scale:.3f} | 截图均值: {screen_bgr.mean():.1f} | 区域: {region}")
            self.capture_diagnostic_snapshot(template_path, region=region, image_bgr=screen_bgr, reason="未命中", level="WARN", threshold=threshold, score=best_score, meta={"best_scale": round(best_scale, 3)})
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
    def find_image_ultimate_safe(self, main_path, anti_path, region=None, main_threshold=0.80, anti_threshold=0.65, mask_areas=None, top_threshold=0.75, bot_threshold=0.85):
        if not self.is_running: return None
        try:
            screen_bgr = self.capture_region(region, mask_areas=mask_areas)
            screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)

            scales_to_try = self.get_scales_to_try(fast_mode=True)

            # 预初始化：所有 scale 模板加载失败时循环体一次都不进，
            # 下方调试块引用的 points/scale 会成为未定义变量
            points = []
            scale = 0.0

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

                if h_m < 10 or w_m < 10 or h_m > screen_bgr.shape[0] or w_m > screen_bgr.shape[1]:
                    continue

                # 1. 基础彩色初筛
                res_main = cv2.matchTemplate(screen_bgr, main_tpl_bgr, cv2.TM_CCOEFF_NORMED)
                loc = np.where(res_main >= main_threshold)
                raw_pts = [(int(x), int(y), w_m, h_m, float(res_main[y, x])) for x, y in zip(*loc[::-1])]
                # IoU NMS 去重（按分数降序，替代原始网格去重）
                points = self._nms_iou(raw_pts, iou_threshold=0.3)
                points = self._sort_column_first(points, x_idx=0, y_idx=1, tolerance=50)

                for x, y, _, _, base_score in points:

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

                    if base_score >= 0.76 and score_top >= top_threshold and score_bot >= bot_threshold:
                        self.log(f"[终极安全-通过]: 锁定目标!总分:{base_score:.3f} | 顶部车名:{score_top:.2f} | 右下调校:{score_bot:.2f}")
                        return (x + w_m // 2 + (region[0] if region else 0), y + h_m // 2 + (region[1] if region else 0))
                    else:
                        self.log(f"[终极安全-拦截]: 总分={base_score:.3f} 顶部={score_top:.2f} 右下={score_bot:.2f} pos=({x},{y}) scale={scale:.3f}")

            # 保存最终截图用于调试（仅调试模式开启时）
            _debug_enabled = False
            if hasattr(self, "is_debug_screenshots_enabled"):
                _debug_enabled = self.is_debug_screenshots_enabled()
            if _debug_enabled:
                import os as _os
                _debug_dir = _os.path.join(APP_DIR, "debug", "ultimate_safe")
                _os.makedirs(_debug_dir, exist_ok=True)
                _stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time()*1000)%1000:03d}"
                # 画标注：用最后一次 scale 的 points
                _annotated = screen_bgr.copy()
                for _px, _py, _pw, _ph, _ps in points:
                    cv2.rectangle(_annotated, (_px, _py), (_px+_pw, _py+_ph), (0, 255, 0), 2)
                    cv2.putText(_annotated, f"{scale:.2f}:{_ps:.2f}", (_px, _py-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                _path = _os.path.join(_debug_dir, f"{_stamp}_annotated.png")
                cv2.imwrite(_path, _annotated)
                _path_raw = _os.path.join(_debug_dir, f"{_stamp}_raw.png")
                cv2.imwrite(_path_raw, screen_bgr)
                self.log(f"[终极安全] 保存调试截图: {_path} 候选总数={len(points)}")

            return None
        except Exception as e:
            self.log(f"ultimate_safe 异常: {e}")
            return None
    def wait_for_image_ultimate_safe(self, main_path, anti_path, region=None, main_threshold=0.80, anti_threshold=0.65, timeout=3, interval=0.2, mask_areas=None, top_threshold=0.75, bot_threshold=0.85):
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_ultimate_safe(main_path, anti_path, region, main_threshold, anti_threshold, mask_areas=mask_areas, top_threshold=top_threshold, bot_threshold=bot_threshold)
            if pos: return pos
            time.sleep(interval)
        return None

    def find_new_consumable_car_strict(self, region=None):
        """两步法识别目标车卡（多线程并行版）：
        Step 1: 并行全屏跑 newCC.png 找候选车卡
        Step 2: 串行对每个候选内部固定位置验 NEW 角标 + 等级标签
        保留 multi-scale + gray/edge 兜底。
        """
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)

            # v1.2.11.3: 缩放比缓存——前 2 辆强制全量搜索（不同车最佳 scale 可能不同），
            # 第 3 辆起只搜缓存附近 5 个 scale，耗时从 ~5s 降到 <1s。
            full_count = getattr(self, "_strict_car_full_count", 0)
            cached_scale = getattr(self, "_strict_car_cached_scale", None)
            if cached_scale and full_count >= 4:
                scales = [round(cached_scale * f, 3) for f in (0.95, 0.98, 1.0, 1.02, 1.05)]
                scales = [s for s in scales if 0.35 <= s <= 1.8]
            else:
                scales = []
                for s in self.get_scales_to_try(fast_mode=False):
                    if s not in scales:
                        scales.append(s)
                for s in [1.0, 0.98, 1.02, 0.95, 1.05]:
                    if s not in scales:
                        scales.append(s)

            profile = get_recognition_profile(self, "cj.strict_new_car")
            MAIN_THRESHOLD = float(profile.get("main_threshold", 0.82))
            MAIN_GRAY_THRESHOLD = float(profile.get("gray_threshold", 0.60))
            MAIN_EDGE_THRESHOLD = float(profile.get("edge_threshold", 0.18))
            MAIN_FALLBACK_MIN = float(profile.get("main_fallback_min", 0.66))
            TAG_THRESHOLD = float(profile.get("tag_threshold", 0.80))
            CLS_THRESHOLD = float(profile.get("class_threshold", 0.80))
            TAG_PAD = 4
            CLS_PAD = 4

            # 动态计算 TAG 和 CLS 在 newCC.png 中的相对位置
            _cls_img = self.config.get("class_image", "classS2829.png")

            # 加载原始模板（scale=1.0）用来自动定位 TAG/CLS 位置
            _ref_tpl, _ = self.get_scaled_template("newCC.png", 1.0)
            _ref_tag, _ = self.get_scaled_template("newcartag.png", 1.0)
            _ref_cls, _ = self.get_scaled_template(_cls_img, 1.0)

            if _ref_tpl is not None and _ref_tag is not None:
                _r = cv2.matchTemplate(_ref_tpl, _ref_tag, cv2.TM_CCOEFF_NORMED)
                _, _, _, _tl = cv2.minMaxLoc(_r)
                TAG_REL_X_RATIO = _tl[0] / _ref_tpl.shape[1]
                TAG_REL_Y_RATIO = _tl[1] / _ref_tpl.shape[0]
            else:
                TAG_REL_X_RATIO = 260.0 / 314.0
                TAG_REL_Y_RATIO = 169.0 / 236.0

            if _ref_tpl is not None and _ref_cls is not None:
                _r2 = cv2.matchTemplate(_ref_tpl, _ref_cls, cv2.TM_CCOEFF_NORMED)
                _, _, _, _cl = cv2.minMaxLoc(_r2)
                CLS_REL_X_RATIO = _cl[0] / _ref_tpl.shape[1]
                CLS_REL_Y_RATIO = _cl[1] / _ref_tpl.shape[0]
            else:
                CLS_REL_X_RATIO = 228.0 / 314.0
                CLS_REL_Y_RATIO = 201.0 / 236.0

            self.log(f"[StrictCar] TAG ratio=({TAG_REL_X_RATIO:.4f},{TAG_REL_Y_RATIO:.4f}) CLS ratio=({CLS_REL_X_RATIO:.4f},{CLS_REL_Y_RATIO:.4f})")

            # === Step 0: 预计算所有 scaled template + mask ===
            scale_data = {}
            _load_debug_count = 0
            for scale in scales:
                main_tpl, main_path = self.get_scaled_template("newCC.png", scale)
                tag_tpl, tag_path = self.get_scaled_template("newcartag.png", scale)
                class_tpl, cls_path = self.get_scaled_template(_cls_img, scale)
                if _load_debug_count == 0:
                    self.log(f"[StrictCar-Load] newCC.png path={main_path} shape={main_tpl.shape if main_tpl is not None else None}")
                    self.log(f"[StrictCar-Load] newcartag.png path={tag_path} shape={tag_tpl.shape if tag_tpl is not None else None}")
                    self.log(f"[StrictCar-Load] {_cls_img} path={cls_path} shape={class_tpl.shape if class_tpl is not None else None}")
                    _load_debug_count = 1
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

                border_px_cc = max(8, int(min(h_m, w_m) * 0.06))
                main_mask_cc = np.ones((h_m, w_m), dtype=np.uint8) * 255
                main_mask_cc[:border_px_cc, :] = 0
                main_mask_cc[-border_px_cc:, :] = 0
                main_mask_cc[:, :border_px_cc] = 0
                main_mask_cc[:, -border_px_cc:] = 0

                scale_data[scale] = {
                    'main_tpl': main_tpl,
                    'tag_tpl': tag_tpl,
                    'class_tpl': class_tpl,
                    'main_mask': main_mask_cc,
                    'h_m': h_m, 'w_m': w_m,
                    'h_t': h_t, 'w_t': w_t,
                    'h_c': h_c, 'w_c': w_c,
                    'tag_rel_x': int(w_m * TAG_REL_X_RATIO),
                    'tag_rel_y': int(h_m * TAG_REL_Y_RATIO),
                    'cls_rel_x': int(w_m * CLS_REL_X_RATIO),
                    'cls_rel_y': int(h_m * CLS_REL_Y_RATIO),
                    'main_res_max': 0.0,  # for debug
                }

            if not scale_data:
                return None

            # === Step 1: 并行 matchTemplate ===
            def _match_one_scale(item):
                scale, sd = item
                try:
                    res = cv2.matchTemplate(screen_bgr, sd['main_tpl'], cv2.TM_CCOEFF_NORMED, mask=sd['main_mask'])
                    _, max_val, _, max_loc = cv2.minMaxLoc(res)
                    locs = np.where(res >= MAIN_FALLBACK_MIN)
                    raw_points = [(int(x), int(y), float(res[y, x])) for x, y in zip(*locs[::-1])]
                    raw_points.sort(key=lambda b: -b[2])
                    nms_input = [(px, py, sd['w_m'], sd['h_m'], ps) for px, py, ps in raw_points]
                    candidates = [(c[0], c[1], c[4]) for c in self._nms_iou(nms_input, iou_threshold=0.3)]
                    return (scale, candidates, float(max_val), (int(max_loc[0]), int(max_loc[1])))
                except Exception:
                    return (scale, [], 0.0, (0, 0))

            max_workers = min(len(scale_data), max(1, (os.cpu_count() or 4) // 2))  # v1.2.10.6: cpu-1 -> cpu//2，留更多核心给游戏
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                parallel_results = list(ex.map(_match_one_scale, scale_data.items()))

            # 更新 debug 用的 max score
            for scale, candidates, max_val, max_loc in parallel_results:
                if scale in scale_data:
                    scale_data[scale]['main_res_max'] = max_val
                    scale_data[scale]['main_res_max_loc'] = max_loc
                self.log(
                    f"[StrictCar-Step1] scale={scale:.3f} max_score={max_val:.4f} "
                    f"candidates={len(candidates)} threshold={MAIN_THRESHOLD} fallback={MAIN_FALLBACK_MIN}"
                )

            # 按最佳候选分数降序
            parallel_results.sort(
                key=lambda r: max((c[2] for c in r[1]), default=0),
                reverse=True
            )

            # === Step 2: 串行验证 ===
            valid_candidates = []
            debug_saved = 0

            for scale, candidates, max_val, max_loc in parallel_results:
                sd = scale_data[scale]
                main_tpl = sd['main_tpl']
                tag_tpl = sd['tag_tpl']
                class_tpl = sd['class_tpl']
                h_m, w_m = sd['h_m'], sd['w_m']
                h_t, w_t = sd['h_t'], sd['w_t']
                h_c, w_c = sd['h_c'], sd['w_c']
                tag_rel_x = sd['tag_rel_x']
                tag_rel_y = sd['tag_rel_y']
                cls_rel_x = sd['cls_rel_x']
                cls_rel_y = sd['cls_rel_y']

                if not candidates:
                    if debug_saved < 3:
                        debug_saved += 1
                        self._save_strict_car_simple(
                            f"no_newcc_scale_{scale:.3f}",
                            screen_bgr=screen_bgr,
                            meta={
                                "reason": "全屏未找到 newCC 候选",
                                "scale": float(scale),
                                "max_newcc_score": float(max_val),
                                "main_threshold": float(MAIN_THRESHOLD),
                                "fallback_min": float(MAIN_FALLBACK_MIN),
                            },
                            anno={
                                "title": f"缩放{scale:.3f} 无 newCC 候选 (最高{max_val:.3f})",
                                "tag_boxes": [],
                                "class_boxes": [],
                                "max_tag_loc": (max_loc[0], max_loc[1], int(w_m), int(h_m), float(max_val)),
                            },
                        )
                    continue

                # 灰度/边缘兜底用的模板特征：每个 scale 只算一次（v1.2.10.1：原代码在每个候选循环内重复 cvtColor+Canny）
                tpl_gray_cache = None
                tpl_edge_cache = None

                for car_x, car_y, car_score in candidates:
                    # --- 2a: 判断车卡是否可信（彩色优先，灰度+边缘兜底）---
                    is_card_valid = False
                    gray_score = 0.0
                    edge_score = 0.0

                    if car_score >= MAIN_THRESHOLD:
                        is_card_valid = True
                    elif car_score >= MAIN_FALLBACK_MIN:
                        try:
                            patch = screen_bgr[car_y:car_y + h_m, car_x:car_x + w_m]
                            if patch.shape[:2] == main_tpl.shape[:2]:
                                if tpl_gray_cache is None:
                                    tpl_gray_cache = cv2.cvtColor(main_tpl, cv2.COLOR_BGR2GRAY)
                                    tpl_edge_cache = cv2.Canny(tpl_gray_cache, 60, 160)
                                cand_gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
                                _, gray_score, _, _ = cv2.minMaxLoc(
                                    cv2.matchTemplate(cand_gray, tpl_gray_cache, cv2.TM_CCOEFF_NORMED))
                                cand_edge = cv2.Canny(cand_gray, 60, 160)
                                _, edge_score, _, _ = cv2.minMaxLoc(
                                    cv2.matchTemplate(cand_edge, tpl_edge_cache, cv2.TM_CCOEFF_NORMED))
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

                    # --- 2c: 在车卡内部固定位置验等级标签 ---
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
                            f"[StrictCar] 车卡({car_x},{car_y}) 等级标签不足: "
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

                    off_x = region[0] if region else 0
                    off_y = region[1] if region else 0
                    click_x = car_x + w_m // 2 + off_x
                    click_y = car_y + h_m // 2 + off_y
                    candidate_meta = {
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
                    valid_candidates.append((
                        int(click_x), int(click_y), float(effective_score), candidate_meta,
                        (int(tx0), int(ty0), int(w_t), int(h_t), float(tag_score)),
                        (int(cx0), int(cy0), int(w_c), int(h_c), float(cls_score)),
                    ))

            if valid_candidates:
                # 视觉顺序优先，而不是“谁的模板分最高就选谁”。否则当前全新车分数稍低时
                # 会直接跳到下一辆。先按列分组，再在列内从上到下；同一卡的多尺度重复
                # 由位置顺序稳定落在一起。
                ordered = self._sort_column_first(valid_candidates, x_idx=0, y_idx=1, tolerance=70)
                x, y, _, selected_meta, tag_box, class_box = ordered[0]
                self.last_strict_car_meta = selected_meta
                car_x = selected_meta["card_x"]
                car_y = selected_meta["card_y"]
                w_m = selected_meta["card_w"]
                h_m = selected_meta["card_h"]
                scale = selected_meta["scale"]
                car_score = selected_meta["car_score"]
                tag_score = selected_meta["tag_score"]
                cls_score = selected_meta["class_score"]
                gray_score = selected_meta["gray_score"]
                edge_score = selected_meta["edge_score"]
                off_x = region[0] if region else 0
                off_y = region[1] if region else 0
                self.last_strict_car_click_points = [
                    (int(x), int(y)),
                    (int(car_x + int(w_m * 0.5) + off_x), int(car_y + int(h_m * 0.4) + off_y)),
                    (int(car_x + int(w_m * 0.5) + off_x), int(car_y + int(h_m * 0.6) + off_y)),
                ]
                self.log(
                    f"[StrictCar] 最终锁定目标车: car=({car_x},{car_y}) "
                    f"car={car_score:.3f} tag={tag_score:.3f} cls={cls_score:.3f} "
                    f"gray={gray_score:.3f} edge={edge_score:.3f} scale={scale:.3f} "
                    f"视觉顺序=1/{len(ordered)}"
                )
                if debug_saved < 5:
                    self._save_strict_car_simple(
                        f"locked_visual_first_scale_{scale:.3f}",
                        screen_bgr=screen_bgr,
                        meta=selected_meta,
                        anno={
                            "title": f"视觉首车 car={car_score:.2f} tag={tag_score:.2f} cls={cls_score:.2f}",
                            "tag_boxes": [tag_box],
                            "class_boxes": [class_box],
                            "max_tag_loc": (int(car_x), int(car_y), int(w_m), int(h_m), float(car_score)),
                        },
                    )
                # v1.2.11.3: 缓存最佳缩放比，前 2 辆全量搜索后第 3 辆起用缓存
                self._strict_car_cached_scale = scale
                self._strict_car_full_count = getattr(self, "_strict_car_full_count", 0) + 1
                return (x, y)

            # v1.2.11.3: 缓存 scale 搜索失败 → 回退全量搜索（仅一次机会）
            if cached_scale:
                self.log(f"[StrictCar] 缓存 scale={cached_scale:.3f} 未命中，回退全量搜索")
                self._strict_car_cached_scale = None
                return self.find_new_consumable_car_strict(region=region)

            self.log("[StrictCar] 本帧未找到达标目标车，返回 None（由翻页逻辑继续查找）")
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
        """等待目标车，并用相邻帧空间一致性过滤菜单动画/hover 造成的瞬时误判。

        v1.2.11.3: 双层超时——
        - 确认窗口 timeout：首次找到目标后开始计时，用于连续帧确认
        - 绝对超时 absolute_timeout：无论是否找到目标，总时间上限，
          防止“永远找不到目标”时无限循环（如超抽次数>买车数）。
        """
        profile = get_recognition_profile(self, "cj.strict_new_car")
        required = max(1, int(profile.get("confirm_frames", 2)))
        max_distance = max(10, int(profile.get("confirm_distance", 70)))
        strong_threshold = float(profile.get("strong_threshold", 0.86))
        absolute_start = time.time()
        absolute_timeout = 15.0   # 总时间上限：无目标时最多 3 轮全量搜索
        confirm_start = None      # 首次找到目标后才开始确认倒计时
        last_pos = None
        confirmed = 0
        first_visual_pos = None
        first_visual_score = 0.0
        while self.is_running:
            # 绝对超时：无论是否找到目标，总时间到了就退出
            if time.time() - absolute_start >= absolute_timeout:
                self.log(f"[StrictCar-Confirm] 绝对超时 {absolute_timeout:.0f}s，退出等待")
                break
            # 确认窗口超时：找到目标后开始计时
            if confirm_start is not None and time.time() - confirm_start >= timeout:
                break
            pos = self.find_new_consumable_car_strict(region=self.regions["全界面"])
            if pos:
                meta = getattr(self, "last_strict_car_meta", None) or {}
                confidence = min(
                    float(meta.get("tag_score", 0.0) or 0.0),
                    float(meta.get("class_score", 0.0) or 0.0),
                    max(
                        float(meta.get("car_score", 0.0) or 0.0),
                        float(meta.get("gray_score", 0.0) or 0.0),
                    ),
                )
                if first_visual_pos is None:
                    first_visual_pos = pos
                    first_visual_score = confidence
                    confirm_start = time.time()   # 首次找到目标，确认窗口从此刻开始
                if last_pos and abs(pos[0] - last_pos[0]) <= max_distance and abs(pos[1] - last_pos[1]) <= max_distance:
                    confirmed += 1
                else:
                    confirmed = 1
                last_pos = pos
                self.log(
                    f"[StrictCar-Confirm] pos={pos} 连续帧={confirmed}/{required} "
                    f"综合最低分={confidence:.3f}"
                )
                if confirmed >= required:
                    return pos
            else:
                confirmed = 0
                last_pos = None
            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)

        # 超时前若出现过一次非常强的候选，允许保守回退，避免低帧率机器永久漏车。
        if first_visual_pos and first_visual_score >= strong_threshold:
            self.log(
                f"[StrictCar-Confirm] 连续帧不足但视觉首车为强候选，保守采用: "
                f"pos={first_visual_pos} score={first_visual_score:.3f}"
            )
            return first_visual_pos
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
            if screen_bgr is None:
                self.log(f"[GrayMatch] 截图失败: {template_path} | region={region}")
                return None
            screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)
            effective_threshold = self.get_calibrated_gray_threshold(threshold)

            tpl_gray_raw = self.load_template_gray(template_path)
            if tpl_gray_raw is None:
                self.log(f"[GrayMatch] 模板加载失败: {template_path}")
                self.capture_diagnostic_snapshot(f"no_template_{template_path}", region=region, image_bgr=screen_bgr, reason="模板加载失败", level="ERROR")
                return None

            best_score = 0.0
            best_scale = 0.0

            for scale in scales_to_try:
                tpl_gray = tpl_gray_raw
                if scale != 1.0:
                    tpl_gray = cv2.resize(tpl_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

                h, w = tpl_gray.shape[:2]
                if h < 5 or w < 5 or h > screen_gray.shape[0] or w > screen_gray.shape[1]:
                    continue

                res = cv2.matchTemplate(screen_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val > best_score:
                    best_score = max_val
                    best_scale = scale
                if max_val >= effective_threshold:
                    self.log(f"[GrayMatch] 命中: {template_path} | 模式: 原图 | 灰度得分: {max_val:.3f} (阈值 {effective_threshold:.3f}) | 缩放比: {scale:.3f}")
                    return (
                        max_loc[0] + w // 2 + (region[0] if region else 0),
                        max_loc[1] + h // 2 + (region[1] if region else 0),
                    )

                if invert_mode:
                    tpl_inv = 255 - tpl_gray
                    res_inv = cv2.matchTemplate(screen_gray, tpl_inv, cv2.TM_CCOEFF_NORMED)
                    _, max_val_inv, _, max_loc_inv = cv2.minMaxLoc(res_inv)
                    if max_val_inv > best_score:
                        best_score = max_val_inv
                        best_scale = scale
                    if max_val_inv >= effective_threshold:
                        self.log(f"[GrayMatch] 命中: {template_path} | 模式: 反相 | 灰度得分: {max_val_inv:.3f} (阈值 {effective_threshold:.3f}) | 缩放比: {scale:.3f}")
                        return (
                            max_loc_inv[0] + w // 2 + (region[0] if region else 0),
                            max_loc_inv[1] + h // 2 + (region[1] if region else 0),
                        )

            self.log(f"[GrayMatch] 未命中: {template_path} | 最高分: {best_score:.3f} (阈值 {effective_threshold:.3f}) | 最佳缩放: {best_scale:.3f} | 截图均值: {screen_bgr.mean():.1f} | 区域: {region}")
            debug_path = self.capture_diagnostic_snapshot(template_path, region=region, image_bgr=screen_bgr, reason="未命中", level="WARN", threshold=effective_threshold, score=best_score, meta={"best_scale": round(best_scale, 3)})
            if debug_path:
                self.log(f"[GrayMatch] 调试截图: {debug_path}")
            return None
        except Exception as e:
            self.log(f"find_image_gray 异常: {e}")
            return None
    def find_any_image_gray(self, image_list, region=None, threshold=0.75, fast_mode=True, invert_mode=False, return_name=False):
        """
        纯灰度多图查找,支持多分辨率缩放 + 可选翻转模式
        参数:
            image_list (list): 模板图片路径列表,如 ["a.png", "b.png", "c.png"]
            region (tuple|list|None): 搜索区域,格式通常为 (x, y, w, h),None 表示全屏/默认区域
            threshold (float): 匹配阈值,范围通常 0~1,越高越严格
            fast_mode (bool): 是否使用快速缩放搜索模式,True=较少缩放比,False=更多缩放比
            invert_mode (bool): 是否启用翻转模式,True 时会同时匹配原图和反相图(白底黑字 / 黑底白字都能识别)
            return_name (bool): 为 True 时返回 (x, y, img_path),为 False 时返回 (x, y)
        返回:
            tuple|None:
                - return_name=False: 找到任意一张时返回匹配中心点坐标 (x, y),找不到返回 None
                - return_name=True: 找到时返回 (x, y, img_path),找不到返回 None
        """
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)
            effective_threshold = self.get_calibrated_gray_threshold(threshold)

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
                    if max_val >= effective_threshold:
                        self.log(f"[GrayMatchAny] 命中: {img_path} | 模式: 原图 | 灰度得分: {max_val:.3f} (阈值 {effective_threshold:.3f}) | 缩放比: {scale:.3f}")
                        cx = max_loc[0] + w // 2 + (region[0] if region else 0)
                        cy = max_loc[1] + h // 2 + (region[1] if region else 0)
                        return (cx, cy, img_path) if return_name else (cx, cy)

                    # ==============================
                    # 【新增】翻转模式:反相模板匹配
                    # ==============================
                    if invert_mode:
                        tpl_inv = 255 - tpl_gray
                        res_inv = cv2.matchTemplate(screen_gray, tpl_inv, cv2.TM_CCOEFF_NORMED)
                        _, max_val_inv, _, max_loc_inv = cv2.minMaxLoc(res_inv)
                        if max_val_inv >= effective_threshold:
                            self.log(f"[GrayMatchAny] 命中: {img_path} | 模式: 反相 | 灰度得分: {max_val_inv:.3f} (阈值 {effective_threshold:.3f}) | 缩放比: {scale:.3f}")
                            cx = max_loc_inv[0] + w // 2 + (region[0] if region else 0)
                            cy = max_loc_inv[1] + h // 2 + (region[1] if region else 0)
                            return (cx, cy, img_path) if return_name else (cx, cy)

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

    def _nms_iou(self, candidates, iou_threshold=0.3):
        """IoU-based NMS for candidate deduplication.
        candidates: list of tuples, first 5 elements must be (x, y, w, h, score, ...)
        Returns deduplicated list sorted by score descending.
        """
        if not candidates:
            return []
        candidates.sort(key=lambda c: c[4], reverse=True)
        keep = []
        suppressed = set()
        for i, c1 in enumerate(candidates):
            if i in suppressed:
                continue
            keep.append(c1)
            x1, y1, w1, h1 = c1[0], c1[1], c1[2], c1[3]
            for j in range(i + 1, len(candidates)):
                if j in suppressed:
                    continue
                c2 = candidates[j]
                x2, y2, w2, h2 = c2[0], c2[1], c2[2], c2[3]
                ix1 = max(x1, x2)
                iy1 = max(y1, y2)
                ix2 = min(x1 + w1, x2 + w2)
                iy2 = min(y1 + h1, y2 + h2)
                if ix2 <= ix1 or iy2 <= iy1:
                    continue
                inter = (ix2 - ix1) * (iy2 - iy1)
                area1 = w1 * h1
                area2 = w2 * h2
                denom = area1 + area2 - inter
                iou = inter / denom if denom > 0 else 0
                if iou > iou_threshold:
                    suppressed.add(j)
        return keep

    def find_combo(self, main_path, sub_path, region=None,
                   main_threshold=0.60, sub_threshold=0.70, final_threshold=0.72,
                   use_gray_only=False, use_four_dim=True, sub_independent_scale=True,
                   fast_mode=True, max_candidates=15, mask_areas=None):
        """统一组合匹配方法：主图匹配 → IoU NMS → 子元素验证。

        模式：
        - use_gray_only=True,  use_four_dim=False: 灰度快速/稳定模式
        - use_gray_only=False, use_four_dim=False: 基础彩色模式
        - use_gray_only=False, use_four_dim=True:  四维多维度模式（含灰度预筛）

        返回: (x, y) 或 None
        """
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region, mask_areas=mask_areas)
            if screen_bgr is None:
                return None

            screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
            screen_edge = self.to_edge_image(screen_bgr) if use_four_dim else None

            if use_gray_only:
                screen_main = screen_gray
            else:
                screen_main = screen_bgr

            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)
            if sub_independent_scale:
                # 独立缩放但不能无限缩小——限制在合理范围内
                # 避免小模板(如28x31的liketag)缩到极小尺寸后产生假阳性
                full_scales = self.get_scales_to_try(fast_mode=False)
                sub_scales = [s for s in full_scales if s >= 0.35]
            else:
                sub_scales = scales_to_try

            all_candidates = []

            for scale in scales_to_try:
                main_tpl_c, _ = self.get_scaled_template(main_path, scale)
                if main_tpl_c is None:
                    continue

                h_m, w_m = main_tpl_c.shape[:2]
                if h_m < 5 or w_m < 5 or h_m > screen_main.shape[0] or w_m > screen_main.shape[1]:
                    continue

                if use_gray_only:
                    main_tpl = cv2.cvtColor(main_tpl_c, cv2.COLOR_BGR2GRAY)
                else:
                    main_tpl = main_tpl_c

                res_main = cv2.matchTemplate(screen_main, main_tpl, cv2.TM_CCOEFF_NORMED)

                if use_four_dim:
                    # 四维模式：argpartition top 50 + 低分预筛
                    flat = res_main.ravel()
                    if flat.size == 0:
                        continue
                    top_k = min(50, flat.size)
                    idxs = np.argpartition(flat, -top_k)[-top_k:]
                    for idx in idxs:
                        y, x = np.unravel_index(idx, res_main.shape)
                        score = float(res_main[y, x])
                        if score < max(0.55, main_threshold - 0.12):
                            continue
                        all_candidates.append((int(x), int(y), w_m, h_m, score, scale))
                else:
                    # 非四维模式：阈值过滤
                    locs = np.where(res_main >= main_threshold)
                    for x, y in zip(*locs[::-1]):
                        score = float(res_main[y, x])
                        all_candidates.append((int(x), int(y), w_m, h_m, score, scale))

            if not all_candidates:
                self.log(f"[ComboMatch] 未命中: {main_path}+{sub_path} | 无候选 (主图阈值 {main_threshold}) | 截图均值: {screen_bgr.mean():.1f} | 区域: {region}")
                self.capture_diagnostic_snapshot(f"combo_{main_path}+{sub_path}", region=region, image_bgr=screen_bgr, reason="无候选", level="WARN", threshold=main_threshold, meta={"sub_path": sub_path})
                return None

            # IoU NMS 去重（跨所有缩放比）
            all_candidates = self._nms_iou(all_candidates, iou_threshold=0.3)

            # 收集所有通过阈值的候选，返回 final_score 最高的
            best_result = None
            best_final_score = -1.0

            for x, y, w_m, h_m, base_score, scale in all_candidates[:max_candidates]:
                main_tpl_c, _ = self.get_scaled_template(main_path, scale)
                if main_tpl_c is None:
                    continue

                if use_four_dim:
                    # === 四维打分 ===
                    main_tpl_gray = self.to_gray_image(main_tpl_c)
                    main_tpl_edge = self.to_edge_image(main_tpl_c)

                    roi_bgr = screen_bgr[y:y + h_m, x:x + w_m]
                    roi_gray = screen_gray[y:y + h_m, x:x + w_m]
                    roi_edge = screen_edge[y:y + h_m, x:x + w_m]

                    if roi_bgr.shape[:2] != main_tpl_c.shape[:2]:
                        continue

                    color_score = self.match_template_score(roi_bgr, main_tpl_c)
                    gray_score = self.match_template_score(roi_gray, main_tpl_gray)
                    edge_score = self.match_template_score(roi_edge, main_tpl_edge)

                    roi_center = self.crop_center_ratio(roi_bgr, ratio=0.6)
                    tpl_center = self.crop_center_ratio(main_tpl_c, ratio=0.6)
                    center_score = self.match_template_score(roi_center, tpl_center)

                    # 子元素独立缩放验证
                    pad = 5
                    sub_roi = screen_bgr[
                        max(0, y - pad):min(screen_bgr.shape[0], y + h_m + pad),
                        max(0, x - pad):min(screen_bgr.shape[1], x + w_m + pad),
                    ]
                    like_score = 0.0
                    # 子元素缩放绑定主图缩放：±0.15 范围内搜索
                    narrow_sub_scales = [s for s in sub_scales if abs(s - scale) <= 0.15]
                    if not narrow_sub_scales:
                        narrow_sub_scales = [scale]
                    for sub_scale in narrow_sub_scales:
                        sub_tpl_c, _ = self.get_scaled_template(sub_path, sub_scale)
                        if sub_tpl_c is None:
                            continue
                        if sub_tpl_c.shape[0] > sub_roi.shape[0] or sub_tpl_c.shape[1] > sub_roi.shape[1]:
                            continue
                        curr = self.match_template_score(sub_roi, sub_tpl_c)
                        if curr > like_score:
                            like_score = curr

                    if like_score < sub_threshold:
                        continue

                    final_score = (
                        color_score * 0.35 +
                        gray_score * 0.25 +
                        edge_score * 0.05 +
                        center_score * 0.20 +
                        like_score * 0.15
                    )

                    if final_score >= final_threshold and final_score > best_final_score:
                        cx = x + w_m // 2 + (region[0] if region else 0)
                        cy = y + h_m // 2 + (region[1] if region else 0)
                        best_final_score = final_score
                        best_result = (cx, cy)
                        self.log(
                            f"[ComboMatch] 候选: {main_path}+{sub_path} | "
                            f"综合: {final_score:.3f} | 彩色: {color_score:.3f} | "
                            f"灰度: {gray_score:.3f} | 边缘: {edge_score:.3f} | "
                            f"中心: {center_score:.3f} | 标签: {like_score:.3f} | "
                            f"缩放: {scale:.3f}"
                        )
                else:
                    # === 非四维：直接验证子元素 ===
                    sub_tpl_c, _ = self.get_scaled_template(sub_path, scale)
                    if sub_tpl_c is None:
                        continue

                    h_s, w_s = sub_tpl_c.shape[:2]
                    pad = 5
                    sub_roi = screen_main[
                        max(0, y - pad):min(screen_main.shape[0], y + h_m + pad),
                        max(0, x - pad):min(screen_main.shape[1], x + w_m + pad),
                    ]
                    if sub_roi.shape[0] < h_s or sub_roi.shape[1] < w_s:
                        continue

                    if use_gray_only:
                        sub_tpl = cv2.cvtColor(sub_tpl_c, cv2.COLOR_BGR2GRAY)
                    else:
                        sub_tpl = sub_tpl_c

                    res_sub = cv2.matchTemplate(sub_roi, sub_tpl, cv2.TM_CCOEFF_NORMED)
                    sub_score = float(cv2.minMaxLoc(res_sub)[1])

                    final_score = base_score * 0.70 + sub_score * 0.30
                    if final_score >= final_threshold and final_score > best_final_score:
                        cx = x + w_m // 2 + (region[0] if region else 0)
                        cy = y + h_m // 2 + (region[1] if region else 0)
                        best_final_score = final_score
                        best_result = (cx, cy)
                        self.log(
                            f"[ComboMatch] 候选: {main_path}+{sub_path} | "
                            f"主图: {base_score:.3f} | 元素: {sub_score:.3f} | "
                            f"缩放: {scale:.3f}"
                        )

            if best_result:
                self.log(f"[ComboMatch] 最终选中: final_score={best_final_score:.3f}")
            else:
                self.log(f"[ComboMatch] 未命中: {main_path}+{sub_path} | 有候选但未过终审 (终审阈值 {final_threshold}) | 候选数: {len(all_candidates)} | 区域: {region}")
                self.capture_diagnostic_snapshot(f"combo_{main_path}+{sub_path}", region=region, image_bgr=screen_bgr, reason="有候选但未过终审", level="WARN", threshold=final_threshold, meta={"candidate_count": len(all_candidates), "sub_path": sub_path})
            return best_result
        except Exception as e:
            self.log(f"find_combo 异常: {e}")
            return None

    # ==========================================
    # 以下为从上游同步的新增方法
    # ==========================================

    def get_calibrated_gray_threshold(self, threshold):
        """根据校准结果动态调整灰度匹配阈值。"""
        calib = getattr(self, "match_calibration", {}) or {}
        offset = float(calib.get("gray_threshold_offset", 0.0) or 0.0)
        adjusted = float(threshold) + offset
        return max(0.50, min(0.98, adjusted))

    def find_image_smart(self, template_path, primary_region=None, fallback_region=None, threshold=0.75, fast_mode=True):
        """先搜主区域，失败后回退到备用区域。"""
        if primary_region:
            pos = self.find_image(template_path, region=primary_region, threshold=threshold, fast_mode=fast_mode)
            if pos:
                return pos
        if fallback_region:
            return self.find_image(template_path, region=fallback_region, threshold=threshold, fast_mode=fast_mode)
        return None

    def wait_for_image_with_element(self, main_path, sub_path, region=None, threshold=0.85, timeout=30, interval=0.4, fast_mode=True):
        """等待组合匹配命中（find_image_with_element 的 wait 封装）。"""
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_with_element(main_path, sub_path, region=region, threshold=threshold, fast_mode=fast_mode)
            if pos:
                return pos
            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)
        return None

    def wait_for_image_with_element_stable(self, main_path, sub_path, region=None, main_threshold=0.60, verify_threshold=0.72, sub_threshold=0.70, max_candidates=15, timeout=30, interval=0.4):
        """等待 stable 组合匹配命中。"""
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_with_element_stable(
                main_path, sub_path, region=region,
                main_threshold=main_threshold, verify_threshold=verify_threshold,
                sub_threshold=sub_threshold, max_candidates=max_candidates,
            )
            if pos:
                return pos
            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)
        return None

    def wait_for_image_with_element_fast(self, main_path, sub_path, region=None, threshold=0.70, sub_threshold=0.70, timeout=30, interval=0.4):
        """等待 fast 组合匹配命中。"""
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_with_element_fast(
                main_path, sub_path, region=region,
                threshold=threshold, sub_threshold=sub_threshold,
            )
            if pos:
                return pos
            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)
        return None

    def wait_for_any_image_transparent(self, image_list, region=None, threshold=0.70, timeout=30, interval=0.4, fast_mode=True):
        """等待任意透明模板出现。"""
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_any_image_transparent(image_list, region, threshold, fast_mode)
            if pos:
                return pos
            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)
        return None

    def find_skill_car_from_like_tag(self, region=None):
        """反向定位法：先全屏找 liketag，再反推车卡位置。"""
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            scales_to_try = self.get_scales_to_try(fast_mode=False)
            best_debug = None

            for scale in scales_to_try:
                car_tpl, _ = self.get_scaled_template("skillcar.png", scale)
                tag_tpl, _ = self.get_scaled_template("liketag.png", scale)
                if car_tpl is None or tag_tpl is None:
                    continue

                h_c, w_c = car_tpl.shape[:2]
                h_t, w_t = tag_tpl.shape[:2]
                if h_c < 5 or w_c < 5 or h_t < 3 or w_t < 3:
                    continue
                if h_t > screen_bgr.shape[0] or w_t > screen_bgr.shape[1]:
                    continue

                tag_res = cv2.matchTemplate(screen_bgr, tag_tpl, cv2.TM_CCOEFF_NORMED)
                ys, xs = np.where(tag_res >= 0.70)
                tag_points = [(int(y), int(x), float(tag_res[y, x])) for y, x in zip(ys, xs)]
                tag_points.sort(key=lambda p: (p[0], p[1], -p[2]))
                checked_tags = set()

                for ty, tx, tag_score in tag_points[:80]:
                    key = (tx // 8, ty // 8)
                    if key in checked_tags:
                        continue
                    checked_tags.add(key)

                    sx1 = max(0, int(tx - w_c * 1.10))
                    sy1 = max(0, int(ty - h_c * 1.10))
                    sx2 = min(screen_bgr.shape[1], int(tx + w_t + w_c * 0.45))
                    sy2 = min(screen_bgr.shape[0], int(ty + h_t + h_c * 0.45))
                    search = screen_bgr[sy1:sy2, sx1:sx2]
                    if search.shape[0] < h_c or search.shape[1] < w_c:
                        continue

                    car_res = cv2.matchTemplate(search, car_tpl, cv2.TM_CCOEFF_NORMED)
                    _, car_score, _, car_loc = cv2.minMaxLoc(car_res)
                    card_x = sx1 + car_loc[0]
                    card_y = sy1 + car_loc[1]

                    rel_x = tx - card_x
                    rel_y = ty - card_y
                    if not (-int(w_c * 0.08) <= rel_x <= int(w_c * 1.08) and -int(h_c * 0.08) <= rel_y <= int(h_c * 1.08)):
                        best_debug = f"rel invalid tag:{tag_score:.3f} car:{car_score:.3f} rel:{rel_x},{rel_y} scale:{scale:.3f}"
                        continue
                    if car_score < 0.70:
                        best_debug = f"car low tag:{tag_score:.3f} car:{car_score:.3f} scale:{scale:.3f}"
                        continue

                    click_x = card_x + w_c // 2 + (region[0] if region else 0)
                    click_y = card_y + h_c // 2 + (region[1] if region else 0)
                    self.log(
                        f"[SkillCar] reverse hit: tag={tag_score:.3f} car={car_score:.3f} "
                        f"rel=({rel_x},{rel_y}) scale={scale:.3f}"
                    )
                    return (click_x, click_y)

            if best_debug:
                self.log(f"[SkillCar] reverse miss: {best_debug}")
            return None
        except Exception as e:
            self.log(f"find_skill_car_from_like_tag exception: {e}")
            return None

    def find_skill_car_with_like_tag(self, region=None, timeout=3.0, interval=0.25):
        """组合入口：先 multi 匹配，失败降级反向定位。"""
        profile = get_recognition_profile(
            self,
            "matcher.skillcar_like_combo",
            timeout=timeout,
            interval=interval,
        )
        start = time.time()
        while self.is_running and time.time() - start < profile["timeout"]:
            pos = self.find_image_with_element_multi(
                "skillcar.png",
                "liketag.png",
                region=region,
                fast_mode=profile["fast_mode"],
                main_threshold=profile["main_threshold"],
                like_threshold=profile["like_threshold"],
                final_threshold=profile["final_threshold"],
            )
            if pos:
                return pos

            pos = self.find_skill_car_from_like_tag(region=region)
            if pos:
                return pos

            time.sleep(profile["interval"])
        return None

    def find_new_tag_by_color(self, screen_bgr, tag_tpl, scale):
        """HSV 颜色预筛法：用黄色 HSV 范围先圈定"全新"标签候选，再模板精匹配。"""
        try:
            h_s, w_s = screen_bgr.shape[:2]
            hsv = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array([22, 80, 160]), np.array([42, 255, 255]))
            kernel = np.ones((3, 3), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            candidates = []
            tag_h, tag_w = tag_tpl.shape[:2]
            card_w = max(180, int(267 * scale))
            card_h = max(130, int(198 * scale))

            for cnt in contours:
                x, y, w, h = cv2.boundingRect(cnt)
                area = w * h
                if area < 80 or area > 6000:
                    continue
                if w < 12 or h < 8 or w > 90 or h > 70:
                    continue
                if w / max(h, 1) < 0.6:
                    continue

                pad = max(8, int(12 * scale))
                x1 = max(0, x - pad)
                y1 = max(0, y - pad)
                x2 = min(w_s, x + w + pad)
                y2 = min(h_s, y + h + pad)
                tag_roi = screen_bgr[y1:y2, x1:x2]
                tag_score = self.match_template_score(tag_roi, tag_tpl)
                if tag_score < 0.52:
                    continue

                card_x = int((x + w / 2) - card_w * 0.78)
                card_y = int((y + h / 2) - card_h * 0.78)
                card_x = max(0, min(card_x, w_s - card_w))
                card_y = max(0, min(card_y, h_s - card_h))
                center_x = card_x + card_w // 2
                center_y = card_y + card_h // 2

                candidates.append((tag_score, card_x, card_y, card_w, card_h, center_x, center_y, x, y, w, h))

            if not candidates:
                return []

            candidates.sort(key=lambda item: (-item[0], item[8], item[7]))
            return candidates
        except Exception as e:
            self.log(f"find_new_tag_by_color 异常: {e}")
            return []

    def validate_new_tag_grid_fallback(self, screen_bgr, tx, ty, tw, th):
        """标签位置合理性校验：检查标签左上方是否有白色车卡、左下方是否有橙色信息。"""
        try:
            h_s, w_s = screen_bgr.shape[:2]
            if tx < int(w_s * 0.20) or ty < int(h_s * 0.18) or ty > int(h_s * 0.92):
                return None

            wx1 = max(0, tx - 145)
            wy1 = max(0, ty - 105)
            wx2 = max(0, tx - 12)
            wy2 = max(0, ty - 8)
            white_roi = screen_bgr[wy1:wy2, wx1:wx2]
            if white_roi.size == 0:
                return None
            white_mask = (
                (white_roi[:, :, 0] > 185) &
                (white_roi[:, :, 1] > 185) &
                (white_roi[:, :, 2] > 185)
            )
            white_ratio = float(np.count_nonzero(white_mask)) / max(1, white_mask.size)
            if white_ratio < 0.18:
                return None

            ox1 = max(0, tx - 190)
            oy1 = max(0, ty - 12)
            ox2 = min(w_s, tx + 85)
            oy2 = min(h_s, ty + th + 44)
            orange_roi = screen_bgr[oy1:oy2, ox1:ox2]
            if orange_roi.size == 0:
                return None
            hsv = cv2.cvtColor(orange_roi, cv2.COLOR_BGR2HSV)
            orange_mask = cv2.inRange(hsv, np.array([8, 80, 140]), np.array([32, 255, 255]))
            orange_ratio = float(np.count_nonzero(orange_mask)) / max(1, orange_mask.size)
            if orange_ratio < 0.035:
                return None

            click_x = max(0, min(w_s - 1, tx - 60))
            click_y = max(0, min(h_s - 1, ty - 42))
            return click_x, click_y, white_ratio, orange_ratio
        except Exception as e:
            self.log(f"validate_new_tag_grid_fallback 异常: {e}")
            return None

    # =================================================================
    # skillcar 严格匹配：固定位置 liketag 验证
    # =================================================================

    def find_skill_car_strict(self, region=None):
        """严格匹配 skillcar 车卡（多线程并行版）：
        Step 1: 并行全屏跑 skillcar.png 找候选（限定缩放 0.40~1.20）
        Step 2: 每个候选内部右下象限区域验 liketag.png 或 drivingtag.png
        返回: (x, y) 或 None
        """
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            if screen_bgr is None:
                return None

            # 缩放范围
            base_scales = [1.0, 0.85, 0.75, 0.65, 0.55, 0.95, 0.90, 0.80, 0.70, 0.60, 0.50, 0.45, 0.40, 1.05, 1.10, 1.15, 1.20]
            scales = []
            for s in base_scales:
                if s not in scales:
                    scales.append(s)

            # 阈值常量
            MAIN_THRESHOLD = 0.75       # skillcar 彩色主阈值
            MAIN_FALLBACK_MIN = 0.50    # matchTemplate 预筛下限
            TAG_THRESHOLD = 0.75        # liketag 内部验阈值

            # liketag 搜索区域：右下象限
            TAG_X_MIN_RATIO = 0.65
            TAG_X_MAX_RATIO = 0.98
            TAG_Y_MIN_RATIO = 0.60
            TAG_Y_MAX_RATIO = 0.88

            # 等级标签反向校验：skill car 不应显示等级标签橙色条
            # 等级标签反向校验：skill car 不应显示目标等级标签
            _cls_img = "anti_class_S2829.png"  # 独立模板，不与方案 class_image 混用
            CLS_ANTI_THRESHOLD = 0.70
            CLS_Y_MIN_RATIO = 0.50      # 等级标签搜索区域：车卡下半部分

            # === Step 0: 预计算所有 scaled template + mask（线程安全）===
            scale_data = {}
            for scale in scales:
                main_tpl, _ = self.get_scaled_template("skillcar.png", scale)
                tag_tpl, _ = self.get_scaled_template("liketag.png", scale)
                drv_tpl, _ = self.get_scaled_template("drivingtag.png", scale)
                cls_anti_tpl, _ = self.get_scaled_template(_cls_img, scale)
                if main_tpl is None or tag_tpl is None:
                    continue
                h_m, w_m = main_tpl.shape[:2]
                h_t, w_t = tag_tpl.shape[:2]
                h_d, w_d = drv_tpl.shape[:2] if drv_tpl is not None else (0, 0)
                h_ca, w_ca = cls_anti_tpl.shape[:2] if cls_anti_tpl is not None else (0, 0)
                if h_m < 20 or w_m < 20 or h_m > screen_bgr.shape[0] or w_m > screen_bgr.shape[1]:
                    continue
                if h_t < 8 or w_t < 8:
                    continue

                # 创建边框 mask
                border_px = max(10, int(min(h_m, w_m) * 0.08))
                main_mask = np.ones((h_m, w_m), dtype=np.uint8) * 255
                main_mask[:border_px, :] = 0
                main_mask[-border_px:, :] = 0
                main_mask[:, :border_px] = 0
                main_mask[:, -border_px:] = 0

                # liketag 搜索区域偏移
                tag_x_start = int(w_m * TAG_X_MIN_RATIO)
                tag_x_end = int(w_m * TAG_X_MAX_RATIO)
                tag_y_start = int(h_m * TAG_Y_MIN_RATIO)
                tag_y_end = int(h_m * TAG_Y_MAX_RATIO)

                scale_data[scale] = {
                    'main_tpl': main_tpl,
                    'tag_tpl': tag_tpl,
                    'drv_tpl': drv_tpl,
                    'main_mask': main_mask,
                    'h_m': h_m, 'w_m': w_m,
                    'h_t': h_t, 'w_t': w_t,
                    'h_d': h_d, 'w_d': w_d,
                    'tag_x_start': tag_x_start, 'tag_x_end': tag_x_end,
                    'tag_y_start': tag_y_start, 'tag_y_end': tag_y_end,
                    'cls_anti_tpl': cls_anti_tpl,
                    'h_ca': h_ca, 'w_ca': w_ca,
                    'cls_y_start': int(h_m * CLS_Y_MIN_RATIO),
                }

            if not scale_data:
                return None

            # === Step 1: 并行 matchTemplate ===
            def _match_one_scale(item):
                scale, sd = item
                try:
                    res = cv2.matchTemplate(screen_bgr, sd['main_tpl'], cv2.TM_CCOEFF_NORMED, mask=sd['main_mask'])
                    locs = np.where(res >= MAIN_FALLBACK_MIN)
                    raw_points = [(int(x), int(y), float(res[y, x])) for x, y in zip(*locs[::-1])]
                    raw_points.sort(key=lambda b: -b[2])
                    nms_input = [(px, py, sd['w_m'], sd['h_m'], ps) for px, py, ps in raw_points]
                    candidates = [(c[0], c[1], c[4]) for c in self._nms_iou(nms_input, iou_threshold=0.3)]
                    return (scale, candidates)
                except Exception:
                    return (scale, [])

            max_workers = min(len(scale_data), max(1, (os.cpu_count() or 4) // 2))  # v1.2.10.6: cpu-1 -> cpu//2，留更多核心给游戏
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                parallel_results = list(ex.map(_match_one_scale, scale_data.items()))

            # 按 best candidate score 降序排列
            parallel_results.sort(
                key=lambda r: max((c[2] for c in r[1]), default=0),
                reverse=True
            )

            best_candidate = None
            all_valid_candidates = []

            for scale, candidates in parallel_results:
                sd = scale_data[scale]
                h_m, w_m = sd['h_m'], sd['w_m']
                tag_tpl = sd['tag_tpl']
                drv_tpl = sd['drv_tpl']
                h_t, w_t = sd['h_t'], sd['w_t']
                h_d, w_d = sd['h_d'], sd['w_d']
                tag_x_start = sd['tag_x_start']
                tag_x_end = sd['tag_x_end']
                tag_y_start = sd['tag_y_start']
                tag_y_end = sd['tag_y_end']

                for car_x, car_y, car_score in candidates:
                    if car_score < MAIN_THRESHOLD:
                        continue

                    # 在右下象限搜索 liketag 或 drivingtag
                    tx1 = max(0, car_x + tag_x_start)
                    ty1 = max(0, car_y + tag_y_start)
                    tx2 = min(screen_bgr.shape[1], car_x + tag_x_end + w_t)
                    ty2 = min(screen_bgr.shape[0], car_y + tag_y_end + h_t)
                    tag_search = screen_bgr[ty1:ty2, tx1:tx2]
                    if tag_search.shape[0] < h_t or tag_search.shape[1] < w_t:
                        continue
                    tag_res = cv2.matchTemplate(tag_search, tag_tpl, cv2.TM_CCOEFF_NORMED)
                    _, tag_score, _, _ = cv2.minMaxLoc(tag_res)

                    drv_score = 0.0
                    if drv_tpl is not None and h_d >= 8 and w_d >= 8:
                        drv_tx2 = min(screen_bgr.shape[1], car_x + tag_x_end + w_d)
                        drv_ty2 = min(screen_bgr.shape[0], car_y + tag_y_end + h_d)
                        drv_search = screen_bgr[ty1:drv_ty2, tx1:drv_tx2]
                        if drv_search.shape[0] >= h_d and drv_search.shape[1] >= w_d:
                            drv_res = cv2.matchTemplate(drv_search, drv_tpl, cv2.TM_CCOEFF_NORMED)
                            _, drv_score, _, _ = cv2.minMaxLoc(drv_res)

                    tag_passed = tag_score >= TAG_THRESHOLD
                    drv_passed = drv_score >= TAG_THRESHOLD
                    if not tag_passed and not drv_passed:
                        self.log(
                            f"[SkillCarStrict] 候选({car_x},{car_y}) 标签不足: "
                            f"like={tag_score:.3f} drv={drv_score:.3f}<{TAG_THRESHOLD} "
                            f"car={car_score:.3f} scale={scale:.3f}"
                        )
                        continue

                    # --- 反向校验 ---
                    cls_anti_tpl = sd['cls_anti_tpl']
                    h_ca, w_ca = sd['h_ca'], sd['w_ca']
                    cls_anti_score = 0.0
                    if cls_anti_tpl is not None and h_ca >= 8 and w_ca >= 20:
                        cls_bottom_y = max(0, car_y + sd['cls_y_start'])
                        cls_bottom_y2 = min(screen_bgr.shape[0], car_y + h_m + h_ca)
                        cls_x1 = max(0, car_x)
                        cls_x2 = min(screen_bgr.shape[1], car_x + w_m)
                        if cls_bottom_y2 > cls_bottom_y and cls_x2 > cls_x1:
                            cls_search = screen_bgr[cls_bottom_y:cls_bottom_y2, cls_x1:cls_x2]
                            if cls_search.shape[0] >= h_ca and cls_search.shape[1] >= w_ca:
                                cls_res = cv2.matchTemplate(cls_search, cls_anti_tpl, cv2.TM_CCOEFF_NORMED)
                                _, cls_anti_score, _, cls_max_loc = cv2.minMaxLoc(cls_res)
                                self.log(
                                    f"[SkillCarStrict] 反向校验: cls={cls_anti_score:.3f} "
                                    f"region=({cls_x1},{cls_bottom_y})-({cls_x2},{cls_bottom_y2}) "
                                    f"tpl={w_ca}x{h_ca} best_loc={cls_max_loc}"
                                )
                                if cls_anti_score >= CLS_ANTI_THRESHOLD:
                                    self.log(
                                        f"[SkillCarStrict] 候选({car_x},{car_y}) 被等级标签排除: "
                                        f"cls={cls_anti_score:.3f}>={CLS_ANTI_THRESHOLD} "
                                        f"({_cls_img}) car={car_score:.3f} scale={scale:.3f}"
                                    )
                                    continue
                            else:
                                self.log(f"[SkillCarStrict] 反向校验跳过: ROI too small ({cls_search.shape})")
                        else:
                            self.log(f"[SkillCarStrict] 反向校验跳过: region invalid y=[{cls_bottom_y},{cls_bottom_y2}] x=[{cls_x1},{cls_x2}]")

                    effective_score = car_score
                    tag_type = "like"
                    if drv_passed:
                        effective_score += 0.05
                        tag_type = "drv"

                    self.log(
                        f"[SkillCarStrict] 发现达标候选: car=({car_x},{car_y}) "
                        f"car={car_score:.3f} {tag_type}={max(tag_score, drv_score):.3f} "
                        f"scale={scale:.3f}"
                    )

                    off_x = region[0] if region else 0
                    off_y = region[1] if region else 0
                    click_x = car_x + w_m // 2 + off_x
                    click_y = car_y + h_m // 2 + off_y
                    all_valid_candidates.append((click_x, click_y, effective_score))

            # 按列优先排序，取第一个
            if all_valid_candidates:
                all_valid_candidates = self._sort_column_first(all_valid_candidates, x_idx=0, y_idx=1, tolerance=50)
                best_candidate = (all_valid_candidates[0][0], all_valid_candidates[0][1])
                self.log(f"[SkillCarStrict] 最终选中: pos={best_candidate} (列优先排序，共 {len(all_valid_candidates)} 个候选)")
            return best_candidate

        except Exception as e:
            self.log(f"find_skill_car_strict 异常: {e}")
            return None

    def wait_for_skill_car_strict(self, timeout=4.0, interval=0.25):
        """等待严格匹配 skillcar，带超时循环。"""
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_skill_car_strict(region=self.regions.get("全界面"))
            if pos:
                return pos
            time.sleep(interval)
        return None
