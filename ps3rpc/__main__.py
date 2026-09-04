from time import sleep, time

from pypresence import InvalidID, InvalidPipe, ServerError

from ps3rpc.config import _THERMAL_RE, PrepWork
from ps3rpc.scraper import GatherDetails


def main():
    prepWork = PrepWork()
    try:
        prepWork.read_config()
    except KeyboardInterrupt:
        print("\nSetup cancelled — nothing was saved. Exiting.")
        return

    if not str(prepWork.config.get("ip") or "").strip():
        print(
            "\nNo reachable PS3 was configured, so PS3-RPC can't start.\n"
            "Re-run once your PS3 is on with webMAN MOD running, or edit the\n"
            f'"ip" value in {prepWork.config_path} directly.'
        )
        return

    try:
        prepWork.connect_to_discord()
        gatherDetails = GatherDetails(prepWork)
        timer = int(time()) if prepWork.config["show_timer"] else None
        run_loop(prepWork, gatherDetails, timer)
    except KeyboardInterrupt:
        print("\nShutting down PS3-RPC.")
        if prepWork.RPC is not None:
            try:
                prepWork.RPC.clear()
                prepWork.RPC.close()
            except Exception:
                pass


def run_loop(prepWork, gatherDetails, timer):
    closed = False
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
                timer = int(time())
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

            console = (
                "PS3"
                if prepWork.config["short_console_name"]
                else "PlayStation®3 system"
            )
            if gatherDetails.isRetroGame:
                playing_on = f"Playing PS1/2 on {console}"
            elif gatherDetails.isInGame:
                playing_on = f"Playing on {console}"
            else:
                playing_on = f"On {console} XMB"

            if prepWork.config["temp_on_tooltip"]:
                large_text = gatherDetails.thermalData or gatherDetails.titleID
            else:
                large_text = gatherDetails.titleID

            rpc_kwargs = {
                "large_image": gatherDetails.image,
                "large_text": large_text,
                "start": timer,
            }
            temp_line = (
                gatherDetails.thermalData if prepWork.config["show_temp"] else None
            )
            if prepWork.config["use_appname"]:
                rpc_kwargs["details"] = gatherDetails.name
                rpc_kwargs["state"] = temp_line or playing_on
            else:
                rpc_kwargs["name"] = gatherDetails.name
                rpc_kwargs["details"] = temp_line
                rpc_kwargs["state"] = playing_on

            try:
                prepWork.RPC.update(**rpc_kwargs)
            except (InvalidPipe, InvalidID):
                prepWork.RPC.close()
                prepWork.connect_to_discord()
            except ServerError as e:
                print(f"Discord rejected the RPC update: {e}")
                print(
                    "If you have more than one instance of PS3-RPC running, please close the others."
                )

            sleep(prepWork.config["wait_seconds"])


if __name__ == "__main__":
    main()
