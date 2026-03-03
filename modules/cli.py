import asyncio
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.output import create_output


_PROMPT = ">>> "
_HELP = """\
clients       — list active clients
ping          — check CLI is alive
addclient     — add a new client without restart
stop <phone>  — stop client by phone number
stopall       — stop all clients
exit / quit   — shutdown
help / ?      — this help"""

_pt_output = create_output()
_session: PromptSession | None = None
_loop: asyncio.AbstractEventLoop | None = None


def _write_safe(message: str) -> None:
    """Thread-safe запись через prompt_toolkit output."""
    if _session is None or _loop is None:
        sys.stderr.write(message)
        sys.stderr.flush()
        return

    def _do_write() -> None:
        _session.app.output.write_raw(message)
        _session.app.output.flush()

    _loop.call_soon_threadsafe(_do_write)


def loguru_sink(message: str) -> None:
    """Передаётся напрямую в logger.add() вместо stderr.
    InterceptHandler оставить без изменений — stdlib logging уже
    идёт через loguru, и значит тоже попадёт сюда автоматически."""
    _write_safe(message)


class CLI:
    def __init__(
        self,
        managers: dict,
        manager_tasks: dict,
        launch_manager_func,
        save_config_func,
    ) -> None:
        self._managers = managers
        self._tasks = manager_tasks
        self._launch = launch_manager_func
        self._save_config = save_config_func

    def _print(self, text: str) -> None:
        _write_safe(text + "\n")

    async def _ask(self, prompt: str) -> str:
        assert _session is not None
        return await _session.prompt_async(prompt)

    async def _cmd_clients(self) -> None:
        if not self._managers:
            self._print("No active clients.")
            return
        self._print("Active clients:\n" + "\n".join(f"  {p}" for p in self._managers))

    async def _cmd_ping(self) -> None:
        self._print("pong")

    async def _cmd_addclient(self) -> None:
        phone = (await self._ask("Phone: ")).strip()
        api_id_raw = (await self._ask("API ID: ")).strip()
        api_hash = (await self._ask("API Hash: ")).strip()

        try:
            api_id = int(api_id_raw)
        except ValueError:
            self._print("Invalid API ID.")
            return

        if phone in self._managers:
            self._print(f"Client {phone} is already running.")
            return

        await self._save_config(phone, api_id, api_hash)
        launched = await self._launch(phone, api_id, api_hash)
        self._print(f"Client {phone} started." if launched else f"Failed to start {phone}.")

    async def _cmd_stop(self, phone: str) -> None:
        if not phone:
            self._print("Usage: stop <phone>")
            return
        manager = self._managers.get(phone)
        if not manager:
            self._print(f"No such client: {phone}")
            return
        await manager.stop()
        self._managers.pop(phone, None)
        task = self._tasks.pop(phone, None)
        if task and not task.done():
            task.cancel()
        self._print(f"Client {phone} stopped.")

    async def _cmd_stopall(self) -> None:
        phones = list(self._managers.keys())
        if not phones:
            self._print("No active clients.")
            return
        for phone in phones:
            manager = self._managers.pop(phone, None)
            if manager:
                await manager.stop()
            task = self._tasks.pop(phone, None)
            if task and not task.done():
                task.cancel()
        self._print(f"Stopped {len(phones)} client(s).")

    async def _dispatch(self, line: str) -> bool:
        parts = line.strip().split(maxsplit=1)
        if not parts:
            return True
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        match cmd:
            case "clients":
                await self._cmd_clients()
            case "ping":
                await self._cmd_ping()
            case "addclient":
                await self._cmd_addclient()
            case "stop":
                await self._cmd_stop(arg)
            case "stopall":
                await self._cmd_stopall()
            case "exit" | "quit":
                await self._cmd_stopall()
                self._print("Bye.")
                return False
            case "help" | "?":
                self._print(_HELP)
            case _:
                self._print(f"Unknown command: {cmd!r}. Type 'help'.")
        return True

    async def run(self) -> None:
        global _session, _loop
        _loop = asyncio.get_running_loop()
        _session = PromptSession(output=_pt_output)
        while True:
            try:
                line = await _session.prompt_async(_PROMPT)
            except (EOFError, KeyboardInterrupt):
                break
            if not await self._dispatch(line):
                break