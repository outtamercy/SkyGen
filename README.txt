SkyGen
======

A MO2 plugin that writes SkyPatcher and Base Object Swapper INIs for you. No ESPs. No manual xEdit patching. Just pick your mods, pick your settings, hit Generate.

What it does
------------

- SkyPatcher INIs -- Inject keywords, change stats, swap models, add items to leveled lists. All via SkyPatcher runtime patches. No plugin slot burned.

- Base Object Swapper (BOS) -- Swap objects between mods (M2M) or scan FormIDs and batch-write swap INIs.

- Sentence Builder -- Filter -> Action -> Value. Like filterByArmors=Target|FormID:addKeywords=MyKeyword. Point and click, no hex math.

- Modlist & All-Categories -- Generate patches for your entire load order at once, filtered by category.

Install
-------

1. Download the release ZIP.
2. Extract it. You should see a folder named "SkyGen" (or "SkyGen_0_09b").
3. Drop that ENTIRE folder into your MO2 plugins/ directory.
   Correct path looks like: MO2/plugins/SkyGen/
   NOT: MO2/plugins/SkyGen_0_09b/SkyGen/
4. Inside the SkyGen folder, verify you have:
   - SkyGen/ (plugin root)
   - lz4/    (dependency folder — DO NOT DELETE THIS)
   - keyword/keywords.ini
   - themes/
   If lz4/ is missing, the plugin will crash on generation.
5. Launch MO2. SkyGen shows up in the toolbar.
6. Pick an output folder (I use mods/SkyGen_Output).
7. Hit Generate. Done.

Troubleshooting
---------------

"ModuleNotFoundError: No module named 'lz4'"
  → You deleted or moved the lz4/ folder. Re-download the release and 
     make sure lz4/ sits next to the SkyGen/ plugin folder inside plugins/.

"Welcome screen every time"
  → This is normal on first launch or after changing your mod list.
     Scroll down, check the box, hit Continue.

"No keywords for [category]"
  → That category isn't in keyword/keywords.ini yet. You can still 
     generate — the Sentence Builder lets you type custom FormIDs.

Requirements
------------

- Mod Organizer 2 (v2.5+ recommended)
- Skyrim Special Edition / Anniversary Edition / VR
- SkyPatcher (for SP generation)
- Base Object Swapper (for BOS generation)
- Python 3.11+ with PyQt6 (bundled in release)

Quick Start
-----------

1. SkyPatcher: Pick Target Mod -> Pick Source Mod -> Pick Category -> Filter/Action/Value -> Generate.

2. BOS M2M: Pick Target Mod -> Pick Source Mod -> Pick Category -> Generate.

3. BOS Scan: Check "Scan all mods" -> Pick Category -> FormIDs Scan -> Generate.

That's it. Go break something.
