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


def _remote_sender(remote: socket.socket, messages: queue.Queue, on_close: Callable[[], None]):
    """
    The loop, running in a thread, for a single socket to send messages.
    :param remote: The socket to use to send the messages.
    :param messages: The messages queue.
    :param on_close: What to do when this thread ends.
    """

    try:
        while True:
            remote.send(messages.get())
    except BrokenPipeError:
        # The socket closed.
        pass
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
                with entries_lock:
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
                next_index += 1
                Thread(target=_remote_sender, args=(remote, messages_queue, _closer)).start()
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
        print(f"Retrieving message: {message}")
        with entries_lock:
            for _, target_messages in entries.values():
                print(f"Sending message: {message}")
                target_messages.put(message)


def launch_broadcast_server():
    """
    Launches a broadcast server.
    :return: The pair (messages: a queue to send messages, close: a function to invoke to close it).
    """

    server = socket.create_server(("0.0.0.0", 2358), family=socket.AF_INET, backlog=8)
    lock = threading.Lock()
    entries = OrderedDict()
    Thread(target=_server_accepter, args=(server, entries, lock)).start()

    def close():
        nonlocal server
        LOGGER.info("Closing server")
        server.close()
        with lock:
            for key, entry in entries.values():
                LOGGER.info("Closing entry")
                entry.close()
        server = None

    def is_running():
        return server is not None

    messages = queue.Queue()
    Thread(target=_msg_broadcaster, args=(messages, entries, is_running, lock))

    return messages, close
