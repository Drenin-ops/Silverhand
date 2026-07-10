# Silverhand — Tablet Command Center

Two ways to connect this tablet (`.86`) to the network command monitor
running on the Main PC (`.131`). Both just open the monitor dashboard at
`http://<pc-ip>:7477/monitor`.

## `command-center.html` — works on any tablet (Android / iPad / Windows)

1. Copy this file onto the tablet (email it, USB, cloud, or serve it).
2. Open it in the tablet's browser.
3. Confirm the **Host IP** (default `192.168.1.131`) and tap **CONNECT**.
4. Tick **Auto-connect next time** to skip the form on future opens.
5. Use the browser's **"Add to Home Screen"** so it launches like an app.

To get back to the editable form when auto-connect is on, open it with
`command-center.html?stay=1`.

## `command-center.bat` — Windows tablets only

Double-click it. It opens the dashboard in a borderless app window
(Edge/Chrome) or your default browser. Edit `HOST` / `PORT` at the top if
your Main PC's IP differs. For a locked-down fullscreen display, switch
`--app=` to `--kiosk` (see the comment near the bottom of the file).

## Requirements

- Silverhand must be running on the Main PC, and its GUI server must be
  reachable on the LAN — that means `gui.host` is `0.0.0.0` in `agent.json`
  (already set) and Windows Firewall allows inbound TCP **7477**.
- Both devices on the same network. Adjust the IP if your subnet isn't
  `192.168.1.x`.
