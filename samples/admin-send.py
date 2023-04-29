import logging
import argparse


logging.basicConfig()
LOGGER = logging.getLogger("admin-send")


def main():
    parser = argparse.ArgumentParser(description="VirtualPad sample admin tool")
    subparsers = parser.add_subparsers(dest="command")

    # Server commands
    server_parser = subparsers.add_parser("server", help="Server-related commands")
    server_subparsers = server_parser.add_subparsers(dest="server_command")

    server_subparsers.add_parser("start", help="Start the server")
    server_subparsers.add_parser("stop", help="Stop the server")
    server_subparsers.add_parser("check", help="Check the server status")

    # Pad commands
    pad_parser = subparsers.add_parser("pad", help="Gamepad-related commands")
    pad_subparsers = pad_parser.add_subparsers(dest="pad_command")

    clear_parser = pad_subparsers.add_parser("clear", help="Clear a specific gamepad")
    clear_parser.add_argument("number", type=int, choices=range(8), help="Gamepad number (0-7)")
    pad_subparsers.add_parser("clear-all", help="Clear all gamepads")
    pad_subparsers.add_parser("status", help="Get gamepad status")

    args = parser.parse_args()

    command = args.command
    if command == "server":
        subcommand = args.server_command
        if subcommand == "start":
            pass
        elif subcommand == "stop":
            pass
        elif subcommand == "check":
            pass
        else:
            LOGGER.error("Invalid server sub-command. Use arguments: `server -h` to get proper help")
    elif command == "pad":
        subcommand = args.pad_command
        if subcommand == "clear":
            number = args.number
        elif subcommand == "clear-all":
            pass
        elif subcommand == "status":
            pass
        else:
            LOGGER.error("Invalid pad sub-command. Use arguments: `pad -h` to get proper help")
    else:
        LOGGER.error("Invalid command. Use arguments: `-h`, `server -h`, and `pad -h` to get proper help")


if __name__ == "__main__":
    main()
