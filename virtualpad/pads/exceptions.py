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
