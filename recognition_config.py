DEFAULT_RECOGNITION_PROFILES = {
    "buy.collectionjournal": {"threshold": 0.70, "timeout": 30, "interval": 0.4, "fast_mode": True},
    "buy.masterexplorer": {"threshold": 0.75, "timeout": 30, "interval": 0.4, "fast_mode": True},
    "buy.carcollection": {"threshold": 0.75, "timeout": 30, "interval": 0.3, "fast_mode": True},
    "buy.ccbrand": {"threshold": 0.75, "timeout": 0.8, "interval": 0.2, "fast_mode": True},
    "buy.consumablecar": {"threshold": 0.82, "timeout": 8, "interval": 0.3, "fast_mode": False},
    "race.eventlab": {"threshold": 0.70, "timeout": 5, "interval": 0.25, "fast_mode": True},
    "race.playevent": {"threshold": 0.75, "timeout": 40, "interval": 0.3, "fast_mode": True},
    "race.blueprint_not_found": {"threshold": 0.70, "fast_mode": False, "invert_mode": True},
    "race.blueprint_ready": {"threshold": 0.70, "fast_mode": False, "invert_mode": True},
    "race.skillcar_like": {"timeout": 1.0, "interval": 0.25},
    "race.skillcar_brand": {"threshold": 0.80, "timeout": 0.8, "interval": 0.2, "fast_mode": True},
    "race.start_ready": {"threshold": 0.75, "timeout": 4.0, "interval": 0.2, "fast_mode": True},
    "race.start_loop": {"threshold": 0.75, "timeout": 0.7, "interval": 0.2, "fast_mode": True},
    "race.restart_prompt": {"threshold": 0.70, "timeout": 4.0, "interval": 0.3, "fast_mode": True},
    "race.author_prompt": {"threshold": 0.68, "timeout": 2.0, "interval": 0.15, "fast_mode": True, "invert_mode": True},
    "cj.designpaint": {"threshold": 0.62, "timeout": 10, "interval": 0.25, "fast_mode": False},
    "cj.choosecar_quick": {"threshold": 0.62, "timeout": 2, "interval": 0.25, "fast_mode": False},
    "cj.choosecar_retry": {"threshold": 0.62, "timeout": 10, "interval": 0.25, "fast_mode": False},
    "cj.ccbrand": {"threshold": 0.75, "timeout": 0.8, "interval": 0.2, "fast_mode": True},
    "cj.buyandsell_landing": {"threshold": 0.68, "timeout": 15, "interval": 0.3, "fast_mode": False, "invert_mode": True},
    "cj.rc": {"threshold": 0.70, "timeout": 0.5, "interval": 0.1, "fast_mode": True},
    "cj.spraycar": {"threshold": 0.68, "timeout": 4.0, "interval": 0.2, "fast_mode": False, "invert_mode": True},
    "cj.vehicle_menu": {"threshold": 0.68, "timeout": 4.0, "interval": 0.15, "fast_mode": False, "invert_mode": True},
    "cj.vehicle_menu_retry": {"threshold": 0.68, "timeout": 1.8, "interval": 0.15, "fast_mode": False, "invert_mode": True},
    "cj.vehicle_menu_stable": {"threshold": 0.68, "fast_mode": False, "invert_mode": True},
    "cj.uat_menu": {"threshold": 0.62, "timeout": 1.2, "interval": 0.15, "fast_mode": False},
    "cj.cls": {"threshold": 0.68, "timeout": 8, "interval": 0.25, "fast_mode": False},
    "cj.exp": {"threshold": 0.75, "timeout": 1.2, "interval": 0.3, "fast_mode": True},
    "cj.spne": {"threshold": 0.66, "timeout": 0.8, "interval": 0.15, "fast_mode": False, "invert_mode": True},
    "matcher.skillcar_like_combo": {"main_threshold": 0.78, "like_threshold": 0.75, "final_threshold": 0.75, "fast_mode": True},
    "matcher.skillcar_switch_rc": {"threshold": 0.70, "timeout": 2.0, "interval": 0.2, "fast_mode": True},
    "matcher.skillcar_brand_entry": {"threshold": 0.76, "timeout": 0.8, "interval": 0.2, "fast_mode": True},
    "matcher.uat_menu": {"threshold": 0.62, "fast_mode": False},
    "matcher.buy_used_gray": {"threshold": 0.68, "interval": 0.25, "fast_mode": False},
    "matcher.buy_used_full": {"threshold": 0.65, "interval": 0.25, "fast_mode": False},
    "matcher.buy_used_fast": {"threshold": 0.70, "interval": 0.25, "fast_mode": True},
}

# 缓存：用户 profiles 只解析一次
_merged_cache = {}
_cache_initialized = False


def _build_merged_profiles(user_profiles):
    """预合并用户覆盖到默认配置，避免每次调用都 deepcopy。"""
    merged = {}
    for key, default_vals in DEFAULT_RECOGNITION_PROFILES.items():
        merged[key] = dict(default_vals)
        user_vals = user_profiles.get(key)
        if isinstance(user_vals, dict):
            merged[key].update(user_vals)
    return merged


def get_recognition_profile(bot, key, **overrides):
    global _cache_initialized, _merged_cache
    if not _cache_initialized:
        user_profiles = getattr(bot, "config", {}).get("recognition_profiles", {}) or {}
        _merged_cache = _build_merged_profiles(user_profiles)
        _cache_initialized = True
    profile = dict(_merged_cache.get(key, {}))
    if overrides:
        profile.update({k: v for k, v in overrides.items() if v is not None})
    return profile
