import socket
import uinput
from .pads import PadMismatch, pad_send_all


_BUFLEN = 32


def pad_loop(remote: socket.socket, index: int, device: uinput.Device):
    """
    This loop runs in a thread, reads all the button commands.
    It reads, from socket, buttons and axes changes and sends
    them via virtual pads.
    :param index: The index of the pad.
    :param device: The value of the pad, on start.
    :param remote: The socket to read commands from.
    """

    buffer = bytearray(_BUFLEN)
    try:
        while True:
            # Get the received contents.
            remote.recv_into(buffer, 1)
            length = min(32, remote.recv_into(buffer, buffer[0]))
            if length % 2 == 1:
                length -= 1
            contents = buffer[:length]
            # Only changed buttons and axes will exist here.
            fixed = []
            for index in range(0, length, 2):
                key, state = contents[index:index + 2]
                if 10 <= key < 12:
                    # Fix any change to {0 -> 0}|{1 -> 1}|{2... -> -1}
                    fixed.append((key, -1 if state >= 2 else 1))
                elif 0 <= key < 10:
                    # Fix any change to {0 -> 0}|{1... -> 1}
                    fixed.append((key, state and 1))
            # Send the data. If the current pad is different,
            # then this thread ends.
            pad_send_all(index, fixed, device)
    except PadMismatch:
        # Forgive this one. This is expected. Other exceptions
        # will bubble and be logged.
        pass
