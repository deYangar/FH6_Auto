## v1.2.3.0 (2026-07-11)

### 跑图选车等级标签反向校验

`find_skill_car_strict` 新增第四重验证：在车卡底部搜索区域匹配 B600 等级标签模板，排除错误等级的车辆。

- 使用独立模板 `images/anti_class_b600.png`，与方案的 class_image 分离，避免跨方案干扰
- 搜索区域覆盖车卡下半 50% 高度，仅限当前卡片宽度（防止误扫相邻卡片）
- 阈值 0.70，匹配到等级标签即排除该候选

### 🔧 Bug 修复

- 修复 `_save_strict_car_simple` 末尾误粘贴 `load_template` 代码导致 `find_new_consumable_car_strict` 崩溃（`template_path` 未定义）

---

**下载说明：** 运行 `FH6Auto.exe` 即可，`assets/` 和 `images/` 已打包在内。
