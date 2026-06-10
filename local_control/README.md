# Local Control — Lost-Remote Recovery

Direct software control of your Devialet Expert over your LAN. No cloud, no
Home Assistant, no AWS — just UDP packets to the amp. This is the fastest way
to prove software control works.

Both tools auto-discover the amp by listening for its UDP status broadcasts
(the amp sends them roughly every 300 ms, even in standby).

## 1. CLI — prove it works first

Zero dependencies. Run from this directory:

```bash
# Step 1: passive test — proves discovery and packet parsing (sends nothing)
python3 devialet_cli.py status

# Step 2: first active test — audible, safe, instantly reversible
python3 devialet_cli.py mute
python3 devialet_cli.py unmute

# Step 3: small volume change
python3 devialet_cli.py vol up
python3 devialet_cli.py vol 120          # 0-175 integer scale
python3 devialet_cli.py vol -- -30.5db   # or set in dB directly

# Step 4: source switching
python3 devialet_cli.py source "Optical 1"   # names from 'status' output

# Step 5: power
python3 devialet_cli.py off
python3 devialet_cli.py on

# Bonus: stream live state changes
python3 devialet_cli.py watch
```

Each command waits for the amp's next status broadcast and prints the
confirmed new state — so you know the command actually took effect.

## 2. Menu bar app (macOS)

```bash
pip3 install -r requirements.txt
python3 devialet_menubar.py
```

A `◎` icon appears in the menu bar showing the current volume in dB
(or `off` / `muted` / `—` while searching). The dropdown has:

- Device name and IP
- Turn On / Turn Off
- Mute / Unmute
- Volume Up / Down (⌘+ / ⌘- while the menu is open) and a volume slider
- Source submenu with the active input checked

Volume is capped at -10 dB (175/255) in software to protect your speakers,
same as the Home Assistant integration.

### Run at login (optional)

Simplest approach — Automator: create an Application that runs the shell
script `cd /path/to/repo/local_control && /usr/bin/python3 devialet_menubar.py`,
then add it to System Settings → General → Login Items.

## Troubleshooting

- **"No Devialet found"**: the amp must be on the same subnet/VLAN. It
  broadcasts on UDP port 45454 — check firewalls (macOS will prompt to allow
  incoming connections for Python the first time; click Allow).
- **Port conflict**: only one listener can bind UDP 45454 per machine. Don't
  run the CLI, menu bar app, Home Assistant integration, or Alexa bridge on
  the same machine at the same time.
- **Commands ignored**: commands go to UDP port 45455 on the amp's IP. Each
  command is sent twice for reliability, but UDP has no delivery guarantee —
  retry if needed.
