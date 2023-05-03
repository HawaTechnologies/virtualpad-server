import os
import queue
import stat
import json
import logging
import contextlib
from typing.io import IO
from .broadcast import launch_broadcast_server


# These files are created for the target user.
LOGGER = logging.getLogger("virtualpad.admin")
LOGGER.setLevel(logging.INFO)
START_USER = os.getenv('FOR_USER') or os.getenv('USER')
_FIFO_PATH = f"/home/{START_USER}/.config/Hawa/run"
_FIFO_ADMIN_TO_SERVER = f"{_FIFO_PATH}/admin-to-server"


def _clear_channel_fifo_files():
    """
    Destroys the pipes.
    """

    try:
        os.unlink(_FIFO_ADMIN_TO_SERVER)
    except:
        pass


def _create_if_not_fifo(file_path):
    """
    [re-]Creates a file if it is not a unix FIFO.
    :param file_path: The path.
    """

    if os.path.exists(file_path):
        file_stat = os.stat(file_path)
        if stat.S_ISFIFO(file_stat.st_mode):
            return
        else:
            os.unlink(file_path)
    os.mkfifo(file_path, 0o600)


def _create_channel_fifo_files():
    """
    Prepares the pipes.
    :returns: The queue of messages to write, the handler
        to close the notification server, and the handler
        to read commands.
    """

    os.makedirs(_FIFO_PATH, exist_ok=True)
    _create_if_not_fifo(_FIFO_ADMIN_TO_SERVER)
    os.system(f"chown {START_USER}:{START_USER} /home/{START_USER}/.config/Hawa/run/*")
    os.system(f"ls -la /home/{START_USER}/.config/Hawa/run/*")
    messages, close = launch_broadcast_server()
    LOGGER.info("Opening read channel (waiting until a sender is ready)")
    fr = open(_FIFO_ADMIN_TO_SERVER, 'r')
    return messages, close, fr


@contextlib.contextmanager
def using_admin_channel():
    """
    A context manager to have the admin channel ready.
    """

    from_admin = None
    close = None

    try:
        # Clears the channel fifo files (perhaps they lingered).
        _clear_channel_fifo_files()

        # Creates the channel fifo files (perhaps again).
        messages, close, from_admin = _create_channel_fifo_files()

        # Uses them.
        yield messages, from_admin
    finally:
        # Close the notification server.
        try:
            close()
        except:
            pass

        # Close from_admin. Forgive any exception.
        try:
            from_admin.close()
        except:
            pass


def send_to_fifo(obj, messages: queue.Queue):
    """
    Send something to a fifo.
    :param messages: The queue to send the message to.
    :param obj: The message to send.
    """

    line = json.dumps(obj)
    LOGGER.info(f"Sending: {line.strip()}")
    messages.put(f"{line}\n")


def read_from_fifo(fp: IO):
    """
    Read something from a fifo.
    :param fp: The fifo to read the object from.
    :return: The read object.
    """

    while True:
        line = fp.readline().strip()
        if line:
            break
    LOGGER.info(f"Received: {line}")
    return json.loads(line)
