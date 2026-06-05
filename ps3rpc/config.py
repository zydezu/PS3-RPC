import json
import re
import sys
from pathlib import Path
from socket import AF_INET, SOCK_DGRAM, socket
from time import sleep

import networkscan
import requests
from bs4 import BeautifulSoup
from pypresence import DiscordNotFound, InvalidPipe
from pypresence.presence import Presence
from requests.exceptions import ConnectionError

default_config = {
    "ip": "",
    "client_id": 1512043386327007253,
    "wait_seconds": 30,
    "show_temp": False,
    "retro_covers": False,
    "hibernate_seconds": 600,
    "ip_prompt": True,
    "show_timer": True,
    "prefer_dev_app": False,
    "use_appname": False,
    "show_only_in_game": True,
    "temp_on_tooltip": True,
}

headers = {"User-Agent": "Mozilla/5.0"}
wmanVer = "1.47.45"

_PSX_RE = re.compile(r"/(dev_hdd0|dev_usb00[0-9])/PSXISO")
_PS2_RE = re.compile(r"/(dev_hdd0|dev_usb00[0-9])/PS2ISO")
_RETRO_LINK_RE = re.compile(r'">(.*)</a>')
_VERSION_RE = re.compile(r"(.+)\d{2}\.\d{2}")
_THERMAL_RE = re.compile(r"Â")
_GOOGLE_SEARCH_RE = re.compile(r"google\.com/search\?q=([^\"&]+)")
SEPARATOR = "=" * 25 + "\n"


def _arrow_select(prompt, options):
    """Arrow-key selection menu. Returns the index of the chosen option."""
    selected = 0

    def render():
        for i, opt in enumerate(options):
            marker = "> " if i == selected else "  "
            sys.stdout.write(f"  {marker}{opt}\r\n")
        sys.stdout.flush()

    def move_up():
        sys.stdout.write(f"\033[{len(options)}A")
        sys.stdout.flush()

    print(prompt)
    render()

    if sys.platform == "win32":
        import msvcrt

        while True:
            ch = msvcrt.getwch()
            if ch == "\xe0":
                ch2 = msvcrt.getwch()
                if ch2 == "H":
                    selected = (selected - 1) % len(options)
                elif ch2 == "P":
                    selected = (selected + 1) % len(options)
            elif ch in ("\r", "\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()
                return selected
            move_up()
            render()
    else:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while True:
                ch = sys.stdin.read(1)
                if ch == "\x1b":
                    ch = sys.stdin.read(1)
                    if ch == "[":
                        ch = sys.stdin.read(1)
                        if ch == "A":
                            selected = (selected - 1) % len(options)
                        elif ch == "B":
                            selected = (selected + 1) % len(options)
                elif ch in ("\r", "\n"):
                    break
                elif ch == "\x03":
                    raise KeyboardInterrupt
                move_up()
                render()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write("\r\n")
        sys.stdout.flush()
        return selected


class PrepWork:
    config_path = Path("ps3rpcconfig.json")

    def __init__(self):
        self.RPC = None
        self.config = {}
        self.session = requests.Session()
        self.session.headers.update(headers)

    def read_config(self):
        if self.config_path.is_file():
            try:
                with self.config_path.open(mode="r") as f:
                    self.config = json.load(f)
            except json.JSONDecodeError:
                print(
                    f"Config file {self.config_path} is corrupted, "
                    "resetting to defaults."
                )
                self.config_path.unlink()
                self.config = default_config
                self.prompt_user()
                return
            self.config["wait_seconds"] = max(15, self.config["wait_seconds"])
            if not self.test_for_webman(self.config["ip"]) and self.config["ip_prompt"]:
                print("PS3 cannot be reached via the IP saved in the config file.")
                self.prompt_user()
        else:
            self.config = default_config
            self.prompt_user()

    def prompt_user(self):
        print("\n===== PS3-RPC Setup =====\n")
        options = [
            "Automatic — scan network for PS3",
            "Manual   — enter IP address directly",
        ]
        choice = _arrow_select(
            "How would you like to find your PS3's IP address?\nUse arrow keys to navigate and press enter to select an option.\n",
            options,
        )
        print(SEPARATOR)
        if choice == 0:
            self.grab_host_network()
        else:
            self.get_IP_from_user()

    def grab_host_network(self):
        hostNetwork = None
        try:
            tempSock = socket(AF_INET, SOCK_DGRAM)
            tempSock.connect(("8.8.8.8", 80))
            hostNetwork = tempSock.getsockname()[0]
            tempSock.close()
        except Exception as e:
            print(f'Error while getting host network: "{e}"')

        if hostNetwork is not None:
            hostNetwork = hostNetwork.rsplit(".", 1)[0] + "."
            print(f"Detected network: {hostNetwork}0/24")
            self.scan_network(hostNetwork)
        else:
            print("Could not determine host network. Falling back to manual entry.")
            self.get_IP_from_user()

    def scan_network(self, my_network):
        my_network += "0/24"
        max_retries = 5
        for attempt in range(1, max_retries + 1):
            print(f"Scanning {my_network} for PS3... (attempt {attempt}/{max_retries})")
            my_scan = networkscan.Networkscan(my_network)
            my_scan.run()

            hosts = my_scan.list_of_hosts_found
            print(f"Scan complete — {len(hosts)} host(s) found.")

            for host in hosts:
                if self.test_for_webman(host, silent=True):
                    print(f'PS3 found at "{host}".')
                    self.save_config(host)
                    return

            if attempt < max_retries:
                print(f"PS3 not found. Retrying in 20 seconds...")
                sleep(10)

        print(f"PS3 not found after {max_retries} scan attempts.")
        print("Falling back to manual IP entry.")
        self.get_IP_from_user()

    def get_IP_from_user(self):
        while True:
            ip = input(
                "Enter your PS3's IP address\n(for example: 192.168.0.122): "
            ).strip()
            if self.test_for_webman(ip):
                self.save_config(ip)
                break
            print("Could not connect to PS3 at that address. Please try again.")

    def test_for_webman(self, ip, silent=False):
        url = f"http://{ip}"
        try:
            response = self.session.get(url)
        except ConnectionError:
            if not silent:
                print(f'No webpage found on "{ip}"')
            return False
        if response is not None:
            soup = BeautifulSoup(response.text, "html.parser")
            title_tag = soup.find("title")
            pageTitle = title_tag.get_text(strip=True) if title_tag else ""
            if "wMAN" in pageTitle or "webMAN" in pageTitle:
                if not silent:
                    print(f'Given IP "{ip}" belongs to webman.')
                return True
            else:
                if not silent:
                    print(
                        f'WebmanMOD not found on "{ip}", reports "{pageTitle}". '
                        "If you believe this is an error, please contact the developer. "
                        "Please ensure the PS3 is turned on, has webmanMOD installed and running, "
                        "and is connected to the same network as the PC."
                    )
                return False

    def save_config(self, valid_ip):
        self.config["ip"] = valid_ip
        with self.config_path.open(mode="w+") as f:
            json.dump(self.config, f, indent=4)

    def connect_to_discord(self):
        while True:
            try:
                self.RPC = Presence(self.config["client_id"])
                self.RPC.connect()
                print("Connected to Discord client")
                break
            except (DiscordNotFound, InvalidPipe, ConnectionRefusedError) as e:
                print(f'Could not connect to Discord: "{e}"')
                print(
                    "Ensure Discord is running. If PS3-RPC is a systemd service, "
                    "Discord must be running in the same user session."
                )
                sleep(20)
