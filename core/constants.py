try:
    import mobase  # type: ignore
    _MOB_AVAILABLE = True
except ImportError:
    # Standalone mode (FrankenSnoop BAT) - mobase not available outside MO2
    mobase = None  # type: ignore
    _MOB_AVAILABLE = False
import hashlib
from pathlib import Path
from typing import Dict
import re
"""
SkyGen Constants Module

This module centralizes all configuration constants and magic strings used throughout
the SkyGen plugin, ensuring consistency and ease of modification.
"""

# --- Plugin Identification and Paths ---
PLUGIN_NAME = "SkyGen"
PLUGIN_AUTHOR = "Mayhem"
# WAS: PLUGIN_VERSION = (0, 0, 1, mobase.ReleaseType.ALPHA)
# FIX: Conditional version definition
if _MOB_AVAILABLE:
    PLUGIN_VERSION = (0, 9, 1, mobase.ReleaseType.BETA)  # 0.9.1 Beta
else:
    PLUGIN_VERSION = (0, 9, 0, "BETA")  # String fallback for standalone
CURRENT_EXTRACTION_LOGIC_VERSION = 2 # Bump this from 1 to 2 when we update the logic and need to invalidate old manifests
PLUGIN_DESCRIPTION = "Automated patch generator for Skyrim SE/VR."
PLUGIN_DATA_DIR_NAME = "SkyGen"
PLUGIN_CONFIG_FILE_NAME = "skygen_config.ini"
PLUGIN_LOG_FILE_NAME = "SkyGen_Debug.txt"
PLUGIN_LOGGER_NAME = "SkyGen"
PLUGIN_URL = "https://github.com/outtamercy/SkyGen" # Real URL
MANIFEST_FILE_NAME = "skygen_manifest.ini"
CURRENT_APP_VERSION = "0.9.0-BETA"

# --- Debugging and Logging ---
DEBUG_MODE = False # Set to True for verbose debugging, False for normal operation
BYPASS_BLACKLIST = False
TRACEBACK_LOGGING = False
# FormID math tweak for massive load orders (870+ plugins) - keeps prefix-to-index mapping honest
MOD_INDEX_OFFSET = 0xFE000000
MAX_LOG_FILE_SIZE_MB = 5

# --- MO2 Log Levels (for consistent logging across the plugin) ---
MO2_LOG_CRITICAL = 50
MO2_LOG_ERROR = 40
MO2_LOG_WARNING = 30
MO2_LOG_INFO = 20
MO2_LOG_DEBUG = 10
MO2_LOG_TRACE = 5 # Custom trace level for extremely verbose logging

# Game Specific Paths (Examples - adjust as necessary for your setup)
# These are typically resolved by OrganizerWrapper, but kept here for reference
GAME_DATA_PATHS = {
    "SkyrimSE": "Skyrim Special Edition/Data",
    "SkyrimVR": "SkyrimVR/Data"
}

GAME_EXECUTABLES = {
    "DataExporter": {
        "SkyrimSE": "SSEEdit.exe",
        "SkyrimVR": "SSEEditVR.exe"
    }
}

GAME_VERSIONS = [
    "SkyrimSE",
    "SkyrimVR"
]

OUTPUT_TYPES = [
    "SkyPatcher INI",
    "BOS INI"
]


# SkyPatcher actually patches these core record types (based on user documentation)
SKYPATCHER_SUPPORTED_RECORD_TYPES = (
    "NPC_", "WEAP", "ARMO", "AMMO", "ALCH", "BOOK", "MISC", "INGR", "KEYM",
    "FURN", "LVLI", "LVLC", "CONT", "SPEL", "RACE", "FLST", "ARMA"
)

# BOS supports all base-object-swappable record types (comprehensive list)
BOS_SUPPORTED_RECORD_TYPES = [
    "STAT", "MSTT", "FURN", "FLOR", "TREE", "GRAS", "ACTI", "DOOR", "LIGH",
    "SCEN", "REGN", "CONT", "MISC", "ALCH", "AMMO", "ARMO", "ARMA", "BOOK",
    "INGR", "KEYM", "SCRL", "SLGM", "SPEL", "WEAP", "TXST", "EFSH", "EXPL",
    "PROJ", "DEBR", "HAZD", "IDLE", "PACK", "CSTY", "LCTN", "WTHR", "CLMT",
    "WATR", "SNDR", "SNCT", "IMGS", "IMAD", "LSCR", "ANIO", "WRLD", "CELL"
]

# Reverse mapping: signature → list of categories (SP categories mandatory, BOS optional)
SIGNATURE_TO_CATEGORIES = {
    "ARMO": ["Armor", "SkyPatcher"],
    "WEAP": ["Weapons", "SkyPatcher"],
    "AMMO": ["Ammo", "SkyPatcher"],
    "BOOK": ["Books", "SkyPatcher"],
    "ALCH": ["Alchemy", "SkyPatcher"],
    "INGR": ["Ingredients", "SkyPatcher"],
    "MISC": ["Misc", "BOS"],
    "STAT": ["Statics", "BOS"],
    "FURN": ["Furniture", "BOS"],
    "CONT": ["Containers", "BOS"],
    "LIGH": ["Lights", "BOS"],
    "DOOR": ["Doors", "BOS"],
    "ACTI": ["Activators", "BOS"],
    "TREE": ["Trees", "BOS"],
    "FLOR": ["Flora", "BOS"],
    "NPC_": ["NPCs", "SkyPatcher"],
    "SPEL": ["Spells", "SkyPatcher"],
    "RACE": ["Races", "SkyPatcher"],
    "LVLI": ["Leveled Items", "SkyPatcher"],
    "LVLN": ["Leveled NPCs", "SkyPatcher"],
    "FLST": ["Form Lists", "SkyPatcher"],
}

# Category filtering aliases - when looking for category X, also check for signatures Y
# Fixes extraction gaps (e.g., Skyrim.esm has RACE but NPC_ sometimes missed)
CATEGORY_FILTER_ALIASES = {
    "NPC_": {"NPC_", "RACE"},  # Race records are NPC templates
    # Add others as needed - ARMO/ARMA often co-occur, WEAP/AMMO, etc.
}

# Slot names for keyword material extraction
# DataExporter strips these from armor keywords to isolate the material
ARMOR_SLOTS = ["boots", "cuirass", "gauntlets", "helmet", "shield", "cloak", "body", "hand", "feet", "head", "hair", "beard"]

# Origin plugin → signature → material fragments that DLC actually adds
# Expand this as you research — keeps Cat Gen from slapping Bonemold on Dawnguard
ORIGIN_KEYWORD_HINTS = {
    "Skyrim.esm": {
        "ARMO": ["iron", "steel", "leather", "hide", "fur", "elven", "glass", "ebony", "daedric", "dragon", "imperial", "studded", "scaled", "dwarven", "orcish", "heavy", "light"],
    },
    "Update.esm": {
        "ARMO": ["iron", "steel", "leather", "hide", "fur", "elven", "glass", "ebony", "daedric", "dragon", "imperial", "studded", "scaled", "dwarven", "orcish", "heavy", "light"],
    },
    "Dawnguard.esm": {
        "ARMO": ["heavy", "light", "dawnguard", "vampire", "falmer", "snowelf", "hardened"],
    },
    "Dragonborn.esm": {
        "ARMO": ["bonemold", "chitin", "stalhrim", "nordic", "carved"],
    },
    "HearthFires.esm": {
        "ARMO": ["iron", "steel", "leather", "hide", "fur", "elven", "glass", "ebony", "daedric", "dragon", "imperial", "studded", "scaled", "dwarven", "orcish", "heavy", "light"],
    },
}

# ============================================
# BLACKLIST / SILOED INTELLIGENCE CONSTANTS
# ============================================

# --- Shield Constants (Official Content Protection) ---

# The "Founders" - Base Game + Official DLCs (lowercase for matching)
BASE_GAME_PLUGINS = {
    "Skyrim.esm",      
    "Update.esm", 
    "Dawnguard.esm", 
    "HearthFires.esm", 
    "Dragonborn.esm",
    "_ResourcePack.esl",
        # VR equivalents
    "SkyrimVR.esm", "SkyrimVR.exe",
}

# The "Creation Club Core 75" - AE update files
AE_CORE_FILES = {
    "ccBGSSSE001-Fish.esm", "ccqdrsse001-survivalmode.esl", "ccBGSSSE037-Curios.esl",
    "ccbgssse025-advdsgs.esm", "ccASVSSE001-ALMSIVI.esm", "ccBGSSSE002-ExoticArrows.esl", "ccBGSSSE003-Zombie.esl",
    "ccBGSSSE004-RuinsEdge.esl", "ccBGSSSE005-Goldbrand.esl", "ccBGSSSE006-StendarsHammer.esl",
    "ccBGSSSE007-Chrysamere.esl", "ccBGSSSE008-Wraithguard.esl", "ccBGSSSE010-PetHtH.esl",
    "ccBGSSSE011-HrsRsBATTLE.esl", "ccBGSSSE012-HrsRsUMBER.esl", "ccBGSSSE013-Dawnfang.esl",
    "ccBGSSSE014-SpellEquip.esl", "ccBGSSSE016-Umbra.esm", "ccBGSSSE018-Shadowrend.esl",
    "ccBGSSSE019-StaffofSheogorath.esl", "ccBGSSSE020-GrayCowl.esl", "ccBGSSSE031-AdvCyrus.esm",
    "ccBGSSSE034-StaffofHasedoki.esl", "ccBGSSSE035-PetRND.esl", "ccBGSSSE036-PetBMT.esl",
    "ccBGSSSE038-BowofShadows.esl", "ccBGSSSE040-AdvOBG01.esl", "ccBGSSSE041-NetchLeather.esl",
    "ccBGSSSE043-CrossbowSDE.esl", "ccBGSSSE045-Hasedoki.esl", "ccBGSSSE050-BA_DAEDRIC.esl",
    "ccBGSSSE051-BA_DAEDRICMAIL.esl", "ccBGSSSE052-BA_DRAGONSCALE.esl",
    "ccBGSSSE053-BA_DRAGONBONE.esl", "ccBGSSSE054-BA_ORCISHISH.esl",
    "ccBGSSSE055-BA_ORCISHSCALED.esl", "ccBGSSSE056-BA_SILVER.esl",
    "ccBGSSSE057-BA_STALHRIM.esl", "ccBGSSSE058-BA_STEEL.esl",
    "ccBGSSSE059-BA_DWARVENMAIL.esl", "ccBGSSSE060-BA_DAEDRICPLATE.esl",
    "ccBGSSSE061-BA_DWARVENPLATE.esl", "ccBGSSSE062-BA_DWARVENRAW.esl",
    "ccBGSSSE063-BA_EBONYPLATE.esl", "ccBGSSSE064-BA_ELVENHUNTER.esl",
    "ccBGSSSE066-STENNARSMARK.esl", "ccBGSSSE067-DAEDRICCROSSBOW.esl",
    "ccBGSSSE068-BLOODCHILLMANOR.esl", "ccBGSSSE069-CONTEST.esl",
    "ccEDHSSE001-NORSEHALBERD.esl", "ccEDHSSE002-SPLKNT.esl",
    "ccEDHSSE003-GallowsHall.esl", "ccEEJSSE001-HBT.esl",
    "ccEEJSSE002-Tower.esl", "ccEEJSSE003-Hollow.esl",
    "ccEEJSSE004-Hall.esl", "ccEEJSSE005-Cave.esl",
    "ccFSVSSE001-Backpack.esl", "ccMTYSSE001-KnightsOfTheNine.esl",
    "ccMTYSSE002-VE.esl", "ccORSSSE001-Goblins.esl",
    "ccPEWSSE002-ArmsOfChaos.esl", "ccQDRSSE001-GDRBANNER70.esl",
    "ccRMSSSE001-STEALTHELDER.esl", "ccTDSSE001-DWAFUN.esl",
    "ccVSVSSE001-Vigilant.esl", "ccVSVSSE002-Pets.esl",
    "ccVSVSSE003-Necro.esl", "ccVSVSSE004-Behead.esl",
}

# Combined shield for UI/Auditor/PM - union of both sets
BLESSED_CORE_FILES = BASE_GAME_PLUGINS.union(AE_CORE_FILES)

BLESSED_HASH_PREFIX = "BLESSED_"

BLACKLIST_AUTHORS = {
    "Jaxonz",
    "Expired6978",
    "Meh321",
    "Sheson",
    "Doodlum",
    "Powerofthree",
    "Ryan-RSM-McKenzie",
    "Aers",
    "Nu_P_P",
    "Tudoran",
    "towawot",
    "Umgak",
    "VersuchDrei",
    "Xenius",
    "MaskedRPGFan",
    "andrelo12",
    "KrisV777",
    "Edzio",
    "Gopher",
    "BanjoBunny",
    "Acro",
    "Nemesis",
    "XPMSE",
    "Team XPMSE",
    "Groovtama"
}


# The "Founders" - Authors that trigger automatic Shield protection
PROTECTED_AUTHORS = {
    "creationclub",
    "cc",
    "Bethesda Game Studios",
    "Bethesda",
    "Mcarofano",
    "Bnesmith",
    "Rsalvatore",

}

# The "CC Pattern" - Creation Club content identification
OFFICIAL_CC_PREFIX = "cc"  # All CC mods start with "cc"

# ============================================
# FRAMEWORK DETECTION - Dual Tier System
# ============================================
# Prevents double-dipping like BLESSED_CORE union pattern.
# Tier 1: Exact filename matches (O(1)) - catches known globals
# Tier 2: Regex patterns (O(n)) - catches VR/SE/AE variants, new formats

# Tier 1: Hardcoded exact matches - never patchable, never change
GLOBAL_IGNORE_PLUGINS = {
    "AddItemMenuSE.esp",
    "AddItemMenuSE_AE.esp",
    "SkyUI_SE.esp",
    "RaceMenu.esp",
    "RaceMenuPlugin.esp",
    "XPMSE.esp",
    "MCMHelper.esp",
  
    # McmHelper is utility, catches all variants via scent below
}

# Tier 2: Fuzzy scents - catches SE/AE/VR/SKSE suffixes automatically
# These run ONLY if Tier 1 misses (prevents double detection)
SCENT_PATTERNS = {
    # Core Frameworks
    "SKSE": re.compile(r"SKSE|Script Extender", re.I),
    "DynDOLOD": re.compile(r"DynDOLOD|dyndolod", re.I),
    "Synthesis": re.compile(r"Synthesis|Mutagen", re.I),
    
    # UI/Menu mods (catches SkyUI, RaceMenu, etc regardless of suffix)
    "Menu": re.compile(r"SkyUI|RaceMenu|AddItemMenu|UIExtensions", re.I),
    "MCMHelper": re.compile(r"MCMHelper|MCM", re.I),
    
    # Engine/Utility libraries
    "PapyrusUtil": re.compile(r"PapyrusUtil", re.I),
    "ConsoleUtil": re.compile(r"ConsoleUtil", re.I),
    "JContainers": re.compile(r"JContainers", re.I),
    "AddressLib": re.compile(r"Address.*Library", re.I),
    "PO3": re.compile(r"powerofthree|po3", re.I),
    "SPID": re.compile(r"SPID|Spell.*Perk", re.I),
    
    # Swapper frameworks (for detection, not necessarily blacklist)
    "BaseObjectSwapper": re.compile(r"BaseObjectSwapper|_SWAP\.ini", re.I),
    "SkyPatcher": re.compile(r"SkyPatcher", re.I),
    
    # Animation/Framework (catches XPMSE variants)
    "AnimationFramework": re.compile(r"XPMSE|XP32|FNIS|Nemesis", re.I),
}

# Signatures that indicate pure framework/utility mods (GLOBAL layer)
GLOBAL_FRAMEWORK_SIGNATURES = {
    'SCPT', 'SKSE', 'SNDR', 'SOUN', 'CLMT', 'WTHR', 'MESG', 
    'DLBR', 'GMST', 'KYWD',  # GMST game settings, KYWD if keywords-only
}

# ============================================
# BOS SIGNATURES - Pluginless Body Mod Support
# ============================================

# Add asset signatures for pluginless body mods (SOS/SOSAM)
BOS_SIGNATURES = {
    "STAT", "MSTT", "FURN", "CONT", "LIGH", 
    "ALCH", "AMMO", "ARMO", "ARMA", "BOOK", "INGR",
    "KEYM", "MISC", "SCRL", "SLGM", "SPEL", "WEAP",
    "NPC_", "RACE",
    "ASSET_SKIN", "ASSET_BODY",
}

BOS_CATEGORIES = {
    "Tree": {'TREE'},
    "Furniture": {'FURN', 'MSTT'},
    "Container": {'CONT'},
    "Light": {'LIGH'},
    "Misc": {'STAT', 'ACTI', 'DOOR', 'FLOR'},
    "Body": {'ARMO', 'ARMA', 'NPC_', 'RACE'},
    "Skin": {'ARMO', 'ARMA', 'NPC_', 'RACE', 'ASSET_SKIN', 'ASSET_BODY'},
}

# Content scents - folder paths that scream "this is content not framework"
CONTENT_SCENTS = {
    "BodyMod": re.compile(r'actors[/\\]character', re.I),
    "SkinTextures": re.compile(r'textures[/\\]actors[/\\]character', re.I),
    "MeshAssets": re.compile(r'meshes[/\\]actors[/\\]character', re.I),
}

SP_SIGNATURES = {
    "KYWD", "LVLI", "NPC_", "ARMO", "WEAP", 
    "FLST", "ALCH", "AMMO", "BOOK", "MISC",
    "INGR", "SLGM", "SCRL", "CONT", "LIGH"
}

# Moved from sp_panel.py
SIGNATURE_TO_FILTER = {
    "KYWD": "filterByKeywords",
    "LVLI": "filterByLLs", 
    "NPC_": "filterByNPCs",
    "ARMO": "filterByArmors",
    "WEAP": "filterByWeapons",
    "ALCH": "filterByPotions",      # Changed from filterByItems
    "AMMO": "filterByAmmos",        # Changed from filterByItems
    "BOOK": "filterByBooks",        # Changed from filterByItems
    "MISC": "filterByMiscItems",    # Changed from filterByItems
    "INGR": "filterByIngredients",  # Changed from filterByItems
    "CONT": "filterByContainers",
    "LIGH": "filterByLights",
    "RACE": "filterByRaces",
    "SPEL": "filterBySpells",
    "LVLN": "filterByLVLs",
    "FLST": "filterByForms",
}


# Maps keywords.ini section names to 4-letter record type codes
# so the user's INI can use full words ([armor]) while the UI uses codes (ARMO)
KEYWORD_SECTION_MAP = {
    'ARMOR': 'ARMO', 'WEAPON': 'WEAP', 'MAGICEFFECT': 'MGEF',
    'SPELL': 'SPEL', 'MAGIC': 'SPEL', 'BOOK': 'BOOK',
    'AMMO': 'AMMO', 'RACE': 'RACE', 'NPC': 'NPC_',
    'ALCHEMY': 'ALCH', 'ALCH': 'ALCH', 'INGREDIENT': 'INGR',
    'INGR': 'INGR', 'KEY': 'KEYM', 'KEYM': 'KEYM',
    'FURNITURE': 'FURN', 'FURN': 'FURN', 'CONTAINER': 'CONT',
    'CONT': 'CONT', 'MISC': 'MISC', 'LEVELEDITEM': 'LVLI',
    'LEVELEDCREATURE': 'LVLC', 'LIGHT': 'LIGH',
    'PROJECTILE': 'PROJ', 'HAZARD': 'HAZD',
    'ENCHANTMENT': 'ENCH', 'SCROLL': 'SCRL',
    'SOULGEM': 'SLGM', 'TREE': 'TREE', 'FLORA': 'FLOR',
    'SOUND': 'SOUN', 'ACTIVATOR': 'ACTI', 'DOOR': 'DOOR',
    'CELL': 'CELL', 'WORLDSPACE': 'WRLD', 'QUEST': 'QUST',
    'PERK': 'PERK', 'SHOUT': 'SHOU', 'ARMA': 'ARMA',
    'STAT': 'STAT', 'MSTT': 'MSTT', 'FORMLIST': 'FLST',
}

# ============================================
# AUDITOR VISUAL LANGUAGE (Adaptive Theme)
# ============================================

# Colors for List Items - Optimized for Dark/Void Themes
COLOR_LOCKED  = "#FFB300"   # Amber/Gold: Frameworks (Highly Visible)
COLOR_USER_BL = "#FF5252"   # Soft Red: User manual blacklist 
COLOR_HIDDEN  = "#757575"   # Medium Grey: Auto-hidden (Visible but secondary)
COLOR_STARRED = "#4CAF50"   # Emerald: User manual whitelist
COLOR_PARTIAL = "#FFD700"   # Yellow: Pre-existing swap/caution
COLOR_ACTIVE  = "#E0E0E0"   # Off-White: Standard selectable mod

# Icons for List Items
ICON_LOCKED  = "🔒"
ICON_BLESSED = "🛡️"
ICON_USER_BL = "⚠"
ICON_STARRED = "⭐"
ICON_PARTIAL = "⚡"
ICON_NONE    = ""

# Auditor Background
AUDITOR_BG_COLOR = "#1A1A1A" # Match the "Void" theme exactly

# ============================================
# SILO-SPECIFIC RECORD MAPS
# ============================================

# BOS: Base Object Swapper supported categories
BOS_RECORD_MAP = {
    "Tree": {"STAT"},
    "Furniture": {"FURN"},
    "Container": {"CONT"},
    "Light": {"LIGH"},
    "Misc": {"MSTT", "MISC", "SLGM"},
    "All": {"STAT", "MSTT", "FURN", "CONT", "LIGH", "ALCH", "AMMO", 
            "ARMO", "BOOK", "INGR", "KEYM", "MISC", "SCRL", "SLGM", "WEAP"}
}

# SP: SkyPatcher supported categories  
SP_RECORD_MAP = {
    "NPCs": {"NPC_"},
    "Armors": {"ARMO", "ARMA"},
    "Weapons": {"WEAP"},
    "Alchemy": {"ALCH"},
    "Projectiles": {"PROJ"},
    "Misc Items": {"MISC", "BOOK", "INGR", "KEYM", "SCRL", "SLGM"},
    "All": {"KYWD", "LVLI", "NPC_", "ARMO", "WEAP", "FLST", "ALCH", 
            "AMMO", "BOOK", "MISC", "INGR", "SLGM", "SCRL", "CONT", "LIGH"}
}

# Filter to available Actions mapping (Sentence Builder)
FILTER_TO_ACTIONS = {
    # Keyword filters (most categories)
    "filterByKeywords": ["addKeywords", "removeKeywords"],
    
    # Actor / NPC
    "filterByNPCs": ["addKeywords", "removeKeywords", "setRace", "setGender", "setStats", "setOutfit"],
    "filterByRaces": ["addKeywords", "removeKeywords", "setStats"],
    
    # Items & Equipment
    "filterByArmors": ["addKeywords", "removeKeywords", "setWeightClass", "setArmorRating", "setSlot", "setWeight", "setValue"],
    "filterByWeapons": ["addKeywords", "removeKeywords", "attackDamage", "setReach", "setSpeed", "setCritDamage", "setWeight", "setValue"],
    "filterByAmmos": ["addKeywords", "removeKeywords", "setDamage", "setProjectile", "setWeight", "setValue"],
    "filterByPotions": ["addKeywords", "removeKeywords", "setWeight", "setValue"],
    "filterByIngredients": ["addKeywords", "removeKeywords", "setWeight", "setValue"],
    "filterByBooks": ["addKeywords", "removeKeywords", "setWeight", "setValue"],
    "filterByMiscItems": ["addKeywords", "removeKeywords", "setWeight", "setValue"],
    "filterByScrolls": ["addKeywords", "removeKeywords", "setCastType", "setDeliveryType", "setWeight", "setValue"],
    "filterByLights": ["addKeywords", "removeKeywords", "setRadius", "setColor", "setWeight", "setValue"],
    
    # Containers
    "filterByContainers": ["addKeywords", "removeKeywords", "addItem", "removeItem"],
    
    # Magic
    "filterBySpells": ["addKeywords", "removeKeywords", "setCastType", "setDeliveryType"],
    "filterByEffects": ["addKeywords", "removeKeywords", "setMagnitude", "setDuration"],
    
    # Leveled Lists
    "filterByLLs": ["addToLLs", "removeFromLLs", "replaceInLLs"],
    "filterByLVLs": ["addToLLs", "removeFromLLs", "replaceInLLs"],
    
    # Generic / catch-all
    "filterByForms": ["addKeywords", "removeKeywords"],
}

# ============================================
# PERSISTENCE & MANIFEST
# ============================================
USER_RULES_FILE_NAME = "blacklist_{profile}.ini"

# Data directory relative to plugin root
DATA_DIR_NAME = "data"
CACHE_DIR_NAME = "cache"

# Default subdirectories for generated files
DEFAULT_SKYPATCHER_SUBDIR = "SkyPatcher Patches"
DEFAULT_BOS_INI_SUBDIR = "BOS INI Files"

# File Extensions
INI_FILE_EXTENSION = ".ini"

# --- SkyPatcher INI Headers and Footers ---
SKYPATCHER_INI_HEADER = """; SkyPatcher INI Patch File
; Generated by SkyGen
;
"""

SKYPATCHER_INI_FOOTER = """; End of SkyPatcher INI Patch File"""

# --- BOS INI Headers, Footers, and Entry Templates ---
BOS_INI_HEADER = """; BOS INI Patch File
; Generated by SkyGen
;
"""

BOS_INI_FOOTER = """; End of BOS INI Patch File"""

# Error Messages (expanded for clarity)
ERROR_MESSAGES = {
    "CONFIG_LOAD_FAILED": "Failed to load configuration. Using default settings.",
    "CONFIG_SAVE_FAILED": "Failed to save configuration.",
    "INI_GENERATION_FAILED": "Failed to generate INI file.",
    "DIRECTORY_CREATION_FAILED": "Failed to create necessary directory.",
    "NO_RECORDS_FOUND": "No relevant records found for the selected criteria.",
    "UNKNOWN_ERROR": "An unknown error occurred. Please check the debug log.",
    "TARGET_PLUGIN_NOT_FOUND": "Target plugin '{0}' not found in MO2's load order. Cannot generate patch.",
    "SOURCE_PLUGIN_NOT_FOUND": "Source plugin '{0}' not found in MO2's load order. Proceeding without source data.",
    "DATA_EXPORT_FAILED": "Data export failed. Please ensure the data exporter is configured correctly and plugins are valid.",
    "FILE_WRITE_ERROR": "Failed to write file '{0}': {1}",
    "NO_MATCHING_RECORDS": "No records matched your criteria. Please adjust filters or ensure plugins are active.",
    "CATEGORY_REQUIRED": "A category (record type) must be selected for SkyPatcher INI generation.", 
    "OUTPUT_FOLDER_REQUIRED": "Output folder cannot be empty. Please select a directory.",
}

# --- Success Messages (can be expanded) ---
SUCCESS_MESSAGES = {
    "INI_GENERATED": "INI file generated successfully! Output file: {0}",
    "BATCH_GENERATION_COMPLETE": "Batch generation completed. See log for details.",
    "BOS_INI_GENERATION_COMPLETE": "BOS INI generation complete. {success} files generated, {failed} failed."
}

# --- Framework & Pattern Detection ---
# ============================================
# BLACKLIST / SILOED INTELLIGENCE CONSTANTS
# ============================================

BLACKLIST_KEYWORDS = {
    # Generic System Terms
    "patch", "reproccer", "dynamic", "generated",
    
    # Specific Frameworks & Tools
    "RaceMenu", "SkyUI", "DynDOLOD", "Engine Fixes", 
    "Address Library", "USSEP", "SKSE", "ConsoleUtil", 
    "Base Object Swapper", "Papyrus Extender", "Synthesis",
    "Mutagen", "MCMHelper"
}

# --- Framework Identification Scents ---
# These are the "Tags" your snoop engine applies to a plugin's DNA
SCENT_TAG_BOS = "BOS_FRAMEWORK"
SCENT_TAG_SP  = "SKYPATCHER_FRAMEWORK"

FRAMEWORK_SCENTS = {
    "BOS": {"Base Object Swapper", "BOS", "Swapper"},
    "SP": {"SkyPatcher", "SP", "Patcher"}
}

# Signatures that explicitly define a framework mod
FRAMEWORK_LOGIC_SIGNATURES = {
    "BOS_RECORDS", 
    "SP_RECORDS"
}

# Utility Functions
# ============================================

def hash_file_head(file_path: Path, size: int = 4096) -> str:
    """SHA256 of first 4KB – centralized to eliminate DRY violations."""
    try:
        with open(file_path, 'rb') as f:
            data = f.read(size)
        return hashlib.sha256(data).hexdigest()[:16]
    except Exception:
        return "0" * 16