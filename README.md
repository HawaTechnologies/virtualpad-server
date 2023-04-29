# VirtualPad Server

A virtual pad server. It allows a console to host up to 8 virtual gamepads and expose them via wi-fi.

## Installation

First, ensure the /dev/uinput device is owned by root:input, and that input users can read and write:

    sudo chown root:input /dev/uinput
    sudo chmod g+rwx /dev/uinput

Then, ensure you run this server in the context of a user belonging to the input group:

    sudo usermod -aG input {username}

Also, ensure the proper packages are installed. Either use virtualenv or `sudo apt install python-pip`:

    pip install -r requirements.txt

Then, run the server:

    python vpad-server.py &
