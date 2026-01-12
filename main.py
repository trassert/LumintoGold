import asyncio
import logging
import random
import re
import contextlib
from sys import stderr
from os import listdir, mkdir, path
from time import time

import aiofiles
import orjson
from loguru import logger

from telethon import events, functions, types
from telethon.sync import TelegramClient
from telethon.tl.custom import Message
from telethon.tl.types import MessageMediaDocument, PeerUser, User
from telethon.tl.functions.account import UpdateStatusRequest

logger.remove()
logger.add(
    stderr,
    format=(
        "[{time:HH:mm:ss} <level>{level}</level>]: "
        "<green>{file}:{function}</green> <cyan>></cyan> {message}"
    ),
    level="INFO",
    colorize=True,
    backtrace=False,
    diagnose=False,
)


class InterceptHandler(logging.Handler):
    def emit(self, record):
        level = "TRACE" if record.levelno == 5 else record.levelname
        logger.opt(depth=6, exception=record.exc_info).log(
            level, record.getMessage()
        )


logging.basicConfig(handlers=[InterceptHandler()], level=0)


from modules import (  # noqa: E402
    ai,
    d,
    formatter,
    get_sys,
    task_gen,
    genpass,
    phrase,
    flip_map,
    iterators,
    settings,
    tz,
)


def get_args(text: str, skip_first: bool = True) -> list[str]:
    parts = text.split()
    return parts[1:] if skip_first and parts else parts


class UserbotManager:
    def __init__(self, phone: str, api_id: int, api_hash: str):
        self.phone = phone
        self.settings = settings.UBSettings(phone, "clients")
        self.client = TelegramClient(
            session=path.join("sessions", phone),
            api_id=api_id,
            api_hash=api_hash,
            use_ipv6=None,
            system_version="4.16.30-vxCUSTOM",
            device_model="LumintoGold",
            system_lang_code="ru",
            lang_code="ru",
        )
        self.iris_task = task_gen.Generator(f"{phone}_iris")
        self.online_task = task_gen.Generator(f"{phone}_online")
        self.iceyes_task = task_gen.Generator(f"{phone}_iceyes")
        self.ai_client = ai.Client(None, None)

    async def init(self):
        self.client.use_ipv6 = await self.settings.get("use.ipv6")
        self.ai_client = ai.Client(
            await self.settings.get("ai.token"),
            await self.settings.get("ai.proxy"),
        )
        await self.client.start(phone=self.phone)
        logger.info(f"Запущен клиент ({self.phone})")

        self._register_handlers()

        if await self.settings.get("block.voice"):
            self.client.add_event_handler(self.block_voice, events.NewMessage())

        if await self.settings.get("luminto.reactions"):
            for chat in ("lumintoch", "trassert_ch"):
                self.client.add_event_handler(
                    self.reactions, events.NewMessage(chats=chat)
                )

        if await self.settings.get("iris.farm"):
            await self.iris_task.create(
                func=self.iris_farm, task_param=4, random_delay=(5, 360)
            )

        if await self.settings.get("iceyes.bonus"):
            await self.iceyes_task.create(
                func=self.iceyes_bonus, task_param=1, random_delay=(1, 60)
            )

        if await self.settings.get("auto.online"):
            await self.online_task.create(
                func=self.auto_online, task_param=30, unit="seconds"
            )

    def _register_handlers(self):
        self.client.on(d.cmd(r"(?i)^\.чистка"))(self.clear_pm)
        self.client.on(d.cmd(r"(?i)^\.т"))(self.typing)
        self.client.on(d.cmd(r"(?i)^\.слов"))(self.words)
        self.client.on(d.cmd(r"(?i)^\.пинг$"))(self.ping)
        self.client.on(d.cmd(r"(?i)^\.флип"))(self.flip_text)
        self.client.on(d.cmd(r"(?i)^\.гс$"))(self.on_off_block_voice)
        self.client.on(d.cmd(r"(?i)^\.читать$"))(self.on_off_mask_read)
        self.client.on(d.cmd(r"(?i)^\.серв$"))(self.server_load)
        self.client.on(d.cmd(r"(?i)^\.токен (.+)"))(self.ai_token)
        self.client.on(d.cmd(r"(?i)^\.прокси (.+)"))(self.ai_proxy)
        self.client.on(d.cmd(r"(?i)^\.ии\s([\s\S]+)"))(self.ai_resp)
        self.client.on(d.cmd(r"(?i)^\.релоадконфиг$"))(self.config_reload)
        self.client.on(d.cmd(r"(?i)^\.автоферма$"))(self.on_off_farming)
        self.client.on(d.cmd(r"(?i)^\.онлайн$"))(self.toggle_online)
        self.client.on(d.cmd(r"(?i)^\.автобонус$"))(self.on_off_bonus)
        self.client.on(d.cmd(r"(?i)^\.set (.+)"))(self.set_setting)
        self.client.on(d.cmd(r"(?i)^\.время (.+)"))(self.time_by_city)
        self.client.on(
            d.cmd(
                r"(?i)^\.genpass(?:\s+(.+))?",
            )
        )(self.gen_pass)
        self.client.on(
            d.cmd(
                r"(?i)^\.генпасс(?:\s+(.+))?",
            )
        )(self.gen_pass)
        self.client.on(
            d.cmd(
                r"(?i)^\.пароль(?:\s+(.+))?",
            )
        )(self.gen_pass)

        self.client.on(events.NewMessage())(self._dynamic_mask_reader)

    async def reactions(self, event: Message):
        await asyncio.sleep(random.randint(0, 1000))
        logger.info("Отправил реакцию!")
        await self.client(
            functions.messages.SendReactionRequest(
                peer=event.peer_id,
                msg_id=event.message.id,
                big=True,
                add_to_recent=True,
                reaction=[
                    types.ReactionEmoji(
                        emoticon=random.choice(["💘", "❤️", "👍"])
                    )
                ],
            )
        )

    async def iris_farm(self):
        target = -1002355128955
        try:
            await self.client.send_message(
                target, random.choice(["/ферма", "/фарма"])
            )
        except Exception:
            await self.client.send_message(
                "iris_cm_bot", random.choice(["/ферма", "/фарма"])
            )
        logger.info(f"{self.phone} - сработала автоферма")

    async def iceyes_bonus(self):
        target = "iceyes_bot"
        await self.client.send_message(target, "💸 Бонус")
        logger.info(f"{self.phone} - сработал автобонус")

    async def auto_online(self):
        await self.client(UpdateStatusRequest(offline=False))

    async def block_voice(self, event: Message):
        if not isinstance(event.peer_id, PeerUser):
            return
        me = await self.client.get_me()
        if me.id == event.sender_id:
            return
        if isinstance(event.media, MessageMediaDocument) and event.media.voice:
            await event.delete()
            msg = await self.settings.get(
                "voice.message", phrase.voice.default_message
            )
            await event.respond(msg)

    async def clear_pm(self, event: Message):
        dialogs = await self.client.get_dialogs()
        deleted_count = 0

        message: Message = await event.edit(phrase.pm.wait.format(0))
        for dialog in dialogs:
            user = dialog.entity
            if isinstance(user, User) and user.deleted:
                await self.client.delete_dialog(dialog.id)
                await asyncio.sleep(await self.settings.get("typing.delay"))
                deleted_count += 1
                if deleted_count % 5 == 0:
                    await message.edit(phrase.pm.wait.format(deleted_count))

        return await event.edit(phrase.pm.cleared.format(deleted_count))

    async def set_setting(self, event: Message):
        arg: str = event.pattern_match.group(1)
        key, value = arg.split(" ", maxsplit=1)
        await self.settings.set(key, value)
        return await event.edit(phrase.setting.set.format(key=key, value=value))

    async def time_by_city(self, event: Message):
        city_name: str = event.pattern_match.group(1)
        location = tz.geolocator.geocode(city_name)
        if not location:
            return await event.edit(phrase.time.not_found.format(city_name))

        tz_name = tz.get_timezone(
            location.latitude,
            location.longitude,
            await self.settings.get("geoapify.token"),
        )
        if not tz_name:
            return await event.edit(phrase.time.not_timezone.format(city_name))

        tzz = tz.pytz.timezone(tz_name)
        city_time = tz.datetime.now(tzz)
        return await event.edit(
            (
                f"📍 {location.address}\n"
                f"🕒 Время: {city_time.strftime('%H:%M:%S')}\n"
                f"📅 Дата: {city_time.strftime('%d.%m.%Y')}\n"
                f"🌐 Пояс: {tz_name}"
            )
        )

    async def typing(self, event: Message):
        try:
            text = event.text.split(" ", maxsplit=1)[1]
        except IndexError:
            return await event.edit(phrase.no_text)
        bep = ""
        while bep != text:
            await event.edit(bep + await self.settings.get("typings"))
            await asyncio.sleep(await self.settings.get("typing.delay"))
            bep += text[len(bep)]
            await event.edit(bep)
            await asyncio.sleep(await self.settings.get("typing.delay"))

    async def words(self, event: Message):
        args = get_args(event.text.lower())
        arg_len = None
        arg_count = None

        for x in args:
            if "л" in x:
                val = x.replace("л", "").strip()
                if val.isdigit():
                    arg_len = int(val)
            elif "в" in x:
                val = x.replace("в", "").strip()
                if val.isdigit():
                    arg_count = int(val)

        words = iterators.Counter()
        total = 0
        dots = ""
        msg = await event.edit(phrase.words.all.format(words=total, dots=dots))

        async for message in self.client.iter_messages(event.chat_id):
            total += 1
            if total % 200 == 0:
                dots = dots + "." if len(dots) < 3 else ""
                try:
                    await msg.edit(
                        phrase.words.all.format(words=total, dots=dots)
                    )
                except Exception:
                    await asyncio.sleep(await self.settings.get("typing.delay"))
                    with contextlib.suppress(Exception):
                        msg = await event.reply(
                            phrase.words.except_all.format(total)
                        )

            if message.text:
                for word in message.text.split():
                    clean = re.sub(r"\W+", "", word).strip()
                    if clean and not clean.isdigit():
                        if arg_len is None or len(clean) >= arg_len:
                            words[clean.lower()] += 1

            if total % 1000 == 0:
                await asyncio.sleep(await self.settings.get("typing.delay"))

        freq = sorted(words, key=words.get, reverse=True)
        out = phrase.words.out
        maxsize = min(50, len(freq))
        if arg_count is not None and arg_count < len(freq):
            maxsize = arg_count
        for i in range(maxsize):
            out += f"{i + 1}. {words[freq[i]]}: {freq[i]}\n"

        try:
            await msg.edit(out)
        except Exception:
            await event.reply(out)

    async def ping(self, event: Message):
        timestamp = event.date.timestamp()
        timedel = round(time() - timestamp, 2)
        t1 = time()
        await event.edit(phrase.ping.pong)
        pingtime = round(time() - t1, 2)
        await event.edit(
            phrase.ping.ping.format(
                timedel=f"{timedel} сек.", ping=f"{pingtime} сек."
            )
        )

    async def flip_text(self, event: Message):
        try:
            text = event.text.split(" ", maxsplit=1)[1]
        except IndexError:
            return await event.edit(phrase.no_text)
        flipped = "".join(flip_map.flip_map.get(c, c) for c in reversed(text))
        await event.edit(flipped)

    async def on_off_block_voice(self, event: Message):
        enabled = not await self.settings.get("block.voice")
        await self.settings.set("block.voice", enabled)
        if enabled:
            self.client.add_event_handler(self.block_voice, events.NewMessage())
            await event.edit(phrase.voice.block)
        else:
            self.client.remove_event_handler(self.block_voice)
            await event.edit(phrase.voice.unblock)

    async def _dynamic_mask_reader(self, event: Message):
        mask_read_chats = await self.settings.get("mask.read") or []
        if event.chat_id in mask_read_chats:
            await event.mark_read()

    async def on_off_mask_read(self, event: Message):
        mask_read_chats = await self.settings.get("mask.read") or []
        if event.chat_id in mask_read_chats:
            mask_read_chats.remove(event.chat_id)
            await event.edit(phrase.read.off)
        else:
            mask_read_chats.append(event.chat_id)
            await event.edit(phrase.read.on)
        await self.settings.set("mask.read", mask_read_chats)

    async def server_load(self, event: Message):
        await event.edit(await get_sys.get_system_info())

    async def ai_token(self, event: Message):
        token = event.pattern_match.group(1).strip()
        await self.settings.set("ai.token", token)
        self.ai_client.change_api_key(token)
        await event.edit(phrase.ai.token_set)

    async def ai_proxy(self, event: Message):
        proxy = event.pattern_match.group(1).strip()
        await self.settings.set("ai.proxy", proxy)
        self.ai_client.change_proxy(proxy)
        await event.edit(phrase.ai.proxy_set)

    async def ai_resp(self, event: Message):
        if not await self.settings.get("ai.token"):
            return await event.edit(phrase.ai.no_token)
        text = event.pattern_match.group(1).strip()
        try:
            response = await self.ai_client.generate(text)
        except Exception as e:
            return await event.edit(phrase.error.format(e))
        if len(response) > 4096:
            chunks = formatter.splitter(response)
            await event.edit(chunks[0])
            for chunk in chunks[1:]:
                await event.reply(chunk)
        else:
            await event.edit(response)

    async def config_reload(self, event: Message):
        await self.settings._ensure_loaded(forced=True)
        await event.edit(phrase.config.reload)

    async def on_off_farming(self, event: Message):
        enabled = not await self.settings.get("iris.farm")
        await self.settings.set("iris.farm", enabled)
        if enabled:
            await event.edit(phrase.farm.on)
            await self.iris_task.create(
                func=self.iris_farm, task_param=4, random_delay=(5, 360)
            )
        else:
            self.iris_task.stop()
            await event.edit(phrase.farm.off)

    async def on_off_bonus(self, event: Message):
        enabled = not await self.settings.get("iceyes.bonus")
        await self.settings.set("iceyes.bonus", enabled)
        if enabled:
            await event.edit(phrase.bonus.on)
            await self.iris_task.create(
                func=self.iceyes_bonus, task_param=1, random_delay=(1, 60)
            )
        else:
            self.iris_task.stop()
            await event.edit(phrase.bonus.off)

    async def gen_pass(self, event: Message):
        args = (event.pattern_match.group(1) or "").strip()
        length = genpass.Default.length
        letters = genpass.Default.letters
        digits = genpass.Default.digits
        special = genpass.Default.special

        if d_match := re.search(r"д(\d+)", args):
            length = int(d_match[1])
        if re.search(r"\+б", args):
            letters = True
        elif re.search(r"-б", args):
            letters = False
        if re.search(r"\+ц", args):
            digits = True
        elif re.search(r"-ц", args):
            digits = False
        if re.search(r"\+с", args):
            special = True
        elif re.search(r"-с", args):
            special = False

        try:
            pwd = genpass.gen_pass(length, letters, digits, special)
            await event.edit(phrase.password.done.format(pwd))
        except Exception as ex:
            await event.edit(phrase.error.format(ex))

    async def toggle_online(self, event: Message):
        enabled = not await self.settings.get("auto.online")
        await self.settings.set("auto.online", enabled)
        if enabled:
            await event.edit(phrase.online.on)
            await self.online_task.create(
                func=self.auto_online, task_param=30, unit="seconds"
            )
        else:
            self.online_task.stop()
            await event.edit(phrase.online.off)

    async def run(self):
        await self.init()
        await self.client.run_until_disconnected()


async def run_userbot(number: str, api_id: int, api_hash: str):
    try:
        bot = UserbotManager(number, api_id, api_hash)
        await bot.run()
    except Exception:
        logger.exception(f"Критическая ошибка в {number}")


async def main():
    clients_dir = "clients"
    try:
        clients = listdir(clients_dir)
    except FileNotFoundError:
        mkdir(clients_dir)
        clients = []

    if not clients:
        logger.warning("Нет ни одного клиента! Создаём нового..")
        number = input("Введи номер: ")
        api_id = int(input("Введи api_id: "))
        api_hash = input("Введи api_hash: ")
        async with aiofiles.open(
            path.join(clients_dir, f"{number}.json"), "wb"
        ) as f:
            await f.write(
                orjson.dumps(
                    {"api_id": api_id, "api_hash": api_hash},
                    option=orjson.OPT_INDENT_2,
                )
            )
        return await main()

    logger.info(f"Клиенты: {clients}")
    tasks = []
    for client_file in clients:
        async with aiofiles.open(
            path.join(clients_dir, client_file), "rb"
        ) as f:
            data = orjson.loads(await f.read())
        phone = client_file.replace(".json", "")
        tasks.append(run_userbot(phone, data["api_id"], data["api_hash"]))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        try:
            import uvloop

            uvloop.run(main())
        except ModuleNotFoundError:
            logger.warning(
                "Uvloop не найден! Установите его: pip install uvloop"
            )
            asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("Закрываю бота...")
