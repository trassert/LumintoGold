import re
import json
import random
import asyncio

from loguru import logger
from sys import stderr
from telethon import events
from telethon import functions, types
from telethon.sync import TelegramClient
from telethon.tl.types import MessageMediaDocument, PeerUser
from telethon.tl.custom import Message

from time import time
from os import path, mkdir
# from threading import Thread, Lock

import modules.phrases as phrase
from modules.flip_map import flip_map
from modules.iterators import Counter
import modules.get_sys as get_sys

logger.remove()
logger.add(
    stderr,
    format="<blue>{time:HH:mm:ss}</blue>"
    " | <level>{level}</level>"
    " | <green>{function}</green>"
    " | <green>{thread.name}</green>"
    " <cyan>></cyan> {message}",
    level="INFO",
    colorize=True,
)

# lock = Lock()


async def userbot(phone_number, api_id, api_hash):
    # lock.acquire()

    def settings(key, value=None, delete=None):
        "Изменить/получить ключ из настроек"
        if value is not None:
            logger.info(f"Значение {key} теперь {value}")
            try:
                with open(
                    path.join("clients", f"{phone_number}.json"), "r", encoding="utf-8"
                ) as f:
                    data = json.load(f)
                with open(
                    path.join("clients", f"{phone_number}.json"), "w", encoding="utf-8"
                ) as f:
                    data[key] = value
                    data = dict(sorted(data.items()))
                    return json.dump(data, f, indent=4, ensure_ascii=False)
            except FileNotFoundError:
                logger.error("Файл не найден")
                with open(
                    path.join("clients", f"{phone_number}.json"), "w", encoding="utf-8"
                ) as f:
                    data = {}
                    data[key] = value
                    return json.dump(data, f, indent=4)
            except json.decoder.JSONDecodeError:
                logger.error("Ошибка при чтении файла")
                with open(
                    path.join("clients", f"{phone_number}.json"), "w", encoding="utf-8"
                ) as f:
                    json.dump({}, f, indent=4)
                return None
        elif delete is not None:
            logger.info(f"Удаляю ключ: {key}")
            with open(
                path.join("clients", f"{phone_number}.json"), "r", encoding="utf-8"
            ) as f:
                data = json.load(f)
            with open(
                path.join("clients", f"{phone_number}.json"), "w", encoding="utf-8"
            ) as f:
                if key in data:
                    del data[key]
                return json.dump(data, f, indent=4, ensure_ascii=False)
        else:
            logger.info(f"Получаю ключ: {key}")
            try:
                with open(
                    path.join("clients", f"{phone_number}.json"), "r", encoding="utf-8"
                ) as f:
                    data = json.load(f)
                    return data.get(key)
            except json.decoder.JSONDecodeError:
                logger.error("Ошибка при чтении файла")
                with open(
                    path.join("clients", f"{phone_number}.json"), "w", encoding="utf-8"
                ) as f:
                    json.dump({}, f, indent=4)
                return None
            except FileNotFoundError:
                logger.error("Файл не найден")
                with open(
                    path.join("clients", f"{phone_number}.json"), "w", encoding="utf-8"
                ) as f:
                    json.dump({}, f, indent=4)
                return None

    client = TelegramClient(
        session=f"clients/{phone_number}",
        api_id=api_id,
        api_hash=api_hash,
        use_ipv6=False,
        system_version="4.16.30-vxCUSTOM",
        device_model="Telegram Helpbot (trassert)",
        system_lang_code="ru",
    )
    logger.info(f"Запускаю клиент ({phone_number})")
    await client.start(phone=phone_number)
    # lock.release()

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

    async def ads():
        n = 277
        while True:
            for id in [
                -1002099619201,
                -1001331993835,
                -1002122910801,
                -1001558923105,
                -1001523623779,
                -1001807725339,
                -1001801979291,
            ]:
                try:
                    await client.forward_messages(
                        id,
                        n,
                        -1002783775634,
                    )
                    logger.warning("Отправил рекламу!")
                    await asyncio.sleep(700)
                except Exception:
                    logger.error("Не получилось отправить рекламу")

    async def iris_farm():
        await asyncio.sleep(random.randint(0, 750))
        while True:
            await client.send_message(
                -1002355128955,
                random.choice(["/ферма", "/фарма", "!бизнес"]),
            )
            logger.warning("Фармлю!")
            await asyncio.sleep(14500)

    async def typing(event: Message):
        try:
            original = event.text.split(" ", maxsplit=1)[1]
        except Exception:
            return await client.edit_message(
                event.sender_id, event.message, phrase.no_args
            )
        text = original
        bep = ""
        while bep != original:
            await client.edit_message(
                event.sender_id, event.message, bep + settings("typings")
            )
            await asyncio.sleep(settings("delay"))
            bep = bep + text[0]
            text = text[1:]
            await client.edit_message(event.chat_id, event.message, bep)
            await asyncio.sleep(settings("delay"))

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
        await client.edit_message(
            event.sender_id, event.message, phrase.words.all.replace("~", "0")
        )
        async for message in client.iter_messages(event.chat_id):
            total += 1
            if total % 200 == 0:
                await client.edit_message(
                    event.sender_id,
                    event.message,
                    phrase.words.all.replace("~", str(total)),
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
        freq = sorted(words, key=words.get, reverse=True)
        out = phrase.words.out
        minsize = 50
        maxsize = len(freq) if len(freq) < minsize else minsize
        if arg2 is not None:
            if arg2 < len(freq):
                maxsize = arg2
        for i in range(maxsize):
            out += f"{i + 1}. {words[freq[i]]}: {freq[i]}\n"
        await client.edit_message(event.chat_id, event.message, out)

    async def ping(event: Message):
        timestamp = event.date.timestamp()
        ping = round(time() - timestamp, 2)
        if ping < 0:
            ping = phrase.ping.min
        else:
            ping = f"за {str(ping)} сек."
        await client.edit_message(
            event.chat_id, event.message, phrase.ping.form.replace("~", ping)
        )

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
        return await client.edit_message(
            event.chat_id, event.message, "".join(reversed(list(final_str)))
        )

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
            text = settings("voice_message")
            if text is None:
                settings("voice_message", phrase.voice.default_message)
                text == phrase.voice.default_message
            await event.respond(text)

    async def on_off_block_voice(event: Message):
        if settings("block_voice"):
            settings("block_voice", False)
            await event.edit(phrase.voice.unblock)
            client.remove_event_handler(block_voice)
        else:
            settings("block_voice", True)
            await event.edit(phrase.voice.block)
            client.add_event_handler(block_voice, events.NewMessage())

    async def on_off_mask_read(event: Message):
        all_chats = settings("mask_read")
        if event.chat_id in all_chats:
            all_chats.remove(event.chat_id)
            settings("mask_read", all_chats)
            event.client.remove_event_handler(
                mask_read_any, events.NewMessage(chats=event.chat_id)
            )
            return await event.client.edit_message(
                event.sender_id, event.message, phrase.read.off
            )
        else:
            all_chats.append(event.chat_id)
            settings("mask_read", all_chats)
            event.client.add_event_handler(
                mask_read_any, events.NewMessage(chats=event.chat_id)
            )
            return await event.client.edit_message(
                event.sender_id, event.message, phrase.read.on
            )

    async def server_load(event: Message):
        return await client.edit_message(
            event.chat_id, event.message, get_sys.get_system_info()
        )

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

    # client.add_event_handler(anim, events.NewMessage(outgoing=True, pattern=r"\.аним"))

    client.add_event_handler(typing, events.NewMessage(outgoing=True, pattern=r"\.т "))
    client.add_event_handler(words, events.NewMessage(outgoing=True, pattern=r"\.слов"))

    client.add_event_handler(ping, events.NewMessage(outgoing=True, pattern=r"\.пинг"))

    client.add_event_handler(reactions, events.NewMessage(chats="lumintoch"))
    client.add_event_handler(reactions, events.NewMessage(chats="trassert_ch"))

    if phone_number == "79116978417":
        logger.warning("Запускаю рекламу!")
        asyncio.create_task(ads())
    asyncio.create_task(iris_farm())

    await client.run_until_disconnected()


# if __name__ == "__main__":
#     try:
#         with open(path.join("clients", "all.json"), "r", encoding="utf-8") as f:
#             all = json.load(f)
#             for number in all.keys():
#                 if number != list(all.keys())[-1]:
#                     Thread(
#                         target=run,
#                         args=(
#                             userbot(
#                                 number, all[number]["api_id"], all[number]["api_hash"]
#                             ),
#                         ),
#                         name=number,
#                         daemon=True,
#                     ).start()
#                 else:
#                     run(userbot(number, all[number]["api_id"], all[number]["api_hash"]))
#     except FileNotFoundError:
#         mkdir("clients")
#         logger.info("Заполните, пожалуйста, файл clients\\all.json")


async def run_userbot(number, api_id, api_hash):
    """Обертка для запуска userbot с обработкой исключений"""
    try:
        await userbot(number, api_id, api_hash)
    except Exception as e:
        logger.error(f"Ошибка в userbot {number}: {e}")

async def main():
    try:
        with open(path.join("clients", "all.json"), "r", encoding="utf-8") as f:
            all_data = json.load(f)
            
            # Создаем задачи для всех userbot
            tasks = []
            for number, config in all_data.items():
                task = run_userbot(
                    number, 
                    config["api_id"], 
                    config["api_hash"]
                )
                tasks.append(task)
            
            # Запускаем все userbot одновременно
            await asyncio.gather(*tasks)
            
    except FileNotFoundError:
        mkdir("clients")
        logger.info("Заполните, пожалуйста, файл clients\\all.json")

if __name__ == "__main__":
    # Запускаем все асинхронно
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Закрываю бота...")