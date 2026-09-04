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

from ps3rpc.ui import C, clear, err, ok, warn

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
    "use_icon0": True,
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


def _read_key():
    """Block for one keypress. Returns 'up' / 'down' / 'space' / 'enter' / None."""
    if sys.platform == "win32":
        import msvcrt

        ch = msvcrt.getwch()
        if ch == "\xe0":
            return {"H": "up", "P": "down"}.get(msvcrt.getwch())
        if ch == " ":
            return "space"
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x03":
            raise KeyboardInterrupt
        return None

    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            if sys.stdin.read(1) == "[":
                return {"A": "up", "B": "down"}.get(sys.stdin.read(1))
            return None
        if ch == " ":
            return "space"
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x03":
            raise KeyboardInterrupt
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _arrow_select(prompt, options):
    """Arrow-key selection menu. Returns the index of the chosen option."""
    selected = 0

    def render():
        for i, opt in enumerate(options):
            if i == selected:
                sys.stdout.write(f"{C.YELLOW}{C.BOLD}> {opt}{C.RESET}\r\n")
            else:
                sys.stdout.write(f"  {C.GRAY}{opt}{C.RESET}\r\n")
        sys.stdout.flush()

    def move_up():
        sys.stdout.write(f"\033[{len(options)}A")
        sys.stdout.flush()

    print(prompt)
    render()
    while True:
        key = _read_key()
        if key == "up":
            selected = (selected - 1) % len(options)
        elif key == "down":
            selected = (selected + 1) % len(options)
        elif key == "enter":
            sys.stdout.write("\r\n")
            sys.stdout.flush()
            return selected
        else:
            continue
        move_up()
        render()


def _toggle_select(prompt, items, values):
    """Checklist menu"""
    selected = 0

    def render():
        for i, (key, label) in enumerate(items):
            box = f"{C.GREEN}[x]{C.RESET}" if values[key] else f"{C.GRAY}[ ]{C.RESET}"
            if i == selected:
                sys.stdout.write(f"{C.YELLOW}{C.BOLD}>{C.RESET} {box} {label}\r\n")
            else:
                sys.stdout.write(f"  {box} {C.GRAY}{label}{C.RESET}\r\n")
        sys.stdout.flush()

    def move_up():
        sys.stdout.write(f"\033[{len(items)}A")
        sys.stdout.flush()

    print(prompt)
    render()
    while True:
        key = _read_key()
        if key == "up":
            selected = (selected - 1) % len(items)
        elif key == "down":
            selected = (selected + 1) % len(items)
        elif key == "space":
            item_key = items[selected][0]
            values[item_key] = not values[item_key]
        elif key == "enter":
            sys.stdout.write("\r\n")
            sys.stdout.flush()
            return values
        else:
            continue
        move_up()
        render()


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
                warn(
                    f"Config file {self.config_path} is corrupted, resetting to defaults."
                )
                self.config_path.unlink()
                self.config = default_config.copy()
                self.prompt_user()
                self.configure_options()
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
                warn("No PS3 IP address is saved yet.")
                self.prompt_user()
            elif self.config["ip_prompt"] and not self.test_for_webman(saved_ip):
                err(f'PS3 cannot be reached at the saved IP address "{saved_ip}".')
                self.prompt_user()
        else:
            self.config = default_config.copy()
            print(
                f"{C.GRAY}No config file found — a new one will be saved to "
                f"{self.config_path}{C.RESET}"
            )
            self.prompt_user()
            self.configure_options()

    def prompt_user(self):
        clear()
        print(f"\n{C.BOLD}{C.CYAN}===== PS3-RPC Setup ====={C.RESET}\n")
        options = [
            "Automatic — scan network for PS3",
            "Manual   — enter IP address directly",
        ]
        choice = _arrow_select(
            f"{C.BOLD}How would you like to find your PS3's IP address?{C.RESET}\n"
            f"{C.GRAY}Use arrow keys to navigate and press enter to select an option.{C.RESET}\n",
            options,
        )
        print(SEPARATOR)
        if choice == 0:
            self.grab_host_network()
        else:
            self.get_IP_from_user()

    # Options shown on the first-run toggle screen.
    _TOGGLE_OPTIONS = [
        ("show_temp", "Show PS3 CPU/RSX temperature in the presence"),
        ("retro_covers", "Use game-specific covers for PS1/PS2 games"),
        ("ip_prompt", "Re-prompt for IP if the PS3 can't be reached on startup"),
        ("show_timer", "Display time elapsed in the presence"),
        ("prefer_dev_app", "Use Discord dev app images instead of GameTDB covers"),
        ("use_icon0", "Use the game's own ICON0.PNG instead of GameTDB/dev app covers"),
        (
            "use_appname",
            "Show game name as the activity details line instead of the app name",
        ),
        ("short_console_name", 'Show "PS3" instead of "PlayStation®3 system"'),
        (
            "show_only_in_game",
            "Only update presence when a game is running (hide on XMB)",
        ),
        ("temp_on_tooltip", "Show temperature when hovering over the large image"),
    ]

    def configure_options(self):
        """Let the user toggle the boolean config options before starting."""
        clear()
        print(f"\n{C.BOLD}{C.CYAN}===== First-time Setup: Options ====={C.RESET}\n")
        values = {
            key: bool(self.config.get(key, default_config[key]))
            for key, _ in self._TOGGLE_OPTIONS
        }
        values = _toggle_select(
            f"{C.BOLD}View and toggle any options below, then press enter to continue.{C.RESET}\n"
            f"{C.GRAY}Use arrow keys to navigate, "
            f"{C.WHITE}{C.BOLD}space{C.RESET}{C.GRAY} to toggle, "
            f"{C.WHITE}{C.BOLD}enter{C.RESET}{C.GRAY} to confirm.{C.RESET}\n",
            self._TOGGLE_OPTIONS,
            values,
        )
        self.config.update(values)
        self.save_config(self.config["ip"])
        print(SEPARATOR)

    def grab_host_network(self):
        host_ip = None
        try:
            tempSock = socket(AF_INET, SOCK_DGRAM)
            tempSock.connect(("8.8.8.8", 80))
            host_ip = tempSock.getsockname()[0]
            tempSock.close()
        except Exception as e:
            err(f'Error while getting host network: "{e}"')

        if host_ip is not None:
            self.scan_network(host_ip)
        else:
            warn("Could not determine host network. Falling back to manual entry.")
            self.get_IP_from_user()

    def scan_network(self, host_ip, timeout=2.5, workers=64):
        # every address in the range is HTTP-probed
        network = ipaddress.ip_network(f"{host_ip}/24", strict=False)
        targets = [str(ip) for ip in network.hosts() if str(ip) != host_ip]
        print(
            f"{C.GRAY}Scanning {network} for webMAN "
            f"({len(targets)} addresses)...{C.RESET}"
        )

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
            ok(f'PS3 found at "{found}".')
            self.save_config(found)
            return

        warn("No webMAN instance found on the network.")
        print(f"{C.GRAY}Falling back to manual IP entry.{C.RESET}")
        self.get_IP_from_user()

    def get_IP_from_user(self):
        while True:
            ip = input(
                f"{C.BOLD}Enter your PS3's IP address{C.RESET} "
                f"{C.GRAY}(for example: 192.168.0.122),{C.RESET}\n"
                f"{C.GRAY}or press Ctrl+C to quit:{C.RESET} "
            ).strip()
            if not ip:
                warn("No address entered.\n")
                continue
            if _IPV4_RE.match(ip) is None:
                warn(f'"{ip}" does not look like an IPv4 address — trying it anyway.')
            if self.test_for_webman(ip):
                self.save_config(ip)
                break
            print(f"{C.GRAY}Please try again.{C.RESET}\n")

    def test_for_webman(self, ip, silent=False):
        ip = str(ip or "").strip()
        if not ip:
            if not silent:
                err("No IP address to test.")
            return False
        url = f"http://{ip}"
        try:
            response = self.session.get(url, timeout=5)
        except requests.RequestException as e:
            if not silent:
                err(f'Could not reach a webpage on "{ip}" ({type(e).__name__}).')
            return False
        if _page_is_webman(response.text):
            if not silent:
                ok(f'PS3 IP: "{ip}"')
            return True
        if not silent:
            err(
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
                ok("Successfully connected to Discord client")
                break
            except (DiscordNotFound, InvalidPipe, ConnectionRefusedError) as e:
                err(f'Could not connect to Discord: "{e}"')
                print(
                    f"{C.GRAY}Ensure Discord is running. If PS3-RPC is a systemd "
                    f"service, Discord must be running in the same user "
                    f"session.{C.RESET}"
                )
                sleep(20)
