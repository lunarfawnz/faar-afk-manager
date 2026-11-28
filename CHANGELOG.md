# Changelog

## v1.4.2

- Hallow's Eve now looks at the hotbar before holding anything. A character that already has a mutation tag is skipped without being pressed, so it no longer holds an already-mutated character and then reports it as a new mutation.
- Mutation tags are now spotted by their shape instead of only by reading the text, which works in small windows and on any background (water, floor, plot). The name is still read when possible.
- Dracula is only counted when the tag is red, so another mutation can't be miscounted as Dracula. A red tag that can't be read is logged as "could be Dracula" instead of being guessed.
- When the game draws the event banner lower than usual (under the Shops / Plot / Fishing buttons), the event name and timer are now still found.
- If the held slot can't be seen for a moment (small window, or the fishing bar over the hotbar), the app keeps watching the character for a mutation instead of giving up for the whole event. It only stops after 2 minutes of an unreadable hotbar, and it still never presses blind.
- The "different event" safety stop now needs 3 unexpected mutations instead of 2, so one misread can't end Hallow's Eve early.
- Fertilizers in Selene's shop are no longer mistaken for being in stock. Their "x1.25 Food" / "x2 Food" lines sit where other items show their stock count; now only "OUT OF STOCK" or a real "x Left" count is believed for them, and if neither can be read it makes at most 3 careful clicks.
- Rare catch notifications are more reliable: windows are now watched for cutscenes on their own, about once a second, so a shop visit, rejoin or slow check on another account can no longer make one get missed. Two rare catches close together on the same account are both reported, and each notification now says what time the catch happened.

## v1.4.1

- Selene now sells Big Fertilizer and Huge Fertilizer under her potions. Both are recognised and can be switched on or off in Settings → Selene items (on by default).
- Selene's shop now closes after the fertilizer row, so the new items are no longer missed.
- New phone notifications for rare catches: God, Omniscient and Apex. The app spots each tier's cutscene and reads the character's name from the "You have caught" message. Each tier has its own switch under Phone remote → Notify me about, and the catch is written in the Activity log too.

## v1.4.0

### New
- **How to use page.** A new **❓ How to use** page in the app explains every feature, setup step and common problem, so you don't need Discord or GitHub to learn it.
- **Join Event and Daily Rewards pop-ups are cleared by themselves.** Join Event is closed with its X; Daily Rewards is claimed (only when its button really says Claim). Both used to block E and clicks, which could make Selene visits and rebirths quietly fail.
- **Rebirth only when you can afford it.** The app reads your cash and the rebirth cost, and doesn't open the rebirth menu (or trigger the "not enough cash" Robux pop-up) until you can rebirth. It remembers the next cost after each rebirth. If the numbers can't be read it falls back to the old way. Setting: **Only open the rebirth menu when you can afford it** (on).
- **Cap Roblox's FPS.** Writes Roblox's own "Maximum Frame Rate" before each launch, which saves a lot of CPU. 30 is a good AFK value; 0 puts Roblox's own setting back. Key presses automatically last long enough for that FPS.
- **Restart each Roblox every N hours** (off by default) to free the memory Roblox piles up over long AFK runs. It waits until the account isn't busy with Hallow's Eve, Selene, a rebirth or a pop-up.

### Selene
- **Selene by the clock.** She's only in town for 5 minutes from every :00 and :30, so the app only looks for her then, and doesn't start a new visit in her last 50 seconds so nobody gets cut off. Setting: **Only look for her while she's in town** (on).

### Hallow's Eve
- **Smarter "put away before the end".** The lead time now grows with how many accounts are holding a character and how long a press really takes (up to 45 s), so the last account isn't late. Accounts in small windows use the timer read on another account in the same event.
- **Safer held-slot reading.**
  - The selection frame has to be a thin line around one slot, so blue floor or water around the hotbar no longer counts.
  - On bigger windows, the blue "Lvl." text that only shows on the held character is used as a second check.
  - For a few seconds after a press, readings are ignored so game lag can't cause a second press.

### Rejoin
- An account counts as back in game when its hotbar shows up, not only when the Shops button is visible.

## v1.3.3

### Anti-AFK (fixed)
- **Anti-AFK never ran for accounts with Auto ability on.** The ability check runs every few seconds, and the app counted each check as "activity" even when no key was pressed, so the anti-AFK timer never ran out and Roblox kicked the account after 20 minutes. Now only real key presses and clicks count, so anti-AFK kicks in on time.

### Auto ability (fixed)
- The marked ability button is now also found on windows of a different size from the one you marked it on.
- If the button hasn't looked ready for 5 minutes, the log says so (with how green it looks) and tells you to mark it again, instead of silently never pressing.

### Hallow's Eve (fixed)
- **The hotbar really doesn't have to be full now.** Roblox shrinks the hotbar and centres it when you have fewer items, but the app always looked where a full 10-slot hotbar would be, so with fewer items it read (and pressed) the wrong slots. It now finds the hotbar on screen, counts how many slots it has, and skips any character slot you listed that's empty.
- **No more random number-key presses.** Blue floor or water showing where the hotbar should be (for example while the fishing bar covers it) could look like a held character, so the app kept "putting away" slots that weren't held, which picked them up instead. The held-slot check now looks for the real selection frame around one slot and ignores blue that covers everything.
- When no Hallow's Eve is on (or a different event is), a character in hand is put away within about 2 seconds: the hotbar is checked every second and two looks in a row have to agree. If one press doesn't change anything, that slot isn't pressed again for 15 minutes.
- A slot is never pressed twice in a row unless the hotbar can clearly be read; if it can't, the app stops pressing for that event and says so.
- **Every event is logged by name:** Hallow's Eve, Heaven's Collide, Solar, Hell's Gates and Slime Rain. Anything other than Hallow's Eve is treated as "not Hallow's Eve": no character is held, and a held one is put away.
- The banner title is read better on small windows (tested down to about 540 px wide).

## v1.3.2

### Launching
- **Windows are now matched by the account that's actually logged in.** FAAR reads Roblox's own log file for each window to see which account it is, and links it automatically, even if the launch already timed out or you opened Roblox yourself. Checked every 5 seconds.
- **New: Link an open Roblox window.** If an account doesn't pick up its window, open its ⋯ menu → **Link an open Roblox window**, click **Show** to check which window is which, then **Link**.
- Waits up to 5 minutes for a slow window instead of 100 seconds (you can still Cancel), and keeps launching the other accounts meanwhile.
- If no window can be matched, the log now lists every Roblox window FAAR can see, to help track down why.

### Low RAM
- **New (off by default): restart a Roblox before your PC runs out of memory.** Turn on **Restart Roblox when the PC runs low on RAM** in Settings. When free RAM stays below the limit (1000 MB by default), the Roblox using the most memory is closed and launched again (at most one every 3 minutes). With it on, if memory does run out, the biggest Roblox is restarted straight away.
- Rejoins now wait (up to 2 minutes) for enough free RAM before reopening Roblox, so a crash from low memory doesn't turn into another crash.

## v1.3.1

### Fixes
- **Windows not being picked up.** If an account has waited 15 seconds and no Roblox of its own has started, it now takes over an open Roblox window that isn't linked to any account (for example one left over from an earlier launch) instead of sitting on "Waiting for window".
- **Running out of RAM.** If your PC runs out of memory, FAAR Manager now says so in one clear log line (showing free RAM and how much FAAR itself is using), sends a "PC out of memory" phone notification, and keeps going instead of flooding the log with errors.
- **Closing or minimised windows** no longer cause "Assertion failed" errors, and an account whose window is gone isn't counted as failing and rested.

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
