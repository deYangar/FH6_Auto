import time


def press_with_pause(bot, key, *, delay=0.08, after=0.0):
    bot.hw_press(key, delay=delay)
    if after > 0:
        time.sleep(after)


def press_many(bot, key, count, *, delay=0.08, after=0.0):
    for _ in range(count):
        if not bot.is_running:
            return False
        press_with_pause(bot, key, delay=delay, after=after)
    return True


def wait_image_or_log(
    bot,
    template_path,
    *,
    region,
    threshold,
    timeout,
    interval,
    fast_mode,
    not_found_message,
    invert_mode=False,
    click=False,
    click_double=False,
    post_delay=0.0,
    transparent=False,
):
    wait_fn = bot.wait_for_image_transparent if transparent else bot.wait_for_image_gray
    kwargs = {
        "region": region,
        "threshold": threshold,
        "timeout": timeout,
        "interval": interval,
        "fast_mode": fast_mode,
    }
    if not transparent:
        kwargs["invert_mode"] = invert_mode
    pos = wait_fn(template_path, **kwargs)
    if not pos:
        if not_found_message:
            bot.log(not_found_message)
        return None
    if click:
        bot.game_click(pos, double=click_double)
        if post_delay > 0:
            time.sleep(post_delay)
    return pos


def wait_any_image_or_log(
    bot,
    image_list,
    *,
    region,
    threshold,
    timeout,
    interval,
    fast_mode,
    not_found_message,
    invert_mode=False,
    click=False,
    click_double=False,
    post_delay=0.0,
):
    pos = bot.wait_for_any_image_gray(
        image_list,
        region=region,
        threshold=threshold,
        timeout=timeout,
        interval=interval,
        fast_mode=fast_mode,
        invert_mode=invert_mode,
    )
    if not pos:
        if not_found_message:
            bot.log(not_found_message)
        return None
    if click:
        bot.game_click(pos, double=click_double)
        if post_delay > 0:
            time.sleep(post_delay)
    return pos


def click_if_found(bot, pos, *, double=False, post_delay=0.0):
    if not pos:
        return False
    bot.game_click(pos, double=double)
    if post_delay > 0:
        time.sleep(post_delay)
    return True
