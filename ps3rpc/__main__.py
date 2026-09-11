import contextlib
import io
from time import sleep, time

from pypresence import InvalidID, InvalidPipe, ServerError

from ps3rpc.config import _THERMAL_RE, SEPARATOR, PrepWork
from ps3rpc.scraper import GatherDetails
from ps3rpc.ui import C, clear, err, warn

_EVENT_MARKERS = ("✓", "✗", "⚠")


def _print_header():
    print(f"{C.BOLD}{C.CYAN}PS3-RPC{C.RESET}  {C.GRAY}(Ctrl+C to stop){C.RESET}\n")


def _print_gather_output(captured):
    """Split a chunk of captured scraper output into one-off events"""
    lines = [line for line in captured.splitlines() if line.strip()]
    transient = [line for line in lines if any(m in line for m in _EVENT_MARKERS)]
    steady = [line for line in lines if line not in transient]

    if transient:
        for line in transient:
            print(line)
        print(f"{C.GRAY}{SEPARATOR.rstrip()}{C.RESET}")
    for line in steady:
        print(line)


def main():
    prepWork = PrepWork()
    try:
        prepWork.read_config()
    except KeyboardInterrupt:
        print()
        warn("Setup cancelled — nothing was saved. Exiting.")
        return

    if not str(prepWork.config.get("ip") or "").strip():
        print()
        err("No reachable PS3 was configured, so PS3-RPC can't start.")
        print(
            f"{C.GRAY}Re-run once your PS3 is on with webMAN MOD running, or edit "
            f'the "ip" value in {prepWork.config_path} directly.{C.RESET}'
        )
        return

    try:
        prepWork.connect_to_discord()
        gatherDetails = GatherDetails(prepWork)
        timer = int(time()) if prepWork.config["show_timer"] else None
        run_loop(prepWork, gatherDetails, timer)
    except KeyboardInterrupt:
        print(f"\n{C.GRAY}Shutting down PS3-RPC.{C.RESET}")
        if prepWork.RPC is not None:
            try:
                prepWork.RPC.clear()
                prepWork.RPC.close()
            except Exception:
                pass


def run_loop(prepWork, gatherDetails, timer):
    closed = False
    show_timer = prepWork.config["show_timer"]
    accurate_timer = prepWork.config["accurate_timer"]
    prev_game = None
    while True:
        # this is slow!
        html_ok = gatherDetails.get_html()

        if not html_ok:
            clear()
            _print_header()
            if gatherDetails.isRetroGame:
                print(
                    f"{C.GRAY}PS2 game previously mounted, keeping RPC active and "
                    f"waiting {prepWork.config['wait_seconds']} seconds{C.RESET}"
                )
                sleep(prepWork.config["wait_seconds"])
            else:
                warn(
                    f"PS3 not found on network, closing RPC and hibernating "
                    f"{prepWork.config['hibernate_seconds']} seconds."
                )
                if not closed:
                    prepWork.RPC.clear()
                prepWork.RPC.close()
                closed = True
                sleep(float(prepWork.config["hibernate_seconds"]))
        else:
            if closed:
                prepWork.connect_to_discord()
                timer = int(time()) if show_timer else None
                prev_game = None
                closed = False

            gather_buf = io.StringIO()
            with contextlib.redirect_stdout(gather_buf):
                if prepWork.config["show_temp"] or prepWork.config["show_tooltip"]:
                    gatherDetails.get_thermals()
                if prepWork.config["show_tooltip"] and prepWork.config["show_firmware"]:
                    gatherDetails.get_firmware()

                gatherDetails.decide_game_type()
            gathered_output = gather_buf.getvalue()

            if gatherDetails.name:
                gatherDetails.name = _THERMAL_RE.sub("", gatherDetails.name)

            if show_timer:
                game = gatherDetails.titleID or gatherDetails.name
                if game != prev_game:
                    timer = int(time())
                    if accurate_timer and gatherDetails.isInGame:
                        session_seconds = gatherDetails.get_session_seconds()
                        if session_seconds is not None:
                            timer = int(time()) - session_seconds
                    prev_game = game

            clear()
            _print_header()
            _print_gather_output(gathered_output)

            if prepWork.config["show_only_in_game"] and not gatherDetails.isInGame:
                print(
                    f"{C.GRAY}On XMB, skipping RPC update "
                    f"(show_only_in_game){C.RESET}"
                )
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

            if prepWork.config["show_tooltip"]:
                large_text = gatherDetails.build_tooltip() or gatherDetails.titleID
            else:
                large_text = gatherDetails.titleID

            rpc_kwargs = {
                "large_image": gatherDetails.image,
                "large_text": large_text,
                "start": timer,
            }
            if gatherDetails.searchURL and prepWork.config["search_button"]:
                rpc_kwargs["buttons"] = [
                    {"label": "Search game", "url": gatherDetails.searchURL}
                ]
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
                err(f"Discord rejected the RPC update: {e}")
                print(
                    f"{C.GRAY}If you have more than one instance of PS3-RPC "
                    f"running, please close the others.{C.RESET}"
                )

            sleep(prepWork.config["wait_seconds"])


if __name__ == "__main__":
    main()
