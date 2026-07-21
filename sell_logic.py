import time


class SellMixin:
    """卖车业务逻辑：识别并移除消耗品车辆"""

    def find_and_remove_consumable_car(self, target_count):
        # ====== 任务内锁定，每次进入任务强制重置详情状态锁 ======
        self.detail_state_confirmed = False
        if self.sc_count >= target_count:
            return True

        self.update_running_ui("移除车辆", self.sc_count, target_count)

        self.log("准备验证/进入菜单...")
        if not self.enter_menu():
            return False

        self.log("进入车辆与收藏...")
        self.hw_press("pagedown", delay=0.15)
        time.sleep(1.0)

        pos_buycar = self.wait_for_buy_and_used_car(timeout=15)
        if not pos_buycar:
            self.log("未识别到 购买新车与二手车")
            return False

        self.game_click(pos_buycar)
        time.sleep(0.8)
        self.hw_press("enter")
        time.sleep(5)

        pos_bs = self.wait_for_any_image_gray(
            ["buyandsell-w.png", "buyandsell-b.png"],
            region=self.regions["左"],
            threshold=0.75,
            timeout=60,
            interval=0.5,
            fast_mode=True
        )
        if not pos_bs:
            self.log("未找到购买与出售")
            return False

        self.game_click(pos_bs)
        time.sleep(1.0)

        self.hw_press("pagedown", delay=0.15)
        time.sleep(1.0)

        self.hw_press("enter")  # 进入我的车辆
        time.sleep(2.0)
        # 选择一辆收藏车驾驶以进入车库详情
        self.hw_press("y")
        time.sleep(1.0)
        self.hw_press("enter")
        time.sleep(0.8)
        self.hw_press("esc")
        time.sleep(1.5)
        # 驾驶收藏的车
        self.hw_press("enter")
        time.sleep(0.8)
        self.move_to_game_coord(5, 5)
        time.sleep(0.2)

        # ====== 上车检测：OCR 中心区域检测"上车" ======
        ocr_engine = self.get_ocr_engine()
        img = self.capture_region(self.regions["全界面"])
        text = ""
        if img is not None and ocr_engine:
            text = ocr_engine.detect_text_in_region(img, {
                "y_start": 0.34,
                "y_end": 0.66,
                "x_start": 0.325,
                "x_end": 0.675,
            })
        if "上车" in text:
            self.log(f"OCR 识别到'上车'，按 Enter 上车 (text={text})")
            self.hw_press("enter")
            time.sleep(2.0)
        else:
            self.log(f"OCR 未识别到'上车'，车辆已在驾驶 (text={text})")
            self.hw_press("esc")
            time.sleep(1.5)
            self.hw_press("esc")
        time.sleep(2.0)

        # 等待购买与出售界面出现
        found = False
        for i in range(30):
            if not self.is_running:
                return False
            pos = self.wait_for_any_image(
                ["buyandsell-b.png", "buyandsell-w.png"],
                region=self.regions["左"],
                threshold=0.70,
                timeout=1.5,
                interval=0.2,
                fast_mode=True
            )
            if pos:
                self.log(f"第 {i + 1} 次检测到购买与出售，进入车辆界面")
                self.hw_press("enter")
                time.sleep(1.5)
                found = True
                break
            self.log(f"第 {i + 1} 次未检测到购买与出售，等待后重试")
            time.sleep(1.0)
        if not found:
            self.log("30次内未找到购买与出售")
            return False

        # ====== 筛选找车：OCR 视觉导航（v1.2.10.0，按文字目标适配不同账号的车辆列表）======
        sell_filter = self.get_scheme_filter("sell_filter")
        if not sell_filter:
            self.log("当前方案未配置 sell_filter，跳过删车环节", level="WARN")
            return True
        self.log(f"当前方案: {self.config.get('current_scheme', 0) + 1}，使用 OCR 视觉导航筛选: {' + '.join(sell_filter)}")
        if not self.open_and_apply_filter(sell_filter, label="删车筛选"):
            self.log("删车筛选失败（目标选项缺失或导航失败），中止删车", level="ERROR")
            return False

        # ====== 筛选后 OCR 检测：是否没有可用车辆 ======
        _no_car = False
        _ocr_engine = self.get_ocr_engine()
        if _ocr_engine:
            _filter_img = self.capture_region(self.regions["全界面"])
            if _filter_img is not None:
                _filter_text = _ocr_engine.detect_text_in_region(_filter_img, {
                    "y_start": 0.2,
                    "y_end": 0.8,
                    "x_start": 0.15,
                    "x_end": 0.85,
                }, max_side=640)
                self.log(f"筛选后 OCR: {_filter_text}")
                if "没有可用的车辆" in _filter_text or "找不到可用的车辆" in _filter_text:
                    _no_car = True

        if _no_car:
            self.log("找不到对应车辆，跳过删车环节")
            self.hw_press("enter")
            time.sleep(0.7)
            self.hw_press("x")
            time.sleep(0.7)
            self.hw_press("esc")
            time.sleep(0.7)
            self.hw_press("esc")
            time.sleep(0.7)
            self.hw_press("esc")
            time.sleep(0.7)
            return True

        # 逐车删除
        not_found_pages = 0
        while self.sc_count < target_count:
            if not self.is_running:
                return False
            self.log(f"正在扫描当前页面... (连续未找到: {not_found_pages}/10)")

            pos_target = self.wait_for_image_ultimate_safe(
                main_path="removecarobject.png",
                anti_path="newcartag.png",
                region=self.regions["全界面"],
                main_threshold=0.77,
                anti_threshold=0.65,
                timeout=1.0,
                interval=0.2,
                top_threshold=0.0,
                bot_threshold=0.0
            )

            if pos_target:
                self.detail_state_confirmed = True

            if not pos_target:
                not_found_pages += 1
                if not_found_pages >= 10:
                    self.log("连续 10 页未找到目标车辆，车辆已全部清理完毕。")
                    break
                self.log(f"当前页面未找到，向右翻页寻找... (第 {not_found_pages} 次翻页)")
                for _ in range(4):
                    self.hw_press("right", delay=0.06)
                    time.sleep(0.1)
                time.sleep(0.4)
                continue

            not_found_pages = 0
            self.log("锁定目标车辆，执行点击...")
            self.game_click(pos_target)
            time.sleep(0.8)

            self.log("寻找 '从车库移除' 按钮...")
            pos_remove = self.wait_for_image_gray(
                "removecar.png",
                region=self.regions["中间"],
                threshold=0.70,
                timeout=1.5,
                interval=0.3,
                fast_mode=True
            )

            if pos_remove:
                self.log("直接找到移除按钮，点击...")
                self.game_click(pos_remove)
            else:
                self.log("未直接找到移除按钮，按下 Enter 呼出菜单...")
                self.hw_press("enter")
                time.sleep(0.8)
                pos_remove = self.wait_for_image_gray(
                    "removecar.png",
                    region=self.regions["中间"],
                    threshold=0.75,
                    timeout=1.5,
                    interval=0.3,
                    fast_mode=True
                )
                if pos_remove:
                    self.log("呼出菜单后找到移除按钮，点击...")
                    self.game_click(pos_remove)
                else:
                    self.log("仍未找到移除按钮，可能点错了/该车无法移除，按 ESC 放弃该车...")
                    self.hw_press("esc")
                    time.sleep(1.0)
                    self.hw_press("right")
                    time.sleep(1.2)
                    continue

            time.sleep(0.8)
            self.log("确认移除...")
            self.hw_press("down")
            time.sleep(0.3)
            self.hw_press("enter")
            time.sleep(1.2)

            self.sc_count += 1
            self.update_running_ui("移除车辆", self.sc_count, target_count)
            self.log(f"成功移除车辆！当前进度: {self.sc_count}/{target_count}")

        # 退回上一级
        for _ in range(3):
            if not self.is_running:
                return False
            self.hw_press("esc")
            time.sleep(1.0)

        return True
