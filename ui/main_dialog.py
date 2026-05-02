# main_dialog.py – Phase-2: geometry now handled by GeometryManager/.dat file
from __future__ import annotations
import json
from PyQt6.QtWidgets import ( # type: ignore
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QWidget, QMessageBox,QLabel,
    QSizePolicy, QGroupBox, QComboBox, QLineEdit, QCheckBox, QRadioButton,
    QButtonGroup, QSplitter, QFileDialog, QStackedWidget,QSpacerItem, QScrollArea, QApplication
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QByteArray, QTimer # type: ignore
from PyQt6.QtGui import QIcon, QIntValidator, QDoubleValidator # type: ignore
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from pathlib import Path
import logging
import traceback
from datetime import datetime
from ..utils.logger import LoggingMixin, MO2_LOG_INFO, MO2_LOG_DEBUG
from ..src.config import ConfigManager
from .theme_manager import ThemeManager
from ..src.organizer_wrapper import OrganizerWrapper
from ..src.controller import SkyGenUIController
from ..core.constants import (
    SKYPATCHER_SUPPORTED_RECORD_TYPES, BOS_SUPPORTED_RECORD_TYPES, BYPASS_BLACKLIST,
    PLUGIN_CONFIG_FILE_NAME, PLUGIN_NAME, PLUGIN_VERSION, DEBUG_MODE, TRACEBACK_LOGGING,
)
from .feedback import StatusLogWidget
from ..utils.file_ops import FileOperationsManager
from ..extractors.plugin_extractor import PluginExtractor
from ..utils.data_exporter import DataExporter
from ..utils.patch_gen import PatchAndConfigGenerationManager
from .sp_panel import SkyPatcherPanel
from .bos_panel import BosPanel
from ..utils.geom_mgr import GeometryManager
from ..ui.auditor_dialog import BlacklistAuditorDialog
from .welcome_panel import WelcomePanel

if TYPE_CHECKING:
    from mobase import IOrganizer # type: ignore


class SkyGenMainDialog(QDialog, LoggingMixin):
    #######################################################################
    #  life-cycle
    #######################################################################
    tool_dialog_closed = pyqtSignal()
    _ui_built = False

    def __init__(
        self,
        organizer_wrapper: OrganizerWrapper,
        file_operations_manager: FileOperationsManager,
        plugin_extractor: PluginExtractor,
        patch_generator: PatchAndConfigGenerationManager,
        data_exporter: DataExporter,
        plugin_path: Path,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.controller: Optional[SkyGenUIController] = None
        self.log_info("SkyGenMainDialog initialized.")
        self.plugin_path = plugin_path.resolve()
        # Load embedded fonts (Eagle Lake, Almendra) - zero system dependency
        font_dir = self.plugin_path / "fonts"
        self._eagle_font = None
        self._almendra_font = None
        
        if font_dir.exists():
            from PyQt6.QtGui import QFontDatabase, QFont # type: ignore
            
            eagle_id = QFontDatabase.addApplicationFont(str(font_dir / "EagleLake-Regular.ttf"))
            if eagle_id != -1:
                families = QFontDatabase.applicationFontFamilies(eagle_id)
                if families:
                    self._eagle_font = QFont(families[0], 24, QFont.Weight.Bold)
                    
            almendra_id = QFontDatabase.addApplicationFont(str(font_dir / "Almendra-Regular.ttf"))
            if almendra_id != -1:
                families = QFontDatabase.applicationFontFamilies(almendra_id)
                if families:
                    self._almendra_font = QFont(families[0], 12)

        # ---------- core references ----------
        self.organizer_wrapper = organizer_wrapper
        self.file_ops = file_operations_manager
        self.plugin_extractor = plugin_extractor
        self.patch_generator = patch_generator
        self.data_exporter = data_exporter
        # ---------- self-contained INI ----------
        config_dir = Path(__file__).resolve().parent.parent / "data"
        config_dir.mkdir(parents=True, exist_ok=True)
        self.config_manager = ConfigManager(
            self.file_ops,
            config_dir / PLUGIN_CONFIG_FILE_NAME,
            organizer_wrapper.profile_name,  # <-- Profile-aware config
        )
        # ---------- geometry manager ----------
        self.geometry_manager = GeometryManager(self.plugin_path)
        # Register namespaces
        self.geometry_manager.register_global()
        self.geometry_manager.register_namespace("SkyPatcher")
        self.geometry_manager.register_namespace("BOS")

        # ---------- viewers / theming ----------
        self.status_log_widget = StatusLogWidget(str(self.plugin_path), self)
        self.theme_manager = ThemeManager(
            self.config_manager,
            self.organizer_wrapper.organizer.basePath(),
            str(Path(__file__).resolve().parent.parent),
            self,
            organizer_wrapper=self.organizer_wrapper,
        )
        # ---------- window chrome ----------
        self.setWindowTitle(
            self.tr(f"{PLUGIN_NAME} {'.'.join(map(str, PLUGIN_VERSION[:3]))}")
        )
        self.setWindowIcon(QIcon(str(self.plugin_path / "icons" / "SkyGen.ico")))
        # ---------- buttons ----------
        self.close_button = QPushButton("Close")
        self.close_button.setIcon(QIcon(str(self.plugin_path / "icons" / "close.png")))
        self.close_button.clicked.connect(self.reject)
        # ---------- build & restore ----------
        self._setup_ui()

        self.setMinimumSize(900, 500)
        self.setMaximumHeight(16777215)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # ---------- geometry tracking ----------
        self._geometry_restored = False
        self._geometry_fully_restored = False
        # ---------- close-event guard ----------
        self._flushed = False
        self._startup_complete = False

        # track MO2 profile for swap detection
        self._last_profile = self.organizer_wrapper.profile_name

    def set_startup_complete(self) -> None:
        """Mark dialog as ready to be shown by controller."""
        self._startup_complete = True
        self.log_debug("Main dialog unlocked for display")

    def bulk_log_restore(self, buffer: list[str]) -> None:
        """Ingest session buffer when dialog is fully initialized."""
        if not buffer:
            return
        try:
            if hasattr(self, 'status_log_widget') and self.status_log_widget:
                for line in buffer:
                    self.status_log_widget.append_line(line, 20)
                print(f"BULK_RESTORE_OK: {len(buffer)} lines ingested")
            else:
                print(f"BULK_RESTORE_FAIL: widget not ready, {len(buffer)} lines lost")
        except Exception as e:
            print(f"BULK_RESTORE_CRASH: {e}")

    def _flush_viewer_log_to_disk(self) -> None:
        """Nuclear flush - ensure pending updates hit the widget before we read."""
        try:
            # Strategy 1: Normal path - process events first so toPlainText is fresh
            viewer = getattr(self, 'status_log_widget', None)
            if viewer:
                # Force GUI to catch up so we don't miss recent logs
                QApplication.instance().processEvents()
                
                display = getattr(viewer, 'log_display', None) or viewer
                if hasattr(display, 'toPlainText'):
                    content = display.toPlainText()
                    if content:
                        target = self.plugin_path / "logs" / "viewer.txt"
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(content, encoding='utf-8')  # Overwrite, clean slate
                        print(f"VIEWER_FLUSH_OK: {len(content)} chars to {target}")
                        return
            
            # Strategy 2: Fallback to controller session buffer (correct attribute name)
            if (hasattr(self, 'controller') and self.controller and
                hasattr(self.controller, '_session_buffer') and  # <-- FIXED: was _pending_session_buffer
                self.controller._session_buffer):
                
                content = "\n".join(self.controller._session_buffer)
                target = self.plugin_path / "logs" / "viewer.txt"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding='utf-8')
                print(f"VIEWER_FALLBACK_FLUSH: {len(content)} chars from buffer")
                return
                
            print("VIEWER_FLUSH_FAIL: No content found")
            
        except Exception as e:
            print(f"VIEWER_FLUSH_CRASH: {e}")

    def closeEvent(self, event):
        """Trap 1: X button or Alt+F4."""
        print("TRAP_CLOSEEVENT")
        if not getattr(self, '_close_fired', False):
            self._close_fired = True
            self.reject()
        event.accept()

    def reject(self):
        """Clean close: saves geometry and flushes log."""
        self.log_info("REJECT-CALLED")
        
        # Flush paperwork before we bail
        self._flush_viewer_log_to_disk()
        
        current_type = getattr(self, '_current_output_type', None)
        if current_type:
            self.save_geometry_for_output_type(current_type)
        
        self.save_geometry_now()
        
        if self.controller:
            self.controller._save_current_ui_config_to_models()
            self.config_manager.flush_config()
        
        super().reject()

    def on_dialog_close(self):
        """Trap 3: Controller finished signal."""
        print("TRAP_ON_DIALOG_CLOSE")
        self._flush_viewer_log_to_disk()

    def _require_pm_ready(self, operation_name: str) -> bool:
        """Global safety pin for all PM-dependent operations."""
        if not hasattr(self, 'controller') or not self.controller:
            self.log_warning(f"{operation_name}: Controller not ready")
            return False
        if not getattr(self.controller, '_pm_ready', False):
            self.log_warning(f"{operation_name}: PM not initialized")
            return False
        return True
    #######################################################################
    #  geometry  (save only on close / manual call)
    #######################################################################
    def showEvent(self, event):
        """Only guard: verify PM has data before allowing interaction."""
        if not self._startup_complete:
            event.ignore()
            return
        super().showEvent(event)
        
        # catch profile swaps — re-read MO2 INI directly, no API
        current_profile = self.organizer_wrapper.refresh_profile()
        if getattr(self, '_last_profile', None) and self._last_profile != current_profile:
            self.log_info(f"Profile switch: {self._last_profile} -> {current_profile}")
            # rebuild config manager for new profile
            config_dir = Path(__file__).resolve().parent.parent / "data"
            self.config_manager = ConfigManager(
                self.file_ops,
                config_dir / PLUGIN_CONFIG_FILE_NAME,
                self.organizer_wrapper.profile_name,
            )
            # reseal welcome — force fresh scan
            ac = self.config_manager.get_application_config()
            ac.welcome_acknowledged = False
            ac.welcome_load_order_sig = ""
            self.config_manager.save_application_config(ac)
            # nuke PM so Frankie rebuilds from scratch
            if self.controller:
                self.controller._pm_init_done = False
                self.controller._pm_ready = False
                self.controller._pm_signals_wired = False
                self.controller.profile_manager = None
                self.controller.siloed_snoop = None
                if hasattr(self.controller, '_rich_silos'):
                    self.controller._rich_silos.clear()
                if hasattr(self.controller, '_plugin_to_mod_bridge'):
                    self.controller._plugin_to_mod_bridge.clear()
                # fire up Frankie immediately
                self.controller._deferred_pm_init()
            # reset geometry
            self._geometry_restored = False
            self._geometry_fully_restored = False
            # drop back to welcome
            self.panel_stack.setCurrentWidget(self.welcome_panel)
            self.game_version_group.setVisible(False)
            self.output_type_group.setVisible(False)
            self.advanced_settings_group.setVisible(False)
            self._last_profile = current_profile
            return
        self._last_profile = current_profile
        
        # PM guard - panels will retry if PM not ready
        if (hasattr(self, 'controller') and self.controller and 
            not getattr(self.controller, '_pm_ready', False)):
            self.log_info("DEFERRED_SHOW: PM warming...")

    def _get_current_output_type_name(self) -> str:
        """Return current output type string or empty if not set."""
        return getattr(self, '_current_output_type', '')

    def _delayed_restore(self, geom: QByteArray):
        """Restore geometry after window is fully visible."""
        success = self.restoreGeometry(geom)
        print(f"GEO-RESTORED: {len(geom)} bytes, success={success}, visible={self.isVisible()}")
        self._geometry_fully_restored = True

    def update_ui_for_output_type(self, output_type: str):
        """Switch panels, save old geometry, stage new geometry."""
        self.log_info(f"🔄 PANEL SWITCH: {output_type}")
        
        # Save current panel geometry BEFORE switch
        if hasattr(self, '_current_output_type') and self._current_output_type:
            self.save_geometry_for_output_type(self._current_output_type)
        
        # Switch panels
        new_panel = self._panel_map[output_type]
        self.panel_stack.setCurrentWidget(new_panel)
        new_panel.setEnabled(True)
        QTimer.singleShot(50, lambda: new_panel.setFocus())
        
        # ---- Single source of truth for sizing ----
        self.game_version_group.setMinimumHeight(50)
        self.game_version_group.setMaximumHeight(70)
        self.output_type_group.setMinimumHeight(50)
        self.output_type_group.setMaximumHeight(70)
        self.advanced_settings_group.setMaximumHeight(80)
        
        if output_type == "BOS INI":
            self.panel_stack.setMinimumHeight(420)
        else:
            self.panel_stack.setMinimumHeight(280)
        
        self.main_vertical_splitter.setStretchFactor(0, 0)
        self.main_vertical_splitter.setStretchFactor(1, 0)
        self.main_vertical_splitter.setStretchFactor(2, 1)
        self.main_vertical_splitter.setStretchFactor(3, 0)
        self.main_vertical_splitter.setCollapsible(0, False)
        self.main_vertical_splitter.setCollapsible(1, False)
        self.main_vertical_splitter.setCollapsible(2, False)
        
        # Button visibility
        is_sp = output_type == "SkyPatcher INI"
        is_bos = output_type == "BOS INI"
        self.sp_panel.generate_btn.setVisible(is_sp)
        self.bos_panel.generate_btn.setVisible(is_bos)
        
        # RESTORE: This was missing — why SP looked like BOS and BOS geom felt broken
        self._restore_geometry_for_output_type(output_type)
        
        self._current_output_type = output_type
        self.log_info(f"✅ PANEL SWITCH FINISHED")

    #######################################################################
    #  geometry helpers
    #######################################################################
    def save_geometry_now(self) -> None:
        """Save global window and splitter state."""
        self.geometry_manager.save_global("main_window_geometry", self.saveGeometry())
        self.geometry_manager.save_global("main_vertical_splitter", 
                                          self.main_vertical_splitter.saveState())

    def save_geometry_for_output_type(self, output_type: str) -> None:
        """Save panel-specific geometry."""
        namespace = "SkyPatcher" if output_type == "SkyPatcher INI" else "BOS"
    
        # Outer splitter (main vertical)
        self.geometry_manager.save(namespace, "outer_splitter",
                                   self.main_vertical_splitter.saveState())
    
        # Inner splitter (panel-specific)
        current_panel = self.panel_stack.currentWidget()
        if hasattr(current_panel, 'inner_splitter'):
            self.geometry_manager.save(namespace, "inner_splitter",
                                       current_panel.inner_splitter.saveState())

        # Save window geometry for this panel
        self.geometry_manager.save(namespace, "window_geometry", self.saveGeometry())

    def _restore_geometry_for_output_type(self, output_type: str) -> None:
        """Stage geometry for deferred restore."""
        namespace = "SkyPatcher" if output_type == "SkyPatcher INI" else "BOS"
    
        # Stage outer splitter
        geom = self.geometry_manager.load(namespace, "outer_splitter")
        if geom and not geom.isEmpty():
            self.main_vertical_splitter.restoreState(geom)
    
        # Stage inner for panel's showEvent
        current_panel = self.panel_stack.currentWidget()
        if hasattr(current_panel, 'inner_splitter'):
            self.geometry_manager.stage_restore(namespace, current_panel.inner_splitter, 
                                                "inner_splitter")

        # Restore window geometry
        win_geom = self.geometry_manager.load(namespace, "window_geometry")
        if win_geom and not win_geom.isEmpty():
            self.restoreGeometry(win_geom)
        else:
            # No saved geometry — let Qt handle it, don't guess
            pass

    #######################################################################
    #  live logger toggles
    #######################################################################
    def _live_debug_toggle(self, on: bool) -> None:
        level = logging.DEBUG if on else logging.INFO
        logging.getLogger("SkyGen").setLevel(level)
        self.log_info(f"Logger debug = {on}")

    def _live_trace_toggle(self, on: bool) -> None:
        if self.controller:
            self.controller.app_config.traceback_logging = on
        self.log_info(f"Traceback logging = {on}")

    #######################################################################
    #  builders
    #######################################################################
    def _build_game_version_group(self) -> None:
        self.game_version_group = QGroupBox("Game Version")
        lay = QHBoxLayout(self.game_version_group)
        lay.addWidget(QLabel("Game Version:"))
        self.game_version_se_radio = QRadioButton("SkyrimSE")
        self.game_version_vr_radio = QRadioButton("SkyrimVR")
        btn_grp = QButtonGroup(self)
        btn_grp.addButton(self.game_version_se_radio)
        btn_grp.addButton(self.game_version_vr_radio)
        lay.addWidget(self.game_version_se_radio)
        lay.addWidget(self.game_version_vr_radio)
        lay.addStretch(1)

    def _build_output_type_group(self) -> None:
        self.output_type_group = QGroupBox("Output Type")
        lay = QHBoxLayout(self.output_type_group)
        self.output_type_se_radio = QRadioButton("SkyPatcher INI")
        self.output_type_bos_radio = QRadioButton("BOS INI")
        btn_grp = QButtonGroup(self)
        for rb in (
            self.output_type_se_radio,
            self.output_type_bos_radio,
        ):
            btn_grp.addButton(rb)
        lay.addWidget(self.output_type_se_radio)
        lay.addWidget(self.output_type_bos_radio)
        lay.addStretch(1)

    def _build_advanced_settings_group(self) -> None:
        self.advanced_settings_group = QGroupBox("Dev Settings")
        lay = QVBoxLayout(self.advanced_settings_group)

        # hide button
        self.hide_dev_btn = QPushButton("Hide Dev Settings")
        self.hide_dev_btn.setCheckable(True)
        self.hide_dev_btn.toggled.connect(self._toggle_dev_settings)
        lay.addWidget(self.hide_dev_btn)

        # dev container (to hide)
        self.dev_container = QWidget()
        dev_layout = QVBoxLayout(self.dev_container)

        # warning label - only shows when dev section visible
        warning_label = QLabel("⚠️ Only modify these settings if you know what you're doing!")
        warning_label.setStyleSheet("color: #ff6b6b; font-weight: bold;")
        dev_layout.addWidget(warning_label)

        # keep only dev/debug stuff here
        self.debug_logging_checkbox = QCheckBox("Enable Debug Logging")
        self.traceback_logging_checkbox = QCheckBox("Enable Traceback Logging")
        self.loom_enabled_checkbox = QCheckBox("Enable Loom Auto-Keywords")
        self.loom_enabled_checkbox.setToolTip("Auto-weave keywords from record DNA — disables manual Sentence Builder")
        ac = self.config_manager.get_application_config()
        self.loom_enabled_checkbox.setChecked(getattr(ac, 'loom_enabled', False))

        ac = self.config_manager.get_application_config()
        if not DEBUG_MODE:
            self.debug_logging_checkbox.setChecked(ac.debug_logging)
            self.debug_logging_checkbox.setEnabled(True)
        else:
            self.debug_logging_checkbox.setChecked(True)
            self.debug_logging_checkbox.setEnabled(False)
        if not TRACEBACK_LOGGING:
            self.traceback_logging_checkbox.setChecked(ac.traceback_logging)
            self.traceback_logging_checkbox.setEnabled(True)
        else:
            self.traceback_logging_checkbox.setChecked(True)
            self.traceback_logging_checkbox.setEnabled(False)

        # Panic button — when config feels haunted, smash it
        self._panic_btn = QPushButton("💾 Config Panic Button")
        self._panic_btn.setToolTip("Emergency save — writes config to disk immediately")
        self._panic_btn.clicked.connect(self._on_panic_flush)
        # Audit button — context-aware
        self.audit_btn = QPushButton("🔍 Audit")
        self.audit_btn.setToolTip("Blacklist Auditor")
        self.audit_btn.clicked.connect(self._on_audit_clicked)

        # row: checkboxes on the left, action buttons on the right
        controls_row = QHBoxLayout()
        
        # left column — toggles
        checks_col = QVBoxLayout()
        checks_col.addWidget(self.debug_logging_checkbox)
        checks_col.addWidget(self.traceback_logging_checkbox)
        checks_col.addWidget(self.loom_enabled_checkbox)
        checks_col.addStretch()
        controls_row.addLayout(checks_col)
        
        # right column — buttons
        buttons_col = QVBoxLayout()
        buttons_col.addWidget(self._panic_btn)
        buttons_col.addWidget(self.audit_btn)
        buttons_col.addStretch()
        controls_row.addLayout(buttons_col)
        
        dev_layout.addLayout(controls_row)

        lay.addWidget(self.dev_container)

    def _toggle_dev_settings(self, hidden: bool) -> None:
        self.dev_container.setVisible(not hidden)
        self.hide_dev_btn.setText("Show Dev Settings" if hidden else "Hide Dev Settings")
        # update_ui_for_output_type hard-caps this group at 80px — kills the dev section when expanded
        self.advanced_settings_group.setMaximumHeight(80 if hidden else 400)

    def _on_panic_flush(self) -> None:
        """Emergency config save — bypasses normal close-event flow."""
        try:
            if self.controller:
                self.controller._save_current_ui_config_to_models()
            self.config_manager.flush_config()
            self.log_info("PANIC FLUSH: Config hammered to disk")
        except Exception as e:
            self.log_error(f"PANIC FLUSH failed: {e}")
    #######################################################################
    #  UI skeleton
    #######################################################################
    def _setup_ui(self) -> None:
        try:
            self.main_layout = QVBoxLayout(self)
            self.main_layout.setContentsMargins(10, 10, 10, 10)
            self.main_layout.setSpacing(10)
            
            # main horizontal splitter (left settings | right log)
            self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
            self.main_splitter.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            self.main_layout.addWidget(self.main_splitter)
            
            # left: settings panel
            self.settings_panel = QWidget()
            self.settings_panel.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            
            # SNM: Create vertical splitter ONCE
            self.main_vertical_splitter = QSplitter(Qt.Orientation.Vertical)
            self.main_vertical_splitter.setContentsMargins(0, 0, 0, 0)
            self.main_vertical_splitter.setHandleWidth(6)
            settings_main_layout = QVBoxLayout(self.settings_panel)
            settings_main_layout.setContentsMargins(0, 0, 0, 0)
            settings_main_layout.addWidget(self.main_vertical_splitter)
            
            self.main_splitter.addWidget(self.settings_panel)
            
            # right: log panel
            self.log_panel = QWidget()
            self.log_panel.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            self.log_layout = QVBoxLayout(self.log_panel)
            self.log_layout.setContentsMargins(0, 0, 0, 0)
            self.log_layout.setSpacing(5)
            self.log_panel.setMinimumWidth(300)
            self.main_splitter.addWidget(self.log_panel)
            self.status_log_widget.append_line("Ready", MO2_LOG_INFO)

            # build sections (creates the group boxes)
            self._build_game_version_group()
            self._build_output_type_group()

            # Hide configuration groups during welcome phase (revealed by _enter_workspace)
            self.game_version_group.setVisible(False)
            self.output_type_group.setVisible(False)

            self._build_patch_settings_stacked()
            self._build_advanced_settings_group()

            # Add to splitter in order
            self.main_vertical_splitter.addWidget(self.game_version_group)
            self.main_vertical_splitter.addWidget(self.output_type_group)
            self.main_vertical_splitter.addWidget(self.panel_stack)
            self.main_vertical_splitter.addWidget(self.advanced_settings_group)

            self.panel_stack.currentChanged.connect(self._on_panel_switched)
            
            # log widget
            self.log_layout.addWidget(self.status_log_widget)
            
            # bottom button row 
            bottom_row = QHBoxLayout()
            self.status_label = QLabel("Ready")
            bottom_row.addWidget(self.status_label)
            
            # Theme combo in button row
            bottom_row.addStretch()
            bottom_row.addWidget(QLabel("Theme:"))
            self.theme_combo = QComboBox()
            self.theme_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self.theme_combo.setMinimumWidth(120)
            bottom_row.addWidget(self.theme_combo)
            bottom_row.addSpacing(15)
            
            # Single Wiz button (context-aware)
            self.wiz_btn = QPushButton("Blacklist⚡ Wiz")
            self.wiz_btn.setToolTip("Launch BL Wizard")
            self.wiz_btn.clicked.connect(self._on_wiz_clicked)
            
            # Panel stop buttons
            bottom_row.addWidget(self.sp_panel.stop_button)
            bottom_row.addWidget(self.bos_panel.stop_btn)
            
            # Wiz button
            bottom_row.addWidget(self.wiz_btn)
            
            # Panel generate buttons
            bottom_row.addWidget(self.sp_panel.generate_btn)
            bottom_row.addWidget(self.bos_panel.generate_btn)
            
            bottom_row.addStretch()
            bottom_row.addWidget(self.close_button)
            
            self.main_layout.addLayout(bottom_row)
            
            # splitter behavior locks
            self.main_vertical_splitter.setMinimumHeight(400)
            self.main_splitter.setCollapsible(0, True)
            self.main_splitter.setCollapsible(1, True)
            self.main_vertical_splitter.setCollapsible(2, True)
            self._ui_built = True
            
        except Exception as e:
            self.log_critical(f"_setup_ui crashed: {e}", exc_info=True)
            raise

    #######################################################################
    #  panel injection
    #######################################################################
    def _build_patch_settings_stacked(self):
        self.panel_stack = QStackedWidget()
        
        # SP index 0, BOS index 1 (PRESERVED for geometry .dat compatibility)
        self.sp_panel = SkyPatcherPanel(self)
        self.bos_panel = BosPanel(self)
        self.panel_stack.addWidget(self.sp_panel)  # 0
        self.panel_stack.addWidget(self.bos_panel)  # 1
        
        # Welcome panel appended at index 2 (default visible)
        self.welcome_panel = WelcomePanel(self)
        self.panel_stack.addWidget(self.welcome_panel)  # 2
        self.panel_stack.setCurrentWidget(self.welcome_panel)
        
        self._panel_map = {
            "SkyPatcher INI": self.sp_panel,
            "BOS INI": self.bos_panel,
            "Welcome": self.welcome_panel,
        }

    def _enter_workspace(self):
        """User survived the welcome screen—unlocking workspace."""
        self.log_info("Welcome acknowledged—unlocking workspace")
        
        ac = self.config_manager.get_application_config()
        ac.welcome_acknowledged = True
        
        # Seal this acknowledgment to the current modlist signature
        current_sig = ""
        if self.controller:
            # Single source of truth: PM's SHA256 sig
            if self.controller.profile_manager:
                current_sig = self.controller.profile_manager.load_order_signature
                if current_sig:
                    ac.welcome_load_order_sig = current_sig
                    self.log_info(f"Welcome seal locked to: {current_sig}")
            
            if current_sig:
                ac.welcome_load_order_sig = current_sig
                self.log_info(f"Welcome seal locked to: {current_sig}")
        
        # Prevents close-event overwrite from stale reference
        if self.controller:
            self.controller.app_config = ac
            # Patch settings dangles the same way — UI signals look it up by name at runtime
            self.controller.patch_settings = ac.patch_settings
            
        self.config_manager.save_application_config(ac)
        
        # Reveal the engine controls
        self.game_version_group.setVisible(True)
        self.output_type_group.setVisible(True)
        self.advanced_settings_group.setVisible(True)
        
        # Restore dev section collapse state
        hidden = getattr(ac, 'dev_settings_hidden', True)
        self.hide_dev_btn.setChecked(hidden)
        self.dev_container.setVisible(not hidden)
        self.hide_dev_btn.setText("Show Dev Settings" if hidden else "Hide Dev Settings")
        
        # Continue to their last working panel
        ps = ac.patch_settings
        # Continue to their last working panel
        target_type = ac.output_type if ac.output_type else "SkyPatcher INI"
        self.set_output_type(target_type, adjust_size=False)
        
        self._restore_all_panel_settings()
        
        if self.controller:
            self.controller.refresh_silos()

    def _restore_all_panel_settings(self):
        """One place to shove INI values back into the UI. Both entry paths call this."""
        if not self.controller:
            return
            
        ps = self.controller.app_config.patch_settings
        
        # ---- SP ----
        if hasattr(self, "sp_panel"):
            sp = self.sp_panel
            
            # Muzzle category for the whole restore — nothing touches it until we're done
            sp.category_combo.blockSignals(True)
            
            # Shove values straight into widgets
            sp.target_mod_combo.setCurrentText(ps.target_mod)
            sp.source_mod_combo.setCurrentText(ps.source_mod)
            sp.category_combo.setCurrentText(ps.category)
            sp.output_folder_input.setText(ps.skypatcher_output_folder)
            
            # Keep the property getter honest so downstream code doesn't get confused
            sp._category = ps.category
            
            if hasattr(sp, "gen_modlist_cb"):
                sp.gen_modlist_cb.setChecked(ps.generate_modlist)
            if hasattr(sp, "gen_all_cats_cb"):
                sp.gen_all_cats_cb.setChecked(ps.generate_all_categories)
            
            # Build SB combos now that category is set
            if ps.category:
                sp._update_sentence_builder(ps.category)
            
            # Sentence Builder — shove saved values back
            if hasattr(sp, 'filter_combo'):
                sp.filter_combo.setCurrentText(ps.sp_filter_type)
            if hasattr(sp, 'action_combo'):
                sp.action_combo.setCurrentText(ps.sp_action_type)
            if hasattr(sp, 'value_combo'):
                sp.value_combo.setCurrentText(ps.sp_value_formid)
            if hasattr(sp, 'lmw_toggle'):
                sp.lmw_toggle.setChecked(ps.sp_lmw_winners_only)
            
            # Only now let category breathe — everything is settled
            sp.category_combo.blockSignals(False)
        
        # ---- BOS ----
        if hasattr(self, "bos_panel"):
            bos = self.bos_panel
            
            # Muzzle combos during restore
            bos.target_combo.blockSignals(True)
            bos.source_combo.blockSignals(True)
            if hasattr(bos, '_cat_combo'):
                bos._cat_combo.blockSignals(True)
            if hasattr(bos, 'scan_all_cb'):
                bos.scan_all_cb.blockSignals(True)
            
            bos.target_combo.setCurrentText(ps.bos_target_mod)
            bos.source_combo.setCurrentText(ps.bos_source_mod)
            if hasattr(bos, 'output_folder_input'):
                bos.output_folder_input.setText(ps.bos_output_folder)
            if hasattr(bos, 'scan_all_cb'):
                bos.scan_all_cb.setChecked(ps.bos_scan_all)
            # Sync UI state after restoring checkbox
            if hasattr(bos, '_on_scan_mode_changed'):
                bos._on_scan_mode_changed()
            
            # M2M
            if hasattr(bos, '_m2m_cat_combo') and ps.m2m_category:
                bos._m2m_cat_combo.setCurrentText(ps.m2m_category)
            if hasattr(bos, '_m2m_chance_spin') and ps.m2m_chance is not None:
                bos._m2m_chance_spin.setValue(ps.m2m_chance)
            
            # XYZ
            if ps.bos_xyz and ps.bos_xyz.startswith("("):
                clean = ps.bos_xyz.strip("()").replace("'", "").replace('"', "")
                values = [v.strip() for v in clean.split(",")]
                bos.xyz = tuple(values)
            elif ps.bos_xyz:
                bos.xyz = tuple(ps.bos_xyz.split(","))
            else:
                bos.xyz = ("0.0", "0.0", "0.0")
            
            bos.target_combo.blockSignals(False)
            bos.source_combo.blockSignals(False)
            if hasattr(bos, '_cat_combo'):
                bos._cat_combo.blockSignals(False)
            if hasattr(bos, 'scan_all_cb'):
                bos.scan_all_cb.blockSignals(False)
            
            if hasattr(bos, '_on_scan_mode_changed'):
                bos._on_scan_mode_changed()
        
        # Hook controller to panels and refresh button state
        self.controller.sp_panel = self.sp_panel
        self.controller.bos_panel = self.bos_panel
        self.controller._update_generate_button()

    #######################################################################
    #  initial data
    #######################################################################
    def _populate_initial_data(self) -> None:
        if not self._ui_built or self.controller is None:
            return
            
        ac = self.controller.app_config
        
        # Theme setup FIRST so users can switch during welcome if ghosting occurs
        # Theme setup — no "default" ghost text ever
        self._populate_theme_combobox()
        self.theme_combo.blockSignals(True)
        
        if ac.selected_theme and self.theme_combo.findText(ac.selected_theme) >= 0:
            self.theme_combo.setCurrentText(ac.selected_theme)
        elif self.theme_combo.count() > 0:
            # Saved theme missing or empty — grab first real item, never invent "default"
            self.theme_combo.setCurrentIndex(0)
            ac.selected_theme = self.theme_combo.currentText()
            self.config_manager.save_application_config(ac)
        else:
            # No themes at all — leave combo empty, no ghost text
            ac.selected_theme = ""
        
        self.theme_combo.blockSignals(False)
        if ac.selected_theme:
            self.theme_manager.apply_theme(ac.selected_theme)
        self.log_debug("Populating initial data from saved config.")
        
        # Determine if we should show the welcome screen:
        # 1. Never acknowledged before? → Show it
        # 2. Acknowledged, but modlist changed since then? → Reshow (safety reset)
        # Determine if we should show the welcome screen:
        # Guard assessment wins over config flag
        show_welcome = False
        guard_situation = "ready"  # Default
        
        # Ask Guard what we're dealing with (if available)
        if self.controller and hasattr(self.controller, 'guard'):
            guard_situation = self.controller.guard.assess_situation()
            
        if guard_situation in ["fresh", "bat_complete", "ml_change", "logic_change"]:
            # Guard says we need to scan - force welcome regardless of config
            show_welcome = True
            ac.welcome_acknowledged = False  # Reset so we show the panel
            self.log_info(f"Guard situation '{guard_situation}' - forcing welcome")
        elif not getattr(ac, 'welcome_acknowledged', False):
            # Never acknowledged ever
            show_welcome = True
            self.log_info("First run—welcome screen required")
        elif self.controller and self.controller.profile_manager:
            # Single source of truth: PM's SHA256 sig
            stored_sig = getattr(ac, 'welcome_load_order_sig', '')
            current_sig = self.controller.profile_manager.load_order_signature if self.controller.profile_manager else ''
            
            if current_sig and stored_sig != current_sig:
                show_welcome = True
                ac.welcome_acknowledged = False
                self.log_info(f"Modlist changed ({stored_sig[:8]} → {current_sig[:8]})—resealing welcome")
            elif not stored_sig and current_sig:
                # Migration: no sig stored yet, capture now without showing
                ac.welcome_load_order_sig = current_sig
                self.config_manager._do_write_ini()
                self.log_info(f"Migration: captured sig {current_sig}")
        
        if hasattr(self, 'welcome_panel') and show_welcome:
            self.panel_stack.setCurrentWidget(self.welcome_panel)
            self.game_version_group.setVisible(False)
            self.output_type_group.setVisible(False)
            self.advanced_settings_group.setVisible(False)  # <-- Hide dev section during welcome
            return  # Stop here. We'll finish setup after they click Continue.
        
        # OK, they're legit. Reveal the engine controls now that 
        # they've theoretically read the manual.
        self.game_version_group.setVisible(True)
        self.output_type_group.setVisible(True)
        ps = ac.patch_settings
        self.set_game_version(ac.game_version)
        self.set_output_type(ac.output_type, adjust_size=False)
        
        # Restore dev-section collapse state
        hidden = getattr(ac, 'dev_settings_hidden', False)
        self.hide_dev_btn.setChecked(hidden)
        self.dev_container.setVisible(not hidden)
        self.hide_dev_btn.setText("Show Dev Settings" if hidden else "Hide Dev Settings")

        # Make sure category combo has items before we try to pick one
        self._populate_category_combobox_initial()
        
        self._restore_all_panel_settings()

    #######################################################################
    #  combo helpers
    #######################################################################
    def _fill_combo(
        self, combo: QComboBox, items: list[str], keep_text: bool = True
    ) -> None:
        old = combo.currentText() if keep_text else ""
        combo.clear()
        combo.addItems([""] + sorted(items))
        if old and old in items:
            combo.setCurrentText(old)
        else:
            combo.setEditText(old)

    def trigger_silo_refresh(self) -> None:
        """Entry point: Trigger PM to emit filtered silo data."""
        self.log_info("🔌 TRIGGER_SILO_REFRESH: Delegating to controller")
        
        if self.controller:
            self.controller.refresh_silos()

    def _populate_category_combobox_initial(self) -> None:
        self.log_debug("Populating category combo box based on selected output type.")
        output_type = self.controller.app_config.output_type
        cats = sorted(
            SKYPATCHER_SUPPORTED_RECORD_TYPES
            if output_type == "SkyPatcher INI"
            else BOS_SUPPORTED_RECORD_TYPES
        )    
        old_category = (
            self.sp_panel.category
            if hasattr(self, "sp_panel") and hasattr(self.sp_panel, "category")
            else ""
        )
        self._fill_combo(self.sp_panel.category_combo, cats)
        if old_category and old_category in cats:
            self.sp_panel.category_combo.setCurrentText(old_category)
            self.log_debug(f"Restored category selection: {old_category}")

        if output_type == "BOS INI":
            self._fill_combo(self.bos_panel._cat_combo, cats)

    def _populate_theme_combobox(self) -> None:
        self.log_debug("Populating theme combo box.")
        themes = self.theme_manager.get_available_themes()
        self.theme_combo.clear()
        if themes:
            self.theme_combo.addItems(themes)
        # No fallback — "default" is dead, combo stays empty if no themes found

    #######################################################################
    #  one-time wire-up
    #######################################################################
    def wire_controller(self) -> None:
        """Connect controller to UI elements after initialization."""
        self.controller.debug_logging_checkbox = self.debug_logging_checkbox
        self.controller.traceback_logging_checkbox = self.traceback_logging_checkbox
        if self.controller is None:
            return

        self.log_debug("WIRE_CONTROLLER called – handing live widgets to controller.")
        self.controller.set_ui_widgets_for_access({
            "sp_panel": self.sp_panel,
            "bos_panel": self.bos_panel,
            "game_version_se_radio": self.game_version_se_radio,
            "game_version_vr_radio": self.game_version_vr_radio,
            "output_type_se_radio": self.output_type_se_radio,
            "output_type_bos_radio": self.output_type_bos_radio,
            "debug_logging_checkbox": self.debug_logging_checkbox,
            "traceback_logging_checkbox": self.traceback_logging_checkbox,
            "main_dialog": self,
            "plugin_extractor": self.plugin_extractor,
        })
        # connect theme combo here (after it exists)
        self.theme_combo.currentTextChanged.connect(
            lambda theme: self.theme_manager.apply_theme(theme)
        )
        # Hook up the welcome panel's two-gate security system:
        # Gate 1: They scrolled to the bottom (30px threshold)
        # Gate 2: The PM finished loading (panels_ready signal)
        # When both gates open AND they check the box, Continue enables.
        # Clicking Continue triggers _enter_workspace above—like turning a key.
        if hasattr(self, 'welcome_panel'):
            self.controller.panels_ready.connect(self.welcome_panel.on_panels_ready)
            self.welcome_panel.continue_clicked.connect(self._enter_workspace)
             
        self.controller._update_generate_button()
        # Populate initial data AFTER wiring is complete
        self._populate_initial_data()
        # ✅ CONNECT PANEL STOP BUTTONS TO CONTROLLER
        self.sp_panel.stop_button.clicked.connect(self.controller.on_stop_clicked)
        self.bos_panel.stop_btn.clicked.connect(self.controller.on_stop_clicked)  # If BOS has one

        self.log_debug("Initial silo refresh deferred to first panel show")
        # trigger_silo_refresh() moved to panel showEvent - MO2 profile guaranteed active by then

    #######################################################################
    #  simple setters
    #######################################################################
    def set_game_version(self, version: str) -> None:
        (
            self.game_version_se_radio
            if version == "SkyrimSE"
            else self.game_version_vr_radio
        ).setChecked(True)

    def set_output_type(self, output_type: str, adjust_size: bool = True) -> None:
        for rb, txt in (
            (self.output_type_se_radio, "SkyPatcher INI"),
            (self.output_type_bos_radio, "BOS INI"),
        ):
            if txt == output_type:
                rb.setChecked(True)
                break
        self.update_ui_for_output_type(output_type)

    def _on_panel_switched(self, index: int) -> None:
        """Ensure panel resizes correctly when switched."""
        self.layout().activate()
        QTimer.singleShot(0, lambda: self.layout().activate())

    def set_activity_indicator(self, active: bool) -> None:
        """Future spinner placeholder."""
        self.status_label.setText("Working…" if active else "Ready")
        # self.status_label.setText("Working…" if active else "Ready")
        # self.log_info(f"Activity indicator {'on' if active else 'off'}.")
        pass

    def _on_audit_clicked(self) -> None:
        """Route to active silo."""
        silo = "SP" if self.panel_stack.currentIndex() == 0 else "BOS"
        self.controller.launch_auditor(silo)

    def _on_wiz_clicked(self) -> None:
        """Route to active silo."""
        silo = "SP" if self.panel_stack.currentIndex() == 0 else "BOS"
        self.controller.launch_wizard(silo)