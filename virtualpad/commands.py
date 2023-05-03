import errno
import json
import os
import socket
import logging
import threading
from typing import Callable


# The logger goes here.
LOGGER = logging.getLogger("virtualpad.commands")
LOGGER.setLevel(logging.INFO)


def _remote_command_reader(remote: socket.socket, on_command: Callable[[dict, Callable[[dict], None]], None]):
    """
    Processes a single command from the remote socket, and closes it.
    """

    def _send(d):
        remote.send(f"{json.dumps(d)}\n".encode("utf-8"))

    try:
        command = json.loads(remote.recv(1024).decode("utf-8").strip())
        on_command(command, _send)
    finally:
        remote.close()


def _server_accepter(server: socket.socket, on_command: Callable[[dict, Callable[[dict], None]], None]):
    """
    An accepter loop that triggers a single command.
    :param server: The server socket to use.
    :param on_command: The handler for received commands.
    """

    while True:
        try:
            remote, _ = server.accept()
            threading.Thread(target=_remote_command_reader, args=(remote, on_command)).start()
        except OSError as e:
            # Accept errors of type EBADF mean that the server
            # is closed. Any other exception should be logged.
            if e.errno != errno.EBADF:
                raise
            else:
                break


def launch_commands_server(path: str, on_command: Callable[[dict, Callable[[dict], None]], None]):
    """
    Launches the commands server. This is only done through
    UNIX sockets and an admin command in user-space. It is
    not done from Godot, but an external Python script.
    :param path: The path to bind this socket to.
    :param on_command: The command handler.
    """

    # Start the new socket.
    if os.path.exists(path):
        os.remove(path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)

    # Finally, start listening.
    server.listen(8)
    thread = threading.Thread(target=_server_accepter, args=(server, on_command))
    thread.start()
    return thread, lambda: server.close()
