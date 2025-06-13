from pathlib import Path
import mobase
import os
import json
import yaml
import configparser # Although not directly used in the moved classes, it's a common dependency for related functions
import re           # Although not directly used in the moved classes, it's a common dependency for related functions
import time
from collections import defaultdict
from typing import Optional

# Import utility functions used by UI classes
from .skygen_file_utilities import (
    load_json_data,
    get_xedit_exe_path,
    write_xedit_ini_for_skygen,
    write_pas_script_to_xedit,
    clean_temp_script_and_ini
)

# Ensure necessary PyQt6 modules are imported correctly or dummy classes are defined
try:
    from PyQt6.QtWidgets import (
        QApplication,
        QDialog,
        QVBoxLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QComboBox,
        QMessageBox,
        QButtonGroup,
        QWidget,
        QSizePolicy,
        QFileDialog,
        QCheckBox,
        QRadioButton,
        QListWidget,
        QListWidgetItem
    )
    from PyQt6.QtCore import Qt, QCoreApplication
    from PyQt6.QtGui import QIcon
except ImportError:
    print("One or more required PyQt modules are not installed. Please ensure PyQt6 is installed.")
    # Define dummy classes/functions to prevent hard crashes if PyQt6 is missing
    class QDialog:
        def __init__(self, *args, **kwargs): pass
        def exec(self): return 0
        def setLayout(self, *args, **kwargs): pass
        def reject(self): pass
        def show(self): pass
        def close(self): pass
    class QVBoxLayout:
        def __init__(self, *args, **kwargs): pass
        def addLayout(self, *args, **kwargs): pass
        def addWidget(self, *args, **kwargs): pass
    class QHBoxLayout:
        def __init__(self, *args, **kwargs): pass
        def addWidget(self, *args, **kwargs): pass
    class QLabel:
        def __init__(self, *args, **kwargs): pass
        def setVisible(self, *args, **kwargs): pass
    class QLineEdit:
        def __init__(self, *args, **kwargs): pass
        def setText(self, *args, **kwargs): pass
        def text(self): return ""
        def setPlaceholderText(self, *args, **kwargs): pass
        def setReadOnly(self, *args, **kwargs): pass
        def setVisible(self, *args, **kwargs): pass
    class QPushButton:
        def __init__(self, *args, **kwargs): pass
        def clicked(self): return type('obj', (object,), {'connect': lambda *args: None})()
        def setText(self, *args, **kwargs): pass
        def setVisible(self, *args, **kwargs): pass
    class QComboBox:
        def __init__(self, *args, **kwargs): pass
        def addItems(self, *args, **kwargs): pass
        def currentIndexChanged(self): return type('obj', (object,), {'connect': lambda *args: None})()
        def currentText(self): return ""
        def itemText(self, index): return ""
        def addItem(self, *args, **kwargs): pass
        def setVisible(self, *args, **kwargs): pass
    class QMessageBox:
        @staticmethod
        def critical(*args, **kwargs): print(f"CRITICAL: {args[2] if len(args) > 2 else 'No message'}")
        @staticmethod
        def warning(*args, **kwargs): print(f"WARNING: {args[2] if len(args) > 2 else 'No message'}")
        @staticmethod
        def information(*args, **kwargs): print(f"INFO: {args[2] if len(args) > 2 else 'No message'}")
    class QButtonGroup:
        def __init__(self, *args, **kwargs): pass
        def addButton(self, *args, **kwargs): pass
    class QWidget:
        def __init__(self, *args, **kwargs): pass
        def setLayout(self, *args, **kwargs): pass
    class QSizePolicy:
        def __init__(self, *args, **kwargs): pass
    class QFileDialog:
        @staticmethod
        def getOpenFileName(*args, **kwargs): return "", ""
        @staticmethod
        def getExistingDirectory(*args, **kwargs): return ""
        def setFileMode(self, *args, **kwargs): pass
        def setOption(self, *args, **kwargs): pass
        def setDirectory(self, *args, **kwargs): pass
        def selectedFiles(self): return []
    class Qt:
        class CheckState:
            Checked = type('obj', (object,), {'value': 2})()
            Unchecked = type('obj', (object,), {'value': 0})()
        class DialogCode:
            Accepted = 1
            Rejected = 0
        AlignLeft = 0
        AlignTop = 0
    class QIcon:
        def __init__(self, *args, **kwargs): pass
    class QApplication:
        def __init__(self, *args, **kwargs): pass
        def exec(self): return 0
        def exit(self, *args, **kwargs): pass
    class QRadioButton:
        def __init__(self, *args, **kwargs): pass
        def setChecked(self, *args, **kwargs): pass
        def toggled(self): return type('obj', (object,), {'connect': lambda *args: None})()
        def sender(self): return self
        def setVisible(self, *args, **kwargs): pass
    class QListWidget:
        def __init__(self, *args, **kwargs): pass
        def addItems(self, *args, **kwargs): pass
        def currentItem(self): return None
        def currentRow(self): return -1
    class QListWidgetItem:
        def __init__(self, *args, **kwargs): pass
    class QCheckBox:
        def __init__(self, *args, **kwargs): pass
        def setChecked(self, *args, **kwargs): pass
        def isChecked(self): return False
        def stateChanged(self): return type('obj', (object,), {'connect': lambda *args: None})()
        def setVisible(self, *args, **kwargs): pass
    class QCoreApplication:
        @staticmethod
        def translate(context, text, disambiguation=None, n=-1): return text
    class QFont:
        def __init__(self, *args, **kwargs): pass
    class QFontMetrics:
        def __init__(self, *args, **kwargs): pass
    class QEvent:
        Type = type('obj', (object,), {'ContextMenu': 0})()
    class QMenu:
        def __init__(self, *args, **kwargs): pass
        def exec(self, *args, **kwargs): return None
        def addAction(self, *args, **kwargs): return None
    class QAction:
        def __init__(self, *args, **kwargs): pass
        def triggered(self): return type('obj', (object,), {'connect': lambda *args: None})()


# Define a wrapper for mobase.IOrganizer to handle missing 'log' method
class OrganizerWrapper:
    """Wrapper for mobase.IOrganizer with enhanced logging capabilities."""
    def __init__(self, actual_organizer: mobase.IOrganizer):
        self._actual_organizer = actual_organizer
        # Define log level mapping internally
        self._log_level_map = {
            0: "DEBUG",
            1: "INFO",
            2: "WARNING",
            3: "ERROR",
            4: "CRITICAL"
        }

        # Custom log file setup
        self._log_file = None
        try:
            # Determine the full path for the custom log file
            # It should be located within your plugin's directory
            plugin_dir = Path(__file__).parent
            log_file_path = plugin_dir / "SkyGen_Debug.log"
            
            # Open the file in write mode ('w')
            self._log_file = open(log_file_path, 'w', encoding='utf-8')
            # Ensure the file is flushed immediately after writing
            self._log_file.reconfigure(line_buffering=True) # Enables line buffering for immediate flushing
            self.log(1, f"SkyGen: Custom log file opened at: {log_file_path}")
        except (IOError, OSError) as e:
            QMessageBox.critical(None, "SkyGen Log Error", 
                                 f"Failed to open plugin debug log file at:\n{log_file_path}\n\n"
                                 f"This is often due to permissions issues. Please ensure the plugin directory is writable.\nError: {e}")
            print(f"[CRITICAL] SkyGen: Failed to open custom log file: {e}")
            self._log_file = None # Ensure it's None if opening failed

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensures log file is closed."""
        self.close_log_file()

    def log(self, level, message):
        """
        Custom logging method that *always* falls back to print() for now,
        to bypass mobase.IOrganizer.log issues.
        """
        log_level_str = self._log_level_map.get(level, "UNKNOWN")
        formatted_message = f"[{log_level_str}] {message}"
        print(formatted_message) # Always print, bypassing hasattr check

        # Write to custom log file as well
        if self._log_file:
            try:
                self._log_file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {formatted_message}\n")
                self._log_file.flush() # Ensure immediate write to disk
            except Exception as e:
                # Fallback print if writing to file fails
                print(f"[CRITICAL] SkyGen: Failed to write to custom log file: {e}")


    # Method to explicitly close the custom log file
    def close_log_file(self):
        """
        Closes the custom log file if it was successfully opened.
        """
        if self._log_file:
            try:
                self.log(1, "SkyGen: Closing custom log file.")
                self._log_file.close()
                self._log_file = None # Set to None after closing
            except Exception as e:
                print(f"[CRITICAL] SkyGen: Error closing custom log file: {e}")


    # Forwarding methods for mobase.IOrganizer functionalities
    def modList(self):
        return self._actual_organizer.modList()

    def pluginList(self):
        return self._actual_organizer.pluginList()

    def basePath(self):
        return self._actual_organizer.basePath()

    def gameDataPath(self):
        if hasattr(self._actual_organizer, 'gameDataPath'):
            return self._actual_organizer.gameDataPath()
        else:
            self.log(2, "SkyGen: WARNING: mobase.IOrganizer object has no attribute 'gameDataPath'.")
            return ""
    
    def overwritePath(self):
        """
        Forwards overwritePath to the actual organizer.
        """
        if hasattr(self._actual_organizer, 'overwritePath'):
            return self._actual_organizer.overwritePath()
        else:
            self.log(3, f"SkyGen: ERROR: mobase.IOrganizer object has no attribute 'overwritePath'. This method is required.")
            return ""

    def startApplication(self, executableName: str, arguments: list[str], workingDirectory: str):
        return self._actual_organizer.startApplication(executableName, arguments, workingDirectory)

    def getPathForExecutable(self, executableName: str):
        if hasattr(self._actual_organizer, 'getPathForExecutable'):
            return self._actual_organizer.getPathForExecutable(executableName)
        else:
            self.log(3, f"SkyGen: ERROR: mobase.IOrganizer object has no attribute 'getPathForExecutable'. This method is required.")
            return ""

    def managedGame(self):
        if hasattr(self._actual_organizer, 'managedGame'):
            return self._actual_organizer.managedGame()
        else:
            self.log(3, f"SkyGen: ERROR: mobase.IOrganizer object has no attribute 'managedGame'. This method is required.")
            return None

    def getExecutables(self):
        if hasattr(self._actual_organizer, 'getExecutables'):
            return self._actual_organizer.getExecutables()
        else:
            self.log(3, f"SkyGen: ERROR: mobase.IOrganizer object has no attribute 'getExecutables'. This method is required.")
            return []

# ───────── UI Classes ─────────
class PluginDisambiguationDialog(QDialog):
    def __init__(self, organizer_wrapper, mod_display_name, matching_plugins, parent=None):
        super().__init__(parent)
        self.organizer = organizer_wrapper
        self.mod_display_name = mod_display_name
        self.matching_plugins = matching_plugins
        self.selected_plugin = None

        self.setWindowTitle(f"Select Plugin for '{self.mod_display_name}'")
        layout = QVBoxLayout()

        label = QLabel(f"Multiple active plugins found for '{self.mod_display_name}'.\nPlease select the correct plugin file:")
        layout.addWidget(label)

        self.plugin_combo = QComboBox()
        self.plugin_combo.addItems(sorted(self.matching_plugins, key=lambda s: s.lower()))
        layout.addWidget(self.plugin_combo)

        button_layout = QHBoxLayout()
        ok_button = QPushButton("OK")
        cancel_button = QPushButton("Cancel")
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

        ok_button.clicked.connect(self._accept_selection)
        cancel_button.clicked.connect(self.reject)

        self.setLayout(layout)

    def _accept_selection(self):
        self.selected_plugin = self.plugin_combo.currentText()
        self.accept()


class SkyGenToolDialog(QDialog):

    def _populate_mod_combobox(self, combo_box: QComboBox):
        mod_list = self.organizer.modList()
        plugin_list = self.organizer.pluginList()
        
        if mod_list and plugin_list:
            display_names = set()

            for mod_internal_name in mod_list.allMods():
                if mod_list.state(mod_internal_name) & mobase.ModState.ACTIVE:
                    display_names.add(mod_list.displayName(mod_internal_name))

            base_esms = ["Skyrim.esm", "Update.esm", "Dawnguard.esm", "HearthFires.esm", "Dragonborn.esm"]
            for esm_name in base_esms:
                if esm_name in plugin_list.pluginNames():
                    if plugin_list.state(esm_name) & mobase.PluginState.ACTIVE:
                        display_names.add(esm_name)

            sorted_unique_display_names = sorted(list(display_names), key=lambda s: s.lower())
            combo_box.addItems(sorted_unique_display_names)
        else:
            self.organizer.log(2, "SkyGen: WARNING: Could not retrieve mod or plugin list from organizer.")


    def _browse_igpc_json(self):
        default_start_dir = "H:/Truth Special Edition/overwrite/SKSE/Plugins/StorageUtilData"
        file_path, _ = QFileDialog.getOpenFileName(self, "Select IGPC JSON File", default_start_dir, "JSON Files (*.json)")
        if file_path:
            self.igpc_json_path = file_path
            self.igpc_path_lineEdit.setText(file_path)

    def _browse_xedit_json(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Pre-exported xEdit JSON File", "", "JSON Files (*.json)")
        if file_path:
            self.pre_exported_xedit_json_path = file_path
            self.xedit_json_lineEdit.setText(file_path)

    def _browse_output_folder(self):
        folder_dialog = QFileDialog(self)
        folder_dialog.setFileMode(QFileDialog.FileMode.Directory)
        folder_dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)

        initial_dir = self.organizer.overwritePath() # Default to overwrite
        if initial_dir and os.path.exists(initial_dir):
            folder_dialog.setDirectory(initial_dir)
        elif self.organizer.basePath() and os.path.exists(self.organizer.basePath()):
             folder_dialog.setDirectory(self.organizer.basePath()) # Fallback to base path

        if folder_dialog.exec():
            selected_folder = folder_dialog.selectedFiles()
            if selected_folder:
                self.output_folder_edit.setText(selected_folder[0])
                self.output_folder_path = selected_folder[0]


    def showError(self, title: str, message: str):
        QMessageBox.critical(self, title, message)

    def showWarning(self, title: str, message: str):
        QMessageBox.warning(self, title, message)

    def showInformation(self, title: str, message: str):
        QMessageBox.information(self, title, message)

    def _get_config_data_for_path_lookup(self) -> dict:
        """
        Helper to read config.json for initial xEdit path lookup, similar to display().
        """
        config_file_path = Path(__file__).parent / "config.json"
        config_data = {}
        if config_file_path.is_file():
            try:
                with open(config_file_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
            except Exception as e:
                self.organizer.log(3, f"SkyGen: ERROR: Could not load config.json for path lookup in _get_config_data_for_path_lookup: {e}")
        return config_data


    def _validate_inputs(self) -> bool:
        if not hasattr(self, 'output_folder_path') or not self.output_folder_path:
            self.showWarning("Input Missing", "Please select an Output Folder for the exports.")
            return False
        if self.selected_output_type == "SkyPatcher YAML":
            # NEW: Centralized xEdit path validation
            xedit_path, xedit_mo2_name = get_xedit_exe_path(self._get_config_data_for_path_lookup(), self.organizer, self)
            self.determined_xedit_exe_path = xedit_path
            self.determined_xedit_executable_name = xedit_mo2_name
            
            # Remaining validations (retained after replacement)
            if self.pre_exported_xedit_json_path and not Path(self.pre_exported_xedit_json_path).is_file():
                self.showError("Input Missing", "Pre-exported xEdit JSON file path is invalid.")
                return False
            
            if not self.selected_game_version:
                self.showError("Invalid Selection", "Please select a valid Game Version.")
                return False

            if not self.selected_category or self.selected_category == "Select Category":
                self.showError("Invalid Selection", "Please select a valid Category.")
                return False

            if not self.selected_target_mod_name or self.selected_target_mod_name == "Select Target Mod":
                self.showError("Invalid Selection", "Please select a valid Target Mod.")
                return False
            
            if not self.selected_source_mod_name or self.selected_source_mod_name == "Select Source Mod":
                self.showError("Invalid Selection", "Please select a valid Source Mod.")
                return False

        elif self.selected_output_type == "BOS INI":
            if not self.igpc_json_path or not Path(self.igpc_json_path).is_file():
                self.showError("Input Missing", "Please select a valid IGPC JSON file for BOS INI generation.")
                return False

        return True

    def _on_game_version_toggled(self, version):
        if self.sender().isChecked():
            self.selected_game_version = version
            self.organizer.log(1, f"SkyGen: Game version selected: {self.selected_game_version}")

    def _update_ui_for_output_type(self):
        """
        Adjusts the visibility of UI elements based on the selected output type.
        """
        is_yaml = (self.selected_output_type == "SkyPatcher YAML")

        # Toggle visibility for SkyPatcher YAML related elements
        self.xedit_json_label.setVisible(is_yaml)
        self.xedit_json_lineEdit.setVisible(is_yaml)
        self.xedit_json_button.setVisible(is_yaml)
        self.category_label.setVisible(is_yaml)
        self.category_combo.setVisible(is_yaml)
        self.target_mod_label.setVisible(is_yaml)
        self.target_mod_combo.setVisible(is_yaml)
        self.source_mod_label.setVisible(is_yaml)
        self.source_mod_combo.setVisible(is_yaml)
        self.keywords_label.setVisible(is_yaml)
        self.keywords_lineEdit.setVisible(is_yaml)
        self.broad_category_swap_checkbox.setVisible(is_yaml)
        self.generate_single_btn.setVisible(is_yaml)
        self.generate_all_btn.setVisible(is_yaml)
        self.game_version_label.setVisible(is_yaml)
        self.se_ae_radio.setVisible(is_yaml)
        self.vr_radio.setVisible(is_yaml)


        # Toggle visibility for BOS INI related elements
        self.igpc_path_label.setVisible(not is_yaml)
        self.igpc_path_lineEdit.setVisible(not is_yaml)
        self.igpc_path_button.setVisible(not is_yaml)

        # Adjust main window size to fit content
        self.adjustSize()

    def _on_output_type_toggled(self, output_type):
        if self.sender().isChecked():
            self.selected_output_type = output_type
            self.organizer.log(1, f"SkyGen: Output type selected: {self.selected_output_type}")
            self._update_ui_for_output_type()

            # --- THIS IS THE NEW LOGIC TO WRITE FILES ON TOGGLE ---
            is_yaml = (self.selected_output_type == "SkyPatcher YAML")
            if is_yaml:
                self.organizer.log(1, "SkyGen: SkyPatcher YAML selected. Attempting to write xEdit INI and Pascal script.")
                
                # Write INI file
                # The issue is here: write_xedit_ini_for_skygen needs the dialog_instance
                write_xedit_ini_for_skygen(self.determined_xedit_exe_path, self.organizer, self) # Pass 'self' as dialog_instance
                
                # Write Pascal script and check for success
                if not write_pas_script_to_xedit(self.full_export_script_path, self.organizer):
                    self.showError("Script Write Error", "Failed to write the xEdit Pascal script to disk. Aborting xEdit launch.")
                    self.organizer.log(3, "SkyGen: ABORTING: Pascal script write failed during type toggle.")
                    return # Stop here if write failed

                # Check for JSON.pas dependency
                json_pas_path = self.full_export_script_path.parent / "JSON.pas"
                if not json_pas_path.is_file():
                    self.showError("Missing Dependency", f"Required 'JSON.pas' not found at:\n{json_pas_path}\n\nPlease ensure it's in your xEdit 'Edit Scripts' folder.")
                    self.organizer.log(3, f"SkyGen: ABORTING: Missing JSON.pas dependency at {json_pas_path}.")
                    return # Stop here if JSON.pas is missing

            else: # If not YAML, ensure temporary files are cleaned up
                self.organizer.log(1, "SkyGen: Non-YAML type selected. Cleaning up temporary xEdit INI and Pascal script if they exist.")
                clean_temp_script_and_ini(self.determined_xedit_exe_path, self.full_export_script_path, self.organizer)
            # --- END NEW LOGIC ---

        self.adjustSize()


    def _update_category(self, index):
        self.selected_category = self.category_combo.currentText()
        self.organizer.log(1, f"SkyGen: Category selected: {self.selected_category}")

    def _on_target_mod_selected(self, index):
        self.selected_target_mod_name = self.target_mod_combo.currentText()
        self.organizer.log(1, f"SkyGen: Target mod selected: {self.selected_target_mod_name}")

    def _on_source_mod_selected(self, index):
        self.selected_source_mod_name = self.source_mod_combo.currentText()
        self.organizer.log(1, f"SkyGen: Source mod selected: {self.selected_source_mod_name}")

    def _on_broad_category_swap_changed(self, state):
        self.broad_category_swap_enabled = (state == Qt.CheckState.Checked.value)
        self.organizer.log(1, f"SkyGen: Broad Category Swap enabled: {self.broad_category_swap_enabled}")

    def _load_config(self):
        config_file_path = Path(__file__).parent / "config.json"
        config_data = {}
        if config_file_path.is_file():
            try:
                with open(config_file_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                    self.organizer.log(1, "SkyGen: Successfully loaded config.json.")
            except (IOError, json.JSONDecodeError, UnicodeDecodeError) as e:
                self.organizer.log(3, f"SkyGen: ERROR: Could not load config.json: {e}")
                # Try to backup corrupted config
                try:
                    backup_path = config_file_path.with_suffix('.json.backup')
                    config_file_path.rename(backup_path)
                    self.organizer.log(2, f"SkyGen: Corrupted config backed up to: {backup_path}")
                except Exception as backup_error:
                    self.organizer.log(3, f"SkyGen: Failed to backup corrupted config: {backup_error}")
        else:
            self.organizer.log(1, "SkyGen: config.json not found. Using empty configuration.")

        # MODIFIED: Default output folder to MO2's overwrite path or a robust fallback
        default_overwrite_path = str(self.organizer.overwritePath())
        # Check if overwritePath() is valid and exists, otherwise use a fallback
        if not default_overwrite_path or not Path(default_overwrite_path).is_dir():
            fallback_output_path = Path(__file__).parent / "SkyGen_Output"
            fallback_output_path.mkdir(parents=True, exist_ok=True) # Ensure fallback directory exists
            default_overwrite_path = str(fallback_output_path)
            self.organizer.log(2, f"SkyGen: WARNING: Overwrite path invalid or not found, defaulting output to {default_overwrite_path}")

        self.output_folder_path = config_data.get("output_folder_path", default_overwrite_path)
        
        self.full_export_script_path = Path(config_data.get("full_export_script_path", "H:/Truth Special Edition/tools/SSEEdit/Edit Scripts/ExportPluginData.pas"))
        self.selected_game_version = config_data.get("selected_game_version", "SkyrimSE")
        self.selected_output_type = config_data.get("selected_output_type", "SkyPatcher YAML")
        # INSERTED: Load determined xEdit paths and name from config
        self.determined_xedit_executable_name = config_data.get("xedit_mo2_name", "")
        self.determined_xedit_exe_path = Path(config_data.get("xedit_exe_path", ""))
        
        plugin_map = config_data.get("plugin_disambiguation_map", {})
        self.plugin_disambiguation_map = plugin_map if isinstance(plugin_map, dict) else {}

    def _save_config(self, config: dict):
        config_file_path = Path(__file__).parent / "config.json"
        try:
            config_file_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = config_file_path.with_suffix('.json.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            temp_path.replace(config_file_path)
            self.organizer.log(1, "SkyGen: Successfully saved config.json.")
        except (IOError, OSError, UnicodeEncodeError) as e:
            self.organizer.log(3, f"SkyGen: ERROR: Could not save config.json: {e}")
            temp_path = config_file_path.with_suffix('.json.tmp')
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass

    def _on_generate_single_clicked(self):
        self.organizer.log(1, "SkyGen: 'Generate Single YAML' button clicked.")
        if self._validate_inputs():
            config_to_save = {
                "output_folder_path": self.output_folder_path,
                "selected_game_version": self.selected_game_version,
                "selected_output_type": self.selected_output_type,
                "plugin_disambiguation_map": self.plugin_disambiguation_map,
                # INSERTED: Save determined xEdit name and path before script path
                "xedit_mo2_name": self.determined_xedit_executable_name,
                "xedit_exe_path": str(self.determined_xedit_exe_path),
                "full_export_script_path": str(self.full_export_script_path),
            }
            self._save_config(config_to_save)
            self.generate_all = False
            self.accept()
        else:
            self.organizer.log(1, "SkyGen: Input validation failed for single generation.")

    def _on_generate_all_clicked(self):
        self.organizer.log(1, "SkyGen: 'Generate All Applicable YAMLs' button clicked.")
        if self._validate_inputs():
            config_to_save = {
                "output_folder_path": self.output_folder_path,
                "selected_game_version": self.selected_game_version,
                "selected_output_type": self.selected_output_type,
                "plugin_disambiguation_map": self.plugin_disambiguation_map,
                # INSERTED: Save determined xEdit name and path before script path
                "xedit_mo2_name": self.determined_xedit_executable_name,
                "xedit_exe_path": str(self.determined_xedit_exe_path),
                "full_export_script_path": str(self.full_export_script_path),
            }
            self._save_config(config_to_save)
            self.generate_all = True
            self.accept()
        else:
            self.organizer.log(1, "SkyGen: Input validation failed for all generation.)")


    def _get_xedit_categories(self):
        return [
            "Armor", "Weapon", "Potion", "Book", "Light", "Activator",
            "Container", "Door", "Flora", "Furniture", "Ingredient",
            "Misc. Item", "Outfit", "NPC", "Race", "Spell", "Magic Effect",
            "Worldspace", "Cell", "Ammo", "Soul Gem", "Key", "Scroll",
            "Enchantment", "Armor Addon", "Constructible Object", "Keyword",
            "Faction", "Global", "Class", "Sound Descriptor", "Impact Data Set",
            "Object Effect", "Load Screen", "Weather", "Clutter", "Explosion",
            "Debris", "Liquid", "Tree", "Landscape", "Texture Set",
            "Material Type", "Menu Display Object", "Dialogue Branch", "Quest",
            "Idle Marker", "Lighting Template", "Actor Value Info", "Equip Slot",
            "Form List", "Static"
        ]

    def clean_mod_name_for_plugin_match(self, name_to_clean):
        cleaned = name_to_clean.lower()
        for suffix in [" - se", " - ae", " - vr"]:
            if cleaned.endswith(suffix):
                cleaned = cleaned[:-len(suffix)]
                break
        cleaned = cleaned.replace("'", "").replace("&", "and").replace(" ", "_")
        return cleaned.strip()

    def _get_plugin_name_from_mod_name(self, mo2_mod_display_name: str, mod_internal_name: str) -> Optional[str]:
        if mod_internal_name in self.plugin_disambiguation_map:
            saved_plugin = self.plugin_disambiguation_map[mod_internal_name]
            if saved_plugin in self.organizer.pluginList().pluginNames() and \
               self.organizer.pluginList().state(saved_plugin) & mobase.PluginState.ACTIVE:
                self.organizer.log(0, f"SkyGen: Using saved plugin '{saved_plugin}' for mod '{mo2_mod_display_name}'.")
                return saved_plugin
            else:
                self.organizer.log(2, f"SkyGen: Saved plugin '{saved_plugin}' for mod '{mo2_mod_display_name}' not found or inactive. Re-disambiguating.")
                del self.plugin_disambiguation_map[mod_internal_name]

        cleaned_mod_name = self.clean_mod_name_for_plugin_match(mod_internal_name)
        potential_plugins = []

        for plugin_filename in self.organizer.pluginList().pluginNames():
            # INSERTED: Skip .pas files
            if plugin_filename.lower().endswith(".pas"):
                self.organizer.log(0, f"SkyGen: DEBUG: Skipping .pas file from plugin matching: {plugin_filename}")
                continue
            plugin_state = self.organizer.pluginList().state(plugin_filename)
            
            plugin_stem = Path(plugin_filename).stem
            cleaned_plugin_stem = self.clean_mod_name_for_plugin_match(plugin_stem)

            if (plugin_state & mobase.PluginState.ACTIVE) and \
                           (cleaned_plugin_stem == cleaned_mod_name or
                            cleaned_plugin_stem.startswith(cleaned_mod_name) or
                            cleaned_mod_name in cleaned_plugin_stem):
                potential_plugins.append(plugin_filename)

        if not potential_plugins:
            self.organizer.log(1, f"SkyGen: No active plugin found for mod '{mo2_mod_display_name}' (cleaned: '{cleaned_mod_name}').")
            return None
        elif len(potential_plugins) == 1:
            self.organizer.log(0, f"SkyGen: Found single plugin '{potential_plugins[0]}' for mod '{mo2_mod_display_name}'.")
            self.plugin_disambiguation_map[mod_internal_name] = potential_plugins[0]
            return potential_plugins[0]
        else:
            self.organizer.log(1, f"SkyGen: Multiple plugins found for '{mo2_mod_display_name}'. Showing disambiguation dialog.")
            disambiguation_dialog = PluginDisambiguationDialog(self.organizer, mo2_mod_display_name, potential_plugins, self)
            if disambiguation_dialog.exec() == QDialog.DialogCode.Accepted:
                # MODIFIED: Use disambiguation_dialog.selected_plugin directly
                self.plugin_disambiguation_map[mod_internal_name] = disambiguation_dialog.selected_plugin
                self.organizer.log(1, f"SkyGen: User selected plugin '{disambiguation_dialog.selected_plugin}' for mod '{mo2_mod_display_name}'.")
                return disambiguation_dialog.selected_plugin
            else:
                self.organizer.log(1, f"SkyGen: Plugin selection cancelled for mod '{mo2_mod_display_name}'.")
                return None


    def _init_ui(self):
        layout = QVBoxLayout()

        igpc_path_layout = QHBoxLayout()
        self.igpc_path_label = QLabel("IGPC JSON Path:")
        self.igpc_path_lineEdit = QLineEdit(self.igpc_json_path)
        self.igpc_path_button = QPushButton("Browse...")
        self.igpc_path_button.clicked.connect(self._browse_igpc_json)
        igpc_path_layout.addWidget(self.igpc_path_label)
        igpc_path_layout.addWidget(self.igpc_path_lineEdit)
        igpc_path_layout.addWidget(self.igpc_path_button)
        layout.addLayout(igpc_path_layout)

        xedit_json_layout = QHBoxLayout()
        self.xedit_json_label = QLabel("Pre-exported xEdit JSON (Optional):")
        self.xedit_json_lineEdit = QLineEdit(self.pre_exported_xedit_json_path)
        self.xedit_json_button = QPushButton("Browse...")
        self.xedit_json_button.clicked.connect(self._browse_xedit_json)
        xedit_json_layout.addWidget(self.xedit_json_label)
        xedit_json_layout.addWidget(self.xedit_json_lineEdit)
        xedit_json_layout.addWidget(self.xedit_json_button)
        layout.addLayout(xedit_json_layout)
            
        output_folder_layout = QHBoxLayout()
        self.output_folder_label = QLabel("Output Folder:")
        self.output_folder_edit = QLineEdit()
        self.output_folder_edit.setReadOnly(True)
        self.output_folder_edit.setPlaceholderText("Select folder for xEdit JSON exports")
        self.output_folder_button = QPushButton("Browse")
        self.output_folder_button.clicked.connect(self._browse_output_folder)
        output_folder_layout.addWidget(self.output_folder_label)
        output_folder_layout.addWidget(self.output_folder_edit)
        output_folder_layout.addWidget(self.output_folder_button)
        layout.addLayout(output_folder_layout)


        game_version_layout = QHBoxLayout()
        self.game_version_label = QLabel("Game Version:")
        self.se_ae_radio = QRadioButton("Skyrim SE/AE")
        self.vr_radio = QRadioButton("Skyrim VR")

        if self.selected_game_version == "SkyrimVR":
            self.vr_radio.setChecked(True)
        else:
            self.se_ae_radio.setChecked(True)
            self.selected_game_version = "SkyrimSE"

        self.se_ae_radio.toggled.connect(lambda: self._on_game_version_toggled("SkyrimSE"))
        self.vr_radio.toggled.connect(lambda: self._on_game_version_toggled("SkyrimVR"))

        game_version_layout.addWidget(self.game_version_label)
        game_version_layout.addWidget(self.se_ae_radio)
        game_version_layout.addWidget(self.vr_radio)
        game_version_layout.addStretch(1)
        layout.addLayout(game_version_layout)

        output_type_layout = QHBoxLayout()
        output_type_label = QLabel("Output Type:")
        self.output_type_group = QButtonGroup(self)
        self.yaml_radio = QRadioButton("SkyPatcher YAML")
        self.bos_ini_radio = QRadioButton("BOS INI")

        self.output_type_group.addButton(self.yaml_radio)
        self.output_type_group.addButton(self.bos_ini_radio)

        if self.selected_output_type == "BOS INI":
            self.bos_ini_radio.setChecked(True)
        else:
            self.yaml_radio.setChecked(True)
            self.selected_output_type = "SkyPatcher YAML"

        self.yaml_radio.toggled.connect(lambda: self._on_output_type_toggled("SkyPatcher YAML"))
        self.bos_ini_radio.toggled.connect(lambda: self._on_output_type_toggled("BOS INI"))

        output_type_layout.addWidget(output_type_label)
        output_type_layout.addWidget(self.yaml_radio)
        output_type_layout.addWidget(self.bos_ini_radio)
        output_type_layout.addStretch(1)
        layout.addLayout(output_type_layout)


        category_layout = QHBoxLayout()
        self.category_label = QLabel("Category:")
        self.category_combo = QComboBox()
        categories = ["Select Category"] + self._get_xedit_categories()
        self.category_combo.addItems(categories)
        self.category_combo.currentIndexChanged.connect(self._update_category)
        category_layout.addWidget(self.category_label)
        category_layout.addWidget(self.category_combo)
        layout.addLayout(category_layout)

        target_mod_layout = QHBoxLayout()
        self.target_mod_label = QLabel("Target Mod (To Replace From):")
        self.target_mod_combo = QComboBox()
        self.target_mod_combo.addItem("Select Target Mod")
        self._populate_mod_combobox(self.target_mod_combo)
        self.target_mod_combo.currentIndexChanged.connect(self._on_target_mod_selected)
        target_mod_layout.addWidget(self.target_mod_label)
        target_mod_layout.addWidget(self.target_mod_combo)
        layout.addLayout(target_mod_layout)

        self.source_mod_layout = QHBoxLayout()
        self.source_mod_label = QLabel("Source Mod (Replace With):")
        self.source_mod_combo = QComboBox()
        self.source_mod_combo.addItem("Select Source Mod")
        self._populate_mod_combobox(self.source_mod_combo)
        self.source_mod_combo.currentIndexChanged.connect(self._on_source_mod_selected)
        self.source_mod_layout.addWidget(self.source_mod_label)
        self.source_mod_layout.addWidget(self.source_mod_combo)
        layout.addLayout(self.source_mod_layout)

        self.keywords_layout = QHBoxLayout()
        self.keywords_label = QLabel("Filter by EDID Keywords (comma-separated):")
        self.keywords_lineEdit = QLineEdit("")
        self.keywords_layout.addWidget(self.keywords_label)
        self.keywords_layout.addWidget(self.keywords_lineEdit)
        layout.addLayout(self.keywords_layout)

        self.broad_swap_layout = QHBoxLayout()
        self.broad_category_swap_checkbox = QCheckBox("Enable Broad Category Swap (replaces by category only, not EDID)")
        self.broad_category_swap_checkbox.setChecked(self.broad_category_swap_enabled)
        self.broad_swap_layout.addWidget(self.broad_category_swap_checkbox)
        layout.addLayout(self.broad_swap_layout)

        button_layout = QHBoxLayout()
        self.generate_single_btn = QPushButton("Generate Single YAML")
        self.generate_all_btn = QPushButton("Generate All Applicable YAMLs")
        self.cancel_btn = QPushButton("Cancel")
        button_layout.addWidget(self.generate_single_btn)
        button_layout.addWidget(self.generate_all_btn)
        button_layout.addWidget(self.cancel_btn)
        layout.addLayout(button_layout)

        self.setLayout(layout)


    def __init__(self, organizer: mobase.IOrganizer,
                 parent=None):
        super().__init__(parent)
        self.organizer = organizer
        self.setWindowTitle("SkyGen - SkyPatcher YAML Generator Configuration")
        self.setMinimumWidth(500)

        self.igpc_json_path = ""
        self.pre_exported_xedit_json_path = ""
        self.selected_game_version = ""
        self.selected_category = ""
        self.selected_target_mod_name = ""
        self.selected_source_mod_name = ""
        self.generate_all = False
        self.search_keywords = ""
        self.broad_category_swap_enabled = False
        self.plugin_disambiguation_map = {}
        self.selected_output_type = "SkyPatcher YAML"

        # These are now set in _load_config or determined in _validate_inputs
        self.determined_xedit_executable_name = "" # Initialize to empty string
        self.determined_xedit_exe_path = Path("") # Initialize to empty path
        
        self.full_export_script_path = Path("H:/Truth Special Edition/tools/SSEEdit/Edit Scripts/ExportPluginData.pas")
        self.output_folder_path = ""
        self._load_config() # This will load values from config.json, including xEdit paths

        self._init_ui()

        self.category_combo.currentIndexChanged.connect(self._update_category)
        self.target_mod_combo.currentIndexChanged.connect(self._on_target_mod_selected)
        self.source_mod_combo.currentIndexChanged.connect(self._on_source_mod_selected)
        self.generate_single_btn.clicked.connect(self._on_generate_single_clicked)
        self.generate_all_btn.clicked.connect(self._on_generate_all_clicked)
        self.cancel_btn.clicked.connect(self.reject)
        if hasattr(self, 'broad_category_swap_checkbox'):
            self.broad_category_swap_checkbox.stateChanged.connect(self._on_broad_category_swap_changed)

        self.igpc_path_lineEdit.setText(self.igpc_json_path)
        self.xedit_json_lineEdit.setText(self.pre_exported_xedit_json_path)
        self.output_folder_edit.setText(self.output_folder_path)

        # Call _update_ui_for_output_type initially to set correct visibility
        self._update_ui_for_output_type()
