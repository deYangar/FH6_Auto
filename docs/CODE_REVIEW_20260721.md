# FH6Auto 代码 Review 报告（待办 backlog）

> 初版：2026-07-21 ｜ 最后更新：2026-07-21 15:55
> 已处理项已从正文移除，仅保留底部清单；明细见 git 历史（b2115ea ~ 本次提交）

---

## 一、冗余 / 重复（剩余 2 项，最大的维护风险）

### 1. race_logic.py vs race_logic_xbox.py —— 84% 相同（约 680 行重复）

Xbox 版真正的独有内容只有四块：分享码前台输入（约 75 行，Xbox 文本框必须前台 SendInput）、`stop_ocr_engine` 方法、零散注释漂移（OCR 区域差异已于 89094aa 统一）。其余全是复制粘贴，每次改 Steam 流程都要人肉搬运，`key` 未定义 Bug 就是漂移恶果。

**方案**：抽 `race_logic_base.py` 放共享 `RaceLogicBase`，两个版本文件各剩约 100 行（`class RaceMixin(RaceLogicBase)` + 覆写 `_input_share_code()` 等）。build.bat 文件交换机制不用动。

**风险**：中偏高。动最核心跑图流程；**Xbox 侧无法实机测**，只能编译 + diff 审查。

### 2. input_handler.py vs input_handler_xbox.py —— 40% 相同（92 行）

`game_click`/`hw_press`/`hw_key_down/up`/`move_to_game_coord` 两边逐字一样。Xbox 独有：前台 SendInput 按键、强制前台窗口。

**方案**：公共部分留 input_handler.py，Xbox 版继承只加前台方法。与第 1 项一起做。

---

## 二、健壮性（未处理精选）

| 位置 | 问题 | 建议 |
|---|---|---|
| `main.py` 21 处 `except+pass` | 静默吞错（ui_call、Hook 注入、文件写入等） | 关键路径至少记日志；ui_call 区分 TclError 与真错误 |
| 诊断 JSONL 写入无锁 | runner + 热键 + 心跳并发 append，行可能交错损坏 | 加 `threading.Lock` 或队列单消费者 |
| `config.json` 写入非原子 | 异常退出可能写坏配置 | 临时文件 + `os.replace` 原子写 |
| `set_english_input()` | 对**任意前台窗口**发 IME 切换消息，可能干扰用户在别的程序打字 | 只对 `self.game_hwnd` 发 |
| `start_pipeline().runner()` | 外层循环控制逻辑无 try/except，异常跳过 `stop_all()` 崩线程 | 最外层包异常，确保清理执行 |
| 自动关机 `shutdown -s -t 180` | 无取消机制 | `stop_all()` 自动 `shutdown -a` 或 UI 加取消按钮 |
| `_log_buffer` 竞态 | daemon 线程 append + 主线程遍历 + 手动截断 rebind | 换 `deque(maxlen=1500)` + 锁 |
| `auto_extract_images()` | 外置模板同名不覆盖，用户可能拿旧模板匹配 | 按大小/时间校验，不同则覆盖 |
| `recognition_config.py` 缓存永不失效 | 运行时改 profile 不生效（当前 UI 不暴露，暂不影响） | 配置写入后失效缓存 |

---

## 三、性能（剩余）

| 项 | 现状 | 建议 | 备注 |
|---|---|---|---|
| 固定 sleep 共约 200+ 秒 | 赛事加载固定 15s、菜单过渡 0.5~5s 遍地 | 条件等待（亮度恢复/模板出现/画面差分） | 需逐项游戏内实测阈值，风险中高 |
| `find_combo` 全图 Canny | 2560×1440 下每帧跑边缘兜底 | 限定区域或降低兜底频率 | 低优先 |

---

## 四、项目治理（剩余）

- **debug 文件夹无清理机制**：调试模式每轮堆积上百张截图（实测半天 270MB+）。建议单目录文件数/总大小上限轮转，或启动时清理 N 天前的调试图。
- **超长方法**（拆分收益有、测试成本高，最后做）：`logic_super_wheelspin` 415 行、`create_next_step` 294、`logic_race` 291（Steam）/290（Xbox）、`find_and_remove_consumable_car` 240。

---

## 五、暂缓项（明确保留，非遗漏）

- **15 个死方法**（vision.py ×10、cj_logic ×1、recovery ×2、anti_cheat ×1、input_handler_xbox ×1）：咩咩洋指示暂留，后续可能重新调用。
- **recovery.py 显示器边界死代码块**（mx/my/mw/mh）：同上政策，做"窗口跑出屏幕检测"时可复用。

---

## 本轮已处理（2026-07-21，明细见 git log b2115ea..HEAD）

- 5 个确认 Bug 全修（race_logic `key` 未定义 / main lambda 捕获 e / vision points 未初始化 / config 损坏日志 / 裸 except）
- 启动崩溃回归修复（log 节流初始化遗漏、截图缓存中毒）
- P1 性能：OCR det/rec 参数优化 + 预处理缓冲复用、截图兜底+GDI 缓存、Canny 冗余上提、log 100ms 节流
- P2 性能：筛选导航重写为逐键搜索零过头（目标入屏即勾选，Enter+像素差验证+点击兜底）、完赛检测间隔 1.0→0.5s
- 冗余清理：OCR 上车检测三处合一、调试截图方法统一、Xbox OCR 区域对齐 Steam、SCHEME_SYNC_FIELDS + clear_template_caches
- 清理：13 处未用导入、3 个孤儿文件、死按钮 + start_test_boot + _save_race_car_debug（224 行）
