import os
import json
import random
from .constants import SLOTS_INDICES


SETTINGS_PATH = "/etc/Hawa/virtualpad-server.conf"


def _regenerate_password():
    return ''.join(random.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(4))


def load():
    """
    Loads the current VirtualPad settings.
    :returns: The settings.
    """

    try:
        with open(SETTINGS_PATH, 'r') as f:
            return json.load(f)
    except OSError:
        settings = {
            "passwords": [_regenerate_password() for _ in SLOTS_INDICES]
        }
        save(settings)
        return settings


def save(settings: dict):
    """
    Saves the current VirtualPad settings.
    :param settings: The settings to save.
    """

    os.makedirs(os.path.dirname(SETTINGS_PATH), 0o700, exist_ok=True)
    with open(SETTINGS_PATH, 'w') as f:
        return json.dump(settings, f)


def passwords_check(index: int, password: str):
    """
    Checks the index and the passwords.
    :param index: The index to check.
    :param password: The password to check.
    :return: Whether the index is valid and the password matches.
    """

    return index in SLOTS_INDICES and load()["passwords"][index] == password


def passwords_regenerate(*args):
    """
    Regenerates the passwords for the specified pads.
    :param args: The list of pads to regenerate the passwords from.
      If empty, all the pads' passwords will be regenerated.
    """

    if not args:
        args = tuple(range(8))
    settings = load()
    for index in args:
        if index not in SLOTS_INDICES:
            continue
        settings["passwords"][index] = _regenerate_password()
    save(settings)


def passwords_get():
    """
    Gets all the passwords to be rendered on screen.
    :return: All the passwords.
    """

    return load()["passwords"]
