import mobase
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QComboBox, QFileDialog, QCheckBox, QGroupBox, QRadioButton, QWidget, QSizePolicy,
    QListWidget, QListWidgetItem
)
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt, QSize
from pathlib import Path
from typing import Any, Optional, Union
import json
import traceback
import time


# Define custom log levels if not available from mobase directly
# These mimic mobase's internal logging levels
MO2_LOG_CRITICAL = 5
MO2_LOG_ERROR = 4
MO2_LOG_WARNING = 3
MO2_LOG_INFO = 2
MO2_LOG_DEBUG = 1
MO2_LOG_TRACE = 0


class OrganizerWrapper:
    """
    A wrapper class for the mobase.IOrganizer interface to handle logging.
    This class exists to provide a consistent logging mechanism that can fall back
    to file-based logging if direct MO2 logging is not available or causes issues.
    """
    def __init__(self, organizer: mobase.IOrganizer):
        self._organizer = organizer
        self._log_file_path: Optional[Path] = None
        self._log_file_handle = None
        self._log_initialized = False

    def set_log_file_path(self, path: Path):
        """Sets the path for the custom log file."""
        self._log_file_path = path
        self._log_initialized = False # Reset, will re-open on first log call

    def _open_log_file(self):
        """Opens or re-opens the log file."""
        if self._log_file_handle:
            self._log_file_handle.close()
            self._log_file_handle = None
        
        if self._log_file_path:
            try:
                # Open in append mode, create if it doesn't exist
                self._log_file_handle = open(self._log_file_path, "a", encoding="utf-8")
                self._log_initialized = True
            except Exception as e:
                pass
                self._log_initialized = False
        else:
            self._log_initialized = False

    def log(self, mo2_log_level: int, message: str):
        """
        Logs a message to the custom log file and optionally to MO2's log if available.
        """
        full_message = f"[{self.get_level_name(mo2_log_level)}] {message}"
        
        # Log to custom file
        if not self._log_initialized:
            self._open_log_file()
        
        if self._log_file_handle:
            try:
                self._log_file_handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())} {full_message}\n")
                self._log_file_handle.flush() # Ensure it's written immediately
            except Exception as e:
                pass
                self._log_initialized = False # Mark as uninitialized, try to re-open next time

    def close_log_file(self):
        """Closes the custom log file handle."""
        if self._log_file_handle:
            try:
                self._log_file_handle.close()
                self._log_file_handle = None
                self._log_initialized = False
            except Exception as e:
                pass # CORRECTED: Changed print to pass


    def get_level_name(self, level: int) -> str:
        """Returns the string name for a given log level."""
        if level == MO2_LOG_CRITICAL: return "CRITICAL"
        if level == MO2_LOG_ERROR: return "ERROR"
        if level == MO2_LOG_WARNING: return "WARNING"
        if level == MO2_LOG_INFO: return "INFO"
        if level == MO2_LOG_DEBUG: return "DEBUG"
        if level == MO2_LOG_TRACE: return "TRACE"
        return "UNKNOWN"
    
    # ADDED DELEGATE METHODS (Ensuring they are present as per review)
    def pluginList(self):
        return self._organizer.pluginList()

    def getExecutables(self):
        """Delegates to MO2's getExecutables if available, otherwise logs error."""
        try:
            return self._organizer.getExecutables()
        except AttributeError:
            self.log(3, "SkyGen: WARNING: MO2 'getExecutables' not available. Falling back to INI parsing.")
            return [] # Return empty list if not available
        except Exception as e:
            self.log(4, f"SkyGen: ERROR: Unexpected error calling getExecutables: {e}")
            return []

    def modsPath(self):
        return self._organizer.modsPath()

    def startApplication(self, name, args, cwd):
        return self._organizer.startApplication(name, args, cwd)

    # Delegate other necessary organizer methods that don't involve logging
    def basePath(self):
        return self._organizer.basePath()
    
    def pluginDataPath(self):
        return self._organizer.pluginDataPath()

    def gameInfo(self):
        return self._organizer.gameInfo()

    def gameFeatures(self):
        return self._organizer.gameFeatures()
    
    def modList(self):
        return self._organizer.modList()


# Dummy classes for PyQt6 if not available, ensuring the script can still be parsed
# although the UI won't function.
# This entire try-except block is crucial for plugin loading without PyQt6.
try:
    from PyQt6.QtWidgets import QWidget, QApplication, QMessageBox, QLabel, QLineEdit, QPushButton, QComboBox, QVBoxLayout, QHBoxLayout, QFileDialog, QCheckBox, QGroupBox, QRadioButton, QSizePolicy, QListWidget, QListWidgetItem
    from PyQt6.QtGui import QIcon
    from PyQt6.QtCore import Qt, QSize
except ImportError:
    # Dummy QWidget
    class QWidget:
        def __init__(self, *args, **kwargs): pass
        def show(self): pass
        def close(self): pass
        def setWindowTitle(self, title): pass
        def setLayout(self, layout): pass
        def setFixedSize(self, width, height): pass
        def setSizePolicy(self, policy): pass

    # Dummy QApplication
    class QApplication:
        def __init__(self, *args, **kwargs): pass
        def instance(self): return None
        def exec(self): return 0

    # Dummy QMessageBox - improved to print messages
    class QMessageBox:
        @staticmethod
        def critical(parent, title, message):
            print(f"CRITICAL: {title}: {message}")
        @staticmethod
        def warning(parent, title, message):
            print(f"WARNING: {title}: {message}")
        @staticmethod
        def information(parent, title, message):
            print(f"INFORMATION: {title}: {message}")
        @staticmethod
        def about(parent, title, message): # Added about method
            print(f"ABOUT: {title}: {message}")

    # Dummy QLabel
    class QLabel:
        def __init__(self, text="", parent=None): self._text = text
        def setText(self, text): self._text = text
        def text(self): return self._text
        def setBuddy(self, widget): pass
        def setAlignment(self, alignment): pass # Dummy alignment
        def setWordWrap(self, wrap): pass # Dummy wrap

    # Dummy QLineEdit
    class QLineEdit:
        def __init__(self, text="", parent=None): self._text = text
        def text(self): return self._text
        def setText(self, text): self._text = text
        def setPlaceholderText(self, text): pass
        def setReadOnly(self, read_only): pass

    # Dummy QPushButton
    class QPushButton:
        def __init__(self, text="", parent=None): self._text = text
        def clicked(self): return DummySignal()
        def setText(self, text): self._text = text
        def setIcon(self, icon): pass # Dummy icon
        def setIconSize(self, size): pass # Dummy icon size

    # Dummy QComboBox - CRITICAL FIX: Changed setCurrent to setCurrentIndex
    class QComboBox:
        def __init__(self, parent=None): self._items = []; self._currentIndex = -1
        def addItems(self, items): self._items.extend(items)
        def addItem(self, item): self._items.append(item)
        def clear(self): self._items = []
        def count(self): return len(self._items)
        def currentText(self): return self._items[self._currentIndex] if 0 <= self._currentIndex < len(self._items) else ""
        def currentIndex(self): return self._currentIndex
        def setCurrentIndex(self, index): # FIXED: Ensure this is setCurrentIndex
            if 0 <= index < len(self._items): self._currentIndex = index
            else: self._currentIndex = -1
        def itemText(self, index): return self._items[index]
        def setEditable(self, editable): pass
        def hidePopup(self): pass
        def activated(self): return DummySignal() # For combo box signal
        def currentIndexChanged(self): return DummySignal() # For combo box signal
        def setSizePolicy(self, policy): pass

    # Dummy Layouts
    class QVBoxLayout:
        def __init__(self, parent=None): self._widgets = []
        def addWidget(self, widget, stretch=0, alignment=Qt.AlignmentFlag.TopLeft): self._widgets.append(widget)
        def addLayout(self, layout, stretch=0): self._widgets.append(layout)
        def addStretch(self, stretch=0): pass
        def setContentsMargins(self, left, top, right, bottom): pass # Dummy margins

    class QHBoxLayout:
        def __init__(self, parent=None): self._widgets = []
        def addWidget(self, widget, stretch=0, alignment=Qt.AlignmentFlag.TopLeft): self._widgets.append(widget)
        def addLayout(self, layout, stretch=0): self._widgets.append(layout)
        def addStretch(self, stretch=0): pass
        def setContentsMargins(self, left, top, right, bottom): pass # Dummy margins

    # Dummy QFileDialog
    class QFileDialog:
        @staticmethod
        def getExistingDirectory(parent, caption, directory): return ""
        @staticmethod
        def getOpenFileName(parent, caption, directory, filter): return ("", "")

    # Dummy QCheckBox
    class QCheckBox:
        def __init__(self, text="", parent=None): self._text = text; self._checked = False
        def isChecked(self): return self._checked
        def setChecked(self, checked): self._checked = checked
        def stateChanged(self): return DummySignal() # Dummy signal

    # Dummy QGroupBox
    class QGroupBox:
        def __init__(self, title="", parent=None): self._title = title
        def setLayout(self, layout): pass
        def setTitle(self, title): pass
    
    # Dummy QRadioButton
    class QRadioButton:
        def __init__(self, text="", parent=None): self._text = text; self._checked = False
        def isChecked(self): return self._checked
        def setChecked(self, checked): self._checked = checked
        def toggled(self): return DummySignal() # Dummy signal

    # Dummy QSizePolicy
    class QSizePolicy:
        Fixed = 0
        Minimum = 1
        Maximum = 2
        Preferred = 3
        Expanding = 4
        Ignored = 5
        GrowFlag = 1
        ShrinkFlag = 2
        ExpandFlag = 4
        NoHeightForWidth = 8
        def __init__(self, horizontal, vertical): pass
        def setHeightForWidth(self, on): pass

    # Dummy QListWidget
    class QListWidget:
        def __init__(self, parent=None): self._items = []
        def addItem(self, item): self._items.append(item)
        def addItems(self, items): self._items.extend(items)
        def clear(self): self._items = []
        def count(self): return len(self._items)
        def item(self, row): return self._items[row] if 0 <= row < len(self._items) else None
        def currentRow(self): return -1 # Dummy, no selection
        def selectedItems(self): return [] # Dummy, no selection
        def setSelectionMode(self, mode): pass
        def setSizePolicy(self, policy): pass
        def itemClicked(self): return DummySignal()
        def currentItemChanged(self): return DummySignal()

    # Dummy QListWidgetItem
    class QListWidgetItem:
        def __init__(self, text="", parent=None): self._text = text
        def text(self): return self._text
        def setText(self, text): self._text = text

    # Dummy QIcon and QSize
    class QIcon:
        def __init__(self, path): pass
    class QSize:
        def __init__(self, width, height): self.width = width; self.height = height

    # Dummy Signal for clicked/activated methods
    class DummySignal:
        def connect(self, func): pass # Do nothing on connect
        def emit(self, *args): pass # Do nothing on emit

    # Dummy QtCore.Qt
    class Qt:
        # Define some common Qt enums if not importing Qt directly
        class DialogCode:
            Accepted = 1
            Rejected = 0
        class AlignmentFlag:
            AlignLeft = 0x0001
            AlignRight = 0x0002
            AlignHCenter = 0x0004
            AlignJustify = 0x0008
            AlignTop = 0x0020
            AlignBottom = 0x0040
            AlignVCenter = 0x0080
            AlignCenter = AlignHCenter | AlignVCenter
            TopLeft = 0 # Default alignment
        class CheckState:
            Unchecked = 0
            PartiallyChecked = 1
            Checked = 2
        class FocusReason:
            NoFocusReason = 0
            TabFocusReason = 1
            BacktabFocusReason = 2
            ActiveWindowFocusReason = 3
            PopupFocusReason = 4
            ShortcutFocusReason = 5
            MenuBarFocusReason = 6
            MouseFocusReason = 7
            WheelFocusReason = 8
            OtherFocusReason = 9

# Main Dialog Class
class SkyGenToolDialog(QDialog):
    """
    The main UI dialog for the SkyGen plugin tool.
    Allows users to select generation options and trigger SkyPatcher YAML or BOS INI creation.
    """

    def __init__(self, wrapped_organizer: OrganizerWrapper, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.wrapped_organizer = wrapped_organizer
        self.setWindowTitle("SkyGen - Automate Your Modding!")
        self.setFixedSize(500, 600) # Fixed size for consistency
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint) # Remove help button
        
        # Internal state variables
        self.selected_output_type = "SkyPatcher YAML" # Default
        self.selected_game_version = ""
        self.selected_target_mod_name = ""
        self.selected_source_mod_name = ""
        self.selected_category = ""
        self.output_folder_path = ""
        self.igpc_json_path = ""
        self.determined_xedit_exe_path: Optional[Path] = None
        self.determined_xedit_executable_name: str = ""
        self.game_root_path: Optional[Path] = None
        self.generate_all = False # For 'Generate All' checkbox state

        self._setup_ui()
        self._populate_game_versions()
        self._populate_categories()
        self._populate_mods()
        self._load_config() # Load saved settings


    def _setup_ui(self):
        """Sets up the layout and widgets of the dialog."""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20) # Add some padding

        # --- Output Type Selection Group ---
        output_type_group = QGroupBox("Select Output Type")
        output_type_layout = QHBoxLayout()
        self.yaml_radio = QRadioButton("SkyPatcher YAML")
        self.bos_ini_radio = QRadioButton("BOS INI")
        
        self.yaml_radio.setChecked(True) # Default selection
        self.yaml_radio.toggled.connect(self._on_output_type_toggled)
        self.bos_ini_radio.toggled.connect(self._on_output_type_toggled)
        
        output_type_layout.addWidget(self.yaml_radio)
        output_type_layout.addWidget(self.bos_ini_radio)
        output_type_layout.addStretch(1) # Push radios to the left
        output_type_group.setLayout(output_type_layout)
        main_layout.addWidget(output_type_group)

        # --- General Settings Group ---
        general_settings_group = QGroupBox("General Settings")
        general_settings_layout = QVBoxLayout()

        # Game Version
        game_version_layout = QHBoxLayout()
        game_version_label = QLabel("Game Version:")
        self.game_version_combo = QComboBox()
        self.game_version_combo.currentIndexChanged.connect(self._on_game_version_selected)
        game_version_layout.addWidget(game_version_label)
        game_version_layout.addWidget(self.game_version_combo)
        general_settings_layout.addLayout(game_version_layout)

        # Output Folder
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


        # --- SkyPatcher YAML Specific Settings Group ---
        self.yaml_settings_group = QGroupBox("SkyPatcher YAML Settings")
        yaml_settings_layout = QVBoxLayout()

        # Target Mod
        target_mod_layout = QHBoxLayout()
        target_mod_label = QLabel("Target Mod:")
        self.target_mod_combo = QComboBox()
        self.target_mod_combo.setEditable(True)
        self.target_mod_combo.setPlaceholderText("Select the mod you are patching TO (e.g., DynDOLOD Output)")
        self.target_mod_combo.activated.connect(self._on_target_mod_selected)
        target_mod_layout.addWidget(target_mod_label)
        target_mod_layout.addWidget(self.target_mod_combo)
        yaml_settings_layout.addLayout(target_mod_layout)

        # Source Mod
        source_mod_layout = QHBoxLayout()
        source_mod_label = QLabel("Source Mod:")
        self.source_mod_combo = QComboBox()
        self.source_mod_combo.setEditable(True)
        self.source_mod_combo.setPlaceholderText("Select the mod you are patching FROM (e.g., Enhanced Landscapes)")
        self.source_mod_combo.activated.connect(self._on_source_mod_selected)
        source_mod_layout.addWidget(source_mod_label)
        source_mod_layout.addWidget(self.source_mod_combo)
        yaml_settings_layout.addLayout(source_mod_layout)

        # Generate All Checkbox (positioned correctly)
        self.generate_all_checkbox = QCheckBox("Generate YAML for all compatible source mods (vs. selected source)")
        self.generate_all_checkbox.setChecked(False)
        self.generate_all_checkbox.stateChanged.connect(self._on_generate_all_toggled)
        yaml_settings_layout.addWidget(self.generate_all_checkbox)

        # Category Selection
        category_layout = QHBoxLayout()
        category_label = QLabel("Category (Record Type):")
        self.category_combo = QComboBox()
        self.category_combo.setPlaceholderText("e.g., STAT, TREE, GRAS")
        self.category_combo.setEditable(True) # Allow custom input
        self.category_combo.activated.connect(self._on_category_selected)
        category_layout.addWidget(category_label)
        category_layout.addWidget(self.category_combo)
        yaml_settings_layout.addLayout(category_layout)

        # Keywords
        keywords_layout = QHBoxLayout()
        keywords_label = QLabel("Keywords (comma-separated):")
        self.keywords_lineEdit = QLineEdit()
        self.keywords_lineEdit.setPlaceholderText("Optional: e.g., pine, oak, rock")
        self.keywords_lineEdit.textChanged.connect(self._on_keywords_changed)
        keywords_layout.addWidget(keywords_label)
        keywords_layout.addWidget(self.keywords_lineEdit)
        yaml_settings_layout.addLayout(keywords_layout)
        
        # Broad Category Swap
        self.broad_category_swap_checkbox = QCheckBox("Enable Broad Category Swap (experimental)")
        self.broad_category_swap_checkbox.setChecked(False) # Default to off
        yaml_settings_layout.addWidget(self.broad_category_swap_checkbox)

        self.yaml_settings_group.setLayout(yaml_settings_layout)
        main_layout.addWidget(self.yaml_settings_group)


        # --- BOS INI Specific Settings Group ---
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
        self.bos_ini_settings_group.setVisible(False) # Hidden by default


        # --- Action Buttons ---
        button_layout = QHBoxLayout()
        self.generate_button = QPushButton("Generate")
        self.generate_button.clicked.connect(self.accept) # Accept dialog on generate
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject) # Reject dialog on cancel

        button_layout.addStretch(1) # Push buttons to the right
        button_layout.addWidget(self.generate_button)
        button_layout.addWidget(self.cancel_button)
        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)

        # Set size policy to preferred and expanding to allow flexible sizing
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)


    def _populate_game_versions(self):
        """Populates the game version combobox with only supported game types (SkyrimSE, SkyrimVR)."""
        supported_games = {
            mobase.GameType.SSE: "SkyrimSE",
            mobase.GameType.SkyrimVR: "SkyrimVR"
        }
        
        current_game_type = self.wrapped_organizer.gameInfo().type()
        
        self.game_version_combo.clear()
        
        # Add current game first if it's supported
        current_game_name = supported_games.get(current_game_type)
        if current_game_name:
            self.game_version_combo.addItem(current_game_name)
            self.selected_game_version = current_game_name
            
            for game_type, name in supported_games.items():
                if name != current_game_name:
                    self.game_version_combo.addItem(name)
        else:
            # If current game is not supported, just add all supported ones
            self.game_version_combo.addItems(sorted(supported_games.values()))
            if supported_games:
                self.selected_game_version = self.game_version_combo.currentText() # Set initial selection to first item
        
        self.wrapped_organizer.log(0, f"SkyGen: Populated game versions: {self.game_version_combo.currentText()}")


    def _populate_categories(self):
        """Populates the category combobox with common record types."""
        common_categories = [
            "ARMO", "WEAP", "AMMO", "MISC", "STAT", "TREE", "GRAS", "FLOR", "CONT",
            "LIGH", "CELL", "WRLD", "QUST", "SPEL", "ENCH", "COBJ", "ALCH", "BOOK",
            "KEYM", "SCRL", "SLGM", "SOUL", "LVLI", "ACTI", "APPA", "ARMA", "CCEM",
            "CSTY", "DOOR", "EFSH", "IDLE", "IMAD", "LCTN", "MGEF", "MOVE", "MSTT",
            "PMIS", "PROJ", "PWAT", "REGN", "SGST", "SMQN", "SNCT", "SNDR", "TXST",
            "VTYP", "WATR", "WRLD", "ZOOM", "GMST" # Added more common types
        ]
        self.category_combo.addItems(sorted(common_categories))
        if common_categories:
            self.selected_category = self.category_combo.currentText() # Set initial selection


    def _populate_mods(self):
        """Populates the mod comboboxes with active mods."""
        mod_list = self.wrapped_organizer.modList()
        active_mods = []
        for mod_name in mod_list.allMods():
            if mod_list.state(mod_name) & mobase.ModState.ACTIVE:
                display_name = mod_list.displayName(mod_name)
                # Attempt to get the plugin name associated with the mod
                plugin_name = self._get_plugin_name_from_mod_name(display_name, mod_name)
                if plugin_name:
                    active_mods.append(display_name)
                    self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Found active mod with plugin: {display_name} ({plugin_name})")
                else:
                    self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Skipping active mod without detectable plugin: {display_name}")

        active_mods.sort(key=str.lower) # Sort alphabetically
        
        self.target_mod_combo.clear()
        self.source_mod_combo.clear()

        # Add an empty/default option
        self.target_mod_combo.addItem("")
        self.source_mod_combo.addItem("")

        self.target_mod_combo.addItems(active_mods)
        self.source_mod_combo.addItems(active_mods)

        # Set initial selections if available
        if active_mods:
            # Attempt to set DynDOLOD Output or similar as default target
            default_target_mods = ["DynDOLOD Output", "TexGen Output", "MergePlugins", "Smashed Patch"]
            for default_mod in default_target_mods:
                if default_mod in active_mods:
                    self.target_mod_combo.setCurrentIndex(self.target_mod_combo.findText(default_mod))
                    self.selected_target_mod_name = default_mod
                    break
            
            # If no default target found, set to first mod (if any)
            if not self.selected_target_mod_name and active_mods:
                self.target_mod_combo.setCurrentIndex(1) # Skip empty string
                self.selected_target_mod_name = self.target_mod_combo.currentText()

            # For source, typically the first active mod alphabetically or specific common source
            if active_mods:
                self.source_mod_combo.setCurrentIndex(1) # Skip empty string
                self.selected_source_mod_name = self.source_mod_combo.currentText()


    def _get_plugin_name_from_mod_name(self, display_name: str, internal_name: str) -> Optional[str]:
        """
        Attempts to find the plugin filename for a given mod display name or internal name.
        Iterates through files in the mod's base directory and its plugins.txt entry.
        """
        # First, check plugins.txt for an exact match or a case-insensitive match
        # This approach is less reliable than checking actual mod contents through MO2's VFS
        
        # Get the actual data path for the mod (which uses MO2's VFS)
        mod_origin_path = Path(self.wrapped_organizer.modList().modPath(internal_name))
        
        # Check if the mod path exists and is a directory
        if not mod_origin_path.is_dir():
            self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Mod path for '{display_name}' ({internal_name}) is not a directory: {mod_origin_path}")
            return None

        # Iterate through files in the mod's directory to find an ESP/ESM/ESL
        for entry in os.scandir(mod_origin_path):
            if entry.is_file():
                filename = entry.name
                if filename.lower().endswith(('.esp', '.esm', '.esl')):
                    self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Found plugin '{filename}' for mod '{display_name}' at {mod_origin_path}")
                    return filename
        
        self.wrapped_organizer.log(0, f"SkyGen: DEBUG: No plugin found within the directory for mod '{display_name}' ({internal_name}): {mod_origin_path}")
        return None


    def _browse_output_folder(self):
        """Opens a dialog to select the output folder."""
        current_path = self.output_folder_lineEdit.text() if self.output_folder_lineEdit.text() else str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder", current_path)
        if folder:
            self.output_folder_path = folder
            self.output_folder_lineEdit.setText(folder)
            self.wrapped_organizer.log(1, f"SkyGen: Output folder set to: {folder}")


    def _browse_igpc_json(self):
        """Opens a dialog to select the IGPC JSON file."""
        current_path = self.igpc_json_lineEdit.text() if self.igpc_json_lineEdit.text() else str(Path.home())
        file_path, _ = QFileDialog.getOpenFileName(self, "Select IGPC JSON File", current_path, "JSON Files (*.json)")
        if file_path:
            self.igpc_json_path = file_path
            self.igpc_json_lineEdit.setText(file_path)
            self.wrapped_organizer.log(1, f"SkyGen: IGPC JSON file set to: {file_path}")


    def _on_output_type_toggled(self):
        """Handles changes in the output type radio buttons."""
        if self.yaml_radio.isChecked():
            self.selected_output_type = "SkyPatcher YAML"
            self.yaml_settings_group.setVisible(True)
            self.bos_ini_settings_group.setVisible(False)
            self.generate_all_checkbox.setVisible(True) # Only show for YAML
            self.wrapped_organizer.log(0, "SkyGen: Output type set to SkyPatcher YAML.")
        elif self.bos_ini_radio.isChecked():
            self.selected_output_type = "BOS INI"
            self.yaml_settings_group.setVisible(False)
            self.bos_ini_settings_group.setVisible(True)
            self.generate_all_checkbox.setVisible(False) # Hide for BOS INI
            self.wrapped_organizer.log(0, "SkyGen: Output type set to BOS INI.")
        self._save_config() # Save setting when toggled


    def _on_game_version_selected(self):
        self.selected_game_version = self.game_version_combo.currentText()
        self.wrapped_organizer.log(0, f"SkyGen: Game version selected: {self.selected_game_version}")
        self._save_config()


    def _on_target_mod_selected(self):
        self.selected_target_mod_name = self.target_mod_combo.currentText()
        self.wrapped_organizer.log(0, f"SkyGen: Target mod selected: {self.selected_target_mod_name}")
        self._save_config()


    def _on_source_mod_selected(self):
        self.selected_source_mod_name = self.source_mod_combo.currentText()
        self.wrapped_organizer.log(0, f"SkyGen: Source mod selected: {self.selected_source_mod_name}")
        self._save_config()


    def _on_category_selected(self):
        self.selected_category = self.category_combo.currentText().upper() # Ensure uppercase
        self.wrapped_organizer.log(0, f"SkyGen: Category selected: {self.selected_category}")
        self.category_combo.setCurrentText(self.selected_category) # Update field to uppercase
        self._save_config()


    def _on_keywords_changed(self):
        self.keywords_lineEdit.setText(self.keywords_lineEdit.text().lower()) # Convert to lowercase as per Pascal script
        self._save_config() # Save on text change for keywords


    def _on_generate_all_toggled(self, state):
        self.generate_all = (state == Qt.CheckState.Checked.value)
        # Disable source mod combo if "Generate All" is checked
        self.source_mod_combo.setEnabled(not self.generate_all)
        self.wrapped_organizer.log(0, f"SkyGen: Generate All checkbox toggled: {self.generate_all}")
        self._save_config()


    def _get_config_path(self) -> Path:
        """Returns the path to the plugin's config.json file."""
        return Path(self.wrapped_organizer.pluginDataPath()) / "SkyGen" / "config.json"


    def _load_config(self):
        """Loads saved settings from config.json."""
        config_path = self._get_config_path()
        if config_path.is_file():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                # Apply settings for output type
                output_type = config.get("output_type", "SkyPatcher YAML")
                if output_type == "SkyPatcher YAML":
                    self.yaml_radio.setChecked(True)
                else:
                    self.bos_ini_radio.setChecked(True)
                self._on_output_type_toggled() # Trigger visibility update
                
                # Apply general settings
                self.game_version_combo.setCurrentIndex(
                    self.game_version_combo.findText(config.get("game_version", self.game_version_combo.currentText()))
                )
                
                self.output_folder_lineEdit.setText(config.get("output_folder_path", str(Path(self.wrapped_organizer.basePath()) / "overwrite")))
                self.output_folder_path = self.output_folder_lineEdit.text()

                # Apply YAML settings
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

                # Apply BOS INI settings
                self.igpc_json_lineEdit.setText(config.get("igpc_json_path", ""))
                self.igpc_json_path = self.igpc_json_lineEdit.text()

                # Load xedit paths if they exist
                self.determined_xedit_exe_path = Path(config.get("xedit_exe_path", "")) if config.get("xedit_exe_path") else None
                self.determined_xedit_executable_name = config.get("xedit_mo2_name", "")

                self.wrapped_organizer.log(1, "SkyGen: Settings loaded successfully.")
            except Exception as e:
                self.wrapped_organizer.log(3, f"SkyGen: ERROR: Failed to load settings from config.json: {e}")
        else:
            self.wrapped_organizer.log(1, "SkyGen: config.json not found, using default settings.")
            self.output_folder_path = str(Path(self.wrapped_organizer.basePath()) / "overwrite")
            self.output_folder_lineEdit.setText(self.output_folder_path)


    def _save_config(self):
        """Saves current settings to config.json."""
        config_path = self._get_config_path()
        config_data = {
            "output_type": self.selected_output_type,
            "game_version": self.game_version_combo.currentText(),
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
            # Ensure the directory exists before writing
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4)
            self.wrapped_organizer.log(0, "SkyGen: Settings saved.")
        except Exception as e:
            self.wrapped_organizer.log(3, f"SkyGen: ERROR: Failed to save settings to config.json: {e}")
            self.showError("Save Error", f"Failed to save settings: {e}")


    def showError(self, title: str, message: str):
        """Displays an error message box."""
        QMessageBox.critical(self, title, message)
        self.wrapped_organizer.log(4, f"SkyGen: UI Error: {title} - {message}")

    def showWarning(self, title: str, message: str):
        """Displays a warning message box."""
        QMessageBox.warning(self, title, message)
        self.wrapped_organizer.log(3, f"SkyGen: UI Warning: {title} - {message}")

    def showInformation(self, title: str, message: str):
        """Displays an information message box."""
        QMessageBox.information(self, title, message)
        self.wrapped_organizer.log(2, f"SkyGen: UI Info: {title} - {message}")
