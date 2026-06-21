# FH6Auto - 后台模式版

基于 **Python + 图像识别 + 后台输入** 的 FH6 视觉自动化工具。

**本版本核心改动**:截图和输入全部后台化,游戏窗口无需在前台即可运行。

> 本项目仅供 Python 自动化技术交流与学习使用。

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
- **修复**:改为两步法 - 先全屏匹配 `newCC.png` 找候选车卡(必须是 22B-STI 车图)→ 每个候选内部固定位置验 NEW + B600,三者几何对齐才放行

### 2026-06-21 修复:模式1 选车后停止运行
- **现象**:选车后找不到 `rc.png` 上车按钮,程序停止
- **根因**:fork 旧逻辑在没找到 rc.png 且没检测到黑屏过场时直接 `return False`,但上车过场不一定是纯黑屏
- **修复**:对齐上游 - 没找到 rc.png 就直接双 Enter 上车,然后进入升级循环(循环内自动 ESC 找升级与调校)

---

## 功能模块

### 循环跑图
- 自动进入菜单 → 创意中心 → EventLab
- 自动输入蓝图分享代码
- 自动匹配车辆与赛事
- 支持按次数重复执行

### 批量买车
- 自动进入车辆收藏
- 定位目标品牌和车辆
- 重复购买指定数量

### 自动卖车(移除消耗品车辆)
- 自动进入车辆收藏 → 购买与出售
- 识别并移除已消耗的车辆(`removecarobject.png` + `removecar.png`)
- P 键切换详情状态重搜 + 多页翻页查找
- 移除确认自动点击,失败自动 ESC 跳过

### 超级抽奖
- 自动点技能路径
- **两步法选车识别**:先全屏匹配车卡模板 (newCC) 确认是目标车型 → 再在车卡内部固定位置验证 NEW 角标 + B600 等级标签,三者几何对齐才放行
- Multi-scale + Gray/Edge 兜底
- 上车后等待菜单稳定,再进入"升级与调校 / 车辆专精"

### 串联与循环
跑图 → 买车 → 超级抽奖 → 卖车 → 下一轮

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

## 致谢

感谢原项目 [YOUSTHEONE/FH6Auto](https://github.com/YOUSTHEONE/FH6Auto) 提供的基础实现与思路。

感谢二改项目 [AxeroYF/FH6](https://github.com/AxeroYF/FH6) 提供的二改实现与思路。

感谢 [lazydog28/mc_auto_boss](https://github.com/lazydog28/mc_auto_boss) 提供的后台实现和思路。

本版本在二改项目的基础上增加了后台截图/输入能力。
