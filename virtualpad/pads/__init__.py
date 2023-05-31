import datetime
from enum import IntEnum
from typing import List, Tuple
from .constants import SLOTS_HEARTBEAT_TIME, SLOTS_INDICES
from .exceptions import PadInUse, PadNotInUse, PadIndexOutOfRange, AuthenticationFailed, PadMismatch
from .devices import make, emit, emit_zero
from .settings import passwords_check


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
    def status(self) -> Status:
        """
        The slot status.
        """

        return self._status

    @property
    def nickname(self) -> str:
        """
        The nickname of the occupant. Only meaningful on OCCUPIED status.
        """

        return self._nickname

    @property
    def connection_index(self) -> int:
        """
        The connection index of the occupant. Only meaningful on OCCUPIED status.
        """

        return self._connection_index

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

    def release(self, force: bool = False, expect: int = -1,
                zero: bool = False):
        """
        Releases the pad.
        :param force: Whether to force-drop the device as well.
        :param expect: The connection id to expect. By default,
            no expect is done. If an expect is specified, then
            no cleanup is done if the current connection index
            does not match the expected one (this is a silent
            failure and only when force == False).
        :param zero: Whether to emit the zero keys or not.
        """

        if force:
            if self._status == self.Status.EMPTY:
                raise PadNotInUse(self._pad_index)

            self._status = self.Status.EMPTY
            self._nickname = ""
            self._connection_index = -1
            self._last_user_stamp = None
            if zero and self._device:
                emit_zero(self._device)
            self._device = None  # It will be destroyed.
        else:
            if self._status != self.Status.OCCUPIED:
                raise PadNotInUse(self._pad_index)

            if expect in [-1, self._connection_index]:
                self._status = self.Status.RECENTLY_USED
                self._nickname = ""
                self._connection_index = -1
                self._last_user_stamp = datetime.datetime.now()
                if zero:
                    # By this point, self._device will exist.
                    emit_zero(self._device)

    def emit(self, events: List[Tuple[int, int]]):
        """
        Emits events, if this slot is occupied.
        :param events: The events to emit, as a list of (key, state) pairs.
            The valid keys are defined in the `devices` file.
        """

        if self._status != self.Status.OCCUPIED:
            raise PadNotInUse(self._pad_index)

        emit(events)

    def heartbeat(self) -> bool:
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

    def serialize(self) -> Tuple[str, str]:
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

    def __getitem__(self, item) -> PadSlot:
        """
        Gets the underlying slots item(s).
        :param item: The item(s) to retrieve.
        :returns: The retrieved items.
        """

        return self._slots[item]

    def occupy(self, pad_index: int, nickname: str, password: str, connection_index: int):
        """
        :param pad_index: The index of the pad to occupy.
        :param nickname: The nickname to use.
        :param password: The password to attempt.
        :param connection_index: The index of the connection that attempts this.
        """

        try:
            pad = self._slots[pad_index]
        except IndexError:
            raise PadIndexOutOfRange(pad_index)

        if not passwords_check(pad_index, password):
            raise AuthenticationFailed()

        pad.occupy(nickname, connection_index)

    def release(self, pad_index: int, force: bool = False, expect: int = -1,
                zero: bool = False):
        """
        Releases a pad by its index.
        :param pad_index: The index of the pad to release.
        :param force: Whether to force-drop the device as well.
        :param expect: The connection id to expect. By default,
            no expect is done. If an expect is specified, then
            no cleanup is done if the current connection index
            does not match the expected one (this is a silent
            failure and only when force == False).
        :param zero: Whether to emit the zero keys or not.
        """

        try:
            pad = self._slots[pad_index]
        except IndexError:
            raise PadIndexOutOfRange(pad_index)

        pad.release(force, expect, zero)

    def release_all(self):
        """
        Releases all the pads.
        """

        for index in SLOTS_INDICES:
            self.release(index, force=True, zero=True)

    def emit(self, pad_index: int, events: List[Tuple[int, int]], expect: int = -1):
        """
        Emits events, if the slot is occupied.
        :param pad_index: The index of the pad that will emit the events.
        :param events: The events to emit, as a list of (key, state) pairs.
            The valid keys are defined in the `devices` file.
        :param expect: The connection index to expect. A mismatch between
            this value (if != -1) and the current connection is an error.
        """

        try:
            pad = self._slots[pad_index]
        except IndexError:
            raise PadIndexOutOfRange(pad_index)

        if expect not in [-1, pad.connection_index]:
            raise PadMismatch(pad_index)

        pad.emit(events)

    def heartbeat(self) -> List[bool]:
        """
        Runs the heartbeat in all the pads.
        :return: The heartbeat results.
        """

        return [pad.heartbeat() for pad in self._slots]

    def serialize(self) -> List[Tuple[str, str]]:
        """
        Serializes all the pads' current states.
        :return: The list of serialized pads' states.
        """

        return [pad.serialize() for pad in self._slots]
