<<<<<<< HEAD
# FH6Auto

基于 **Python + 图像识别 + 输入自动化** 的 FH6 视觉自动化工具。  
支持循环跑图、批量买车、超级抽奖、技能矩阵配置、多模块串联、循环执行、异常恢复与游戏重启守护。

> 本项目仅供 Python 自动化技术交流与学习使用。请勿用于商业用途、破坏游戏平衡或违反相关服务条款。  
> 因使用本工具造成的任何后果，包括但不限于账号异常、封禁、数据损失等，均由使用者自行承担。

## 项目来源

本项目基于 [YOUSTHEONE/FH6Auto](https://github.com/YOUSTHEONE/FH6Auto) 复制与二次维护。  
当前版本在原项目基础上，针对现有游戏版本和本地运行环境做了更新与优化，重点包括：

- 适配当前游戏 UI 流程与图像识别状态。
- 优化主界面布局比例，删除“支持作者 / 检查更新”入口。
- 取消独立迷你监视窗口，在主界面内显示运行状态、暂停、停止和耗时统计。
- 优化超级抽奖选车识别，采用“全新标签 + B600 等级 + 目标车卡片”三段验证。
- 保留外部 `images` 模板覆盖机制，便于后续继续适配游戏界面变化。
- 保留 `config.json` 用户配置文件，启动时自动补全缺失配置项。
- 移除已不使用的更新检查依赖，减少运行环境负担。

## 功能模块

### 循环跑图

- 自动进入菜单与创意中心 / EventLab。
- 自动输入蓝图分享代码。
- 自动匹配目标车辆与目标赛事。
- 支持按设定次数重复执行。

### 批量买车

- 自动进入车辆收藏。
- 自动定位目标品牌和目标车辆。
- 自动重复购买指定数量车辆。

### 超级抽奖

- 自动进入升级 / 熟练度界面。
- 按自定义技能路径点技能。
- 支持技能点耗尽后自动结束模块。
- 选车时先识别“全新”标签，再验证附近的 `B 600` 等级和目标车辆卡片，减少误选其他车辆。

### 串联与循环

可将多个模块串联为流水线：

```text
跑图 -> 买车 -> 超级抽奖 -> 下一轮
```

可配置每个模块完成后是否继续到下一模块，也可配置总循环次数。

## 运行环境

- Windows
- Python 3.10+ 建议
- 游戏语言：简体中文
- 输入法：英文键盘
- 推荐游戏设置：自动转向、自动挡

安装依赖：

```powershell
pip install -r requirements.txt
```

启动程序：

```powershell
python main.py
```

## 使用前准备

### 车辆准备

请先准备用于跑图的车辆：

- 斯巴鲁 Impreza 22B-STi Version
- 调校至 S2 900
- 加入收藏
- 保持默认涂装

### 游戏与系统设置

- 游戏已正常启动。
- 游戏语言设置为简体中文。
- 输入法切换到英文键盘。
- 尽量关闭会影响画面颜色的滤镜、HDR 或特殊后处理。
- 运行过程中不要频繁切换窗口，以免影响截图识别。

## 界面参数

主界面可配置：

- 跑图次数
- 买车次数
- 超级抽奖次数
- 蓝图分享代码
- 大循环次数
- 单局超时时间
- 模块完成后是否继续
- 游戏闪退后是否自动重启
- 自动重启命令

主界面还包含运行监控栏，用于显示：

- 运行状态
- 当前任务
- 当前任务进度
- 大循环进度
- 本任务耗时
- 总运行时间
- 跑图 / 买车 / 超抽模块累计耗时
- 暂停 / 停止控制按钮

## 技能路径

在“超级抽奖”区域可通过方向按钮配置技能路径：

- 上
- 下
- 左
- 右

点击“清除矩阵”可重置路径。蓝色格子表示当前技能树行走路径。

## 快捷键

- `F8`：停止当前任务并释放按键。
- `F9`：暂停 / 继续当前任务。
- `F3`：测试找图流程。

停止任务时，程序会尝试释放方向键、确认键、返回键、空格、持续按住的 `W` 等输入，避免异常退出后卡键。

## 图片模板

项目使用 `images` 目录中的模板图进行识别。程序会优先读取外部 `images` 目录，便于用户自行替换模板以适配不同分辨率、画质和游戏 UI 状态。

常见模板包括：

- `skillcar.png`：跑图刷技能点车辆。
- `CCbrand.png`：消耗品车辆品牌。
- `consumablecar.png`：用于点技能的消耗品车辆。
- `newcartag.png`：黄色“全新”标签。
- `classB600.png`：`B 600` 等级标签。
- `newCC.png`：目标车辆卡片。

超级抽奖选车当前采用三段验证：

```text
全新标签 -> B600 等级 -> 目标车辆卡片
```

只有三段都通过时才会点击车辆进入后续流程。

如果游戏更新导致识别失败，通常需要重新截图并替换对应模板。

## 配置文件

用户配置保存在项目根目录的 `config.json`。  
程序启动时会自动补全缺失字段，并兼容迁移旧版配置文件名。

重要配置包括：

- `race_count`
- `buy_count`
- `cj_count`
- `share_code`
- `global_loops`
- `skill_dirs`
- `auto_restart`
- `restart_cmd`
- `race_timeout`

## 打包

项目提供 `build.bat`，可使用 PyInstaller 打包：

```powershell
.\build.bat
```

打包输出：

```text
dist\FH6Auto.exe
```

如果打包失败，请先确认已安装 PyInstaller：

```powershell
pip install pyinstaller
```

## 技术栈

- `customtkinter`：桌面 UI
- `opencv-python`：模板匹配与图像识别
- `numpy`：图像数组处理
- `pyautogui`：截图与基础自动化
- `pydirectinput`：游戏场景输入模拟
- `pynput`：全局热键监听
- `Pillow`：图像加载与处理
- `pywin32` / `ctypes`：窗口聚焦、DPI 适配与底层输入

## 维护说明

本项目属于对原 FH6Auto 的本地适配与维护版本。  
由于游戏 UI、分辨率、语言文本、画质设置和模板图都会影响识别结果，后续维护重点通常是：

- 更新 `images` 模板。
- 调整识别阈值。
- 修正游戏流程跳转。
- 优化异常恢复逻辑。
- 继续简化 UI 与配置项。

## 致谢

感谢原项目 [YOUSTHEONE/FH6Auto](https://github.com/YOUSTHEONE/FH6Auto) 提供的基础实现与思路。
=======
# Game Window Tester

测试任意游戏窗口是否支持**后台截图**和**后台输入**，无需窗口在前台。

## 原理

| 功能 | API | 说明 |
|------|-----|------|
| 后台截图 | `PrintWindow(hwnd, dc, 3)` | flag=3 即 `PW_RENDERFULLCONTENT`，Win10 1903+，能截 D3D/UE/硬件加速窗口 |
| 后台输入 | `PostMessage` / `SendMessage` | 点对点发 WM 消息给目标窗口，不抢全局键鼠 |

### 关键发现：WM_MOUSEMOVE 前置

直接发 `WM_LBUTTONDOWN` 大部分游戏不响应。**必须先发 `WM_MOUSEMOVE`**，游戏才会处理后续的鼠标点击消息。键盘 `WM_KEYDOWN` 无此限制。

## 快速开始

```bash
# 安装依赖
pip install pywin32 Pillow numpy

# 运行
python forza_test.py

# 打包为 exe
build.bat
```

## 功能

| 功能 | 说明 |
|------|------|
| 🔄 窗口选择 | 下拉框列出所有可见窗口，显示 hwnd / 类名 / 客户区尺寸 / DPI |
| 📸 单次截图 | PrintWindow flag=3 后台截图，显示尺寸和像素均值 |
| ▶ 实时预览 | 持续截图显示在 UI，可调 1~30 FPS |
| ⚠ 黑屏检测 | 像素均值 < 5 自动标红警告 |
| ⌨ 按键测试 | 选按键 → 发送 WM_KEYDOWN/UP |
| 🖱 鼠标测试 | 坐标输入或直接点预览图，三种发送方式可选 |
| 🔐 管理员权限 | 启动检测 + 自动提权 |
| 📐 DPI 感知 | 自动检测目标窗口 DPI 缩放，坐标自动转换 |

## 鼠标点击三种方式

| 方式 | API | 特点 |
|------|-----|------|
| **Post** | `PostMessage` | 异步，不阻塞，发完就返回 |
| **Send** | `SendMessage` | 同步，等窗口处理完才返回 |
| **Both** | 两者都发 | 间隔 100ms，用于对比测试 |

三种都先发 `WM_MOUSEMOVE` 再发 `WM_LBUTTONDOWN/UP`。

## 适用引擎参考

### 截图 (PrintWindow) ✅ 可用

- Unreal Engine 4/5（窗口模式）
- Unity DX11/DX12（窗口模式）
- Source / Source 2
- CryEngine / RE Engine / id Tech
- 自研 DX 引擎（魔兽世界、FF14、剑网三）
- OpenGL 窗口（Minecraft Java 等）
- Chromium / Electron 应用

### 截图 ❌ 不可用

- 独占全屏（Exclusive Fullscreen）
- DRM / 硬件叠加层
- 部分反作弊 Hook GDI

### 输入 (PostMessage + WM_MOUSEMOVE) ✅ 可用

- UE4/5 默认输入系统
- Unity 旧版 Input（GetKey）
- 大部分窗口化游戏
- 网页游戏 / Electron

### 输入 ❌ 不可用

- DirectInput 游戏（老 FPS）
- Raw Input 游戏（CS2、Valorant、Apex）
- XInput 纯手柄游戏
- 带反作弊的竞技游戏（封号风险）

## 约束

- **不能最小化** — 最小化窗口 DC 无像素，PrintWindow 失败
- **窗口模式** — 独占全屏截图全黑
- **管理员权限** — 游戏以管理员运行时，工具也必须管理员
- **反作弊** — 带 EAC/BattlEye/Vanguard 的游戏慎用

## 日志示例

```
[12:55:01] 已选中: "Forza Horizon 5"
  hwnd=0x1A2B3C  class=UnrealWindow
  客户区=1280x720  窗口Rect=(100, 50, 1380, 770)  DPI x1.50
[12:55:03] ✅ PrintWindow 成功 | 尺寸=1280x720 | 均值=87.34
   客户区 GetClientRect=1280x720 | 截图尺寸=1280x720
[12:55:05] 🖱 点击 逻辑(640,360) | 客户区=1280x720 | DPI x1.50 | 方式=PostMessage
  → PostMessage 物理(960,540) WM_MOUSEMOVE+LBUTTONDOWN/UP
```
>>>>>>> 97f527f (feat: add backend capture/input (PrintWindow + PostMessage))
