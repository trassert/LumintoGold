import asyncio
import contextlib
import logging
import random
import re
from pathlib import Path
from sys import stderr
from time import time

import aiofiles
import orjson
from loguru import logger
from telethon import TelegramClient, events, functions, types
from telethon.tl.custom import Message
from telethon.tl.custom.participantpermissions import ParticipantPermissions
from telethon.tl.functions.account import UpdateStatusRequest
from telethon.tl.types import (
    MessageMediaDocument,
    MessageService,
    PeerUser,
    User,
)

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
logger.info("LumintoGold запускается...")

try:
    from vkbottle import Bot
    from vkbottle.tools import PhotoWallUploader

    import_vkbottle = True
except ModuleNotFoundError:
    import_vkbottle = False
    logger.warning("Нету vkbottle! Транслятор tg->vk не будет работать.")


class InterceptHandler(logging.Handler):
    def emit(self, record):
        level = "TRACE" if record.levelno == 5 else record.levelname
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


logging.basicConfig(handlers=[InterceptHandler()], level=0)


class UserbotManager:
    def __init__(self, phone: str, api_id: int, api_hash: str):
        self.phone = phone
        self.settings = settings.UBSettings(phone, "clients")
        self.session_path = Path("sessions") / phone
        self.voice_path = pathes.voice / phone
        self.client = TelegramClient(
            session=str(self.session_path),
            api_id=api_id,
            api_hash=api_hash,
            use_ipv6=False,
            system_version="4.16.30-vxCUSTOM",
            device_model="LumintoGold",
            system_lang_code="ru",
            lang_code="ru",
            connection_retries=-1,
            retry_delay=3,
        )
        self.iris_task = task_gen.Generator(f"{phone}_iris")
        self.online_task = task_gen.Generator(f"{phone}_online")
        self.iceyes_task = task_gen.Generator(f"{phone}_iceyes")
        self.battery_task = task_gen.Generator(f"{phone}_battery")
        self.batt_state = True
        self.notes = notes.Notes(phone)
        self.flood_ctrl = flood.FloodController(self.client, self.settings)
        self.autochat = autochat.AutoChatManager(self.client, self.settings)

    async def init(self):
        use_ipv6 = await self.settings.get("use.ipv6")
        self.client.use_ipv6 = use_ipv6
        self.ai_client = ai.Chat(
            self.phone,
            await self.settings.get("ai.token"),
            model=await self.settings.get("ai.model"),
        )
        try:
            self.groq = ai.Groq(
                self.phone,
                await self.settings.get("groq.token"),
                await self.settings.get("groq.proxy"),
            )
            self.groq.init_client()
        except Exception:
            logger.warning("Установите войс-токен (.войстокен <токен>)")
        await self.client.start(phone=self.phone)
        logger.info(f"Запущен клиент ({self.phone})")
        self._register_handlers()

        if await self.settings.get("block.voice"):
            self.client.add_event_handler(self.block_voice, events.NewMessage())

        if await self.settings.get("luminto.reactions"):
            for chat in ("lumintoch", "trassert_ch"):
                self.client.add_event_handler(self.reactions, events.NewMessage(chats=chat))

        if await self.settings.get("iris.farm"):
            await self.iris_task.create(func=self.iris_farm, task_param=4, random_delay=(5, 360))

        if await self.settings.get("iceyes.bonus"):
            await self.iceyes_task.create(
                func=self.iceyes_bonus, task_param=1, random_delay=(1, 60)
            )

        if await self.settings.get("auto.online"):
            await self.online_task.create(func=self.auto_online, task_param=30, unit="seconds")

        if await self.settings.get("autochat.enabled"):
            await self.autochat.start()

        if await self.settings.get("tg2vk.enabled", False):
            target_chat = await self.settings.get("tg2vk.chat")
            if target_chat:
                self.client.add_event_handler(
                    self._handle_tg_to_vk, events.NewMessage(chats=target_chat)
                )

        if await self.settings.get("battery.status"):
            await self.battery_task.create(func=self.chk_battery, task_param=15, unit="seconds")

    def _register_handlers(self):
        if import_vkbottle:
            self.client.on(d.cmd(r"\.тгвк$"))(self.toggle_tg_to_vk)

        self.client.on(d.cmd(r"\.\$(.+)"))(self.run_shell)

        self.client.on(d.cmd(r"\+нот (.+)\n([\s\S]+)"))(self.add_note)
        self.client.on(d.cmd(r"\-нот (.+)"))(self.rm_note)
        self.client.on(d.cmd(r"\!(.+)"))(self.chk_note)
        self.client.on(d.cmd(r"\.ноты$"))(self.list_notes)

        self.client.on(d.cmd(r"\.чистка"))(self.clean_pm)
        self.client.on(d.cmd(r"\.voice$"))(self.voice2text)
        self.client.on(d.cmd(r"\.баттмон$"))(self.toggle_batt)
        self.client.on(d.cmd(r"\.чатчистка$"))(self.clean_chat)
        self.client.on(d.cmd(r"\.слов"))(self.words)
        self.client.on(d.cmd(r"\.пинг$"))(self.ping)
        self.client.on(d.cmd(r"\.эмоид$"))(self.get_emo_id)
        self.client.on(d.cmd(r"\.флип"))(self.flip_text)
        self.client.on(d.cmd(r"\.гс$"))(self.on_off_block_voice)
        self.client.on(d.cmd(r"\.читать$"))(self.on_off_mask_read)
        self.client.on(d.cmd(r"\.серв$"))(self.server_load)
        self.client.on(d.cmd(r"\.релоадконфиг$"))(self.config_reload)
        self.client.on(d.cmd(r"\.автоферма$"))(self.on_off_farming)
        self.client.on(d.cmd(r"\.онлайн$"))(self.toggle_online)
        self.client.on(d.cmd(r"\.автобонус$"))(self.on_off_bonus)

        self.client.on(d.cmd(r"\.иичистка"))(self.ai_clear)
        self.client.on(d.cmd(r"\.иитокен (.+)"))(self.ai_token)
        self.client.on(d.cmd(r"\.войспрокси (.+)"))(self.voiceproxy)
        self.client.on(d.cmd(r"\.войстокен (.+)"))(self.voicetoken)
        self.client.on(d.cmd(r"\.иимодель (.+)"))(self.ai_model)
        self.client.on(d.cmd(r"\.погода (.+)"))(self.get_weather)
        self.client.on(d.cmd(r"\.ip (.+)"))(self.ipman)
        self.client.on(d.cmd(r"\.аним (.+)"))(self.anim)
        self.client.on(d.cmd(r"\.ии ([\s\S]+)"))(self.ai_resp)
        self.client.on(d.cmd(r"\.т ([\s\S]+)"))(self.typing)
        self.client.on(d.cmd(r"\.set (.+)"))(self.set_setting)
        self.client.on(d.cmd(r"\.setint (.+)"))(self.set_int_setting)
        self.client.on(d.cmd(r"\.время (.+)"))(self.time_by_city)
        self.client.on(d.cmd(r"\.ад(?:\s|$)"))(self.autodelmsg)

        self.client.on(
            d.cmd(
                r"\.genpass(?:\s+(.+))?",
            )
        )(self.gen_pass)
        self.client.on(
            d.cmd(
                r"\.генпасс(?:\s+(.+))?",
            )
        )(self.gen_pass)
        self.client.on(
            d.cmd(
                r"\.пароль(?:\s+(.+))?",
            )
        )(self.gen_pass)

        self.client.on(events.NewMessage())(self.flood_ctrl.monitor)
        self.client.on(d.cmd(r"\-флудстики (\d+) (\d+)$"))(
            lambda e: self.flood_ctrl.set_rule(e, "stickers")
        )
        self.client.on(d.cmd(r"\-флудгиф (\d+) (\d+)$"))(
            lambda e: self.flood_ctrl.set_rule(e, "gifs")
        )
        self.client.on(d.cmd(r"\-флудобщ (\d+) (\d+)$"))(
            lambda e: self.flood_ctrl.set_rule(e, "messages")
        )
        self.client.on(d.cmd(r"\+флудстики$"))(lambda e: self.flood_ctrl.unset_rule(e, "stickers"))
        self.client.on(d.cmd(r"\+флудгиф$"))(lambda e: self.flood_ctrl.unset_rule(e, "gifs"))
        self.client.on(d.cmd(r"\+флудобщ$"))(lambda e: self.flood_ctrl.unset_rule(e, "messages"))

        self.client.on(d.cmd(r"\+авточат (-?\d+)"))(self.autochat.add_chat)
        self.client.on(d.cmd(r"\-авточат (-?\d+)"))(self.autochat.remove_chat)
        self.client.on(d.cmd(r"\.авточат$"))(self.autochat.toggle)
        self.client.on(d.cmd(r"\.авточаттайм (\d+)"))(self.autochat.set_delay)

        self.client.on(d.cmd(r"\.калк (.+)"))(self.calc)
        self.client.on(d.cmd(r"\.к (.+)"))(self.calc)
        self.client.on(d.cmd(r"\.calc (.+)"))(self.calc)

        self.client.on(events.NewMessage())(self._dynamic_mask_reader)

    async def clean_chat(self, event: Message):
        if event.is_private:
            return await event.edit(phrase.clear.private)

        chat = await event.get_chat()
        if not hasattr(chat, "title"):
            return await event.edit(phrase.not_a_chat)

        try:
            me = await self.client.get_me()
            admin_rights: ParticipantPermissions = await self.client.get_permissions(chat, me)
            if not admin_rights.ban_users:
                return await event.edit(phrase.clear.no_rights)

        except Exception:
            return await event.edit(phrase.clear.no_rights)

        await event.edit(phrase.clear.start)

        kicked = 0
        unbanned = 0

        async for user in self.client.iter_participants(chat):
            if user.deleted:
                try:
                    await self.client.kick_participant(chat, user.id)
                    kicked += 1
                    if kicked % 5 == 0:
                        await event.edit(phrase.clear.kick.format(count=kicked))
                except Exception:
                    logger.trace("Не могу удалить участника")
            await asyncio.sleep(await self.settings.get("typing.delay"))

        async for ban in self.client.iter_participants(
            chat, filter=types.ChannelParticipantsKicked
        ):
            user: User = ban
            if user and user.deleted:
                try:
                    await self.client.edit_permissions(chat, user, view_messages=True)
                    unbanned += 1
                    if unbanned % 5 == 0:
                        await event.edit(phrase.clear.unban.format(count=unbanned))
                except Exception:
                    logger.trace("Не могу вынести из бана участника")
            await asyncio.sleep(await self.settings.get("typing.delay"))

        if kicked or unbanned:
            await event.edit(phrase.clear.done.format(kicked=kicked, unbanned=unbanned))
        else:
            await event.edit(phrase.clear.not_found)

    async def chk_battery(self):
        async with aiofiles.open(config.config.battery_path) as f:
            if "Discharging" in await f.read():
                if self.batt_state is True:
                    logger.warning("Нет зарядки!")
                    await self.client.send_message(
                        entity=int(await self.settings.get("battery.chat")),
                        message=await self.settings.get("battery.msg_no"),
                    )
                    self.batt_state = False
            else:
                if self.batt_state is False:
                    await self.client.send_message(
                        entity=int(await self.settings.get("battery.chat")),
                        message=await self.settings.get("battery.msg_yes"),
                    )
                    self.batt_state = True

    async def reactions(self, event: Message):
        await asyncio.sleep(random.randint(0, 1000))
        try:
            await self.client(
                functions.messages.SendReactionRequest(
                    peer=event.peer_id,
                    msg_id=event.message.id,
                    big=True,
                    add_to_recent=True,
                    reaction=[types.ReactionEmoji(emoticon="❤️")],
                )
            )
            logger.info("Отправил реакцию!")
        except Exception:
            pass

    async def _start_iris_farm(self):
        await self.iris_task.create(func=self.iris_farm, task_param=4, random_delay=(5, 360))

    async def _start_iceyes_bonus(self):
        await self.iceyes_task.create(func=self.iceyes_bonus, task_param=1, random_delay=(1, 60))

    async def _start_auto_online(self):
        await self.online_task.create(func=self.auto_online, task_param=30, unit="seconds")

    async def _start_mon_batt(self):
        await self.battery_task.create(func=self.chk_battery, task_param=15, unit="seconds")

    async def _autochat_sender(self):
        chat_ids = await self.settings.get("autochat.chats", [])
        ad_chat = await self.settings.get("autochat.ad_chat")
        ad_id = await self.settings.get("autochat.ad_id")

        if not chat_ids or not ad_chat or not ad_id:
            return

        for chat_id in chat_ids:
            try:
                await self.client.forward_messages(chat_id, int(ad_id), ad_chat)
                logger.info(f"Автопостинг: сообщение отправлено в {chat_id}")
            except Exception:
                logger.trace(f"Автопостинг: ошибка при отправке в {chat_id}")
            await asyncio.sleep(1)

    async def toggle_tg_to_vk(self, event: Message):
        if not import_vkbottle:
            return await event.edit(phrase.tg2vk.no_vkbottle)

        enabled = await self.settings.get("tg2vk.enabled", False)
        target_chat = await self.settings.get("tg2vk.chat")
        vk_group = await self.settings.get("tg2vk.vk_group")
        vk_token = await self.settings.get("tg2vk.vk_token")

        if not target_chat:
            await self.settings.set("tg2vk.enabled", False)
            return await event.edit(phrase.tg2vk.missing_config)

        if not enabled:
            if not vk_group or not vk_token:
                await self.settings.set("tg2vk.enabled", False)
                return await event.edit(phrase.tg2vk.missing_config)
            logger.debug("tg2vk: enabled")
            self.client.add_event_handler(
                self._handle_tg_to_vk, events.NewMessage(chats=target_chat)
            )
            await self.settings.set("tg2vk.enabled", True)
            await event.edit(phrase.tg2vk.on)
        else:
            logger.debug("tg2vk: disabled")
            self.client.remove_event_handler(self._handle_tg_to_vk)
            await self.settings.set("tg2vk.enabled", False)
            await event.edit(phrase.tg2vk.off)

    async def _handle_tg_to_vk(self, event: Message):
        logger.info("tg2vk: Новый пост")
        vk_token = await self.settings.get("tg2vk.vk_token")
        vk_group_id = await self.settings.get("tg2vk.vk_group")
        if not vk_token or not vk_group_id:
            return logger.error("tg2vk: Отсутствует токен или ID группы")

        attachments = []
        bot = Bot(token=vk_token)

        try:
            text = format.f2vk(event.text)

            if event.photo:
                path = await event.download_media(file=bytes)
                uploader = PhotoWallUploader(bot.api)
                photo = await uploader.upload(path)
                attachments.append(photo)

            resp = await bot.api.wall.post(
                owner_id=-abs(int(vk_group_id)),
                message=text,
                attachments=attachments,
            )
            logger.info(f"tg2vk: Пост опубликован (ID={resp.post_id})")
        except Exception:
            logger.trace("tg2vk: Ошибка публикации")

    async def get_emo_id(self, event: Message):
        message: Message = await event.get_reply_message()
        if message is None or not message.entities:
            return await event.edit(phrase.emoji.no_entity)

        text = [
            f"`{entity.document_id}`"
            for entity in message.entities
            if hasattr(entity, "document_id")
        ]

        if not text:
            return await event.edit(phrase.emoji.no_entity)

        return await event.edit(phrase.emoji.get.format(", ".join(text)))

    async def iris_farm(self):
        target = -1002355128955
        try:
            await self.client.send_message(target, random.choice(["/ферма", "/фарма"]))
        except Exception:
            await self.client.send_message("iris_cm_bot", random.choice(["/ферма", "/фарма"]))
        logger.info(f"{self.phone} - сработала автоферма")

    async def iceyes_bonus(self):
        await self.client.send_message("iceyes_bot", "💸 Бонус")
        await self.client.send_message("icetik_bot", "💸 Бонус")
        logger.info(f"{self.phone} - сработал автобонус")

    async def add_note(self, event: Message):
        full_text = event.message.message or ""
        name = event.pattern_match.group(1).strip().lower()

        note_text = ""
        if "\n" in full_text:
            note_text = full_text.split("\n", maxsplit=1)[1]

        media = None
        if event.photo:
            media = event.photo
        elif event.is_reply:
            reply = await event.get_reply_message()
            if reply and reply.photo:
                media = reply.photo

        result = await self.notes.add(name, note_text, media=media, client=self.client)

        if result is False:
            return await event.edit(phrase.notes.error.format(phrase.notes.err_cr))
        return await event.edit(phrase.notes.new.format(name))

    async def rm_note(self, event: Message):
        name = event.pattern_match.group(1).strip().lower()
        if (await self.notes.delete(name)) is False:
            return await event.edit(phrase.notes.error.format(phrase.notes.err_rm))
        return await event.edit(phrase.notes.deleted)

    async def chk_note(self, event: Message):
        arg: str = event.pattern_match.group(1)

        if arg.isdigit():
            note = await self.notes.get_by_index(int(arg))
        else:
            note = await self.notes.get(arg)

        if not note:
            return await event.edit(phrase.notes.not_found)

        if note.get("media"):
            return await event.edit(note["text"], file=note["media"])
        return await event.edit(note["text"])

    async def list_notes(self, event: Message):
        list_notes = await self.notes.get_list()
        if not list_notes:
            return await event.edit(phrase.notes.allnotext)

        text = [f"{i + 1}. {name.capitalize()}" for i, name in enumerate(list_notes)]
        return await event.edit(phrase.notes.alltext.format("\n".join(text)))

    async def auto_online(self):
        await self.client(UpdateStatusRequest(offline=False))

    async def _toggle_setting_and_task(
        self,
        setting_key: str,
        task_attr: str,
        on_phrase,
        off_phrase,
        start_func,
        event: Message,
    ):
        enabled = not await self.settings.get(setting_key)
        await self.settings.set(setting_key, enabled)

        task = getattr(self, task_attr)
        if enabled:
            await start_func()
            await event.edit(on_phrase)
        else:
            task.stop()
            await event.edit(off_phrase)

    async def on_off_farming(self, event: Message):
        await self._toggle_setting_and_task(
            "iris.farm",
            "iris_task",
            phrase.farm.on,
            phrase.farm.off,
            self._start_iris_farm,
            event,
        )

    async def on_off_bonus(self, event: Message):
        await self._toggle_setting_and_task(
            "iceyes.bonus",
            "iceyes_task",
            phrase.bonus.on,
            phrase.bonus.off,
            self._start_iceyes_bonus,
            event,
        )

    async def toggle_online(self, event: Message):
        await self._toggle_setting_and_task(
            "auto.online",
            "online_task",
            phrase.online.on,
            phrase.online.off,
            self._start_auto_online,
            event,
        )

    async def toggle_batt(self, event: Message):
        await self._toggle_setting_and_task(
            "battery.status",
            "battery_task",
            phrase.battmon.on,
            phrase.battmon.off,
            self._start_mon_batt,
            event,
        )

    async def on_off_block_voice(self, event: Message):
        enabled = not await self.settings.get("block.voice")
        await self.settings.set("block.voice", enabled)
        if enabled:
            self.client.add_event_handler(self.block_voice, events.NewMessage())
            await event.edit(phrase.voice.block)
        else:
            self.client.remove_event_handler(self.block_voice)
            await event.edit(phrase.voice.unblock)

    async def on_off_mask_read(self, event: Message):
        mask_read_chats = await self.settings.get("mask.read") or []
        if event.chat_id in mask_read_chats:
            mask_read_chats.remove(event.chat_id)
            await event.edit(phrase.read.off)
        else:
            mask_read_chats.append(event.chat_id)
            await event.edit(phrase.read.on)
        await self.settings.set("mask.read", mask_read_chats)

    async def _dynamic_mask_reader(self, event: Message):
        mask_read_chats = await self.settings.get("mask.read") or []
        if event.chat_id in mask_read_chats:
            await event.mark_read()

    async def block_voice(self, event: Message):
        if not isinstance(event.peer_id, PeerUser):
            return
        me = await self.client.get_me()
        if me.id == event.sender_id:
            return
        if isinstance(event.media, MessageMediaDocument) and event.media.voice:
            await event.delete()
            msg = await self.settings.get("voice.message", phrase.voice.default_message)
            await event.respond(msg)

    async def voice2text(self, event: Message):
        reply: Message = await event.get_reply_message()
        if not reply or not reply.voice:
            return await event.edit(phrase.voicerec.no_reply)

        file_path = self.voice_path / f"voice_{event.id}.ogg"
        await reply.download_media(file=str(file_path))

        try:
            return await event.edit(phrase.voicerec.done.format(await self.groq.voice(event.id)))

        except Exception as e:
            logger.exception("Ошибка при распознавании голоса")
            msg = phrase.voicerec.error.format(error=str(e)[:200])
            return await event.edit(msg)

    async def voiceproxy(self, event: Message):
        arg = event.pattern_match.group(1).strip()
        self.groq.proxy = arg
        await self.settings.set("groq.proxy", arg)
        self.groq.init_client()
        return await event.edit(phrase.voicerec.proxy)

    async def voicetoken(self, event: Message):
        arg = event.pattern_match.group(1).strip()
        self.groq.api_key = arg
        await self.settings.set("groq.token", arg)
        self.groq.init_client()
        return await event.edit(phrase.voicerec.token)

    async def ipman(self, event: Message):
        arg = event.pattern_match.group(1)
        if not ipman.is_valid_ip(arg):
            return await event.edit(phrase.ip.dont_match)
        response = await ipman.get_ip_info(arg)
        await event.edit(
            f"🌐 : IP: `{response.get('query')}`\n\n"
            f"Страна: {response.get('country')}\n"
            f"Регион: {response.get('regionName')}\n"
            f"Город: {response.get('city')}\n"
            f"Провайдер: {response.get('isp')}\n"
            f"Координаты: {response.get('lat')}/{response.get('lon')}"
        )

    async def get_weather(self, event: Message):
        await event.edit(phrase.weather.wait)
        result = await apis.get_weather(
            event.pattern_match.group(1),
            await self.settings.get("token.openweathermap"),
        )
        await event.edit(result)

    async def anim(self, event: Message):
        name = event.text.split(" ", maxsplit=1)[1]
        animation = await db.get_animation(name)
        if not animation:
            return await event.edit(phrase.anim.no)
        for title in animation["text"]:
            await event.edit(title)
            await asyncio.sleep(animation["delay"])

    async def clean_pm(self, event: Message):
        dialogs = await self.client.get_dialogs()
        deleted_count = 0
        msg = await event.edit(phrase.pm.wait.format(0))
        deleted = []
        for dialog in dialogs:
            user: User = dialog.entity
            if not isinstance(user, User):
                continue
            on_delete = False
            if user.deleted:
                on_delete = True
            else:
                messages = await self.client.get_messages(user.id, limit=10)
                if all(isinstance(msg, MessageService) for msg in messages):
                    on_delete = True
            if on_delete:
                deleted.append(f"[{user.first_name}](tg://user?id={user.id})")
                await self.client.delete_dialog(dialog.id)
                await asyncio.sleep(await self.settings.get("typing.delay"))
                deleted_count += 1
                if deleted_count % 5 == 0:
                    await msg.edit(phrase.pm.wait.format(deleted_count))

        await event.edit(phrase.pm.cleared.format(chats=deleted_count, list=", ".join(deleted)))

    async def set_setting(self, event: Message):
        key, value = event.pattern_match.group(1).split(" ", maxsplit=1)
        await self.settings.set(key, value)
        await event.edit(phrase.setting.set.format(key=key, value=value))

    async def set_int_setting(self, event: Message):
        key, value = event.pattern_match.group(1).split(" ", maxsplit=1)
        await self.settings.set(key, int(value))
        await event.edit(phrase.setting.setint.format(key=key, value=value))

    async def time_by_city(self, event: Message):
        city = event.pattern_match.group(1)
        location = tz.geolocator.geocode(city)
        if not location:
            return await event.edit(phrase.time.not_found.format(city))
        tz_name = await tz.get_timezone(
            location.latitude,
            location.longitude,
            await self.settings.get("token.geoapify"),
        )
        if not tz_name:
            return await event.edit(phrase.time.not_timezone.format(city))
        tzz = tz.pytz.timezone(tz_name)
        city_time = tz.datetime.now(tzz)
        await event.edit(
            f"📍 {location.address}\n"
            f"🕒 Время: {city_time.strftime('%H:%M:%S')}\n"
            f"📅 Дата: {city_time.strftime('%d.%m.%Y')}\n"
            f"🌐 Пояс: {tz_name}"
        )

    async def typing(self, event: Message):
        text = event.pattern_match.group(1).strip()
        bep = ""
        while bep != text:
            await event.edit(bep + await self.settings.get("typings"))
            await asyncio.sleep(await self.settings.get("typing.delay"))
            bep += text[len(bep)]
            await event.edit(bep)
            await asyncio.sleep(await self.settings.get("typing.delay"))

    async def words(self, event: Message):
        args = format.get_args(event.text.lower())
        arg_len = next(
            (int(x.replace("л", "")) for x in args if "л" in x and x.replace("л", "").isdigit()),
            None,
        )
        arg_count = next(
            (int(x.replace("в", "")) for x in args if "в" in x and x.replace("в", "").isdigit()),
            None,
        )

        words = iterators.Counter()
        total = 0
        dots = ""
        msg = await event.edit(phrase.words.all.format(words=total, dots=dots))

        async for message in self.client.iter_messages(event.chat_id):
            total += 1
            if total % 200 == 0:
                dots = dots + "." if len(dots) < 3 else ""
                try:
                    await msg.edit(phrase.words.all.format(words=total, dots=dots))
                except Exception:
                    await asyncio.sleep(await self.settings.get("typing.delay"))
                    with contextlib.suppress(Exception):
                        msg = await event.reply(phrase.words.except_all.format(total))

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
        if arg_count is not None:
            maxsize = min(arg_count, len(freq))
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
            phrase.ping.ping.format(timedel=f"{timedel} сек.", ping=f"{pingtime} сек.")
        )

    async def flip_text(self, event: Message):
        try:
            text = event.text.split(" ", maxsplit=1)[1]
        except IndexError:
            return await event.edit(phrase.no_text)
        flipped = "".join(flip_map.flip_map.get(c, c) for c in reversed(text))
        await event.edit(flipped)

    async def server_load(self, event: Message):
        await event.edit(await get_sys.get_system_info())

    async def ai_token(self, event: Message):
        token: str = event.pattern_match.group(1).strip()
        await self.settings.set("ai.token", token)
        self.ai_client.api_key = token
        await event.edit(phrase.ai.token_set)

    async def ai_model(self, event: Message):
        model: str = event.pattern_match.group(1).strip()
        await self.settings.set("ai.model", model)
        self.ai_client.model = model
        await event.edit(phrase.ai.model_set)

    async def ai_clear(self, event: Message):
        await self.ai_client.clear()
        await event.edit(phrase.ai.clear)

    async def ai_resp(self, event: Message):
        if not await self.settings.get("ai.token"):
            return await event.edit(phrase.ai.no_token)
        text = event.pattern_match.group(1).strip()
        try:
            response = await self.ai_client.send(text)
        except Exception as e:
            return await event.edit(phrase.error.format(e))
        if len(response) > 4096:
            chunks = format.splitter(response)
            await event.edit(chunks[0])
            for chunk in chunks[1:]:
                await event.reply(chunk)
        else:
            await event.edit(response)

    async def config_reload(self, event: Message):
        await self.settings._ensure_loaded(forced=True)
        await event.edit(phrase.config.reload)

    async def calc(self, event: Message):
        expr = event.pattern_match.group(1).strip()

        if not re.fullmatch(r"[\d+\-*/().\s]+", expr):
            return await event.edit(phrase.calc.invalid_chars)

        if any(c in expr for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_"):
            return await event.edit(phrase.calc.forbidden)

        try:
            result = eval(expr, {"__builtins__": {}}, {})
        except ZeroDivisionError:
            return await event.edit(phrase.calc.div_by_zero)
        except Exception:
            return await event.edit(phrase.calc.error)

        if isinstance(result, float) and result.is_integer():
            result = int(result)

        await event.edit(phrase.calc.result.format(expr, result))

    async def autodelmsg(self, event: Message):
        lines = event.text.splitlines()
        first_line = lines[0]
        rest_text = "\n".join(lines[1:]).strip()

        parts = first_line.split(maxsplit=2)
        if len(parts) < 2:
            return await event.edit(phrase.autodel.args)

        try:
            delay = int(parts[1])
            text = rest_text or (parts[2] if len(parts) > 2 else "")
        except ValueError:
            delay = config.config.wait_delete
            text = " ".join(parts[1:]) + ("\n" + rest_text if rest_text else "")

        if not text.strip():
            return await event.edit(phrase.autodel.empty)

        msg: Message = await event.edit(text.strip())
        await asyncio.sleep(delay)
        await msg.edit("...")
        await asyncio.sleep(1)
        await msg.delete()

    async def gen_pass(self, event: Message):
        args = (event.pattern_match.group(1) or "").strip()
        length = genpass.Default.length
        letters = genpass.Default.letters
        digits = genpass.Default.digits
        special = genpass.Default.special

        if match := re.search(r"д(\d+)", args):
            length = int(match[1])
        letters = (
            True if re.search(r"\+б", args) else (False if re.search(r"-б", args) else letters)
        )
        digits = True if re.search(r"\+ц", args) else (False if re.search(r"-ц", args) else digits)
        special = (
            True if re.search(r"\+с", args) else (False if re.search(r"-с", args) else special)
        )

        try:
            pwd = genpass.gen_pass(length, letters, digits, special)
            await event.edit(phrase.password.done.format(pwd))
        except Exception as ex:
            await event.edit(phrase.error.format(ex))

    async def run_shell(self, event: Message):
        cmd = event.pattern_match.group(1).strip()
        if not cmd:
            return await event.edit(phrase.shell.no_command)

        msg = await event.edit(phrase.shell.started.format(cmd))
        full_output = ""

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                shell=True,
            )

            while proc.stdout and not proc.stdout.at_eof():
                try:
                    chunk = await asyncio.wait_for(proc.stdout.read(1024), timeout=1.0)
                    if not chunk:
                        break
                    decoded = chunk.decode("utf-8", errors="replace")
                    full_output += decoded

                    display = full_output[-3000:]
                    with contextlib.suppress(Exception):
                        await msg.edit(phrase.shell.live.format(cmd, display))

                except TimeoutError:
                    continue

            await proc.wait()

            final = (full_output or "[no output]").strip()
            if len(final) > 4000:
                final = final[-4000:] + "\n... (обрезано)"
            await msg.edit(phrase.shell.finished.format(cmd, final))

        except Exception as e:
            await msg.edit(phrase.shell.error.format(e))

    async def run(self):
        try:
            await self.init()
            await self.client.run_until_disconnected()
        except Exception:
            logger.exception(f"Критическая ошибка в {self.number}")


async def main():
    pathes.clients.mkdir(exist_ok=True)
    client_files = [f for f in pathes.clients.iterdir() if f.suffix == ".json"]

    if not client_files:
        logger.warning("Нет ни одного клиента! Создаём нового..")
        number = input("Введи номер: ")
        api_id = int(input("Введи api_id: "))
        api_hash = input("Введи api_hash: ")
        config_path = pathes.clients / f"{number}.json"
        async with aiofiles.open(config_path, "wb") as f:
            await f.write(
                orjson.dumps(
                    {"api_id": api_id, "api_hash": api_hash},
                    option=orjson.OPT_INDENT_2,
                )
            )
        return await main()

    logger.info(f"Клиенты: {[f.name for f in client_files]}")
    tasks = []
    for cf in client_files:
        result = await config.load_client(pathes.clients, cf.name)
        if result:
            phone, api_id, api_hash = result
            tasks.append(UserbotManager(phone, api_id, api_hash).run())

    if not tasks:
        return logger.error("Нет ни одного валидного клиента.")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    from modules import (
        ai,
        apis,
        autochat,
        config,
        d,
        db,
        flip_map,
        flood,
        format,
        genpass,
        get_sys,
        ipman,
        iterators,
        notes,
        pathes,
        phrase,
        settings,
        task_gen,
        tz,
    )

    try:
        try:
            import uvloop

            uvloop.run(main())
        except ModuleNotFoundError:
            logger.warning("Uvloop не найден! Установите его: pip install uvloop")
            asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("Закрываю бота...")
