import json
import errno
import socket
import threading
import uinput
from typing.io import IO
from .pads import PadMismatch, pad_send_all, pad_clear, pad_get, pad_set, pads_teardown
from .admin import using_admin_channel


_BUFLEN = 32
# Client commands:
# - 0 to _BUFLEN - 1: A set of events.
# - _BUFLEN: Release my pad (and close connection).
CLOSE_CONNECTION = _BUFLEN

# Server notifications:
PAD_INVALID = bytes([0])
PAD_BUSY = bytes([1])
LOGIN_SUCCESS = bytes([2])
LOGIN_FAILURE = bytes([3])
TERMINATED = bytes([2])


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


def pad_heartbeat(remote: socket.socket, index: int, device: uinput.Device):
    """
    A heartbeat loop, per pad, to detect whether it is alive or not.
    :param remote: The involved socket.
    :param index: The pad index.
    :param device: The device.
    """
    # TODO implement this!


def pad_admin(admin_writer: IO, admin_reader: IO):
    """
    A loop to read for admin commands and write responses.
    :param admin_writer: Handler to send responses to the admin.
    :param admin_reader: Handler to receive commands from the admin.
    """
    # TODO implement this.


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
    try:
        # Getting the first data.
        remote.recv_into(buffer, 21)
        index = buffer[0]
        attempted = bytes(buffer[1:5]).decode("utf-8")
        nickname = bytes(buffer[5:21]).decode("utf-8")
        # Authenticating.
        if index >= 8:
            remote.send(PAD_INVALID)
            return
        entry = pad_get(index)
        if entry[0]:
            remote.send(PAD_BUSY)
            return
        if attempted != entry[2]:
            remote.send(LOGIN_FAILURE)
            return
        remote.send(LOGIN_SUCCESS)
        # Initializing the pad.
        pad_set(index, device_name, nickname)
        json.dump({"command": "pad_set", "nickname": nickname, "index": index}, admin_writer)
        entry = pad_get(index)
        device, nickname, _ = entry
        threading.Thread(target=pad_heartbeat, args=(remote, index, device)).start()
        # Finally, the loop to receive messages.
        while True:
            # Get the received contents.
            remote.recv_into(buffer, 1)
            length = buffer[0]
            if length < _BUFLEN:
                received_length = remote.recv_into(buffer, length)
                _process_events(index, received_length, buffer, device)
            elif length == _BUFLEN:
                pad_clear(index)
                return
            # We're not managing other client commands so far.
    except PadMismatch as e:
        # Forgive this one. This is expected. Other exceptions
        # will bubble and be logged, but this is a standard
        # signal triggered by the user itself to de-auth or
        # by any explicit request (from client or from admin
        # panel) to disconnect.
        json.dump({"command": "pad_release", "index": e.args[1]}, admin_writer)
        remote.send(TERMINATED)
    except Exception as e:
        # The pad connection was killed.
        json.dump({"command": "pad_killed", "index": e.args[1]}, admin_writer)
    finally:
        remote.close()


server_wait = threading.Event()


def is_server_running():
    """
    Tells whether the server is running.
    """

    return server_wait.is_set()


def server_loop(server: socket.socket, device_name: str, admin_writer: IO):
    """
    Listens to ths socket perpetually, or until it is closed.
    Each connection is attempted, authenticated, and then its
    loop starts.
    :param admin_writer: Handler used to send notifications
        and responses to the admin.
    :param server: The main server socket.
    :param device_name: The base device name for the pads.
    """

    server_wait.wait()
    server_wait.set()
    try:
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
        # Tears down the pads in the server.
        pads_teardown()
        server_wait.clear()
