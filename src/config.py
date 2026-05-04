from __future__ import annotations
import os, shutil, tempfile
from PyQt6.QtCore import QByteArray, QTimer # type: ignore
from PyQt6.QtWidgets import QWidget # type: ignore
from typing import Dict, Any, Optional, TypeVar, Type
from pathlib import Path

from ..utils.logger import LoggingMixin, SkyGenLogger, MO2_LOG_INFO, MO2_LOG_ERROR
from ..core.constants import PLUGIN_CONFIG_FILE_NAME
from ..core.models import ApplicationConfig, PatchGenerationOptions
from ..utils.file_ops import FileOperationsManager

T = TypeVar('T', bound='BaseConfig')


# ---------- helpers ----------
def _qba_to_hex(ba: QByteArray) -> str:
    return ba.toHex().data().decode()


def _hex_to_qba(hex_str: str) -> QByteArray:
    return QByteArray.fromHex(hex_str.encode())


# ---------- config models ----------
class BaseConfig:
    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}

    @classmethod
    def from_dict(cls: Type[T], data: Dict[str, Any]) -> T:
        instance = cls()
        for k, v in data.items():
            if hasattr(instance, k):
                setattr(instance, k, v)
        return instance


class PatchSettings(BaseConfig):
    def __init__(self):
        self.generate_modlist: bool = False
        self.target_mod: str = ""
        self.source_mod: str = ""
        self.category: str = ""
        self.keywords: str = ""
        self.skypatcher_output_folder: str = ""
        self.generate_all_categories: bool = False
        self.cache_mode: str = "speed"
        self.sp_filter_type: str = ""
        self.sp_action_type: str = ""
        self.sp_value_formid: str = ""
        self.sp_lmw_winners_only: bool = True

        # BOS
        self.bos_original_id: str = ""
        self.bos_swap_id: str = ""
        self.bos_cells: str = ""
        self.bos_output_folder: str = ""
        self.bos_formids: str = "[]"
        self.bos_xyz: str = "0.0,0.0,0.0"
        self.bos_target_mod: str = "" 
        self.bos_source_mod: str = "" 
        self.bos_scan_all: bool = False       
        self.enable_scan: bool = True
        
        # M2M (Mod-to-Mod) configuration - Section 1 state when NOT in scan mode
        self.m2m_category: str  = "All"      # Selected category filter (All, Statics, Furniture, etc.)
        self.m2m_chance: int    = 100          # Swap chance percentage (0-100)



class ApplicationConfig(BaseConfig):
    def __init__(self):
        self.game_version: str = "SkyrimSE"
        self.output_type: str = "SkyPatcher INI"
        self.debug_logging: bool = False
        self.traceback_logging: bool = False
        self.remember_window_size_pos: bool = True
        self.remember_splitter_state: bool = True
        self.selected_theme: str = "Default"
        self.main_window_geometry: QByteArray = QByteArray()
        self.patch_settings: PatchGenerationOptions = PatchGenerationOptions()
        self.dev_settings_hidden: bool = True  # Keep the dev junk folded up by default
        
        # Welcome screen state - modlist aware safety seal
        self.welcome_acknowledged: bool = False      # Did they click Continue?
        self.welcome_load_order_sig: str = ""        # Which modlist they agreed to
        self.loom_enabled: bool = False

# ---------- manager ----------
class ConfigManager(LoggingMixin):
    def __init__(self, file_operations_manager: FileOperationsManager, 
                 config_file_path: Path,
                 profile_name: str = "Default"):  # <-- ADD: profile parameter
        super().__init__()
        self.file_ops = file_operations_manager
        
        # Profile-specific config filename
        self.config_file_path = config_file_path.with_name(
            f"skygen_config_{profile_name}.ini"
        )
        
        self.app_config = ApplicationConfig()
        self._flush_timer = QTimer()
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._do_write_ini)
        self._flush_timer.setInterval(200)
        self._load_config_from_file()

    # --------------------------------------------------
    # loading
    # --------------------------------------------------
    def _load_config_from_file(self) -> None:
        content = self.file_ops.read_text_file(self.config_file_path)
        if not content:
            self.log_info("No existing configuration file found, using default settings.")
            return

        data = self._parse_ini_content(content)
        app = data.get("Application", {})
        ac = self.app_config
        ac.game_version             = app.get("game_version", ac.game_version)
        ac.output_type              = app.get("output_type", ac.output_type)
        ac.debug_logging            = app.get("debug_logging", str(ac.debug_logging)).lower() == 'true'
        ac.traceback_logging        = app.get("traceback_logging", str(ac.traceback_logging)).lower() == 'true'
        ac.remember_window_size_pos = app.get("remember_window_size_pos", str(ac.remember_window_size_pos)).lower() == 'true'
        ac.remember_splitter_state  = app.get("remember_splitter_state", str(True)).lower() == 'true'
        ac.selected_theme           = app.get("selected_theme", ac.selected_theme)
        ac.dev_settings_hidden      = app.get("dev_settings_hidden", str(ac.dev_settings_hidden)).lower() == 'true'
        ac.dev_settings_hidden      = app.get("dev_settings_hidden", str(ac.dev_settings_hidden)).lower() == 'true'
        ac.loom_enabled = app.get("loom_enabled", str(ac.loom_enabled)).lower() == 'true'

        # Load welcome seal state (defaults to False/empty if missing)
        ac.welcome_acknowledged     = app.get("welcome_acknowledged", str(ac.welcome_acknowledged)).lower() == 'true'
        ac.welcome_load_order_sig   = app.get("welcome_load_order_sig", ac.welcome_load_order_sig)
        # Grab the profile-specific seals too — stuff like welcome_app_version_Vanilla Skyrim SE
        # These are dynamic keys so the loader won't see them unless we loop
        for key, value in app.items():
            if key.startswith('welcome_') and not hasattr(ac, key):
                setattr(ac, key, value)
        patch                       = data.get("PatchGeneration", {})
        ps                          = ac.patch_settings
        ps.cache_mode               = patch.get("cache_mode", ps.cache_mode)
        ps.generate_modlist         = patch.get("generate_modlist", str(ps.generate_modlist)).lower() == 'true'
        ps.target_mod               = patch.get("target_mod", ps.target_mod)
        ps.source_mod               = patch.get("source_mod", ps.source_mod)
        ps.category                 = patch.get("category", ps.category)
        ps.keywords                 = patch.get("keywords", ps.keywords)
        ps.skypatcher_output_folder = patch.get("skypatcher_output_folder", ps.skypatcher_output_folder)
        ps.generate_all_categories  = patch.get("generate_all_categories", str(ps.generate_all_categories)).lower() == 'true'
        ps.sp_filter_type = patch.get("sp_filter_type", ps.sp_filter_type)
        ps.sp_action_type = patch.get("sp_action_type", ps.sp_action_type)
        ps.sp_value_formid = patch.get("sp_value_formid", ps.sp_value_formid)
        ps.sp_lmw_winners_only = patch.get("sp_lmw_winners_only", str(ps.sp_lmw_winners_only)).lower() == 'true'

        # BOS
        ps.bos_original_id       = patch.get("bos_original_id", ps.bos_original_id)
        ps.bos_swap_id           = patch.get("bos_swap_id", ps.bos_swap_id)
        ps.bos_cells             = patch.get("bos_cells", ps.bos_cells)
        ps.bos_output_folder     = patch.get("bos_output_folder", ps.bos_output_folder)
        ps.bos_formids           = patch.get("bos_formids", ps.bos_formids)
        ps.bos_xyz               = patch.get("bos_xyz", ps.bos_xyz)
        ps.bos_target_mod        = patch.get("bos_target_mod", ps.bos_target_mod)        
        ps.bos_source_mod        = patch.get("bos_source_mod", ps.bos_source_mod)
        ps.bos_scan_all          = patch.get("bos_scan_all", str(ps.bos_scan_all)).lower() == 'true'

        # M2M
        ps.enable_scan = patch.get("enable_scan", "true").lower() == "true"
        
        # Load M2M settings with defaults
        ps.m2m_category = patch.get("m2m_category", ps.m2m_category)
        ps.m2m_chance = int(patch.get("m2m_chance", str(ps.m2m_chance)))


        self.log_info("Configuration loaded from file successfully.")

    # --------------------------------------------------
    # saving  (debounced + atomic)
    # --------------------------------------------------
    def save_application_config(self, config: ApplicationConfig) -> None:
        self.app_config = config
        self._write_ini()

    def get_application_config(self) -> ApplicationConfig:
        return self.app_config

    def get_patch_settings(self) -> PatchGenerationOptions:
        return self.app_config.patch_settings

    def save_patch_settings(self, settings: PatchGenerationOptions) -> None:
        self.app_config.patch_settings = settings
        self._write_ini()

    def _write_ini(self) -> None:
        self._flush_timer.start()

    def _do_write_ini(self) -> None:
        """Atomic write."""
        cache_dir = self.config_file_path.parent / "cache"
        cache_dir.mkdir(exist_ok=True)
        temp = cache_dir / f"{self.config_file_path.name}.tmp"

        lines = ["[Application]"]
        ac = self.app_config
        lines += [f"{k}={v}" for k, v in ac.to_dict().items() if k != 'patch_settings']
        
        lines += ["", "[PatchGeneration]"]
        lines += [f"{k}={v}" for k, v in ac.patch_settings.to_dict().items()]

        try:
            with temp.open("w", encoding="utf-8") as f:
                f.write("\n".join(lines))
                f.flush()
                os.fsync(f.fileno())
            shutil.move(str(temp), str(self.config_file_path))
            self.log_info("Config flushed (atomic).")
        except Exception as e:
            self.log_error(f"Atomic save failed: {e}")

    # --------------------------------------------------
    # internal helpers
    # --------------------------------------------------
    def _parse_ini_content(self, content: str) -> Dict[str, Dict[str, str]]:
        config: Dict[str, Dict[str, str]] = {}
        current_section = None
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('[') and line.endswith(']'):
                current_section = line[1:-1]
                config[current_section] = {}
            elif current_section and '=' in line:
                key, value = line.split('=', 1)
                config[current_section][key.strip()] = value.strip()
        return config

    def config_exists(self) -> bool:
        return self.config_file_path.is_file()

    # --------------------------------------------------
    # public flush helper
    # --------------------------------------------------
    def flush_config(self) -> None:
        """Trigger single debounced flush on close."""
        self._write_ini()