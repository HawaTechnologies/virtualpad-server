# VirtualPad Server

A virtual pad server. It allows a console to host up to 8 virtual gamepads and expose them via wi-fi.

## Installation

Ensure you run this server always in the context of `root` user.

Ensure the proper packages are installed. Either use virtualenv or `sudo apt install python-pip`:

    pip install -r requirements.txt

Then, run the server always in the context of `root` user (or sudo):

    sudo ./virtualpad-server

Or perhaps running it as a service owned by root (e.g. create the /etc/systemd/system/hawa-virtualpad.service file):

    [Unit]
    Description=Hawa VirtualPad
    After=network.target

    [Service]
    User=root
    Group=root
    WorkingDirectory=/opt/Hawa/virtualpad
    ExecStart=/opt/Hawa/virtualpad/virtualpad-server
    Restart=always

    [Install]
    WantedBy=multi-user.target

Finally, ensure `virtualpad-admin` is owned by the group `hawamgmt`.

    sudo groupadd hawamgmt
    sudo ln -s /opt/Hawa/virtualpad/virtualpad-admin /usr/local/bin/virtualpad-admin
    sudo chmod ug+rx /opt/Hawa/virtualpad/virtualpad-admin
    sudo chgrp hawamgmt /opt/Hawa/virtualpad/virtualpad-admin

All the users that will be able to access the virtualpad-admin app must belong to that group:

    sudo usermod -aG hawamgmt {username}

This code assumes this codebase is installed into `/opt/Hawa/virtualpad`.