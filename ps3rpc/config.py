import json
import re
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
    "show_elapsed": True,
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


class PrepWork:
    config_path = Path("ps3rpcconfig.txt")

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
        accepted = ["a", "m"]
        print("\nGet PS3's IP address automatically, or manually?")
        while True:
            choice = input('Please enter either "A", or "M": ').strip().lower()
            if choice in accepted:
                break
        if choice == "a":
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
            print(f'Error while getting host network. "{e}"')

        if hostNetwork is not None:
            hostNetwork = hostNetwork.rsplit(".", 1)[0] + "."
            print(f'expected network is "{hostNetwork}"')
            self.scan_network(hostNetwork)

    def scan_network(self, my_network):
        my_network += "0/24"
        found = False
        while True:
            my_scan = networkscan.Networkscan(my_network)
            my_scan.run()

            print("Completed network scan.")
            print(my_scan.list_of_hosts_found)

            for host in my_scan.list_of_hosts_found:
                if self.test_for_webman(host):
                    self.save_config(host)
                    found = True
                    break
            if found:
                break
            else:
                print("PS3 not found on network, waiting 20 seconds before retry")
                sleep(20)

    def get_IP_from_user(self):
        while True:
            ip = input("Enter PS3's IP address: ")
            if self.test_for_webman(ip):
                self.save_config(ip)
                break

    def test_for_webman(self, ip):
        url = f"http://{ip}"
        try:
            response = self.session.get(url)
        except ConnectionError:
            print(f'No webpage found on "{ip}"')
            return False
        if response is not None:
            soup = BeautifulSoup(response.text, "html.parser")
            title_tag = soup.find("title")
            pageTitle = title_tag.get_text(strip=True) if title_tag else ""
            if "wMAN" in pageTitle or "webMAN" in pageTitle:
                print(f'Given IP "{ip}" belongs to webman.')
                return True
            else:
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
