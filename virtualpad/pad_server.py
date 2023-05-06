import json
import socket
import time
import logging
import threading
import socketserver
from typing import Any, Type, Tuple
from virtualpad.base_server import IndexedTCPServer, IndexedHandler, launch_server_in_thread
from virtualpad.broadcast_server import BroadcastServer
from virtualpad.pads import MAX_PAD_COUNT, pad_get, pad_send_all, pad_set, pad_clear, PadMismatch, PAD_MODES


# Logger and settings.
LOGGER = logging.getLogger("hawa.virtualpad.pad-server")
LOGGER.setLevel(logging.INFO)
PAD_PORT = 2357

# Server notifications:
LOGIN_SUCCESS = bytes([0])
LOGIN_FAILURE = bytes([1])
PAD_INVALID = bytes([2])
PAD_MODE_INVALID = bytes([3])
PAD_BUSY = bytes([4])
TERMINATED = bytes([5])
COMMAND_LENGTH_MISMATCH = bytes([6])

# This variable checks whether the pad responded to the last ping command
# or not (this is checked per-pad).
_HEARTBEAT_INTERVAL = 5

# Buttons are: D-Pad (4), B-Pad (4), Shoulders (4), Start/Select (2) and axes (4).
N_BUTTONS = 18
CLOSE_CONNECTION = N_BUTTONS + 0
PING = N_BUTTONS + 1


def _pad_auth(remote: socketserver.StreamRequestHandler):
    """
    Attempts an authentication.
    :returns: A tuple (False, None, None) or (True, index, nickname) if success.
    """

    # Getting the first data.
    read = remote.rfile.read(22)
    if len(read) < 22:
        raise Exception("Login handshake incomplete or aborted")

    index = read[0]
    mode = read[1]
    attempted = bytes(read[2:6]).decode("utf-8")
    nickname = bytes(read[6:22]).decode("utf-8").rstrip('\b\n\t\r ')
    # Authenticating.
    if mode not in range(PAD_MODES):
        remote.wfile.write(PAD_MODE_INVALID)
        return False, None, None
    if index >= MAX_PAD_COUNT:
        remote.wfile.write(PAD_INVALID)
        return False, None, None
    entry = pad_get(index)
    if entry[0]:
        remote.wfile.write(PAD_BUSY)
        return False, None, None
    if attempted != entry[2]:
        remote.wfile.write(LOGIN_FAILURE)
        return False, None, None
    remote.wfile.write(LOGIN_SUCCESS)
    return True, index, nickname, mode


class PadHandler(IndexedHandler):

    def __init__(self, request: Any, client_address: Any, server: socketserver.BaseServer):
        self._has_ping = False
        self._pad_index = None
        self._nickname = None
        self._mode = None
        self._device = None
        super().__init__(request, client_address, server)
        if not isinstance(server, PadServer):
            raise ValueError("Only a MainServer (or subclasses) can use a PadHandler")

    def _send(self, obj):
        self.wfile.write(f"{json.dumps(obj)}\n".encode("utf-8"))

    def _broadcast(self, obj):
        self.server.broadcast(f"{json.dumps(obj)}\n".encode("utf-8"))

    def _auth(self) -> None:
        """
        Attempts an authentication.
        """

        LOGGER.info(f"Remote #{self.index} Logging in")
        success, index, nickname, _mode = _pad_auth(self)
        if not success:
            LOGGER.info(f"Remote #{self.index} failed to log in")
        else:
            LOGGER.info(f"Remote #{self.index} successfully logged in")
            self._pad_index = index
            self._nickname = nickname
            self._mode = _mode

    def _heartbeat(self) -> None:
        """
        Hearthbeat for the joypad.
        """

        while self._device and self._device == pad_get(self._pad_index)[0]:
            time.sleep(_HEARTBEAT_INTERVAL)
            if self._has_ping:
                self._has_ping = False
            else:
                self._broadcast({"type": "notification", "command": "pad:timeout", "index": self._pad_index})
                pad_clear(self._pad_index, self._device)
                self._device = None

    def _init_pad(self) -> None:
        """
        Inits the pad.
        """

        # Setting the device.
        pad_set(self._pad_index, self.server.device_name, self._nickname, self._mode)
        self._broadcast({"type": "notification", "command": "pad:set", "nickname": self._nickname,
                         "index": self._pad_index})
        entry = pad_get(self._pad_index)
        device, _, _ = entry
        self._device = device
        # Launching the heartbeat.
        threading.Thread(target=self._heartbeat).start()

    def _process_events(self, buffer: bytes):
        """
        Sends all the events to the virtual controller.
        :param buffer: The main full/max buffer.
        """

        if not self._device:
            return

        # Only changed buttons and axes will exist here.
        fixed = []
        for index in range(0, len(buffer), 2):
            key, state = buffer[index:index + 2]
            if 0 <= key < 14:
                # These are the buttons. State becomes boolean.
                # Fix any change to {0 -> 0}|{1... -> 1}
                fixed.append((key, state and 1))
            else:
                # 0-255 state is respected for axes.
                fixed.append((key, min(255, max(0, state))))
        # Send the data. If the current pad is different,
        # then this thread ends.
        pad_send_all(self._pad_index, fixed, self._device)

    def setup(self) -> None:
        super().setup()
        LOGGER.info(f"Remote #{self.index} starting")
        self._auth()
        if self._pad_index is not None:
            self._init_pad()
        else:
            self._device = None

    def handle(self) -> None:
        device = self._device
        try:
            while self._device:
                try:
                    buffer = self.rfile.read(1)
                except ConnectionResetError:
                    # In this case, the socket died.
                    return

                if not buffer:
                    return

                length = buffer[0]
                if length < N_BUTTONS:
                    commands = self.rfile.read(length * 2)
                    if len(commands) != length * 2:
                        self.wfile.write(COMMAND_LENGTH_MISMATCH)
                    self._process_events(commands)
                elif length == CLOSE_CONNECTION:
                    pad_clear(self._pad_index)
                    return
                elif length == PING:
                    self._has_ping = True
                    pass
        except PadMismatch:
            pass
        finally:
            if device:
                pad_clear(self._pad_index, device)
            self._device = None

    def finish(self) -> None:
        super().finish()
        LOGGER.info(f"Remote #{self.index} finished")


class PadServer(IndexedTCPServer):
    """
    This server handles all the pads' commands.
    """

    def __init__(self, server_address: Tuple[str, int], RequestHandlerClass: Type[socketserver.BaseRequestHandler],
                 bind_and_activate: bool, broadcast_server: IndexedTCPServer, device_name: str = "Hawa-VirtualPad"):
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)
        self._device_name = device_name
        self._broadcast_server = broadcast_server

    @property
    def device_name(self):
        return self._device_name

    def broadcast(self, message: bytes):
        self._broadcast_server.broadcast(message)

    def server_activate(self) -> None:
        super().server_activate()
        LOGGER.info("Server started")

    def server_close(self) -> None:
        super().server_close()
        LOGGER.info("Server stopped")


def launch_pad_server(broadcast_server: BroadcastServer) -> socketserver.TCPServer:
    return launch_server_in_thread(PadServer, ("0.0.0.0", PAD_PORT), PadHandler, broadcast_server)

