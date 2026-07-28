# FH6 YOLO 工具项目

截图采集、网页标注、模型训练导出全套。**根目录是唯一开发位置**，`dist\FH6_YOLO_Training_Kit` 是打包生成的分发包（跑 `打包Kit.bat` 再生成，别手改）。

## 日常流程

```
游戏里翻到目标画面
   ↓
双击「标注工作台.bat」→ 浏览器打开
   ↓
📷 截一张 (C) / 连截5张 / 实时预览   ← 截图直接进 raw\<目录>\
   ↓
左侧点新图 → 🤖 模型打标 → 拖拽微调框 → 自动保存
   ↓
双击「一键训练.bat」→ 自动续训 s 模型 → 导出 ONNX
```

## 脚本一览

| 脚本 | 作用 |
|---|---|
| 标注工作台.bat | 截图 + 标注 + 模型打标三合一网页工具（http://localhost:5678） |
| 一键训练.bat | 环境检查 + 构建数据集 + s 模型训练 + 导出 ONNX（有 best.pt 自动续训） |
| setup.bat | 只装环境（.venv，自动找 Python 3.10~3.13，自动识别 N 卡装 CUDA 版 torch，清华源） |
| train.bat | 只训练（默认 yolo26s.pt；续训自动降 lr 防震荡） |
| export.bat | 只导出 ONNX（不给参数自动找最新 best.pt） |
| 打包Kit.bat | 把根目录打包成 dist\FH6_YOLO_Training_Kit 分发包 |

## 标注工作台功能

- **截图采集**：顶部截图栏——游戏窗口状态灯、截图目录（可新建）、截一张（快捷键 C）、连截 5 张、MJPEG 实时预览浮窗。截图直接存进 `raw\<目录>\`，自动跳到新图开始标
- **删除文件**：截图栏「🗑 删除文件」按钮——删当前图 + 同名标注 txt，送 Windows 回收站可还原
- **模型打标**：右上角 🤖 按钮，**只手动触发**（切图不会自动跑模型；切图后看到的框是已保存的标注）。用 `models\best.pt`（没有就用 yolo26s.pt）识别当前图，框追加到标注里再手动调整；置信度默认 0.5，顶部输入框可调
- **手动画框**：画框模式可在已有大框内部直接叠加画小框（如 madmike_with_new 里画 new_tag）
- **框编辑**：选中框出现 8 个白色手柄——拖框内部移动（选择模式）、拖手柄缩放、方向键像素级微调（Shift ×10）
- **自动保存**：画完/改完 0.5 秒后自动存 YOLO txt

## 训练机制

- **自动续训**：一键训练检测到 `models\best.pt` 自动接着练（续训自动切 AdamW + lr0=0.0002 防震荡）；产物统一叫 `best.pt` / `best.onnx`，不加后缀
- **验证集固定**：`data\split_manifest.json` 锁定验证集，新图只进训练集，多轮指标可严格横比；重划分用 `python rebuild_dataset.py --fresh-split`
- **从零重练**：`train.bat yolo26s.pt 100`（会覆盖 models\best.pt，谱系重开）
- **产物**：`models\best.pt/onnx`（最新权重，部署用）+ `models\runs\v<时间戳>\`（每轮完整记录）
- **⚠️ 旧版迁移**：以前训出的 `models\best_s.pt/onnx` 改名成 `best.pt/onnx` 即可被新版一键训练识别（只改一次）

## 环境要求

- Windows + **Python 3.10~3.13**（[python.org](https://www.python.org/downloads/)，安装勾选 **Add python.exe to PATH**；3.14 太新不支持；没进 PATH 也能自动从常见安装目录找到）
- 有 N 卡：RTX 40 系驱动 ≥ 560，RTX 50 系需最新驱动（脚本按 cu130→cu128→cu126 自动降级并实跑 kernel 验证）
- 截图功能需要 pywin32（setup.bat 已包含）
- 不需要 conda

## 目录结构

```
raw\<子目录>\        原始截图 + YOLO 标注（同名 .txt）
config\classes.json  7 个类别定义
templates\label.html 工作台网页
yolo26s.pt           官方预训练权重（内置）
label_server.py      工作台服务端（截图+标注+打标）
capture.py           游戏窗口截图引擎
train.py             训练入口（续训判定/降lr/导出）
rebuild_dataset.py   数据集构建（分层划分+固定验证集）
export_onnx.py       ONNX 导出
data\                数据集构建产物（自动生成）
models\              训练产物
_archive\            旧模板匹配方案留底（detector_gui/matcher/capture_gui）
dist\                分发包（打包Kit.bat 生成）
```

## 类别

| ID | 名称 | 说明 |
|----|------|------|
| 0 | new_tag | NEW 角标 |
| 1 | class_s2829 | S2829 等级标签 |
| 2 | class_s1702 | S1702 等级标签 |
| 3 | revuelto_with_new | 方案1 车卡 + NEW |
| 4 | revuelto_no_new | 方案1 车卡 无 NEW |
| 5 | madmike_with_new | 方案2 车卡 + NEW |
| 6 | madmike_no_new | 方案2 车卡 无 NEW |

## 常见问题

- **截图状态灯红**：先启动 FH6 游戏；灯红且提示"模块不可用"则 `pip install pywin32`
- **模型打标按钮不显示**：目录里没有 models\best.pt 也没有 yolo26s.pt
- **有 N 卡但 CUDA 不可用**：更新到最新 NVIDIA 驱动（RTX 50 系必须最新驱动）
- **标注端口被占用**：`标注工作台.bat --port 5679`
- **彻底重装环境**：删 `.venv` 后重跑 setup.bat
- **yolo26s.pt 哪去了**：git 克隆用户仓库里不含这个文件（减轻仓库体积），首次训练时 Ultralytics 会自动下载（~20MB）；打包版 Kit 内置
- **数据量提醒**：当前 32 张图够验证流程，量产建议每类 50+ 标注
