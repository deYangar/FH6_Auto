# FH6Auto 业务逻辑层 Code Review（Part 3 - Logic 层）

> 评审范围：race_logic.py / race_logic_xbox.py / cj_logic.py / sell_logic.py / buy_logic.py / recovery.py / input_handler.py / input_handler_xbox.py / anti_cheat.py / focus_hook_manager.py
> 评审日期：2026-07-21
> 评审人：AI Agent（只分析不修改）

---

## 一、race_logic.py（Steam 版跑图）

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| 7 | `import numpy as np` 未使用 | 低 | 删除未使用导入 |
| 61, 377 | OCR 检测区域 `y_start=0.9` / `y_end=1.0`；与 Xbox 版 `y_start=0.78` / `0.80` 不一致 | 中 | 统一 OCR 区域常量，消除 Steam/Xbox 视觉差异 |
| 94 | `_save_race_car_debug` 与 Xbox 版 `_save_race_car_debug`（race_logic_xbox.py:181）几乎完全相同，约 100 行重复代码 | 中 | 抽取为公共调试工具方法，或放入父类/vision.py |
| 203 | `start_test_find_image` 方法内调用 `wait_for_new_consumable_car_strict`；Xbox 版 docstring 写为 `find_new_consumable_car_strict()` | 低 | 修正 Xbox 版注释与代码一致 |
| 285 | `_navigate_to_eventlab_and_enter` 中 `blueprint_wait_deadline = time.time() + 20` 的 20 秒为魔法数字 | 低 | 提取为配置项常量 |
| 406 | `logic_race` 方法约 240 行，过长 | 中 | 拆分为 `wait_race_start` / `drive_loop` / `handle_finish` 等子方法 |
| 413 | `self.detail_state_confirmed = False` 只赋值，项目全局无读取 | 中 | 确认是否为遗留状态机字段，若无用则删除；若 VisionMixin 中读取则补充注释 |
| 460-473 | OCR "上车"检测代码与 `sell_logic.py:67-78` 几乎完全相同 | 中 | 抽取公共方法 `ocr_detect_boarding()` |
| 511-515 | 固定等待 15 秒（赛事加载），可改为条件等待 | 中 | 检测画面变化（黑屏→亮屏）或车辆出现后再继续，缩短无效等待 |
| 525 | 暂停恢复后 `race_start_time = time.time()` 重置，但 `stuck_timeout` 检测可能因此无限延后 | 中 | 记录总运行时间，暂停恢复时只重置检测间隔而非总超时 |
| 531 | `race_timeout = max(60, int(self.config.get("race_timeout", 300)))`；异常时 fallback 300 为魔法数字 | 低 | 提取为类常量 `DEFAULT_RACE_TIMEOUT` |
| 583 | `import traceback` 在 except 块内动态导入，若导入失败会掩盖原始异常 | 低 | 移到文件顶部导入 |
| 604 | **未定义变量 `key`**：`self.hw_press(key)` 应为 `self.hw_press(ocr_result)` | **高** | 修复变量名，与 Xbox 版（line 669）保持一致 |
| 613 | `stuck_timeout = max(10, int(self.config.get("stuck_timeout", 60)))`；60 为魔法数字 | 低 | 提取为常量 |

---

## 二、race_logic_xbox.py（Xbox 版跑图）

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| 14 | `import numpy as np` 未使用 | 低 | 删除未使用导入 |
| 40 | `stop_ocr_engine` 仅在 main.py 通过 `hasattr` 反射调用，类内无调用 | 低 | 确认是否需要；若仅为外部反射调用可保留，但建议补充注释 |
| 71, 453 | OCR 区域 `y_start=0.78` / `0.80` 与 Steam 版 `0.9` 不一致 | 中 | 统一为相同常量；差异若无明确理由则属于同步遗漏 |
| 181 | `_save_race_car_debug` 与 Steam 版完全重复 | 中 | 同 Steam 版建议，抽取公共方法 |
| 295 | docstring 写 `"直接反复调用 find_new_consumable_car_strict()"`，实际代码调用 `wait_for_new_consumable_car_strict` | 低 | 修正 docstring |
| 490 | `self.detail_state_confirmed = False` 只赋值，项目全局无读取 | 中 | 同 Steam 版建议 |
| 537-550 | OCR "上车"检测代码与 Steam 版 / sell_logic.py 重复 | 中 | 抽取公共方法 |
| 596-600 | 固定等待 15 秒，同 Steam 版问题 | 中 | 同 Steam 版建议 |
| 608-691 | `race_timeout`、`stuck_timeout` 魔法数字同 Steam 版 | 低 | 同 Steam 版建议 |

---

## 三、cj_logic.py（超级抽奖）

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| 12 | `_is_boarding_transition` 仅在类内使用，但 min_dark_mean=8.0 为魔法数字 | 低 | 提取为配置常量 |
| 35, 253 | `_save_upgrade_debug`、`_save_car_select_debug` 与 race_logic 的 `_save_race_car_debug` 结构高度相似 | 中 | 统一为公共调试截图工具 |
| 73 | `_wait_for_uandt_ready` 参数 `stable_frames=3`、`min_brightness=42.0`、`esc_interval = 3.0` 均为魔法数字 | 低 | 提取为常量或配置项 |
| 183 | `_verify_target_point_b600` 中 `_cls_img` 被赋值两次（line 191 覆盖 line 195 的值，或相反） | 中 | 检查逻辑，删除冗余赋值 |
| 210 | `_keyboard_select_target_card` **死代码**：项目全局 0 处调用 | 中 | 确认是否为备用兜底方案；若不需要则删除 |
| 295 | `logic_super_wheelspin` 约 290 行，过长 | 中 | 拆分为 `enter_garage` / `find_target_car` / `upgrade_and_mastery` / `exit_flow` 等子方法 |
| 302, 441 | `self.detail_state_confirmed = False/True` 只赋值，项目全局无读取 | 中 | 同 race_logic 建议 |
| 315, 448 | `wait_for_buy_and_used_car`、`last_strict_car_click_points`、`last_strict_car_meta` 依赖 VisionMixin，耦合较深 | 低 | 保持现状即可，但建议文档化接口依赖 |
| 518 | `already_boarding = self._is_boarding_transition()` 后 time.sleep(4.5) 为固定等待 | 低 | 可检测画面亮度恢复后再继续 |

---

## 四、sell_logic.py（删车）

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| 9, 173 | `self.detail_state_confirmed = False/True` 只赋值，项目全局无读取 | 中 | 同前建议 |
| 67-78 | OCR "上车"检测代码与 race_logic / race_logic_xbox 完全重复 | 中 | 抽取公共方法 `ocr_detect_boarding()` |
| 67 | `ocr_engine = self.get_ocr_engine()` 命名与 line 125 的 `_ocr_engine` 不一致 | 低 | 统一命名风格 |
| 124-137 | 使用下划线前缀变量 `_no_car`、`_ocr_engine`、`_filter_img`、`_filter_text`；在局部作用域中下划线前缀无意义（非忽略变量） | 低 | 去掉下划线前缀，或使用元组解包简化 |
| 143 | `not_found_pages >= 10` 魔法数字 | 低 | 提取为常量 `MAX_EMPTY_PAGES` |
| 160 | `wait_for_image_ultimate_safe` timeout=1.0 较短，每页最多循环 5 次（1.0/0.2）才翻页，效率偏低 | 低 | 若性能允许可保持；否则缩短 interval 或增加 timeout |

---

## 五、buy_logic.py（买车）

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| 7 | `logic_buy_car` 约 120 行，相对适中但仍有优化空间 | 低 | 可拆分 `enter_collection` / `select_brand` / `buy_loop` |
| 116-117 | `_scheme_idx = 0` 时 scroll 4 次，否则 1 次；4 和 1 为魔法数字 | 低 | 抽取为方案配置字典 |
| 119 | `_dn` 为下划线前缀循环变量，无意义 | 低 | 改为常规命名 `i` 或 `idx` |
| 148, 151, 154, 157 | 反复调用 `move_to_game_coord(5, 5)`，5 为魔法数字 | 低 | 提取常量 `SAFE_MOUSE_POS = (5, 5)` |

---

## 六、recovery.py（卡死恢复）

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| 5 | `import json` 未使用 | 低 | 删除 |
| 15 | `check_and_focus_game` 约 143 行，过长 | 低 | 拆分为 `find_game_window` / `update_regions` / `init_backend_input` |
| 79 | **裸 `except:`** 吞错：`except:` 没有任何异常捕获说明 | 中 | 改为 `except Exception as e:` 并记录日志 |
| 158 | `restart_game_and_boot` 约 228 行，过长 | 中 | 拆分为 `launch_game` / `wait_for_process` / `handle_title_screen` / `handle_continue_screen` |
| 316 | `wait_for_freeroam` **死代码**：项目全局 0 处调用 | 中 | 删除或确认是否保留为手动调试方法 |
| 337 | `recover_to_menu` **死代码**：项目全局 0 处调用，且直接代理 `self.enter_menu()` | 中 | 删除，调用方直接使用 `enter_menu()` |

---

## 七、input_handler.py / input_handler_xbox.py（输入封装）

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| input_handler.py:3 | `import pydirectinput` 仅在 fallback 中使用 | 低 | 保持现状 |
| input_handler.py + input_handler_xbox.py | `game_click`、`hw_press`、`hw_key_down`、`hw_key_up`、`move_to_game_coord`、`hw_mouse_move` 在两个文件中几乎完全相同，仅 Xbox 版多了前台输入方法 | **高** | **强烈建议**：input_handler_xbox.py 继承自 input_handler.py，或把公共逻辑抽到公共基类/模块中；当前两文件并行维护，极易出现修改遗漏 |
| input_handler_xbox.py:110 | `foreground_hotkey` **死代码**：项目全局 0 处调用 | 低 | 删除或保留备用 |
| input_handler_xbox.py:6-10 | `KEYEVENTF_EXTENDEDKEY`、`SW_SHOW` 等常量仅在本文件 `_send_input_scan_key` / `_set_foreground_window_force` 中使用 | 低 | 可保持，属于局部封装 |
| input_handler.py:85-101 | fallback 到 `pydirectinput.mouseDown()` 在后台模式下不起作用，且 game_click 中 `self.hw_mouse_move(x, y)` 为空函数 | 中 | fallback 分支在 bg_input 可用时不会触发，但建议增加注释说明 fallback 仅用于无窗口句柄的降级场景 |

---

## 八、anti_cheat.py（反检测）

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| 10-26 | `_init_anti_cheat_state`、`start_anti_cheat_heartbeat`、`stop_anti_cheat_heartbeat` 被 main.py 调用，设计正常 | - | 无需修改 |
| 40 | `_check_print_window_health` 中 `screen.mean()` 返回 numpy 标量，与 `< 3.0` 比较可工作但类型不严格 | 低 | 改为 `float(screen.mean()) < 3.0` |
| 63 | `verify_input_effective` **死代码**：项目全局 0 处调用 | 中 | 删除或接入主流程（如每轮跑图前验证输入有效性） |
| 82-83 | `before` / `after` 截图后发送 down+up 输入作为探测，可能干扰游戏状态 | 中 | 若启用此方法，建议在安全菜单界面执行，避免在驾驶中误触发 |

---

## 九、focus_hook_manager.py（DLL 注入）

| 行号 | 问题 | 严重度 | 建议 |
|------|------|--------|------|
| 47, 51 | `Module32First.argtypes = [wintypes.HANDLE, ctypes.c_void_p]` 和 `Module32Next` 的类型签名不精确；实际传入 `ctypes.byref(me)`（MODULEENTRY32 指针） | 低 | 改为 `ctypes.POINTER(MODULEENTRY32)`，提高类型安全 |
| 5 | `from config import get_asset_path, INTERNAL_DIR, APP_DIR` 均使用 | - | 正常 |

---

## 十、跨文件综合问题

| 维度 | 问题描述 | 严重度 | 建议 |
|------|----------|--------|------|
| 死代码 | `foreground_hotkey`、`_keyboard_select_target_card`、`wait_for_freeroam`、`recover_to_menu`、`verify_input_effective` 共 5 个方法全局 0 调用 | 中 | 统一清理或标记为 `@deprecated` |
| Steam/Xbox 一致性 | OCR 检测区域不一致（完赛 0.9 vs 0.78；蓝图 0.9 vs 0.80） | 中 | v1.2.10.0 同步后仍有残余差异，需人工确认哪个更优后统一 |
| Steam/Xbox 一致性 | `race_logic.py:604` 未定义变量 `key`，Xbox 版已修复为 `ocr_result` | **高** | 立即修复 Steam 版 |
| 冗余 | `_save_race_car_debug`（Steam+Xbox）+ `_save_car_select_debug` + `_save_upgrade_debug` 结构高度相似 | 中 | 统一为 `save_debug_snapshot(stage, annotations, meta)` 公共方法 |
| 冗余 | `ocr_detect_boarding`（上车检测）在 race_logic / race_logic_xbox / sell_logic 中重复实现 | 中 | 抽取公共方法 |
| 冗余 | input_handler.py 与 input_handler_xbox.py 大量公共代码 | **高** | 重构为继承或公共模块 |
| 状态机漏洞 | `detail_state_confirmed` 在 4 个文件中均只写不读 | 中 | 确认是否为遗留字段，统一清理 |
| 性能 | 大量固定 `time.sleep()`（15s 赛事加载、0.5-5s 菜单等待） | 中 | 逐步引入条件等待（画面亮度/模板匹配/画面差异）替代固定等待 |
| 性能 | OCR 检测间隔 1.0 秒；每 3 秒检查 VRAM | 低 | 跑图结束检测可适当缩短到 0.5 秒，提升响应速度 |
| 健壮性 | `recovery.py:79` 裸 `except:` | 中 | 修复为 `except Exception` |
| 可维护性 | `logic_race` ~240 行、`logic_super_wheelspin` ~290 行、`restart_game_and_boot` ~228 行 | 中 | 按阶段拆分子方法 |

---

## 统计

- **高严重度**：2 条（Steam 版 `key` 未定义、input_handler 双文件重复维护风险）
- **中严重度**：约 22 条（死代码 5 条、Steam/Xbox 区域不一致、冗余/重复代码、状态机漏洞、裸 except、超长方法等）
- **低严重度**：约 20 条（未使用导入、魔法数字、命名风格、动态导入位置等）
