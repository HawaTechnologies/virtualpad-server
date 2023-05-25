import json
import os
import random
import traceback
from typing import List, Optional, Tuple
import uinput


MAX_PAD_COUNT = 8
PAD_MODES = 2
SETTINGS_PATH = "/etc/Hawa/virtualpad-server.conf"


def make_pad(name: str, mode: int = 0):
    """
    Builds a pad device.
    :param mode: The pad mode (either 0 or 1, being 1 the
      one typically compatible with the modern pads).
    :param name: The name to use.
    """

    axes = (
        uinput.ABS_X + (0, 255, 0, 15),
        uinput.ABS_Y + (0, 255, 0, 15),
        uinput.ABS_RX + (0, 255, 0, 15),
        uinput.ABS_RY + (0, 255, 0, 15),
    )

    events = [(
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
        uinput.BTN_DPAD_UP,
        uinput.BTN_DPAD_DOWN,
        uinput.BTN_DPAD_LEFT,
        uinput.BTN_DPAD_RIGHT
    ) + axes, tuple(
        (0x01, k) for k in range(0x120, 0x12a)
    ) + axes + ((0x04, 0x04),)]
    device = uinput.Device(
        events[mode], name=name
    )
    device.emit(uinput.ABS_X, 127, syn=False)
    device.emit(uinput.ABS_Y, 127, syn=False)
    device.emit(uinput.ABS_RX, 127, syn=False)
    device.emit(uinput.ABS_RY, 127, syn=True)
    return device


# Each pad entry will only account for the current device and the nickname.
# The password will be retrieved (and handled) from elsewhere.
POOL: List[Tuple[Optional[uinput.Device], Optional[str]]] = [(None, None)] * MAX_PAD_COUNT


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
BTN_UP = 10
BTN_DOWN = 11
BTN_LEFT = 12
BTN_RIGHT = 13
# Axes use 0 .. 255.
ABS_X = 14
ABS_Y = 15
ABS_RX = 16
ABS_RY = 17


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


def _load_settings():
    """
    Loads the current VirtualPad settings.
    :returns: The settings.
    """

    try:
        with open(SETTINGS_PATH, 'r') as f:
            return json.load(f)
    except OSError:
        settings = {
            "passwords": [_regenerate_password() for _ in range(8)]
        }
        _save_settings(settings)
        return settings


def _save_settings(settings):
    """
    Saves the current VirtualPad settings.
    :param settings: The settings to save.
    """

    os.makedirs(os.path.dirname(SETTINGS_PATH), 0o700, exist_ok=True)
    with open(SETTINGS_PATH, 'w') as f:
        return json.dump(settings, f)


def pad_check_password(index: int, password: str):
    """
    Checks whether the password matches for the pad.
    :param index: The pad index.
    :param password: The pad password.
    :return: Whether it matches or not.
    """

    _check_index(index)
    return password == _load_settings()["passwords"][index]


def pad_regenerate_passwords(*args):
    """
    Regenerates the passwords for the specified pads.
    :param args: The list of pads to regenerate the passwords from.
      If empty, all the pads' passwords will be regenerated.
    """

    if not args:
        args = tuple(range(8))
    settings = _load_settings()
    for index in args:
        _check_index(index)
        settings["passwords"][index] = _regenerate_password()
    _save_settings(settings)


def pad_get_passwords():
    """
    Gets all the passwords to be rendered on screen.
    :return: All the passwords.
    """

    return _load_settings()["passwords"]


def pad_get(index: int):
    """
    Gets a gamepad at an index.
    :param index: The index of the gamepad to get.
    :return: The (gamepad, nickname) pair, if any, or (None, None).
    """

    _check_index(index)
    return POOL[index]


def pad_set(index: int, device_name: str, nickname: str, mode: int):
    """
    Sets one of the pool elements to a new device.
    :param index: The device index to start.
    :param device_name: The device name (internal to the OS).
    :param nickname: The associated nickname.
    :param mode: The joypad mode.
    """

    _check_index(index)
    current = POOL[index][0]
    if current:
        raise PadInUse(index, current)
    POOL[index] = make_pad(f"{device_name}-{index} (mode={mode})", mode), nickname


def pad_clear(index: int, expect: Optional[uinput.Device] = None):
    """
    Clears one of the pool elements.
    :param expect: What device to expect, if any.
    :param index: The index to clear.
    """

    _check_index(index)
    current = POOL[index]
    if not current or not current[0]:
        raise PadNotInUse(index)
    if not expect or current[0] == expect:
        POOL[index] = (None, None)


def pads_teardown():
    """
    Clears all the pool elements.
    """

    for index, item in enumerate(POOL):
        if item[0]:
            item[0].destroy()
        POOL[index] = (None, None)


def _pad_send_all_mode0(device: uinput.Device, events: List[Tuple[int, int]]):
    """
    Sends events mapping in "mode 0": Each button (even d-pad buttons) will
    be sent as {1, 0}, and each axis will be sent as [0 .. 255].
    :param device: The device to send events to.
    :param events: The events.
    """

    mapped_events = [
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
        uinput.BTN_DPAD_UP,
        uinput.BTN_DPAD_DOWN,
        uinput.BTN_DPAD_LEFT,
        uinput.BTN_DPAD_RIGHT,
        uinput.ABS_X,
        uinput.ABS_Y,
        uinput.ABS_RX,
        uinput.ABS_RY
    ]

    for event, value in events:
        if event < 14:
            device.emit(mapped_events[event], 1 if value else 0, syn=False)
        else:
            device.emit(mapped_events[event], int(min(255, max(0, value))))
    device.syn()


def _pad_send_all_mode1(device: uinput.Device, events: List[Tuple[int, int]]):
    """
    Sends events mapping in "mode 1": Each non-d-pad button will be mapped
    to a value in [288 .. 298), each axis will be sent as [0 .. 255] and
    each d-pad button will change axes to 0, 127, or 255 respectively.
    :param device: The device to send events to.
    :param events: The events.
    """

    mapped_axes = [
        uinput.ABS_X,
        uinput.ABS_Y,
        uinput.ABS_RX,
        uinput.ABS_RY
    ]

    # Whether the ABS_X or ABS_Y axes (respectively) were
    # explicitly sent or not.
    abs_x_forced = False
    abs_y_forced = False
    # Changes to the axes (only apply while the _forced are
    # not set).
    abs_x_changes = None
    abs_y_changes = None

    for event, value in events:
        if event < 10:
            # Sending the button as-is, but also with a SCAN event.
            device.emit((0x04, 0x04), 0x90001 + event, syn=False)
            device.emit((0x01, 0x120 + event), 1 if value else 0, syn=False)
        elif event < 14:
            # Adding an axis change in the proper direction.
            if event == BTN_UP:
                abs_y_changes = (abs_y_changes or set()) | {[127, 0][value]}
            elif event == BTN_DOWN:
                abs_y_changes = (abs_y_changes or set()) | {[127, 255][value]}
            elif event == BTN_LEFT:
                abs_x_changes = (abs_x_changes or set()) | {[127, 255][value]}
            elif event == BTN_RIGHT:
                abs_x_changes = (abs_x_changes or set()) | {[127, 0][value]}
        else:
            # If ABS_X or ABS_Y is pressed, it will force whatever the D-Pad
            # expresses in its 2 (corresponding) directions.
            if event == ABS_X:
                abs_x_forced = True
            if event == ABS_Y:
                abs_y_forced = True
            device.emit(mapped_axes[event - 14], int(min(255, max(0, value))))
    # Check whether ABS_X was not forced and there are
    # D-Pad changes in the X axis. If there are, force
    # either the middle or the only specified direction
    # set in the axis.
    if not abs_x_forced and abs_x_changes is not None:
        abs_x_changes -= {127}
        device.emit(uinput.ABS_X, abs_x_changes.pop() if len(abs_x_changes) == 1 else 127, syn=False)
    # The same, but the axis Y.
    if not abs_y_forced and abs_y_changes is not None:
        abs_y_changes -= {127}
        device.emit(uinput.ABS_Y, abs_y_changes.pop() if len(abs_y_changes) == 1 else 127, syn=False)
    device.syn()


def _pad_send_all(device: uinput.Device, events: List[Tuple[int, int]], mode: int):
    """
    Sends all the events to the device, atomically.
    :param device: The device to send the events to.
    :param events: The events to send.
    :param mode: The joypad mode.
    """

    try:
        [_pad_send_all_mode0, _pad_send_all_mode1][mode](device, events)
    except Exception as e:
        traceback.print_exc()


def pad_send_all(index: int, events: List[Tuple[int, int]], mode: int, expect: Optional[uinput.Device] = None):
    """
    Sends all the events to the device, atomically.
    :param index: The index of the device to send the events to.
    :param events: The events to send.
    :param mode: The pad mode.
    :param expect: If not None, what device to expect.
    """

    print(f"Sending all events (*): {events}")
    if expect is not None and POOL[index][0] is not expect:
        raise PadMismatch(index)
    _pad_send_all(POOL[index][0], events, mode)


pads_teardown()
