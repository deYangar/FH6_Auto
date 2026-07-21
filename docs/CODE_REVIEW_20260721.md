# FH6Auto 代码 Review 报告

> 日期：2026-07-21 ｜ 版本：v1.2.10.0 ｜ 提交：0cc7622
> 方式：3 个分组精读（GUI/视觉/逻辑，kimi-k2.6）+ 自动化扫描（pyflakes/死代码/重复度/sleep 分布）+ 主 Agent 抽查验证
> 分子报告：`docs/review_part1_gui.md`、`docs/review_part2_vision.md`、`docs/review_part3_logic.md`

---

## 一、总览

| 指标 | 数值 |
|---|---|
| 代码规模 | 18 个 py 文件，约 6600 行 |
| 发现问题 | 约 170 条（高 12 / 中 ~70 / 低 ~90） |
| 确认 Bug | 5 个（2 个会在特定分支必崩） |
| 死代码 | 15 个方法 + 13 处未用导入 + 3 个孤儿文件 |
| Steam/Xbox 重复度 | race_logic **84%**（v1.2.10 同步后反而更高了） |
| 固定 sleep 总量 | 233 秒（分布在跑图/抽奖/删车流程里） |
| 依赖健康度 | requirements.txt 10 项全部在用 ✅ |

**总体评价**：功能迭代快、实机验证充分，但"快速堆功能"留下了三类债：① 少量潜伏崩溃 Bug（都在低频分支，平时跑不到）；② Steam/Xbox 双文件并行维护，改一处漏一处；③ 固定 sleep 堆出来的等待时间。没有架构级硬伤，可以分批还。

---

## 二、🔴 确认 Bug（建议第一批修，全部已人工复核）

| # | 位置 | 问题 | 触发条件 | 影响 |
|---|---|---|---|---|
| 1 | `race_logic.py:603-604` | **未定义变量 `key`**（应为 `ocr_result`） | 完赛按键后二次 OCR 验证发现按键没生效 → 走"重按"分支 | 该分支必崩 NameError，跑图循环中断 |
| 2 | `main.py:206` | lambda 捕获 except 变量 `e`，Python 3 在 except 块结束后删除 `e` | 启动更新检查失败时 | UI 日志回调 NameError |
| 3 | `vision.py:746` | 调试块引用 `points`，但所有缩放比模板加载失败时 `points` 从未赋值 | 调试截图开启 + 模板全部加载失败 | UnboundLocalError（被外层 try 兜住，但调试截图流程断掉） |
| 4 | `main.py:363-364` | `except Exception as e` 捕获后日志没用 `e`（f-string 无占位符） | config.json 损坏时 | 用户看不到损坏原因，排障困难 |
| 5 | `recovery.py:79` | 裸 `except:`（GetDpiForWindow 兼容调用） | 老版本 Windows | 吞掉一切异常含 KeyboardInterrupt |

---

## 三、性能优化机会（按性价比排序）

### P1 — 低风险高收益，不用游戏实测

| 项 | 现状 | 优化 | 预估收益 |
|---|---|---|---|
| OCR det 输入尺寸 | `max_side=960`，筛选面板 555×540 会被放大到 ~960 推理 | 降到 640（或按区域动态） | det 耗时 -40~50%，filter_nav 每次筛选省 1~2s |
| OCR rec 最大宽度 | `REC_MAX_W=320`，菜单文字行实际 ~160px | 降到 240 | rec 耗时 -20~30% |
| OCR det 输入缓存 | 每次调用重新 resize+normalize+transpose | 同尺寸输入复用预处理缓冲 | 省 2~5ms/次，高频调用累积可观 |
| `fh6_backend.capture_window` | **无 try/except**，GDI/PrintWindow 失败直接崩整个 bot；BITMAP 结构每次重建 | 包异常兜底 + 缓存 BITMAP | 消除崩溃点 + 省 ~1ms/帧 |
| `vision.py:959/963` | `find_new_consumable_car_strict` 候选循环内重复算 `tpl_gray`/`tpl_edge` | 提到循环外 | 超抽选车每帧省多次 Canny |
| `log()` 无节流 | 每条日志都 `after(0,...)` 塞 Tk 队列，高频日志会塞爆 | 100ms 批量刷新 | GUI 响应更跟手 |

### P2 — 中风险，需要游戏内验证参数

| 项 | 现状 | 优化 |
|---|---|---|
| 固定 sleep 233 秒 | 赛事加载固定等 15s、菜单过渡 0.5~5s 遍地 | 改条件等待（亮度恢复/模板出现/画面差分）。跑图单圈有望省 5~10s，但**每个阈值都要实测** |
| `find_combo` 全图 Canny | 2560×1440 下每帧跑 Canny 边缘兜底 | 限定区域或降低兜底触发频率 |
| filter_nav 筛选耗时 ~30s | 半页步进 + 0.5s 翻页等待 | 步长调大到 0.7 页、settle 压到 0.3s，约 15s（实测点击差值 220+ 余量充足，节奏加快风险小） |
| OCR 完赛检测间隔 1.0s | 每秒一帧 | 缩到 0.5s，完赛响应更快 |

### P3 — 架构级，远期

- 识别配置缓存（`recognition_config.py`）永不失效：运行时改 profile 不生效。当前 UI 不暴露该配置，暂不影响。

---

## 四、死代码清理清单（全部 grep 验证过零引用）

**15 个方法**（删前再确认一遍 F3 测试流程不用）：

| 文件 | 方法 | 来源 |
|---|---|---|
| vision.py ×10 | `find_image_smart`、`find_skill_car_with_like_tag`、`find_skill_car_strict`、`wait_for_any_image_transparent`、`wait_for_image_with_element`、`wait_for_image_with_element_fast`、`wait_for_image_with_element_multi`、`wait_for_image_with_element_stable`、`_save_action_screenshot`、`_save_debug_screenshot` | v1.2.8.0 按键导航改造 + v1.2.10.0 Xbox 同步后全部失去调用方 |
| cj_logic.py | `_keyboard_select_target_card` | 旧选车兜底 |
| recovery.py ×2 | `recover_to_menu`、`wait_for_freeroam` | 早期恢复逻辑 |
| anti_cheat.py | `verify_input_effective` | 写了没接入 |
| input_handler_xbox.py | `foreground_hotkey` | Xbox 前台热键，零调用 |

**未用导入 13 处**：main.py ×10（PIL.Image/ImageGrab、win32gui、fh6_backend、LOG_FILE、CACHE_DIR、TEMPLATE_CACHE_FILE、TEMPLATE_META_FILE、get_img_path、MATCH_THRESHOLD）、race_logic.py + race_logic_xbox.py 的 `numpy`、recovery.py 的 `json`/`APP_DIR`、config.py 的 `json`/`subprocess`/`tkinter`、recognition_config.py 的 `copy`、race_logic_xbox.py 的 `DIK_CODES`。

**孤儿文件**：`forza_test_tool.spec`（旧 spec，现在是 FH6Auto.spec）、`release_notes_v1.2.6.0.md`（release note 已迁到 docs/）、`.github/workflows/build.yml.disabled`。

**死 UI**：`main.py:1208` 的 `btn_test_boot`（"测试启动流程"按钮）创建了但从未 `.pack()`，界面上看不到——要么补 pack 要么删。

**死配置**：`race_timeout` 在默认配置里但 UI 无入口、save_config 不保存（会慢慢从用户文件里消失）；`detail_state_confirmed` 在 4 个文件里只写不读，疑似遗留状态机字段。

---

## 五、冗余 / 重复（最大的维护风险）

1. **race_logic.py vs race_logic_xbox.py：84% 相同（684 行）**。v1.2.10 同步选车后重复度从 75% 涨到 84%。每次改 Steam 版都要手动同步 Xbox 版，`key` 未定义 Bug 就是"Xbox 版修了 Steam 版没修"类问题的反面例子。**建议**：抽 `RaceLogicBase` 基类，Xbox 子类只覆写输入法和分享码输入两段差异。
2. **input_handler.py vs input_handler_xbox.py：40% 相同**，`game_click`/`hw_press`/`hw_key_down/up` 几乎一样。建议继承或公共模块。
3. **OCR 上车检测**在 race_logic / race_logic_xbox / sell_logic 三处几乎逐字重复。建议抽 `ocr_detect_boarding()`。
4. **调试截图方法** `_save_race_car_debug`（Steam+Xbox 两份）/ `_save_car_select_debug` / `_save_upgrade_debug` 结构高度相似。建议统一 `save_debug_snapshot(stage, ...)`。
5. **Steam/Xbox OCR 区域不一致**：完赛检测 Steam 用 `y 0.9~1.0`、Xbox 用 `0.78~0.80`；蓝图检测 `0.9` vs `0.80`。v1.2.10 同步后的残余差异，需确认哪个对再统一。
6. **main.py 内**：`save_config` 与 `_sync_to_current_scheme` 维护两份 14 字段的 key 列表；模板缓存清理四行组在 3 个方法里复制粘贴。

---

## 六、健壮性问题（中高危精选）

| 位置 | 问题 | 建议 |
|---|---|---|
| `main.py` 21 处 `except+pass` | 静默吞错，包括 ui_call、Hook 注入、文件写入 | 关键路径至少记日志；UI 调度区分 TclError（窗口已关）和真错误 |
| 诊断 JSONL 写入无锁 | runner 线程 + 热键 + 反检测心跳并发 append，行可能交错损坏 | 加 `threading.Lock` 或队列单消费者 |
| `config.json` 写入非原子 | 异常退出可能写坏配置 | 临时文件 + `os.replace` 原子写 |
| `set_english_input()` | 对**当前前台窗口**（可能是你在用的别的程序）发 IME 切换消息 | 只对 `self.game_hwnd` 发 |
| `start_pipeline().runner()` | 外层循环控制逻辑无 try/except 包裹，异常会跳过 `stop_all()` 直接崩线程 | 最外层包异常，确保清理执行 |
| 自动关机 `shutdown -s -t 180` | 无取消机制 | `stop_all()` 里自动 `shutdown -a`，或 UI 加取消按钮 |
| `_log_buffer` 竞态 | daemon 线程 append + 主线程遍历筛选 + 手动截断 rebind | 换 `deque(maxlen=1500)` + 锁 |
| `auto_extract_images()` | 外置模板同名不覆盖，用户可能拿着旧模板匹配 | 按大小/时间校验，不同则覆盖 |

---

## 七、项目治理

- **debug 文件夹 272.8 MB 且无清理机制**——每开一次调试模式就堆积上百张截图。建议：单目录文件数/总大小上限轮转，或启动时清理 N 天前的调试图。
- `.gitignore` 完善 ✅（dist/build/debug/cache/spec 都没入库）。
- 超长方法 TOP5：`logic_super_wheelspin` 415 行、`create_next_step` 294、`logic_race` 291（Steam）/290（Xbox）、`find_and_remove_consumable_car` 240。拆分收益有但测试成本高，**建议最后做**。

---

## 八、建议执行顺序

| 批次 | 内容 | 风险 | 需要实测 |
|---|---|---|---|
| **第1批** | 5 个确认 Bug + 死代码 15 方法 + 未用导入 + 孤儿文件 + 死 UI/死配置清理 | 极低 | 编译通过即可 |
| **第2批** | P1 性能项（OCR 参数/缓存、capture 兜底、Canny 冗余、log 节流）+ 健壮性里的原子写配置/日志锁/`set_english_input` 修正 | 低 | 跑一轮完整流程确认 |
| **第3批** | 重复代码抽取（boarding/调试截图公共方法 → Steam/Xbox 基类化） | 中 | Steam+Xbox 各跑一轮 |
| **第4批** | 固定 sleep 条件化、超长方法拆分、config schema v2（config_version 字段） | 中高 | 逐项游戏实测 |

第1批可以马上做（纯清理零逻辑风险），做完直接编译给你测。第2批我估计半天内能完成。第3批开始就需要你 Xbox 版也能测才稳。

---

*子报告明细：review_part1_gui.md（~72 条）/ review_part2_vision.md（~60 条）/ review_part3_logic.md（~44 条）*
