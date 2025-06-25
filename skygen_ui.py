import mobase
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QComboBox, QFileDialog, QCheckBox, QGroupBox, QRadioButton, QWidget, QSizePolicy,
    QListWidget, QListWidgetItem
)
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt, QSize
from pathlib import Path
import os
import json
import logging # Import logging directly here
import shlex # Import shlex for startApplication args splitting
from typing import Any, Optional, Union

# IMPORTANT: Changed to import the module directly
from . import skygen_file_utilities

# Import MO2_LOG_* constants from the new constants file
from .skygen_constants import (
    MO2_LOG_CRITICAL, MO2_LOG_ERROR, MO2_LOG_WARNING, MO2_LOG_INFO,
    MO2_LOG_DEBUG, MO2_LOG_TRACE
)

# Get the shared logger instance that __init__.py also uses
_shared_plugin_logger_ui = logging.getLogger('skygen')


class OrganizerWrapper:
    """
    A wrapper class for the mobase.IOrganizer interface to handle logging.
    This wrapper ensures that all logging goes through the shared `skygen` logger.
    """
    def __init__(self, organizer: 'mobase.IOrganizer'):
        super().__init__()
        self._organizer = organizer
        self.dialog_instance: Optional[Any] = None
        self._logger = _shared_plugin_logger_ui # Use the shared logger instance
        self._logging_configured = False # Flag to track if file logging is set up

    def set_log_file_path(self, path: Path):
        """
        Configures the FileHandler for the shared skygen logger using the
        make_file_logger function from skygen_file_utilities.
        """
        configured_logger_func = skygen_file_utilities.make_file_logger(path)
        if configured_logger_func:
            self._logging_configured = True
            # We don't need to store the logger_func returned by make_file_logger
            # as our log method will now directly use _shared_plugin_logger_ui
            self.log(MO2_LOG_INFO, f"SkyGen: (Wrapper) Log file configured via make_file_logger: {path}")
        else:
            self._logging_configured = False
            # Fallback to print if make_file_logger failed
            print(f"SkyGen: (Wrapper) ERROR: Failed to configure file logger for '{path}'. Messages will print to console.")


    def log(self, mo2_log_level: int, message: str, exc_info: bool = False):
        """
        Maps MO2 log levels to Python logging levels and logs the message
        using the shared logger instance.
        `exc_info` can be set to True to include exception information.
        """
        log_level_map = {
            MO2_LOG_CRITICAL: logging.CRITICAL,
            MO2_LOG_ERROR: logging.ERROR,
            MO2_LOG_WARNING: logging.WARNING,
            MO2_LOG_INFO: logging.INFO,
            MO2_LOG_DEBUG: logging.DEBUG,
            MO2_LOG_TRACE: logging.DEBUG # Map TRACE to DEBUG
        }
        python_log_level = log_level_map.get(mo2_log_level, logging.INFO)
        
        # Log to the shared logger instance
        _shared_plugin_logger_ui.log(python_log_level, message, exc_info=exc_info)

        # Fallback to console print if the file handler somehow isn't working
        # and we are in a state where we expect logs to go to file.
        # This is a belt-and-suspenders approach for debugging.
        if not self._logging_configured and python_log_level >= logging.INFO: # Only print INFO and above for console fallback
            level_name = {
                MO2_LOG_CRITICAL: "CRITICAL", MO2_LOG_ERROR: "ERROR", MO2_LOG_WARNING: "WARNING",
                MO2_LOG_INFO: "INFO", MO2_LOG_DEBUG: "DEBUG", MO2_LOG_TRACE: "TRACE"
            }.get(mo2_log_level, "UNKNOWN")
            print(f"SkyGen: [{level_name}] {message}")


    def close_log_file(self):
        """
        Closes any active file handlers associated with the shared logger.
        """
        self._logger.info("SkyGen: (Wrapper) Attempting to close file handlers for SkyGen logger.")
        for handler in list(self._logger.handlers):
            if isinstance(handler, logging.FileHandler):
                self._logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception as e:
                    self._logger.warning(f"SkyGen: (Wrapper) Failed to close log file handler: {e}", exc_info=True)
        self._logging_configured = False # Mark as de-initialized

    # --- Delegated MO2 Organizer Methods ---
    # These methods simply pass calls to the actual mobase.IOrganizer instance.
    # Added robust error handling and logging for each.

    def pluginList(self):
        try: return self._organizer.pluginList()
        except Exception as e: self.log(MO2_LOG_ERROR, f"Error in pluginList: {e}", exc_info=True); return []
    
    def getExecutables(self):
        try: return self._organizer.getExecutables()
        except Exception as e: self.log(MO2_LOG_ERROR, f"Error in getExecutables: {e}", exc_info=True); return {}
    
    def modsPath(self):
        try: return self._organizer.modsPath()
        except Exception as e: self.log(MO2_LOG_ERROR, f"Error in modsPath: {e}", exc_info=True); return ""

    def startApplication(self, name, args, cwd):
        try:
            # MO2's startApplication expects a list for args, so ensure it's converted if not
            if isinstance(args, str):
                args = shlex.split(args) # Use shlex to correctly split string args
            return self._organizer.startApplication(name, args, cwd)
        except Exception as e:
            self.log(MO2_LOG_ERROR, f"Error starting application '{name}': {e}", exc_info=True); return None

    def basePath(self):
        try: return self._organizer.basePath()
        except Exception as e: self.log(MO2_LOG_ERROR, f"Error in basePath: {e}", exc_info=True); return ""

    def pluginDataPath(self):
        try: return self._organizer.pluginDataPath()
        except Exception as e: self.log(MO2_LOG_ERROR, f"Error in pluginDataPath: {e}", exc_info=True); return ""

    def profilePath(self):
        try: return self._organizer.profilePath()
        except Exception as e: self.log(MO2_LOG_ERROR, f"Error in profilePath: {e}", exc_info=True); return ""

    def gameInfo(self):
        try: return self._organizer.gameInfo()
        except Exception as e: self.log(MO2_LOG_ERROR, f"Error in gameInfo: {e}", exc_info=True); return None

    def gameFeatures(self):
        try: return self._organizer.gameFeatures()
        except Exception as e: self.log(MO2_LOG_ERROR, f"Error in gameFeatures: {e}", exc_info=True); return []

    def modList(self):
        try: return self._organizer.modList()
        except Exception as e: self.log(MO2_LOG_ERROR, f"Error in modList: {e}", exc_info=True); return []

    def modPath(self, mod_name: str) -> str:
        try: return self._organizer.modPath(mod_name)
        except Exception as e: self.log(MO2_LOG_ERROR, f"Error in modPath for '{mod_name}': {e}", exc_info=True); return ""
    
    def currentGame(self):
        try: return self._organizer.currentGame()
        except Exception as e: self.log(MO2_LOG_ERROR, f"Error in currentGame: {e}", exc_info=True); return None


# Dummy classes for PyQt6 if not available.
try:
    from PyQt6.QtWidgets import QWidget, QApplication, QMessageBox, QLabel, QLineEdit, QPushButton, QComboBox, QVBoxLayout, QHBoxLayout, QFileDialog, QCheckBox, QGroupBox, QRadioButton, QSizePolicy, QListWidget, QListWidgetItem
    from PyQt6.QtGui import QIcon
    from PyQt6.QtCore import Qt, QSize
except ImportError:
    # Define dummy classes if PyQt6 is not installed
    class QWidget:
        def __init__(self, *args, **kwargs): pass
        def show(self): pass
        def close(self): pass
        def setWindowTitle(self, title): pass
        def setLayout(self, layout): pass
        def setFixedSize(self, width, height): pass
        def setSizePolicy(self, policy): pass
        def isVisible(self): return False
        def setVisible(self, visible): pass
        def setEnabled(self, enabled): pass

    class QApplication:
        _instance = None
        def __init__(self, *args, **kwargs):
            if not QApplication._instance:
                QApplication._instance = self
        @staticmethod
        def instance(): return QApplication._instance
        def exec(self): return 0
        def exec_(self): return 0 # For compatibility with Python 3.8+

    class QMessageBox:
        @staticmethod
        def critical(parent, title, message): _shared_plugin_logger_ui.critical(f"UI_CRITICAL: {title}: {message}")
        @staticmethod
        def warning(parent, title, message): _shared_plugin_logger_ui.warning(f"UI_WARNING: {title}: {message}")
        @staticmethod
        def information(parent, title, message): _shared_plugin_logger_ui.info(f"UI_INFO: {title}: {message}")

    class QLabel:
        def __init__(self, *args, **kwargs): pass
    class QLineEdit:
        def __init__(self, *args, **kwargs): pass
        def text(self): return ""
        def setText(self, text): pass
        def setPlaceholderText(self, text): pass
        def textChanged(self): return type('signal', (object,), {'connect': lambda *args: None})() # Dummy signal
    class QPushButton:
        def __init__(self, *args, **kwargs): pass
        def clicked(self): return type('signal', (object,), {'connect': lambda *args: None})() # Dummy signal
    class QComboBox:
        def __init__(self, *args, **kwargs): pass
        def addItems(self, items): pass
        def addItem(self, item): pass
        def clear(self): pass
        def setEditable(self, editable): pass
        def setPlaceholderText(self, text): pass
        def currentText(self): return ""
        def setCurrentIndex(self, index): pass
        def findText(self, text): return -1
        def activated(self): return type('signal', (object,), {'connect': lambda *args: None})() # Dummy signal
        def setEnabled(self, enabled): pass
    class QVBoxLayout:
        def __init__(self, *args, **kwargs): pass
        def addWidget(self, widget, stretch=0, alignment=0): pass
        def addLayout(self, layout, stretch=0): pass
        def setContentsMargins(self, left, top, right, bottom): pass
    class QHBoxLayout:
        def __init__(self, *args, **kwargs): pass
        def addWidget(self, widget, stretch=0, alignment=0): pass
        def addLayout(self, layout, stretch=0): pass
        def addStretch(self, stretch=0): pass
    class QFileDialog:
        @staticmethod
        def getExistingDirectory(parent, caption, directory): return ""
        @staticmethod
        def getOpenFileName(parent, caption, directory, filter): return ("", "")
    class QCheckBox:
        def __init__(self, *args, **kwargs): pass
        def isChecked(self): return False
        def setChecked(self, checked): pass
        def stateChanged(self): return type('signal', (object,), {'connect': lambda *args: None})() # Dummy signal
    class QGroupBox:
        def __init__(self, *args, **kwargs): pass
        def setLayout(self, layout): pass
        def setVisible(self, visible): pass
    class QRadioButton:
        def __init__(self, *args, **kwargs): pass
        def isChecked(self): return False
        def setChecked(self, checked): pass
        def toggled(self): return type('signal', (object,), {'connect': lambda *args: None})() # Dummy signal
    class QSizePolicy:
        Preferred = 0
        Expanding = 0
        def __init__(self, policy1, policy2): pass
    class QListWidget:
        def __init__(self, *args, **kwargs): pass
    class QListWidgetItem:
        def __init__(self, *args, **kwargs): pass

    class QIcon:
        def __init__(self, *args, **kwargs): pass
    class QSize:
        def __init__(self, *args, **kwargs): pass
    class Qt:
        WindowContextHelpButtonHint = 0
        ApplicationModal = 0
        WindowStaysOnTopHint = 0
        # Dummy CheckState for Qt
        class CheckState:
            Checked = type('Checked', (object,), {'value': 2})
            Unchecked = type('Unchecked', (object,), {'value': 0})
        # Dummy Dialog result
        Accepted = 1
        Rejected = 0
    class shlex: # Added dummy shlex
        @staticmethod
        def split(s): return s.split() if s else [] # Basic split for dummy


class SkyGenToolDialog(QDialog):
    """
    The main UI dialog for the SkyGen plugin tool.
    """
    def __init__(self, wrapped_organizer: OrganizerWrapper, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.wrapped_organizer = wrapped_organizer
        self.setWindowTitle("SkyGen - Automate Your Modding!")
        self.setFixedSize(500, 600)
        # Corrected typo: WindowContextHelpHelpButtonHint to WindowContextHelpButtonHint
        if hasattr(Qt, 'WindowContextHelpButtonHint'):
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        else:
            self.wrapped_organizer.log(MO2_LOG_WARNING, "SkyGen: WARNING: Qt.WindowContextHelpButtonHint not found. Skipping context help button removal.")
        
        self.selected_output_type = "SkyPatcher YAML"
        self.selected_game_version = ""
        self.selected_target_mod_name = ""
        self.selected_source_mod_name = ""
        self.selected_category = ""
        self.output_folder_path = ""
        self.igpc_json_path = ""
        self.determined_xedit_exe_path: Optional[Path] = None
        self.determined_xedit_executable_name: str = ""
        self.game_root_path: Optional[Path] = None
        self.generate_all = False
        self.executables_dict = {}
        self.pre_exported_xedit_json_path = ""
        self.all_exported_target_bases_by_formid: dict = {} 


        self._setup_ui()
        self._populate_game_versions()
        self._populate_categories()
        self._load_config()


    def showEvent(self, event):
        super().showEvent(event)
        self.wrapped_organizer.log(MO2_LOG_DEBUG, "SkyGen: DEBUG: showEvent triggered. Populating mods now.")
        self._populate_mods()


    def _setup_ui(self):
        """Sets up the layout and widgets of the dialog."""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)

        output_type_group = QGroupBox("Select Output Type")
        output_type_layout = QHBoxLayout()
        self.yaml_radio = QRadioButton("SkyPatcher YAML")
        self.bos_ini_radio = QRadioButton("BOS INI")
        
        self.yaml_radio.setChecked(True)
        self.yaml_radio.toggled.connect(self._on_output_type_toggled)
        self.bos_ini_radio.toggled.connect(self._on_output_type_toggled)
        
        output_type_layout.addWidget(self.yaml_radio)
        output_type_layout.addWidget(self.bos_ini_radio)
        output_type_layout.addStretch(1)
        output_type_group.setLayout(output_type_layout)
        main_layout.addWidget(output_type_group)

        general_settings_group = QGroupBox("General Settings")
        general_settings_layout = QVBoxLayout()

        game_version_group = QGroupBox("Game Version")
        game_version_layout = QHBoxLayout()
        self.sse_radio = QRadioButton("SkyrimSE/AE")
        self.vr_radio = QRadioButton("SkyrimVR")
        
        self.sse_radio.toggled.connect(lambda: self._on_game_version_radio_toggled("SkyrimSE"))
        self.vr_radio.toggled.connect(lambda: self._on_game_version_radio_toggled("SkyrimVR"))

        game_version_layout.addWidget(self.sse_radio)
        game_version_layout.addWidget(self.vr_radio)
        game_version_layout.addStretch(1)
        game_version_group.setLayout(game_version_layout)
        general_settings_layout.addWidget(game_version_group)

        output_folder_layout = QHBoxLayout()
        output_folder_label = QLabel("Output Folder:")
        self.output_folder_lineEdit = QLineEdit()
        self.output_folder_lineEdit.setPlaceholderText("Path where generated files will be saved")
        self.output_folder_browse_button = QPushButton("Browse...")
        self.output_folder_browse_button.clicked.connect(self._browse_output_folder)
        
        output_folder_layout.addWidget(output_folder_label)
        output_folder_layout.addWidget(self.output_folder_lineEdit)
        output_folder_layout.addWidget(self.output_folder_browse_button)
        general_settings_layout.addLayout(output_folder_layout)

        general_settings_group.setLayout(general_settings_layout)
        main_layout.addWidget(general_settings_group)


        self.yaml_settings_group = QGroupBox("SkyPatcher YAML Settings")
        yaml_settings_layout = QVBoxLayout()

        target_mod_layout = QHBoxLayout()
        target_mod_label = QLabel("Target Mod:")
        self.target_mod_combo = QComboBox()
        self.target_mod_combo.setEditable(True)
        self.target_mod_combo.setPlaceholderText("Select the mod you are patching TO (e.g., DynDOLOD Output)")
        self.target_mod_combo.activated.connect(self._on_target_mod_selected)
        target_mod_layout.addWidget(target_mod_label)
        target_mod_layout.addWidget(self.target_mod_combo)
        yaml_settings_layout.addLayout(target_mod_layout)

        source_mod_layout = QHBoxLayout()
        source_mod_label = QLabel("Source Mod:")
        self.source_mod_combo = QComboBox()
        self.source_mod_combo.setEditable(True)
        self.source_mod_combo.setPlaceholderText("Select the mod you are patching FROM (e.g., Enhanced Landscapes)")
        self.source_mod_combo.activated.connect(self._on_source_mod_selected)
        source_mod_layout.addWidget(source_mod_label)
        source_mod_layout.addWidget(self.source_mod_combo)
        yaml_settings_layout.addLayout(source_mod_layout)

        self.generate_all_checkbox = QCheckBox("Generate YAML for all compatible source mods (vs. selected source)")
        self.generate_all_checkbox.setChecked(False)
        self.generate_all_checkbox.stateChanged.connect(self._on_generate_all_toggled)
        yaml_settings_layout.addWidget(self.generate_all_checkbox)

        category_layout = QHBoxLayout()
        category_label = QLabel("Category (Record Type):")
        self.category_combo = QComboBox()
        self.category_combo.setPlaceholderText("e.g., STAT, TREE, GRAS")
        self.category_combo.setEditable(True)
        self.category_combo.activated.connect(self._on_category_selected)
        category_layout.addWidget(category_label)
        category_layout.addWidget(self.category_combo)
        yaml_settings_layout.addLayout(category_layout)

        keywords_layout = QHBoxLayout()
        keywords_label = QLabel("Keywords (comma-separated):")
        self.keywords_lineEdit = QLineEdit()
        self.keywords_lineEdit.setPlaceholderText("Optional: e.g., pine, oak, rock")
        self.keywords_lineEdit.textChanged.connect(self._on_keywords_changed)
        keywords_layout.addWidget(keywords_label)
        keywords_layout.addWidget(self.keywords_lineEdit)
        yaml_settings_layout.addLayout(keywords_layout)
        
        self.broad_category_swap_checkbox = QCheckBox("Enable Broad Category Swap (experimental)")
        self.broad_category_swap_checkbox.setChecked(False)
        yaml_settings_layout.addWidget(self.broad_category_swap_checkbox)

        self.yaml_settings_group.setLayout(yaml_settings_layout)
        main_layout.addWidget(self.yaml_settings_group)


        self.bos_ini_settings_group = QGroupBox("BOS INI Settings")
        bos_ini_layout = QVBoxLayout()
        
        igpc_json_layout = QHBoxLayout()
        igpc_json_label = QLabel("IGPC JSON Path:")
        self.igpc_json_lineEdit = QLineEdit()
        self.igpc_json_lineEdit.setPlaceholderText("Path to IGPC_DynaDOLOD.json")
        self.igpc_json_browse_button = QPushButton("Browse...")
        self.igpc_json_browse_button.clicked.connect(self._browse_igpc_json)

        igpc_json_layout.addWidget(igpc_json_label)
        igpc_json_layout.addWidget(self.igpc_json_lineEdit)
        igpc_json_layout.addWidget(self.igpc_json_browse_button)
        bos_ini_layout.addLayout(igpc_json_layout)

        self.bos_ini_settings_group.setLayout(bos_ini_layout)
        main_layout.addWidget(self.bos_ini_settings_group)
        self.bos_ini_settings_group.setVisible(False)


        button_layout = QHBoxLayout()
        self.generate_button = QPushButton("Generate")
        self.generate_button.clicked.connect(self.accept)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)

        button_layout.addStretch(1)
        button_layout.addWidget(self.generate_button)
        button_layout.addWidget(self.cancel_button)
        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)


    def _populate_game_versions(self):
        current_game_type = None
        current_game_name = "SkyrimSE"

        try:
            if hasattr(self.wrapped_organizer, 'currentGame') and self.wrapped_organizer.currentGame() is not None:
                current_game_type = self.wrapped_organizer.currentGame().type()
                if hasattr(mobase, 'GameType'):
                    if current_game_type == mobase.GameType.SSE:
                        current_game_name = "SkyrimSE"
                    elif current_game_type == mobase.GameType.SkyrimVR:
                        current_game_name = "SkyrimVR"
                    else:
                        self.wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: INFO: Current game type {current_game_type} not explicitly supported by SkyGen. Defaulting to SkyrimSE/AE.")
                        current_game_name = "SkyrimSE"
                else:
                    self.wrapped_organizer.log(MO2_LOG_WARNING, "SkyGen: WARNING: mobase.GameType not found. Assuming current game is SkyrimSE/AE for initial UI setup.")
                    current_game_name = "SkyrimSE"
        except Exception as e:
            self.wrapped_organizer.log(MO2_LOG_WARNING, f"SkyGen: WARNING: Could not determine current game type from organizer: {e}. Defaulting to SkyrimSE/AE.")
            current_game_name = "SkyrimSE"

        if current_game_name == "SkyrimSE":
            self.sse_radio.setChecked(True)
            self.selected_game_version = "SkyrimSE"
        elif current_game_name == "SkyrimVR":
            self.vr_radio.setChecked(True)
            self.selected_game_version = "SkyrimVR"
        else:
            self.sse_radio.setChecked(True)
            self.selected_game_version = "SkyrimSE"

        self.wrapped_organizer.log(MO2_LOG_DEBUG, f"SkyGen: Initial game version set to: {self.selected_game_version} (via radio buttons).")


    def _on_game_version_radio_toggled(self, version: str):
        if (version == "SkyrimSE" and self.sse_radio.isChecked()) or \
           (version == "SkyrimVR" and self.vr_radio.isChecked()):
            self.selected_game_version = version
            self.wrapped_organizer.log(MO2_LOG_DEBUG, f"SkyGen: Game version selected via radio: {self.selected_game_version}")
            self._save_config()


    def _populate_categories(self):
        common_categories = [
            "ARMO", "WEAP", "AMMO", "MISC", "STAT", "TREE", "GRAS", "FLOR", "CONT",
            "LIGH", "CELL", "WRLD", "QUST", "SPEL", "ENCH", "COBJ", "ALCH", "BOOK",
            "KEYM", "SCRL", "SLGM", "SOUL", "LVLI", "ACTI", "APPA", "ARMA", "CCEM",
            "CSTY", "DOOR", "EFSH", "IDLE", "IMAD", "LCTN", "MGEF", "MOVE", "MSTT",
            "PMIS", "PROJ", "PWAT", "REGN", "SGST", "SMQN", "SNCT", "SNDR", "TXST",
            "VTYP", "WATR", "WRLD", "ZOOM", "GMST"
        ]
        self.category_combo.addItems(sorted(common_categories))
        if common_categories:
            self.selected_category = self.category_combo.currentText()


    def _populate_mods(self):
        mod_list = self.wrapped_organizer.modList()
        active_mods = []
        for mod_name in mod_list.allMods():
            if mod_list.state(mod_name) & mobase.ModState.ACTIVE:
                display_name = mod_list.displayName(mod_name)
                active_mods.append(display_name)

        active_mods.sort(key=str.lower)
        
        self.target_mod_combo.clear()
        self.source_mod_combo.clear()

        self.target_mod_combo.addItem("")
        self.source_mod_combo.addItem("")

        self.target_mod_combo.addItems(active_mods)
        self.source_mod_combo.addItems(active_mods)

        if active_mods:
            default_target_mods = ["DynDOLOD Output", "TexGen Output", "MergePlugins", "Smashed Patch"]
            for default_mod in default_target_mods:
                if default_mod in active_mods:
                    self.target_mod_combo.setCurrentIndex(self.target_mod_combo.findText(default_mod))
                    self.selected_target_mod_name = default_mod
                    break
            
            if not self.selected_target_mod_name and active_mods:
                self.target_mod_combo.setCurrentIndex(1)
                self.selected_target_mod_name = self.target_mod_combo.currentText()

            if active_mods:
                self.source_mod_combo.setCurrentIndex(1)
                self.selected_source_mod_name = self.source_mod_combo.currentText()


    def _browse_output_folder(self):
        current_path = self.output_folder_lineEdit.text() if self.output_folder_lineEdit.text() else str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder", current_path)
        if folder:
            self.output_folder_path = folder
            self.output_folder_lineEdit.setText(folder)
            self.wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Output folder set to: {folder}")


    def _browse_igpc_json(self):
        current_path = self.igpc_json_lineEdit.text() if self.igpc_json_lineEdit.text() else str(Path.home())
        file_path, _ = QFileDialog.getOpenFileName(self, "Select IGPC JSON File", current_path, "JSON Files (*.json)")
        if file_path:
            self.igpc_json_path = file_path
            self.igpc_json_lineEdit.setText(file_path)
            self.wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: IGPC JSON file set to: {file_path}")


    def _on_output_type_toggled(self):
        if self.yaml_radio.isChecked():
            self.selected_output_type = "SkyPatcher YAML"
            self.yaml_settings_group.setVisible(True)
            self.bos_ini_settings_group.setVisible(False)
            self.generate_all_checkbox.setVisible(True)
            self.wrapped_organizer.log(MO2_LOG_DEBUG, "SkyGen: Output type set to SkyPatcher YAML.")
        elif self.bos_ini_radio.isChecked():
            self.selected_output_type = "BOS INI"
            self.yaml_settings_group.setVisible(False)
            self.bos_ini_settings_group.setVisible(True)
            self.generate_all_checkbox.setVisible(False)
            self.wrapped_organizer.log(MO2_LOG_DEBUG, "SkyGen: Output type set to BOS INI.")
        self._save_config()


    def _on_target_mod_selected(self):
        self.selected_target_mod_name = self.target_mod_combo.currentText()
        self.wrapped_organizer.log(MO2_LOG_DEBUG, f"SkyGen: Target mod selected: {self.selected_target_mod_name}")
        self._save_config()


    def _on_source_mod_selected(self):
        self.selected_source_mod_name = self.source_mod_combo.currentText()
        self.wrapped_organizer.log(MO2_LOG_DEBUG, f"SkyGen: Source mod selected: {self.selected_source_mod_name}")
        self._save_config()


    def _on_category_selected(self):
        self.selected_category = self.category_combo.currentText().upper()
        self.wrapped_organizer.log(MO2_LOG_DEBUG, f"SkyGen: Category selected: {self.selected_category}")
        self.category_combo.setCurrentText(self.selected_category)
        self._save_config()


    def _on_keywords_changed(self):
        self.keywords_lineEdit.setText(self.keywords_lineEdit.text().lower())
        self._save_config()


    def _on_generate_all_toggled(self, state):
        self.generate_all = (state == Qt.CheckState.Checked.value)
        self.source_mod_combo.setEnabled(not self.generate_all)
        self.wrapped_organizer.log(MO2_LOG_DEBUG, f"SkyGen: Generate All checkbox toggled: {self.generate_all}")
        self._save_config()


    def _get_config_path(self) -> Path:
        return Path(self.wrapped_organizer.pluginDataPath()) / "SkyGen" / "config.json"


    def _load_config(self):
        config_path = self._get_config_path()
        if config_path.is_file():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                output_type = config.get("output_type", "SkyPatcher YAML")
                if output_type == "SkyPatcher YAML":
                    self.yaml_radio.setChecked(True)
                else:
                    self.bos_ini_radio.setChecked(True)
                self._on_output_type_toggled()
                
                loaded_game_version = config.get("game_version", "SkyrimSE")
                if loaded_game_version == "SkyrimSE":
                    self.sse_radio.setChecked(True)
                elif loaded_game_version == "SkyrimVR":
                    self.vr_radio.setChecked(True)
                self.selected_game_version = loaded_game_version


                self.output_folder_lineEdit.setText(config.get("output_folder_path", str(Path(self.wrapped_organizer.basePath()) / "overwrite")))
                self.output_folder_path = self.output_folder_lineEdit.text()

                self.target_mod_combo.setCurrentIndex(
                    self.target_mod_combo.findText(config.get("target_mod_name", ""))
                )
                self.source_mod_combo.setCurrentIndex(
                    self.source_mod_combo.findText(config.get("source_mod_name", ""))
                )
                self.category_combo.setCurrentIndex(
                    self.category_combo.findText(config.get("category", ""))
                )
                self.keywords_lineEdit.setText(config.get("keywords", ""))
                self.broad_category_swap_checkbox.setChecked(config.get("broad_category_swap_enabled", False))
                self.generate_all_checkbox.setChecked(config.get("generate_all", False))

                self.igpc_json_lineEdit.setText(config.get("igpc_json_path", ""))
                self.igpc_json_path = self.igpc_json_lineEdit.text()

                self.determined_xedit_exe_path = Path(config.get("xedit_exe_path", "")) if config.get("xedit_exe_path") else None
                self.determined_xedit_executable_name = config.get("xedit_mo2_name", "")

                self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: Settings loaded successfully.")
            except Exception as e:
                self.wrapped_organizer.log(MO2_LOG_ERROR, f"SkyGen: ERROR: Failed to load settings from config.json: {e}", exc_info=True)
        else:
            self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: config.json not found, using default settings.")
            self.output_folder_path = str(Path(self.wrapped_organizer.basePath()) / "overwrite")
            self.output_folder_lineEdit.setText(self.output_folder_path)


    def _save_config(self):
        config_path = self._get_config_path()
        config_data = {
            "output_type": self.selected_output_type,
            "game_version": self.selected_game_version,
            "output_folder_path": self.output_folder_lineEdit.text(),
            "target_mod_name": self.target_mod_combo.currentText(),
            "source_mod_name": self.source_mod_combo.currentText(),
            "category": self.category_combo.currentText(),
            "keywords": self.keywords_lineEdit.text(),
            "broad_category_swap_enabled": self.broad_category_swap_checkbox.isChecked(),
            "generate_all": self.generate_all_checkbox.isChecked(),
            "igpc_json_path": self.igpc_json_lineEdit.text(),
            "xedit_exe_path": str(self.determined_xedit_exe_path) if self.determined_xedit_exe_path else "",
            "xedit_mo2_name": self.determined_xedit_executable_name
        }
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4)
            self.wrapped_organizer.log(MO2_LOG_DEBUG, "SkyGen: Settings saved.")
        except Exception as e:
            self.wrapped_organizer.log(MO2_LOG_ERROR, f"SkyGen: ERROR: Failed to save settings to config.json: {e}", exc_info=True)
            self.showError("Save Error", f"Failed to save settings: {e}")


    def showError(self, title: str, message: str):
        QMessageBox.critical(self, title, message)
        self.wrapped_organizer.log(MO2_LOG_CRITICAL, f"SkyGen: UI Error: {title} - {message}")

    def showWarning(self, title: str, message: str):
        QMessageBox.warning(self, title, message)
        self.wrapped_organizer.log(MO2_LOG_WARNING, f"SkyGen: UI Warning: {title} - {message}")

    def showInformation(self, title: str, message: str):
        QMessageBox.information(self, title, message)
        self.wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: UI Info: {title} - {message}")

    def _generate_skypatcher_yaml_internal(self) -> Optional[dict]:
        """
        Internal method to gather all necessary parameters for SkyPatcher YAML generation
        and return them. It no longer performs the xEdit launch or YAML writing directly.
        """
        self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: Preparing parameters for SkyPatcher YAML generation.")

        target_mod_display_name = self.selected_target_mod_name
        source_mod_display_name = self.selected_source_mod_name
        category = self.selected_category
        keywords_str = self.keywords_lineEdit.text().strip()
        keywords = [k.strip() for k in keywords_str.split(',') if k.strip()]
        broad_category_swap_enabled = self.broad_category_swap_checkbox.isChecked()
        output_folder_path = Path(self.output_folder_path)

        if not target_mod_display_name:
            self.showError("Input Error", "Please select a Target Mod.")
            self.wrapped_organizer.log(MO2_LOG_ERROR, "SkyGen: Target Mod not selected. Aborting YAML generation parameter preparation.")
            return None

        if not category:
            self.showError("Input Error", "Please select or enter a Category (Record Type).")
            self.wrapped_organizer.log(MO2_LOG_ERROR, "SkyGen: Category not selected. Aborting YAML generation parameter preparation.")
            return None

        # Determine game mode flag for xEdit (e.g., -SE, -VR)
        game_mode_flag = ""
        if self.selected_game_version == "SkyrimSE":
            game_mode_flag = "SE"
        elif self.selected_game_version == "SkyrimVR":
            game_mode_flag = "VR"
        else:
            self.showError("Game Version Error", "Could not determine game version. Please select SkyrimSE or SkyrimVR.")
            self.wrapped_organizer.log(MO2_LOG_ERROR, "SkyGen: Invalid or unselected game version.")
            return None

        # Check if xEdit path and name are available
        if not self.determined_xedit_exe_path or not self.determined_xedit_executable_name:
            self.showError("xEdit Not Configured", "xEdit executable not found or configured. Please add it to MO2's executables and restart SkyGen.")
            self.wrapped_organizer.log(MO2_LOG_CRITICAL, "SkyGen: CRITICAL: xEdit not found. Aborting generation parameter preparation.")
            return None

        xedit_script_filename = "ExportPluginData.pas"
        
        # Ensure output directory exists (needed here for validation, actual creation in __init__.py)
        if not output_folder_path.is_dir():
            try:
                output_folder_path.mkdir(parents=True, exist_ok=True)
                self.wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Created output directory: {output_folder_path}")
            except Exception as e:
                self.showError("Directory Creation Error", f"Failed to create output directory: {output_folder_path}\n{e}")
                self.wrapped_organizer.log(MO2_LOG_ERROR, f"SkyGen: ERROR: Failed to create output directory {output_folder_path}: {e}", exc_info=True)
                return None

        target_plugin_filename = self._get_plugin_name_from_mod_name(target_mod_display_name, self._get_internal_mod_name_from_display_name(target_mod_display_name))
        if not target_plugin_filename:
            self.showError("Target Mod Error", f"Could not determine plugin file for target mod '{target_mod_display_name}'. Please ensure it has a .esp/.esm/.esl file and is active.")
            self.wrapped_organizer.log(MO2_LOG_ERROR, f"SkyGen: Target mod '{target_mod_display_name}' has no primary plugin. Aborting YAML generation parameter preparation.")
            return None

        return {
            "target_mod_display_name": target_mod_display_name,
            "source_mod_display_name": source_mod_display_name,
            "category": category,
            "keywords": keywords,
            "broad_category_swap_enabled": broad_category_swap_enabled,
            "output_folder_path": output_folder_path,
            "game_mode_flag": game_mode_flag,
            "xedit_exe_path": self.determined_xedit_exe_path,
            "xedit_executable_name": self.determined_xedit_executable_name,
            "xedit_script_filename": xedit_script_filename,
            "target_plugin_filename": target_plugin_filename,
            "generate_all": self.generate_all,
            "all_exported_target_bases_by_formid": self.all_exported_target_bases_by_formid # Pass this through
        }

    # Helper method to get internal mod name, moved from __init__.py display()
    def _get_internal_mod_name_from_display_name(self, display_name: str) -> Optional[str]:
        """
        Retrieves the internal (folder) name of a mod from its display name.
        """
        mod_list = self.wrapped_organizer.modList()
        for mod_internal_name in mod_list.allMods():
            if mod_list.displayName(mod_internal_name) == display_name:
                return mod_internal_name
        return None

    def _get_plugin_name_from_mod_name(self, mod_display_name: str, mod_internal_name: str) -> Optional[str]:
        """
        Tries to determine the primary plugin (.esp, .esm, .esl) associated with a given mod.
        Prioritizes the active plugin and then looks for common plugin extensions.
        """
        self.wrapped_organizer.log(MO2_LOG_DEBUG, f"SkyGen: Attempting to get plugin name for mod: '{mod_display_name}' (internal: '{mod_internal_name}')")

        mod_plugins = []
        try:
            # mobase.IMod.fileNames() returns relative paths like 'plugins/MyPlugin.esp'
            mod_path = Path(self.wrapped_organizer.modPath(mod_internal_name))
            
            # List all files in the mod's actual directory
            for root, _, files in os.walk(mod_path):
                for file in files:
                    file_path = Path(root) / file
                    if file_path.suffix.lower() in ['.esp', '.esm', '.esl']:
                        # Get the filename relative to the mod_path, then just the filename
                        relative_path = file_path.relative_to(mod_path)
                        mod_plugins.append(relative_path.name) # Only the filename
        except Exception as e:
            self.wrapped_organizer.log(MO2_LOG_ERROR, f"SkyGen: ERROR: Could not list files for mod '{mod_internal_name}': {e}", exc_info=True)
            return None

        if not mod_plugins:
            self.wrapped_organizer.log(MO2_LOG_WARNING, f"SkyGen: No plugin files (.esp, .esm, .esl) found for mod: '{mod_display_name}'.")
            return None

        # Check for exact match with display name (e.g., "Unofficial Skyrim Special Edition Patch" -> "Unofficial Skyrim Special Edition Patch.esp")
        for p_name in mod_plugins:
            if p_name.lower() == f"{mod_display_name.lower()}.esp" or \
               p_name.lower() == f"{mod_display_name.lower()}.esm" or \
               p_name.lower() == f"{mod_display_name.lower()}.esl":
                self.wrapped_organizer.log(MO2_LOG_DEBUG, f"SkyGen: Found exact plugin name match for '{mod_display_name}': {p_name}")
                return p_name

        # If multiple plugins exist, try to guess the main one
        if len(mod_plugins) == 1:
            self.wrapped_organizer.log(MO2_LOG_DEBUG, f"SkyGen: Found single plugin '{mod_plugins[0]}' for mod '{mod_display_name}'.")
            return mod_plugins[0]
        else:
            self.wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Multiple plugin files found for mod '{mod_display_name}': {mod_plugins}. Attempting to select main plugin.")
            
            # Prioritize based on common patterns or simple alphabetical order
            sorted_plugins = sorted(mod_plugins, key=lambda x: (x.endswith('.esm'), x.endswith('.esl'), x.endswith('.esp'), x.lower()), reverse=True)
            if sorted_plugins:
                self.wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Selected plugin '{sorted_plugins[0]}' for mod '{mod_display_name}'.")
                return sorted_plugins[0] # Corrected: Access element first.
            
        self.wrapped_organizer.log(MO2_LOG_WARNING, f"SkyGen: Could not determine primary plugin for mod: '{mod_display_name}'.")
        return None

