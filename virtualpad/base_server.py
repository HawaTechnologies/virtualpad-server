import socketserver
from typing import Any, Tuple, Type, Union


_INDICES_MAPPING = {}


def _next_index(cls, server):
    value = _INDICES_MAPPING.setdefault(cls, {}).setdefault(server, 0)
    _INDICES_MAPPING[cls][server] += 1
    return value


def _pop_server(cls, server):
    _INDICES_MAPPING.get(cls, {}).pop(server, None)


class IndexedHandler(socketserver.StreamRequestHandler):
    """
    Each connection will have its own index.
    """

    def __init__(self, request: Any, client_address: Any, server: socketserver.BaseServer):
        super().__init__(request, client_address, server)
        self._index = None

    @property
    def index(self):
        return self._index

    def setup(self) -> None:
        self._index = _next_index(self.__class__, self.server)


class IndexedTCPServer(socketserver.ThreadingTCPServer):
    """
    Indexes each of their connections.
    """

    def server_close(self) -> None:
        super().server_close()
        _pop_server(self.RequestHandlerClass, self)


class IndexedUnixServer(socketserver.ThreadingUnixStreamServer):
    """
    Indexes each of their connections.
    """

    def server_close(self) -> None:
        super().server_close()
        _pop_server(self.RequestHandlerClass, self)

