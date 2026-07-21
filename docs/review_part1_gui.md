# FH6Auto GUI / 配置 / 编排层 Code Review 报告

> Review 范围：`main.py`、`config.py`、`constants.py`、`recognition_config.py`  
> 维度：死代码、冗余、性能、健壮性、配置 schema、可维护性、语法/风格  
> 严重度：🔴 高 / 🟡 中 / 🟢 低

---

## 一、main.py

### 1. 死代码

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| ~10 | `import ctypes` 重复导入（第 3 行已导入） | 🟢 低 | 删除冗余导入 |
| ~26 | `from PIL import Image, ImageGrab` 在 main.py 中未使用 | 🟢 低 | 移除或确认 Mixin 是否真的依赖 main.py 的导入命名空间 |
| ~28 | `import win32gui` 在 main.py 中未使用 | 🟢 低 | 同上 |
| ~29 | `import fh6_backend` 在 main.py 中未使用 | 🟢 低 | 同上；Mixin 应自行导入 |
| ~36 | `MATCH_THRESHOLD` 从 constants 导入但在 main.py 中未使用 | 🟢 低 | 移除，由 VisionMixin 自行导入 |
| ~1134 | `self.btn_test_boot` 已实例化但从未 `.pack()` / `.grid()`，按钮不会显示在 UI 上 | 🔴 高 | 补充 `.pack()` 或移除 |
| ~780 | `is_debug_screenshots_enabled()` 检查 `self.var_debug_screenshots`，但 `setup_ui()` 只创建了 `self.var_debug_mode`，该属性不存在 | 🟡 中 | 统一变量命名；`var_debug_mode` 同时控制截图和诊断模式，应清理二选一逻辑 |
| ~790 | `is_diagnostic_mode_enabled()` 检查 `self.var_diagnostic_mode`，同样不存在于 `setup_ui()` | 🟡 中 | 同上 |
| ~820 | `capture_diagnostic_snapshot` 中 `trace["capture_keys"]` 为 `set()` 但从未 `.add()`，字段完全闲置 | 🟢 低 | 移除或补全用途 |
| ~820 | `capture_diagnostic_snapshot` 中 `ms = int(time.time() * 1000) % 1000` 计算后写入 JSONL，但无消费端 | 🟢 低 | 确认是否需要毫秒精度，否则移除以减少噪音 |
| ~320 | `load_config()` 默认配置中包含 `"race_timeout": 600`，但 UI 中无任何入口控件，`save_config()` 也不保存该字段 | 🟡 中 | 移除死配置或在 UI 暴露；否则造成配置漂移 |

### 2. 冗余 / 重复逻辑

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| ~940-1350 | `setup_ui()` 长达 400+ 行，承担布局、样式、事件绑定、控件创建所有职责 | 🟡 中 | 拆分为 `setup_scheme_bar()`、`setup_task_cards()`、`setup_global_settings()`、`setup_runtime_bar()`、`setup_log_panel()` 等子方法 |
| ~940-1350 | `create_box()`、`create_next_step()` 作为 `setup_ui` 的内嵌函数，无法被外部复用且加剧方法膨胀 | 🟢 低 | 提取为模块级工厂函数或静态方法 |
| ~620-700 | `switch_scheme()`、`delete_scheme()`、`new_scheme()` 中重复出现 `template_cache.clear()`、`scaled_template_cache.clear()` 以及条件性 `template_gray_cache.clear()`、`template_transparent_cache.clear()` 四行组合 | 🟡 中 | 封装 `clear_template_caches()` 方法，避免复制粘贴 |
| ~445-530 | `save_config()` 与 `_sync_to_current_scheme()` 维护两份几乎相同的 key 列表（共 14 个字段），新增字段需改两处 | 🟡 中 | 定义 `SCHEME_SYNC_KEYS` 常量列表，两处共用 |
| ~445 | `_save_int`、`_save_str` 辅助函数与 `normalize_step_entry()` 逻辑部分重叠（都过滤数字、处理异常回退） | 🟢 低 | 提取通用输入校验器 |
| ~1380 | `log()` 的级别推断使用大量字符串匹配；`_on_update_found` 内联 `import tkinter.messagebox`、`import webbrowser` 等 | 🟢 低 | 级别推断可改为调用方显式传 `level`；模块级导入移至文件顶部 |
| ~1340 | `entry_next1/2/3/4` 的 `<FocusOut>` 绑定写了 4 条几乎一样的 lambda | 🟢 低 | 用循环绑定 |
| ~58 | `self._log_buffer = []` 在 `__init__` 中初始化，在 `setup_ui()` (~1300) 中又被覆盖为 `[]` | 🟡 中 | 仅保留一处初始化；否则 `__init__` 到 `setup_ui()` 之间的日志会丢失 |

### 3. 性能

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| ~1380 | `log()` 每次调用都通过 `self.ui_call(write_ui)` 向 Tk 事件队列塞入一个 `after(0, ...)`；高频后端日志（如每帧识图日志）会瞬间塞爆事件队列 | 🔴 高 | 增加批量刷新或节流机制，例如每 100ms 聚合一次日志再刷新 UI |
| ~1380 | `log()` 中 `_log_buffer` 超过 2000 条时执行 `self._log_buffer = self._log_buffer[-1500:]`，在主线程通过 `_apply_log_filter` 遍历同一份列表时发生 rebind，可能导致筛选时丢日志 | 🟡 中 | 使用 `collections.deque(maxlen=1500)` 替代 list + 手动截断，保证线程安全语义 |
| ~1235 | `update_timer()` 每秒执行一次，每次都做 4 组 `format_elapsed` 字符串拼接和多次 `getattr` | 🟢 低 | 可缓存上一次的值，仅在变化时更新 UI；或用 `time.perf_counter` 减少 `time.time()` 调用 |
| ~1455 | `_apply_log_filter()` 从 `_log_buffer` 全量重建文本框内容，O(n) 文本插入；当 buffer 1500 条时卡顿明显 | 🟡 中 | 增量渲染或限制重建最大条数 |
| ~75 | `background_init()` 在 `__init__` 中启动 daemon 线程加载模板缓存，无加载完成信号；用户可能在缓存未就绪时点击开始 | 🟡 中 | 增加加载完成标志或禁用开始按钮直到 `prepare_template_cache()` 结束 |
| ~146 | `check_for_updates()` 每次都新建 daemon 线程，若用户反复触发（如窗口多次获得焦点）可能堆积 | 🟢 低 | 增加 `is_checking_update` 标志锁 |
| ~820 | `capture_diagnostic_snapshot()` 内联 `import json as _json`；高频调用时重复查找模块 | 🟢 低 | 移至文件顶部 |

### 4. 健壮性

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| 全局 | **裸 `except Exception: pass` 泛滥**（约 30+ 处），吞掉所有异常包括 `KeyboardInterrupt`、`SystemExit`、磁盘满错误等 | 🔴 高 | 统一使用 `except Exception as e:` 并至少输出到 stderr 或日志；关键路径（文件写入、Hook 注入）必须记录异常详情 |
| ~135 | `ui_call()` 裸 `except Exception: pass` 会静默丢弃所有 UI 调度失败，包括窗口已销毁后的 `TclError` | 🔴 高 | 区分 `TclError`（窗口已关）与真正错误；至少打印 traceback 到 stderr |
| ~1380 | `log()` 中的 `write_ui` 在 daemon 线程通过 `after(0, ...)` 投递，但 `self._log_buffer.append()` 与主线程的 `_apply_log_filter()` 迭代存在竞态 | 🟡 中 | 使用 `threading.Lock` 保护 `_log_buffer` 的 append / rebind / iterate 操作 |
| ~1490 | `record_diagnostic_log()` 从任意线程（通常是 daemon runner）直接写文件，无锁保护；若 `log()` 并发调用会导致 JSONL 行交错损坏 | 🔴 高 | 加 `threading.Lock` 或改为队列 + 单消费者写文件 |
| ~820 | `capture_diagnostic_snapshot()` 同样以 `"a"` 模式写 `diagnostic.jsonl`，多线程并发 append 可能产生损坏行 | 🟡 中 | 同上 |
| ~445 | `save_config()` 在主线程直接写 JSON 文件，无文件锁；若后台线程也在写（虽然当前没有）会损坏配置 | 🟡 中 | 使用临时文件 + `os.replace` 原子写入；或加锁 |
| ~320 | `load_config()` 中 `self.config.update(user_config)` 未校验 `user_config` 类型；若文件损坏为列表/字符串会抛 `AttributeError`，被外层捕获后静默忽略，导致用户配置全部丢失 | 🟡 中 | 增加 `isinstance(user_config, dict)` 校验 |
| ~1925 | `start_hotkey_listener()` 的回调 `on_press` 直接调用 `self.stop_all()` / `self.toggle_pause()` / `self.start_test_find_image()`，未通过 `ui_call()` 切到主线程 | 🟡 中 | 虽然当前这些方法以状态位为主，但 `start_test_find_image()` 若涉及 UI 操作会跨线程访问 Tk | |
| ~1950 | `set_english_input()` 使用 `GetForegroundWindow()` 获取**任意前台窗口**并发送 IME 控制消息；若用户正在其他应用打字，会被强制切为英文 | 🔴 高 | 改为只对 `self.game_hwnd` 发送，或至少校验前台窗口是否是目标游戏 |
| ~690 | `new_scheme()` / `delete_scheme()` 使用 `shutil.copy2()` / `shutil.rmtree()` 操作文件系统，无异常回滚；删除方案无二次确认 | 🟡 中 | `rmtree` 前增加确认对话框；复制失败应清理已创建目录 |
| ~720 | `delete_scheme()` 删除方案后 `schemes.pop(idx)`，若 `idx` 越界会抛 `IndexError`（理论上不会，因为前面检查了 `len`） | 🟢 低 | 保留防御性判断即可 |
| ~1630 | `start_pipeline()` 的 `runner()` 闭包中，内层 `try/except` 只包裹步骤执行，循环控制逻辑（`next_idx` 计算、自动关机等）无保护；一旦抛异常线程直接崩溃，`stop_all()` 不会执行 | 🔴 高 | 在最外层 `while self.is_running` 包裹 `try/except Exception` 并确保 `stop_all()` / `finish_diagnostic_trace_session()` 被调用 |
| ~1770 | 自动关游戏使用 `os.system('taskkill ...')`、自动关机使用 `os.system("shutdown ...")`；`os.system` 会阻塞并启动 `cmd.exe`，且无法捕获退出码 | 🟡 中 | 改用 `subprocess.run([...], check=False)` |
| ~1770 | 自动关机倒计时 180 秒期间无任何取消机制；若用户在 `shutdown -s` 后想取消，只能手动运行 `shutdown -a` | 🟡 中 | 在 UI 提供“取消关机”按钮，或在 `stop_all()` 中自动执行 `shutdown -a` |
| ~927 | `on_app_close()` 先 `stop_all()` 再 `unload_focus_hook()` 再 `self.destroy()`；若 `destroy()` 后仍有线程调用 `ui_call()`，会静默失败而非优雅退出 | 🟡 中 | 设置 `_is_closing = True` 标志，阻止新的 `ui_call` 投递 |

### 5. 配置 Schema

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| ~320 | 顶层字段与 `schemes[]` 内字段重复（历史遗留），存在双向同步：`load_config` 把 scheme 同步到顶层，`save_config` 把顶层同步回 scheme | 🟡 中 | 当前迁移逻辑已能工作，但长期应在 `save_config` 中不再写冗余顶层字段，仅保留 `current_scheme` 和 `schemes` 数组 |
| ~320 | `load_config()` 在迁移旧配置时，若 `schemes` 为空列表才迁移；但如果用户手动把 `schemes` 改为 `[]`，会再次触发迁移覆盖 | 🟢 低 | 使用显式的 `"config_version"` 字段控制迁移，而非依赖 `schemes` 的真值性 |
| ~320 | `load_config()` 同步 `class_image` 到顶层：`self.config["class_image"] = _schemes[_idx].get(...)`，但 `save_config()` 不单独保存 `class_image`；双向同步链路不对称 | 🟢 低 | 统一由 `_sync_to_current_scheme()` 负责，顶层不再保留 `class_image` |
| ~380 | v1.2.10.0 筛选字段迁移直接 `for _i, _s in enumerate(...)` 并原地修改 `_s`，无 schema 版本标记；未来再次变更默认值时无法区分“用户未设置”与“用户显式设为空列表” | 🟡 中 | 引入 `config_version` 字段，仅当版本低于目标时才执行迁移；区分 `None` 与 `[]` |
| ~445 | `save_config()` 不保存 `race_timeout`，但默认配置包含它；长期会导致该字段从用户文件中消失 | 🟢 低 | 若决定弃用，从默认配置中移除；若保留，在 UI 暴露入口 |

### 6. 可维护性

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| ~1380 | `log()` 的级别推断依赖中文关键词匹配（如 `"失败" in text and "点击" not in text`），维护成本高且行为不可预测 | 🟡 中 | 强制所有调用点显式传入 `level`；推断逻辑降级为 fallback 并打印 `warnings.warn` |
| ~1630 | `start_pipeline()` 的 `runner()` 闭包超过 150 行，混入了：步骤路由、循环计数、失败恢复、下一步跳转、大循环判断、自动关机 | 🔴 高 | 拆分为 `_run_pipeline_loop()`、`_execute_step()`、`_handle_step_failure()`、`_handle_pipeline_completion()` 等子方法 |
| ~940 | 大量魔法数字硬编码：`1360x760`、`0.98`、`255`、`300`、`48`、`64`、`220`、`260`、`170`、`96`、`340`、`30`、`600` 等 | 🟢 低 | 提取为 `UI_` / `LAYOUT_` 前缀的常量 |
| ~980 | `create_box()` 默认 `height=255`，但 `box_race` 被立刻覆盖为 `height=300`；魔法数字不一致 | 🟢 低 | 让 `create_box` 接受 `height` 参数 |
| ~146 | `check_for_updates()` 中版本号从 HTML 正则提取，依赖 GitHub 页面 DOM 结构，易因页面改版失效 | 🟡 中 | 改用 GitHub API `/releases/latest` 并处理 403 速率限制；或至少增加 HTML 解析失败 fallback |
| ~205 | `_on_update_found()` 弹窗与闪烁逻辑混在一起：弹窗是模态阻塞调用，闪烁是异步 `after` 链；弹窗阻塞期间闪烁不会更新 | 🟢 低 | 先启动闪烁，再用 `after` 延迟弹窗，或把弹窗改为非模态 |
| ~580 | `apply_scheme_to_ui()` 对 10+ 个控件逐个 `if hasattr(...)` 判存后设置值，代码膨胀 | 🟢 低 | 维护 `(widget_name, config_key, default)` 映射表，循环处理 |

### 7. 语法 / 风格

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| ~10 | `import ctypes` 重复 | 🟢 低 | 删除 |
| ~26 | `from PIL import Image, ImageGrab`、`import win32gui`、`import fh6_backend`、`MATCH_THRESHOLD` 未使用 | 🟢 低 | 删除 |
| ~137 | `_open_releases_page()` 内联 `import webbrowser` | 🟢 低 | 移至文件顶部 |
| ~146 | `check_for_updates()` 内联 `import urllib.request, ssl, re` | 🟢 低 | 移至文件顶部 |
| ~205 | `_on_update_found()` 内联 `from tkinter import messagebox`、`import webbrowser` | 🟢 低 | 移至文件顶部 |
| ~755 | `rename_scheme()` 内联 `import tkinter.simpledialog as sd` | 🟢 低 | 移至文件顶部 |
| ~1630 | `runner()` 闭包内内联 `import traceback` | 🟢 低 | 移至文件顶部 |
| ~690 | `new_scheme()` / `delete_scheme()` 内联 `import shutil` | 🟢 低 | 移至文件顶部（虽然功能正确，但风格不一致） |
| ~146 | SSL 回退逻辑嵌套过深：先 `try` 正常 SSL，再 `except Exception:` 创建不验证证书上下文 | 🟡 中 | 封装为 `create_ssl_context(verify=True)` 辅助函数 |
| ~320 | `load_config()` 中 `ext_path = USER_CONFIG_FILE` 赋值后未使用变量名（后面直接用 `USER_CONFIG_FILE`） | 🟢 低 | 统一使用 `ext_path` 或删除该行 |
| ~1770 | `os.system("shutdown -s -f -t 180")` 缺少引号处理；虽然当前字符串是常量，但风格上应避免 `os.system` 拼接命令 | 🟢 低 | 改用 `subprocess.run(["shutdown", "-s", "-f", "-t", "180"])` |

---

## 二、config.py

### 1. 死代码 / 副作用

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| ~10-35 | `check_windows_dependencies()` 在模块导入时立即执行并可能弹出系统 MessageBox；副作用发生在 `import config` 时 | 🟡 中 | 改为函数，由 `main.py` 在 `if __name__ == "__main__"` 或 `__init__` 中显式调用 |
| ~37-45 | `ctypes.windll.shcore.SetProcessDpiAwareness(2)` 与 `main.py` 第 5 行重复设置 DPI Awareness | 🟢 低 | 保留 main.py 中的即可（必须在 UI 操作之前），config.py 中删除 |

### 2. 健壮性

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| ~70-85 | `auto_extract_images()` 在遍历内部目录树时，若外部目录已存在同名文件但内容不同，不会覆盖；用户可能看到旧模板 | 🟡 中 | 增加校验（文件大小 / 修改时间 / hash），不同时覆盖或提示 |
| ~95-110 | `get_img_path()` 使用全局可变变量 `_current_scheme_dir`，无锁保护；若多线程同时切换方案和识图，可能读到错误 scheme 的模板 | 🟡 中 | 使用 `threading.Lock` 保护 `_current_scheme_dir` 的读写，或将其封装为带锁的类 |
| ~95 | `get_img_path()` 回退链路过长（6 个 if），且最后一个回退直接返回原始 `filename`（可能包含绝对路径或不存在路径），调用方容易在未找到时得到静默失败 | 🟡 中 | 未找到时返回 `None` 或抛出异常，让调用方明确处理 |
| ~115 | `get_asset_path()` 最后一个回退返回 `None`，但调用方 `get_asset_path("icon.ico")` 在 `main.py` 中仅做 `if icon_path:` 判空；风格不一致 | 🟢 低 | 统一返回语义（`None` 表示未找到）即可，当前已这么做 |

### 3. 可维护性

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| ~60 | `CURRENT_VERSION = "1.2.10.0"` 硬编码；发布时容易忘记同步 Git tag | 🟢 低 | 考虑从 `version.txt` 或 Git tag 动态读取（PyInstaller 可通过 `--add-data` 打包） |
| ~70 | `auto_extract_configs()` 只迁移 `bot_config.json` / `bot-config.json`，若未来再改名仍需扩展硬编码列表 | 🟢 低 | 使用 glob 匹配 `bot*config*.json` |

---

## 三、constants.py

### 1. 死代码

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| ~3 | `PUL = ctypes.POINTER(ctypes.c_ulong)` 定义后仅被结构体字段类型引用，本身无独立用途；非真正死代码，但风格上可内联 | 🟢 低 | 保持现状或注释说明 |
| ~4 | `SendInput = ctypes.windll.user32.SendInput` 在本模块未直接使用，由 InputMixin 消费 | 🟢 低 | 若 InputMixin 自行导入，可移除；否则保留并加注释 |

### 2. 可维护性

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| 全局 | `DIK_CODES` 使用裸元组 `(scan_code, extended_flag)`，调用方需记 `code[0]` / `code[1]`，可读性差 | 🟢 低 | 改用 `namedtuple` 或 dataclass：`DIK_CODES["enter"].scan` / `.extended` |
| 末尾 | `MATCH_THRESHOLD = 0.8` 全局阈值，但项目已迁移到 `recognition_config.py` 的按场景 profile，可能已无人使用 | 🟡 中 | 确认 VisionMixin 是否仍引用；若已废弃，标记为 deprecated 或移除 |

---

## 四、recognition_config.py

### 1. 健壮性

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| ~55-65 | `_merged_cache` 和 `_cache_initialized` 是模块级全局状态，**永不清除**；若运行时用户修改 `bot.config["recognition_profiles"]`，缓存不会失效 | 🔴 高 | 增加缓存失效机制：在 `save_config()` 写入 `recognition_profiles` 后调用 `_invalidate_recognition_cache()`，或去掉缓存直接 `copy.deepcopy`（profile 数量极少，性能差异可忽略） |
| ~65 | `get_recognition_profile()` 中 `_merged_cache.get(key, {})` 返回空 dict 时，调用方若直接访问 `profile["threshold"]` 会抛 `KeyError` | 🟡 中 | 对未知 key 返回 `dict(DEFAULT_RECOGNITION_PROFILES.get(key, {}))` 而不是 `{}`，保证默认值兜底；或显式 `raise KeyError(f"Unknown profile: {key}")` |
| ~67 | `overrides` 过滤条件 `if v is not None` 阻止了显式覆盖为 `None` 的意图；虽然 `0`/`False` 不受影响，但语义上仍有限制 | 🟢 低 | 若需支持显式 `None`，改为 sentinel 对象判断 |

### 2. 可维护性

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| ~55 | `_build_merged_profiles()` 只合并 `DEFAULT_RECOGNITION_PROFILES` 中已有的 key；用户新增自定义 profile key 会被忽略 | 🟢 低 | 是否允许用户新增自定义 profile？若允许，需合并 `user_profiles` 中不在默认里的 key |
| ~55 | 注释说“避免每次调用都 deepcopy”，但 `_build_merged_profiles` 仍对每个 key 执行 `dict(default_vals)`（浅拷贝），而 `default_vals` 的值都是不可变类型（float/int/bool/str），浅拷贝已足够 | 🟢 低 | 注释准确即可；当前实现正确，无需深拷贝 |

---

## 五、跨文件 / 架构层面

| 问题 | 严重度 | 建议 |
|------|--------|------|
| **main.py  imports 大量仅供 Mixin 使用的模块**（`Image`, `ImageGrab`, `win32gui`, `fh6_backend`, `MATCH_THRESHOLD`），导致 main.py 依赖膨胀且难以判断哪些导入是真的“死代码” | 🟡 中 | 每个 Mixin 文件自行导入所需模块；main.py 只保留自身直接使用的导入 |
| **DPI Awareness 在 `main.py` 和 `config.py` 中重复设置** | 🟢 低 | 只保留 `main.py` 中的（必须在 Tk/ctk 初始化前） |
| **配置读写无文件锁、无原子写入**；`config.json` 可能在异常退出时损坏为空文件或截断文件 | 🔴 高 | 统一封装 `atomic_write_json(path, data)`：先写 `path.tmp`，再 `os.replace` |
| **日志/诊断文件追加写入无锁**，多线程并发场景下（runner + hotkey + anti-cheat heartbeat）存在行损坏风险 | 🔴 高 | 引入 `logging` 标准库的 `QueueHandler` + `QueueListener` 模式，或至少为文件写入加 `threading.Lock` |
| **Xbox 版替换机制**（`race_logic_xbox.py` / `input_handler_xbox.py` 替换 Steam 版）不在本次 review 范围，但需注意：若 `build.bat` 替换后忘记还原，会导致 Git 工作区污染 | 🟢 低 | 在 `build.bat` 中使用临时复制或验证校验和，确保构建前后工作区干净 |

---

## 统计

| 维度 | 问题数 |
|------|--------|
| 死代码 | ~11 |
| 冗余 / 重复 | ~9 |
| 性能 | ~7 |
| 健壮性 | ~18 |
| 配置 Schema | ~5 |
| 可维护性 | ~10 |
| 语法 / 风格 | ~12 |
| **合计** | **~72** |

---

*报告生成时间：2026-07-21*  
*Reviewer：Subagent Code Review*
