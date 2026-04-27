from __future__ import annotations
import gc
from PyQt6.QtWidgets import QApplication
import mobase  # type: ignore
from pathlib import Path
from PyQt6.QtGui import QIcon  # type: ignore
from PyQt6.QtCore import QCoreApplication, QSize, QPoint, QEventLoop, QObject, QTimer  # type: ignore
from typing import List, TYPE_CHECKING, Any, Optional
import traceback
import os
import sys
from datetime import datetime

# --- EMERGENCY DEBUGGING BLOCK (COMPLETE) ---
_plugin_root_for_emergency_log_path = Path(__file__).parent
_emergency_log_dir = _plugin_root_for_emergency_log_path / "logs"
_emergency_log_dir.mkdir(parents=True, exist_ok=True)
log_file_path = _emergency_log_dir / "Ebug.txt"
try:
    with open(log_file_path, "w", encoding='utf-8') as f:
        f.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] --- PLUGIN STARTING (EMERGENCY DEBUG) ---\n")
        f.write(f"  Current working directory: {os.getcwd()}\n")
        f.write(f"  __file__: {__file__}\n")

        plugin_root_for_emergency_log = Path(__file__).parent
        if str(plugin_root_for_emergency_log) not in sys.path:
            sys.path.insert(0, str(plugin_root_for_emergency_log))
            f.write(f"  Added plugin root to sys.path: {plugin_root_for_emergency_log}\n")

        lz4_dir_for_emergency_log = plugin_root_for_emergency_log / 'lz4_tools'
        if str(lz4_dir_for_emergency_log) not in sys.path and lz4_dir_for_emergency_log.is_dir():
            sys.path.insert(0, str(lz4_dir_for_emergency_log))
            f.write(f"  Added lz4_tools directory to sys.path: {lz4_dir_for_emergency_log}\n")
        elif not lz4_dir_for_emergency_log.is_dir():
            f.write(
                f"  WARNING: lz4_tools directory not found at: {lz4_dir_for_emergency_log}. LZ4-related functions may fail.\n")
        else:
            f.write(f"  lz4_tools directory already in sys.path: {lz4_dir_for_emergency_log}\n")

        f.write(f"  sys.path contents AFTER initial additions:\n")
        for p in sys.path:
            f.write(f"    - {p}\n")

        f.write(f"  Attempting to import lz4.frame directly for test:\n")
        try:
            import lz4.frame
            f.write(f"  - lz4.frame imported successfully in EMERGENCY DEBUG!\n")
        except ImportError as lz4_import_e:
            f.write(f"  - Failed to import lz4.frame in EMERGENCY DEBUG: {lz4_import_e}\n")
            f.write(f"  - Traceback:\n")
            traceback.print_exc(file=f)
        f.write(f"--- END EMERGENCY DEBUG BLOCK ---\n")
except Exception as e:
    print(f"CRITICAL ERROR: Failed to write to emergency log: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
# --- END EMERGENCY DEBUGGING BLOCK ---

# --- CRITICAL FIX: Explicitly order imports and use module-level referencing ---
from .utils.logger import LoggingMixin, SkyGenLogger
from .core.constants import (
    PLUGIN_NAME, PLUGIN_AUTHOR, PLUGIN_VERSION, PLUGIN_DESCRIPTION, PLUGIN_URL,
    PLUGIN_LOGGER_NAME, MO2_LOG_CRITICAL, MO2_LOG_INFO, DEBUG_MODE,
    PLUGIN_LOG_FILE_NAME, PLUGIN_CONFIG_FILE_NAME
)
from .src.organizer_wrapper import OrganizerWrapper
from .core import base
from .src.controller import SkyGenUIController
from .src.config import ConfigManager, ApplicationConfig
from .ui.theme_manager import ThemeManager

plugin_root_path = Path(__file__).parent
if str(plugin_root_path) not in sys.path:
    sys.path.insert(0, str(plugin_root_path))

from .extractors.plugin_extractor import PluginExtractor
from .utils.file_ops import FileOperationsManager
from .utils.data_exporter import DataExporter
from .utils.patch_gen import PatchAndConfigGenerationManager
from .ui.main_dialog import SkyGenMainDialog
from .utils.guard import Guard

# --- DEBUGGING ADDITION: Print sys.path and attempt lz4 import ---
print(f"[{PLUGIN_NAME}.__init__] sys.path after plugin path addition and imports:")
for p in sys.path:
    print(f"  - {p}")
try:
    import lz4.frame
    print(f"[{PLUGIN_NAME}.__init__] Successfully imported lz4.frame (bundled).")
except ImportError as e:
    print(f"[{PLUGIN_NAME}.__init__] CRITICAL ERROR: Failed to import lz4.frame: {e}")
# --- END DEBUGGING ADDITION ---


class SkyGenPlugin(mobase.IPluginTool, LoggingMixin):
    def __init__(self):
        print(f"[{self.__class__.__name__}.__init__] Starting SkyGenPlugin instance creation. ID: {id(self)}")
        super().__init__()
        print(f"[{self.__class__.__name__}.__init__] After super().__init__(). ID: {id(self)}")

        self._is_plugin_instance_initialized: bool = False
        self._init_guard: bool = False
        self._cold_boot_complete = False
        self._session_buffer: List[str] = []
        self._logger = SkyGenLogger()
        self._module_name = self.__class__.__name__

        # CRITICAL FIX: Set plugin_path FIRST before anything uses it
        self.plugin_path = Path(__file__).parent

        # Initialize other attributes to None (will be set in init())
        self.profile_manager = None
        self.blacklist_manager = None
        self.theme_manager = None
        self.organizer: Optional[mobase.IOrganizer] = None
        self.file_operations_manager: Optional[FileOperationsManager] = None
        self.plugin_extractor: Optional[PluginExtractor] = None
        self.data_exporter: Optional[DataExporter] = None
        self.patch_generator: Optional[PatchAndConfigGenerationManager] = None
        self.dialog: Optional[SkyGenMainDialog] = None
        self.config_manager: Optional[ConfigManager] = None

        print(f"[{self.__class__.__name__}.__init__] SkyGenPlugin __init__ completed.")                 
        
    # ------------------------------------------------------------------ #
    #  MO2 entry point
    # ------------------------------------------------------------------ #
    def init(self, organizer: mobase.IOrganizer) -> bool:
        """Initializes the plugin's core components."""
        if self._init_guard:
            print(f"[{self.__class__.__name__}.init] Duplicate init() call blocked for instance {id(self)}.")
            return True
        self._init_guard = True

        print(f"[{self.__class__.__name__}.init] init method called by MO2. ID: {id(self)}")
        self.log_info("SkyGenPlugin: init method called by MO2.")
        try:
            self.organizer = organizer

            # 1. Create wrapper FIRST
            self.organizer_wrapper = OrganizerWrapper(self.organizer)
            self.file_operations_manager = FileOperationsManager(self.organizer.basePath())
            
            # 2. NOW create Guard (needs wrapper)
            self.guard = Guard(self.plugin_path, self.organizer_wrapper)
            
            # 3. Config (needs profile from wrapper)
            config_file_full_path = self.plugin_path / "data" / PLUGIN_CONFIG_FILE_NAME
            self.config_manager = ConfigManager(
                self.file_operations_manager, 
                config_file_full_path,
                self.organizer_wrapper.profile_name
            )
            
            # 3. business-logic helpers (NOW config_manager exists)
            self.plugin_extractor = PluginExtractor(self.organizer_wrapper)
            self.data_exporter = DataExporter(self.organizer_wrapper, self.plugin_extractor)
            self.patch_generator = PatchAndConfigGenerationManager(
                organizer_wrapper=self.organizer_wrapper,
                file_operations_manager=self.file_operations_manager,
                plugin_extractor=self.plugin_extractor,
                patch_settings=self.config_manager.get_patch_settings()  # NOW works
            )

            # 4. dialog (must exist *before* ThemeManager)
            self.dialog = SkyGenMainDialog(
                organizer_wrapper=self.organizer_wrapper,
                file_operations_manager=self.file_operations_manager,
                plugin_extractor=self.plugin_extractor,
                patch_generator=self.patch_generator,
                data_exporter=self.data_exporter,
                plugin_path=self.plugin_path
            )

            # 5. controller with managers INSIDE the parentheses
            self.dialog.controller = SkyGenUIController(
                main_dialog=self.dialog,
                organizer_wrapper=self.organizer_wrapper,
                file_operations_manager=self.file_operations_manager,
                plugin_extractor=self.plugin_extractor,
                data_exporter=self.data_exporter,
                patch_generator=self.patch_generator,
                config_manager=self.config_manager,
                theme_manager=None,
                plugin_path=self.plugin_path,
                guard=self.guard,
            )
            
            # Theme manager assigned after creation
            self.dialog.controller.theme_manager = self.theme_manager

            # 6. theme manager (needs dialog)
            self.theme_manager = ThemeManager(
                config_manager=self.config_manager,
                mo2_base_path=self.organizer.basePath(),
                plugin_path=str(self.plugin_path),
                target_widget=self.dialog
            )

            # give controller the theme manager now that it exists
            self.dialog.controller.theme_manager = self.theme_manager

            self.dialog.wire_controller()
            self.dialog.controller.connect_ui_elements()



            # 7. register extractor
            base.FileMetadataExtractor.register_extractor(
                ['.esp', '.esm', '.esl'],
                self.plugin_extractor.__class__
            )

            # 8. default setting if missing
            if not self.organizer.pluginSetting(self.name(), "output_directory"):
                self.organizer.setPluginSetting(self.name(), "output_directory", "SkyGen Output")
                self.log_info("Initialized 'output_directory' setting dynamically.")

            self.log_info("SkyGenPlugin: init method completed successfully.")
            return True

        except Exception as e:
            self.log_critical(f"SkyGen.init() failed: {e}", exc_info=True)
            print(f"[{self.__class__.__name__}.init] CRITICAL ERROR: SkyGen.init() failed: {e}")
            traceback.print_exc()
            return False

    # ------------------------------------------------------------------ #
    #  MO2 callbacks (unchanged stubs)
    # ------------------------------------------------------------------ #
    def onAboutToRun(self, application: str, arguments: List[str]) -> bool: return True
    def onFinishedRun(self, application: str, exitCode: int) -> None: pass
    def onInstall(self, mod: str) -> None: pass
    def onModStateChanged(self, mod: str, oldState: mobase.ModState, newState: mobase.ModState) -> None: pass
    def onRefresh(self) -> None: pass
    def onUserInterfaceInitialized(self) -> None: pass
    def onProfileChanged(self, oldProfile: mobase.IProfile, newProfile: mobase.IProfile) -> None: pass
    def onPluginSettingChanged(self, pluginName: str, settingName: str, oldValue: Any, newValue: Any) -> None: pass
    def onPluginEnabled(self, pluginName: str) -> None: pass
    def onPluginDisabled(self, pluginName: str) -> None: pass
    def setup(self, organizer: mobase.IOrganizer) -> bool: return True
    def teardown(self) -> None:
        # CC Style: One last paperwork dump before lights out
        if hasattr(self, 'dialog') and self.dialog:
            self.dialog._flush_viewer_log_to_disk()
        
        self.log_info("SkyGen plugin tearing down. Closing log file.")
        SkyGenLogger().close_log_file()

    # ------------------------------------------------------------------ #
    #  required IPluginTool interface
    # ------------------------------------------------------------------ #
    def name(self) -> str: return PLUGIN_NAME
    def author(self) -> str: return PLUGIN_AUTHOR
    def description(self) -> str: return PLUGIN_DESCRIPTION
    def version(self) -> mobase.VersionInfo: return mobase.VersionInfo(PLUGIN_VERSION)
    def isActive(self) -> bool: return True
    def settings(self) -> List[mobase.PluginSetting]: return []
    def displayName(self) -> str: return PLUGIN_NAME
    def icon(self) -> QIcon: return QIcon()
    def tooltip(self) -> str: return "Launch the SkyGen tool for automated patch generation."
    def group(self) -> int: return mobase.PluginSettingGroup.Tools

    # ------------------------------------------------------------------ #
    #  display()  –  NOW only shows the dialog
    # ------------------------------------------------------------------ #
    def display(self):
        print(f"[{self.__class__.__name__}.display] SkyGen display() called.")
        self.log_info("SkyGen plugin display() called.")
        
        # Detect profile switch at SG open time
        old_profile = self.organizer_wrapper.profile_name
        self.organizer_wrapper._parse_mo2_ini()
        if old_profile != self.organizer_wrapper.profile_name:
            self.log_info(f"Profile switch: {old_profile} → {self.organizer_wrapper.profile_name}")
            self.dialog.controller._pm_init_done = False
        
        if old_profile != self.organizer_wrapper.profile_name:
            self.log_info(f"Profile switch: {old_profile} → {self.organizer_wrapper.profile_name}")
            # Force PM re-init for new modlist
            self.dialog.controller._pm_init_done = False
        
        self.dialog._populate_initial_data()
        QTimer.singleShot(100, self.dialog.controller._deferred_pm_init)
        self.dialog.exec()

# ---------------------------------------------------------------------- #
#  MO2 plugin factory
# ---------------------------------------------------------------------- #
def createPlugin() -> mobase.IPlugin:
    print("[createPlugin] createPlugin function called.")
    try:
        SkyGenLogger()._initialize_logger()
        print("[createPlugin] SkyGenLogger singleton initialized successfully.")
    except Exception as e:
        print(f"CRITICAL ERROR: Failed to initialize SkyGenLogger in createPlugin: {e}")
        traceback.print_exc()
    return SkyGenPlugin()