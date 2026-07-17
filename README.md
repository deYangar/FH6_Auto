# FH6Auto - 后台模式版

基于 **Python + 图像识别 + 后台输入** 的 FH6 视觉自动化工具。

**本版本核心改动**: 截图和输入全部后台化,游戏窗口无需在前台即可运行。集成 PP-OCRv6 ONNX 引擎（det + rec）识别比赛结果和按钮文字。

> 本项目仅供 Python 自动化技术交流与学习使用。

---
## ✅ 已适配 7月14日更新后，新的刷技能点途径。目前由于时间关系，方案1还是用斯巴鲁刷超抽，可能会亏，没通行证的玩家建议暂时停止使用后面的刷超抽功能，跑图没问题。后面找到新的适合车辆后更新
## ✅ 已适配 1974 马自达 #123 Mad Mike 808 Wagon 更高效率刷超抽，适合拥有通行证的玩家使用

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
- 方案1: 斯巴鲁 22B-STI 标准模式
- **方案2: 1974 马自达 #123 Mad Mike 808 Wagon 超抽模式**（需通行证）
  - 买车/超抽/卖车使用马自达，赛车使用斯巴鲁
  - 独立技能树路径和模板图片
- 可新建/删除/重命名方案

### 循环跑图（EventLab 新流程）
- 选车检测（drivingtag）→ ESC 退回主菜单 → EventLab → 搜索蓝图分享码 → 自动开始比赛
- **OCR 完赛检测**: 截取画面底部 1/5，rec 模型识别按钮文字
  - 成功画面: `Esc重试 Enter继续` → OCR 识别"继续"/"退出"判定场景
  - 失败画面: `Esc退出 Enter重试`
  - 非末轮按"重试"对应键，末轮按"退出"/"继续"对应键
  - 检测到 stuck（90s 无结果）→ ESC → 主菜单 → 重新走 EventLab 流程
- 按键后等待验证，防止按键未生效

### 批量买车
- 自动进入车辆收藏
- 定位目标品牌和车辆
- 重复购买指定数量

### 自动卖车(移除消耗品车辆)
- 自动进入车辆收藏 → 购买与出售
- 识别并移除已消耗的车辆(`removecarobject.png` + `removecar.png`)
- 多页翻页查找
- 移除确认自动点击,失败自动 ESC 跳过

### 超级抽奖
- 自动点技能路径
- **严格选车识别**: `find_skill_car_strict` 四重验证 - skillcar.png 全屏匹配 (≥0.75) + 右下象限 liketag 或 drivingtag 验证 (≥0.75) + **等级标签反向校验 (≥0.70)**
- **等级标签反向校验**: 在车卡底部搜索区域匹配 B600 等级标签模板 (`anti_class_b600.png`)，排除错误等级的车辆
- **drivingtag 双验证**: 驾驶中的车独有驾驶图标,比 liketag 更唯一;drivingtag 命中时额外加分
- **多分辨率支持**: 缩放范围 0.40~1.20,覆盖 720p~1080p
- **多线程并行匹配**: 多尺度 matchTemplate 并行执行，速度提升 ~7 倍
- Multi-scale + Gray/Edge 兜底
- 上车后等待菜单稳定,再进入"升级与调校 / 车辆专精"

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
  - `debug_race_car_select/`
  - `debug_strict_car/`
  - `debug_car_select/`
  - `debug_upgrade_flow/`
  - `debug/miss/`（灰度匹配未命中截图）

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

## 技术细节

### OCR 引擎
- 模型: PP-OCRv6 tiny detection + recognition (ONNX 格式)
- 来源: PaddlePaddle HuggingFace 官方预转换模型
- Detection 模型: PP-OCRv6_tiny_det_onnx (1.78MB)
- Recognition 模型: PP-OCRv6_tiny_rec_onnx (4.3MB)
- 推理: onnxruntime (CPU) 或 onnxruntime-directml (GPU)
- Detection 找文字区域 → Recognition 逐区域识别
- Detection 失败时自动回退到固定区域 rec-only，不影响流程
- CPU 推理 rec 耗时 ~3ms，DirectML GPU 推理 ~2ms

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

本项目使用本地打包,不依赖 GitHub Actions:

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

> Xbox 版编译时会临时替换 input_handler.py / race_logic.py 为 Xbox 版本,编译完成后自动恢复。

---

## 重要约束

- **不能最小化** - 最小化窗口 DC 无像素,PrintWindow 失败
- **窗口模式** - 独占全屏截图全黑
- **管理员权限** - 游戏以管理员运行时,工具也必须管理员

---

## 快捷键

- `F8`:停止当前任务并释放按键
- `F9`:暂停 / 继续
- `F3`:测试找图流程

---

## 更新日志

### v1.2.6.0 (2026-07-17)

**🔍 OCR 完赛检测重写**
- 不再匹配"挑战完成"/"挑战失败"关键字，改为识别画面底部按钮文字
- 成功画面: Esc重试 Enter继续 → 识别"继续"判定成功
- 失败画面: Esc退出 Enter重试 → 识别"退出"判定失败
- 根据是否末轮 + 成功/失败，自动选择正确的按键

**🐛 OCR UTF-8 解码异常修复**
- 修复 onnxruntime CPU 后端在特定输入 shape 下触发 `UnicodeDecodeError` 的 bug
- rec 推理添加 try/except 兜底，异常时跳过该文字区域

**🐛 超级抽奖 brand_retry_done 修复**
- 修复 `brand_retry_done` 变量未初始化导致的逻辑异常
- 重新选品牌后删过车 → 允许再次重试选品牌（不再卡死）
- 翻页上限从 5 页恢复到 10 页

**⚡ OCR 引擎预热**
- 跑图开始时立即加载 OCR 引擎，不再等到蓝图检测阶段懒加载

**🔧 DirectML 实时切换**
- 跑图中切换 DirectML 勾选框自动重建 OCR 引擎，无需重启任务

**📦 恢复 Xbox 专属逻辑**
- `race_logic_xbox.py` 从 main 分支恢复，包含 Xbox 前台输入 + 分享码输入前 10s 等待

### v1.2.5.0 (2026-07-16)

**🏁 EventLab 新流程重写**
- 适配最新游戏更新后的 EventLab 比赛流程
- 移除地图收藏功能（不再需要）
- 移除 `playenent.png` 匹配（旧流程遗留）
- 默认分享码更新为 `103435586`

**🔍 OCR 完赛检测（首次集成）**
- 集成 PP-OCRv6 tiny ONNX 模型识别比赛结果
- **模型**: PP-OCRv6 tiny recognition（ONNX 格式，仅 4.3MB）
- **来源**: PaddlePaddle HuggingFace 官方预转换模型
- **识别**: "挑战完成" -> WIN，"挑战失败" -> FAIL
- 按键二次验证: 释放按键后等 1s 再次 OCR，若结果不变则重按一次

**⚡ DirectML 加速选项**
- ✅ 勾选: OCR 推理使用 GPU (DirectML)，占用约 100MB 显存
- ❌ 不勾选: OCR 使用 CPU，限制为半数核心
- 无 GPU 或驱动不兼容时自动回退 CPU

**📦 依赖变更**
- 新增: `onnxruntime-directml`（替代 `onnxruntime`，包含 DirectML 支持）
- 新增: `pyyaml`（读取 OCR 模型字符字典）

---

### v1.2.4.0 (2026-07-13)

**🗺️ 地图已收藏功能**
- 新增"地图已收藏"复选框，勾选后跳过分享码输入，PageDown × 7 直接导航
- **⚠️ 注意：用来刷点的图必须是切到收藏时的第一个！**
- 蓝图的 VEI 赛事信息检测对两条路径均生效

**⏱️ Xbox 版本分享码输入超时**
- Xbox 版本新增"输入前等待(秒)"设置框，默认 10 秒
- 超时等待放在搜索框打开后、输入数字前
- 仅 Xbox 版本可见，Steam 版本不显示

**🔧 超级抽奖方案1优化，黑屏恢复改进**
- 模式1 上车后若检测到黑屏过渡，画面恢复后自动切换慢速 Esc 模式（3s 间隔）
- 第一波亮起时仍保持原有 1.2s 快速 Esc 节奏

### v1.2.3.0 (2026-07-11)

**🚗 跑图选车等级标签反向校验**
- `find_skill_car_strict` 新增第四重验证：B600 等级标签模板反向校验
- 使用独立模板 `images/anti_class_b600.png`，与方案的 class_image 分离

**🔧 Bug 修复**
- 修复 `_save_strict_car_simple` 末尾误粘贴代码导致崩溃
- 恢复方案1 classB600.png 为原始模板

### v1.2.2.0 (2026-07-10)

**🔧 错误处理改进**
- 全项目 34 处静默吞错改为带日志输出
- 涉及配置读写、模板匹配、截图、坐标计算等核心环节

**🚗 超级抽奖逻辑增强**
- 翻页搜索从 3 页扩展到 5 页
- 新增品牌重试机制：5 页未找到 → 重新选品牌 → 仍未找到才退出

**🗑️ 删除车辆逻辑增强**
- 翻页搜索从 5 页扩展到 10 页
- 同样新增品牌重试机制

**📦 合并 dev 分支**
- PNG 压缩模板缓存
- `find_image_gray` 未命中时保存调试截图

---

### v1.2.1.0 (2026-07-08)

**🚗 新增方案2: Mad Mike 马自达超抽模式**
- 适配 **1974 马自达 #123 Mad Mike 808 Wagon**
- 方案独立的技能树路径和模板图片
- 支持方案切换（新建 / 删除 / 重命名）

**⚡ 多线程并行匹配优化**
- `ThreadPoolExecutor` 并行执行多尺度 `matchTemplate`
- 17 个尺度并行匹配从 **3.04s 降至 0.41s**，加速 **~7.4 倍**

**🔧 模板匹配改进**
- `matchTemplate` 加 mask 排除黄色高亮边框
- `get_scales_to_try` 扩展比例覆盖
- 去除 HSV 兜底选车逻辑

**🎮 Xbox 分享码输入修复（独立版本）**
- Xbox 文本框改为前台 SendInput 真实键盘输入
- 编译产物为 `FH6Auto_xbox.exe`

**✨ 更新检测功能**
- 启动时自动检查 GitHub Releases
- 右上角版本状态指示

**🐛 Bug 修复**
- 删除所有 "按 P 切换详情" 重试逻辑
- 修复 B600 等级标签硬编码问题
- 修复 `_log_buffer` 竞争条件

---

### v1.2.0.0 (2026-07-07)

**上游同步** (来自 [AxeroYF/FH6](https://github.com/AxeroYF/FH6) v4.1.0):
- 新增 `recognition_config.py` - 36 套识别预设配置
- `vision.py` 新增 10 个识别方法
- `cj_logic.py` 新增刷图车切换逻辑
- `race_logic.py` 新增蓝图失效检测 + 赛事评价弹窗处理

**车辆识别匹配系统重构**:
- `find_combo` 改为返回最高分候选
- 子元素缩放范围绑定主模板
- 评分权重调整

**新增 `find_skill_car_strict` 严格匹配方法**:
- skillcar.png 全屏匹配 (≥0.75) + 右下象限 liketag/drivingtag 验证
- **drivingtag 双验证**: 驾驶中独有驾驶图标
- 多分辨率支持: 缩放范围 0.40~1.20

**诊断系统**:
- JSONL 事件日志 + 截图保存到 `diagnostic_reports/`

---

## Bug 修复记录

### 2026-07-17 修复: OCR rec 推理 UTF-8 解码异常
- **现象**: 跑图 OCR 检测时 `'utf-8' codec can't decode byte 0xb2`
- **原因**: onnxruntime CPU 后端在处理特定 shape 的输入张量时内部触发 UTF-8 解码
- **修复**: rec 推理添加 try/except 兜底 + 边界校验，异常时跳过该文字区域；DirectML 后端不受影响

### 2026-07-17 修复: 超级抽奖重新选品牌后卡死
- **现象**: 第一轮 10 页未找到 → retry → 重选品牌后删了一辆车 → 后续又 10 页未找到 → 直接停止
- **原因**: `brand_retry_done` 未初始化且成功删除车辆后未重置
- **修复**: 初始化 `brand_retry_done = False`；每次成功找到并删除车辆后重置标志

### 2026-06-18 修复: 数字输入重复
- **现象**: 输入 `890169683` 变成 `8899001166`
- **原因**: `lParam=0`,PostMessage 缺少 scan code 和 transition state
- **修复**: 硬编码 `SCAN_MAP`,正确构造 lParam;数字/字母额外发 `WM_CHAR`

### 2026-06-18 修复: 方向键卡死(菜单上下震荡)
- **现象**: 卡在开始竞赛,菜单上下轮询不停
- **原因**: 方向键是 extended keys,lParam bit 24 必须为 1
- **修复**: `SCAN_MAP` 硬编码方向键 scan code + `extended=True`

### 2026-06-18 修复: 鼠标点击不生效
- **现象**: 识别到 eventlab 但无任何点击动作
- **原因**: 误删 `import win32api`,被 `except Exception: pass` 静默吞掉
- **修复**: 恢复 `import win32api`

### 2026-06-18 修复: startw 点击后不进赛事
- **现象**: 跑完几轮后,找到 startw.png 但不进入下一圈
- **原因**: `PostMessage` 鼠标点击在某些按钮上不被识别为"确认"
- **修复**: `click_with_confirm()` - 点击后额外按 Enter 确认

### 2026-06-18 修复: 按键状态累积(多轮后菜单卡死)
- **现象**: 跑几轮后菜单上下震荡,新按键被旧按键淹没
- **原因**: 上轮 W/UP 残留未释放
- **修复**: `release_all()` 每轮开始前强制释放所有按键

### 2026-06-21 重构: 两步法选车识别
- **现象**: B539 车卡被误识为 B600
- **根因**: NEW 角标和 B600 等级标签各自全屏独立扫描后"凑对"
- **修复**: 改为两步法 - 先全屏匹配 newCC.png → 候选内部固定位置验 NEW + B600

### 2026-06-21 修复: 1600×900 分辨率下选车识别失败
- **现象**: skillcar.png 匹配得分极低(0.388)
- **根因**: scale=1.0 被 fast_mode 排除
- **修复**: 优先插入 `1.0`

### 2026-07-07 修复: skillcar 误选当前装备车
- **现象**: bot 选中了当前装备车 GMC Syclone 1991 而非 skillcar
- **修复**: 创建 `find_skill_car_strict` 严格匹配方法,提高阈值至 0.75

### 2026-07-07 修复: 驾驶中的 skillcar 识别不到
- **现象**: 驾驶状态下 liketag 位移,固定位置验证失败
- **修复**: liketag 改为右下象限区域搜索 + drivingtag 双验证

### 2026-07-07 修复: 低分辨率下 skillcar 漏匹配
- **现象**: 720p 下 scale≈0.55,被 `min_scale=0.60` 砍掉
- **修复**: base_scales 下限从 0.60 降到 0.40

---

## 致谢

感谢原项目 [YOUSTHEONE/FH6Auto](https://github.com/YOUSTHEONE/FH6Auto) 提供的基础实现与思路。

感谢二改项目 [AxeroYF/FH6](https://github.com/AxeroYF/FH6) 提供的二改实现与思路。

感谢 [lazydog28/mc_auto_boss](https://github.com/lazydog28/mc_auto_boss) 提供的后台实现和思路。

本版本在二改项目的基础上增加了后台截图/输入能力。
