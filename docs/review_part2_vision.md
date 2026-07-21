# FH6Auto 视觉/OCR 层 Code Review（Part 2：Vision & OCR）

> 评审范围：vision.py、ocr_onnx.py、fh6_backend.py、filter_nav.py
> 评审维度：死代码、性能、冗余、健壮性、可维护性、语法/风格

---

## 一、vision.py（2181 行）

### 1.1 死代码

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 23 | `_save_debug_screenshot` 无任何调用 | 低 | 模块级函数，grep 全项目仅定义处命中。建议删除或接入调试开关。 |
| 37 | `_save_action_screenshot` 无任何调用 | 低 | 同上，仅定义处命中。 |
| 514 | `find_image_with_element` 无任何业务调用 | 低 | 仅被 `wait_for_image_with_element`（1698 行，死代码）调用。 |
| 522 | `find_image_with_element_stable` 无任何业务调用 | 低 | 仅被 `wait_for_image_with_element_stable`（1710 行，死代码）调用。 |
| 533 | `find_image_with_element_multi` 无任何业务调用 | 低 | 仅被死代码包装方法（550、1824 行）及 race_logic.py 注释引用，无实际执行业务调用。 |
| 542 | `find_image_with_element_fast` 无任何业务调用 | 低 | 仅被 `wait_for_image_with_element_fast`（1726 行，死代码）调用。 |
| 550 | `wait_for_image_with_element_multi` 无任何调用 | 低 | 纯包装方法，无业务调用。 |
| 1688 | `find_image_smart` 无任何调用 | 低 | 纯包装方法，无业务调用。 |
| 1698 | `wait_for_image_with_element` 无任何调用 | 低 | 纯包装方法，无业务调用。 |
| 1710 | `wait_for_image_with_element_stable` 无任何调用 | 低 | 纯包装方法，无业务调用。 |
| 1726 | `wait_for_image_with_element_fast` 无任何调用 | 低 | 纯包装方法，无业务调用。 |
| 1741 | `wait_for_any_image_transparent` 无任何调用 | 低 | 纯包装方法，无业务调用。 |
| 1824 | `find_skill_car_with_like_tag` 无任何调用 | 低 | 纯包装方法，无业务调用。 |
| 2173 | `wait_for_skill_car_strict` 无任何调用 | 低 | 纯包装方法，无业务调用。 |

### 1.2 性能

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 1497 | `find_combo` 四维度模式全图 Canny | 高 | `use_four_dim=True` 时，`self.to_edge_image(screen_bgr)` 对完整截图跑 Canny（如 2560×1440），非常耗时。建议仅在候选 ROI 上补算边缘，或提供开关关闭。 |
| 1537 | `find_combo` 四维度模式 `argpartition` 开销 | 中 | 对每个缩放比的完整 matchTemplate 结果（可达 200 万元素）做 `np.argpartition(top_k=50)`。建议先用 `minMaxLoc` 快速预筛，仅在最高分高于下限时再 argpartition。 |
| 767 | `find_new_consumable_car_strict` 候选循环内重复计算 `tpl_gray`/`tpl_edge` | 高 | 959、963 行：`tpl_gray = cv2.cvtColor(main_tpl, ...)` 和 `tpl_edge = cv2.Canny(tpl_gray, ...)` 位于**候选遍历内**，但仅依赖 `main_tpl`（按缩放比固定）。应移至 Step 0 预计算，存入 `scale_data`。 |
| 767 | `find_new_consumable_car_strict` 重度并行与模板膨胀 | 中 | `fast_mode=False` 时预加载约 40 个缩放比 × 3 张模板 = 120 张缩放图，再开最多 `cpu_count-1` 个线程做 `matchTemplate`。单帧 CPU 占用极高。建议跨帧缓存 `scale_data`，或限制非必要时只用 `fast_mode`。 |
| 250 | `get_scales_to_try` 未缓存 | 中 | 每次多尺度匹配都重新构造 scales 列表（fast 模式约 22 个，非 fast 约 40+）。建议按分辨率缓存结果。 |
| 15 | `cv2.setNumThreads(1)` 全局副作用 | 低 | 模块级修改 OpenCV 全局线程数，影响同进程所有 cv2 调用。应加注释说明原因，或移至配置初始化。 |

### 1.3 冗余

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 1115–1311 | `find_image_gray` 与 `find_any_image_gray` 核心逻辑大量重复 | 中 | 两者几乎共享同一套“灰度模板→缩放→matchTemplate→invert_mode”流程。建议提取 `_match_gray_single` 公共函数。 |
| 1260–1278 | 多个 `wait_for_*` 轮询包装方法结构完全重复 | 中 | `wait_for_image_gray`、`wait_for_any_image_gray`、`wait_for_image_transparent`、`wait_for_new_consumable_car_strict` 等 10+ 个方法使用同一套 `while time.time() - start < timeout` 循环。建议统一为 `_poll_until(fn, timeout, interval)` 辅助方法。 |
| 74 | `_save_strict_car_simple` 内部重复导入标准库 | 低 | 方法内再写 `import os, time, json`，而模块顶部已导入。建议删除内部冗余导入。 |
| 930 | `find_image_ultimate_safe` 内联 `import os as _os` | 低 | 模块顶部已导入 `os`。建议删除内联导入。 |

### 1.4 健壮性

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 746 | `find_image_ultimate_safe` 潜在 `UnboundLocalError` | 高 | 调试保存块使用 `points`，但 `points` 定义在 `for scale in scales_to_try` 循环体内。若所有缩放比均因模板加载失败导致循环体未执行，`points` 未绑定即被引用，抛出异常。建议初始化 `points = []` 于循环前。 |
| 34, 53, 181, 193, 231, 282, 320, 367, 405, 884, 969, 1438, 2051 | 大量裸 `except Exception:` | 中 | 13 处裸异常吞掉所有错误（包括 `AttributeError`、`KeyError` 等），导致调试困难、故障静默。建议至少区分 `cv2.error` 与常规异常，或记录 traceback。 |
| 367 | `find_image_in_screen` 异常后返回 None，不记录模板/截图上下文 | 中 | 失败时仅日志输出 `e`，没有 traceback，难以定位是哪张模板、哪个区域出错。 |
| 220 | `capture_region` `self.game_hwnd` 无属性保护 | 低 | 直接访问 `self.game_hwnd`，若 Mixin 宿主未初始化会抛 `AttributeError`。建议用 `getattr(self, 'game_hwnd', None)`。 |
| 767 | `find_new_consumable_car_strict` 灰色/边缘兜底在异常时跳过，不记录 | 低 | `try/except Exception: pass` 直接跳过候选，灰度/边缘分数丢失。 |

### 1.5 可维护性

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 767 | `find_new_consumable_car_strict` 方法过长（约 330 行） | 高 | 包含 Step0 预计算、Step1 并行匹配、Step2 串行验证、调试保存等。建议拆分为 `_strict_car_preload`、`_strict_car_match_parallel`、`_strict_car_verify` 等子方法。 |
| 1476 | `find_combo` 方法过长（约 200 行） | 中 | 包含灰度/彩色/四维度三种模式分支。建议提取 `_combo_verify_gray`、`_combo_verify_4dim` 子方法。 |
| 1953 | `find_skill_car_strict` 方法过长（约 170 行） | 中 | 结构与 `find_new_consumable_car_strict` 类似，可同样拆分。 |
| 250 | `get_scales_to_try` 硬编码基准分辨率 2560 | 低 | `primary_base = 2560` 写死。若用户主要用其他分辨率，首选比例偏移。建议参数化或从配置读取。 |
| 767 | `find_new_consumable_car_strict` 大量魔法数字 | 中 | `MAIN_THRESHOLD = 0.85`、`MAIN_GRAY_THRESHOLD = 0.62`、`MAIN_EDGE_THRESHOLD = 0.20`、`TAG_PAD = 4`、`CLS_PAD = 4` 等全部硬编码。建议收拢到类常量或配置字典。 |
| 800 | `find_image_ultimate_safe` 硬编码区域比例 | 中 | `top_h = int(h_m * 0.25)`、`right_w = int(w_m * 0.35)`、`pad_slide = 5` 等。建议常量化。 |

### 1.6 语法/风格

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 930 | `find_image_ultimate_safe` 调试保存变量全部加下划线前缀 | 低 | `_debug_dir`、`_stamp`、`_annotated`、`_path` 等，风格不统一且冗余。 |
| 767 | `find_new_consumable_car_strict` `_load_debug_count` 命名风格 | 低 | 单发计数器用下划线前缀，无必要。 |

---

## 二、ocr_onnx.py

### 2.1 死代码

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 无 | 无独立死代码 | — | 所有公开方法均有调用。 |

### 2.2 性能

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 175 | `detect`/`detect_text_in_region`/`detect_lines_in_region` 均懒加载 + 重复 det | 中 | 每次调用若 `session is None` 则 `init()`；`filter_nav` 导航时可能连续 OCR 10+ 次，每次重新跑 det（960px 图）。建议由调用方保证 `init()` 只执行一次，或增加简易结果缓存。 |
| 120 | `_det_preprocess` resize 后向上取整到 32 倍数 | 低 | `new_h = max(32, (new_h // 32) * 32)` 只向下取整，未处理向上取整导致超 `max_side` 的边界情况（虽罕见）。建议加断言或截断。 |

### 2.3 冗余

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 240–290 | `detect_text_in_region` 与 `detect_lines_in_region` 重复约 40 行 | 中 | 区域裁剪、detection 回退、逐框 rec、边界校验逻辑几乎完全一致。建议提取 `_ocr_region_base` 生成器，由两者分别包装。 |

### 2.4 健壮性

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 308–310 | `detect()` 存在不可达的 `elif` 分支 | 中 | 306 行已判断 `"完成" in combined`，308 行 `elif "完成" in combined` 永不可达；310 行同理。应删除冗余分支，或修正为更细粒度匹配（如仅 `"完成"` 但不含 `"挑战"` 的情况）。 |
| 102 | `yaml` 在 `init()` 内部导入 | 低 | 模块级依赖应在顶部导入，避免首次 OCR 时额外 IO/解析开销。 |
| 70 | `_create_session` 内联 `import os as _os` | 低 | 模块顶部已导入 `os`。 |
| 228 | `_decode_ctc` 索引逻辑稍脆弱 | 低 | `idx - 1 < len(self.chars)` 中若 `idx == 0` 理论上已被 `idx != 0` 过滤，但 `-1` 索引在 Python 中合法，一旦 guard 失效会静默取最后一个字符。建议显式 `if idx == 0: continue`。 |

### 2.5 可维护性

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 55 | `TEXT_REGION` 硬编码比例 | 低 | 比赛结果文字区域比例固定。若游戏 UI 更新或不同分辨率布局变化会失效。建议收拢到 `recognition_config` 或允许外部传入。 |
| 145 | `_unclip` 为简化径向扩展，非标准 Vatti | 低 | DB 算法的 unclip 通常需要 shapely/Vatti 裁剪。当前实现只是简单外扩，对倾斜文字框可能不够精确。注释说明即可。 |

---

## 三、fh6_backend.py

### 3.1 死代码

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 无 | 无死代码 | — | 所有定义均被调用。 |

### 3.2 性能

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 209 | `capture_window` 全图 PrintWindow 无法裁剪前置 | 低 | PrintWindow 必须捕获完整客户区，region 只能在 numpy 层裁剪。2560×1440 下每帧约 14.7MB 位图数据，频繁调用时内存带宽较高。建议调用方在需求允许时合并多次识别到同一帧截图上。 |

### 3.3 冗余

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 无 | 无明显冗余 | — | — |

### 3.4 健壮性

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 209 | `capture_window` 无异常保护，GDI 失败直接崩溃 | 高 | `PrintWindow`、`GetBitmapBits`、`np.frombuffer(...).reshape` 等均未包裹 try/except。任一 GDI 句柄异常或位图尺寸不匹配都会导致整个 bot 崩溃。建议加 try/finally 保护资源释放，并返回 None 降级到 ImageGrab。 |
| 209 | `capture_window` reshape 前未校验位图字节长度 | 中 | `np.frombuffer(bmp_bits, dtype=np.uint8).reshape((h, w, 4))` 假设 bmp_bits 长度严格等于 `h*w*4`。若 GDI 返回异常长度（如句柄失效），reshape 抛 `ValueError`。建议先 `assert len(bmp_bits) == h*w*4`。 |
| 100 | `BackgroundInputManager._send_key` 对未定义键静默返回 | 低 | `vk = VK_MAP.get(key)` 为 None 时直接 `return`，无日志。建议加 warn 日志。 |

### 3.5 可维护性

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 32, 66 | `VK_MAP`/`SCAN_MAP` 为超大硬编码字典 | 低 | 维护方便性尚可，但若有新按键需求需改源码。可考虑从 JSON 加载。 |

### 3.6 语法/风格

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 无 | 无显著问题 | — | — |

---

## 四、filter_nav.py

### 4.1 死代码

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 无 | 常量被外部引用，方法均有调用 | — | `DEFAULT_SELL_FILTER_SCHEME1/2`、`DEFAULT_RACE_FILTER` 在 main.py/race_logic.py 中被引用，非死代码。 |

### 4.2 性能

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 314 | `_search_and_focus` 最坏情况需 14 页 × 0.5s 等待 + OCR | 中 | `_MAX_PAGES=14`，每页 `_PAGE_SETTLE=0.5`，最坏 7s 纯等待 + OCR 耗时。建议根据实测列表长度动态缩减 `_MAX_PAGES`，或允许更短的 settle 时间。 |
| 314 | `_scroll_to_top` 同样存在大量按键与等待 | 低 | 最多 14 轮 × 10 次 up × `_PRESS_GAP=0.1` + 0.5s = 约 7s 以上。 |
| 134 | `_ocr_panel_lines` 每次全量 det+rec | 中 | 筛选面板约 555×540，det 模型每次仍需完整推理。导航过程中可能 OCR 20+ 次。建议缓存上一页 OCR 结果用于比较。 |

### 4.3 冗余

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 无 | 无明显冗余 | — | — |

### 4.4 健壮性

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 134 | `_capture_filter_panel` 直接访问 `self.regions["全界面"]` | 中 | 若宿主未配置 `"全界面"` 区域会抛 `KeyError`。建议 `.get("全界面")` 并返回 None 降级。 |
| 236 | `_find_highlight_band` 内部亮度最低者兜底可能误判 | 低 | 当黄绿色边框检测失败时， fallback 取全宽行带平均亮度最低者。若面板存在其他黑底 UI 元素，可能误认。建议增加候选行高度过滤。 |
| 457 | `_click_toggle_line` 复选框区域硬依赖 `pw` | 低 | `rx1, rx2 = pw - 48, pw - 4` 假设面板宽度与复选框位置固定。若游戏 UI 改版可能失效。建议用比例或 OCR 框右边界动态计算。 |
| 314 | `_search_and_focus` 的 `seen_pages` 循环检测对重复行敏感 | 低 | `page_key = tuple(_norm_text(l["text"]) for l in lines)`，若某页只有 1 行且重复出现，会误判为循环。概率低，但可接受。 |

### 4.5 可维护性

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 26 | `FILTER_PANEL_REGION` 硬编码 1600×900 居中比例 | 中 | 虽使用比例值，但注释和公式均基于 1600×900。若游戏窗口比例变化（如 21:9），面板可能不再居中。建议通过模板匹配或配置化获取面板区域。 |
| 42–48 | 大量交互时序/阈值魔法数字 | 低 | `_PRESS_DELAY`、`_PRESS_GAP`、`_PAGE_SETTLE`、`_TOGGLE_SETTLE`、`_MAX_PAGES`、`_MAX_CORRECTION`、`_CLICK_DIFF_THRESHOLD` 均为模块常量，已命名，尚可接受。但 `_CLICK_DIFF_THRESHOLD=120.0` 缺乏自动校准机制，不同显卡/画质下可能偏移。 |
| 168 | `_clean_panel_lines` 硬编码像素阈值 | 低 | `y1 < h * 0.04` 和 `(y2 - y1) < 18` 为经验值。建议注释说明 18px 的来源。 |
| 236 | `_find_highlight_band` HSV 范围硬编码 | 低 | `(20, 80, 140)`–`(50, 255, 255)` 为黄绿色边框经验值。建议常量化并注释。 |

### 4.6 语法/风格

| 行号 | 问题 | 严重度 | 说明/建议 |
|------|------|--------|-----------|
| 无 | 无显著问题 | — | — |

---

## 五、跨文件综合建议

1. **统一 wait 轮询模式**：vision.py 中 10+ 个 `wait_for_*` 方法结构完全一致，应提取 `_poll_with_timeout(find_fn, timeout, interval)` 到基类或工具模块，减少 200+ 行重复代码。
2. **模板匹配灰度/边缘图预计算**：`find_new_consumable_car_strict` 的 `tpl_gray`/`tpl_edge` 应在 `scale_data` 中预计算，避免每个候选重复跑 Canny。
3. **OCR 高频调用优化**：`filter_nav.py` 导航时连续 OCR 同一区域，可考虑在 `_search_and_focus` 内缓存当前页 OCR 结果，减少 det 模型重复推理。
4. **截图与异常降级**：`fh6_backend.capture_window` 应加 try/except，GDI 失败时自动降级到 `ImageGrab`/`pyautogui`，避免 bot 崩溃。
5. **魔法数字集中管理**：将 vision.py 中散布的阈值、比例、像素值收拢到 `recognition_config.py` 或类级常量字典，便于实机调参。
6. **大文件拆分**：vision.py 已超 2000 行，建议按职责拆分为 `template_matching.py`、`car_recognition.py`、`debug_utils.py`，降低认知负担。

---

*评审完成时间：2026-07-21*
