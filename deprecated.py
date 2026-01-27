"Код для работы с низкокачественной накруткой ради денег."

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

selenium_options = Options()
selenium_options.add_experimental_option("excludeSwitches", ["enable-logging"])
selenium_options.add_argument("--log-level=3")
selenium_options.add_argument("--disable-dev-shm-usage")
selenium_options.add_argument("--headless")
selenium_options.set_capability("browserVersion", "117")
selenium_options.add_argument("start-maximized")


if settings("earnbots") is None:
    logger.info("Первый запуск клиента...")
    settings(
        "earnbots",
        {
            "bee": False,
            "bch": False,
            "vktarget": False,
            "freegrc": False,
            "arikado": False,
            "daily": False,
        },
    )
    settings("typings", "..")
    settings("delay", 0.05)
    settings("mask_read", [])
    settings("sleep_time", 1000)
earnbots = settings("earnbots")

vk_token = settings("token_vk")
vk = VKMethods(logger=logger, token=vk_token)


async def vktarget(event):
    "Автозаработок на VKtarget"
    settings("last_time_vktarget", time())
    await event.mark_read()
    await sleep(4)
    if "Вступите в" in event.text:
        if await vk.join_vk_group(event.text.split("](")[1].split(")")[0]) == 0:
            await event.click(text="Скрыть")
            return await event.respond("Задания")
        await event.click(text="Проверить")
        await event.respond("Задания")
    elif "Поставьте лайк на" in event.text:
        if await vk.like_vk_post(event.text.split("](")[1].split(")")[0]) == 0:
            await event.click(text="Скрыть")
            return await event.respond("Задания")
        await event.click(text="Проверить")
        await event.respond("Задания")
    elif "Добавить в" in event.text:
        if await vk.add_vk_friend(event.text.split("](")[1].split(")")[0]) == 0:
            await event.click(text="Скрыть")
            return await event.respond("Задания")
        await event.click(text="Проверить")
        await event.respond("Задания")
    elif "Посмотреть" in event.text:
        if await vk.like_vk_post(event.text.split("](")[1].split(")")[0]) == 0:
            await event.click(text="Скрыть")
            return await event.respond("Задания")
        await event.click(text="Проверить")
        await event.respond("Задания")
    elif "канал" in event.text:
        for line in event.text.split("\n"):
            if "канал" in line:
                channelname = line.split("](")[1].split(")")[0]
        try:
            await client(JoinChannelRequest(channelname))
            logger.info(f"Подписываюсь на канал {channelname}")
            await sleep(20)
            await event.click(text="Проверить")
        except:
            try:
                await client(ImportChatInviteRequest(channelname))
                logger.info(f"Подписываюсь на канал {channelname}")
                await sleep(20)
                await event.click(text="Проверить")
            except:
                await event.click(text="Скрыть")
                logger.info(f"Не смог подписаться на канал {channelname}")
                return await event.respond("Задания")
        return await event.respond("Задания")
    elif (
        "Доступны новые задания!" in event.text
        and "исчезнуть" not in event.text
    ):
        logger.info("Доступны новые задания!")
        await event.respond("Задания")
    else:
        try:
            await event.click(text="Скрыть")
        except:
            await event.respond("Задания")


bch_iterator = StringIterator(
    ["📲 Surfing sites", "🤖 Message Bots", "📢 Join chats"]
)


async def earn_bch(event):
    settings("last_time_bch", time())
    await event.mark_read()
    await sleep(4)
    if "Welcome" in event.text:
        await event.respond(bch_iterator.next())
    elif 'Press the "Go to website"' in event.text:
        for row in event.reply_markup.rows:
            for button in row.buttons:
                if button.text == "📲 Go to website":
                    driver = webdriver.Chrome(options=selenium_options)
                    driver.get(button.url)
                    logger.info(f"Перехожу на сайт {get_clean_url(button.url)}")
                    await sleep(200)
                    driver.quit()
    elif 'Press the "Go to channel"' in event.text:
        for row in event.reply_markup.rows:
            for button in row.buttons:
                if "channel" in button.text:
                    url = button.url.split("t.me/")[1]
        try:
            await client(JoinChannelRequest(url))
            logger.info(f"Подписываюсь на канал {url}")
            await event.click(text="✅ Joined")
        except:
            try:
                await client(ImportChatInviteRequest(url))
                logger.info(f"Подписываюсь на канал {url}")
                await event.click(text="✅ Joined")
            except:
                logger.info(f"Не смог подписаться на канал {url}")
                await event.click(text="⏭ Skip")
    elif "turn off the notification" in event.text:
        logger.info("Новые задания!")
        await event.respond(bch_iterator.next())
    elif "have looked at all" in event.text:
        logger.info("Задания кончились")
        await event.respond(bch_iterator.next())
    elif "Forward a message to me from the bot" in event.text:
        for row in event.reply_markup.rows:
            for button in row.buttons:
                if "bot" in button.text:
                    bot = (
                        button.url.split("t.me/")[1].split("?")[0].split("/")[0]
                    )
                    try:
                        bot = bot.split("?")[0]
                    except:
                        pass
        try:
            async with client.conversation(bot, timeout=30) as conv:
                await conv.send_message("/start")
                response = await conv.get_response()
                return await client.forward_messages(
                    entity=event.sender_id,
                    messages=response.id,
                    from_peer=response.sender_id,
                )
        except:
            logger.info("Бот не отвечает")
            await event.click(text="⭕️ Report")
            logger.info("Проверяю другие задачи")
            return await event.respond(bch_iterator.next())
    elif "Please check later" in event.text:
        tick = bch_iterator.last()
        sleep_time = int(settings("sleep_time")) / 10
        for _ in range(10):
            logger.info(f"Сплю {sleep_time} сек")
            await sleep(sleep_time)
        if tick == bch_iterator.last():
            await event.respond(bch_iterator.next())
    elif "You earned" in event.text:
        logger.info(event.text)


bee_iterator = StringIterator(
    ["🤖 Join Bots", "💻 Visit Sites", "📢 Join Channels", "stop"]
)
all_bees = StringIterator(
    [
        "ClickBeeDOGEBot",
        "ClickBeeSHIBABot",
        "ClickBeeBEESBot",
        "ClickBeeBot",
        "ClickBeeBTCBot",
        "ClickBeeLTCBot",
        "sleep",
    ]
)


async def earn_bee(event):
    "Автозаработок на ClickBee"
    settings("last_time_bee", time())
    await event.mark_read()
    await sleep(4)
    if "browse the website" in event.text:
        for row in event.reply_markup.rows:
            for button in row.buttons:
                if "Open" in button.text:
                    cache = bee_iterator.last()
                    logger.info(f"Перехожу на сайт {get_clean_url(button.url)}")
                    driver = webdriver.Chrome(options=selenium_options)
                    driver.get(button.url)
                    try:
                        sleeptime = (
                            int(
                                driver.find_element(
                                    by=By.ID, value="timer"
                                ).text
                            )
                            + 10
                        )
                    except:
                        sleeptime = 50
                    await sleep(sleeptime)
                    driver.quit()
                    if cache == bee_iterator.last():
                        next = bee_iterator.next()
                        if next != "stop":
                            return await event.respond(next)
                        return await event.respond(bee_iterator.next())
    elif "You've earned" in event.text:
        logger.info(event.text)
        logger.info("Проверяю другие задачи")
        next = bee_iterator.next()
        if next != "stop":
            return await event.respond(next)
        return await event.respond(bee_iterator.next())
    elif "NO TASKS" in event.text:
        logger.info("Нет задач")
        task = bee_iterator.next()
        if task == "stop":
            client.remove_event_handler(earn_bee)
            bot = all_bees.next()
            if bot == "sleep":
                sleep_time = int(settings("sleep_time")) / 10
                for _ in range(10):
                    logger.info(f"Сплю {sleep_time} сек")
                    await sleep(sleep_time)
                bot = all_bees.next()
            client.add_event_handler(earn_bee, events.NewMessage(chats=bot))
            await client.send_message(bot, bee_iterator.next())
        else:
            await event.respond(task)
    elif "then forward any message" in event.text:
        for row in event.reply_markup.rows:
            for button in row.buttons:
                if "✅" in button.text:
                    return await event.click(text=button.text)
    elif "FORWARD a message from that bot" in event.text:
        for line in event.text.split("\n"):
            if "Open the bot" in line:
                mybot = (
                    line.split("](")[1]
                    .replace(")", "")
                    .replace("https://t.me/", "")
                    .split("?")[0]
                    .split("/")[0]
                )
        logger.info(f"Отправляю сообщение боту {mybot}")
        try:
            async with client.conversation(
                mybot, timeout=30, total_timeout=30
            ) as conv:
                await conv.send_message("/start")
                response = await conv.get_response()
                return await client.forward_messages(
                    entity=event.sender_id,
                    messages=response.id,
                    from_peer=response.sender_id,
                )
        except:
            logger.info("Бот не отвечает")
            await event.respond("🔙 Back")
            await sleep(5)
            logger.info("Проверяю другие задачи")
            next = bee_iterator.next()
            if next != "stop":
                return await event.respond(next)
            return await event.respond(bee_iterator.next())
    elif "and join it" in event.text:
        for line in event.text.split("\n"):
            if "this Telegram channel" in line:
                channelname = line.split("](")[1].split(")")[0]
        try:
            await client(JoinChannelRequest(channelname))
            logger.info(f"Вступаю в канал {channelname}")
        except:
            try:
                await client(ImportChatInviteRequest(channelname))
                logger.info(f"Вступаю в канал {channelname}")
            except:
                logger.info(f"Не смог вступить в канал {channelname}")
                skipped_button = next(
                    (
                        button
                        for row in event.reply_markup.rows
                        for button in row.buttons
                        if "Skip" in button.text
                    ),
                    None,
                )
                if skipped_button:
                    return await event.click(text=skipped_button.text)
        for row in event.reply_markup.rows:
            for button in row.buttons:
                if "✅" in button.text:
                    return await event.click(text=button.text)
    elif "error" in event.text.lower():
        logger.info("Проверяю другие задачи")
        next = bee_iterator.next()
        if next != "stop":
            return await event.respond(next)
        return await event.respond(bee_iterator.next())
    elif "new task" in event.text.lower():
        logger.info("Новые задачи!")
        next = bee_iterator.next()
        if next != "stop":
            return await event.respond(next)
        return await event.respond(bee_iterator.next())


async def miner_freegrc():
    logger.info("FreeGRC запущен")
    driver = webdriver.Chrome(options=selenium_options)
    wait = WebDriverWait(driver, 10)
    url = "https://freegridco.in/#free_roll"
    grc_cookies = {"name": "session_id", "value": settings("token_freegrc")}
    while True:
        driver.get(url)
        driver.add_cookie(grc_cookies)
        driver.refresh()
        logger.info("Получил страницу")
        try:
            wait.until(
                EC.visibility_of_element_located((By.ID, "roll_wait_text"))
            )
            element = driver.find_element(By.ID, "roll_wait_text")
            cache = (
                element.text.replace("Wait for", "")
                .replace("before next roll", "")
                .split(":")
            )
            sleep_time = int(cache[0]) * 60 + int(cache[1]) + 20
            logger.info(f"Сплю {sleep_time} сек")
            await sleep(sleep_time)
        except TimeoutException:
            logger.info("Нет необходимости спать")
        wait.until(EC.element_to_be_clickable((By.ID, "roll_button")))
        element = driver.find_element(By.ID, "roll_button")
        element.click()
        wait.until(EC.visibility_of_element_located((By.ID, "balance")))
        balance = driver.find_element(By.ID, "balance").text
        logger.info(f"Прокручено, теперь на балансе {balance} GRC")


async def miner_arikado():
    logger.info("Arikado запущен")
    driver = webdriver.Chrome(options=selenium_options)
    wait = WebDriverWait(driver, 10)
    arikado_url = "https://grc.arikado.ru/#faucet"
    arikado_cookies = {
        "name": "auth_cookie",
        "value": settings("token_arikado"),
    }
    while True:
        driver.get(arikado_url)
        driver.add_cookie(arikado_cookies)
        driver.refresh()
        logger.info("Получил страницу")
        try:
            wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//input[@value='Claim']")
                )
            )
            driver.find_element(By.XPATH, "//input[@value='Claim']").click()
            bal = (
                driver.find_element(
                    By.XPATH, "//p[contains(text(), 'Welcome')]"
                )
                .text.split(":")[1]
                .replace(")", "")
            )
            logger.info(f"Прокручено, теперь на балансе {bal}")
        except TimeoutException:
            wait.until(EC.visibility_of_element_located((By.ID, "main_block")))
            data = (
                driver.find_element(By.ID, "main_block")
                .text.split("\n")[-1]
                .split(":")
            )
            sleeptime = int(data[0]) * 3600 + int(data[1]) * 60 + int(data[2])
            logger.info(f"Сплю {sleeptime} сек")
            await sleep(sleeptime)


async def get_last_sent_date():
    last = settings("last_sent")
    if last is not None:
        last = (
            last.replace(":", "-")
            .replace(".", "-")
            .replace(" ", "-")
            .split("-")
        )
    try:
        return datetime(
            int(last[0]),
            int(last[1]),
            int(last[2]),
            int(last[3]),
            int(last[4]),
            int(last[5]),
            int(last[6]),
        )
    except:
        return None


async def update_last_sent_date(today):
    settings("last_sent", str(today))


async def daily_bots():
    await client.send_message("TronTRXAirdropBot", bots["TronTRXAirdropBot"])
    await client.send_message("BlazeBNBbot", bots["BlazeBNBbot"])
    await client.send_message(
        "plentyofficial_premium_v4bot", bots["plentyofficial_premium_v4bot"]
    )
    await client.send_message(
        "RavenCoin_RVN_Latoken_v7bot", bots["RavenCoin_RVN_Latoken_v7bot"]
    )
    await client.send_message(
        "EarnRVN_Referral_v5bot", bots["EarnRVN_Referral_v5bot"]
    )


async def send_daily_message():
    logger.info("Старт дневных сборов")
    while True:
        today = datetime.now()
        last_message_sent_date = await get_last_sent_date()
        "Если файл новый"
        if last_message_sent_date is None:
            await daily_bots()
            await update_last_sent_date(today)
            await sleep(86400)
            last_message_sent_date = await get_last_sent_date()
        seconds = (
            timedelta(days=1) - (today - last_message_sent_date)
        ).total_seconds()
        "Если время прошло"
        if today - last_message_sent_date > timedelta(days=1):
            await daily_bots()
            await update_last_sent_date(today)
        await sleep(seconds)


async def helper(event):
    await client.edit_message(event.chat_id, event.message, phrase.help)


async def settings_bee_on(event):
    earnbots = settings("earnbots")
    if earnbots["bee"]:
        return await event.edit(phrase.bee.already_on)
    earnbots["bee"] = True
    settings("earnbots", earnbots)
    current = all_bees.next()
    client.add_event_handler(earn_bee, events.NewMessage(chats=current))
    message = bee_iterator.next()
    if message != "stop":
        await client.send_message(current, message)
    else:
        await client.send_message(current, bee_iterator.next())
    await client.edit_message(event.chat_id, event.message, phrase.bee.on)


async def settings_bee_off(event):
    earnbots = settings("earnbots")
    earnbots["bee"] = False
    settings("earnbots", earnbots)
    client.remove_event_handler(earn_bee)
    await client.edit_message(event.chat_id, event.message, phrase.bee.off)


async def settings_bch_on(event):
    earnbots = settings("earnbots")
    if earnbots["bch"]:
        return await event.edit(phrase.bch.already_on)
    earnbots["bch"] = True
    settings("earnbots", earnbots)
    client.add_event_handler(earn_bch, events.NewMessage(chats="adbchbot"))
    await client.send_message("adbchbot", bots["adbchbot"])
    await client.edit_message(event.chat_id, event.message, phrase.bch.on)


async def settings_bch_off(event):
    earnbots = settings("earnbots")
    earnbots["bch"] = False
    settings("earnbots", earnbots)
    client.remove_event_handler(earn_bch, events.NewMessage(chats="adbchbot"))
    await client.edit_message(event.chat_id, event.message, phrase.bch.off)


async def settings_vk_on(event):
    if settings("token_vk") is not None:
        earnbots = settings("earnbots")
        if earnbots["vktarget"]:
            return await event.edit(phrase.vk.already_on)
        earnbots["vktarget"] = True
        settings("earnbots", earnbots)
        client.add_event_handler(
            vktarget, events.NewMessage(chats="vktarget_bot")
        )
        await client.send_message("vktarget_bot", bots["vktarget_bot"])
        await event.edit(phrase.vk.on)
    else:
        await client.send_message("me", phrase.vk.no_token)


async def settings_vk_off(event):
    earnbots = settings("earnbots")
    earnbots["vktarget"] = False
    settings("earnbots", earnbots)
    client.remove_event_handler(
        vktarget, events.NewMessage(chats="vktarget_bot")
    )
    await client.edit_message(event.chat_id, event.message, phrase.vk.off)


tasks = {}


async def settings_freegrc_on(event):
    if settings("token_freegrc") is not None:
        try:
            if tasks["freegrc"] is True:
                return await event.edit(phrase.grc.already_on)
        except KeyError:
            pass
        earnbots = settings("earnbots")
        earnbots["freegrc"] = True
        settings("earnbots", earnbots)
        tasks["freegrc"] = create_task(miner_freegrc())
        return await event.edit(phrase.grc.on)
    else:
        await client.send_message("me", phrase.grc.no_token)


async def settings_freegrc_off(event):
    earnbots = settings("earnbots")
    earnbots["freegrc"] = False
    settings("earnbots", earnbots)
    tasks["freegrc"].cancel()
    await client.edit_message(event.chat_id, event.message, phrase.grc.off)


async def settings_arikado_on(event):
    if settings("token_arikado") is not None:
        try:
            if tasks["arikado"] is True:
                return await event.edit(phrase.arikado.already_on)
        except KeyError:
            pass
        earnbots = settings("earnbots")
        earnbots["arikado"] = True
        settings("earnbots", earnbots)
        tasks["arikado"] = create_task(miner_arikado())
        return await event.edit(phrase.arikado.on)
    else:
        await client.send_message("me", phrase.arikado.no_token)


async def settings_arikado_off(event):
    earnbots = settings("earnbots")
    earnbots["arikado"] = False
    settings("earnbots", earnbots)
    tasks["arikado"].cancel()
    await client.edit_message(event.chat_id, event.message, phrase.arikado.off)


async def settings_daily_on(event):
    try:
        if tasks["daily"] is True:
            return await event.edit(phrase.daily.already_on)
    except KeyError:
        pass
    earnbots = settings("earnbots")
    earnbots["daily"] = True
    settings("earnbots", earnbots)
    tasks["daily"] = create_task(send_daily_message())
    return await event.edit(phrase.daily.on)


async def settings_daily_off(event):
    earnbots = settings("earnbots")
    earnbots["daily"] = False
    settings("earnbots", earnbots)
    tasks["daily"].cancel()
    await client.edit_message(event.chat_id, event.message, phrase.daily.off)


async def settings_global(event):
    earnbots = settings("earnbots")
    await client.edit_message(
        event.sender_id,
        event.message,
        phrase.settings.format(
            bee="✅" if earnbots["bee"] else "❌",
            bch="✅" if earnbots["bch"] else "❌",
            vktarget="✅" if earnbots["vktarget"] else "❌",
            daily="✅" if earnbots["daily"] else "❌",
            freegrc="✅" if earnbots["freegrc"] else "❌",
            arikado="✅" if earnbots["arikado"] else "❌",
            token_freegrc="✅"
            if settings("token_freegrc") is not None
            else "❌",
            token_arikado="✅"
            if settings("token_arikado") is not None
            else "❌",
            token_vk="✅" if settings("token_vk") is not None else "❌",
        ),
    )


async def settings_sleep(event):
    split = event.text.split(maxsplit=1)
    if len(split) < 2:
        return await event.edit(phrase.no_args)
    arg = split[1]
    if not arg[1].isdigit():
        return await event.edit(phrase.bad_args)
    settings("sleep_time", int(arg))
    return await event.edit(phrase.sleep_time.format(sleep_time=arg))


async def token_add(event):
    text = event.text.split()
    if len(text) == 1:
        return await event.edit(phrase.no_args)
    elif len(text) != 3:
        return await event.edit(phrase.bad_args)
    elif text[1] == "вк":
        settings("token_vk", text[2])
        return await event.edit(phrase.token_added)
    elif text[1] == "фг":
        settings("token_freegrc", text[2])
        return await event.edit(phrase.token_added)
    elif text[1] == "ар":
        settings("token_arikado", text[2])
        return await event.edit(phrase.token_added)


async def check_bots():
    await sleep(10)
    while True:
        logger.info("Проверка ботов")
        sleep_time = settings("sleep_time")
        try:
            if (time() - sleep_time - 10 > settings("last_time_bee")) and (
                earnbots["bee"]
            ):
                logger.info("BEE спал слишком долго, отправляю новое сообщение")
                if bee_iterator.next() != "stop":
                    await client.send_message(
                        all_bees.last(), bee_iterator.last()
                    )
                else:
                    await client.send_message(
                        all_bees.last(), bee_iterator.next()
                    )
        except TypeError:
            settings("last_time_bee", 0.00)
        try:
            if (time() - sleep_time - 10 > settings("last_time_bch")) and (
                earnbots["bch"]
            ):
                logger.info("BCH спал слишком долго, отправляю новое сообщение")
                await client.send_message("adbchbot", bch_iterator.next())
        except TypeError:
            settings("last_time_bch", 0.00)
        try:
            if (time() - sleep_time - 10 > settings("last_time_vktarget")) and (
                earnbots["vktarget"]
            ):
                logger.info(
                    "VKTarget спал слишком долго,отправляю новое сообщение"
                )
                await client.send_message("vktarget_bot", bots["vktarget_bot"])
        except TypeError:
            settings("last_time_vktarget", 0.00)
        await sleep(sleep_time)


# if earnbots['bee']:
#     bot = all_bees.next()
#     client.add_event_handler(earn_bee, events.NewMessage(chats=bot))
#     await client.send_message(bot, bee_iterator.next())
# client.add_event_handler(
#     settings_bee_off, events.NewMessage(outgoing=True, pattern=r'\-bee')
# )
# client.add_event_handler(
#     settings_bee_on, events.NewMessage(outgoing=True, pattern=r'\+bee')
# )

# if earnbots['bch']:
#     client.add_event_handler(earn_bch, events.NewMessage(chats='adbchbot'))
#     await client.send_message('adbchbot', bots['adbchbot'])
# client.add_event_handler(
#     settings_bch_off, events.NewMessage(outgoing=True, pattern=r'\-bch')
# )
# client.add_event_handler(
#     settings_bch_on, events.NewMessage(outgoing=True, pattern=r'\+bch')
# )

# if earnbots['vktarget']:
#     if vk_token is not None:
#         client.add_event_handler(
#             vktarget, events.NewMessage(chats='vktarget_bot'))
#         await client.send_message('vktarget_bot', bots['vktarget_bot'])
#     else:
#         await client.send_message('me', phrase.vk.no_token)
# client.add_event_handler(
#     settings_vk_off, events.NewMessage(outgoing=True, pattern=r'\-vk')
# )
# client.add_event_handler(
#     settings_vk_on, events.NewMessage(outgoing=True, pattern=r'\+vk')
# )

# if earnbots['freegrc']:
#     if settings('token_freegrc') is not None:
#         tasks['freegrc'] = create_task(miner_freegrc())
#     else:
#         await client.send_message('me', phrase.grc.no_token)
# client.add_event_handler(
#     settings_freegrc_off, events.NewMessage(
#         outgoing=True, pattern=r'\-grc')
# )
# client.add_event_handler(
#     settings_freegrc_on, events.NewMessage(outgoing=True, pattern=r'\+grc')
# )

# if earnbots['arikado']:
#     if settings('token_arikado') is not None:
#         tasks['arikado'] = create_task(miner_arikado())
#     else:
#         await client.send_message('me', phrase.arikado.no_token)
# client.add_event_handler(
#     settings_arikado_off,
#     events.NewMessage(
#         outgoing=True, pattern=r'\-arikado'
#     )
# )
# client.add_event_handler(
#     settings_arikado_on,
#     events.NewMessage(
#         outgoing=True,
#         pattern=r'\+arikado'
#     )
# )

# if earnbots['daily']:
#     tasks['daily'] = create_task(send_daily_message())
# client.add_event_handler(
#     settings_daily_off,
#     events.NewMessage(
#         outgoing=True,
#         pattern=r'\-daily'
#     )
# )
# client.add_event_handler(
#     settings_daily_on, events.NewMessage(outgoing=True, pattern=r'\+daily')
# )


async def chart(event):
    arg2 = re.search(r"с\d+", event.text)
    arg1 = re.search(r"д\d+", event.text)
    driver = webdriver.Chrome(options=selenium_options)
    wait = WebDriverWait(driver, 10)
    url = "https://freegridco.in/#balance"
    if settings("token_freegrc") is None:
        return await client.edit_message(
            event.sender_id, event.message, phrase.grc.no_token
        )
    grc_cookies = {"name": "session_id", "value": settings("token_freegrc")}
    driver.get(url)
    driver.add_cookie(grc_cookies)
    driver.refresh()
    wait.until(
        EC.visibility_of_element_located((By.CLASS_NAME, "table_horizontal"))
    )
    element = driver.find_element(By.CLASS_NAME, "table_horizontal").text.split(
        "\n"
    )
    element.pop(0)
    frame = {
        "День": [],
        "Бесплатный бросок": [],
        "Покупка броска": [],
        "Бросок": [],
        "Получено": [],
        "Проценты": [],
        "Лотерея": [],
        "Вывод": [],
    }
    types = [
        "День",
        "Бесплатный бросок",
        "Покупка броска",
        "Бросок",
        "Получено",
        "Проценты",
        "Лотерея",
        "Вывод",
    ]
    last = [0]
    for x in element:
        cache = []
        c = x.split(" ")
        Date = c[0]
        cache.append(Date)
        Type = 1
        if "bet" in c:
            Type = 2
        elif "profit" in c:
            Type = 3
        elif "received" in c:
            Type = 4
        elif "interest" in c:
            Type = 5
        elif "spent" in c or "reward" in c:
            Type = 6
        elif "exchange" in c:
            Type = 7
        cache.append(Type)
        Delta = round(float(c[-2]), 8)
        cache.append(Delta)
        if last[0] == Date:
            if len(frame[types[Type]]) > 0:
                frame[types[Type]][-1] = frame[types[Type]][-1] + Delta
            else:
                frame[types[Type]].append(Delta)
        else:
            frame["День"].append(Date)
            frame[types[Type]].append(Delta)
            for x in range(1, 8):
                if x != Type:
                    frame[types[x]].append(0)
        last = cache
    df = pd.DataFrame(frame)
    df["День"] = pd.to_datetime(df["День"])
    if arg1:
        conv = pd.Timedelta(days=int(arg1.group(0).replace("д", "")))
        df = df[df["День"] > (df["День"].iloc[-1] - conv)]
    else:
        conv = pd.Timedelta(days=5)
        df = df[df["День"] > (df["День"].iloc[-1] - conv)]
    df = df.set_index("День")
    if arg2:
        df = df.resample(arg2.group(0).replace("с", "") + "D").sum()
    sns.set_theme(style="dark")

    def formatter(timestamp):
        return timestamp.strftime("%m.%d")

    df.set_index(df.index.map(formatter)).plot(kind="bar", stacked=True)
    plt.xticks(fontsize=9)
    plt.xlabel("Дата", fontsize=10)
    plt.ylabel("Получено", fontsize=12)
    plt.title("График накоплений GRC", fontsize=16)
    plt.savefig("balance.png")
    await client.edit_message(event.chat_id, event.message, phrase.balance)
    await client.send_file(event.chat_id, "balance.png")
    remove("balance.png")


client.add_event_handler(
    settings_sleep, events.NewMessage(outgoing=True, pattern=r"\.сон")
)
client.add_event_handler(
    token_add, events.NewMessage(outgoing=True, pattern=r"\.токен")
)
client.add_event_handler(
    chart, events.NewMessage(outgoing=True, pattern=r"\.денег")
)
client.add_event_handler(
    settings_global, events.NewMessage(outgoing=True, pattern=r"\.настройки")
)
client.add_event_handler(
    helper, events.NewMessage(outgoing=True, pattern=r"\.помощь")
)
# create_task(check_bots())
