from telethon import events

from ..main import UserbotManager
from . import d


def register(manager: UserbotManager, import_vkbottle: bool):
    if import_vkbottle:
        manager.client.on(d.cmd(r"\.тгвк$"))(manager.toggle_tg_to_vk)

    manager.client.on(d.cmd(r"\.\$(.+)"))(manager.run_shell)

    manager.client.on(d.cmd(r"\+нот (.+)\n([\s\S]+)"))(manager.add_note)
    manager.client.on(d.cmd(r"\-нот (.+)"))(manager.rm_note)
    manager.client.on(d.cmd(r"\!(.+)"))(manager.chk_note)
    manager.client.on(d.cmd(r"\.ноты$"))(manager.list_notes)

    manager.client.on(d.cmd(r"\.чистка"))(manager.clean_pm)
    manager.client.on(d.cmd(r"\.чсчистка"))(manager.clean_blacklist)
    manager.client.on(d.cmd(r"\.voice$"))(manager.voice2text)
    manager.client.on(d.cmd(r"\.баттмон$"))(manager.toggle_batt)
    manager.client.on(d.cmd(r"\.чатчистка$"))(manager.clean_chat)
    manager.client.on(d.cmd(r"\.слов"))(manager.words)
    manager.client.on(d.cmd(r"\.пинг$"))(manager.ping)
    manager.client.on(d.cmd(r"\.эмоид$"))(manager.get_emo_id)
    manager.client.on(d.cmd(r"\.флип"))(manager.flip_text)
    manager.client.on(d.cmd(r"\.гс$"))(manager.on_off_block_voice)
    manager.client.on(d.cmd(r"\.читать$"))(manager.on_off_mask_read)
    manager.client.on(d.cmd(r"\.серв$"))(manager.server_load)
    manager.client.on(d.cmd(r"\.релоадконфиг$"))(manager.config_reload)
    manager.client.on(d.cmd(r"\.автоферма$"))(manager.on_off_farming)
    manager.client.on(d.cmd(r"\.онлайн$"))(manager.toggle_online)
    manager.client.on(d.cmd(r"\.автобонус$"))(manager.on_off_bonus)

    manager.client.on(d.cmd(r"\.id (.+)"))(manager.get_id)

    manager.client.on(d.cmd(r"\.иичистка"))(manager.ai_clear)
    manager.client.on(d.cmd(r"\.иипрокси (.+)"))(manager.ai_proxy)
    manager.client.on(d.cmd(r"\.иитокен (.+)"))(manager.ai_token)
    manager.client.on(d.cmd(r"\.иимодель (.+)"))(manager.ai_model)

    manager.client.on(d.cmd(r"\.погода (.+)"))(manager.get_weather)
    manager.client.on(d.cmd(r"\.ip (.+)"))(manager.ipman)
    manager.client.on(d.cmd(r"\.аним (.+)"))(manager.anim)
    manager.client.on(d.cmd(r"\.ии ([\s\S]+)"))(manager.ai_resp)
    manager.client.on(d.cmd(r"\.т ([\s\S]+)"))(manager.typing)
    manager.client.on(d.cmd(r"\.set (.+)"))(manager.set_setting)
    manager.client.on(d.cmd(r"\.setint (.+)"))(manager.set_int_setting)
    manager.client.on(d.cmd(r"\.время (.+)"))(manager.time_by_city)
    manager.client.on(d.cmd(r"\.ад(?:\s|$)"))(manager.autodelmsg)

    manager.client.on(
        d.cmd(
            r"\.genpass(?:\s+(.+))?",
        )
    )(manager.gen_pass)
    manager.client.on(
        d.cmd(
            r"\.генпасс(?:\s+(.+))?",
        )
    )(manager.gen_pass)
    manager.client.on(
        d.cmd(
            r"\.пароль(?:\s+(.+))?",
        )
    )(manager.gen_pass)

    manager.client.on(events.NewMessage())(manager.flood_ctrl.monitor)
    manager.client.on(d.cmd(r"\-флудстики (\d+) (\d+)$"))(
        lambda e: manager.flood_ctrl.set_rule(e, "stickers")
    )
    manager.client.on(d.cmd(r"\-флудгиф (\d+) (\d+)$"))(
        lambda e: manager.flood_ctrl.set_rule(e, "gifs")
    )
    manager.client.on(d.cmd(r"\-флудобщ (\d+) (\d+)$"))(
        lambda e: manager.flood_ctrl.set_rule(e, "messages")
    )
    manager.client.on(d.cmd(r"\+флудстики$"))(
        lambda e: manager.flood_ctrl.unset_rule(e, "stickers")
    )
    manager.client.on(d.cmd(r"\+флудгиф$"))(lambda e: manager.flood_ctrl.unset_rule(e, "gifs"))
    manager.client.on(d.cmd(r"\+флудобщ$"))(lambda e: manager.flood_ctrl.unset_rule(e, "messages"))

    manager.client.on(d.cmd(r"\+авточат (-?\d+)"))(manager.autochat.add_chat)
    manager.client.on(d.cmd(r"\-авточат (-?\d+)"))(manager.autochat.remove_chat)
    manager.client.on(d.cmd(r"\.авточат$"))(manager.autochat.toggle)
    manager.client.on(d.cmd(r"\.авточаттайм (\d+)"))(manager.autochat.set_delay)

    manager.client.on(d.cmd(r"\.калк (.+)"))(manager.calc)
    manager.client.on(d.cmd(r"\.к (.+)"))(manager.calc)
    manager.client.on(d.cmd(r"\.calc (.+)"))(manager.calc)

    manager.client.on(events.NewMessage())(manager._dynamic_mask_reader)

    return
