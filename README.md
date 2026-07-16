# FH6Auto - 后台模式版

基于 **Python + 图像识别 + 后台输入** 的 FH6 视觉自动化工具。

**本版本核心改动**:截图和输入全部后台化,游戏窗口无需在前台即可运行。集成 PP-OCRv6 ONNX 引擎识别比赛结果。

> 本项目仅供 Python 自动化技术交流与学习使用。

---

## ✅ 已适配 1974 马自达 #123 Mad Mike 808 Wagon 更高效率刷超跑，适合拥有通行证的玩家使用

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
- 输入:`PostMessage` 直接发 WM 消息给目标窗口句柄,点对点不抢全局键盘
- 长按模拟:`BackgroundInputManager._repeat_loop` 每 50ms 重发 `WM_KEYDOWN`,配合正确的 lParam 构造(scan code + extended flag + repeat count + prev state + transition state)

---

## 功能模块

### 方案切换
- 支持多方案配置，每个方案独立设置车辆、技能树、跑图张数等参数
- 方案1: 斯巴鲁 22B-STI 标准模式
- **方案2: 1974 马自达 #123 Mad Mike 808 Wagon 超抽模式**（需通行证）
  - 买车/超抽/卖车使用马自达，赛车使用斯巴鲁
  - 独立技能树路径和模板图片
- 可新建/删除/重命名方案

### 循环跑图（EventLab 新流程）
- ESC 进入主菜单 -> EventLab -> 搜索蓝图分享码 -> 自动开始比赛
- **OCR 完赛检测**: 集成 PP-OCRv6 tiny ONNX 模型，识别 "挑战完成" / "挑战失败" 文字
- 无需模板图片，OCR 直接识别屏幕文字，更可靠
- 按键后二次 OCR 验证，防止按键未生效
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
- **严格选车识别**: `find_skill_car_strict` 四重验证 - skillcar.png 全屏匹配 (≥0.75) + 右下象限 liketag 或 drivingtag 验证 (≥0.75) + **等级标签反向校验 (≥0.70)**
- **等级标签反向校验**: 在车卡底部搜索区域匹配 B600 等级标签模板 (`anti_class_b600.png`)，排除错误等级的车辆
- **drivingtag 双验证**: 驾驶中的车独有驾驶图标,比 liketag 更歧义;drivingtag 命中时额外加成
- **多分辨率支持**: 缩放范围 0.40~1.20,覆盖 720p~1080p
- **多线程并行匹配**: 多尺度 matchTemplate 并行执行，速度提升 ~7 倍
- Multi-scale + Gray/Edge 兜底
- 上车后等菜单稳定,再进入"升级与调校 / 车辆专精"

### 串联与循环
跑图 -> 买车 -> 超级抽奖 -> 卖车 -> 下一轮

### 更新检测
- 启动时自动检查 GitHub Releases 是否有新版本
- 最新版: 右上角显示绿色 "✅ 最新版"
- 有新版本: 右上角闪烁提示 + 弹出对话框，点击确定打开下载页面
- 点击右上角版本号可随时打开 Releases 页面

### 调试截图开关
- 界面提供"调试截图"勾选框,状态保存到 `config.json` 的 `debug_screenshots` 字段。
- 默认关闭,避免长期运行产生大量调试图片

### DirectML 加速选项
- 界面提供 "DirectML加速" 勾选框
- ✅ 勾选: OCR 推理使用 GPU (DirectML)，释放 CPU 给游戏
- ❌ 不勾选: OCR 使用 CPU（限制为半数核心），游戏性能影响最小
- 不勾选时占用约 100MB 显存
- 无 GPU 或驱动不兼容时自动回退 CPU

---

## 技术细节

### OCR 引擎
- 模型: PP-OCRv6 tiny recognition (ONNX 格式, 4.3MB)
- 来源: PaddlePaddle HuggingFace 官方预转换模型
- 推理: onnxruntime (DirectML 可选)
- 仅使用 recognition 模型，跳过 detection（游戏 UI 文字位置固定）
- CPU 推理耗时 ~3ms，DirectML GPU 推理 ~2ms

### CPU 优化
- ONNX Runtime 线程限制为 `CPU核心数 / 2`
- OpenCV 内部线程设为 1（由 ThreadPoolExecutor 接管并行）
- ThreadPoolExecutor 最大 workers 也限制为 `CPU核心数 / 2`
- 确保游戏运行时有足够 CPU 资源

---

**下载说明：** 运行 `FH6Auto.exe`（Steam）或 `FH6Auto_xbox.exe`（Xbox）即可，`assets/` 和 `images/` 已打包在内。
