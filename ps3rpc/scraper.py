import platform
import re
import subprocess

import requests
from bs4 import BeautifulSoup
from requests.exceptions import ConnectionError

from ps3rpc.config import _PS2_RE, _PSX_RE, _RETRO_LINK_RE, _VERSION_RE, headers


class GatherDetails:
    def __init__(self, prep):
        self.prep = prep
        self.session = requests.Session()
        self.session.headers.update(headers)
        self.soup = None
        self.thermalData = None
        self.name = None
        self.titleID = None
        self.image = None
        self.isRetroGame = False
        self.isInGame = False
        self._prev_title = ""

    def ping_PS3(self):
        ip = self.prep.config["ip"]
        if platform.system().lower() == "windows":
            command = ["ping", "-n", "5", ip]
        else:
            command = ["ping", "-c", "5", ip]
        try:
            subprocess.check_call(command, stdout=subprocess.DEVNULL)
            return True
        except subprocess.CalledProcessError:
            return False

    def get_html(self):
        url = f"http://{self.prep.config['ip']}/cpursx.ps3?/sman.ps3"
        if not self.ping_PS3():
            return False
        try:
            response = self.session.get(url)
            self.soup = BeautifulSoup(response.text, "html.parser")
            return True
        except ConnectionError as e:
            print(f'get_html():  webman not found. "{e}".')
            return False

    def get_thermals(self):
        thermal_tag = self.soup.find("a", href="/cpursx.ps3?up")
        if thermal_tag is None:
            print("get_thermals(): could not find thermal data in HTML")
            return
        thermalData = str(thermal_tag)
        cpu = re.search(r"CPU(.+?)C", thermalData)
        rsx = re.search(r"RSX(.+?)C", thermalData)
        if cpu and rsx:
            self.thermalData = f"{cpu.group(0)} | {rsx.group(0)}"
            print(f"get_thermals():     {self.thermalData}")
        else:
            from ps3rpc.config import wmanVer

            print(
                f"get_thermals(): could not find html for thermal data, "
                f"has webmanMOD been updated since {wmanVer}?"
            )

    def decide_game_type(self):
        self.isRetroGame = False
        self.isInGame = False
        if self.soup.find("a", target="_blank") is not None:
            print("decide_game_type():  PS3 Game or Homebrew")
            self.isInGame = True
            self.get_PS3_details()
        elif (
            self.soup.find("a", href=_PSX_RE) is not None
            or self.soup.find("a", href=_PS2_RE) is not None
        ):
            self.isRetroGame = True
            self.isInGame = True
            print("decide_game_type():  Retro")
            self.get_retro_details()
        else:
            print("decide_game_type():  XMB")
            self.name = "XMB"
            self.image = "xmb"
            self.titleID = None

    def get_PS3_details(self):
        title_tag = self.soup.find("a", target="_blank")
        name_tag = title_tag.find_next_sibling()
        if title_tag is None or name_tag is None:
            return
        titleID = title_tag.get_text(strip=True)
        name = name_tag.get_text(strip=True)
        name = _VERSION_RE.sub("", name) if _VERSION_RE.search(name) else name
        self.name = name or titleID
        self.titleID = titleID
        print(f"get_PS3_details():  {titleID} | {name}")
        if self._prev_title != titleID:
            self.get_PS3_image()
            self._prev_title = titleID

    def get_retro_details(self):
        name = "PlayStation 1/2"
        if self.prep.config["retro_covers"]:
            name_tag = self.soup.find("a", href=_PSX_RE) or self.soup.find(
                "a", href=_PS2_RE
            )
            if name_tag is not None:
                sibling = name_tag.find_next_sibling()
                if sibling is not None:
                    match = _RETRO_LINK_RE.search(str(sibling))
                    if match:
                        name = match.group(1)
        self.name = name
        print(f"get_retro_details(): {name}")
        self.get_retro_image()

    def get_PS3_image(self):
        self.image = self.titleID.lower()
        if not self.prep.config["prefer_dev_app"]:
            self.image = self.use_gametdb()
        print(f"get_PS3_image():    {self.image}")

    def use_gametdb(self):
        region_map = {
            "A": "ZH",
            "E": "EN",
            "H": "US",
            "J": "JA",
            "K": "KO",
            "U": "US",
        }
        region_code = region_map.get(self.titleID[2])
        if not region_code:
            print(
                f"! use_gametdb(): Unexpected key: {self.titleID[2]} ! \n"
                "Falling back to Discord dev app images"
            )
            return self.titleID.lower()
        url = f"https://art.gametdb.com/ps3/cover/{region_code}/{self.titleID}.jpg"
        try:
            resp = self.session.get(url, headers={"User-Agent": "PS3RPC/2.0.1"})
            if resp.status_code == 200:
                print("using GameTDB")
                return url
        except requests.RequestException:
            pass
        print(f"use_gametdb(): no image found at {url}, using Discord dev app image")
        return self.titleID.lower()

    def get_retro_image(self):
        imgName = self.name.lower()
        imgName = imgName.replace(" ", "_")
        imgName = imgName.replace("&amp;", "")
        imgName = re.sub(r"[\W]+", "", imgName)
        imgName = imgName[:32]
        self.image = imgName
        print(f"get_retro_image():  {imgName}")
