import asyncio
import sys
import threading


_PROMPT = ">>> "
_HELP = """\
clients       — list active clients
ping          — check CLI is alive
addclient     — add a new client without restart
stop <phone>  — stop client by phone number
stopall       — stop all clients
exit / quit   — shutdown
help / ?      — this help"""


class _SafeSink:
    """Loguru sink that erases the prompt before writing and redraws it after."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._prompt_active = False

    def set_prompt_active(self, value: bool) -> None:
        with self._lock:
            self._prompt_active = value

    def write(self, message: str) -> None:
        with self._lock:
            if self._prompt_active:
                sys.stderr.write(f"\r\033[K{message}")
                sys.stderr.write(_PROMPT)
            else:
                sys.stderr.write(message)
            sys.stderr.flush()


safe_sink = _SafeSink()


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
        self._running = False

    def _print(self, text: str) -> None:
        safe_sink.set_prompt_active(False)
        sys.stdout.write(f"\r\033[K{text}\n")
        sys.stdout.flush()

    def _show_prompt(self) -> None:
        safe_sink.set_prompt_active(True)
        sys.stdout.write(_PROMPT)
        sys.stdout.flush()

    async def _readline(self) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, sys.stdin.readline)

    async def _cmd_clients(self) -> None:
        if not self._managers:
            self._print("No active clients.")
            return
        lines = "\n".join(f"  {p}" for p in self._managers)
        self._print(f"Active clients:\n{lines}")

    async def _cmd_ping(self) -> None:
        self._print("pong")

    async def _cmd_addclient(self) -> None:
        safe_sink.set_prompt_active(False)

        sys.stdout.write("Phone: ")
        sys.stdout.flush()
        phone = (await self._readline()).strip()

        sys.stdout.write("API ID: ")
        sys.stdout.flush()
        api_id_raw = (await self._readline()).strip()

        sys.stdout.write("API Hash: ")
        sys.stdout.flush()
        api_hash = (await self._readline()).strip()

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
        self._running = True
        self._show_prompt()
        while self._running:
            try:
                line = await self._readline()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                break
            safe_sink.set_prompt_active(False)
            keep_running = await self._dispatch(line)
            if not keep_running:
                self._running = False
                break
            self._show_prompt()