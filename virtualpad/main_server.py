import json
import logging
import os.path
import socketserver
from typing import Type, Union, Dict, Any
from virtualpad.base_server import IndexedUnixServer, IndexedHandler, launch_server
from virtualpad.broadcast_server import launch_broadcast_server
from virtualpad.pad_server import launch_pad_server
from virtualpad.pads import PadSlots
from virtualpad.pads.settings import passwords_get, passwords_regenerate


LOGGER = logging.getLogger("hawa.virtualpad.main-server")
LOGGER.setLevel(logging.INFO)
MAIN_BINDING = os.path.expanduser("/run/Hawa/admin.sock")
GROUP = "hawamgmt"


class MainServerState:

    def __init__(self):
        self.broadcast_server = None
        self.pad_server = None


class MainHandler(IndexedHandler):
    """
    Attends a management command.
    """

    def __init__(self, request: Any, client_address: Any, server: socketserver.BaseServer):
        if not isinstance(server, MainServer):
            raise ValueError("Only a MainServer (or subclasses) can use a MainHandler")
        super().__init__(request, client_address, server)

    def _send(self, obj):
        self.wfile.write(f"{json.dumps(obj)}\n".encode("utf-8"))

    def _broadcast(self, obj):
        self.server.broadcast(f"{json.dumps(obj)}\n".encode("utf-8"))

    def setup(self) -> None:
        super().setup()
        LOGGER.info(f"Admin #{self.index} starting")

    def finish(self) -> None:
        LOGGER.info(f"Admin #{self.index} finished")
        super().finish()

    def handle(self) -> None:
        state = _STATES[self.server]
        assert isinstance(self.server, MainServer)

        line = self.rfile.readline()
        if len(line) == 0:
            return

        try:
            payload = json.loads(line.decode("utf-8").strip())
            command = payload.get("command")

            if command == "server:start":
                if not state.pad_server:
                    state.pad_server = launch_pad_server(_STATES[self.server].broadcast_server)
                    self._send({"type": "response", "code": "server:ok", "status": self.server.slots.serialize()})
                else:
                    self._send({"type": "response", "code": "server:already-running"})
            elif command == "server:stop":
                if state.pad_server:
                    state.pad_server.shutdown()
                    state.pad_server = None
                    self._send({"type": "response", "code": "server:ok"})
                else:
                    self._send({"type": "response", "code": "server:not-running"})
            elif command == "server:is-running":
                self._send({"type": "response", "code": "server:is-running",
                            "value": state.pad_server is not None})
            elif command == "pad:clear":
                index = payload.get("index")
                force = payload.get("force")
                if index in range(8):
                    self.server.slots.release(index, force, zero=True)
                    self._send({"type": "response", "code": "pad:ok", "index": index})
                    self._broadcast({"type": "notification", "code": "pad:cleared", "index": index})
                else:
                    self._send({"type": "response", "code": "pad:invalid-index", "index": index})
            elif command == "pad:clear-all":
                self.server.slots.release_all()
                self._send({"type": "response", "code": "pad:ok"})
                self._broadcast({"type": "notification", "code": "pad:all-cleared"})
            elif command == "pad:status":
                self._send({"type": "response", "code": "pad:status", "value": {
                    "pads": self.server.slots.serialize(),
                    "passwords": passwords_get()
                }})
            elif command == "pad:reset-passwords":
                passwords_regenerate(*payload.get("indices", ()))
                self._send({"type": "response", "code": "ok", "value": {
                    "passwords": passwords_get()
                }})
            else:
                self._send({"type": "response", "code": "unknown-command", "value": command})
        except:
            LOGGER.exception("An error on command processing has occurred!")


class MainServer(IndexedUnixServer):
    """
    This is a main server and does the following:
    - Mounts, until its death, a broadcast server.
    - Mounts, on demand, a pad server.
    - Attends management commands.
    """

    def __init__(
            self,
            server_address: Union[str, bytes],
            RequestHandlerClass: Type[socketserver.BaseRequestHandler],
            bind_and_activate: bool = True
    ):
        try:
            os.unlink(server_address)
        except:
            pass
        self._slots = PadSlots()
        self._settings = None
        os.makedirs(os.path.dirname(server_address), 0o755, exist_ok=True)
        LOGGER.info(f"Binding main server to: {server_address}")
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)

    @property
    def slots(self):
        return self._slots

    def server_activate(self) -> None:
        super().server_activate()
        os.system(f"chgrp {GROUP} {MAIN_BINDING}")
        os.system(f"chmod g+rw {MAIN_BINDING}")
        os.system(f"chmod o-rwx {MAIN_BINDING}")
        self._settings = _STATES.setdefault(self, MainServerState())
        self._settings.broadcast_server = launch_broadcast_server()
        self._settings.pad_server = launch_pad_server(self._settings.broadcast_server)
        LOGGER.info("Server started")

    def server_close(self) -> None:
        super().server_close()
        if self._settings and self._settings.broadcast_server:
            self._settings.broadcast_server.shutdown()
        self._settings = None
        _STATES.pop(self, None)
        LOGGER.info("Server stopped")

    def broadcast(self, message: bytes):
        if not self._settings or not self._settings.broadcast_server:
            LOGGER.info("Cannot broadcast anything. The broadcast server is not running")
        self._settings.broadcast_server.broadcast(message)


_STATES: Dict[MainServer, MainServerState] = {}


def launch_main_server():
    return launch_server(MainServer, MAIN_BINDING, MainHandler)
