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

        pos_rc = self.wait_for_image("rc.png", region=self.regions["全界面"], threshold=0.65, timeout=2, interval=0.2, fast_mode=True)
        if pos_rc:
            self.log("找到上车按钮，执行点击")
            self.game_click(pos_rc)
            time.sleep(2.0)
        else:
            self.log("该车辆已经驾驶，或未找到上车按钮，按两次ESC退回")
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

        # 筛选：按 Y 打开筛选面板
        self.hw_press("y")
        time.sleep(1.0)

        # 用 repitem.png 图像识别找到筛选选项（替代旧的键盘导航）
        pos_repitem = self.wait_for_image_gray(
            "repitem.png",
            region=self.regions["中间"],
            threshold=0.70,
            timeout=1,
            interval=0.3,
            fast_mode=True
        )
        if not pos_repitem:
            self.log("未识别到筛选选项(repitem.png)")
            return False

        self.game_click(pos_repitem)
        time.sleep(0.8)
        self.hw_press("esc")
        time.sleep(1.0)

        # 切换到消耗品品牌
        self.log("切换到消耗品品牌...")
        self.hw_press("backspace")
        brand_pos = None
        for _ in range(5):
            if not self.is_running:
                return False
            brand_pos = self.wait_for_any_image_gray(
                ["CCbrand.png"],
                region=self.regions["全界面"],
                threshold=0.75,
                timeout=0.8,
                interval=0.2,
                fast_mode=True
            )
            if brand_pos:
                break
            self.hw_press("up")
            time.sleep(0.25)

        if not brand_pos:
            self.log("未找到品牌")
            return False

        self.game_click(brand_pos)
        time.sleep(0.8)

        # 品牌重确认（与买车/超抽一致，后台点击可能只聚焦未进入）
        for retry in range(3):
            if not self.is_running:
                return False
            still_brand = self.find_image_gray(
                "CCbrand.png",
                region=self.regions["全界面"],
                threshold=0.75,
                fast_mode=True
            )
            if not still_brand:
                break
            self.log(f"品牌仍停留在制造商列表，补 Enter 进入车辆列表 ({retry + 1}/3)")
            self.hw_press("enter")
            time.sleep(1.0)

        self.log("开始删除消耗品车辆...")

        not_found_pages = 0
        while self.sc_count < target_count:
            if not self.is_running:
                return False
            self.log(f"正在严格扫描当前页面... (连续未找到: {not_found_pages}/5)")

            # 使用终极安全锁：removecarobject.png + 排斥 newcartag.png（不删新车）
            pos_target = self.wait_for_image_ultimate_safe(
                main_path="removecarobject.png",
                anti_path="newcartag.png",
                region=self.regions["全界面"],
                main_threshold=0.77,
                anti_threshold=0.65,
                timeout=1.0,
                interval=0.2
            )

            if pos_target:
                self.detail_state_confirmed = True

            if not pos_target:
                not_found_pages += 1
                if not_found_pages >= 5:
                    self.log("连续翻找 5 页仍未搜索到目标车辆！视为车辆已全部清理完毕。")
                    self.log("主动结束清理任务，准备进入下一步骤...")
                    break

                self.log(f"当前页面未找到，向右翻页寻找... (第 {not_found_pages} 次翻页)")
                for _ in range(4):
                    self.hw_press("right", delay=0.06)
                    time.sleep(0.1)
                time.sleep(0.4)
                continue

            # 找到目标，重置翻页计数器
            not_found_pages = 0

            self.log("锁定目标车辆，执行点击...")
            self.game_click(pos_target)
            time.sleep(0.8)

            # 寻找"从车库移除"按钮
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

            # 确认移除操作
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
