import logging
import queue
import time
import errno
import uinput
import socket
import threading
from typing import Callable
from .pads import PadMismatch, pad_send_all, pad_clear, pad_get, pad_set, pads_teardown, MAX_PAD_COUNT, POOL
from .admin import send_notification, using_admin_channel

# The logger goes here.
LOGGER = logging.getLogger("virtualpad.server")
LOGGER.setLevel(logging.INFO)

# Buffer size.
_BUFLEN = 32

# Client commands:
# - 0 to _BUFLEN - 1: A set of events.
# - CLOSE_CONNECTION = _BUFLEN: Release my pad (and close connection).
# - PONG = _BUFLEN + 1: A response to a ping command.
CLOSE_CONNECTION = _BUFLEN
PING = _BUFLEN + 1

# Server notifications:
LOGIN_SUCCESS = bytes([0])
LOGIN_FAILURE = bytes([1])
PAD_INVALID = bytes([2])
PAD_BUSY = bytes([3])
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
        if 0 <= key < 14:
            # Fix any change to {0 -> 0}|{1... -> 1}
            fixed.append((key, state and 1))
    # Send the data. If the current pad is different,
    # then this thread ends.
    pad_send_all(pad_index, fixed, device)


# This variable checks whether the pad responded to the last ping command
# or not (this is checked per-pad).
_HEARTBEATS = [True] * MAX_PAD_COUNT
_HEARTBEAT_INTERVAL = 5


def pad_heartbeat(remote: socket.socket, index: int, messages: queue.Queue, device: uinput.Device):
    """
    A heartbeat loop, per pad, to detect whether it is alive or not.
    :param device: The device to check against.
    :param messages: The admin writer.
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
                send_notification({"type": "notification", "command": "pad:timeout", "index": index}, messages)
                break
    except:
        pass


def _pad_auth(remote: socket.socket, buffer: bytearray):
    """
    Attempts an authentication.
    :returns: A tuple (False, None, None) or (True, index, nickname) if success.
    """

    # Getting the first data.
    read = remote.recv_into(buffer, 21)
    if read == 0:
        raise Exception("Login handshake aborted")
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


def _pad_init(remote: socket.socket, index: int, device_name: str, nickname: str, messages: queue.Queue):
    """
    Inits the gamepad.
    :param remote: The socket to work with.
    :param index: The pad index.
    :param device_name: The device name.
    :param nickname: The nickname to use.
    :param messages: The queue to send notifications to.
    :returns: The proper device to work with.
    """

    pad_set(index, device_name, nickname)
    send_notification({"type": "notification", "command": "pad:set", "nickname": nickname, "index": index},
                      messages)
    entry = pad_get(index)
    device, nickname, _ = entry
    threading.Thread(target=pad_heartbeat, args=(remote, index, messages, device)).start()
    return device


def _pad_read_command(remote: socket.socket, index: int, buffer: bytearray, device: uinput.Device):
    """
    Reads and processes an incoming command.
    :param remote: The socket to work with.
    :param index: The index.
    :param buffer: The buffer.
    :param device: The device to forward events to.
    """

    read = remote.recv_into(buffer, 1)
    if read == 0:
        # Force a close, even if no CLOSE_CONNECTION was received.
        raise PadMismatch(index)

    length = buffer[0]
    if length < _BUFLEN:
        length = length * 2
        received_length = remote.recv_into(buffer, length)
        _process_events(index, received_length, buffer, device)
    elif length == CLOSE_CONNECTION:
        pad_clear(index)
        return
    elif length == PING:
        _HEARTBEATS[index] = True
        pass
    # We're not managing other client commands so far.


def pad_loop(remote: socket.socket, connection_index: int, device_name: str, messages: queue.Queue):
    """
    This loop runs in a thread, reads all the button commands.
    It reads, from socket, buttons and axes changes and sends
    them via virtual pads.

    Note that this thread will die automatically when the pad
    is released (or all the pads are terminated).
    :param remote: The socket to read commands from.
    :param connection_index: The connection index.
    :param device_name: The internal device name of the pad.
    :param messages: The queue to write messages into.
    """

    buffer = bytearray(_BUFLEN)
    index = None
    device = None
    try:
        # Authenticating.
        LOGGER.info(f"Pad {connection_index} :: Attempting authentication")
        success, index, nickname = _pad_auth(remote, buffer)
        if not success:
            LOGGER.info("Authentication failed")
            return
        # Initializing the pad.
        LOGGER.info(f"Pad {connection_index} :: Initializing pad")
        device = _pad_init(remote, index, device_name, nickname, messages)
        # Finally, the loop to receive messages.
        while True:
            # Get the received contents.
            LOGGER.info(f"Pad {connection_index} :: Waiting for pad command")
            _pad_read_command(remote, index, buffer, device)
    except OSError as e:
        if e.errno != errno.EBADF:
            raise
        # Forgive this one. This is expected. Other exceptions
        # will bubble and be logged, but this is a standard
        # signal triggered by the user itself to de-auth or
        # by any explicit request (from client or from admin
        # panel) to disconnect.
        LOGGER.info(f"Pad {connection_index} :: Terminating gracefully")
        send_notification({"type": "notification", "command": "pad:release", "index": index}, messages)
    except PadMismatch as e:
        # Forgive this one. This is expected. Other exceptions
        # will bubble and be logged, but this is a standard
        # signal triggered by the user itself to de-auth or
        # by any explicit request (from client or from admin
        # panel) to disconnect.
        LOGGER.info(f"Pad {connection_index} :: Terminating gracefully")
        send_notification({"type": "notification", "command": "pad:release", "index": index}, messages)
        remote.send(TERMINATED)
    except Exception as e:
        # Something weird happened. Clear the pad just in case.
        LOGGER.info(f"Pad {connection_index} :: Terminating abruptly")
        LOGGER.exception(f"Pad #{index} :: Exception on socket thread!")
        send_notification({"type": "notification", "command": "pad:killed", "index": index}, messages)
        try:
            pad_clear(index, expect=device)
        except:
            pass
        try:
            remote.send(TERMINATED)
        except:
            pass
    finally:
        remote.close()


server_wait = threading.Event()
server_wait.set()


def is_server_running():
    """
    Tells whether the server is running.
    """

    return server_wait.is_set()


def server_loop(server: socket.socket, device_name: str, messages: queue.Queue,
                close_callback: Callable[[], None], timeout: int = 10):
    """
    Listens to ths socket perpetually, or until it is closed.
    Each connection is attempted, authenticated, and then its
    loop starts.
    :param close_callback: A callback for when this server gets
        closed.
    :param timeout: The timeout, in seconds, to wait.
    :param messages: Handler used to send notifications
        and responses to the admin.
    :param server: The main server socket.
    :param device_name: The base device name for the pads.
    """

    try:
        send_notification({"type": "notification", "command": "server:waiting"}, messages)
        server_wait.wait(0)
    except Exception:
        send_notification({"type": "notification", "command": "server:wait-error"}, messages)
        server.close()
        close_callback()
        raise

    try:
        send_notification({"type": "notification", "command": "server:launching"}, messages)
        server_wait.set()
        # Tears down the pads in the server.
        pads_teardown()
        index = 0
        while True:
            try:
                remote, address = server.accept()
                threading.Thread(target=pad_loop, args=(remote, index, device_name, messages)).start()
                index += 1
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
        send_notification({"type": "notification", "command": "server:closed"}, messages)


class VirtualPadService:
    """
    The whole VirtualPad service entry point.
    """

    def __init__(self, device_name: str = "VirtualPad", timeout: int = 10):
        self._vpad_server = None
        self._device_name = device_name
        self._timeout = timeout

    def _close_callback(self):
        self._vpad_server = None

    def _on_command(self, payload: dict, send_response: Callable[[dict], None],
                    messages: queue.Queue):
        """
        Processes a command.
        :param command: The command to process.
        :param send_response: A callback to send the command back.
        :param messages: The messages queue to use to broadcast.
        :param device_name: The base name  for the devices.
        :param timeout: The timeout to use for the socket.
        """

        command = payload.get("command")
        if command == "server:start":
            if not self._vpad_server:
                self._vpad_server = socket.create_server(("0.0.0.0", 2357), family=socket.AF_INET, backlog=8)
                threading.Thread(target=server_loop, args=(self._vpad_server, self._device_name, messages,
                                                           self._close_callback, self._timeout)).start()
            else:
                send_response({"type": "response", "code": "server:already-running"})
        elif command == "server:stop":
            if self._vpad_server:
                self._vpad_server.close()
                send_response({"type": "response", "code": "server:ok"})
            else:
                send_response({"type": "response", "code": "server:not-running"})
        elif command == "server:is-running":
            send_response({"type": "response", "code": "server:is-running",
                          "value": self._vpad_server is not None})
        elif command == "pad:clear":
            index = payload.get("index")
            if index in range(8):
                pad_clear(index)
                send_response({"type": "response", "code": "pad:ok", "index": index})
                send_notification({"type": "notification", "code": "pad:cleared", "index": index}, messages)
            else:
                send_response({"type": "response", "code": "pad:invalid-index", "index": index})
        elif command == "pad:clear-all":
            pads_teardown()
            send_response({"type": "response", "code": "pad:ok"})
            send_notification({"type": "notification", "code": "pad:all-cleared"}, messages)
        elif command == "pad:status":
            send_response({"type": "response", "code": "pad:status", "value": [
                entry[1:] for entry in POOL
            ]})

    def main(self):
        """
        A loop to read for admin commands and write responses.
        :param device_name: The base name  for the devices.
        :param timeout: The timeout to use for the socket.
        :param messages: The queue to send messages to.
        :param admin_reader: Handler to receive commands from the admin.
        """

        with using_admin_channel(self._on_command) as (messages, commands_thread):
            commands_thread.join()
