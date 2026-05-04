"""
SkyGen Organizer-Wrapper – MO2 INI-based path resolution.
Zero API calls for path resolution. Self-contained.
"""

from __future__ import annotations

import mobase  # type: ignore
from pathlib import Path
from typing import Optional, List, Tuple

from ..core.constants import MO2_LOG_DEBUG, MO2_LOG_INFO, MO2_LOG_WARNING, MO2_LOG_ERROR
from ..utils.logger import LoggingMixin


class OrganizerWrapper(LoggingMixin):
    """
    INI-based path resolver. No MO2 API calls for file paths.
    Parses ModOrganizer.ini directly on init.
    """

    def __init__(self, organizer: mobase.IOrganizer):
        super().__init__()
        self.organizer = organizer
        self._load_order_cache: Optional[List[str]] = None
        
        # Parse INI immediately - no lazy init
        self._parse_mo2_ini()
        # Cache the lineup so Frankie and the exporter share the same truth
        self.active_plugins = self.read_loadorder_txt()
        
        self.log_info(f"{self.__class__.__name__} initialized with profile: {self._profile_name}")

    # ------------------------------------------------------------------
    # INI Parsing
    # ------------------------------------------------------------------
    def _decode_byte_array(self, value: str) -> str:
        """
        Decode MO2/Qt @ByteArray wrapper and unescape backslashes.
        @ByteArray(Vanilla Skyrim SE) -> Vanilla Skyrim SE
        """
        value = value.strip()
        
        if value.startswith('@ByteArray(') and value.endswith(')'):
            value = value[11:-1]
        
        # Qt doubles backslashes in INI
        value = value.replace('\\\\', '\\')
        value = value.strip('"').strip("'")
        
        return value

    def _parse_mo2_ini(self) -> None:
        """
        Parse ModOrganizer.ini for all critical paths.
        Hard fail if INI missing or critical paths unresolvable.
        """
        import configparser
        
        mo2_root = Path(self.organizer.basePath()).resolve()
        
        # Try Portable first (INI next to EXE)
        mo2_ini_path = mo2_root / "ModOrganizer.ini"
        
        if not mo2_ini_path.is_file():
            # Global install fallback: AppData/Local
            global_path = Path.home() / "AppData" / "Local" / "ModOrganizer" / "ModOrganizer.ini"
            if global_path.is_file():
                mo2_ini_path = global_path
                self.log_info(f"Global MO2 install detected: {mo2_ini_path}")
            else:
                self.log_critical(f"ModOrganizer.ini not found at: {mo2_root} or {global_path}")
                raise RuntimeError("MO2 configuration not found in Portable or Global locations")

        # Parse INI first - BEFORE any config access
        config = configparser.ConfigParser()
        try:
            config.read(mo2_ini_path, encoding='utf-8')
        except Exception as e:
            self.log_critical(f"Failed to parse ModOrganizer.ini: {e}")
            raise RuntimeError(f"MO2 configuration corrupted: {e}")
        
        if 'General' not in config:
            self.log_critical("No [General] section in ModOrganizer.ini")
            raise RuntimeError("MO2 configuration invalid: missing [General] section")

        # Store essentials first (needed by fallback method)
        self._mo2_root = mo2_root
        self._mo2_config = config
        
        # Extract selected_profile from INI (PRIMARY SOURCE)
        try:
            self._profile_name = self._decode_byte_array(
                config.get('General', 'selected_profile', fallback='Default')
            ).strip()
            if not self._profile_name:
                self._profile_name = 'Default'
        except Exception as e:
            self.log_warning(f"Could not parse selected_profile: {e}, using Default")
            self._profile_name = 'Default'
        
        # Set profile directory based on install type (Global vs Portable)
        if mo2_ini_path.parent != mo2_root:
            # Global install: Check for instance subdirectory
            instance_name = self._decode_byte_array(
                config.get('General', 'selected_instance', fallback='')
            ).strip()
            if instance_name:
                self._profile_dir = mo2_ini_path.parent / instance_name / "profiles" / self._profile_name
            else:
                self._profile_dir = mo2_ini_path.parent / "profiles" / self._profile_name
        else:
            # Portable install: MO2Root/profiles/
            self._profile_dir = mo2_root / "profiles" / self._profile_name
            
        self.log_debug(f"Profile from INI: '{self._profile_name}', path: {self._profile_dir}")
        
        # Fallback to timestamp detection only if INI profile doesn't exist
        if not self._profile_dir.exists():
            self.log_warning(f"INI profile '{self._profile_name}' not found, using timestamp fallback")
            self._detect_active_profile_fallback()
        
        try:
            game_path_raw = self._decode_byte_array(
                config.get('General', 'gamePath')
            )
            if not game_path_raw:
                raise ValueError("gamePath is empty")
            
            mods_path_raw = self._decode_byte_array(
                config.get('General', 'modsPath', fallback='./mods')
            )
            if not mods_path_raw:
                mods_path_raw = './mods'
            
        except (configparser.NoOptionError, ValueError) as e:
            self.log_critical(f"Required path not found in [General]: {e}")
            raise RuntimeError(f"MO2 configuration incomplete: {e}")
        
        # Resolve absolute paths
        game_path = Path(game_path_raw)
        if not game_path.is_absolute():
            game_path = (mo2_root / game_path_raw).resolve()
        else:
            game_path = game_path.resolve()
        
        self._game_path = game_path
        self._game_data_path = (game_path / "Data").resolve()
        self._mods_path = (mo2_root / mods_path_raw).resolve()
        self._overwrite_path = (mo2_root / "overwrite").resolve()
        
        # Validate critical paths
        critical = {
            "game_data": self._game_data_path,
            "mods": self._mods_path,
            "profile": self._profile_dir,
        }
        
        for name, path in critical.items():
            if not path.exists():
                self.log_critical(f"Critical path does not exist: {name} = {path}")
                raise RuntimeError(f"MO2 path validation failed: {name} = {path}")
        
        self.log_info(f"MO2 paths resolved: profile={self._profile_name}, mods={self._mods_path}")
        self.log_debug(f"Game data: {self._game_data_path}")

    def _detect_active_profile_fallback(self) -> None:
        """Fallback: detect active profile via plugins.txt timestamps if INI profile invalid."""
        profiles_base = self._mo2_root / "profiles"
        most_recent_path: Optional[Path] = None
        latest_mtime = 0.0
        
        for profile_folder in profiles_base.iterdir():
            if not profile_folder.is_dir():
                continue
            plugins_txt = profile_folder / "plugins.txt"
            if plugins_txt.exists():
                mtime = plugins_txt.stat().st_mtime
                if mtime > latest_mtime:
                    latest_mtime = mtime
                    most_recent_path = profile_folder
        
        if most_recent_path:
            self._profile_dir = most_recent_path.resolve()
            self._profile_name = most_recent_path.name
            self.log_info(f"Fallback profile detected via timestamp: {self._profile_name}")
        else:
            self.log_critical("No profiles found via timestamp fallback")
            raise RuntimeError("Cannot detect active MO2 profile")

    def refresh_profile(self) -> str:
        """Re-parse MO2 INI to catch profile switches without API calls."""
        self._parse_mo2_ini()
        self.active_plugins = self.read_loadorder_txt()
        return self._profile_name

    # ------------------------------------------------------------------
    # Path Properties - Direct Access
    # ------------------------------------------------------------------
    @property
    def mo2_root(self) -> Path:
        """MO2 installation root directory."""
        return self._mo2_root
    
    @property
    def game_path(self) -> Path:
        """Root game directory (e.g., Skyrim Special Edition)."""
        return self._game_path
    
    @property
    def game_data_path(self) -> Path:
        """Game Data directory (contains vanilla ESMs)."""
        return self._game_data_path
    
    @property
    def mods_path(self) -> Path:
        """MO2 mods directory."""
        return self._mods_path
    
    @property
    def profile_name(self) -> str:
        """Active profile name."""
        return self._profile_name
    
    @property
    def profile_dir(self) -> Path:
        """Active profile directory."""
        return self._profile_dir
    
    @property
    def overwrite_path(self) -> Path:
        """MO2 overwrite directory."""
        return self._overwrite_path

    # ------------------------------------------------------------------
    # Plugin Path Resolution - 3-Tier LMW (No API calls)
    # ------------------------------------------------------------------
    def get_plugin_path(self, plugin_name: str) -> Optional[Path]:
        """
        Resolve plugin path using 3-tier LMW search.
        Tier 1: mods/{mod_name}/{plugin_name}
        Tier 2: profiles/{profile}/{plugin_name}  
        Tier 3: GamePath/Data/{plugin_name} (base game)
        
        Returns None if not found in any tier.
        """
        # Tier 1: Search mods folders
        if self._mods_path.exists():
            for mod_folder in self._mods_path.iterdir():
                if not mod_folder.is_dir():
                    continue
                candidate = mod_folder / plugin_name
                if candidate.is_file():
                    return candidate.resolve()
                
                # Check Data subdirectory (some mods nest plugins)
                nested = mod_folder / "Data" / plugin_name
                if nested.is_file():
                    return nested.resolve()
        
        # Tier 2: Profile directory (rare, but possible)
        profile_candidate = self._profile_dir / plugin_name
        if profile_candidate.is_file():
            return profile_candidate.resolve()
        
        # Tier 3: Base game Data folder
        game_candidate = self._game_data_path / plugin_name
        if game_candidate.is_file():
            return game_candidate.resolve()
        
        self.log_debug(f"Plugin not found in any tier: {plugin_name}")
        return None

    def initialize_paths(self) -> None:
        """
        SNM: Maintained for backward compatibility.
        Paths now resolved eagerly in _parse_mo2_ini().
        """
        self.log_debug("initialize_paths() called - paths already resolved")
        pass

    # ------------------------------------------------------------------
    # Load-order helpers (File-based, minimal API)
    # ------------------------------------------------------------------
    def read_loadorder_txt(self) -> List[str]:
        """
        Build active list from loadorder.txt order + plugins.txt active filter.
        Base masters always included since MO2 doesn't list them in plugins.txt.
        """
        loadorder_path = self._profile_dir / "loadorder.txt"
        full_order = []
        if loadorder_path.is_file():
            try:
                lines = loadorder_path.read_text(encoding="utf-8").splitlines()
                full_order = [ln.split("#")[0].strip() for ln in lines if ln.strip()]
            except Exception as e:
                self.log_warning(f"loadorder.txt read failed: {e}")
        
        if not full_order:
            return self._read_plugins_txt_active()
        
        # Active set from plugins.txt — only *starred lines
        active_set = set(self._read_plugins_txt_active())
        
        # Base masters are always on — MO2 never puts them in plugins.txt
        base_masters = {"Skyrim.esm", "Update.esm", "Dawnguard.esm",
                        "HearthFires.esm", "Dragonborn.esm"}
        
        # Preserve load order, evict inactive non-base plugins
        active = []
        for plugin in full_order:
            if plugin in base_masters or plugin in active_set:
                active.append(plugin)
        
        self.log_debug(f"Active lineup: {len(active)} from {len(full_order)} load order")
        return active

    def _read_plugins_txt_active(self) -> List[str]:
        """Read active plugins from plugins.txt."""
        plugins_path = self._profile_dir / "plugins.txt"
        
        if not plugins_path.is_file():
            self.log_warning("No plugins.txt found")
            return []
        
        try:
            lines = plugins_path.read_text(encoding="utf-8").splitlines()
            # Lines starting with * are active
            active = [ln[1:].strip() for ln in lines if ln.startswith('*')]
            self.log_debug(f"Read {len(active)} active plugins from plugins.txt")
            return active
        except Exception as e:
            self.log_warning(f"Could not read plugins.txt: {e}")
            return []

    def read_modlist_txt(self) -> Tuple[List[str], List[str]]:
        """
        Returns (active_mods, inactive_mods) from modlist.txt.
        Active mods prefixed with +, inactive with -.
        """
        modlist_path = self._profile_dir / "modlist.txt"
        
        if not modlist_path.is_file():
            return [], []
        
        try:
            lines = modlist_path.read_text(encoding="utf-8").splitlines()
            active = [ln[1:].strip() for ln in lines if ln.startswith('+')]
            inactive = [ln[1:].strip() for ln in lines if ln.startswith('-')]
            return active, inactive
        except Exception as e:
            self.log_warning(f"Could not read modlist.txt: {e}")
            return [], []

    # ------------------------------------------------------------------
    # Convenience (for compatibility)
    # ------------------------------------------------------------------
    def data_path(self) -> Path:
        """Alias for game_data_path."""
        return self._game_data_path

    def profile_path(self) -> Path:
        """Alias for profile_dir."""
        return self._profile_dir