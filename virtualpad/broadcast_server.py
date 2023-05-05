import logging
import queue
import socketserver
import threading
from threading import Lock
from typing import Any, Tuple, Dict, Type, NamedTuple
from .base_server import IndexedHandler, IndexedTCPServer, launch_server_in_thread


LOGGER = logging.getLogger("hawa.virtualpad.broadcast-server")
LOGGER.setLevel(logging.INFO)
BROADCAST_PORT = 2358
_FINISH = object()


class BroadcastServerSettings(NamedTuple):
    """
    Settings for a server.
    """

    lock: threading.Lock
    queues: Dict


class BroadcastHandler(IndexedHandler):
    """
    Each handler goes into an infinite loop, ready to forward
    any received message.
    """

    QUEUES = {}
    LOCK = Lock()

    def __init__(self, request: Any, client_address: Any, server: socketserver.BaseServer):
        super().__init__(request, client_address, server)
        self._queue = None

    def setup(self) -> None:
        super().setup()
        with self.LOCK:
            self._queue = queue.Queue()
            self.QUEUES[self] = self._queue
        LOGGER.info(f"Remote #{self.index} starting")

    def handle(self) -> None:
        while True:
            message = self._queue.get()
            if message is _FINISH:
                return
            # Otherwise, the message will be a bytes instance.
            self.wfile.write(message)

    def finish(self) -> None:
        LOGGER.info(f"Remote #{self.index} finished")
        with self.LOCK:
            self._queue = None
            self.QUEUES.pop(self, None)


class BroadcastServer(IndexedTCPServer):
    """
    It has a single queue and broadcasts their contents to
    all their connections.
    """

    def __init__(
            self,
            server_address: Tuple[str, int],
            RequestHandlerClass: Type[socketserver.BaseRequestHandler],
            bind_and_activate: bool = True,
    ):
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)
        self._queue = None
        self._settings = None

    def server_activate(self) -> None:
        self._queue = queue.Queue
        self._settings = _SETTINGS.setdefault(self, BroadcastServerSettings(lock=threading.Lock(),
                                                                            queues={}))

    def _send_all(self, what: any) -> None:
        with self._settings.lock:
            for s, q in self._settings.queues.items():
                q.put(what)

    def broadcast(self, message: bytes) -> None:
        self._send_all(message)

    def close_all(self) -> None:
        self._send_all(_FINISH)


_SETTINGS: Dict[BroadcastServer, BroadcastServerSettings]


def launch_broadcast_server() -> socketserver.TCPServer:
    return launch_server_in_thread(BroadcastServer, ("0.0.0.0", BROADCAST_PORT), BroadcastHandler)
