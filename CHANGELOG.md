# Changelog

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
