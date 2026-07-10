"""
测试 PNG 缓存 roundtrip 是否无损
验证 cv2.imencode -> pickle -> unpickle -> np.frombuffer -> cv2.imdecode 是否返回与原始 ndarray 完全一致的图像
"""
import os
import sys
import pickle
import json
import time
import cv2
import numpy as np

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import APP_DIR, CACHE_DIR, TEMPLATE_CACHE_FILE, TEMPLATE_META_FILE, get_img_path

IMAGES_DIR = os.path.join(APP_DIR, "images")

def get_template_meta():
    """复制 vision.py 中的 meta 生成逻辑"""
    if not os.path.isdir(IMAGES_DIR):
        return {}
    meta = {}
    for root, dirs, files in os.walk(IMAGES_DIR):
        for fname in files:
            if fname.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                abs_path = os.path.join(root, fname)
                rel_path = os.path.relpath(abs_path, IMAGES_DIR).replace("\\", "/")
                try:
                    meta[rel_path] = os.path.getsize(abs_path)
                except Exception:
                    pass
    return meta

def get_scales():
    """复制 get_scales_to_try 的返回值"""
    scales = [1.0]
    primary = 1.0
    for delta in [-0.02, 0.02]:
        s = round(primary + delta, 3)
        if 0.1 <= s <= 2.0 and s not in scales:
            scales.append(s)
    for s in [0.35, 0.38, 0.42, 0.48, 0.52, 0.58, 0.62, 0.68, 0.72, 0.78, 0.82, 0.88, 0.92, 1.25, 1.35, 1.4, 1.6, 1.7, 1.8]:
        if s not in scales:
            scales.append(s)
    return sorted(scales)

def test_png_roundtrip():
    """测试单个模板的 PNG roundtrip"""
    meta = get_template_meta()
    if not meta:
        print("No templates found!")
        return False
    
    scales = get_scales()
    print(f"Templates: {len(meta)}, Scales: {len(scales)}")
    
    # 取前 5 个模板测试
    test_files = list(meta.keys())[:5]
    all_ok = True
    max_diff = 0
    
    for rel_path in test_files:
        img_path = os.path.join(IMAGES_DIR, rel_path)
        tpl = cv2.imread(img_path, cv2.IMREAD_COLOR)
        if tpl is None:
            print(f"  SKIP {rel_path} (read failed)")
            continue
        
        for scale in scales[:5]:  # 每个模板只测前 5 个 scale
            # 原始缩放
            if scale == 1.0:
                scaled_orig = tpl.copy()
            else:
                scaled_orig = cv2.resize(tpl, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            
            # PNG roundtrip
            ok, buf = cv2.imencode('.png', scaled_orig)
            if not ok:
                print(f"  FAIL encode {rel_path} scale={scale}")
                all_ok = False
                continue
            
            # 模拟 pickle -> unpickle 流程
            raw_bytes = buf.tobytes()
            # pickle roundtrip
            raw_bytes = pickle.loads(pickle.dumps(raw_bytes))
            
            # 解码
            arr = np.frombuffer(raw_bytes, dtype=np.uint8)
            decoded = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            
            if decoded is None:
                print(f"  FAIL decode {rel_path} scale={scale}")
                all_ok = False
                continue
            
            # 比较形状
            if scaled_orig.shape != decoded.shape:
                print(f"  SHAPE MISMATCH {rel_path} scale={scale}: {scaled_orig.shape} vs {decoded.shape}")
                all_ok = False
                continue
            
            # 比较像素
            diff = np.abs(scaled_orig.astype(np.int16) - decoded.astype(np.int16))
            pixel_max = diff.max()
            pixel_mean = diff.mean()
            if pixel_max > max_diff:
                max_diff = pixel_max
            
            if pixel_max > 0:
                print(f"  WARN {rel_path} scale={scale}: max_diff={pixel_max} mean_diff={pixel_mean:.4f}")
            
            # 验证 matchTemplate 结果一致性
            # 创建一个假屏幕（用原图放大）
            fake_screen = cv2.resize(tpl, None, fx=2, fy=2, interpolation=cv2.INTER_AREA)
            if decoded.shape[0] <= fake_screen.shape[0] and decoded.shape[1] <= fake_screen.shape[1]:
                res_orig = cv2.matchTemplate(fake_screen, scaled_orig, cv2.TM_CCOEFF_NORMED)
                res_decoded = cv2.matchTemplate(fake_screen, decoded, cv2.TM_CCOEFF_NORMED)
                _, max_orig, _, _ = cv2.minMaxLoc(res_orig)
                _, max_decoded, _, _ = cv2.minMaxLoc(res_decoded)
                if abs(max_orig - max_decoded) > 0.001:
                    print(f"  MATCH DIFF {rel_path} scale={scale}: orig={max_orig:.6f} decoded={max_decoded:.6f}")
                    all_ok = False
    
    print(f"\n=== Result ===")
    print(f"All OK: {all_ok}")
    print(f"Max pixel diff: {max_diff}")
    return all_ok

def test_cache_file_sizes():
    """对比 ndarray vs PNG 缓存文件大小"""
    meta = get_template_meta()
    scales = get_scales()
    
    ndarry_size = 0
    png_size = 0
    count = 0
    
    for rel_path in meta:
        img_path = os.path.join(IMAGES_DIR, rel_path)
        tpl = cv2.imread(img_path, cv2.IMREAD_COLOR)
        if tpl is None:
            continue
        
        for scale in scales:
            if scale == 1.0:
                scaled = tpl.copy()
            else:
                scaled = cv2.resize(tpl, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            
            # ndarray 大小
            ndarry_size += scaled.nbytes
            
            # PNG 大小
            ok, buf = cv2.imencode('.png', scaled)
            if ok:
                png_size += buf.tobytes().__sizeof__()
            
            count += 1
    
    print(f"\n=== Cache Size Comparison ===")
    print(f"Templates: {len(meta)}, Items: {count}")
    print(f"ndarray total: {ndarry_size / 1024 / 1024:.2f} MB")
    print(f"PNG bytes total: {png_size / 1024 / 1024:.2f} MB")
    print(f"Compression ratio: {ndarry_size / max(png_size, 1):.1f}x")

def test_full_build_both():
    """完整构建两种缓存并对比"""
    meta = get_template_meta()
    scales = get_scales()
    
    # 构建 ndarray 缓存
    cache_ndarray = {}
    cache_png = {}
    
    for rel_path in meta:
        img_path = os.path.join(IMAGES_DIR, rel_path)
        tpl = cv2.imread(img_path, cv2.IMREAD_COLOR)
        if tpl is None:
            continue
        
        cache_ndarray[rel_path] = {}
        cache_png[rel_path] = {}
        
        for scale in scales:
            if scale == 1.0:
                scaled = tpl.copy()
            else:
                scaled = cv2.resize(tpl, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            
            cache_ndarray[rel_path][str(round(scale, 3))] = scaled
            
            ok, buf = cv2.imencode('.png', scaled)
            if ok:
                cache_png[rel_path][str(round(scale, 3))] = buf.tobytes()
    
    # pickle 两种缓存到文件
    ndarray_file = os.path.join(CACHE_DIR, "test_ndarray.pkl")
    png_file = os.path.join(CACHE_DIR, "test_png.pkl")
    
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    with open(ndarray_file, "wb") as f:
        pickle.dump(cache_ndarray, f, protocol=pickle.HIGHEST_PROTOCOL)
    
    with open(png_file, "wb") as f:
        pickle.dump(cache_png, f, protocol=pickle.HIGHEST_PROTOCOL)
    
    ndarray_fsize = os.path.getsize(ndarray_file)
    png_fsize = os.path.getsize(png_file)
    
    print(f"\n=== Full Cache File Sizes ===")
    print(f"ndarray pickle: {ndarray_fsize / 1024 / 1024:.2f} MB")
    print(f"PNG bytes pickle: {png_fsize / 1024 / 1024:.2f} MB")
    print(f"Compression: {ndarray_fsize / max(png_fsize, 1):.1f}x")
    
    # 验证 PNG 缓存可以正确加载和解码
    with open(png_file, "rb") as f:
        loaded_png = pickle.load(f)
    
    decode_failures = 0
    for rel_path in list(loaded_png.keys())[:10]:
        for scale_key, raw in loaded_png[rel_path].items():
            if isinstance(raw, (bytes, bytearray)):
                arr = np.frombuffer(raw, dtype=np.uint8)
                decoded = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if decoded is None:
                    print(f"  DECODE FAIL: {rel_path} scale={scale_key}")
                    decode_failures += 1
    
    print(f"\nDecode failures (first 10 templates): {decode_failures}")
    
    # 清理
    os.remove(ndarray_file)
    os.remove(png_file)
    
    return decode_failures == 0

if __name__ == "__main__":
    print("=" * 60)
    print("Test 1: PNG Roundtrip Integrity")
    print("=" * 60)
    test_png_roundtrip()
    
    print("\n" + "=" * 60)
    print("Test 2: Cache File Size Comparison")
    print("=" * 60)
    test_cache_file_sizes()
    
    print("\n" + "=" * 60)
    print("Test 3: Full Build Both Formats")
    print("=" * 60)
    ok = test_full_build_both()
    
    print(f"\n{'=' * 60}")
    print(f"Overall: {'ALL PASS' if ok else 'ISSUES FOUND'}")
    print(f"{'=' * 60}")
