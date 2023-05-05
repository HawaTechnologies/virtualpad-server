import socketserver
from typing import Any, Tuple, Type, Union


class IndexedHandler(socketserver.StreamRequestHandler):
    """
    Each connection will have its own index.
    """

    _INDICES_MAPPING = {}

    @classmethod
    def _next_index(cls, server):
        value = IndexedHandler._INDICES_MAPPING.setdefault(cls, {}).setdefault(server, 0)
        IndexedHandler._INDICES_MAPPING[cls][server] += 1
        return value

    @classmethod
    def _pop_server(cls, server):
        IndexedHandler._INDICES_MAPPING[cls].pop(server, None)

    def __init__(self, request: Any, client_address: Any, server: socketserver.BaseServer):
        super().__init__(request, client_address, server)
        self._index = None

    @property
    def index(self):
        return self._index

    def setup(self) -> None:
        self._index = self._next_index(self.server)


class IndexedTCPServer(socketserver.ThreadingTCPServer):
    """
    Indexes each of their connections.
    """

    def server_close(self) -> None:
        super().server_close()
        if isinstance(self.RequestHandlerClass, IndexedHandler):
            self.RequestHandlerClass._pop_server(self)


class IndexedUnixServer(socketserver.ThreadingUnixStreamServer):
    """
    Indexes each of their connections.
    """

    def server_close(self) -> None:
        super().server_close()
        if isinstance(self.RequestHandlerClass, IndexedHandler):
            self.RequestHandlerClass._pop_server(self)

