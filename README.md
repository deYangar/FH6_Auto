# FH6Auto - 后台模式版

基于 **Python + 图像识别 + 后台输入** 的 FH6 视觉自动化工具。

**本版本核心改动**:截图和输入全部后台化,游戏窗口无需在前台即可运行。

> 本项目仅供 Python 自动化技术交流与学习使用。

---

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

### 循环跑图
- 自动进入菜单 -> 创意中心 -> EventLab
- 自动输入蓝图分享代码
- 自动匹配车辆与赛事
- 支持按次数重复执行

### 批量买车
- 自动进入车辆收藏
- 定位目标品牌和车辆
- 重复购买指定数量

### 自动卖车(移除消耗品车辆)
- 自动进入车辆收藏 -> 购买与出售
- 识别并移除已消耗的车辆(`removecarobject.png` + `removecar.png`)
- 多页翻页查找
- 移除确认自动点击,失败自动 ESC 跳过

### 超级抽奖
- 自动点技能路径
- **严格选车识别**: `find_skill_car_strict` 三重验证 - skillcar.png 全屏匹配 (≥0.75) + 右下象限 liketag 或 drivingtag 验证 (≥0.75)
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

### Focus Hook 开关
- 界面提供"Hook游戏窗口使其始终为焦点"勾选框，状态保存到 `config.json` 的 `focus_hook_enabled` 字段。
- 勾选后：
  - 软件启动后会自动尝试 Hook 已打开的游戏窗口；
  - 每次检测到游戏窗口时会确认 Hook 是否已注入；
  - 关闭软件时自动卸载 Hook。
- Hook DLL 来自 [Hook_FocusLoss](https://github.com/deYangar/Hook_FocusLoss) 项目：`assets/focus_hook_x64.dll`、`assets/focus_hook_x86.dll`。
- Hook 原理：注入目标进程后，替换窗口 WndProc 拦截失焦消息（WM_ACTIVATE/WM_KILLFOCUS/WM_ACTIVATEAPP 等），同时 Hook 8 个焦点相关 API（GetForegroundWindow/GetFocus/GetActiveWindow/SetCursorPos/ClipCursor/ShowCursor/GetCursorPos/SetCursor），让游戏始终认为自己处于焦点状态。
- DLL 注入后会自动写调试日志到 `%TEMP%\focus_hook_debug.log`。

---

## 运行环境

- Windows 10/11
- Python 3.10+
- 游戏语言:简体中文
- 输入法:英文键盘
- 推荐:自动转向、自动挡

```powershell
pip install -r requirements.txt
python main.py
```

---

## 本地打包

本项目使用本地打包,不依赖 GitHub Actions:

```bat
build.bat
```

输出文件:

```text
dist\FH6Auto.exe
```

`assets/` 与 `images/` 会随 exe 一起打包。

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

### v1.2.1.0 (2026-07-08)

**🚗 新增方案2: Mad Mike 马自达超抽模式**
- 适配 **1974 马自达 #123 Mad Mike 808 Wagon**，更高效率刷超抽
- 买车 / 超抽 (CJ) / 卖车 使用马自达品牌车辆，赛车仍使用斯巴鲁 22B
- 方案独立的技能树路径: right -> right -> up -> up -> up
- 方案独立的模板图片（CCbrand / consumablecar / newCC / removecarobject / classS1702 等）
- 马自达模板按宽度等比缩放对齐斯巴鲁尺寸，保证多尺度匹配兼容性
- 支持方案切换（新建 / 删除 / 重命名），每个方案独立配置

**⚡ 多线程并行匹配优化**
- `find_skill_car_strict` 和 `find_new_consumable_car_strict` 采用 `ThreadPoolExecutor` 并行执行多尺度 `matchTemplate`
- 全局 `cv2.setNumThreads(1)` 禁用 OpenCV 内部多线程，由 Python 线程池接管并行
- 实测 17 个尺度并行匹配从 **3.04s 降至 0.41s**，加速 **~7.4 倍**
- 线程数 = CPU 核心数 - 1，保留一个核心给 UI 和游戏

**🔧 模板匹配改进**
- `matchTemplate` 加 mask 排除选中车卡黄色高亮边框，匹配分从 0.73 提升至 0.83
- `get_scales_to_try` fast_mode 从 8 个比例扩展到 ~22 个，覆盖 0.4~1.5 全范围
- 去除 HSV 兜底选车逻辑，避免马自达多车型场景下选错车
- `find_new_consumable_car_strict` 找不到目标车时返回 None，由翻页逻辑接管

**✨ 更新检测功能**
- 启动时自动检查 GitHub Releases 是否有新版本
- 最新版: 右上角显示绿色 "✓ 最新版"
- 有新版本: 右上角红橙闪烁提示 + 弹出对话框显示更新内容，点击确定打开下载页面
- 点击右上角版本号可随时打开 Releases 页面

**🐛 Bug 修复**
- 删除所有 "按 P 切换详情" 重试逻辑（cj_logic / race_logic / sell_logic），简化状态机
- 修复 `find_skill_car_strict` 和 `find_new_consumable_car_strict` 中 B600 等级标签硬编码问题，改为动态读取 `class_image` 配置
- 修复 `_log_buffer` 竞争条件导致的启动崩溃

---

### v1.2.0.0 (2026-07-07)

**上游同步** (来自 [AxeroYF/FH6](https://github.com/AxeroYF/FH6) v4.1.0):
- 新增 `recognition_config.py` - 36 套识别预设配置,支持通过 `config.json` 覆盖参数
- `vision.py` 新增 10 个识别方法:动态阈值校准、智能找图、多元素验证、HSV 色彩预筛等
- `cj_logic.py` 新增刷图车切换逻辑:自动检测当前车并切换到收藏的技能车
- `race_logic.py` 新增蓝图失效检测 + 赛事评价弹窗处理
- `flow_common.py` 新增 5 个工具函数 + 5 张模板图片

**车辆识别匹配系统重构**:
- `find_combo` 改为返回最高分候选(而非第一个通过阈值的)
- 子元素缩放范围绑定到主模板 ±0.15,防止小模板在极小缩放下误匹配
- 评分权重调整:边缘 20%->5%,彩色 30%->35%,中心 15%->20%

**新增 `find_skill_car_strict` 严格匹配方法**:
- skillcar.png 全屏匹配 (car ≥ 0.75) + 右下象限 liketag/drivingtag 验证 (≥ 0.75)
- **drivingtag 双验证**: 驾驶中的车独有驾驶图标(黄绿色方向盘),比 liketag 更唯一
- liketag 验证从固定点改为右下象限区域搜索,容忍不同分辨率下的比例差异
- 多分辨率支持: 缩放范围 0.40~1.20,覆盖 720p~1080p
- `race_logic.py` 和 `cj_logic.py` 全部切换为 `wait_for_skill_car_strict`

**诊断系统**:
- JSONL 事件日志 + 截图保存到 `diagnostic_reports/`
- 日志级别过滤 + 日志导出
- 关闭时零开销

**其他改进**:
- `log()` 方法支持 `level` 参数和自动级别推断
- `find_new_consumable_car_strict` 缩放优先级优化
- `get_scales_to_try` 下限从 0.45 降到 0.35
- 移除过时的"启动前先将键盘设置为英文键盘"提示

---

## Bug 修复记录

### 2026-06-18 修复:数字输入重复
- **现象**:输入 `890169683` 变成 `8899001166`
- **原因**:`lParam=0`,PostMessage 缺少 scan code 和 transition state,游戏把 KEYDOWN/KEYUP 搞混
- **修复**:硬编码 `SCAN_MAP`,正确构造 lParam;数字/字母额外发 `WM_CHAR`

### 2026-06-18 修复:方向键卡死(菜单上下震荡)
- **现象**:卡在开始竞赛,菜单上下轮询不停
- **原因**:方向键是 extended keys,lParam bit 24 必须为 1;`MapVirtualKey` 返回 numpad scan code 导致 KEYUP 不匹配
- **修复**:`SCAN_MAP` 硬编码方向键 scan code + `extended=True`;`_repeat_loop` 递增 repeat count;`key_up` 清除计数

### 2026-06-18 修复:鼠标点击不生效(eventlab 识别到但不点击)
- **现象**:识别到 eventlab 但无任何点击动作
- **原因**:误删 `import win32api`,`win32gui.MAKELONG` 抛出 `AttributeError`,被 `except Exception: pass` 静默吞掉
- **修复**:恢复 `import win32api`,改回 `win32api.MAKELONG`

### 2026-06-18 修复:startw 点击后不进赛事(多轮后失效)
- **现象**:跑完几轮后,找到 startw.png 但不进入下一圈
- **原因**:`PostMessage` 鼠标点击在某些按钮上不被识别为"确认"
- **修复**:`click_with_confirm()` - 点击后额外按 Enter 确认;每轮开始前 `release_all()` 清空状态

### 2026-06-18 修复:按键状态累积(多轮后菜单卡死)
- **现象**:跑几轮后菜单上下震荡,新按键被旧按键淹没
- **原因**:上轮 W/UP 残留未释放,`_repeat_loop` 持续发消息,消息队列堆积
- **修复**:`release_all()` - 每轮开始前 + 点击前 + 跑图结束时强制释放所有按键,清空 `_pressed_keys` 和 `_repeat_counts`

### 2026-06-21 重构:两步法选车识别
- **现象**:B539 车卡被误识为 B600,上了错误的车
- **根因**:NEW 角标和 B600 等级标签各自全屏独立扫描后"凑对",不同车卡的标签可能错误组合
- **修复**:改为两步法 - 先全屏匹配 `newCC.png` 找候选车卡(必须是 22B-STI 车图)-> 每个候选内部固定位置验 NEW + B600,三者几何对齐才放行

### 2026-06-21 修复:模式1 选车后停止运行
- **现象**:选车后找不到 `rc.png` 上车按钮,程序停止
- **根因**:fork 旧逻辑在没找到 rc.png 且没检测到黑屏过场时直接 `return False`,但上车过场不一定是纯黑屏
- **修复**:对齐上游 - 没找到 rc.png 就直接双 Enter 上车,然后进入升级循环(循环内自动 ESC 找升级与调校)

### 2026-06-21 修复:1600×900 分辨率下循环跑图选车识别失败
- **现象**:skillcar.png 匹配得分极低(0.388),识别到黑色空位而非实际车辆
- **根因**:`get_scales_to_try(fast_mode=True)` 只取前 8 个缩放,1600×900 下 scale=1.0 排第 10 被排除,而用户模板正是按 1600 原生分辨率截的
- **修复**:在 primary_scale 微调后优先插入 `1.0`,确保 1600×900 和 1778×1000 两种分辨率下 1.0 都在 fast_mode 前 8 个里

### 2026-07-07 修复:skillcar 误选当前装备车
- **现象**:循环跑图开始时,bot 选中了当前装备车 GMC Syclone 1991 而非 skillcar
- **根因**:`race_logic.py` 里 4 处 skillcar 匹配直接调 `wait_for_image_with_element_multi`,硬编码 `final_threshold=0.7`,0.707 通过了阈值。匹配发生在左侧车辆详情大面板上
- **修复**:创建 `find_skill_car_strict` 严格匹配方法 - skillcar.png 全屏匹配 (≥0.75) + 右下象限 liketag/drivingtag 验证 (≥0.75),无灰度兜底。`race_logic.py` 和 `cj_logic.py` 全部切换

### 2026-07-07 修复:驾驶中的 skillcar 识别不到
- **现象**:用户正在驾驶 skillcar 时,liketag 向左位移,原位出现驾驶图标,导致固定位置验证失败
- **根因**:liketag 在驾驶状态下会左移 ~10%,原位变为驾驶图标(黄绿色方向盘标志)
- **修复**:1) liketag 验证从固定点改为右下象限区域搜索; 2) 新增 `drivingtag.png` 模板,liketag OR drivingtag 双验证; 3) drivingtag 命中时 +0.05 加分(全屏唯一)

### 2026-07-07 修复:低分辨率下 skillcar 漏匹配
- **现象**:720p (1389×782) 屏幕下 skillcar 匹配 scale≈0.55,被 `min_scale=0.60` 砍掉
- **修复**:`find_skill_car_strict` base_scales 下限从 0.60 降到 0.40,`get_scales_to_try` 下限从 0.45 降到 0.35,`find_combo` sub_scales 下限从 0.50 降到 0.35

---

## 致谢

感谢原项目 [YOUSTHEONE/FH6Auto](https://github.com/YOUSTHEONE/FH6Auto) 提供的基础实现与思路。

感谢二改项目 [AxeroYF/FH6](https://github.com/AxeroYF/FH6) 提供的二改实现与思路。

感谢 [lazydog28/mc_auto_boss](https://github.com/lazydog28/mc_auto_boss) 提供的后台实现和思路。

本版本在二改项目的基础上增加了后台截图/输入能力。
