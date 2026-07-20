import time


class BuyMixin:
    """批量买车业务逻辑"""

    def logic_buy_car(self, target_count):
        if self.car_counter >= target_count:
            return True

        self.update_running_ui("批量买车", self.car_counter, target_count)

        self.log("准备验证/进入菜单...")
        if not self.enter_menu():
            return False

        pos_collectionjournal = self.wait_for_image_transparent(
            "collectionjournal.png",
            region=self.regions["左"],
            threshold=0.7,
            timeout=30,
            interval=0.4,
            fast_mode=True
        )
        if not pos_collectionjournal:
            self.log("未找到收集簿")
            return False

        self.game_click(pos_collectionjournal, double=True)
        time.sleep(1.0)


        pos_masterexplorer = self.wait_for_image(
            "masterexplorer.png",
            region=self.regions["全界面"],
            threshold=0.75,
            timeout=30,
            interval=0.4,
            fast_mode=True
        )
        if not pos_masterexplorer:
            self.log("未找到探索")
            return False

        self.game_click(pos_masterexplorer, double=True)
        time.sleep(0.6)

        pos_carcollection = self.wait_for_image_transparent(
            "carcollection.png",
            region=self.regions["全界面"],
            threshold=0.75,
            timeout=30,
            interval=0.3,
            fast_mode=True
        )
        if not pos_carcollection:
            self.log("未找到车辆收集")
            return False

        # Forza 菜单焦点优先级高于后台鼠标点击。
        # 这里虽然能识别到车辆收藏图标，但鼠标点击不会稳定把焦点从“探索”切到“车辆收藏”。
        # 因此从当前“探索”焦点用方向键下移，再按 Enter 进入，避免 Enter 误进探索。
        self.hw_press("down")
        time.sleep(0.35)
        self.hw_press("enter")
        time.sleep(1.5)

        # 进入车辆网格后，按 Backspace 打开“制造商/品牌”列表。
        # AxeroYF/FH6 原版也是这样做；截图底部提示为“Backspace 制造商”。
        self.hw_press("backspace")
        time.sleep(0.5)

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
        # 后台点击品牌有时只把焦点停在品牌项上，未真正进入车辆列表。
        # 如果 CCbrand 仍可见，说明还在制造商列表，补 Enter 确认进入。
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
        # 品牌进入车辆列表后，方案1往下滚4次，方案2滚1次
        _scheme_idx = self.config.get("current_scheme", 0)
        _scroll_count = 4 if _scheme_idx == 0 else 1
        time.sleep(0.7)
        for _dn in range(_scroll_count):
            if not self.is_running:
                return False
            self.log(f"[BuyScroll] {_dn+1}/{_scroll_count}")
            self.hw_press("down")
            time.sleep(1.0)
        self.log("[BuyScroll] done")

        pos_22b = self.wait_for_image(
            "consumablecar.png",
            region=self.regions["全界面"],
            threshold=0.90,
            timeout=8,
            interval=0.3,
            fast_mode=False
        )
        if not pos_22b:
            self.log("未找到消耗品车辆")
            return False

        self.game_click(pos_22b, double=True)
        time.sleep(1.0)

        while self.car_counter < target_count:
            if not self.is_running:
                return False

            self.hw_press("space")
            time.sleep(0.6)
            self.move_to_game_coord(5, 5)
            self.hw_press("down")
            time.sleep(0.2)
            self.move_to_game_coord(5, 5)
            self.hw_press("enter")
            time.sleep(0.6)
            self.move_to_game_coord(5, 5)
            self.hw_press("enter")
            time.sleep(0.6)
            self.move_to_game_coord(5, 5)
            self.hw_press("enter")
            time.sleep(0.7)

            self.car_counter += 1
            self.update_running_ui("批量买车", self.car_counter, target_count)
            self.log(f"批量买车计数 +1: {self.car_counter}/{target_count}")

        for _ in range(5):
            if not self.is_running:
                return False
            self.hw_press("esc")
            time.sleep(0.8)

        return True
