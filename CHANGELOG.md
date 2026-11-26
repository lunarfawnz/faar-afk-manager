# Changelog

## v1.3.0

### Phone remote (new)
- **Control FAAR Manager from your phone.** Install it to your home screen like an app: start, pause and stop automation; launch, close and rejoin accounts; flip each account's switches; see a screenshot of any Roblox window; see the Hallow's Eve counter; and read the activity log.
- **Notifications on your phone** for: Dracula got, things that need you (SACRIFICE pop-up, a stuck Robux pop-up, rejoins failed or stopped), disconnects and rejoins, and automation stopped or the app crashed. Each one can be switched off.
- **Private by design.** It runs over your own Tailscale network (free), so nothing is opened to the internet. Phones need a PIN, 5 wrong PINs lock sign-in for 5 minutes, and you can sign out every phone from the PC. Roblox logins never leave your PC.
- Set it up from the new **📱 Phone remote** page: install Tailscale on the PC and phone, set a PIN, turn it on, click **Set up Tailscale link**, open the link on your phone and add it to your home screen. iPhone needs iOS 16.4+ for notifications.

## v1.2.1

### Hallow's Eve
- **The hotbar no longer has to be full.** "First/Last character slot" is replaced by **Character slots**: list them like `2-4` or `3,4,6,9` (`0` = slot 10). Your old range is filled in automatically.
- **Skips characters that already have a mutation.** When the event starts it holds the first character with no mutation yet and skips potions and mutated ones.
- **Moves on as soon as a character gets a mutation.** Dracula (or the mutation you set) is counted; any other mutation swaps to the next unmutated character right away.
- **Puts the character away 4 seconds before the event ends.** It reads the event's countdown so a last-second catch can't mutate it (needs a window about 1500 px wide or bigger to read the timer; smaller windows put it away when the banner goes). Adjustable in Settings, 0 = off.
- **Wrong-event failsafe.** If two characters get mutations Hallow's Eve never gives, it stops, puts the character away and doesn't count that event.
- **No more accidental double presses.** Pressing a slot toggles it, so after a press it now waits until the hotbar shows the change twice in a row before doing anything else, and only presses again after a few seconds with no change, ending with a long press if the game keeps missing it.
- **Stray characters.** A character left in hand when no event is running is put away only after two looks agree, so one misread can never pick a character up.
- **Event counter.** Saved per account: events since your last Dracula, total events and total Draculas. Every event ends with a log line saying what happened to each character it held.

### Low FPS
- New **Roblox FPS limit** setting. If you cap Roblox's FPS to save CPU, set it here and every key press and click (hotbar, auto ability, shops) is held long enough for the game to notice it.

### Launching
- **Launch all is much faster.** Accounts start a few seconds apart and load side by side instead of waiting for each window to open.
- **Windows are matched to the right account** even when they open out of order, so you no longer get stuck on "Waiting for window".
- **Cancel.** While an account is loading, its button turns into **Cancel** so you can skip it and move on.
- "Seconds between launches" now defaults to 6. If you still have the old 12, lower it in Settings.

### Shops
- **Scrolling through the Boost and Selene shops is at least twice as fast**, without skipping rows.
- **Selene's shop closes as soon as her bottom row is done** (Sinister and Lucrative Realization) instead of scrolling into empty space.

### Auto-rejoin
- **Much more reliable after "Disconnected" (error 256, 277...)**, including on small tiled windows. It now also reads Roblox's own log files to spot disconnects.
- **Keeps retrying if the server isn't back yet** (5 tries over about 5 minutes) instead of giving up.
- New setting: **Also rejoin if Roblox closes or crashes** (on by default). Use the app's Close button to close an account for good.
- An account stops rejoining after 5 rejoins in 30 minutes, so it can't get stuck in a loop.
- When every account gets kicked at once, they rejoin one at a time.

### Other
- Fixed auto-update failing with "Failed to load Python DLL" when the app restarted itself.
- `build_exe.bat` now keeps all its build files in `%LOCALAPPDATA%\FAAR Manager\build` instead of the app folder.

**Updating with the built-in updater from an older version:** if you see "Failed to load Python DLL" once after updating, just open FAAR Manager again. It's fixed from this version on.

## Standalone .exe

- **Build to a single `.exe`.** `build_exe.bat` packs the whole app into one `dist\FAAR Manager.exe`
  you can upload as a GitHub release. No Python install needed to run it.
- **Tesseract is bundled inside the exe.** People who download your release don't have to install
  anything else — the text reader and its English data are packed in. (You only need Tesseract
  installed on the PC you build on.)
- **New app icon.** A fish-and-sparkle icon on the exe, the window and the taskbar, replacing the
  default Python icon.
- **Keeps its data next to the exe.** Accounts, settings and logs live in a `data` folder beside the
  exe, so it carries over between updates.

## Smoother, faster UI

- **Faster to open.** Only the Accounts page is built at startup; the other pages and the graphics
  setup now load quietly just after the window appears, so it opens quickly.
- **No more black flash when switching pages.** Pages are kept loaded and switched instantly instead
  of being torn down and rebuilt each time.
- **Less flicker.** Account cards only redraw when something actually changes, instead of every
  second.

## Other languages

- **Stock reading now works in any language.** The app reads the in-stock count (the "xN" tag, like
  `x2 Left!` or `x1 restantes!`) instead of English words, so it works whatever language the game is
  in. It also ignores the "2x Rainbow" catch-message spam that floats over the shop.
- **Sold-out detection in more languages.** Recognises the sold-out label in several languages
  (English, Spanish and more), on top of the xN reading.
- **Drop-in language packs.** Any `<lang>.traineddata` added to the `tessdata` folder is used
  automatically, and gets bundled into the exe when you build.

## Rename

- The app is now **FAAR Manager** / *Fish an Anime RNG Multi Account Manager* (title bar, window and
  taskbar).
