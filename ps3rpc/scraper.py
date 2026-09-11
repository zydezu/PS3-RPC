import io
import platform
import re
import subprocess

import requests
from bs4 import BeautifulSoup
from PIL import Image
from requests.exceptions import ConnectionError

from ps3rpc.config import (
    _CLOCKS_RE,
    _FAN_RE,
    _FIRMWARE_RE,
    _GOOGLE_SEARCH_RE,
    _HDD_RE,
    _PS2_RE,
    _PSX_RE,
    _RETRO_LINK_RE,
    _THERMAL_RE,
    _VERSION_RE,
    headers,
)
from ps3rpc.ui import C, ok, warn

_LABEL_WIDTH = 10  # widest current label ("Game type:") — keeps the log table-aligned


def _log(label, value=""):
    """Dim, table-aligned debug line: 'label      value'."""
    padded = label.ljust(_LABEL_WIDTH)
    if value:
        print(f"{C.GRAY}{padded}{C.RESET} {value}")
    else:
        print(f"{C.GRAY}{label}{C.RESET}")


def _temp_color(celsius):
    """Green/cyan/yellow/red ramp for a PS3 CPU/RSX temperature reading."""
    if celsius < 50:
        return C.GREEN
    if celsius < 65:
        return C.CYAN
    if celsius < 75:
        return C.YELLOW
    return C.RED


def _colorize_temps(cpu_str, rsx_str):
    """Colour each 'CPU: 67°C' / 'RSX: 67°C' fragment by how hot it is."""

    def colored(fragment):
        match = re.search(r"(\d+)", fragment)
        color = _temp_color(int(match.group(1))) if match else C.RESET
        return f"{color}{fragment}{C.RESET}"

    return f"{colored(cpu_str)} {C.GRAY}|{C.RESET} {colored(rsx_str)}"


def _square_pad(png_bytes):
    """Make sure image fits on Discord (1:1)"""
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    size = max(img.size)
    if img.size == (size, size):
        return png_bytes
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(img, ((size - img.width) // 2, (size - img.height) // 2), img)
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


class GatherDetails:
    def __init__(self, prep):
        self.prep = prep
        self.session = requests.Session()
        self.session.headers.update(headers)
        self.soup = None
        self.temps = None
        self.systemExtras = ""
        self.firmware = None
        self.name = None
        self.titleID = None
        self.image = None
        self.isRetroGame = False
        self.isInGame = False
        self._prev_title = ""
        self._icon0_cache = {}

    def ping_PS3(self):
        # 2 packets (not 5): ping exits 0 as soon as any reply comes back, so
        # this still tolerates one dropped/ARP-delayed packet, but no longer
        # blocks the whole poll cycle for ~4s waiting out unneeded pings.
        ip = self.prep.config["ip"]
        if platform.system().lower() == "windows":
            command = ["ping", "-n", "2", "-w", "1000", ip]
        else:
            command = ["ping", "-c", "2", "-W", "1", ip]
        try:
            subprocess.check_call(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
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
            warn(f'Connection: webman not found. "{e}".')
            return False

    def get_thermals(self):
        thermal_tag = self.soup.find("a", href="/cpursx.ps3?up")
        if thermal_tag is None:
            warn("Thermals: could not find thermal data in HTML")
            return
        thermalData = str(thermal_tag)
        cpu = re.search(r"CPU(.+?)C", thermalData)
        rsx = re.search(r"RSX(.+?)C", thermalData)
        if cpu and rsx:
            self.temps = _THERMAL_RE.sub("", f"{cpu.group(0)} | {rsx.group(0)}")
            _log("Thermals:", _colorize_temps(cpu.group(0), rsx.group(0)))
            self.systemExtras = self._system_extras()
        else:
            from ps3rpc.config import wmanVer

            warn(
                f"Thermals: could not find html for thermal data, "
                f"has webmanMOD been updated since {wmanVer}?"
            )

    def _system_extras(self):
        """'GPU 500/650 MHz | HDD 76.8 GB free | Fan speed: 45%' from the cpursx page."""
        cfg = self.prep.config
        if not (
            cfg.get("show_clocks")
            or cfg.get("show_hdd_free")
            or cfg.get("show_fan_speed")
        ):
            return ""
        page = self.soup.get_text(" ")
        parts = []
        if cfg.get("show_clocks"):
            clocks = _CLOCKS_RE.search(page)
            if clocks:
                parts.append(f"GPU {clocks.group(1)}/{clocks.group(2)} MHz")
        if cfg.get("show_hdd_free"):
            hdd = _HDD_RE.search(page)
            if hdd:
                parts.append(f"HDD {' '.join(hdd.group(1).split())} free")
        if cfg.get("show_fan_speed"):
            fan = _FAN_RE.search(page)
            if fan:
                parts.append(f"Fan speed: {fan.group(1)}%")
        if parts:
            _log("System:", " | ".join(parts))
        return " | ".join(parts)

    def get_session_seconds(self):
        """Seconds the current game has been running, from webman UI."""
        label = self.soup.find("label", title="Play")
        if label is None or label.next_sibling is None:
            return None
        match = re.search(r"(\d+):(\d{2}):(\d{2})", str(label.next_sibling))
        if not match:
            return None
        hours, minutes, seconds = (int(part) for part in match.groups())
        return hours * 3600 + minutes * 60 + seconds

    def get_firmware(self):
        """PS3 firmware / CFW string, e.g. 'FW 4.93 CEX Cobra 8.5'."""
        match = _FIRMWARE_RE.search(self.soup.get_text(" "))
        self.firmware = f"FW {' '.join(match.group(1).split())}" if match else None
        if self.firmware:
            _log("Firmware:", self.firmware)

    def build_tooltip(self):
        """Large-image hover text: temp/clocks/HDD/firmware/title ID (per config)."""
        temps = self.temps if self.prep.config.get("tooltip_temp") else None
        titleID = self.titleID if self.prep.config.get("tooltip_game_id") else None
        parts = [p for p in (temps, self.systemExtras, self.firmware, titleID) if p]
        return " | ".join(parts)

    def decide_game_type(self):
        self.isRetroGame = False
        self.isInGame = False
        if self.soup.find("a", target="_blank") is not None:
            _log("Game type:", f"{C.GREEN}PS3 Game or Homebrew{C.RESET}")
            self.isInGame = True
            self.get_PS3_details()
        elif (
            self.soup.find("a", href=_PSX_RE) is not None
            or self.soup.find("a", href=_PS2_RE) is not None
        ):
            self.isRetroGame = True
            self.isInGame = True
            _log("Game type:", f"{C.MAGENTA}Retro{C.RESET}")
            self.get_retro_details()
        else:
            _log("Game type:", f"{C.BLUE}XMB{C.RESET}")
            self.name = "XMB"
            self.image = "xmb"
            self.titleID = None

    def get_PS3_details(self):
        title_tag = self.soup.find("a", target="_blank")
        if title_tag is None:
            return
        titleID = title_tag.get_text(strip=True)
        name = ""
        name_tag = title_tag.find_next_sibling()
        if name_tag is not None:
            name = name_tag.get_text(strip=True)
            name = (
                _VERSION_RE.sub(r"\1", name).strip()
                if _VERSION_RE.search(name)
                else name
            )
        if not name:
            google_tag = self.soup.find("a", href=_GOOGLE_SEARCH_RE)
            if google_tag is not None:
                match = _GOOGLE_SEARCH_RE.search(google_tag.get("href", ""))
                if match:
                    name = match.group(1)
                    _log("Game:", f"name from search link: {name}")
        self.name = name or titleID
        self.titleID = titleID
        _log(
            "Game:",
            f"{C.GRAY}{titleID}{C.RESET} {C.GRAY}|{C.RESET} "
            f"{C.WHITE}{C.BOLD}{self.name}{C.RESET}",
        )
        if self._prev_title != titleID:
            self.get_PS3_image()
            self._prev_title = titleID

    def get_retro_details(self):
        self.titleID = None
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
        _log("Game:", f"{C.WHITE}{C.BOLD}{name}{C.RESET}")
        self.get_retro_image()

    def get_PS3_image(self):
        self.image = self.titleID.lower()
        if self.prep.config.get("use_icon0"):
            icon_url = self.use_icon0()
            if icon_url:
                self.image = icon_url
                _log("Cover:", f"{C.CYAN}{self.image}{C.RESET}")
                return
        if not self.prep.config["prefer_dev_app"]:
            self.image = self.use_gametdb()
        image_color = C.CYAN if self.image.startswith("http") else C.GRAY
        _log("Cover:", f"{image_color}{self.image}{C.RESET}")

    def use_icon0(self):
        """Fetch the game's ICON0.PNG from the PS3 and upload to uguu.se"""
        if self.titleID in self._icon0_cache:
            return self._icon0_cache[self.titleID]

        ip = self.prep.config["ip"]
        icon_url = f"http://{ip}/dev_hdd0/game//{self.titleID}/ICON0.PNG"
        try:
            resp = self.session.get(icon_url, timeout=8)
            if resp.status_code != 200 or not resp.content:
                warn(f"Cover: no ICON0.PNG found at {icon_url}")
                return None
        except requests.RequestException as e:
            warn(f"Cover: could not fetch ICON0.PNG ({type(e).__name__})")
            return None

        icon_bytes = resp.content
        try:
            icon_bytes = _square_pad(icon_bytes)
        except Exception as e:
            warn(
                f"Cover: could not square the icon ({type(e).__name__}), uploading as-is"
            )

        try:
            upload = requests.post(
                "https://uguu.se/upload?output=text",
                files={"files[]": ("ICON0.PNG", icon_bytes, "image/png")},
                timeout=15,
            )
            upload.raise_for_status()
            uploaded_url = upload.text.strip()
            if not uploaded_url.startswith("http"):
                raise ValueError(f"unexpected response: {uploaded_url!r}")
        except (requests.RequestException, ValueError) as e:
            warn(f"Cover: upload to uguu.se failed ({type(e).__name__})")
            return None

        ok(f"Cover: uploaded to {uploaded_url}")
        self._icon0_cache[self.titleID] = uploaded_url
        return uploaded_url

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
            warn(
                f"Cover: unexpected region key {self.titleID[2]} — "
                "falling back to Discord dev app images"
            )
            return self.titleID.lower()
        url = f"https://art.gametdb.com/ps3/cover/{region_code}/{self.titleID}.jpg"
        try:
            resp = self.session.get(url, headers={"User-Agent": "PS3RPC/2.0.1"})
            if resp.status_code == 200:
                ok("Cover: using GameTDB cover")
                return url
        except requests.RequestException:
            pass
        warn(f"Cover: no image found at {url}, using Discord dev app image")
        return self.titleID.lower()

    def get_retro_image(self):
        imgName = self.name.lower()
        imgName = imgName.replace(" ", "_")
        imgName = imgName.replace("&amp;", "")
        imgName = re.sub(r"[\W]+", "", imgName)
        imgName = imgName[:32]
        self.image = imgName
        _log("Cover:", f"{C.GRAY}{imgName}{C.RESET}")
