from telethon import events

# Wrapper for events.NewMessage

def cmd(pattern, *, incoming=False, outgoing=True, **kwargs) -> events.NewMessage:
    return events.NewMessage(
        pattern=pattern,
        incoming=incoming,
        outgoing=outgoing,
        **kwargs
    )