import datetime
from enum import IntEnum
from typing import List, Tuple
from .constants import SLOTS_HEARTBEAT_TIME, SLOTS_INDICES
from .exceptions import PadInUse, PadNotInUse
from .devices import make, emit


class PadSlot:
    """
    A Pad slot tells which pads are available (in total, a fixed number
    of pads will be available). Pads are created in a deferred fashion,
    to leave place for physical game pads to be created first, if it is
    the case.
    """

    class Status(IntEnum):
        """
        The status for a pad slot.
        """

        EMPTY = 0
        OCCUPIED = 1
        RECENTLY_USED = 2

    def __init__(self, pad_index: str):
        """
        :param pad_index: This index will be guaranteed to be valid.
        """

        self._pad_index = pad_index
        self._name = f"Hawa-VirtualPad-{pad_index}"
        self._status = self.Status.EMPTY
        self._device = None
        # Now, the user data (main for status == OCCUPIED).
        self._nickname = ""
        self._connection_index = -1
        # And then, the stamp of last usage (main for status == RECENTLY_USED).
        self._last_user_stamp = None

    @property
    def status(self):
        """
        The slot status.
        """

        return self._status

    @property
    def nickname(self):
        """
        The nickname of the occupant. Only meaningful on OCCUPIED status.
        """

        return self._nickname

    def occupy(self, nickname: str, connection_index: int):
        """
        Occupies the pad by a user in a given connection index.
        :param nickname: The user's nickname.
        :param connection_index: The user's connection index.
        """

        if self._status == self.Status.OCCUPIED:
            raise PadInUse(self._pad_index)

        self._status = self.Status.OCCUPIED
        self._nickname = nickname
        self._connection_index = connection_index
        if self._device is None:
            self._device = make(self._name)

    def release(self, force: bool = False):
        """
        Releases the pad.
        :param force: Whether to force-drop the device as well.
        """

        if force:
            if self._status == self.Status.EMPTY:
                raise PadNotInUse(self._pad_index)

            self._status = self.Status.EMPTY
            self._nickname = ""
            self._connection_index = -1
            self._last_user_stamp = None
            self._device = None  # It will be destroyed.
        else:
            if self._status != self.Status.OCCUPIED:
                raise PadNotInUse(self._pad_index)

            self._status = self.Status.RECENTLY_USED
            self._nickname = ""
            self._connection_index = -1
            self._last_user_stamp = datetime.datetime.now()

    def heartbeat(self):
        """
        Completely releases the pad, if it is recently used and
        the heartbeat time has elapsed.
        :returns: Whether the heartbeat was elapsed.
        """

        if self._status == self.Status.RECENTLY_USED and \
                (datetime.datetime.now() - self._status).total_seconds() > SLOTS_HEARTBEAT_TIME:
            self._status = self.Status.EMPTY
            self._last_user_stamp = None
            self._device = None  # It will be destroyed.
            return True
        return False

    def emit(self, events: List[Tuple[int, int]]):
        """
        Emits events, if this slot is occupied.
        :param events: The events to emit, as a list of (key, state) pairs.
            The valid keys are defined in the `devices` file.
        """

        if self._status != self.Status.OCCUPIED:
            raise PadNotInUse(self._pad_index)

        emit(events)

    def serialize(self):
        """
        Returns the current state of this pad, as (status, nick).
        """

        if self._status == self.Status.OCCUPIED:
            return "occupied", self._nickname
        elif self._status == self.Status.RECENTLY_USED:
            return "recently-used", ""
        else:
            return "empty", ""


class PadSlots:
    """
    A collection of instances, and means to manage them all indirectly.
    """

    def __init__(self):
        self._slots = [PadSlot(index) for index in SLOTS_INDICES]

    def serialize(self):
        """
        Serializes all the pads' current states.
        :return: The list of serialized pads' states.
        """

        return [pad.serialize() for pad in self._slots]
