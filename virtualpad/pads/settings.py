import os
import json
import random


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
            "passwords": [_regenerate_password() for _ in range(8)]
        }
        save(settings)
        return settings


def save(settings):
    """
    Saves the current VirtualPad settings.
    :param settings: The settings to save.
    """

    os.makedirs(os.path.dirname(SETTINGS_PATH), 0o700, exist_ok=True)
    with open(SETTINGS_PATH, 'w') as f:
        return json.dump(settings, f)