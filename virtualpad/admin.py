import os
import queue
import json
import logging
import contextlib
from typing import Callable, Any
from .broadcast import launch_broadcast_server
from .commands import launch_commands_server


LOGGER = logging.getLogger("virtualpad.admin")
LOGGER.setLevel(logging.INFO)
START_USER = os.getenv('FOR_USER') or os.getenv('USER')
ADMIN_SOCKET = f"/home/{START_USER}/.config/Hawa/admin.sock"


def _create_channels(on_command: Callable[[dict, Callable[[dict], None], queue.Queue], None]):
    """
    Prepares the pipes.
    :returns: The queue of messages to write, the handler
        to close the notification server, the command server
        thread and the handler to read commands.
    """

    messages, broadcaster_close = launch_broadcast_server()

    def _on_command(command: dict, sender: Callable[[dict], None]):
        on_command(command, sender, messages)

    commands_thread, commands_close = launch_commands_server(ADMIN_SOCKET, _on_command)
    return messages, broadcaster_close, commands_thread, commands_close


@contextlib.contextmanager
def using_admin_channel(on_command: Callable[[dict, Callable[[dict], None]], None]):
    """
    A context manager to have the admin channel ready.
    :param on_command: The commands handler.
    """

    commands_close = None
    broadcaster_close = None

    try:
        messages, broadcaster_close, commands_thread, commands_close = _create_channels(on_command)

        # Uses them.
        yield messages, commands_thread
    finally:
        # Close the notification server.
        try:
            broadcaster_close()
        except:
            pass

        # Close from_admin. Forgive any exception.
        try:
            commands_close()
        except:
            pass


def send_notification(obj, messages: queue.Queue):
    """
    Send something to a fifo.
    :param messages: The queue to send the message to.
    :param obj: The message to send.
    """

    line = json.dumps(obj)
    LOGGER.info(f"Sending: {line.strip()}")
    messages.put(f"{line}\n")
