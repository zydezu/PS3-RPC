import re
from time import sleep, time

from pypresence import InvalidPipe, InvalidID, ServerError

from ps3rpc.config import PrepWork, headers, _THERMAL_RE
from ps3rpc.scraper import GatherDetails


def main():
    prepWork = PrepWork()
    prepWork.read_config()
    prepWork.connect_to_discord()
    closed = False
    gatherDetails = GatherDetails(prepWork)
    timer = None
    if prepWork.config["show_timer"]:
        timer = time()

    if not prepWork.config["ip"]:
        exit("script failed to execute critical functions.")

    while True:
        if not gatherDetails.get_html():
            if gatherDetails.isRetroGame:
                print(
                    f"PS2 game previously mounted, keeping RPC active and "
                    f"waiting {prepWork.config['wait_seconds']} seconds"
                )
                sleep(prepWork.config["wait_seconds"])
            else:
                print(
                    f"PS3 not found on network, closing RPC and hibernating "
                    f"{prepWork.config['hibernate_seconds']} seconds."
                )
                if not closed:
                    prepWork.RPC.clear()
                prepWork.RPC.close()
                closed = True
                sleep(float(prepWork.config["hibernate_seconds"]))
        else:
            print("")
            if closed:
                prepWork.connect_to_discord()
                timer = time()
                closed = False

            if prepWork.config["show_temp"] or prepWork.config["temp_on_tooltip"]:
                gatherDetails.get_thermals()
                if gatherDetails.thermalData:
                    gatherDetails.thermalData = _THERMAL_RE.sub(
                        "", gatherDetails.thermalData
                    )

            gatherDetails.decide_game_type()

            if gatherDetails.name:
                gatherDetails.name = _THERMAL_RE.sub("", gatherDetails.name)

            if prepWork.config["show_only_in_game"] and not gatherDetails.isInGame:
                print("On XMB, skipping RPC update (show_only_in_game)")
                sleep(prepWork.config["wait_seconds"])
                continue

            if gatherDetails.isRetroGame:
                playing_on = "Playing PS1/2 on PlayStation®3 system"
            elif gatherDetails.isInGame:
                playing_on = "Playing on PlayStation®3 system"
            else:
                playing_on = "On PlayStation®3 XMB"

            if prepWork.config["temp_on_tooltip"]:
                large_text = gatherDetails.thermalData or gatherDetails.titleID
            else:
                large_text = gatherDetails.titleID

            rpc_kwargs = {
                "large_image": gatherDetails.image,
                "large_text": large_text,
                "start": timer,
            }
            if prepWork.config["use_appname"]:
                rpc_kwargs["details"] = gatherDetails.name
                rpc_kwargs["state"] = gatherDetails.thermalData or playing_on
            else:
                rpc_kwargs["name"] = gatherDetails.name
                rpc_kwargs["details"] = gatherDetails.thermalData
                rpc_kwargs["state"] = playing_on

            try:
                prepWork.RPC.update(**rpc_kwargs)
            except (InvalidPipe, InvalidID):
                prepWork.RPC.close()
                prepWork.connect_to_discord()
            except ServerError as e:
                print(f"Discord rejected the RPC update: {e}")
                print("If you have more than one instance of PS3-RPC running, please close the others.")

            sleep(prepWork.config["wait_seconds"])


if __name__ == "__main__":
    main()
