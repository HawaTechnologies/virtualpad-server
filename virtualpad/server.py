import time
import errno
import uinput
import socket
import threading
from typing import Callable
from typing.io import IO
from .pads import PadMismatch, pad_send_all, pad_clear, pad_get, pad_set, pads_teardown, MAX_PAD_COUNT, POOL
from .admin import send_to_fifo, read_from_fifo

# Buffer size.
_BUFLEN = 32

# Client commands:
# - 0 to _BUFLEN - 1: A set of events.
# - CLOSE_CONNECTION = _BUFLEN: Release my pad (and close connection).
# - PONG = _BUFLEN + 1: A response to a ping command.
CLOSE_CONNECTION = _BUFLEN
PING = _BUFLEN + 1

# Server notifications:
PAD_INVALID = bytes([0])
PAD_BUSY = bytes([1])
LOGIN_SUCCESS = bytes([2])
LOGIN_FAILURE = bytes([3])
TERMINATED = bytes([4])


def _process_events(pad_index: int, length: int, buffer: bytearray, device: uinput.Device):
    """
    Sends all the events to the virtual controller.
    :param pad_index: The involved pad's index.
    :param length: The buffer length.
    :param buffer: The main full/max buffer.
    :param device: The internal uinput device.
    """

    if length % 2 == 1:
        length -= 1
    contents = buffer[:length]
    # Only changed buttons and axes will exist here.
    fixed = []
    for index in range(0, length, 2):
        key, state = contents[index:index + 2]
        if 10 <= key < 12:
            # Fix any change to {0 -> 0}|{1 -> 1}|{2... -> -1}
            fixed.append((key, -1 if state >= 2 else 1))
        elif 0 <= key < 10:
            # Fix any change to {0 -> 0}|{1... -> 1}
            fixed.append((key, state and 1))
    # Send the data. If the current pad is different,
    # then this thread ends.
    pad_send_all(pad_index, fixed, device)


# This variable checks whether the pad responded to the last ping command
# or not (this is checked per-pad).
_HEARTBEATS = [True] * MAX_PAD_COUNT
_HEARTBEAT_INTERVAL = 5


def pad_heartbeat(remote: socket.socket, index: int, admin_writer: IO, device: uinput.Device):
    """
    A heartbeat loop, per pad, to detect whether it is alive or not.
    :param device: The device to check against.
    :param admin_writer: The admin writer.
    :param remote: The involved socket.
    :param index: The pad index.
    """

    try:
        while device == pad_get(index)[0]:
            time.sleep(_HEARTBEAT_INTERVAL)
            if _HEARTBEATS[index]:
                _HEARTBEATS[index] = False
            else:
                remote.close()
                send_to_fifo({"type": "notification", "command": "pad:timeout", "index": index}, admin_writer)
                break
    except:
        pass


def _pad_auth(remote: socket.socket, buffer: bytearray):
    """
    Attempts an authentication.
    :returns: A tuple (False, None, None) or (True, index, nickname) if success.
    """

    # Getting the first data.
    remote.recv_into(buffer, 21)
    index = buffer[0]
    attempted = bytes(buffer[1:5]).decode("utf-8")
    nickname = bytes(buffer[5:21]).decode("utf-8")
    # Authenticating.
    if index >= MAX_PAD_COUNT:
        remote.send(PAD_INVALID)
        return False, None, None
    entry = pad_get(index)
    if entry[0]:
        remote.send(PAD_BUSY)
        return False, None, None
    if attempted != entry[2]:
        remote.send(LOGIN_FAILURE)
        return False, None, None
    remote.send(LOGIN_SUCCESS)
    return True, index, nickname


def _pad_init(remote: socket.socket, index: int, device_name: str, nickname: str, admin_writer: IO):
    """
    Inits the gamepad.
    :param remote: The socket to work with.
    :param index: The pad index.
    :param device_name: The device name.
    :param nickname: The nickname to use.
    :param admin_writer: The writer to send notifications to.
    :returns: The proper device to work with.
    """

    pad_set(index, device_name, nickname)
    send_to_fifo({"type": "notification", "command": "pad:set", "nickname": nickname, "index": index},
                 admin_writer)
    entry = pad_get(index)
    device, nickname, _ = entry
    threading.Thread(target=pad_heartbeat, args=(remote, index, admin_writer)).start()
    return device


def _pad_read_command(remote: socket.socket, index: int, buffer: bytearray, device: uinput.Device):
    """
    Reads and processes an incoming command.
    :param remote: The socket to work with.
    :param index: The index.
    :param buffer: The buffer.
    :param device: The device to forward events to.
    """

    remote.recv_into(buffer, 1)
    length = buffer[0]
    if length < _BUFLEN:
        received_length = remote.recv_into(buffer, length)
        _process_events(index, received_length, buffer, device)
    elif length == CLOSE_CONNECTION:
        pad_clear(index)
        return
    elif length == PING:
        _HEARTBEATS[index] = True
        pass
    # We're not managing other client commands so far.


def pad_loop(remote: socket.socket, device_name: str, admin_writer: IO):
    """
    This loop runs in a thread, reads all the button commands.
    It reads, from socket, buttons and axes changes and sends
    them via virtual pads.

    Note that this thread will die automatically when the pad
    is released (or all the pads are terminated).
    :param admin_writer: The admin interface to write messages into.
    :param device_name: The internal device name of the pad.
    :param remote: The socket to read commands from.
    """

    buffer = bytearray(_BUFLEN)
    index = None
    device = None
    try:
        # Giving some timeout for operations.
        remote.settimeout(3)
        # Authenticating.
        success, index, nickname = _pad_auth(remote, buffer)
        if not success:
            return
        # Initializing the pad.
        device = _pad_init(remote, index, device_name, nickname, admin_writer)
        # Finally, the loop to receive messages.
        while True:
            # Get the received contents.
            _pad_read_command(remote, index, buffer, device)
    except PadMismatch as e:
        # Forgive this one. This is expected. Other exceptions
        # will bubble and be logged, but this is a standard
        # signal triggered by the user itself to de-auth or
        # by any explicit request (from client or from admin
        # panel) to disconnect.
        send_to_fifo({"type": "notification", "command": "pad:release", "index": e.args[1]}, admin_writer)
        remote.send(TERMINATED)
    except Exception as e:
        # Something weird happened. Clear the pad just in case.
        try:
            pad_clear(index, expect=device)
        except:
            pass
        send_to_fifo({"type": "notification", "command": "pad:killed", "index": e.args[1]}, admin_writer)
    finally:
        remote.close()


server_wait = threading.Event()


def is_server_running():
    """
    Tells whether the server is running.
    """

    return server_wait.is_set()


def server_loop(server: socket.socket, device_name: str, admin_writer: IO,
                close_callback: Callable[[], None], timeout: int = 10):
    """
    Listens to ths socket perpetually, or until it is closed.
    Each connection is attempted, authenticated, and then its
    loop starts.
    :param close_callback: A callback for when this server gets
        closed.
    :param timeout: The timeout, in seconds, to wait.
    :param admin_writer: Handler used to send notifications
        and responses to the admin.
    :param server: The main server socket.
    :param device_name: The base device name for the pads.
    """

    try:
        send_to_fifo({"type": "notification", "command": "server:waiting"}, admin_writer)
        server_wait.wait(timeout)
    except Exception:
        send_to_fifo({"type": "notification", "command": "server:wait-error"}, admin_writer)
        server.close()
        close_callback()
        raise

    try:
        send_to_fifo({"type": "notification", "command": "server:launching"}, admin_writer)
        server_wait.set()
        # Tears down the pads in the server.
        pads_teardown()
        while True:
            try:
                remote, address = server.accept()
                threading.Thread(target=pad_loop, args=(remote, device_name, admin_writer)).start()
            except OSError as e:
                # Accept errors of type EBADF mean that the server
                # is closed. Any other exception should be logged.
                if e.errno != errno.EBADF:
                    raise
                else:
                    break
    finally:
        # Tears down the pads in the server, again.
        pads_teardown()
        server_wait.clear()
        # Close the server, if any.
        try:
            server.close()
        except:
            pass
        close_callback()
        send_to_fifo({"type": "notification", "command": "server:closed"}, admin_writer)


def main(admin_writer: IO, admin_reader: IO, device_name: str, timeout: int = 10):
    """
    A loop to read for admin commands and write responses.
    :param device_name: The base name  for the devices.
    :param timeout: The timeout to use for the socket.
    :param admin_writer: Handler to send responses to the admin.
    :param admin_reader: Handler to receive commands from the admin.
    """

    # Supported admin commands:
    # - Start server (command="server:start").
    # - Stop server (command="server:stop").
    # - Tell whether server is running (command="server:is-running").
    # - Clear or re-generate pad (command="pad:clear").
    # - Clear all pads (command="pad:clear-all").
    # - List all the pads (in use or not; command="pad:status").
    server = None

    def close_callback():
        nonlocal server
        server = None

    while True:
        payload = read_from_fifo(admin_reader)
        command = payload.get("command")
        if command == "server:start":
            if not server:
                server = socket.create_server(("0.0.0.0", 2357), family=socket.AF_INET, backlog=8)
                threading.Thread(target=server_loop, args=(server, device_name, admin_writer,
                                                           close_callback, timeout)).start()
            else:
                send_to_fifo({"type": "notification", "command": "server:already-running"}, admin_writer)
        elif command == "server:stop":
            if server:
                server.close()
            else:
                send_to_fifo({"type": "notification", "command": "server:not-running"}, admin_writer)
        elif command == "server:is-running":
            send_to_fifo({"type": "notification", "command": "server:is-running", "value": server is None},
                         admin_writer)
        elif command == "pad:clear":
            index = payload.get("index")
            if index in range(8):
                pad_clear(index)
                send_to_fifo({"type": "notification", "command": "pad:cleared", "index": index}, admin_writer)
            else:
                send_to_fifo({"type": "notification", "command": "pad:invalid-index", "index": index}, admin_writer)
        elif command == "pad:clear-all":
            pads_teardown()
            send_to_fifo({"type": "notification", "command": "pad:all-cleared"}, admin_writer)
        elif command == "pad:status":
            send_to_fifo({"type": "notification", "command": "pad:status", "value": [
                entry[1:] for entry in POOL
            ]}, admin_writer)
