import errno
import socket
import threading

import uinput
from .pads import PadMismatch, pad_send_all, pad_clear, pad_get, pad_set

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
    # TODO implement this!
    pass


def pad_loop(remote: socket.socket, device_name: str):
    """
    This loop runs in a thread, reads all the button commands.
    It reads, from socket, buttons and axes changes and sends
    them via virtual pads.

    Note that this thread will die automatically when the pad
    is released (or all the pads are terminated).
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
        # TODO notify admin interface about pad set.
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
    except PadMismatch:
        # Forgive this one. This is expected. Other exceptions
        # will bubble and be logged, but this is a standard
        # signal triggered by the user itself to de-auth or
        # by any explicit request (from client or from admin
        # panel) to disconnect.
        # TODO notify admin interface about pad close.
        remote.send(TERMINATED)
    except Exception as e:
        # TODO notify admin interface about abrupt pad close.
        # TODO this might also involve a connection abruptly
        # TODO closed by client timeout.
        pass
    finally:
        remote.close()


def server_loop(server: socket.socket, device_name: str):
    """
    Listens to ths socket perpetually, or until it is closed.
    Each connection is attempted, authenticated, and then its
    loop starts.
    :param server: The main server socket.
    :param device_name: The base device name for the pads.
    """

    while True:
        try:
            remote, address = server.accept()
            threading.Thread(target=pad_loop, args=(remote, device_name)).start()
        except OSError as e:
            # Accept errors of type EBADF mean that the server
            # is closed. Any other exception should be logged.
            if e.errno != errno.EBADF:
                raise
            else:
                break
