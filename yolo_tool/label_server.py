"""
FH6 YOLO 标注工作台（截图采集 + 网页标注 + 模型自动打标，三合一）
启动后浏览器打开 http://localhost:5678

功能:
  - 游戏窗口后台截图（单张 / 连拍 / MJPEG 实时预览）
  - 手动画框 / 拖拽移动 / 手柄缩放 / 方向键微调
  - 训练好的 YOLO 模型一键自动打标
"""

import os
import sys
import json
import time
import threading
from datetime import datetime
from pathlib import Path

import cv2
from flask import Flask, render_template, jsonify, request, send_from_directory, Response

# 路径
if getattr(sys, 'frozen', False):
    _APP_DIR = os.path.dirname(sys.executable)
    _BUNDLE_DIR = sys._MEIPASS  # PyInstaller 解压目录
else:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))
    _BUNDLE_DIR = _APP_DIR

PROJECT_ROOT = os.path.dirname(_APP_DIR)

# 原始数据目录：优先脚本同级 raw/（Training Kit 与新版源码布局），逐级兼容旧布局
DATA_RAW_CANDIDATES = [
    os.path.join(_APP_DIR, "raw"),
    os.path.join(_APP_DIR, "data", "raw"),
    os.path.join(PROJECT_ROOT, "yolo_tool", "raw"),
    os.path.join(PROJECT_ROOT, "yolo_tool", "data", "raw"),
]
DATA_RAW = next((p for p in DATA_RAW_CANDIDATES if os.path.isdir(p)), DATA_RAW_CANDIDATES[0])

CONFIG_DIR_CANDIDATES = [
    os.path.join(_APP_DIR, "config"),
    os.path.join(PROJECT_ROOT, "yolo_tool", "config"),
]
CONFIG_DIR = next((p for p in CONFIG_DIR_CANDIDATES if os.path.isdir(p)), CONFIG_DIR_CANDIDATES[0])

# Flask 模板目录：优先从 bundle 读取
TEMPLATE_DIR = os.path.join(_BUNDLE_DIR, "templates")
if not os.path.isdir(TEMPLATE_DIR):
    TEMPLATE_DIR = os.path.join(_APP_DIR, "templates")

app = Flask(__name__, static_folder=None, template_folder=TEMPLATE_DIR)


def load_classes():
    path = os.path.join(CONFIG_DIR, "classes.json")
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"classes": {}, "next_class_id": 0}


def get_image_dirs():
    """获取所有截图子目录"""
    if not os.path.isdir(DATA_RAW):
        return []
    dirs = []
    for d in sorted(os.listdir(DATA_RAW)):
        full = os.path.join(DATA_RAW, d)
        if os.path.isdir(full):
            imgs = [f for f in os.listdir(full) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp'))]
            if imgs:
                dirs.append({"name": d, "count": len(imgs)})
    return dirs


def get_images(tag):
    """获取某个目录下所有图片文件名"""
    full = os.path.join(DATA_RAW, tag)
    if not os.path.isdir(full):
        return []
    imgs = [f for f in os.listdir(full) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp'))]
    imgs.sort()
    return imgs


def get_label_path(tag, img_name):
    """图片对应的 YOLO 标签文件路径"""
    full = os.path.join(DATA_RAW, tag)
    stem = os.path.splitext(img_name)[0]
    return os.path.join(full, f"{stem}.txt")


def read_labels(tag, img_name):
    """读取已有的 YOLO 标签"""
    lp = get_label_path(tag, img_name)
    if not os.path.isfile(lp):
        return []
    labels = []
    with open(lp, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 5:
                labels.append({
                    "class_id": int(parts[0]),
                    "cx": float(parts[1]),
                    "cy": float(parts[2]),
                    "w": float(parts[3]),
                    "h": float(parts[4]),
                })
    return labels


def save_labels(tag, img_name, labels):
    """保存 YOLO 标签，空标注时删除 txt 文件"""
    lp = get_label_path(tag, img_name)
    if not labels:
        # 空标注：删除已有的 txt
        if os.path.isfile(lp):
            os.remove(lp)
        return
    with open(lp, "w") as f:
        for lb in labels:
            f.write(f"{lb['class_id']} {lb['cx']:.6f} {lb['cy']:.6f} {lb['w']:.6f} {lb['h']:.6f}\n")


def sanitize_tag(tag):
    """目录名清洗：去掉路径分隔符等非法字符"""
    tag = (tag or "").strip()
    for ch in '\\/:*?"<>|':
        tag = tag.replace(ch, "_")
    tag = tag.strip(". ")
    return tag or "unsorted"


def send_to_recycle_bin(path):
    """把文件送进 Windows 回收站（SHFileOperationW + FOF_ALLOWUNDO），可还原。成功返回 True。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        FO_DELETE = 3
        FOF_SILENT = 0x0004
        FOF_NOCONFIRMATION = 0x0010
        FOF_ALLOWUNDO = 0x0040
        FOF_NOERRORUI = 0x0400

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR),
                ("fFlags", ctypes.c_uint16),
                ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", wintypes.LPCWSTR),
            ]

        # pFrom 要求双 \0 结尾的多字符串；create_unicode_buffer 自带结尾 \0，内容再拼一个即得双 \0
        from_buf = ctypes.create_unicode_buffer(path + "\0")
        op = SHFILEOPSTRUCTW()
        op.hwnd = None
        op.wFunc = FO_DELETE
        op.pFrom = ctypes.cast(from_buf, wintypes.LPCWSTR)
        op.pTo = None
        op.fFlags = FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI
        op.fAnyOperationsAborted = False
        op.hNameMappings = None
        op.lpszProgressTitle = None
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return result == 0 and not op.fAnyOperationsAborted
    except Exception as e:
        print(f"[删除] 回收站调用失败: {e}")
        return False


# ============================================================
# 截图采集（懒加载，缺 pywin32 不影响标注功能）
# ============================================================

_capture_state = {"cap": None, "lock": threading.Lock(), "init_failed": False}


def get_capture():
    """懒加载 GameCapture；pywin32 缺失时返回 None"""
    if _capture_state["cap"] is None and not _capture_state["init_failed"]:
        try:
            sys.path.insert(0, _APP_DIR)
            from capture import GameCapture
            cap = GameCapture()
            cap.enable_dpi()
            _capture_state["cap"] = cap
        except Exception as e:
            _capture_state["init_failed"] = True
            print(f"[截图模块] 初始化失败: {e}")
    return _capture_state["cap"]


def grab_frame(timeout=10.0):
    """加锁截图，返回 BGR 数组或 None。

    timeout=None 时非阻塞：拿不到锁直接放弃本帧（供 MJPEG 预览流用，避免预览卡死截图请求）。
    """
    cap = get_capture()
    if cap is None:
        return None
    lock = _capture_state["lock"]
    if timeout is None:
        if not lock.acquire(blocking=False):
            return None
    else:
        if not lock.acquire(timeout=timeout):
            return None
    try:
        try:
            if not cap.find_game_window():
                return None
            return cap.capture()
        except Exception as e:
            print(f"[截图模块] 截图异常: {e}")
            return None
    finally:
        lock.release()


def save_snap(tag):
    """截一张存到 raw/<tag>/，返回文件名或 None"""
    frame = grab_frame()
    if frame is None:
        return None
    save_dir = os.path.join(DATA_RAW, tag)
    os.makedirs(save_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    name = f"{ts}.png"
    cv2.imwrite(os.path.join(save_dir, name), frame)
    return name


# ============================================================
# 模型自动打标（懒加载）
# ============================================================

_model_cache = {"model": None, "name": None, "device": None}


def find_model_file():
    """查找可用权重：环境变量 > models/best.pt > 根目录 yolo26s.pt"""
    env = os.environ.get("FH6_YOLO_MODEL")
    if env and os.path.isfile(env):
        return env
    candidates = [
        os.path.join(_APP_DIR, "models", "best.pt"),
        os.path.join(_APP_DIR, "yolo26s.pt"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def get_model():
    """懒加载 YOLO 模型，返回 (model, name)；无权重返回 (None, None)"""
    if _model_cache["model"] is None:
        path = find_model_file()
        if not path:
            return None, None
        from ultralytics import YOLO
        model = YOLO(path)
        try:
            import torch
            device = 0 if torch.cuda.is_available() else "cpu"
        except Exception:
            device = "cpu"
        _model_cache["model"] = model
        _model_cache["name"] = os.path.basename(path)
        _model_cache["device"] = device
        print(f"[模型打标] 已加载 {path}，设备: {device}")
    return _model_cache["model"], _model_cache["name"]


# ============================================================
# 路由 — 标注
# ============================================================

@app.route("/")
def index():
    return render_template("label.html")


@app.route("/api/classes")
def api_classes():
    return jsonify(load_classes())


@app.route("/api/dirs")
def api_dirs():
    return jsonify(get_image_dirs())


@app.route("/api/images/<tag>")
def api_images(tag):
    return jsonify(get_images(tag))


@app.route("/api/labels/<tag>/<img_name>")
def api_get_labels(tag, img_name):
    return jsonify(read_labels(tag, img_name))


@app.route("/api/labels/<tag>/<img_name>", methods=["POST"])
def api_save_labels(tag, img_name):
    labels = request.json.get("labels", [])
    save_labels(tag, img_name, labels)
    return jsonify({"ok": True, "count": len(labels)})


@app.route("/api/delete/<tag>/<img_name>", methods=["POST"])
def api_delete_image(tag, img_name):
    """删除图片 + 同名标注 txt（优先送回收站，可还原；回收站不可用时永久删除）"""
    if img_name not in get_images(tag):
        return jsonify({"ok": False, "error": "图片不存在"}), 404
    img_path = os.path.join(DATA_RAW, tag, img_name)
    lbl_path = get_label_path(tag, img_name)
    recycled, removed = [], []
    for p in (img_path, lbl_path):
        if not os.path.isfile(p):
            continue
        fname = os.path.basename(p)
        if send_to_recycle_bin(p):
            recycled.append(fname)
        else:
            try:
                os.remove(p)
                removed.append(fname)
            except Exception as e:
                return jsonify({"ok": False, "error": f"删除失败 {fname}: {e}"}), 500
    return jsonify({"ok": True, "recycled": recycled, "removed": removed})


@app.route("/api/model_status")
def api_model_status():
    """只检查权重文件是否存在（不加载），供前端决定按钮显隐"""
    path = find_model_file()
    return jsonify({
        "available": bool(path),
        "name": os.path.basename(path) if path else None,
    })


@app.route("/api/autolabel/<tag>/<img_name>", methods=["POST"])
def api_autolabel(tag, img_name):
    """用训练好的模型对单张图推理，返回 YOLO 归一化框"""
    # 路径安全：只接受真实存在的目录和图片名
    if img_name not in get_images(tag):
        return jsonify({"ok": False, "error": "图片不存在"}), 404

    body = request.get_json(silent=True) or {}
    try:
        conf = min(max(float(body.get("conf", 0.5)), 0.01), 0.95)
    except (TypeError, ValueError):
        conf = 0.5

    model, mname = get_model()
    if model is None:
        return jsonify({"ok": False, "error": "未找到模型文件（models/best.pt）"}), 404

    img_path = os.path.join(DATA_RAW, tag, img_name)
    t0 = time.time()
    results = model.predict(
        source=img_path,
        conf=conf,
        iou=0.7,
        imgsz=640,
        device=_model_cache["device"],
        verbose=False,
    )
    r = results[0]
    h0, w0 = r.orig_shape

    boxes = []
    if r.boxes is not None and len(r.boxes) > 0:
        for b in r.boxes:
            x1, y1, x2, y2 = b.xyxy[0].tolist()
            cid = int(b.cls[0].item())
            boxes.append({
                "class_id": cid,
                "name": r.names.get(cid, str(cid)),
                "cx": ((x1 + x2) / 2) / w0,
                "cy": ((y1 + y2) / 2) / h0,
                "w": (x2 - x1) / w0,
                "h": (y2 - y1) / h0,
                "conf": round(float(b.conf[0].item()), 3),
            })

    # 跨类去重：NMS 按类别独立做，模型犹豫时同一张卡会同时输出 with_new + no_new
    # （类 3/4 = Revuelto 互斥，类 5/6 = Mad Mike 互斥），同位重叠只留置信度高的；
    # 同类重叠 >0.6 也一并去掉（补 NMS iou=0.7 的缝隙）
    EXCLUSIVE_PAIRS = {frozenset((3, 4)), frozenset((5, 6))}

    def _iou(a, b):
        ax1, ay1 = a["cx"] - a["w"] / 2, a["cy"] - a["h"] / 2
        ax2, ay2 = a["cx"] + a["w"] / 2, a["cy"] + a["h"] / 2
        bx1, by1 = b["cx"] - b["w"] / 2, b["cy"] - b["h"] / 2
        bx2, by2 = b["cx"] + b["w"] / 2, b["cy"] + b["h"] / 2
        iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
        ih = max(0.0, min(ay2, by2) - max(ay1, by1))
        inter = iw * ih
        union = a["w"] * a["h"] + b["w"] * b["h"] - inter
        return inter / union if union > 0 else 0.0

    kept = []
    dedup_dropped = 0
    for b in sorted(boxes, key=lambda x: -x.get("conf", 0.0)):
        dup = False
        for k in kept:
            pair = frozenset((b["class_id"], k["class_id"]))
            iou = _iou(b, k)
            if (pair in EXCLUSIVE_PAIRS and iou > 0.3) or (b["class_id"] == k["class_id"] and iou > 0.6):
                dup = True
                break
        if dup:
            dedup_dropped += 1
        else:
            kept.append(b)
    boxes = kept

    return jsonify({
        "ok": True,
        "model": mname,
        "count": len(boxes),
        "dedup_dropped": dedup_dropped,
        "time_ms": int((time.time() - t0) * 1000),
        "boxes": boxes,
    })


@app.route("/raw/<tag>/<path:filename>")
def serve_raw(tag, filename):
    directory = os.path.join(DATA_RAW, tag)
    return send_from_directory(directory, filename)


# ============================================================
# 路由 — 截图采集
# ============================================================

@app.route("/api/capture/status")
def api_capture_status():
    """截图模块状态：pywin32 是否可用、游戏窗口是否找到"""
    cap = get_capture()
    if cap is None:
        return jsonify({"available": False, "game_found": False,
                        "reason": "截图模块不可用（需要 pip install pywin32）"})
    with _capture_state["lock"]:
        hwnd = cap.find_game_window()
        rect = cap.get_window_rect() if hwnd else None
    return jsonify({
        "available": True,
        "game_found": bool(hwnd),
        "hwnd": hwnd,
        "rect": list(rect) if rect else None,
    })


@app.route("/api/capture/snap", methods=["POST"])
def api_capture_snap():
    """截一张图存进 raw/<tag>/"""
    body = request.get_json(silent=True) or {}
    tag = sanitize_tag(body.get("tag", ""))
    try:
        if get_capture() is None:
            return jsonify({"ok": False, "error": "截图模块不可用（需要 pip install pywin32）"}), 500
        name = save_snap(tag)
        if name is None:
            return jsonify({"ok": False, "error": "未找到 Forza Horizon 6 窗口，或截图失败。先启动游戏。"}), 404
        return jsonify({"ok": True, "tag": tag, "name": name})
    except Exception as e:
        return jsonify({"ok": False, "error": f"截图服务端异常: {e}"}), 500


@app.route("/api/capture/burst", methods=["POST"])
def api_capture_burst():
    """连拍 n 张（默认 5，间隔 0.3s）"""
    body = request.get_json(silent=True) or {}
    tag = sanitize_tag(body.get("tag", ""))
    try:
        n = min(max(int(body.get("n", 5)), 1), 10)
    except (TypeError, ValueError):
        n = 5
    if get_capture() is None:
        return jsonify({"ok": False, "error": "截图模块不可用（需要 pip install pywin32）"}), 500
    names = []
    for i in range(n):
        name = save_snap(tag)
        if name is None:
            if not names:
                return jsonify({"ok": False, "error": "未找到 Forza Horizon 6 窗口，或截图失败。先启动游戏。"}), 404
            break
        names.append(name)
        if i < n - 1:
            time.sleep(0.3)
    return jsonify({"ok": True, "tag": tag, "count": len(names), "names": names})


@app.route("/api/capture/preview")
def api_capture_preview():
    """MJPEG 实时预览流（约 8fps，宽 960）"""
    def gen():
        while True:
            # 非阻塞抢锁：截图请求持锁时直接跳过本帧，预览永不阻塞 snap
            frame = grab_frame(timeout=None)
            if frame is not None:
                h, w = frame.shape[:2]
                if w > 960:
                    frame = cv2.resize(frame, (960, int(h * 960 / w)), interpolation=cv2.INTER_AREA)
                ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
                if ok:
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                           + jpg.tobytes() + b"\r\n")
            time.sleep(0.12)

    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame",
                    headers={"Cache-Control": "no-cache"})


# ============================================================
# 主入口
# ============================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="FH6 YOLO 标注工作台")
    parser.add_argument("--port", type=int, default=5678)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    # 确保 templates 目录存在
    tpl_dir = os.path.join(_APP_DIR, "templates")
    os.makedirs(tpl_dir, exist_ok=True)

    print(f"\n{'='*50}")
    print(f"  FH6 YOLO 标注工作台（截图 + 标注 + 模型打标）")
    print(f"  打开浏览器: http://{args.host}:{args.port}")
    print(f"  数据目录: {DATA_RAW}")
    print(f"  模型权重: {find_model_file() or '未找到（模型打标不可用）'}")
    print(f"  截图模块: {'可用' if get_capture() else '不可用（缺 pywin32）'}")
    print(f"{'='*50}\n")

    # 自动打开浏览器
    import webbrowser
    webbrowser.open(f"http://{args.host}:{args.port}")

    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
