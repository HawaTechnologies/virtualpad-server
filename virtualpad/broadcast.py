import errno
import logging
import queue
import socket
import threading
from threading import Thread, Lock
from typing import Callable
from collections import OrderedDict


# The logger goes here.
LOGGER = logging.getLogger("virtualpad.broadcast")
LOGGER.setLevel(logging.INFO)


def _remote_sender(remote: socket.socket, messages: queue.Queue, on_close: Callable[[], None], index: int):
    """
    The loop, running in a thread, for a single socket to send messages.
    :param remote: The socket to use to send the messages.
    :param messages: The messages queue.
    :param on_close: What to do when this thread ends.
    :param index: The remote index.
    """

    try:
        LOGGER.info(f"Client #{index} :: Starting remote sender loop")
        while True:
            LOGGER.info(f"Client #{index} :: Waiting for message")
            message = messages.get()
            LOGGER.info(f"Client #{index} :: Sending message")
            remote.send(message.encode('utf-8'))
    except BrokenPipeError:
        # The socket closed.
        LOGGER.info(f"Client #{index} :: Terminating gracefully")
    except:
        LOGGER.error(f"Client #{index} :: Terminating abruptly")
        LOGGER.exception(f"Client #{index} :: Exception on socket thread!")
    finally:
        on_close()


def _server_accepter(server: socket.socket, entries: OrderedDict, entries_lock: Lock):
    """
    The loop, running in a thread, for a server socket to spawn clients
    that receive notifications. These notifications should be understood
    as public ones (MANY applications, simultaneously, can be notified
    on this server's updates).
    :param server: The notification server.
    :param entries: The notification server's entries.
    :param entries_lock: A mutex over the entries.
    """

    try:
        next_index = 0
        with entries_lock:
            entries.clear()

        def _closer_callback(index):
            def _closer():
                LOGGER.info(f"Client #{index} :: Closed - Releasing")
                with entries_lock:
                    LOGGER.info(f"Client #{index} :: Closed - Cleaning remote entry")
                    entries.pop(index, None)
            return _closer

        while True:
            try:
                remote, _ = server.accept()
                messages_queue = queue.Queue()
                entry = (remote, messages_queue)
                with entries_lock:
                    entries[next_index] = entry
                _closer = _closer_callback(next_index)
                Thread(target=_remote_sender, args=(remote, messages_queue, _closer, next_index)).start()
                next_index += 1
            except OSError as e:
                # Accept errors of type EBADF mean that the server
                # is closed. Any other exception should be logged.
                if e.errno != errno.EBADF:
                    raise
                else:
                    break
    finally:
        with entries_lock:
            entries.clear()


def _msg_broadcaster(messages: queue.Queue, entries: OrderedDict, still_running: Callable[[], bool],
                     entries_lock: Lock):
    """
    The loop, running in a thread, to forward all the messages.
    :param messages: The messages to send.
    :param entries: The entries.
    """

    while still_running():
        message = messages.get()
        with entries_lock:
            for _, target_messages in entries.values():
                target_messages.put(message)


def launch_broadcast_server():
    """
    Launches a broadcast server.
    :return: The pair (messages: a queue to send messages, close: a function to invoke to close it).
    """

    # Start the new socket.
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(('0.0.0.0', 2358))

    # Finally, start listening.
    server.listen(8)
    lock = threading.Lock()
    entries = OrderedDict()
    Thread(target=_server_accepter, args=(server, entries, lock)).start()

    def close():
        nonlocal server
        LOGGER.info("Closing server")
        server.close()
        LOGGER.info("Server closed")
        with lock:
            for key, entry in entries.values():
                LOGGER.info("Closing entry")
                entry.close()
        server = None

    def is_running():
        return server is not None

    messages = queue.Queue()
    Thread(target=_msg_broadcaster, args=(messages, entries, is_running, lock)).start()

    return messages, close
