#!/usr/bin/python
from virtualpad.server import main
from virtualpad.admin import using_admin_channel


if __name__ == "__main__":
    with using_admin_channel() as (admin_writer, admin_reader):
        main(admin_writer, admin_reader, "Hawa-Virtualpad")

