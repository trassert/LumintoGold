import asyncio
import sys

_HELP = """\
clients       — list active clients
ping          — check CLI is alive
addclient     — add a new client without restart
stop <phone>  — stop client by phone number
stopall       — stop all clients
exit / quit   — shutdown
help / ?      — this help"""

_PROMPT = ">>> "


class CLI:
    def __init__(
        self,
        managers: dict,
        manager_tasks: dict,
        launch_manager_func,
        save_config_func,
        phrase,
    ):
        self._managers = managers
        self._tasks = manager_tasks
        self._launch = launch_manager_func
        self._save_config = save_config_func
        self._phrase = phrase
        self._running = False
        self._print_lock = asyncio.Lock()

    async def _write(self, text: str) -> None:
        async with self._print_lock:
            sys.stdout.write(f"\r{text}\n{_PROMPT}")
            sys.stdout.flush()

    async def _prompt(self) -> None:
        async with self._print_lock:
            sys.stdout.write(_PROMPT)
            sys.stdout.flush()

    async def _readline(self) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, sys.stdin.readline)

    async def _cmd_clients(self) -> None:
        if not self._managers:
            await self._write("No active clients.")
            return
        lines = [f"  {phone}" for phone in self._managers]
        await self._write("Active clients:\n" + "\n".join(lines))

    async def _cmd_ping(self) -> None:
        await self._write("pong")

    async def _cmd_addclient(self) -> None:
        async with self._print_lock:
            sys.stdout.write("Phone: ")
            sys.stdout.flush()
        phone = (await self._readline()).strip()

        async with self._print_lock:
            sys.stdout.write("API ID: ")
            sys.stdout.flush()
        api_id_raw = (await self._readline()).strip()

        async with self._print_lock:
            sys.stdout.write("API Hash: ")
            sys.stdout.flush()
        api_hash = (await self._readline()).strip()

        try:
            api_id = int(api_id_raw)
        except ValueError:
            await self._write("Invalid API ID.")
            return

        if phone in self._managers:
            await self._write(f"Client {phone} is already running.")
            return

        await self._save_config(phone, api_id, api_hash)
        launched = await self._launch(phone, api_id, api_hash)
        if launched:
            await self._write(f"Client {phone} started.")
        else:
            await self._write(f"Failed to start client {phone}.")

    async def _cmd_stop(self, phone: str) -> None:
        if not phone:
            await self._write("Usage: stop <phone>")
            return
        manager = self._managers.get(phone)
        if not manager:
            await self._write(f"No such client: {phone}")
            return
        await manager.stop()
        self._managers.pop(phone, None)
        task = self._tasks.pop(phone, None)
        if task and not task.done():
            task.cancel()
        await self._write(f"Client {phone} stopped.")

    async def _cmd_stopall(self) -> None:
        phones = list(self._managers.keys())
        if not phones:
            await self._write("No active clients.")
            return
        for phone in phones:
            manager = self._managers.pop(phone, None)
            if manager:
                await manager.stop()
            task = self._tasks.pop(phone, None)
            if task and not task.done():
                task.cancel()
        await self._write(f"Stopped {len(phones)} client(s).")

    async def _cmd_help(self) -> None:
        await self._write(_HELP)

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
                await self._write("Bye.")
                return False
            case "help" | "?":
                await self._cmd_help()
            case _:
                await self._write(f"Unknown command: {cmd}. Type 'help' for a list.")
        return True

    async def run(self) -> None:
        self._running = True
        await self._prompt()
        while self._running:
            try:
                line = await self._readline()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                break
            keep_running = await self._dispatch(line)
            if not keep_running:
                self._running = False
                break
