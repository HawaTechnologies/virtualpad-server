import json
import time
import logging
import threading
import socketserver
import traceback
from typing import Any, Type, Tuple
from .base_server import IndexedTCPServer, IndexedHandler, launch_server_in_thread
from .broadcast_server import BroadcastServer
from .pads import PadSlots, SLOTS_INDICES, PadNotInUse, PadIndexOutOfRange, PadInUse, AuthenticationFailed, PadMismatch

# Logger and settings.
LOGGER = logging.getLogger("hawa.virtualpad.pad-server")
LOGGER.setLevel(logging.INFO)
PAD_PORT = 2357

# Server notifications:
LOGIN_SUCCESS = bytes([0])
LOGIN_FAILURE = bytes([1])
PAD_INVALID = bytes([2])
PAD_BUSY = bytes([4])
TERMINATED = bytes([5])
COMMAND_LENGTH_MISMATCH = bytes([6])
PONG = bytes([7])
TIMEOUT = bytes([8])

# This variable checks whether the pad responded to the last ping command
# or not (this is checked per-pad).
_HEARTBEAT_INTERVAL = 5

# Buttons are: D-Pad (4), B-Pad (4), Shoulders (4), Start/Select (2) and axes (4).
N_BUTTONS = 18
CLOSE_CONNECTION = N_BUTTONS + 1
PING = N_BUTTONS + 2


def _pad_auth(remote: 'PadHandler'):
    """
    Reads (receives) and parses a pad auth message.
    :param remote: The remote to receive it from.
    :return: The received and parsed data.
    """

    # Getting the first data.
    read = remote.rfile.read(22)
    if len(read) < 22:
        raise RuntimeError("Login handshake incomplete or aborted")

    pad_index = read[0]
    attempted = bytes(read[1:5]).decode("utf-8")
    nickname = bytes(read[5:21]).decode("utf-8").rstrip('\b')
    LOGGER.info(f"For pad index {pad_index}, '{nickname}' attempts to join")
    try:
        remote.slots.occupy(pad_index, nickname, attempted, remote.index)
        remote.wfile.write(LOGIN_SUCCESS)
        return pad_index
    except PadIndexOutOfRange:
        remote.wfile.write(PAD_INVALID)
        raise
    except PadInUse:
        remote.wfile.write(PAD_BUSY)
        raise
    except AuthenticationFailed:
        remote.wfile.write(LOGIN_FAILURE)
        raise


class PadHandler(IndexedHandler):

    def __init__(self, request: Any, client_address: Any, server: socketserver.BaseServer):
        self._has_ping = False
        self._pad_index = None
        self._nickname = None
        if not isinstance(server, PadServer):
            raise ValueError("Only a MainServer (or subclasses) can use a PadHandler")
        self._slots = server.slots
        super().__init__(request, client_address, server)

    @property
    def slots(self):
        return self._slots

    def _send(self, obj):
        self.wfile.write(f"{json.dumps(obj)}\n".encode("utf-8"))

    def _broadcast(self, obj):
        self.server.broadcast(f"{json.dumps(obj)}\n".encode("utf-8"))

    def _heartbeat(self) -> None:
        """
        Heartbeat for the gamepad.
        """

        while self._pad_index in SLOTS_INDICES and self._slots[self._pad_index].connection_index == self.index:
            time.sleep(_HEARTBEAT_INTERVAL)
            if self._has_ping:
                self._has_ping = False
            else:
                if self._pad_index is not None:
                    self._broadcast({"type": "notification", "command": "pad:timeout", "index": self._pad_index})
                    try:
                        self.wfile.write(TIMEOUT)
                        self._slots.release(self._pad_index, True, self.index, True)
                    except PadNotInUse:
                        pass
                self._device = None
                break

    def _init_pad(self) -> None:
        """
        Attempts an authentication. On success, it establishes the _pad_index
        to a value other than None. On failure, it keeps _pad_index == None.
        The heartbeat is already launched on success.
        """

        LOGGER.info(f"Remote #{self.index} Logging in")
        try:
            self._pad_index = _pad_auth(self)
            threading.Thread(target=self._heartbeat).start()
            LOGGER.info(f"Remote #{self.index} successfully logged in")
        except Exception as e:
            LOGGER.info(f"Remote #{self.index} failed to log in: {type(e).__name__} -> {e}")

    def _process_events(self, buffer: bytes):
        """
        Sends all the events to the virtual controller.
        :param buffer: The main full/max buffer.
        """

        if self._pad_index is None:
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
        try:
            self._slots.emit(self._pad_index, fixed, self.index)
        except:
            traceback.print_exc()

    def setup(self) -> None:
        super().setup()
        LOGGER.info(f"Remote #{self.index} starting")
        self._init_pad()

    def handle(self) -> None:
        try:
            while self._pad_index is not None:
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
                        return
                    self._process_events(commands)
                elif length == CLOSE_CONNECTION:
                    self.slots.release(self._pad_index, False, self.index, True)
                    self._pad_index = None
                    return
                elif length == PING:
                    LOGGER.info(f"Remote #{self.index} ping")
                    self._has_ping = True
                    self.wfile.write(PONG)
                    pass
        except PadMismatch:
            pass
        except Exception as e:
            traceback.print_exc()
            raise
        finally:
            try:
                if self._pad_index is not None:
                    self.slots.release(self._pad_index, False, self.index, False)
            except PadNotInUse:
                pass
            self._pad_index = None

    def finish(self) -> None:
        super().finish()
        LOGGER.info(f"Remote #{self.index} finished")


class PadServer(IndexedTCPServer):
    """
    This server handles all the pads' commands.
    """

    def __init__(self, server_address: Tuple[str, int], RequestHandlerClass: Type[socketserver.BaseRequestHandler],
                 bind_and_activate: bool, broadcast_server: IndexedTCPServer, slots: PadSlots):
        self._slots = slots
        self._use_heartbeat_loop = False
        self._broadcast_server = broadcast_server
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)

    @property
    def slots(self):
        return self._slots

    def broadcast(self, message: bytes):
        self._broadcast_server.broadcast(message)

    def _heartbeat_loop(self):
        while self._use_heartbeat_loop:
            result = enumerate(self._slots.heartbeat())
            for pad_index, device_disposed in result:
                if device_disposed:
                    LOGGER.info(f"Pad #{pad_index}'s device disposed on no use")
            time.sleep(1)

    def server_activate(self) -> None:
        super().server_activate()
        self._use_heartbeat_loop = True
        threading.Thread(target=self._heartbeat_loop).start()
        LOGGER.info("Server started")

    def server_close(self) -> None:
        super().server_close()
        self._use_heartbeat_loop = False
        LOGGER.info("Server stopped")


def launch_pad_server(broadcast_server: BroadcastServer, slots: PadSlots) -> socketserver.TCPServer:
    return launch_server_in_thread(PadServer, ("0.0.0.0", PAD_PORT), PadHandler, broadcast_server, slots)
