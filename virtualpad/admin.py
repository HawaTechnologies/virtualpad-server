import os
import json
import contextlib
from typing.io import IO


# These files are created for the target user.
START_USER = os.getenv('USER') or os.getenv('USERNAME')
_FIFO_SERVER_TO_ADMIN = f"/home/{START_USER}/.config/Hawa/run/server-to-admin"
_FIFO_ADMIN_TO_SERVER = f"/home/{START_USER}/.config/Hawa/run/admin-to-server"


def _clear_channel_fifo_files():
    """
    Destroys the pipes.
    """

    try:
        os.unlink(_FIFO_SERVER_TO_ADMIN)
    except:
        pass

    try:
        os.unlink(_FIFO_ADMIN_TO_SERVER)
    except:
        pass


def _create_channel_fifo_files():
    """
    Prepares the pipes.
    """

    os.mkfifo(_FIFO_SERVER_TO_ADMIN, 0x600)
    os.mkfifo(_FIFO_ADMIN_TO_SERVER, 0x600)
    os.system(f"chown {START_USER}:{START_USER} /home/pi/.config/Hawa/run/*")
    return open(_FIFO_SERVER_TO_ADMIN, 'w'), open(_FIFO_ADMIN_TO_SERVER, 'r')


@contextlib.contextmanager
def using_admin_channel():
    """
    A context manager to have the admin channel ready.
    """

    to_admin = None
    from_admin = None
    try:
        # Clears the channel fifo files (perhaps they lingered).
        _clear_channel_fifo_files()

        # Creates the channel fifo files (perhaps again).
        to_admin, from_admin = _create_channel_fifo_files()

        # Uses them.
        yield to_admin, from_admin
    finally:
        # Close to_admin. Forgive any exception.
        try:
            to_admin.close()
        except:
            pass

        # Close from_admin. Forgive any exception.
        try:
            from_admin.close()
        except:
            pass

        # Again: clears the channels after usage.
        _clear_channel_fifo_files()


def send_to_fifo(obj, fp: IO):
    """
    Send something to a fifo.
    :param obj: The object to send.
    :param fp: The fifo to send the object to.
    """

    fp.write(f"{json.dumps(obj)}\n")


def read_from_fifo(fp: IO):
    """
    Read something from a fifo.
    :param fp: The fifo to read the object from.
    :return: The read object.
    """

    return json.loads(fp.readline().strip())
