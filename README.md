# VirtualPad Server

A virtual pad server. It allows a console to host up to 8 virtual gamepads and expose them via wi-fi.

## Installation

First, ensure the /dev/uinput device is owned by root:input, and that input users can read and write:

    sudo chown root:input /dev/uinput
    sudo chmod g+rwx /dev/uinput

Alternatively, create a system boot file (e.g. /etc/udev/rules.d/99-uinput.rules) with the following lines:

    KERNEL=="uinput", MODE="0660", GROUP="input", OPTIONS+="static_node=uinput"

(the advantage with this is that no explicit code is needed in a custom script everytime)

Then, ensure you run this server in the context of a user belonging to the input group:

    sudo usermod -aG input {username}

Also, ensure the proper packages are installed. Either use virtualenv or `sudo apt install python-pip`:

    pip install -r requirements.txt

Then, run the server:

    python virtualpad-server &

Or perhaps running it as a service (owned by {username}).
