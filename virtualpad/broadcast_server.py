import logging
import queue
import socketserver
import threading
from typing import Any, Tuple, Dict, Type, NamedTuple
from .base_server import IndexedHandler, IndexedTCPServer, launch_server_in_thread


LOGGER = logging.getLogger("hawa.virtualpad.broadcast-server")
LOGGER.setLevel(logging.INFO)
BROADCAST_PORT = 2358
_FINISH = object()


class BroadcastServerState(NamedTuple):
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

    def __init__(self, request: Any, client_address: Any, server: socketserver.BaseServer):
        if not isinstance(server, BroadcastServer):
            raise ValueError("Only a BroadcastServer (or subclasses) can use a BroadcastHandler")
        super().__init__(request, client_address, server)
        self._queue = None

    def setup(self) -> None:
        super().setup()
        with _STATES[self.server].lock:
            self._queue = queue.Queue()
            _STATES[self.server].queues[self] = self._queue
        LOGGER.info(f"Remote #{self.index} starting")

    def handle(self) -> None:
        while True:
            message = self._queue.get()
            if message is _FINISH:
                return
            # Otherwise, the message will be a bytes instance.
            # Failure to send this message will mean it closed.
            try:
                self.wfile.write(message)
            except:
                # The connection closed or is broken.
                return

    def finish(self) -> None:
        LOGGER.info(f"Remote #{self.index} finished")
        with _STATES[self.server].lock:
            self._queue = None
            _STATES[self.server].queues.pop(self, None)


class BroadcastServer(IndexedTCPServer):
    """
    Broadcasts a message to the clients.
    """

    def __init__(
            self,
            server_address: Tuple[str, int],
            RequestHandlerClass: Type[socketserver.BaseRequestHandler],
            bind_and_activate: bool = True,
    ):
        self._state = None
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)

    def server_activate(self) -> None:
        super().server_activate()
        self._state = _STATES.setdefault(self, BroadcastServerState(lock=threading.Lock(), queues={}))
        LOGGER.info("Server started")

    def _send_all(self, what: any) -> None:
        if not self._state:
            LOGGER.error("This server was cleared. There's no way to send messages")
            return

        with self._state.lock:
            for s, q in self._state.queues.items():
                q.put(what)

    def broadcast(self, message: bytes) -> None:
        LOGGER.info(f"Broadcasting: {message}")
        self._send_all(message)

    def server_close(self) -> None:
        self._send_all(_FINISH)
        super().server_close()
        self._state = None
        _STATES.pop(self, None)
        LOGGER.info("Server stopped")


_STATES: Dict[BroadcastServer, BroadcastServerState] = {}


def launch_broadcast_server() -> socketserver.TCPServer:
    return launch_server_in_thread(BroadcastServer, ("0.0.0.0", BROADCAST_PORT), BroadcastHandler)
