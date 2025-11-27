import asyncio
import logging
import random
import re
import contextlib
from sys import stderr

import aiofiles
import orjson
from loguru import logger

logger.remove()
logger.add(
    stderr,
    format="[{time:HH:mm:ss} <level>{level}</level>]:"
    " <green>{file}:{function}</green>"
    " <cyan>></cyan> {message}",
    level="INFO",
    colorize=True,
    backtrace=False,
    diagnose=False
)


class InterceptHandler(logging.Handler):
    def emit(self, record) -> None:
        level = "TRACE" if record.levelno == 5 else record.levelname
        logger.opt(depth=6, exception=record.exc_info).log(
            level,
            record.getMessage(),
        )


logging.basicConfig(handlers=[InterceptHandler()], level=0)

from os import listdir, mkdir, path  # noqa: E402
from time import time  # noqa: E402

from telethon import (  # noqa: E402
    events,
    functions,
    types,
)
from telethon.sync import TelegramClient  # noqa: E402
from telethon.tl.custom import Message  # noqa: E402
from telethon.tl.types import MessageMediaDocument, PeerUser  # noqa: E402

from modules import (  # noqa: E402
    ai,
    d,
    formatter,
    get_sys,
    task_gen,
    genpass,
    phrase
)
from modules.flip_map import flip_map  # noqa: E402
from modules.iterators import Counter  # noqa: E402
from modules.settings import UBSettings  # noqa: E402


async def userbot(phone_number: str, api_id: int, api_hash: str) -> None:
    Settings = UBSettings(phone_number, "clients")
    client = TelegramClient(
        session=path.join("sessions", phone_number),
        api_id=api_id,
        api_hash=api_hash,
        use_ipv6=await Settings.get("use.ipv6"),
        system_version="4.16.30-vxCUSTOM",
        device_model="LumintoGold",
        system_lang_code="ru",
        lang_code="ru",
    )
    logger.info(f"Запускаю клиент ({phone_number})")
    await client.start(phone=phone_number)

    farm_task = task_gen.Generator(f"{phone_number}_iris")
    ai_client = ai.Client(
        await Settings.get("ai.token"),
        await Settings.get("ai.proxy"),
    )

    async def reactions(event: Message):
        await asyncio.sleep(random.randint(0, 1000))
        logger.info("Отправил реакцию!")
        return await client(
            functions.messages.SendReactionRequest(
                peer=event.peer_id,
                msg_id=event.message.id,
                big=True,
                add_to_recent=True,
                reaction=[types.ReactionEmoji(emoticon=random.choice(["💘", "❤️", "👍"]))],
            ),
        )

    async def iris_farm() -> None:
        try:
            await client.send_message(
                -1002355128955,
                random.choice(["/ферма", "/фарма"]),
            )
        except Exception:
            await client.send_message(
                "iris_cm_bot",
                random.choice(["/ферма", "/фарма"]),
            )
        logger.info(f"{phone_number} - сработала автоферма")

    async def block_voice(event: Message) -> None:
        if not isinstance(event.peer_id, PeerUser):
            return
        me = await client.get_me()
        if me.id == event.sender_id:
            return
        if not isinstance(event.media, MessageMediaDocument):
            return
        if event.media.voice:
            await event.delete()
            await event.respond(
                await Settings.get(
                    "voice.message",
                    phrase.voice.default_message,
                ),
            )

    @client.on(d.cmd(r"(?i)^\.т"))
    async def typing(event: Message):
        try:
            original = event.text.split(" ", maxsplit=1)[1]
        except Exception:
            return await event.edit(phrase.no_text)
        text = original
        bep = ""
        while bep != original:
            await event.edit(bep + await Settings.get("typings"))
            await asyncio.sleep(await Settings.get("typing.delay"))
            bep = bep + text[0]
            text = text[1:]
            await event.edit(bep)
            await asyncio.sleep(await Settings.get("typing.delay"))
        return None

    @client.on(d.cmd(r"(?i)^\.слов"))
    async def words(event: Message) -> None:
        arg = None
        arg2 = None
        try:
            args = event.text.lower().split()
            del args[0]
            for x in args:
                if "л" in x:
                    arg = x.replace("л", "").strip()
                    if arg.isdigit():
                        arg = int(arg)
                elif "в" in x:
                    arg2 = x.replace("в", "").strip()
                    if arg2.isdigit():
                        arg2 = int(arg2)
        except Exception:
            pass
        words = Counter()
        total = 0
        dots = ""
        msg: Message = await event.edit(
            phrase.words.all.format(words=total, dots=dots),
        )

        async for message in client.iter_messages(event.chat_id):
            total += 1
            if total % 200 == 0:
                try:
                    dots = dots + "." if len(dots) < 3 else ""
                    await msg.edit(
                        phrase.words.all.format(words=total, dots=dots),
                    )
                except Exception:
                    await asyncio.sleep(await Settings.get("typing.delay"))
                    with contextlib.suppress(Exception):
                        msg = await event.reply(
                            phrase.words.except_all.format(total),
                        )
            if message.text:
                for word in message.text.split():
                    word = re.sub(r"\W+", "", word).strip()
                    if word != "" and not word.isdigit():
                        if arg is not None:
                            if len(word) >= arg:
                                words[word.lower()] += 1
                        else:
                            words[word.lower()] += 1
            if total % 1000 == 0:
                await asyncio.sleep(await Settings.get("typing.delay"))

        freq = sorted(words, key=words.get, reverse=True)
        out = phrase.words.out
        minsize = 50
        maxsize = min(minsize, len(freq))
        if arg2 is not None and arg2 < len(freq):
            maxsize = arg2
        for i in range(maxsize):
            out += f"{i + 1}. {words[freq[i]]}: {freq[i]}\n"
        try:
            await msg.edit(out)
        except Exception:
            await event.reply(out)

    @client.on(d.cmd(r"(?i)^\.пинг$"))
    async def ping(event: Message) -> None:
        timestamp = event.date.timestamp()
        timedel = round(time() - timestamp, 2)
        t1 = time()
        await event.edit(phrase.ping.pong)
        pingtime = round(time() - t1, 2)
        return await event.edit(
            phrase.ping.ping.format(
                timedel=f"{timedel} сек.",
                ping=f"{pingtime} сек.",
            )
        )

    async def mask_read_any(event: Message):
        """Просматривает сообщение."""
        return await event.mark_read()

    @client.on(d.cmd(r"(?i)^\.флип"))
    async def flip_text(event: Message):
        try:
            text = event.text.split(" ", maxsplit=1)[1]
        except Exception:
            return await event.edit(phrase.no_text)
        final_str = ""
        for char in text:
            new_char = flip_map.get(char, char)
            final_str += new_char
        return await event.edit("".join(reversed(list(final_str))))

    @client.on(d.cmd(r"(?i)^\.гс$"))
    async def on_off_block_voice(event: Message) -> None:
        if await Settings.get("block.voice"):
            await Settings.set("block.voice", False)
            await event.edit(phrase.voice.unblock)
            client.remove_event_handler(block_voice)
        else:
            await Settings.set("block.voice", True)
            await event.edit(phrase.voice.block)
            client.add_event_handler(block_voice, events.NewMessage())

    @client.on(d.cmd(r"(?i)^\.читать$"))
    async def on_off_mask_read(event: Message):
        all_chats = await Settings.get("mask.read")
        if event.chat_id in all_chats:
            all_chats.remove(event.chat_id)
            await Settings.set("mask.read", all_chats)
            event.client.remove_event_handler(
                mask_read_any,
                events.NewMessage(chats=event.chat_id),
            )
            return await event.client.edit_message(
                event.sender_id,
                event.message,
                phrase.read.off,
            )
        all_chats.append(event.chat_id)
        await Settings.set("mask.read", all_chats)
        event.client.add_event_handler(
            mask_read_any,
            events.NewMessage(chats=event.chat_id),
        )
        return await event.client.edit_message(
            event.sender_id,
            event.message,
            phrase.read.on,
        )

    @client.on(d.cmd(r"(?i)^\.серв$"))
    async def server_load(event: Message):
        return await event.edit(await get_sys.get_system_info())

    @client.on(d.cmd(r"(?i)^\.токен (.+)"))
    async def ai_token(event: Message) -> None:
        token: str = event.pattern_match.group(1).strip()
        await Settings.set("ai.token", token)
        ai_client.change_api_key(token)
        await event.edit(phrase.ai.token_set)

    @client.on(d.cmd(r"(?i)^\.прокси (.+)"))
    async def ai_proxy(event: Message) -> None:
        proxy: str = event.pattern_match.group(1).strip()
        await Settings.set("ai.proxy", proxy)
        ai_client.change_api_key(proxy)
        await event.edit(phrase.ai.proxy_set)

    @client.on(d.cmd(r"(?i)^\.ии\s([\s\S]+)"))
    async def ai_resp(event: Message):
        if await Settings.get("ai.token") is None:
            return await event.edit(phrase.ai.no_token)
        text = event.pattern_match.group(1).strip()
        try:
            response = await ai_client.generate(text)
        except Exception as e:
            return await event.edit(phrase.error.format(e))
        try:
            if len(response) > 4096:
                response = formatter.splitter(response)
                await event.edit(response.pop(0))
                for chunk in response:
                    await event.reply(chunk)
            else:
                return await event.edit(response)
        except Exception as e:
            return await event.edit(phrase.error.format(e))

    @client.on(d.cmd(r"(?i)^\.релоадконфиг$"))
    async def config_reload(event: Message) -> None:
        await Settings._ensure_loaded(forced=True)
        return await event.edit(phrase.config.reload)

    @client.on(d.cmd(r"(?i)^\.автофарм$"))
    @client.on(d.cmd(r"(?i)^\.автоферма$"))
    async def on_off_farming(event: Message):
        nonlocal farm_task
        if await Settings.get("iris.farm"):
            await Settings.set("iris.farm", False)
            farm_task.stop()
            return await event.edit(phrase.farm.off)
        await Settings.set("iris.farm", True)
        await event.edit(phrase.farm.on)
        await farm_task.create(
            func=iris_farm,
            task_param=4,
            random_delay=(5, 360),
        )
        return None

    @client.on(d.cmd(r"(?i)^\.genpass(?:\s+(.+))?"))
    @client.on(d.cmd(r"(?i)^\.генпасс(?:\s+(.+))?"))
    @client.on(d.cmd(r"(?i)^\.пароль(?:\s+(.+))?"))
    async def generate_password(event: Message):
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

    if await Settings.get("block.voice"):
        client.add_event_handler(block_voice, events.NewMessage())
    if await Settings.get("luminto.reactions"):
        client.add_event_handler(
            reactions,
            events.NewMessage(chats="lumintoch"),
        )
        client.add_event_handler(
            reactions,
            events.NewMessage(chats="trassert_ch"),
        )
    if await Settings.get("iris.farm"):
        await farm_task.create(
            func=iris_farm,
            task_param=4,
            random_delay=(5, 360),
        )

    await client.run_until_disconnected()


async def run_userbot(number, api_id, api_hash) -> None:
    """Обертка для запуска userbot с обработкой исключений."""
    try:
        await userbot(number, api_id, api_hash)
    except Exception:
        logger.exception(f"Критическая ошибка в {number}")


async def main() -> None:
    try:
        clients = listdir("clients")
        logger.info(f"Клиенты: {clients}")
        if clients == []:
            raise FileNotFoundError
        tasks = []
        for client in clients:
            async with aiofiles.open(path.join("clients", client), "rb") as f:
                data = orjson.loads(await f.read())
            task = run_userbot(
                client.replace(".json", ""),
                data["api_id"],
                data["api_hash"],
            )
            tasks.append(task)
        await asyncio.gather(*tasks)
    except FileNotFoundError:
        try:
            mkdir("clients")
        except Exception:
            pass
        logger.warning("Нет ни одного клиента! Создаём нового..")
        number = input("Введи номер: ")
        api_id = int(input("Введи api_id: "))
        api_hash = input("Введи api_hash: ")
        async with aiofiles.open(
            path.join("clients", f"{number}.json"), "wb"
        ) as f:
            await f.write(
                orjson.dumps(
                    {"api_id": api_id, "api_hash": api_hash},
                    option=orjson.OPT_INDENT_2,
                )
            )
        await main()


if __name__ == "__main__":
    try:
        try:
            import uvloop

            uvloop.run(main())
        except ModuleNotFoundError:
            logger.warning(
                "Uvloop не найден!\n"
                "Установите его для большей производительности\n"
                "> pip install uvloop"
            )
            asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("Закрываю бота...")
