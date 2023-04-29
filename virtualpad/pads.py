from typing import List, Optional, Tuple

import uinput


def make_pad(name: str, deadzone: float = 0.1):
    """
    Builds a pad device.
    :param name: The name to use.
    :param deadzone: The axis' dead zone.
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
        uinput.ABS_X + (-1., 1., 0., max(0., min(1., deadzone))),
        uinput.ABS_Y + (-1., 1., 0., deadzone)
    )
    return uinput.Device(
        events, name=name
    )


POOL: List[Optional[Tuple[uinput.Device, str]]] = [None] * 8


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


def _check_index(index):
    if not (0 <= index < 8):
        raise PadIndexOutOfRange(index)


def pool_get_pad(index: int):
    """
    Gets a gamepad at an index.
    :param index: The index of the gamepad to get.
    :return: The (gamepad, nickname) pair, if any, or None.
    """

    _check_index(index)
    return POOL[index] or (None, None)


def pool_set(index: int, device_name: str, nickname: str, deadzone: float = 0.1):
    """
    Sets one of the pool elements to a new device.
    :param index: The device index to start.
    :param device_name: The device name (internal to the OS).
    :param nickname: The associated nickname.
    :param deadzone: The device's dead zone.
    """

    _check_index(index)
    current = POOL[index]
    if current:
        raise PadInUse(index, current)
    POOL[index] = make_pad(device_name, deadzone=deadzone), nickname


def pool_clear(index: int):
    """
    Clears one of the pool elements.
    :param index: The index to clear.
    """

    _check_index(index)
    current = POOL[index]
    if not current:
        raise PadNotInUse(index)
    POOL[index] = None


def pool_teardown():
    """
    Clears all the pool elements.
    """

    for index, item in enumerate(POOL):
        if item:
            item[0].destroy()
            POOL[index] = None
