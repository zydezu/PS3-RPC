import ipaddress
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from socket import AF_INET, SOCK_DGRAM, socket
from time import sleep

import requests
from bs4 import BeautifulSoup
from pypresence import DiscordNotFound, InvalidPipe
from pypresence.presence import Presence

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
    "short_console_name": True,
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
_IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
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


def _page_is_webman(html):
    """True if an HTML page's <title> looks like webMAN MOD."""
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    page_title = title_tag.get_text(strip=True) if title_tag else ""
    return "wMAN" in page_title or "webMAN" in page_title


def _scan_probe(ip, timeout):
    """HTTP-probe a single address. Returns the ip if webMAN answers, else None."""
    try:
        resp = requests.get(f"http://{ip}", timeout=timeout, headers=headers)
    except requests.RequestException:
        return None
    return ip if _page_is_webman(resp.text) else None


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
                self.config = default_config.copy()
                self.prompt_user()
                return
            missing = {k: v for k, v in default_config.items() if k not in self.config}
            if missing:
                self.config.update(missing)
                self.save_config(self.config["ip"])
                print(
                    f"Config updated with {len(missing)} new default(s): {', '.join(missing)}"
                )
            self.config["wait_seconds"] = max(15, self.config["wait_seconds"])
            saved_ip = str(self.config.get("ip") or "").strip()
            if not saved_ip:
                print("No PS3 IP address is saved yet.")
                self.prompt_user()
            elif self.config["ip_prompt"] and not self.test_for_webman(saved_ip):
                print(f'PS3 cannot be reached at the saved IP address "{saved_ip}".')
                self.prompt_user()
        else:
            self.config = default_config.copy()
            print(
                f"No config file found — a new one will be saved to {self.config_path}"
            )
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
        host_ip = None
        try:
            tempSock = socket(AF_INET, SOCK_DGRAM)
            tempSock.connect(("8.8.8.8", 80))
            host_ip = tempSock.getsockname()[0]
            tempSock.close()
        except Exception as e:
            print(f'Error while getting host network: "{e}"')

        if host_ip is not None:
            self.scan_network(host_ip)
        else:
            print("Could not determine host network. Falling back to manual entry.")
            self.get_IP_from_user()

    def scan_network(self, host_ip, timeout=1.5, workers=64):
        # every address in the range is HTTP-probed
        network = ipaddress.ip_network(f"{host_ip}/24", strict=False)
        targets = [str(ip) for ip in network.hosts() if str(ip) != host_ip]
        print(f"Scanning {network} for webMAN ({len(targets)} addresses...")

        found = None
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_scan_probe, ip, timeout): ip for ip in targets}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    found = result
                    for pending in futures:
                        pending.cancel()
                    break

        if found:
            print(f'PS3 found at "{found}".')
            self.save_config(found)
            return

        print("No webMAN instance found on the network.")
        print("Falling back to manual IP entry.")
        self.get_IP_from_user()

    def get_IP_from_user(self):
        while True:
            ip = input(
                "Enter your PS3's IP address (for example: 192.168.0.122),\n"
                "or press Ctrl+C to quit: "
            ).strip()
            if not ip:
                print("No address entered.\n")
                continue
            if _IPV4_RE.match(ip) is None:
                print(f'"{ip}" does not look like an IPv4 address — trying it anyway.')
            if self.test_for_webman(ip):
                self.save_config(ip)
                break
            print("Could not connect to PS3 at that address. Please try again.\n")

    def test_for_webman(self, ip, silent=False):
        ip = str(ip or "").strip()
        if not ip:
            if not silent:
                print("No IP address to test.")
            return False
        url = f"http://{ip}"
        try:
            response = self.session.get(url, timeout=5)
        except requests.RequestException as e:
            if not silent:
                print(f'Could not reach a webpage on "{ip}" ({type(e).__name__}).')
            return False
        if _page_is_webman(response.text):
            if not silent:
                print(f'Given IP "{ip}" belongs to webMAN.')
            return True
        if not silent:
            print(
                f'webMAN MOD not found on "{ip}". '
                "Please ensure the PS3 is turned on, has webMAN MOD installed and "
                "running, and is connected to the same network as the PC."
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
