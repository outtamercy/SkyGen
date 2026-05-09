SkyGen
======

MO2 plugin that writes SkyPatcher and Base Object Swapper INIs for you. No ESPs. No manual xEdit. Pick your mods, pick settings, hit Generate, go play.

What it does
------------

- SkyPatcher INIs — inject keywords, change stats, swap models, add to leveled lists. Runtime patches, zero plugin slots burned.
- Base Object Swapper (BOS) — swap objects between mods (M2M) or scan FormIDs and batch-write swap INIs.
- Sentence Builder — Filter → Action → Value. Point and click, no hex math.
- Modlist & All-Categories — patch your whole load order at once, filtered by category.
- Loom (Auto-Keywords) — reads your plugin records and suggests keywords automatically. Still learning, sometimes wrong, but getting smarter. Toggle it in Dev Settings if you wanna try it.
- Blacklist — auto-detects framework mods (SkyUI, RaceMenu, DynDOLOD, etc.) and keeps them out of your patch so you don't accidentally keyword a menu. You can edit the list manually if it gets something wrong.

Install
-------

1. Download the release ZIP.
2. Extract it. You should see a folder named "SkyGen".
3. Drop that ENTIRE folder into your MO2 `plugins/` directory.
   Correct: `MO2/plugins/SkyGen/`
   Wrong: `MO2/plugins/SkyGen_0_09b/SkyGen/` ← don't do this
4. Inside the SkyGen folder, make sure you have:
   - `SkyGen/` (plugin root)
   - `lz4/` (dependency folder — DO NOT DELETE)
   - `keyword/keywords.ini`
   - `themes/`
   Missing `lz4/` = crash on generation. Don't ask me why, it just does.
5. Launch MO2. SkyGen shows up in the toolbar.
6. Pick an output folder (I use `mods/SkyGen_Output`).
7. Hit Generate. Done.

First Launch
------------

You'll see a welcome screen. First few opens show text (readme, changelog) so you actually know what's new. After that it switches to animated GIFs because I got tired of QtMultimedia crashing. If the GIFs don't show, you probably still get text — either way, scroll down, check the box, hit Continue.

Loom — Auto-Keyword Suggestions
-------------------------------

Loom looks at your plugin records (weapon stats, armor slots, spell types, etc.) and tries to guess the right keywords instead of making you pick them manually. It's not perfect yet — sometimes it suggests "Iron" for a steel sword because the record data is weird. But it's way better than staring at a blank Sentence Builder.

Turn it on in Dev Settings → "Enable Loom Auto-Keywords". When active, the manual Filter/Action/Value combos get greyed out and Loom takes over. When off, you're back to manual mode. Your choice.

Blacklist — Keeping Frameworks Out of Your Patch
------------------------------------------------

SkyGen automatically scans your load order and flags known framework/utility mods (SkyUI, RaceMenu, DynDOLOD, SKSE stuff, etc.). These mods never enter the patch pipeline — you can't accidentally target them, and they don't clutter the scan.

The blacklist lives in `data/mod_blacklist.txt`. SkyGen builds it automatically on first run and updates it when your load order changes. If it flags something wrong, open the file and delete the line. If it misses something, add the plugin name manually. The Blacklist Auditor (🔍 button) shows you exactly what got flagged and why.

Troubleshooting
---------------

SkyGen is fully contained. You do **not** need Python installed. It actually runs better without one.

`ModuleNotFoundError: No module named 'lz4'`
→ You deleted or moved the `lz4/` folder. Re-download the release and make sure `lz4/` sits next to the `SkyGen/` folder inside `plugins/`.

"Welcome screen every time"
→ Normal on first launch or after changing your mod list. Scroll down, check the box, hit Continue.

"No keywords for [category]"
→ That category isn't in `keyword/keywords.ini` yet. You can still generate — the Sentence Builder lets you type custom FormIDs.

Need help? Discord: https://discord.gg/f6dFYNEBf or https://discord.gg/kR9Wjv6GG

Requirements
------------

- Mod Organizer 2 (v2.5+ recommended)
- Skyrim SE / AE / VR
- SkyPatcher (for SP generation)
- Base Object Swapper (for BOS generation)
- Python 3.11+ with PyQt6 (bundled in release, you don't install it)

Quick Start
-----------

1. **SkyPatcher:** Target Mod → Source Mod → Category → Filter/Action/Value → Generate.
2. **BOS M2M:** Target Mod → Source Mod → Category → Generate.
3. **BOS Scan:** Check "Scan all mods" → Category → FormIDs Scan → Generate.
4. **Auto-Keywords:** Turn on Loom in Dev Settings, pick a category, hit Generate. See what it guesses.

That's it. Go break something.