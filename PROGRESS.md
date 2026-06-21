# FH6Auto 项目进度

## 当前版本
**v1.1.6.4** (2026-06-21)

---

## 项目结构

```
forza_test_tool/
├── main.py                 # 入口文件，UI + 流程控制 (~800行)
├── constants.py            # ctypes 结构体 + DIK_CODES 扫描码映射
├── config.py               # 路径策略 + 配置管理 + 资源自动释放
├── input_handler.py        # 键盘/鼠标输入封装（硬件级 + PostMessage 后台）
├── vision.py               # 图像识别引擎（模板匹配/边缘检测/多尺度适配）
├── recovery.py             # 故障恢复 + 游戏状态管理 + 自动启动流程
├── race_logic.py           # 循环跑图业务逻辑 + F3 测试找图
├── buy_logic.py            # 批量买车业务逻辑
├── cj_logic.py             # 超级抽奖业务逻辑
├── anti_cheat.py           # 反检测心跳检测（新增）
├── fh6_backend.py          # 后台输入管理器（PrintWindow + PostMessage）
├── game_window_tester.py   # 游戏窗口后台截图 & 输入测试工具
├── build.bat               # 本地打包脚本
├── .github/workflows/      # GitHub Actions CI（已禁用，改用本地打包）
├── images/                 # 识图模板素材
├── assets/                 # 图标/配置示例
└── PROGRESS.md             # 本文件
```

---

## 核心功能

### ✅ 已完成功能

| 模块 | 说明 |
|------|------|
| 后台截图 | `PrintWindow` flag=3，Win10+ D3D/UE 窗口可后台截取 |
| 后台输入 | `PostMessage` 键盘/鼠标，点对点不抢全局键鼠 |
| 循环跑图 | 自动进 EventLab → 输蓝图码 → 选车 → 自动跑 → 超时重开 |
| 批量买车 | 进车辆收藏 → 定位品牌 → 重复购买 |
| 超级抽奖 | 技能树路径 → 三段验证选车 → 翻页记忆优化 |
| 故障恢复 | 高级状态机退回菜单 + 显存不足检测 + 10次重试上限 |
| 暂停/停止 | F8 停止、F9 暂停（松开油门）、F3 测试找图 |
| 自动打包 | PyInstaller + **本地 `build.bat`** |
| 窗口测试器 | 独立工具，测后台截图/输入 |
| **反检测心跳** | **新增：PrintWindow 健康检测 + 输入有效性验证** |

---

## 重构记录

### 2026-06-19: main.py 拆分重构
- **原始状态**: `main.py` 单文件 4000+ 行，维护困难
- **拆分后**: 9 个模块文件，职责分离
  - `constants.py` — 常量和 ctypes 结构体
  - `config.py` — 配置和资源路径
  - `input_handler.py` — 输入封装
  - `vision.py` — 图像识别引擎
  - `recovery.py` — 故障恢复
  - `race_logic.py` / `buy_logic.py` / `cj_logic.py` — 业务逻辑
  - `anti_cheat.py` — 反检测心跳（新增）
- **主类继承**: `FH_UltimateBot` 多重继承所有 Mixin
- **打包方式**: GitHub Actions CI 禁用，改用本地 `build.bat`
- **2026-06-19 修复**: 批量买车进入车辆收藏时，改用键盘焦点导航：在命中 `carcollection.png` 后从当前“探索”焦点按 `down` 再 `enter`，避免后台鼠标点击未切焦点导致误进“探索”；进入车辆网格后按 `backspace` 打开制造商/品牌列表（与 AxeroYF/FH6 原版一致）。
- **2026-06-19 审计修复**: 对照 AxeroYF/FH6 审计确认无方法/图片/assets 丢失；恢复原版“点击后移开鼠标防 hover 遮挡识图”的语义为可选参数 `game_click(..., move_away=True)`，默认关闭，避免品牌/菜单选择被后台移开悬停点打断。
- **2026-06-19 超级抽奖误选修复**: 收紧并改造 `find_new_consumable_car_strict`：不再按 AxeroYF 原版遇到 `目标>=0.56` 即点击，而是收集本屏候选；判定条件为彩色整卡 `目标>=0.70`，或组合 `目标>=0.62 且 灰度>=0.62 且 边缘>=0.20`。已取消“灰度单独通过”，避免 BRZ 等相似蓝车误判为目标车。
- **2026-06-19 超级抽奖调试功能**: 对“全新+B600 通过但目标车分数不足”的候选自动保存调试材料到 `debug_strict_car/`，包括全屏标注图、候选车卡裁剪、搜索区域、`newCC.png` 模板和 `meta.json`。
- **2026-06-19 超级抽奖安全修复**: 找不到 `rc.png`“上车”按钮时，不再执行原版的盲按 `enter` 上车，直接失败退出，避免后台点击未选中目标车时误上当前焦点车辆（如 BRZ FE）。
- **2026-06-19 超级抽奖识别区域修复**: 修正 `find_new_consumable_car_strict` 的目标车搜索区域。旧逻辑从“全新”标签反推大区域后让模板自由滑动，容易出现裁剪区上偏、右下缺失；新逻辑使用 `newcartag` 相对 `newCC` 的固定锚点反推车辆图片左上角，只允许小范围微调，并收紧标签相对位置校验。
- **2026-06-19 品牌进入确认修复**: 在批量买车和超级抽奖中，点击 `CCbrand.png` 后检测品牌图是否仍可见；若仍停留制造商列表，则最多补 3 次 `Enter` 进入车辆列表，避免“选中斯巴鲁但没点进去”就开始扫车。
- **2026-06-19 超级抽奖点击点修复**: `find_new_consumable_car_strict` 识别目标车仍使用 `newCC` 车辆图片区，但返回点击坐标改为 `B600` 等级区域中心，不再点击车身图片中心，提升后台点击选中车卡的可靠性。
- **2026-06-19 选车/上车调试功能**: 新增并增强 `debug_car_select/` 调试输出。超级抽奖识别到目标车后，会保存每个 SendMessage 候选点的 `before_send_point_N` / `after_send_point_N`、`before_enter_select` / `after_enter_select`、`after_rc_search` 等阶段截图和 meta，标注目标点击点/上车按钮坐标，便于分析识别正确但后台点击未选中/未上车的问题。
- **2026-06-19 超级抽奖 SendMessage 强点选车**: 修复底层鼠标释放事件后，3 次点击会真实生效并点过头，因此选车收敛为只点主点（B600 中心）单次 SendMessage（clicks=1, hold=0.22s, gap=0.18s），不发送 `WM_LBUTTONDBLCLK`。修复调试 meta 中 `np.int64` 导致 JSON 序列化失败的问题；`WM_LBUTTONUP` 的 `wParam` 从错误的 `MK_LBUTTON` 改为 `0`，避免游戏只收到 hover/press 而不触发真正 release/click。用户确认现已能正确选择车辆上车。
- **2026-06-19 超级抽奖升级与调校/上车过场判定**: 上车后卡在“升级与调校/车辆专精”。用户提供 `Downloads/调试日志/debug_upgrade_flow` 后确认红圈点位正确，但 `before_uandt_click` 亮度均值仅约 14.9，说明暗屏加载阶段模板已提前命中，菜单还不可交互；`after_uandt_click` 亮度约 83.7 才像稳定菜单。已新增 `_wait_for_uandt_ready()`：必须亮度不低（默认均值>=42）且连续 3 帧命中同一 UandT 位置，才允许进入。用户希望可点击时优先鼠标点，因此主路径为“菜单稳定后 SendMessage 鼠标点击升级与调校”；若未找到车辆专精，再用 `Down` 一次 + `Enter` 兜底复查。用户进一步反馈上车后无法正确 Esc 退回；已给 `_wait_for_uandt_ready()` 增加 `press_esc_when_missing=True`：上车后如果画面已亮但仍看不到 UandT，每隔约 1.2s 按一次 Esc 尝试退回车辆主菜单，直到 UandT 连续稳定命中。`车辆专精`识别阈值回到原版 0.62，并将车辆专精点击改为 SendMessage 单击。用户又反馈按 Enter 后已进入上车过场，但脚本仍因找不到 `rc.png` 判失败；查看截图确认 after_enter_select 已是黑屏加载/车辆过场。新增 `_is_boarding_transition()`：若 Enter 后全屏亮度均值 <=8 判定已进入上车/切车过场，跳过 `rc.png` 搜索和补 Enter，直接等待车辆菜单；补 Enter 后同样检测到过场则继续，不再误判失败。

---

## 2026-06-21 重构：两步法选车识别 + 模式1流程对齐上游

### 背景

06-20 几何参数实测修复后，发现 B600 (真目标) 和 B539 (误目标) 的等级标签视觉外观几乎完全一致，传统模板匹配 (TM_CCOEFF_NORMED) 无法区分——539 和 600 的数字笔画相似度 >0.95，任何阈值都救不了。

### 根因

旧 `find_new_consumable_car_strict` 流程是 **NEW 全屏扫 → B600 附近搜 → 车卡反推**，三个模板各自独立全屏匹配后“凑对”，导致 B539 车卡上的 NEW 角标 + B539 被误识为 B600 → 锁定了错误车辆。

### 修复：两步法识别 (vision.py)

**新流程**：
1. **Step 1**: 全屏跑 `newCC.png` 找候选车卡（必须是 22B-STI 车图，`MAIN_THRESHOLD=0.85`），NMS 去重
2. **Step 2**: 每个候选内部固定相对位置验 `newcartag.png` (NEW 角标) + `classB600.png` (等级标签)，`TAG_THRESHOLD=0.85` / `CLS_THRESHOLD=0.85`
3. 三者必须在同一张车卡内几何对齐，彻底杜绝“跨车卡凑对”

**保留能力**：
- Multi-scale (1.0/0.98/1.02/0.95/1.05 + `get_scales_to_try`)
- Gray + Edge 兜底（彩色 0.70~0.85 区间启用，`GRAY=0.62` / `EDGE=0.20`）
- 调试快照（`_save_strict_car_simple` 成功+失败都输出）
- 接口不变（`last_strict_car_meta` / `last_strict_car_click_points`）

**实测验证**：
- 负例（画面无目标）：输出 0 个目标 ✅
- 正例（画面有 2 个目标）：输出 2 个目标，无误检 ✅

### 修复：模式1 选车后流程对齐上游 (cj_logic.py)

**旧逻辑**：没找到 rc.png → 补 Enter → 再找 rc.png → 还找不到 → 检测黑屏过场 → 没黑屏 → **return False 停止**

**问题**：上车过场不一定是黑屏（`_is_boarding_transition` 只检测亮度≤8 的纯黑），导致车已上但程序以为没上，停止运行。

**新逻辑**（对齐上游 `latest_main.py`）：没找到 rc.png → **直接双 Enter 上车** → 进升级循环（`_wait_for_uandt_ready` 自动 ESC 找升级与调校）

### 清理
- 删除 `_debug_20260621_085058/`（调试产物）
- 删除 `_review_upstream/`（上游审查临时目录）
- 删除 `UPSTREAM_UPDATE_PLAN.md`（已执行完的合并方案）
- 删除 `vision.py.backup_*`（备份文件）
- 删除 `_fix_p.py`（临时脚本）
- vision.py 删除 6 个死代码函数共 171 行
- `.gitignore` 新增 `_debug_*/`、`*.backup_*`、`_review_upstream/`、`UPSTREAM_UPDATE_PLAN.md`

### 优化：超级抽奖选车翻页 2→3 页
- `cj_logic.py` `max_pages = 2` → `3`

### 更新：Focus Hook DLL (18:15)
- 从 `focus_hook` 项目复制新版 DLL 到 `assets/`
- 新版 hook 8 个 API（新增 GetFocus/GetActiveWindow/GetCursorPos/SetCursor）
- 新增调试日志写入 `%TEMP%\focus_hook_debug.log`
- 卸载时恢复 WndProc + 发送 WM_ACTIVATE 刷新窗口状态

### 修复：1600×900 分辨率下 race_logic 选车识别失败 (18:36)
- **现象**：用户 skillcar.png 模板匹配 0.388，识别到黑色空位
- **根因**：`get_scales_to_try(fast_mode=True)` 只取前 8 个缩放，1600×900 下 scale=1.0 排第 10 被排除
- **修复**：在 primary_scale 微调后、其它来源前优先插入 `1.0`，确保两种分辨率（1600/1778）下 1.0 都在 fast_mode 前 8 个里
- **验证**：用户模板 scale=1.0 得分 0.8862 ← 完美匹配
- **2026-06-19 超级抽奖计数器/误选车型修复**: 用户反馈成功专精后计数器不增加，且在没有符合条件车辆后误选“全新但非 22B/B600”的 SVX。修复：`cj_counter += 1` 移到“已进入车辆专精并执行技能路径”之后、`SPNE` 提前 return 之前，避免成功处理车辆不计数；`find_new_consumable_car_strict()` 的 B600 匹配阈值从 0.58 提高到 0.72；新增 `_verify_target_point_b600()`，车卡点击后、Enter 上车前二次校验 B600。后续用户反馈严格识别已高置信命中 B600，但点击/hover 后小区域二次匹配误杀；修复为优先使用严格识别阶段保存的 `last_strict_car_meta.class_score`（点击前置信度）通过二次校验，只有严格阶段分数不足时才用扩大后的局部区域兜底匹配。列表未找到满足【全新+B600+目标车型】条件的车辆时返回 `True` 结束超抽步骤，不再触发全局恢复。车辆列表右移翻页节奏放慢：单次 Right delay 0.10s、间隔 0.22s，翻页后等待 0.65s，避免列表滑动未完成就识别/点击。
- **2026-06-19 全部计数器审查**: 用户要求不只修超抽，还要检查循环跑图/批量买车/其他计数器。审查结论：跑图在 `restart.png` 完赛后才 `race_counter += 1`，超时重开不计数，逻辑基本正确；买车在一套购买确认键序列后 `car_counter += 1`，逻辑基本正确。增强：为跑图、买车、超抽都增加明确日志 `xxx计数 +1: 当前/目标`；修复 UI 待机状态会把任务进度/大循环重置成 `0/0` 的问题，改为停止/完成时保留最后计数，新任务开始时再初始化。用户反馈顶部任务卡片“执行: 0/99”一直不变，根因是 `update_running_ui()` 只更新运行面板 `lbl_runtime_progress`，未同步更新 `lbl_race/lbl_car/lbl_cj`；已增加任务名到顶部标签映射，三个卡片的“执行: x/y”随业务计数同步刷新。
- **2026-06-19 循环跑图选车兜底删除/调试记录/组合识别修复**: 用户反馈循环跑图日志显示“组合识别未命中”后又用 `skillcar.png` 单图兜底命中，导致未选正确车辆就开始跑图。解释：组合识别是同时匹配 `skillcar.png + liketag.png`，本应作为目标车辆确认；原代码组合失败后降级到单图 `skillcar.png` 阈值 0.68，过于危险。已删除两处单图兜底：组合未命中时只重新选品牌/翻页继续找组合，最终仍无组合目标则失败停止，禁止仅凭 `skillcar.png` 开始跑图。新增 `debug_race_car_select/`：组合识别未命中时保存 `screen_raw.png`、`screen_annotated.png`、`meta.json`，标注/记录 `skillcar.png`、`liketag.png` 全屏最佳分数、缩放、位置，以及最佳 skillcar 附近的 liketag 分数。用户提供 meta 显示 `skillcar.png` 最佳缩放 1.137，`liketag_near_skillcar` 最佳缩放 0.711，证明失败原因有两层：一是组合识别强制主图和子元素使用同一 scale；二是循环跑图调用组合识别时 `fast_mode=True` 只取前 8 个缩放，漏掉 1600 基准对应的 1.137。已修改 `find_image_with_element_multi()`，主图 skillcar 使用主缩放，子元素 liketag 在主图附近独立尝试全部缩放，并在命中日志输出“主缩放/标签缩放”；循环跑图两处组合识别改为 `fast_mode=False`、timeout 4s，确保能尝试 1.137 等完整缩放。用户指出全屏最佳 liketag 可能落到 BRZ 上，真正应该看同一车卡内 liketag；已增强 `debug_race_car_select` 标注：红框=skillcar，全屏绿框=全屏最佳 liketag（仅参考），黄框=skillcar 附近/同车卡内最佳 liketag（正式组合依据）。
- **2026-06-19 收尾整理**: 新增“调试截图”UI 勾选框，保存到 `config.json` 的 `debug_screenshots` 字段，默认关闭；`debug_race_car_select/`、`debug_strict_car/`、`debug_car_select/`、`debug_upgrade_flow/` 仅在开启时生成。清理项目根目录临时审查脚本/报告、调试拼图图片、`_review_axeroyf/`、`__pycache__/`（均进回收站）。README 更新本地打包、调试开关和当前核心流程说明。用户反馈勾选框不会实时把 `debug_screenshots` 写成 true；修复为 `CTkCheckBox(command=self.save_config)`，勾选/取消立即写入 config.json。
- **2026-06-20 Focus Hook 集成**: 按用户要求参考 `workspace/focus_hook`。新增 `focus_hook_manager.py`，内置 `LoadLibraryA` 远程注入与 `FreeLibrary` 卸载逻辑；复制 `focus_hook_x64.dll`、`focus_hook_x86.dll` 到 `assets/`，通过现有 `--add-data assets;assets` 随 exe 打包。UI 新增“Hook游戏窗口使其始终为焦点”勾选框，配置字段 `focus_hook_enabled`；勾选/取消立即保存 config。启动后若已启用，会自动尝试检测游戏窗口并注入；每次 `check_and_focus_game()` 成功定位游戏窗口后会确认 Hook；关闭软件时 `on_app_close()` 会先停止任务再自动卸载 Hook。
- **2026-06-19 上车后升级流程调试/收紧**: 新增 `debug_upgrade_flow/`，保存点击“升级与调校”和“车辆专精”前后截图；将 `UandT` 与 `clsldcn` 的灰度识别阈值收紧到 `0.72`，把点击“升级与调校”后的等待从 0.5s 增加到 1.2s，并把点击“上车”后的等待增加到约 5s，避免车辆/菜单未完全加载就过早点升级与调校。

---

## 反检测心跳检测 (AntiCheatMixin)

### 功能
1. **PrintWindow 健康检测**
   - 每 10 秒后台截图一次
   - 检测是否返回空 / 全黑
   - 连续 3 次异常则告警

2. **输入有效性验证**
   - 在已知安全状态下发送测试输入
   - 对比前后截图差异
   - 连续 3 次无变化则判定 PostMessage 被过滤

> 已按要求移除 EAC/BattlEye/Vanguard 等反作弊模块扫描。

3. ~~反作弊模块扫描~~（已移除 — 该检测方式不可靠）

### 使用方法
- 任务启动时自动开启 (`start_pipeline` → `start_anti_cheat_heartbeat`)
- 任务停止时自动关闭 (`stop_all` → `stop_anti_cheat_heartbeat`)

---

## 已知限制

1. **不能最小化** — 最小化窗口 DC 无像素，PrintWindow 失败
2. **窗口模式** — 独占全屏截图全黑
3. **管理员权限** — 游戏以管理员运行时，工具也必须管理员
4. **反作弊** — EAC/BattlEye/Vanguard 可能过滤 PostMessage（已加检测告警）

---

## TODO / 未来方向

- [ ] OCR 文字识别（已注释，可重新评估是否启用）
- [ ] 更智能的分辨率自适应（当前靠缩放比例 `get_scales_to_try`）
- [ ] 日志文件持久化（当前仅 UI 日志）
- [ ] 测试启动按钮 UI 放开（当前被注释）
