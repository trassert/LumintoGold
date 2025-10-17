import re
import aiofiles
import random
import asyncio
import logging
import orjson

import modules.phrases as phrase
from modules.flip_map import flip_map
from modules.iterators import Counter
from modules.settings import UBSettings
import modules.get_sys as get_sys

from loguru import logger
from sys import stderr
from telethon import events
from telethon import functions, types
from telethon.sync import TelegramClient
from telethon.tl.types import MessageMediaDocument, PeerUser
from telethon.tl.custom import Message
from time import time
from os import mkdir, listdir, path


logger.remove()
logger.add(
    stderr,
    format="<blue>{time:HH:mm:ss}</blue>"
    " | <level>{level}</level>"
    " | <green>{function}</green>"
    " <cyan>></cyan> {message}",
    level="INFO",
    colorize=True,
)


class InterceptHandler(logging.Handler):
    def emit(self, record):
        level = "TRACE" if record.levelno == 5 else record.levelname
        logger.opt(depth=6, exception=record.exc_info).log(
            level, record.getMessage()
        )


logging.basicConfig(handlers=[InterceptHandler()], level=0)


async def userbot(phone_number: str, api_id: int, api_hash: str):
    Settings = UBSettings(phone_number, "clients")
    client = TelegramClient(
        session=f"sessions/{phone_number}",
        api_id=api_id,
        api_hash=api_hash,
        use_ipv6=True,
        system_version="4.16.30-vxCUSTOM",
        device_model="LumintoGold",
        system_lang_code="ru",
    )
    logger.info(f"Запускаю клиент ({phone_number})")
    await client.start(phone=phone_number)

    farm_task = None

    async def reactions(event: Message):
        await asyncio.sleep(random.randint(0, 1000))
        logger.info("Отправил реакцию!")
        return await client(
            functions.messages.SendReactionRequest(
                peer=event.peer_id,
                msg_id=event.message.id,
                big=True,
                add_to_recent=True,
                reaction=[types.ReactionEmoji(emoticon="❤️")],
            )
        )

    async def iris_farm():
        await asyncio.sleep(random.randint(0, 750))
        while True:
            await client.send_message(
                -1002355128955,
                random.choice(["/ферма", "/фарма"]),
            )
            logger.warning("Фармлю!")
            await asyncio.sleep(14500)

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

    async def words(event: Message):
        arg = None
        arg2 = None
        try:
            args = event.text.split()
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
            phrase.words.all.format(words=total, dots=dots)
        )

        async for message in client.iter_messages(event.chat_id):
            total += 1
            if total % 200 == 0:
                try:
                    dots = dots + "." if len(dots) < 3 else ""
                    await msg.edit(
                        phrase.words.all.format(words=total, dots=dots)
                    )
                except Exception:
                    await asyncio.sleep(await Settings.get("typing.delay"))
                    try:
                        msg = await event.reply(
                            phrase.words.except_all.format(total)
                        )
                    except Exception:
                        pass
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
        maxsize = len(freq) if len(freq) < minsize else minsize
        if arg2 is not None:
            if arg2 < len(freq):
                maxsize = arg2
        for i in range(maxsize):
            out += f"{i + 1}. {words[freq[i]]}: {freq[i]}\n"
        try:
            await msg.edit(out)
        except Exception:
            await event.reply(out)

    async def ping(event: Message):
        timestamp = event.date.timestamp()
        ping = round(time() - timestamp, 2)
        if ping < 0:
            ping = phrase.ping.min
        else:
            ping = f"за {str(ping)} сек."
        await event.edit(phrase.ping.form.replace("~", ping))

    async def mask_read_any(event: Message):
        "Просматривает сообщение"
        return await event.mark_read()

    async def flip_text(event: Message):
        text = event.text.split(" ", maxsplit=1)[1]
        final_str = ""
        for char in text:
            if char in flip_map.keys():
                new_char = flip_map[char]
            else:
                new_char = char
            final_str += new_char
        return await event.edit("".join(reversed(list(final_str))))

    async def block_voice(event: Message):
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
                    "voice.message", phrase.voice.default_message
                )
            )

    async def on_off_block_voice(event: Message):
        if await Settings.get("block.voice"):
            await Settings.set("block.voice", False)
            await event.edit(phrase.voice.unblock)
            client.remove_event_handler(block_voice)
        else:
            await Settings.set("block.voice", True)
            await event.edit(phrase.voice.block)
            client.add_event_handler(block_voice, events.NewMessage())

    async def on_off_mask_read(event: Message):
        all_chats = await Settings.get("mask.read")
        if event.chat_id in all_chats:
            all_chats.remove(event.chat_id)
            await Settings.set("mask.read", all_chats)
            event.client.remove_event_handler(
                mask_read_any, events.NewMessage(chats=event.chat_id)
            )
            return await event.client.edit_message(
                event.sender_id, event.message, phrase.read.off
            )
        else:
            all_chats.append(event.chat_id)
            await Settings.set("mask.read", all_chats)
            event.client.add_event_handler(
                mask_read_any, events.NewMessage(chats=event.chat_id)
            )
            return await event.client.edit_message(
                event.sender_id, event.message, phrase.read.on
            )

    async def server_load(event: Message):
        return await event.edit(get_sys.get_system_info())

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^/автофарм$"))
    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^/автоферма$"))
    async def on_off_farming(event: Message):
        nonlocal farm_task
        if await Settings.get("iris.farm"):
            await Settings.set("iris.farm", False)
            if farm_task is not None:
                farm_task.cancel()
                return await event.edit(phrase.farm.off)
            return await event.edit(phrase.farm.off_notask)
        else:
            await Settings.set("iris.farm", True)
            await event.edit(phrase.farm.on)
            farm_task = asyncio.create_task(iris_farm())

    client.add_event_handler(
        on_off_block_voice, events.NewMessage(outgoing=True, pattern=r"\.гс")
    )
    client.add_event_handler(
        on_off_mask_read, events.NewMessage(outgoing=True, pattern=r"\.читать")
    )
    client.add_event_handler(
        server_load, events.NewMessage(outgoing=True, pattern=r"\.серв")
    )
    client.add_event_handler(
        flip_text, events.NewMessage(outgoing=True, pattern=r"\.флип")
    )
    client.add_event_handler(
        typing, events.NewMessage(outgoing=True, pattern=r"\.т ")
    )
    client.add_event_handler(
        words, events.NewMessage(outgoing=True, pattern=r"\.слов")
    )
    client.add_event_handler(
        ping, events.NewMessage(outgoing=True, pattern=r"\.пинг")
    )

    if await Settings.get("block.voice"):
        client.add_event_handler(block_voice, events.NewMessage())
    if await Settings.get("luminto.reactions", True):
        client.add_event_handler(
            reactions, events.NewMessage(chats="lumintoch")
        )
        client.add_event_handler(
            reactions, events.NewMessage(chats="trassert_ch")
        )

    if await Settings.get("iris.farm"):
        farm_task = asyncio.create_task(iris_farm())

    await client.run_until_disconnected()


async def run_userbot(number, api_id, api_hash):
    """Обертка для запуска userbot с обработкой исключений"""
    try:
        await userbot(number, api_id, api_hash)
    except Exception as e:
        logger.error(f"Ошибка в userbot {number}: {e}")


async def main():
    try:
        clients = listdir("clients")
        tasks = []
        for client in clients:
            async with aiofiles.open(path.join("clients", client), "rb") as f:
                data = orjson.loads(await f.read())
            task = run_userbot(
                client.replace(".json", ""), data["api_id"], data["api_hash"]
            )
            tasks.append(task)
        await asyncio.gather(*tasks)
    except FileNotFoundError:
        mkdir("clients")
        logger.error("Создайте, пожалуйста, файлы в clients")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("Закрываю бота...")
