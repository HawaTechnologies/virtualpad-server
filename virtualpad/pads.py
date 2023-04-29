import random
from typing import List, Optional, Tuple
import uinput


MAX_PAD_COUNT = 8


def make_pad(name: str):
    """
    Builds a pad device.
    :param name: The name to use.
    """

    events = (
        uinput.BTN_NORTH,
        uinput.BTN_EAST,
        uinput.BTN_SOUTH,
        uinput.BTN_WEST,
        uinput.BTN_TL,   # L1
        uinput.BTN_TR,   # R1
        uinput.BTN_TL2,  # L2
        uinput.BTN_TR2,  # R2
        uinput.BTN_SELECT,
        uinput.BTN_START,
        uinput.ABS_X + (-1, 1, 0, 0),
        uinput.ABS_Y + (-1, 1, 0, 0)
    )
    return uinput.Device(
        events, name=name
    )


POOL: List[Tuple[Optional[uinput.Device], Optional[str], Optional[str]]] = [(None, None, '')] * MAX_PAD_COUNT


# Buttons use 0, 1.
BTN_NORTH = 0
BTN_EAST = 1
BTN_SOUTH = 2
BTN_WEST = 3
BTN_L1 = 4
BTN_R1 = 5
BTN_L2 = 6
BTN_R2 = 7
BTN_SELECT = 8
BTN_START = 9
# Axes use -1, 0, 1.
ABS_X = 10
ABS_Y = 11


_MAPPED_EVENTS: List[Tuple[int, int]] = [
    uinput.BTN_NORTH,
    uinput.BTN_EAST,
    uinput.BTN_SOUTH,
    uinput.BTN_WEST,
    uinput.BTN_TL,
    uinput.BTN_TR,
    uinput.BTN_TL2,
    uinput.BTN_TR2,
    uinput.BTN_SELECT,
    uinput.BTN_START,
    uinput.ABS_X,
    uinput.ABS_Y
]


class PadException(Exception):
    """
    Exceptions related to managing pads.
    """

    code = None

    def __init__(self, *args):
        super().__init__(self.code, *args)


class PadIndexOutOfRange(PadException):
    code = "index_out_of_range"


class PadInUse(PadException):
    code = "pad_in_use"


class PadNotInUse(PadException):
    code = "pad_not_in_use"


class PadMismatch(PadException):
    code = "pad_mismatch"


def _check_index(index):
    if not (0 <= index < MAX_PAD_COUNT):
        raise PadIndexOutOfRange(index)


def _regenerate_password():
    return ''.join(random.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(4))


def pad_get(index: int):
    """
    Gets a gamepad at an index.
    :param index: The index of the gamepad to get.
    :return: The (gamepad, nickname) pair, if any, or None.
    """

    _check_index(index)
    return POOL[index] or (None, None, None)


def pad_set(index: int, device_name: str, nickname: str):
    """
    Sets one of the pool elements to a new device.
    :param index: The device index to start.
    :param device_name: The device name (internal to the OS).
    :param nickname: The associated nickname.
    """

    _check_index(index)
    current = POOL[index]
    if current:
        raise PadInUse(index, current)
    POOL[index] = make_pad(f"{device_name}-{index}"), nickname, ''


def pad_clear(index: int, expect: Optional[uinput.Device] = None):
    """
    Clears one of the pool elements.
    :param expect: What device to expect, if any.
    :param index: The index to clear.
    """

    _check_index(index)
    current = POOL[index]
    if not current:
        raise PadNotInUse(index)
    if not expect or current[0] == expect:
        POOL[index] = (None, None, _regenerate_password())


def pads_teardown():
    """
    Clears all the pool elements.
    """

    for index, item in enumerate(POOL):
        if item:
            item[0].destroy()
            POOL[index] = (None, None, _regenerate_password())


def _pad_send_all(device: uinput.Device, events: List[Tuple[int, int]]):
    """
    Sends all the events to the device, atomically.
    :param device: The device to send the events to.
    :param events: The events to send.
    """

    # Pass all the commands as events using syn=True, then
    # after the last one just call .syn().
    for event, value in events:
        device.emit(_MAPPED_EVENTS[event], value, syn=True)
    device.syn()


def pad_send_all(index: int, events: List[Tuple[int, int]], expect: Optional[uinput.Device] = None):
    """
    Sends all the events to the device, atomically.
    :param index: The index of the device to send the events to.
    :param events: The events to send.
    :param expect: If not None, what device to expect.
    """

    if expect is not None and POOL[index][0] is not expect:
        raise PadMismatch(index)
    _pad_send_all(POOL[index][0], events)


# Initialize the pool.
for index in range(MAX_PAD_COUNT):
    pad_clear(index)
