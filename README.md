# PS3-RPC
A program to display what game you're playing on homebrewed PS3 via your PC!

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/boysaremoe) [![pypresence](https://img.shields.io/badge/using-pypresence-00bb88.svg?style=for-the-badge&logo=discord&logoWidth=20)](https://github.com/qwertyquerty/pypresence)

## Display Examples

| Default | `short_console_name: False` | `show_temp: True` |
|:-:|:-:|:-:|
| <img src="https://github.com/zydezu/PS3-RPC/blob/main/img/default2.png?raw=true"> | <img src="https://github.com/zydezu/PS3-RPC/blob/main/img/default.png?raw=true"> | <img src="https://github.com/zydezu/PS3-RPC/blob/main/img/default3.png?raw=true"> |


## Usage

### Requirements
* PS3 with either HFW&HEN, or CFW installed
* PS3 with [webmanMOD](https://github.com/aldostools/webMAN-MOD/releases) installed 
* PS3 and PC on the same network/internet connection
* Discord installed and open on the PC running the script
* Administrator permissions on the PC
* A Python 3.9 interpreter installed on the PC if you aren't using the .exe

### Windows
* Download the `PS3RPC_Windows_*.exe` from the [latest release](https://github.com/zydezu/PS3-RPC/releases/latest), x64 for 64-bit device or ARM64 for an ARM64 device

#### Installing as a Windows service (optional)
Download [NSSM](https://nssm.cc/release/nssm-2.24.zip) and run `nssm install <service name ie. ps3rpc>` to install PS3RPC as a Windows service.
WARNING: PS3RPC.exe must be in a location that won't change ie. C:\ps3rpc\PS3RPC.exe

> [!NOTE]
> The executable file will very likely be flagged as a virus on your computer due to `pyinstaller` being used to compile it.
> As far as I know, there is nothing I can do to fix this.

### Linux 

* Download the `PS3RPC_Linux_*` from the [latest release](https://github.com/zydezu/PS3-RPC/releases/latest), x64 for a 64-bit system or ARM64 if you're using an ARM system (like a Raspberry Pi).

You can also download and run script manually, like this:
```bash
# Clone the GitHub repository under the user folder
git clone https://github.com/zydezu/PS3-RPC ~/PS3-RPC
# Run the start script
cd ~/PS3-RPC && ./start.py
```

From there you can run the script via double clicking on the file within your file explorer, and clicking on "Run (in terminal)".

Alternatively, you can run the command via the terminal by running `cd ~/PS3-RPC && ./start.py` again.

#### Installing as a systemd service (optional)
<details>
  <summary>If you would like the script to start on device boot, after the first run, run the following commands in your terminal:</summary>
<br>
	
```bash
# Creates the user service folder if it doesn't exist yet, and the user systemd env folder
mkdir -p ~/.config/systemd/user ~/.config/environment.d/
# Include local binaries in your systemd user environment
# (we need this so systemd can find the 'uv' executable)
bash -c 'echo "
# Adds ~/.local/bin to PATH so systemd services can find user-installed binaries
PATH=${HOME}/.local/bin:
" >> ~/.config/environment.d/90-path.conf'

# Creates a systemd .service file in the user service folder that runs the script
bash -c 'echo "
[Unit]
Description=Enables PS3-RPC
Wants=network-online.target
After=network-online.target

[Service]
ExecStart=/usr/bin/python3 $HOME/PS3-RPC/start.py
Restart=on-failure
StandardOutput=journal
StandardError=journal
WorkingDirectory=$HOME/PS3-RPC

[Install]
WantedBy=default.target
" > ~/.config/systemd/user/PS3-RPC.service'
# Reloads the systemd service to recognize the new service
systemctl --user daemon-reload
# Enables the service and starts it
systemctl --user enable --now PS3-RPC
# Make it clear that something happened
echo "Finished adding user service for PS3-RPC."
echo "You can check the status of the service with `systemctl --user status PS3-RPC`"
```

In order to check the health of the service, you can run `systemctl --user status ps3rpc`<br>
For more depth logs you can use `journalctl --user -xeu ps3rpc`
</details>

## Limitations
* __A PC must be used to display presence, there is no way to install and use this script solely on the PS3__
* The script relies on webmanMOD, and a major change to it will break this script, please submit a bug report when this happens about the updated version of webman so the script can be updated
* PSX and PS2 game name depends on the name of the file
* PSX and PS2 game detection will **not** work on PSN .pkg versions because webman cannot show those games as mounted/playing.
* PS2 ISO game detection can be inconsistent, varying on degree of consistency by the value of "Refresh time."

## Additional Information

### GameTDB
This script can utilise images provided by [GameTDB](https://www.gametdb.com/), if you are able, consider supporting the service.

### External config file
PS3-RPC makes use of an external config file named `ps3rpcconfig.json` to store settings. 

| Key | Default | Description |
|---|---|---|
| `ip` | `""` | Your PS3's IP address |
| `client_id` | `1512043386327007253` | Discord developer application ID to send presence data to |
| `wait_seconds` | `30` | How often (in seconds) to refresh presence data (minimum 15) |
| `show_temp` | `false` | Show PS3 CPU/RSX temperature in the presence |
| `retro_covers` | `false` | Use game-specific covers for PS1/PS2 games |
| `hibernate_seconds` | `600` | How long (in seconds) to wait before retrying when PS3 is unreachable |
| `ip_prompt` | `true` | Re-prompt for IP if the PS3 can't be reached on startup |
| `show_timer` | `true` | Display time elapsed in the presence |
| `prefer_dev_app` | `false` | Use Discord dev app images instead of GameTDB covers |
| `use_appname` | `false` | Show game name as the activity details line instead of the app name |
| `short_console_name` | `true` | Show "PS3" instead of "PlayStation®3 system" in the presence |
| `show_only_in_game` | `true` | Only update presence when a game is running (hide on XMB) |
| `temp_on_tooltip` | `true` | Show temperature when hovering over the large image in the activity |

### Using your own images
If you'd like to control what images are used for each game, you must create a Discord Developer Application over at the [Discord Developer Portal](https://discord.com/developers/applications).

Once created, copy the application ID from the Developer Portal and paste it into the external `ps3rpcconfig.json`, replacing the value of `client_id`.

You are now able to upload your own assets in the Developer Portal under `Rich Presence > Art Assets`. Note that the name of the asset uploaded must be the lowercase title ID provided in the script's output. (e.g. `abcd12345`)
