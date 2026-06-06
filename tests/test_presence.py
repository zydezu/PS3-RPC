"""
Manual presence test — simulates playing Persona 5 (NPUB31848) on PS3.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
from time import sleep, time

from pypresence import DiscordNotFound, InvalidID, InvalidPipe, ServerError
from pypresence.presence import Presence

from ps3rpc.config import PrepWork, default_config
from ps3rpc.scraper import GatherDetails

TITLE_ID = "BLES01507"
GAME_NAME = "Hyperdimension Neptunia mk2"
WAIT = 15


def main():
    prep = PrepWork()
    if prep.config_path.is_file():
        with prep.config_path.open() as f:
            prep.config = json.load(f)
        print(f"Loaded config from {prep.config_path}")
    else:
        prep.config = default_config
        with prep.config_path.open("w") as f:
            json.dump(prep.config, f, indent=4)
        print(f"No config found — created {prep.config_path} with defaults.")
    CLIENT_ID = prep.config["client_id"]
    print(f"Connecting to Discord (client_id={CLIENT_ID})...")
    rpc = Presence(CLIENT_ID)
    try:
        rpc.connect()
    except (DiscordNotFound, InvalidPipe, ConnectionRefusedError) as e:
        print(f"Could not connect to Discord: {e}")
        print("Make sure Discord is running.")
        return
    print("Connected.")

    gd = GatherDetails(prep)
    gd.titleID = TITLE_ID
    gd.name = GAME_NAME
    gd.isInGame = True
    gd.isRetroGame = False
    gd._prev_title = ""
    gd.get_PS3_image()

    if prep.config["show_temp"] or prep.config["temp_on_tooltip"]:
        gd.thermalData = "CPU 65°C | RSX 70°C"

    timer = int(time())
    console = "PS3" if prep.config["short_console_name"] else "PlayStation®3 system"
    playing_on = f"Playing on {console}"

    large_text = gd.thermalData if prep.config["temp_on_tooltip"] else gd.titleID
    temp_line = gd.thermalData if prep.config["show_temp"] else None

    rpc_kwargs = {
        "large_image": gd.image,
        "large_text": large_text or gd.titleID,
        "start": timer,
    }
    if prep.config["use_appname"]:
        rpc_kwargs["details"] = gd.name
        rpc_kwargs["state"] = temp_line or playing_on
    else:
        rpc_kwargs["name"] = gd.name
        rpc_kwargs["details"] = temp_line
        rpc_kwargs["state"] = playing_on

    print(f"\nSetting presence: {GAME_NAME} ({TITLE_ID})")
    print(f"  large_image: {gd.image}")
    print(f"  state:       {playing_on}")
    print(f"\nUpdating every {WAIT}s — press Ctrl+C to stop.\n")

    try:
        while True:
            try:
                rpc.update(**rpc_kwargs)
                print("Presence updated.")
            except (InvalidPipe, InvalidID):
                print("Lost Discord connection, reconnecting...")
                rpc.close()
                rpc = Presence(CLIENT_ID)
                rpc.connect()
            except ServerError as e:
                print(f"Discord rejected update: {e}")
            sleep(WAIT)
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        rpc.clear()
        rpc.close()


if __name__ == "__main__":
    main()
