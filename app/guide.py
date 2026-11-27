GUIDE = [
    ("Start here", [
        "FAAR Manager opens several Roblox windows, each signed in to its own account, and handles the boring "
        "parts of Fish an Anime RNG for you: rebirths, the Boost shop, Selene's shop, Hallow's Eve, staying "
        "online and rejoining.",
        "It only moves the mouse and presses keys like a person would. It never spends Robux: it only clicks "
        "cash or gem buttons, and any Robux pop-up is closed with its X, never Buy.",
        "Macros and alt accounts go against Roblox's rules, so there's always some ban risk. Use it at your own risk.",
    ]),
    ("1. First launch", [
        "Close every Roblox window before opening FAAR Manager. It has to start first so several Roblox "
        "windows can run at once.",
        "The sidebar shows '● Multi-instance on' in green when that works. If it's red, close every Roblox "
        "window and it turns green by itself.",
        "Your accounts, settings and logs are kept in %LOCALAPPDATA%\\FAAR Manager, so updating the app never "
        "loses them.",
    ]),
    ("2. Add your accounts", [
        "Accounts → + Add account, then paste that account's .ROBLOSECURITY cookie. The dialog shows where to "
        "find it in your browser.",
        "Log in to each account in a fresh browser session and don't press Log out afterwards, or the cookie "
        "stops working.",
        "The cookie IS your login. It's stored encrypted so only your Windows user can read it, and it's only "
        "ever sent to roblox.com. Never share it with anyone.",
    ]),
    ("3. Pick the game", [
        "Settings → Game: paste a normal game link or a private server link (both the privateServerLinkCode= "
        "kind and the share?code= kind work). Every account joins it.",
    ]),
    ("4. Launch and start", [
        "Click Launch all, or Launch on one account. Accounts start a few seconds apart and load side by side. "
        "While one is loading, its button says Cancel.",
        "Each window is matched to its account by reading Roblox's own log, so it doesn't matter which window "
        "opens first. If a window still isn't picked up, use ⋯ → Link an open Roblox window.",
        "Turn features on per account with the switches on its card, then press ▶ Start in the sidebar.",
        "F8 pauses or resumes. F9 stops. Everything the app does is written in Activity log.",
    ]),
    ("Where to stand", [
        "Boost shop accounts: next to the boosts stand, so its 'Boosts Store' prompt shows.",
        "Selene accounts: where her prompt appears when she arrives.",
        "Hallow's Eve accounts: anywhere you fish.",
    ]),
    ("Boost shop", [
        "Every 5-minute restock, it opens the Boost shop and buys the potions you switched on in Settings → "
        "Boost shop items. Items are recognised by colour, so any game language works.",
    ]),
    ("Selene", [
        "Selene is in town for 5 minutes from every :00 and :30. The app only looks for her then, and doesn't "
        "start a new visit in her last 50 seconds so nobody gets cut off.",
        "When one account spots her, it shops first, then every other account with Selene on is visited one "
        "at a time. Pick what to buy in Settings → Selene items. Abilities are never bought, and the "
        "character she sometimes sells is skipped unless you switch it on.",
        "Her shop closes as soon as her bottom row (Sinister and Lucrative Realization) is done.",
    ]),
    ("Auto rebirth", [
        "On a timer, it reads your cash and the rebirth cost. If you can't afford it yet, the menu isn't even "
        "opened. When you can, it presses Rebirth! and remembers the next cost.",
        "At rebirth 250 the SACRIFICE pop-up appears. The app never answers it: that account pauses until you "
        "close it or take it there yourself.",
    ]),
    ("Hallow's Eve", [
        "Settings → Hallow's Eve → Character slots: list the hotbar slots with characters, like 2-4 or 3,4,6,9 "
        "(0 = slot 10). The hotbar doesn't have to be full.",
        "When the event starts, it holds the first character with no mutation yet. When it gets Dracula it's "
        "counted and the next one is held. Any other mutation swaps to the next one straight away.",
        "It puts the character away a few seconds before the timer ends (more when several accounts are "
        "holding), so a last-second catch can't mutate it.",
        "Every event is named in the log (Hallow's Eve, Heaven's Collide, Solar, Hell's Gates, Slime Rain). "
        "Only Hallow's Eve holds a character; during anything else, or no event, a held character is put away "
        "within about 2 seconds.",
        "A counter is kept per account: events since your last Dracula, total events and total Draculas.",
        "It never presses a slot twice in a row unless it can clearly read the hotbar, and if a press changes "
        "nothing, that slot is left alone for 15 minutes.",
    ]),
    ("Auto ability", [
        "Turn Auto ability on for an account, then Settings → Auto ability → Mark ability button: hover the "
        "ability button in a Roblox window and keep the mouse there for 5 seconds.",
        "It then presses the key (V by default) whenever the button is green. If it hasn't looked ready for "
        "5 minutes, the log tells you to mark it again.",
    ]),
    ("Staying online", [
        "Anti-AFK moves the mouse and clicks when an account hasn't had any real input for a while, so Roblox "
        "doesn't kick it after 20 minutes.",
        "Rejoin: after 'Disconnected' (error 256, 277...) or if Roblox closes or crashes, the account is "
        "reopened and the Welcome Back pop-up is closed with its X. It retries if the server isn't back yet.",
        "Join Event and Daily Rewards pop-ups are cleared by themselves (Join Event with its X, Daily Rewards "
        "by pressing Claim).",
    ]),
    ("Saving CPU and RAM", [
        "Low graphics and lower priority for alts are on the Settings page.",
        "Cap Roblox's FPS: writes Roblox's own Maximum Frame Rate before each launch (30 is a good AFK value). "
        "Set it back to 0 to restore what Roblox had.",
        "Restart each Roblox every N hours (off by default) frees the memory Roblox piles up over long runs.",
        "Restart Roblox when the PC runs low on RAM (off by default) restarts the biggest Roblox before "
        "Windows starts crashing them.",
    ]),
    ("Phone remote", [
        "Control everything from your phone and get notifications (Dracula, pop-ups that need you, "
        "disconnects, automation stopped). Open 📱 Phone remote and follow its 4 steps: install Tailscale on "
        "the PC and phone, set a PIN, turn it on, then open the link on your phone and add it to your home "
        "screen.",
        "It only works inside your own Tailscale network and needs your PIN. Your Roblox logins never leave "
        "this PC.",
    ]),
    ("Updates", [
        "The app checks for a new version when it opens. Click 'Update to v…' in the sidebar when it shows up; your "
        "accounts and settings are kept.",
    ]),
    ("Something isn't working?", [
        "⋯ → Test detection on an account card shows what the app sees in that window right now: prompts, "
        "shop buttons, the rebirth menu, the held hotbar slot and which event is showing.",
        "Small windows are harder to read. If something is missed, make that window bigger.",
        "Multi-instance red: close every Roblox window, wait a few seconds.",
        "An account keeps getting kicked: make sure Anti-AFK is on for it.",
        "Selene never found: the account must be standing where her prompt appears, and the PC clock must be "
        "right (she arrives at :00 and :30).",
        "Still stuck? Send the Activity log (or log.txt in %LOCALAPPDATA%\\FAAR Manager) to whoever helps you.",
    ]),
]
