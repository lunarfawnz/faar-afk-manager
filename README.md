# FAAR Manager

A multi-account launcher and AFK helper for **Fish an Anime RNG** on Roblox (Windows only).

Run several Roblox clients side by side, each signed in to its own account, and let them handle
the boring parts on their own: rebirths, the Boost shop restock, Selene's roaming shop, the
Hallow's Eve event, Anti-AFK and rejoining after a server shutdown.

> [!WARNING]
> Running macros and alt accounts goes against Roblox's Terms of Use, so any account you use this on
> carries a ban risk. Use it at your own risk. The app only sends mouse clicks and key presses like a
> person would; it does not inject into, read the memory of, or modify Roblox in any way.

## Features

- **Multi-instance**: run as many clients as your PC handles, no separate multi-instance tool needed
- **Cookie sign-in**: each account signs in with its `.ROBLOSECURITY` cookie, stored encrypted to your Windows user
- **Private servers**: paste a private server link and every account joins it
- **Auto rebirth** on a timer, including the rebirth 250 SACRIFICE pop-up (pauses and waits for you)
- **Boost shop**: buys every cash/gem potion at each 5-minute restock, skipping `NO STOCK!` items
- **Selene shop**: buys everything buyable when she shows up, then visits her on every other account in turn
- **Hallow's Eve**: holds your character during the event and moves to the next one once it gets the Dracula mutation
- **Anti-AFK**: a little mouse movement and a few clicks every 14 minutes
- **Auto-rejoin**: reopens an account after `Disconnected` (error 256, 277...) and closes the Welcome Back pop-up
- **Window layout**: tiles the alts on any monitor and maximizes the ones you don't tile
- **Performance**: low graphics (allowlisted Fast Flags only), lower CPU priority and memory trimming for alts

### It never spends Robux

- Only buttons with the **cash** or **gem** icon are ever clicked. Anything with a Robux icon is skipped.
- Before every single click the app checks for Roblox's purchase pop-up. If one is open, nothing gets
  clicked except its **X**. The Buy button is never touched.
- The Welcome Back "triple your cash" offer is closed with its X, never YES.

## Requirements

- Windows 10 or 11
- [Python 3.10+](https://www.python.org/downloads/) (tick **"Add python.exe to PATH"** while installing)
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) for reading on-screen text (stock
  labels, the event banner, the Disconnected box). The English language data is included in `tessdata/`.

## Getting started

1. Download this repo (**Code → Download ZIP**) and unzip it, or `git clone` it.
2. **Close every Roblox window.** The app has to start before Roblox for multi-instance to work.
3. Double-click **`run.bat`**. The first run installs the Python packages it needs (about a minute),
   then opens the app and closes its own console window.
4. From then on you can open **`FAAR Manager.pyw`** directly. Run `run.bat` again after updating in
   case something new needs installing.

The sidebar shows **● Multi-instance on** in green once it's working. If it's red, close every
Roblox window and it turns green by itself.

## Usage

### Add accounts

**Accounts → + Add account**, then paste the account's `.ROBLOSECURITY` cookie (the dialog shows
where to find it). Use a fresh browser login for each account and don't click **Log out** afterwards,
or the cookie stops working.

> [!CAUTION]
> The cookie **is** your login. It's saved in `data/accounts.json`, encrypted with Windows DPAPI so it
> only works for your Windows user, and it's only ever sent to roblox.com. Never share it, and never
> commit the `data/` folder (it's in `.gitignore`).

### Launch and start

1. Click **Launch all**, or **Launch** on a single account.
2. Turn features on per account with the switches on its card.
3. Press **▶ Start** in the sidebar.

| Key | Action |
| --- | --- |
| `F8` | Pause / resume |
| `F9` | Stop |

Everything the app does shows up in **Activity log** and in `data/log.txt`.

### Where to stand

- **Boost shop** accounts stand next to the boosts stand so its `Boosts Store` prompt is showing.
- **Selene** accounts stand at the spot where her prompt appears when she arrives.

The game only draws the window that's in front, so only your focused window (usually your main) can
spot Selene. When it does, that account shops first, then every other account with Selene on is
brought forward one at a time, checked and shopped, and focus goes back to your main.

### Hallow's Eve

The hotbar must be full: slot 1 is the rod, your characters go from **First character slot** to
**Last character slot**, then potions. While the event is on, the app holds the current character;
when it shows the Dracula mutation it switches to the next slot, and after the last one it puts it
away. It reads small text, so it works best on a full-size window.

### Checking what the app sees

**⋯ → Test detection** on an account card shows what the app finds in that window right now:
Selene's or the Boosts Store prompt, shop buttons and their stock, the rebirth menu, the held hotbar
slot and whether Hallow's Eve is on.

## Settings

All settings are on the **Settings** page.

| Section | What you can change |
| --- | --- |
| Windows | Monitor for tiled windows, auto-fit size, maximizing untiled windows and which monitor they go on |
| Game | Game or private server link (both `privateServerLinkCode=` and `share?code=` links work) |
| Rebirth | How often to try a rebirth |
| Boost shop | Restock interval, lining up with the clock (:00, :05, :10...), delay after restock |
| Selene | How often to look for her, cooldown after a visit, how long to check each account in a round |
| Buying | Max clicks per item (stops early at `OUT OF STOCK` / `NO STOCK!` / `OWNED`) |
| Hallow's Eve | Character slots, the mutation to wait for |
| Performance | Low graphics, lower priority and memory trim for alts |
| General | Anti-AFK interval, Disconnected check interval, idle time before acting |

## Running it next to your own script

Only one window can have the mouse and keyboard at a time. If you drive your main with your own
script, copy [`for_other_scripts/fish_input_lock.py`](for_other_scripts/fish_input_lock.py) next to
it and wrap each action:

```python
from fish_input_lock import my_turn

with my_turn():
    pyautogui.press("2")
```

While your script is inside `with my_turn():` the app waits, and the other way round. Keep each block
short (one action or one shop visit). If your main is added in the app, turn its **Tile** switch off so
it's never moved.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| Sidebar says multi-instance is off | Close every Roblox window (check Task Manager for `RobloxPlayerBeta`) |
| `Not enough cash to rebirth yet` | Normal: the Robux "Skip Rebirth" pop-up was closed, it tries again next time |
| Account shows **Waiting for you** | The SACRIFICE pop-up (rebirth 250) is open; answer it yourself and it resumes |
| Stock not read / Hallow's Eve never starts | Tesseract isn't installed or wasn't found |
| Low graphics didn't change anything | Restart the Roblox clients; it applies when a client starts |
| The app closed without a message | Look in `data/crash.log` |

## Project layout

```
FAAR Manager.pyw          start the app without a console
run.bat                   installs packages, then starts the app
main.py
app/
  gui.py                  the window (customtkinter)
  engine.py               automation loop and actions
  builtin.py              on-screen detection (template matching + OCR)
  builtin_templates.py    reference images
  hallows.py              Hallow's Eve detection
  purchase.py             Robux pop-up detection
  roblox.py               sign-in and launching
  route.py                after-rejoin handling
  optimize.py             performance settings
  storage.py              accounts and settings
  win.py                  Windows input, windows and capture
for_other_scripts/
  fish_input_lock.py
tessdata/eng.traineddata  Tesseract English data
```

## Disclaimer

Not affiliated with Roblox Corporation or the developers of Fish an Anime RNG.
