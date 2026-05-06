SkyGen® — The Manual
====================

What it does
------------
SkyGen® is a MO2 plugin that writes SkyPatcher and Base Object Swapper INIs. No ESPs. No manual xEdit. Pick mods, pick settings, hit Generate.

Install
-------
1. Download the release ZIP.
2. Extract it. You should see a folder named "SkyGen".
3. Drop that ENTIRE folder into your MO2 plugins/ directory.
   Correct path: MO2/plugins/SkyGen/
   Wrong path: MO2/plugins/SkyGen_0_09b/SkyGen/
4. Inside the SkyGen folder, verify you have:
   - SkyGen/ (plugin root)
   - lz4/    (dependency — DO NOT DELETE)
   - keyword/keywords.ini
   - themes/
   - fonts/ (EagleLake + Almendra)
   - icons/ (forge animation, Septim, etc.)
   If lz4/ is missing, generation will crash.
5. Launch MO2. SkyGen shows up in the toolbar.

Requirements
------------
- Mod Organizer 2 (v2.5+ recommended)
- Skyrim Special Edition / Anniversary Edition / VR
- SkyPatcher (for SP generation)
- Base Object Swapper (for BOS generation)

SkyPatcher Modes
----------------
Single Mod
  Target Mod: The mod whose records you want to change (victim).
  Source Mod: The mod providing the new data (donor).
  Category: WEAP, ARMO, NPC_, etc.
  Sentence Builder: Filter → Action → Value.
  Example: filterByArmors=TargetMod|FormID:addKeywords=MyKeyword

Modlist Gen
  Generates for every plugin in your filtered load order.
  Uses the same category + keyword for all.

All Categories
  Runs every supported category (WEAP, ARMO, NPC_, etc.) in one shot.
  Heavy. Save this for when you're setting up a new profile.

BOS Modes
---------
M2M (Mod-to-Mod)
  Swaps objects from Source Mod into Target Mod.
  Pick Target → Source → Category → Generate.

FID Scan
  Harvests FormIDs from all active plugins into a table.
  Check rows you want, export to JSON, generate INI.
  Category filter narrows what gets harvested.

The Blacklist
-------------
SkyGen hides framework/utility mods from the combo boxes so you don't accidentally try to patch SkyUI or DynDOLOD.

If something looks wrong:
• Audit button (dev settings) shows every plugin and why it's locked/active.
• Blacklist Wizard button auto-detects utility mods and adds them.
• You can manually whitelist/blacklist anything in the Auditor.

CRITICAL: Synthesis must be disabled if the blacklist didn't catch it. Synthesis is a patcher, not a content mod. It will break the scan.

Output Folder
-------------
You MUST pick an output folder. I use mods/SkyGen_Output. Generate there, then move files to your mod folder if you want. The patches are just INI files — no ESP slots used.

Troubleshooting
---------------
"ModuleNotFoundError: No module named 'lz4'"
  → You deleted or moved the lz4/ folder. Re-download the release.

"Welcome screen every time"
  → Normal on first launch or after changing your mod list. Scroll, check, Continue.

"No keywords for [category]"
  → That category isn't in keyword/keywords.ini yet. You can still generate — type custom FormIDs in the Value box.

"Generate button greyed out"
  → Check that you have Target + Source + Category + Output Folder filled. BOS needs all four. SP needs at least Target + Category + Output.

Support
-------
Discord:
  https://discord.gg/f6dFYNEBf
  https://discord.gg/kR9Wjv6GG
  https://discord.com/channels/1358821582654406676/1396947505568026735

Source & Releases:
  https://github.com/outtamercy/SkyGen