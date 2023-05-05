import socketserver
import threading
from typing import Any, Type


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


def launch_server_in_thread(server_type: Type[socketserver.TCPServer], binding: Any,
                            handler_type: Type[socketserver.BaseRequestHandler],
                            *args, **kwargs) -> socketserver.TCPServer:
    """
    Launches a server in a separate thread. Returns the server instance.
    :param server_type: The server type.
    :param binding: The server binding.
    :param handler_type: The handler type.
    :return: The server instance.
    """

    server = server_type(binding, handler_type, *args, **kwargs)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return server


def launch_server(server_type: Type[socketserver.TCPServer], binding: Any,
                  handler_type: Type[socketserver.BaseRequestHandler],
                  *args, **kwargs):
    """
    Launches a server in the same thread.
    :param server_type: The server type.
    :param binding: The server binding.
    :param handler_type: The handler type.
    :return: The server instance.
    """

    server_type(binding, handler_type, *args, **kwargs).serve_forever()
