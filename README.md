# FH6Auto - 后台模式版

基于 **Python + 图像识别 + 后台输入** 的 FH6 视觉自动化工具。

当前版本：**v1.2.11.2**

**本版本核心改动**: 截图和输入全部后台化,游戏窗口无需在前台即可运行。集成 PP-OCRv6 ONNX 引擎（det + rec）识别比赛结果和按钮文字。

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

> Xbox 版编译时会临时替换 input_handler.py / race_logic.py 为 Xbox 版本,编译完成后自动恢复。

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

### v1.2.11.2 (2026-07-22)

**🧵 任务生命周期与闪退修复**
- 心跳和后台输入线程改用独立停止事件，并在释放 OCR、GDI 和输入资源前等待旧任务退出
- 暂停/终止后立即开始新任务时改为排队启动，避免旧线程与新任务并发访问原生资源
- Focus Hook 注入/卸载增加超时，并复用游戏进程中已有的 Hook 模块
- 增加单实例互斥，避免多个工具实例同时控制同一游戏窗口
- 修复停止任务时截图缓存释放引用错误

**🚗 任务3/任务4识别修复**
- 任务3从“模板最高分优先”改为“视觉顺序优先”，并增加连续两帧空间确认，避免跳过当前带“全新”角标的车辆
- 任务4车卡模板漏检时立即验证当前焦点车辆，不再先连续右移后捡漏；验证失败时仅右移一格

**📦 构建与验证**
- 本地构建优先使用 `.venv`，版本号统一读取 `config.CURRENT_VERSION`
- 新增 6 项回归测试，覆盖线程退出、截图缓存释放入口、车辆视觉排序及任务4焦点兜底
- 使用 Python 3.12.13 + PyInstaller 6.21.0 完成打包和 EXE 冒烟测试

### v1.2.11.0 (2026-07-22)

**🐛 筛选导航 Bug 修复（v1.2.10.0 回归）**
- 修复卡底检测误判：高亮在可见区内移动时 OCR 文字不变，旧版连续 2 次不变即判到底 → 新版加入高亮行下标追踪 + 64×64 像素差兜底，高亮在动就不判卡底
- 修复循环检测误判：OCR 噪声导致 page_key 偶然重复即判循环 → 新版加 ≥3 步门槛 + 像素校验（画面有变化不判循环）
- 修复 `_scroll_to_top` 同类误判：文字不变时加像素差确认，高亮还在上移就不停
- 修复短目标 OCR 容错：S1/S2/A 等 ≤3 字符目标被读成 SI/51/S 时精确匹配全 miss → 新增常见易混字符模糊匹配（I↔1, 5↔S, Z↔2），S2 不会误匹配 S1
- 以上修复覆盖所有筛选场景（跑图选车/删车筛选，Steam/Xbox 共用 FilterNavMixin）

**👍 评价弹窗改为"取消"**
- 完赛评价弹窗动作从"点踩"改为"取消"（下移两格 + Enter），Steam/Xbox 同步

**🔧 功能调整**
- 方案1 购买 Revuelto 滚动次数 4→5
- 蓝图搜索网络波动重试：OCR 只识别到"确定"无"挑战"入口 → 自动关掉弹窗重新搜索（最多 2 次），Steam/Xbox 同步
- 阶段3 搜索逻辑提取为 `_input_share_code()` 方法，支持重试复用

**🔇 日志降噪**
- 更新检查超时从 `[ERROR]` + traceback 文件改为一句提示 `[更新检查] 网络不通，跳过（不影响使用）`，超时 10s→5s
- 终极安全匹配调试截图加 `is_debug_screenshots_enabled()` 门控，不开调试不再写盘
- 游戏进程检测日志细化：区分 tasklist 命令失败 / 游戏没开 / 进程在但窗口找不到 / PID 解析失败四种情况

**🐛 进程检测修复**
- `tasklist` 无匹配时某些 Windows 版本返回退出码 1，`check_output` 直接抛异常 → 改用 `subprocess.run` 不管退出码都读 stdout

### v1.2.10.0 (2026-07-21)

**🔍 筛选导航重写：OCR 视觉导航替代固定按键**
- 旧版删车筛选/跑图选车用固定“按 N 下”导航，其他账号因车辆拥有情况不同（列表条目缺失/增减）会错位
- 新版按文字目标导航：Y 打开筛选 → X 重置残留勾选 → 逐键 OCR 搜索，目标入屏瞬间高亮正好在它上面，直接 Enter（零过头）→ 复选框像素差验证（阈值 120，实测 220+）→ 未命中自动回滚误勾 + 点击兜底 → ESC 关闭
- 关键发现：滚动页高亮行在截图里没有静态视觉特征（逐行全特征扫描证实），靠运动学规律解决——列表滚动时高亮贴屏幕底边，目标入屏那一刻高亮 == 目标
- 筛选前 X 重置残留勾选；目标选项缺失 → 报错放弃该环节，不带错误筛选继续跑（防卖错车）
- 新增 `filter_nav.py`（FilterNavMixin）+ `ocr_onnx.py` 新增 `detect_lines_in_region()` 逐行 OCR

**👎 评价弹窗改为 OCR 点踩**
- 赛事评价弹窗（点赞/点踩/取消）从图片匹配改为 OCR 识别中央区域“点踩”文字
- 动作从“Enter 点赞”改为“下移一格 + Enter 点踩”

**🐛 Bug 修复（7 项）**
- 修复二次 OCR 验证“按键没生效重按”分支必崩（未定义变量）
- 修复 lambda 捕获 except 块变量（Python3 出 except 块即删除）
- 修复 find_image_ultimate_safe 所有 scale 模板加载失败时调试块 UnboundLocalError
- 修复 config.json 损坏日志缺少异常原因
- 修复 recovery.py 裸 except
- 修复启动崩溃（log 节流变量未初始化）
- 修复截图缓存中毒（PrintWindow 失败后 GDI 对象被反复复用 → 释放缓存 + 全新重试）

**⚡ 性能优化**
- OCR：rec 输入宽 320→240（耗时 -20~25%）；det 预处理缓冲复用（零分配）；筛选面板 det max_side 960→416（提速 ~44%）
- 截图：DC/位图按 (hwnd,w,h) 缓存复用（省 ~1ms/帧）；GDI 失败返回 None 不再崩 bot
- 模板匹配：灰度/边缘模板按 scale 惰性缓存（原每个候选重复 cvtColor+Canny）
- 日志：100ms 批量节流渲染（原每条 after(0)）
- 筛选按键提速：间隔 0.1→0.06/0.04s（~2 倍）；卡底检测加丢键容错
- 完赛检测间隔 1.0→0.5s
- 多线程匹配线程数 cpu-1 → cpu//2，留更多核心给游戏

**🧹 代码清理（约 370 行）**
- 删除死方法 _save_race_car_debug（Steam+Xbox 共 224 行）、start_test_boot、死按钮、孤儿文件、8 处未用导入
- OCR 上车检测抽取为共享方法（原三处重复实现）
- 调试截图统一为通用 _save_point_debug
- Xbox 版 OCR 区域对齐 Steam 版

**🔧 OCR 模型**
- 换用 PP-OCRv6 small（det 9.4MB + rec 20.2MB，字典 18708 字符），移除 tiny（错误率过高）

**⚙️ 配置变更（自动迁移，无需手动改）**
- 方案新增 `sell_filter`（方案1 默认 `["重复项","S2","顶级超跑","全轮驱动"]`，方案2 默认 `["S1","漂移赛车","后轮驱动","传奇"]`）
- 方案新增 `race_filter`（默认 `["收藏","复古拉力赛车","传奇"]` = Mad Mike 808 Wagon）
- 其他账号适配：只需把选项文字改成自己列表里的实际文字

**🔄 Xbox 版选车同步**
- Xbox 版跑图选车从旧版图片匹配升级为与 Steam 版一致的 OCR 视觉导航 + OCR 上车检测

**🧪 离线验证工具**
- 新增 `test_filter_nav.py`：用真实筛选面板截图离线验证 OCR 行识别/高亮行检测/目标定位，无需启动游戏

### v1.2.9.0 (2026-07-20)

**⚠️ 升级须知：本次更新改动较大，升级前请先删除旧版的 `images/` 和 `cache/` 文件夹，程序启动时会自动释放最新模板并重建缓存。**

**🚗 方案1 适配 Revuelto 刷超抽（无通行证方案）！！！**
- 方案1 重命名为「方案1 - 无通行证用Revuelto刷超抽」
- 技能树路径 skill_dirs 改为 `['up','up','up','right','right']`（适配 Revuelto 技能树 13->9->5->1->2->3）
- 步骤顺序 next_4 默认改为 1（2341 循环）
- 等级标签 classB600.png -> classS2829.png，反向校验 anti_class_b600.png -> anti_class_S2829.png
- 分享码改为 167982162
- DirectML 加速默认开启

**🔍 筛选导航替代图片匹配选车**
- 跑图选车统一用固定按键导航 + OCR 检测“上车”（Y -> Enter -> 35×down -> Enter -> 19×down -> Enter -> ESC -> Enter），替代旧版 skillcar/liketag/drivingtag 图片匹配
- 删车筛选用固定按键导航（方案1: down×2/6/14/28，方案2: down×7/10/32/5），替代 repitem/CCbrand 图片匹配
- 删车上车检测统一用 OCR 识别“上车”，替代 rc.png
- 删除删车 brand_retry 逻辑，筛选后直接逐车删除

**📊 列优先排序选车**
- 图片匹配候选从“最高分优先”改为列优先排序（1->5->9->2->6->10->3->7->11->4->8->12），同列内从上到下，列间从左到右
- 影响 `find_image_ultimate_safe`（删车）和 `find_skill_car_strict`（跑图选车）

**🗑️ 删车匹配修复**
- `find_image_ultimate_safe` 新增 `top_threshold`/`bot_threshold` 参数，删车场景设为 0.0 跳过顶部文字和右下角校验
- 修复 debug 截图 `parallel_results` 未定义异常
- 新增 debug 截图保存到 `debug/ultimate_safe/`

**🚫 删车筛选后空结果检测**
- 筛选完按 ESC 后 OCR 扫描，识别到“没有可用的车辆”自动跳过删车环节（Enter -> X -> ESC×3）

**🐛 DPI 缩放修复**
- `SetProcessDpiAwareness(2)` 移至 main.py 第一行
- 窗口恢复检测增加 DPI 状态日志和缩放比例探测

**🛒 买车流程方案区分**
- 方案1 买车后 down×4，方案2 down×1
- 修复 use_send=True 导致按键翻倍问题

**🔧 其他改进**
- 模板路径查找改为 APP_DIR/scheme -> INTERNAL_DIR/scheme -> APP_DIR/root -> INTERNAL_DIR/root
- 超抽选车 TAG/CLS 位置从硬编码改为动态计算（用 newCC.png 自动定位）
- 方案2模板图片更新（newcartag/classS1702/newCC/removecarobject）
- images/ 根目录7个重复文件清理，模板归入 scheme_1/
- OCR 完赛检测区域从下 1/5 收窄到下 1/10
- 日志分类精细化（ERROR/WARN/DEBUG）
- 大循环间隔加画面恢复检测（防黑屏加载）
- 多线程匹配 max_workers 从 cpu//2 改为 cpu-1

### v1.2.8.1 (2026-07-19)

**🚗 选车方式与方案绑定**
- 方案1（斯巴鲁）：保留旧版图片匹配选车（skillcar + liketag + drivingtag）
- 方案2（马自达）：使用固定按键导航 + OCR 检测"上车"（Y → Enter → 35×down → Enter → 19×down → Enter → ESC → Enter）
- 切换方案时自动切换选车方式

**🗑️ 删除车辆筛选与方案绑定**
- 方案1：保留旧版图片匹配筛选（repitem + CCbrand + 品牌重试）
- 方案2：使用固定按键导航筛选（Y → 7×down → Enter → 10×down → Enter → 32×down → Enter → 5×down → Enter → ESC）
- 方案1上车检测保留 rc.png 图片匹配，方案2使用 OCR 检测"上车"

### v1.2.8.0 (2026-07-19)

**🚗 跑图选车改为固定按键导航 + OCR**
- 用固定按键序列（Y → Enter → 35×down → Enter → 19×down → Enter → ESC → Enter）替代纯图片匹配选车
- OCR 在中心区域检测"上车"文字，有则 Enter 上车，无则车辆已在驾驶按 ESC
- 删除 `wait_for_skill_car_strict` 四重验证、`skillcarbrand.png` 品牌搜索、翻页找车、`drivingtag.png` 检测等全部图片匹配逻辑

**🗑️ 删除车辆筛选改为固定按键导航**
- 用固定按键序列（Y → 7×down → Enter → 10×down → Enter → 32×down → Enter → 5×down → Enter → ESC）替代 `repitem.png` + `CCbrand.png` 图片匹配筛选
- 删除车辆上车检测从 `rc.png` 图片匹配改为 OCR 检测"上车"
- 删除 `brand_retry_done` 品牌重试循环，筛选后直接逐车删除

### v1.2.7.0 (2026-07-17)

**✨ 新增**
- **单局跑图超时检测**: 原硬编码 90 秒卡死超时改为可自定义，默认 600 秒，保存在 config.json
- **GitHub Actions CI/CD**: 推送到 main 自动编译 Steam + Xbox 两个版本，通过 `docs/` 中的 release note 控制是否发布 Release

**🔧 改进**
- 调试模式合并：原"调试截图"和"诊断模式"合并为一个"调试模式"开关

**🐛 修复**
- 修复 OCR 完赛检测在 onnxruntime CPU 后端的 UTF-8 解码异常
- 修复超级抽奖重新选品牌后 `brand_retry_done` 未初始化导致的卡死

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
