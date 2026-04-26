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

1. Download the release.
2. Drop the SkyGen folder into your MO2 plugins/ directory.
3. Launch MO2. SkyGen shows up in the toolbar.
4. Pick an output folder (I use mods/SkyGen_Output).
5. Hit Generate. Done.

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
