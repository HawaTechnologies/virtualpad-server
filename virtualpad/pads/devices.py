from typing import List, Tuple
import uinput
import traceback


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
N_BUTTONS = 14
# Axes use 0 .. 255.
ABS_X = 14
ABS_Y = 15
ABS_RX = 16
ABS_RY = 17
N_AXES = 4


def make(name: str):
    """
    Builds a pad device.
    :param name: The name to use.
    """

    axes = (
        uinput.ABS_X + (0, 255, 0, 15),
        uinput.ABS_Y + (0, 255, 0, 15),
        uinput.ABS_RX + (0, 255, 0, 15),
        uinput.ABS_RY + (0, 255, 0, 15),
    )

    events = tuple(
        (0x01, k) for k in range(0x120, 0x12a)
    ) + axes + ((0x04, 0x04),)
    device = uinput.Device(
        # bustype=virtual
        # vendor=0x2357 (I deliberately picked this one)
        # product_id=0x1
        events, name=name, bustype=0x06, vendor=0x2357, product=0x1, version=1
    )
    device.emit(uinput.ABS_X, 127, syn=False)
    device.emit(uinput.ABS_Y, 127, syn=False)
    device.emit(uinput.ABS_RX, 127, syn=False)
    device.emit(uinput.ABS_RY, 127, syn=True)
    return device


def emit_zero(device: uinput.Device):
    """
    Emits a release of all the input keys. This is used when doing
    a pad release in the following conditions:
    - Kicking the user by admin.
    - Kicking the user by timeout.
    - User gracefully closing.
    :param device: The device to emit the release of all the keys.
    """

    emit(device, [(index, 0) for index in range(N_BUTTONS)] +
                 [(index, 127) for index in range(N_BUTTONS, N_BUTTONS + N_AXES)])


def emit(device: uinput.Device, events: List[Tuple[int, int]]):
    """
    Sends all the events to the device, atomically.
    :param device: The device to send the events to.
    :param events: The events to send.
    """

    try:
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
                _emit(device, (0x04, 0x04), 0x90001 + event)
                _emit(device, (0x01, 0x120 + event), 1 if value else 0)
            elif event < 14:
                # Adding an axis change in the proper direction.
                if event == BTN_UP:
                    abs_y_changes = (abs_y_changes or set()) | {[127, 0][value]}
                elif event == BTN_DOWN:
                    abs_y_changes = (abs_y_changes or set()) | {[127, 255][value]}
                elif event == BTN_LEFT:
                    abs_x_changes = (abs_x_changes or set()) | {[127, 0][value]}
                elif event == BTN_RIGHT:
                    abs_x_changes = (abs_x_changes or set()) | {[127, 255][value]}
            else:
                # If ABS_X or ABS_Y is pressed, it will force whatever the D-Pad
                # expresses in its 2 (corresponding) directions.
                if event == ABS_X:
                    abs_x_forced = True
                if event == ABS_Y:
                    abs_y_forced = True
                _emit(device, mapped_axes[event - 14], int(min(255, max(0, value))))
        # Check whether ABS_X was not forced and there are
        # D-Pad changes in the X axis. If there are, force
        # either the middle or the only specified direction
        # set in the axis.
        if not abs_x_forced and abs_x_changes is not None:
            abs_x_changes -= {127}
            _emit(device, uinput.ABS_X, abs_x_changes.pop() if len(abs_x_changes) == 1 else 127)
        # The same, but the axis Y.
        if not abs_y_forced and abs_y_changes is not None:
            abs_y_changes -= {127}
            _emit(device, uinput.ABS_Y, abs_y_changes.pop() if len(abs_y_changes) == 1 else 127)
        device.syn()
    except Exception as e:
        traceback.print_exc()


def _emit(device, key, value):
    device.emit(key, value, syn=False)
