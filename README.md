# FH6Auto - 后台模式版

基于 **Python + 图像识别 + 后台输入** 的 FH6 视觉自动化工具。

当前版本：**v1.3.3**

**本版本核心改动**: 超抽/删车流程稳定与提速——OCR 筛选选车提速 2~3 倍 + 三阶段点击 fallback（PR #29，@hui-shao）；后台车辆专精加点与全局恢复稳定性重构（PR #28，@AriaSulT）；修复 YOLO 等级标签二次校验误杀真目标。截图和输入全部后台化，游戏窗口无需在前台即可运行。

> 本项目仅供 Python 自动化技术交流与学习使用。

---
## ✅ 已适配 7月14日更新后的新刷技能点途径。方案1已适配使用 Revuelto 刷超抽，无需通行证！方案2适配 1974 马自达 #123 Mad Mike 808 Wagon 更高效率刷超抽，适合拥有通行证的玩家使用

---

## 后台化改动说明

| 项目 | 原版 | 本版 |
|------|------|------|
| 截图 | `ImageGrab.grab()` / `pyautogui.screenshot()` | `PrintWindow(hwnd, dc, 3)` |
| 键盘输入 | `SendInput` / `pydirectinput` | `PostMessage WM_KEYDOWN/UP` |
| 鼠标输入 | 物理光标移动 + 点击 | `PostMessage WM_MOUSEMOVE + WM_LBUTTONDOWN/UP` |
| 窗口聚焦 | 强制 `SetForegroundWindow` | 不强制前台,后台运行 |
| 物理鼠标 | 被脚本移动 | 完全自由,不受干扰 |

**原理**:
- 截图:`PrintWindow` flag=3 (`PW_RENDERFULLCONTENT`),Win10 1903+ 可截 D3D/UE 硬件加速窗口
- 输入:`PostMessage` 直接发 WM 消息给目标窗口句柄,点对点不抢全局键鼠
- 长按模拟:`BackgroundInputManager._repeat_loop` 每 50ms 重发 `WM_KEYDOWN`,配合正确的 lParam 构造(scan code + extended flag + repeat count + prev state + transition state)

---

## 功能模块

### 方案切换
- 支持多方案配置，每个方案独立设置车辆、技能树、跑图次数等参数
- **方案1:  适配 兰博基尼 Revuelto 刷超抽**（无通行证方案）
  - 买车/超抽/卖车使用Revuelto，赛车使用斯巴鲁
- **方案2: 1974 马自达 #123 Mad Mike 808 Wagon 超抽模式**（需通行证）
  - 买车/超抽/卖车使用马自达，赛车使用斯巴鲁
  - 独立技能树路径和模板图片
- 可新建/删除/重命名方案

### 循环跑图（EventLab 新流程）
- **OCR 视觉导航选车**（v1.2.10.0+）: 按 `race_filter` 配置的文字目标筛选（默认 `收藏 + 复古拉力赛车 + 传奇`，用于定位跑图车辆斯巴鲁 22B），实时 OCR 列表 + 黄绿边框定位高亮行，自动适配不同账号的车辆列表，替代旧版固定按键导航
- **OCR 上车检测**: 中心区域（558×287 居中矩形比例）识别"上车"文字，有则 Enter 上车，无则车辆已在驾驶
- ESC 退回主菜单 → EventLab → 搜索蓝图分享码 → 自动开始比赛
- **OCR 完赛检测**: 截取画面底部 1/5，rec 模型识别按钮文字
  - 成功画面: `Esc重试 Enter继续` → OCR 识别"继续"/"退出"判定场景
  - 失败画面: `Esc退出 Enter重试`
  - 非末轮按"重试"对应键，末轮按"退出"/"继续"对应键
  - 检测到 stuck（可自定义超时）→ ESC → 主菜单 → 重新走 EventLab 流程
- 按键后等待验证，防止按键未生效

### 批量买车
- 自动进入车辆收藏
- 定位目标品牌和车辆
- 重复购买指定数量

### 自动卖车(移除消耗品车辆)
- 自动进入车辆收藏 → 购买与出售
- **OCR 视觉导航筛选**（v1.2.10.0+）: 按方案 `sell_filter` 配置的文字目标勾选（方案1 默认 `重复项 + S2 + 顶级超跑 + 全轮驱动`，方案2 默认 `S1 + 漂移赛车 + 后轮驱动 + 传奇`），筛选前 X 重置残留勾选，目标缺失时报错中止（防卖错车），替代旧版固定按键导航
- **OCR 上车检测**: 驾驶收藏车时用 OCR 识别"上车"文字替代 `rc.png` 图片匹配
- 识别并移除已消耗的车辆(`removecarobject.png` + `removecar.png`)
- 车卡模板因高亮失配时，优先打开并验证当前焦点车辆；验证失败后才向右移动一格，避免跳过剩余车辆
- 多页翻页查找
- 移除确认自动点击,失败自动 ESC 跳过

### 超级抽奖
- 自动点技能路径
- **严格选车识别**: `find_new_consumable_car_strict` 组合验证目标车卡、"全新"角标和当前方案等级标签
- **视觉顺序优先**: 多辆车同时达标时按界面列顺序、再按从上到下选择，避免模板分数更高的下一辆车抢先被选中
- **跨帧确认**: 默认要求目标连续两帧出现在相近位置，过滤菜单动画、悬停变化造成的瞬时误判
- **多分辨率支持**: 缩放范围 0.40~1.20,覆盖 720p~1080p
- **多线程并行匹配**: 多尺度 matchTemplate 并行执行，速度提升 ~7 倍
- Multi-scale + Gray/Edge 兜底
- 上车后等待菜单稳定,再进入"升级与调校 / 车辆专精"

### YOLO 识别（v1.3.0+）
- 超抽选车与删车默认走 YOLO 深度学习识别：全新车卡 + NEW 角标双目标检测，速度与准确性相较模板匹配大幅优化
- NEW 角标交叉验证 + 等级标签二次校验（YOLO 模式直接用模型自身的等级标签识别过硬校验，模型不可用时降级模板校验），防止误选非全新车
- 模型外置：首次启动自动释放到 exe 旁 `onnx_models/yolo_best.onnx`，自训模型直接覆盖即生效，免重编译
- 界面提供开关与置信度滑条（默认 0.65）；关闭或模型缺失自动降级模板匹配
- 附带标注训练工具包 `yolo_tool/`：网页截图标注（模型辅助打标）→ 一键续训 → 导出 → 部署，详见 `yolo_tool/README.md`

### 串联与循环
跑图 -> 买车 -> 超级抽奖 -> 卖车 -> 下一轮

### 更新检测
- 启动时自动检查 GitHub Releases 是否有新版本
- 最新版: 右上角显示绿色 "✓ 最新版"
- 有新版本: 右上角闪烁提示 + 弹出对话框，点击确定打开下载页面
- 点击右上角版本号可随时打开 Releases 页面

### 调试截图开关
- 界面提供"调试截图"勾选框,状态保存到 `config.json` 的 `debug_screenshots` 字段。
- 默认关闭,避免长期运行产生大量文件。
- 开启后才会生成:
  - `debug_strict_car/`
  - `debug_car_select/`
  - `debug_upgrade_flow/`
  - `debug/miss/`（灰度匹配未命中截图）
  - `debug/filter_nav/`（筛选导航 OCR 调试）

### Focus Hook 开关
- 界面提供"Hook游戏窗口使其始终为焦点"勾选框，状态保存到 `config.json` 的 `focus_hook_enabled` 字段。
- 勾选后：
  - 软件启动后会自动尝试 Hook 已打开的游戏窗口；
  - 每次检测到游戏窗口时会确认 Hook 是否已注入；
  - 关闭软件时自动卸载 Hook。
- Hook DLL 来自 [Hook_FocusLoss](https://github.com/deYangar/Hook_FocusLoss) 项目：`assets/focus_hook_x64.dll`、`assets/focus_hook_x86.dll`。
- Hook 原理：注入目标进程后，替换窗口 WndProc 拦截失焦消息（WM_ACTIVATE/WM_KILLFOCUS/WM_ACTIVATEAPP 等），同时 Hook 8 个焦点相关 API（GetForegroundWindow/GetFocus/GetActiveWindow/SetCursorPos/ClipCursor/ShowCursor/GetCursorPos/SetCursor），让游戏始终认为自己处于焦点状态。
- DLL 注入后会自动写调试日志到 `%TEMP%\focus_hook_debug.log`。

### DirectML 加速选项
- 界面提供 "DirectML加速" 勾选框
- ✅ 勾选: OCR 推理使用 GPU (DirectML)，释放 CPU 给游戏
- ❌ 不勾选: OCR 使用 CPU（限制为半数核心），游戏性能影响最小
- 勾选状态实时生效，跑图中切换自动重建 OCR 引擎
- 无 GPU 或驱动不兼容时自动回退 CPU

---

## 配置文件说明（config.json）

程序运行目录下的 `config.json` 保存全部配置。它由程序在**每次改动界面控件时自动重写**（`json.dump` 整个字典），因此：

- 顶层字段会与 `schemes[当前方案]` **自动互相同步**，带「自动同步」标注的字段无需手改。
- 缺失的字段会在启动时自动补全默认值，旧版配置自动迁移。

> ⚠️ **不要给 config.json 加 `//` 或 `#` 注释。** 程序用标准 `json.load` 解析，遇到注释会判定「配置损坏」并**自动把整套配置重置为默认值**（方案、次数、分享码全部丢失）。
>
> 想知道每个字段的含义，请对照仓库里的 **`config.example.json`**（带行内中文注释，仅供对照参考，**不要直接改名成 config.json**），或看下方字段表。

### 顶层字段

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `current_scheme` | int | 0 | 当前方案索引（0=方案1，1=方案2） |
| `schemes` | array | — | 方案列表，每项字段见下表 |
| `global_loops` | int | 10 | 全局循环次数（整个流程跑多少轮） |
| `auto_restart` | bool | false | 游戏掉线/崩溃时自动重启 |
| `restart_cmd` | string | `start steam://run/2483190` | 自动重启游戏的命令 |
| `race_timeout` | int | 600 | 单局跑图超时检测（秒） |
| `race_start_wait` | int | 15 | 每轮发车前等待时长（秒），等游戏展示车辆+加载，加载慢的机器可调大 |
| `stuck_timeout` | int | 60 | 卡死检测超时（秒，最小 10） |
| `debug_screenshots` | bool | false | 调试截图开关（保存识别截图到 debug/） |
| `focus_hook_enabled` | bool | false | 窗口焦点钩子（保持游戏窗口可后台截图/发键） |
| `auto_close_game` | bool | false | 任务完成后自动关闭游戏 |
| `auto_shutdown` | bool | false | 任务完成后自动关机 |
| `diagnostic_mode` | bool | false | 诊断模式（输出详细追踪日志） |
| `use_directml` | bool | true | DirectML 加速 OCR（占少量显存） |
| `use_yolo` | bool | true | YOLO 识别（超抽选车/删车），关闭或模型缺失自动降级模板匹配 |
| `yolo_conf` | float | 0.65 | YOLO 置信度阈值（0.10~0.95，界面滑条可调） |
| `sharecode_timeout` | int | 10 | 输入分享码前等待秒数（仅 Xbox 版） |
| `class_image` / `race_count` / `buy_count` / `cj_count` / `sell_count` / `skill_dirs` / `share_code` / `cj_mode` / `chk_1~4` / `next_1~4` / `name` | — | — | **自动同步**自 `schemes[当前方案]`，无需手改 |

### 流程阶段字段（四阶段串联）

四个阶段：**1.循环跑图(race) → 2.批量买车(buy) → 3.超级抽奖(cj) → 4.移除车辆(sell)**。每个阶段有一组 `计数 + 继续开关 + 跳转目标`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `race_count` / `buy_count` / `cj_count` / `sell_count` | int | 对应阶段的执行次数（局数/台数/抽数） |
| `chk_1`~`chk_4` | bool | 该阶段跑完后**是否继续**到下一阶段；为 false 则流程在此停止 |
| `next_1`~`next_4` | int | 继续时**跳转到的阶段号**（1=跑图 2=买车 3=超抽 4=删车）。默认 `1→2→3→4→1` 成环；`next_4` 填 1~3 跳回前序阶段，填 4 或更大则继续删车 |

> 例：默认配置下跑图(1)跑完跳买车(2)，买车跑完跳超抽(3)，超抽跑完跳删车(4)，删车跑完回到跑图(1)，如此循环 `global_loops` 轮。把某个 `chk_N` 设为 false 即可让流程在第 N 阶段后停下。

### 方案字段（schemes 数组每一项）

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | 方案名称（仅显示用） |
| `class_image` | string | 车辆等级图标模板（方案1 `classS2829.png`=S2，方案2 `classS1702.png`=S1） |
| `race_count`/`buy_count`/`cj_count`/`sell_count` | int | 本方案各阶段执行次数 |
| `skill_dirs` | array | 技能树点击顺序（`up`/`down`/`left`/`right`） |
| `share_code` | string | 跑图蓝图数字代码 |
| `cj_mode` | int | 超级抽奖模式：1=从我的车辆开始，2=从设计与喷涂开始 |
| `chk_1`~`chk_4` / `next_1`~`next_4` | bool/int | 本方案的阶段串联设置（含义同上） |
| `sell_filter` | array | 删车筛选选项（OCR 视觉导航目标，须与游戏筛选面板文字一致） |
| `race_filter` | array | 跑图筛选选项（OCR 视觉导航目标，须与游戏筛选面板文字一致） |

---

## 技术细节

### OCR 引擎
- 模型: PP-OCRv6 small detection + recognition (ONNX 格式)
- 来源: PaddlePaddle HuggingFace 官方预转换模型
- Detection 模型: PP-OCRv6_small_det_onnx (9.4MB)
- Recognition 模型: PP-OCRv6_small_rec_onnx (20.2MB, 字典 18708 字符)
- 推理: onnxruntime (CPU) 或 onnxruntime-directml (GPU)
- Detection 找文字区域 → Recognition 逐区域识别
- Detection 失败时自动回退到固定区域 rec-only，不影响流程

### CPU 优化
- ONNX Runtime 线程限制为 `CPU核心数 / 2`
- OpenCV 内部线程设为 1（由 ThreadPoolExecutor 接管并行）
- ThreadPoolExecutor 最大 workers 也限制为 `CPU核心数 / 2`
- 确保游戏运行时有足够 CPU 资源

---

## 运行环境

- Windows 10/11
- Python 3.10+
- 游戏语言:简体中文
- 推荐:自动转向、自动挡

```powershell
pip install -r requirements.txt
python main.py
```

---

## 本地打包

项目支持本地打包；`build.bat` 会优先使用仓库中的 `.venv\Scripts\python.exe`，不存在时再使用系统 Python。推送到 `main` 后也可由 GitHub Actions 自动构建。

```bat
build.bat            :: 编译 Steam 版 (FH6Auto.exe)
build.bat steam      :: 同上
build.bat xbox       :: 编译 Xbox 版 (FH6Auto_xbox.exe)
build.bat all        :: 编译两个版本
```

输出文件:

```text
dist\FH6Auto.exe        :: Steam 版,全后台输入
dist\FH6Auto_xbox.exe   :: Xbox 版,含前台 SendInput 分享码修复
```

`assets/`、`images/` 与 `onnx_models/` 会随 exe 一起打包。

版本号统一读取 `config.py` 中的 `CURRENT_VERSION`，本地无需维护额外的 `version.json`。

> Xbox 版通过运行时 hook（`runtime_hook_xbox.py`）切换平台模块，编译期不再做文件 swap 污染。

---

## 重要约束

- **不能最小化** - 最小化窗口 DC 无像素,PrintWindow 失败
- **窗口模式** - 独占全屏截图全黑
- **管理员权限** - 游戏以管理员运行时,工具也必须管理员

### 已知限制

- 任务1当前通过 `race_filter` 缩小车辆范围后直接选择当前焦点卡片。请确保筛选结果唯一，或首次运行时观察是否选中预期的斯巴鲁 22B；后续版本将增加车型身份与上车状态的二次确认。
- 任务4的“当前焦点优先验证”逻辑已通过自动化回归测试，正式长时间运行前仍建议先进行一轮实机验证。

---

## 快捷键

- `F8`:停止当前任务并释放按键
- `F9`:暂停 / 继续
- `F3`:测试找图流程

---

## 更新日志

完整版本更新日志与 Bug 修复记录已迁移至 [CHANGELOG.md](CHANGELOG.md)，最新发布见 [GitHub Releases](https://github.com/deYangar/FH6_Auto/releases)。

## 致谢

感谢原项目 [YOUSTHEONE/FH6Auto](https://github.com/YOUSTHEONE/FH6Auto) 提供的基础实现与思路。

感谢二改项目 [AxeroYF/FH6](https://github.com/AxeroYF/FH6) 提供的二改实现与思路。

感谢 [lazydog28/mc_auto_boss](https://github.com/lazydog28/mc_auto_boss) 提供的后台实现和思路。

本版本在二改项目的基础上增加了后台截图/输入能力。
