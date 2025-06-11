import mobase
import os
import json
import yaml
import subprocess
import traceback
from pathlib import Path
from collections import defaultdict
import time # Added for time.sleep
from typing import Optional

# Import functions from the utility file
    # Import functions from the utility file
from .skygen_file_utilities import (
        load_json_data,
        run_xedit_export,
        generate_and_write_skypatcher_yaml,
        generate_bos_ini_files,
        get_xedit_path_from_ini, # Keep this one as it's used in get_xedit_exe_path
        get_xedit_exe_path,      # <--- THIS IS THE CRUCIAL ADDITION
        write_xedit_ini_for_skygen,
        write_pas_script_to_xedit,
        clean_temp_script_and_ini
    )
    
    


# Ensure necessary modules are imported correctly and used appropriately
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
            # MODIFIED: Show QMessageBox on log file open failure
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
                # Changed from mobase.ModState.ENABLED back to mobase.ModState.ACTIVE for compatibility
                if mod_list.state(mod_internal_name) & mobase.ModState.ACTIVE:
                    display_names.add(mod_list.displayName(mod_internal_name))

            base_esms = ["Skyrim.esm", "Update.esm", "Dawnguard.esm", "HearthFires.esm", "Dragonborn.esm"]
            for esm_name in base_esms:
                if esm_name in plugin_list.pluginNames():
                    # mobase.PluginState.ACTIVE is typically correct for plugins
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

    def _on_output_type_toggled(self, output_type):
        if self.sender().isChecked():
            self.selected_output_type = output_type
            self.organizer.log(1, f"SkyGen: Output type selected: {self.selected_output_type}")
            self._update_ui_for_output_type()

    def _update_ui_for_output_type(self):
        is_yaml = (self.selected_output_type == "SkyPatcher YAML")
        is_bos_ini = (self.selected_output_type == "BOS INI")

        self.igpc_path_label.setVisible(is_bos_ini)
        self.igpc_path_lineEdit.setVisible(is_bos_ini)
        self.igpc_path_button.setVisible(is_bos_ini)

        self.xedit_json_label.setVisible(is_yaml)
        self.xedit_json_lineEdit.setVisible(is_yaml)
        self.xedit_json_button.setVisible(is_yaml)
            
        self.output_folder_label.setVisible(True)
        self.output_folder_edit.setVisible(True)
        self.output_folder_button.setVisible(True)

        self.game_version_label.setVisible(is_yaml)
        self.se_ae_radio.setVisible(is_yaml)
        self.vr_radio.setVisible(is_yaml)

        self.category_label.setVisible(is_yaml)
        self.category_combo.setVisible(is_yaml)

        self.target_mod_label.setVisible(is_yaml)
        self.target_mod_combo.setVisible(is_yaml)

        self.source_mod_label.setVisible(is_yaml)
        self.source_mod_combo.setVisible(is_yaml)

        self.keywords_label.setVisible(is_yaml)
        self.keywords_lineEdit.setVisible(is_yaml)

        self.broad_category_swap_checkbox.setVisible(is_yaml)

        if is_yaml:
            self.generate_single_btn.setText("Generate SkyPatcher YAML")
            self.generate_all_btn.setVisible(True)
        elif is_bos_ini:
            self.generate_single_btn.setText("Generate BOS INI")
            self.generate_all_btn.setVisible(False)
        else:
            self.generate_single_btn.setText("Generate")
            self.generate_all_btn.setVisible(False)

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

        self.full_export_script_path = Path(config_data.get("full_export_script_path", "H:/Truth Special Edition/tools/SSEEdit/Edit Scripts/ExportPluginData.pas"))
        # MODIFIED: Default output folder to MO2's overwrite path
        self.output_folder_path = config_data.get("output_folder_path", str(self.organizer.overwritePath())) 
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
        self.determined_xedit_exe_path = Path("") # Initialize to empty path
        self.determined_xedit_executable_name = "" # Initialize to empty string

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

        self._update_ui_for_output_type()


# ───────── Plugin Logic ─────────
class SkyGenPlugin:
    def __init__(self, config_data, dialog, wrapped_organizer):
        self.dialog = dialog
        self.wrapped_organizer = wrapped_organizer

        self.output_folder_path: Path = self._validate_path(config_data.get("output_folder_path"), "Output Folder Path")
        self.full_export_script_path: Path = self._validate_path(config_data.get("full_export_script_path"), "Export Script Path")
        
        # xEdit path and MO2 name are now passed in via config_data, already determined by display()
        self.xedit_exe_path = Path(config_data.get("xedit_exe_path")) if config_data.get("xedit_exe_path") else None
        self.xedit_mo2_name = config_data.get("xedit_mo2_name")

        # Final check: if xEdit path is still not valid, raise an error.
        # The main display() method should have already shown a QMessageBox.
        if not self.xedit_exe_path or not self.xedit_exe_path.is_file() or not self.xedit_mo2_name:
            self.wrapped_organizer.log(3, "SkyGen: ERROR: SkyGenPlugin initialized with invalid xEdit path/name. This should have been caught earlier.")
            raise FileNotFoundError("SkyGenPlugin: xEdit executable or MO2 name is missing/invalid during initialization.")

        self.selected_game_version: str = config_data.get("selected_game_version", "SkyrimSE")
        self.selected_output_type: str = config_data.get("selected_output_type", "SkyPatcher YAML")
        self.plugin_disambiguation_map: dict = config_data.get("plugin_disambiguation_map", {})

    def _validate_path(self, raw_path: Optional[str], label: str) -> Path:
        if not raw_path:
            self.dialog.showError("Config Error", f"Missing {label} in config.json.")
            raise ValueError(f"Missing {label}")
        try:
            path = Path(raw_path).expanduser()
            resolved = path.resolve(strict=False)
            if not resolved.drive:
                raise ValueError("Path does not contain a drive letter.")
            return resolved
        except Exception as e:
            self.dialog.showError("Path Error", f"Invalid {label}: {raw_path}\nError: {e}")
            raise


    def run_export(self, target_plugin_name: str):
        try:
            # Determine if YAML mode is selected
            is_yaml = self.selected_output_type == "SkyPatcher YAML"
            if is_yaml:
                write_xedit_ini_for_skygen(self.xedit_exe_path)
                write_pas_script_to_xedit(self.full_export_script_path)
            
            success = run_xedit_export(
                wrapped_organizer=self.wrapped_organizer,
                dialog=self.dialog,
                xedit_exe_path=self.xedit_exe_path,
                xedit_mo2_name=self.xedit_mo2_name,
                xedit_script_path=self.full_export_script_path,
                output_base_dir=self.output_folder_path,
                target_plugin_filename=target_plugin_name,
                game_version=self.selected_game_version,
                target_mod_display_name=target_plugin_name,
                target_category=getattr(self.dialog, "selected_category", None)
            )
            
            # Clean up temporary files if YAML export mode
            if is_yaml:
                clean_temp_script_and_ini(
                    xedit_exe_path=self.xedit_exe_path,
                    script_path=self.full_export_script_path,
                    wrapped_organizer=self.wrapped_organizer
                )
            
            if not success:
                self.dialog.showError("Export Failed", "The xEdit export did not succeed.")
            return success

        except Exception as e:
            self.dialog.showError("Runtime Error", f"An error occurred while preparing export:\n{str(e)}")
            self.wrapped_organizer.log(1, f"Exception during export: {e}")
            return False


class SkyGenGeneratorTool(mobase.IPluginTool):
    def __init__(self):
        super().__init__()
        self.organizer = None
        self.dialog = None

    def init(self, organizer: mobase.IOrganizer):
        self.organizer = organizer
        return True

    def name(self):
        return "SkyGen"

    def author(self):
        return "Ms. Mayhem & BoltBot"

    def description(self):
        return "SkyPatcher and BOS Gen Tool"

    def version(self):
        return mobase.VersionInfo(1, 0, 0, mobase.ReleaseType.ALPHA)

    def displayName(self):
        return self.name()

    def tooltip(self):
        return "Generate SkyPatcher YAMLs and BOS INIs (Requires SkyPatcher & BOS)"

    def icon(self):
        return QIcon()

    def flags(self):
        return mobase.PluginFeature.Tool | mobase.PluginFeature.Python

    def isActive(self):
        return True

    def settings(self):
        return []

    def display(self):
        if QApplication.instance() is None:
            _ = QApplication([])

        wrapped_organizer = OrganizerWrapper(self.organizer)

        # 1. Load initial config data to pass to get_xedit_exe_path
        config_file_path = Path(__file__).parent / "config.json"
        config_data_for_path_lookup = {}
        if config_file_path.is_file():
            try:
                with open(config_file_path, 'r', encoding='utf-8') as f:
                    config_data_for_path_lookup = json.load(f)
            except Exception as e:
                wrapped_organizer.log(3, f"SkyGen: ERROR: Could not load config.json for initial path lookup: {e}")

        # 2. Determine xEdit path and MO2 name using the centralized logic
        # Pass a temporary QMessageBox instance for initial critical error messages
        temp_msg_box = QMessageBox()
        initial_xedit_exe_path, initial_xedit_mo2_name = get_xedit_exe_path(
            config_data_for_path_lookup, 
            wrapped_organizer, 
            temp_msg_box # Pass a temporary dialog_instance for critical errors
        )

        # 3. If xEdit path could not be found, show a critical error and exit.
        if not initial_xedit_exe_path or not initial_xedit_exe_path.is_file() or not initial_xedit_mo2_name: # Added check for initial_xedit_mo2_name
            QMessageBox.critical(None, "xEdit Not Found", 
                                 "The xEdit executable could not be located or its MO2 name determined. "
                                 "Please ensure it's correctly configured as an executable in Mod Organizer 2, "
                                 "or manually set 'xedit_exe_path' and 'xedit_mo2_name' in the config.json file in the plugin directory.")
            wrapped_organizer.log(3, "SkyGen: xEdit executable or MO2 name not found during initial plugin display. Aborting.")
            wrapped_organizer.close_log_file()
            return

        self.dialog = SkyGenToolDialog(wrapped_organizer) # Initialize dialog without direct path passing
        result = self.dialog.exec()

        if result == 1:
            igpc_json_path = self.dialog.igpc_json_path
            pre_exported_xedit_json_path = self.dialog.xedit_json_lineEdit.text().strip()
            selected_game_version = self.dialog.selected_game_version
            selected_category = self.dialog.selected_category
            selected_target_mod_name = self.dialog.selected_target_mod_name
            selected_source_mod_name = self.dialog.selected_source_mod_name
            generate_all = self.dialog.generate_all
            search_keywords = self.dialog.keywords_lineEdit.text().strip()
            broad_category_swap_enabled = self.dialog.broad_category_swap_enabled
            
            # Retrieve the determined paths from the dialog's state, as they were set during init
            mo2_exec_name_to_use = self.dialog.determined_xedit_executable_name
            xedit_actual_file_path = self.dialog.determined_xedit_exe_path

            # Retrieve the output folder path as a string from the dialog
            output_folder_path_str = self.dialog.output_folder_path

            selected_output_type = self.dialog.selected_output_type
            full_export_script_path = self.dialog.full_export_script_path


            wrapped_organizer.log(1, f"SkyGen: Dialog accepted. Output Type: {selected_output_type}")
            wrapped_organizer.log(1, f"SkyGen: IGPC Path: {igpc_json_path}")
            wrapped_organizer.log(1, f"SkyGen: Output Folder: {output_folder_path_str}") # Log the string version

            igpc_data = None
            if selected_output_type == "BOS INI":
                igpc_data = load_json_data(wrapped_organizer, Path(igpc_json_path), "IGPC JSON", self.dialog)
                if not igpc_data:
                    return

            if selected_output_type == "SkyPatcher YAML":
                wrapped_organizer.log(1, f"SkyGen: Preparing for SkyPatcher YAML generation.")

                wrapped_organizer.log(1, f"SkyGen: Determined xEdit Executable (MO2 Name): {mo2_exec_name_to_use}")
                wrapped_organizer.log(1, f"SkyGen: Actual xEdit Executable Path: {xedit_actual_file_path}")
                wrapped_organizer.log(1, f"SkyGen: Full Export Script Path (from config): {full_export_script_path}")
                wrapped_organizer.log(1, f"SkyGen: Game Version: {selected_game_version}")
                wrapped_organizer.log(1, f"SkyGen: Category: {selected_category}")
                wrapped_organizer.log(1, f"SkyGen: Target Mod: {selected_target_mod_name}")
                wrapped_organizer.log(1, f"SkyGen: Source Mod (Single): {selected_source_mod_name}")
                wrapped_organizer.log(1, f"SkyGen: Search Keywords: {search_keywords}")
                wrapped_organizer.log(1, f"SkyGen: Broad Category Swap Enabled: {broad_category_swap_enabled}")


                target_mod_plugin_name = None
                target_mod_internal_name = None

                for mod_internal_name_candidate in wrapped_organizer.modList().allMods():
                    if wrapped_organizer.modList().displayName(mod_internal_name_candidate) == selected_target_mod_name:
                        target_mod_internal_name = mod_internal_name_candidate
                        wrapped_organizer.log(0, f"SkyGen: Found internal mod name for target mod '{selected_target_mod_name}': {target_mod_internal_name}")
                        break
                if not target_mod_internal_name and selected_target_mod_name.lower().endswith(".esm"):
                    if selected_target_mod_name in wrapped_organizer.pluginList().pluginNames():
                        if wrapped_organizer.pluginList().state(selected_target_mod_name) & mobase.PluginState.ACTIVE:
                            target_mod_internal_name = selected_target_mod_name
                            wrapped_organizer.log(0, f"SkyGen: Target mod is active base game ESM: {target_mod_internal_name}")

                if not target_mod_internal_name:
                    self.dialog.showError("Mod Error", f"Could not find internal mod name for target mod '{selected_target_mod_name}'.")
                    return

                target_mod_plugin_name = self.dialog._get_plugin_name_from_mod_name(selected_target_mod_name, target_mod_internal_name)
                if not target_mod_plugin_name:
                    self.dialog.showError("Plugin Selection Cancelled", f"Target mod plugin selection cancelled or failed for '{selected_target_mod_name}'.")
                    return

                all_exported_target_bases_by_formid = {}
                if pre_exported_xedit_json_path:
                    xedit_exported_data = load_json_data(wrapped_organizer, Path(pre_exported_xedit_json_path), "Pre-exported xEdit JSON", self.dialog)
                    if xedit_exported_data and isinstance(xedit_exported_data, dict):
                        for item in xedit_exported_data.get("sourceModBaseObjects", []):
                            if item.get("FormID"):
                                all_exported_target_bases_by_formid[item["FormID"]] = item
                    else:
                        self.dialog.showError("xEdit Data Error", "Pre-exported xEdit JSON is not in the expected dictionary format or is empty.")
                        return
                else:
                    wrapped_organizer.log(1, f"SkyGen: Determined MO2 executable name for xEdit: '{mo2_exec_name_to_use}' from path stem.")

                    wrapped_organizer.log(1, f"SkyGen: Using full export script path: {full_export_script_path}")


                    # Call run_xedit_export without the -o: argument, ensuring CWD is overwrite
                    success = run_xedit_export(
                        wrapped_organizer=wrapped_organizer,
                        dialog=self.dialog,
                        xedit_exe_path=xedit_actual_file_path,
                        xedit_mo2_name=mo2_exec_name_to_use,
                        xedit_script_path=full_export_script_path,
                        # Pass output_folder_path_str converted to Path object
                        output_base_dir=Path(output_folder_path_str),
                        target_plugin_filename=target_mod_plugin_name,
                        game_version=selected_game_version,
                        target_mod_display_name=target_mod_plugin_name,
                        target_category=selected_category
                    )

                    # Now, assume the output file is "Export.json" in the output_folder_path
                    # The name for actual_xedit_export_path is now generated within run_xedit_export
                    # Need to retrieve the actual output path from the run_xedit_export success
                    # For simplicity, if pre_exported_xedit_json_path is not used, and run_xedit_export
                    # was successful, we assume it generated the file. We would need run_xedit_export
                    # to return the path if we wanted to dynamically load it here.
                    # As a workaround, we will assume it's `output_base_dir / f"SkyGen_xEditExport{safe_plugin_name}{timestamp}.json"`
                    # for the `load_json_data` call below.
                    # This requires replicating the path naming logic or having run_xedit_export return the path.
                    # Let's temporarily assume it's "Export.json" for existing functionality, but acknowledge
                    # this part needs more robust linking if the exact filename is truly dynamic and needed outside.
                    # For now, if the new path is used, the polling will work inside run_xedit_export.
                    # But if we need to load it here, we need the exact name.
                    # Reverting to the old "Export.json" assumption for now for pre-existing loading logic,
                    # or better, make run_xedit_export return this path.
                    xedit_exported_json_path_from_run = run_xedit_export(
                        wrapped_organizer=wrapped_organizer,
                        dialog=self.dialog,
                        xedit_exe_path=xedit_actual_file_path,
                        xedit_mo2_name=mo2_exec_name_to_use,
                        xedit_script_path=full_export_script_path,
                        output_base_dir=Path(output_folder_path_str), # Pass converted Path object
                        target_plugin_filename=target_mod_plugin_name,
                        game_version=selected_game_version,
                        target_mod_display_name=target_mod_plugin_name,
                        target_category=selected_category
                    )

                    if not xedit_exported_json_path_from_run:
                        self.dialog.showError("xEdit Export Failed", "xEdit data export failed. Check MO2 logs for details.")
                        return
                    
                    xedit_exported_data = load_json_data(wrapped_organizer, xedit_exported_json_path_from_run, "xEdit Exported Data", self.dialog)
                    if xedit_exported_data and isinstance(xedit_exported_data, dict):
                        for item in xedit_exported_data.get("sourceModBaseObjects", []):
                            if item.get("FormID"):
                                all_exported_target_bases_by_formid[item["FormID"]] = item
                    else:
                        self.dialog.showError("xEdit Data Error", "xEdit exported JSON is not in the expected dictionary format or is empty.")
                        return
                    
                    try:
                        # Clean up the dynamically named export file here in plugin.py
                        if xedit_exported_json_path_from_run.is_file():
                            xedit_exported_json_path_from_run.unlink()
                            wrapped_organizer.log(1, f"SkyGen: Cleaned up temporary xEdit export file: {xedit_exported_json_path_from_run}")
                    except Exception as e:
                        wrapped_organizer.log(2, f"SkyGen: Failed to delete temporary xEdit export file {xedit_exported_json_path_from_run}: {e}")

                if generate_all:
                    wrapped_organizer.log(1, "SkyGen: Generating YAMLs for all applicable source mods.")
                    generated_count = 0
                    for mod_internal_name in wrapped_organizer.modList().allMods():
                        if wrapped_organizer.modList().state(mod_internal_name) & mobase.ModState.ACTIVE:
                            current_source_mo2_name = wrapped_organizer.modList().displayName(mod_internal_name)
                            current_source_plugin_name = None
                            
                            if current_source_mo2_name.lower().endswith(".esm"):
                                if current_source_mo2_name in wrapped_organizer.pluginList().pluginNames():
                                    if wrapped_organizer.pluginList().state(current_source_mo2_name) & mobase.PluginState.ACTIVE:
                                        current_source_plugin_name = current_source_mo2_name
                                        wrapped_organizer.log(0, f"SkyGen: Source mod is active base game ESM: {current_source_plugin_name}")
                            else:
                                current_source_plugin_name = self.dialog._get_plugin_name_from_mod_name(current_source_mo2_name, mod_internal_name)
                            

                            current_source_mod_base_objects_from_xedit = [
                                item for item in all_exported_target_bases_by_formid.values()
                                if item.get("originMod") == current_source_plugin_name and item.get("category") == selected_category
                            ]

                            if current_source_mod_base_objects_from_xedit:
                                wrapped_organizer.log(1, f"SkyGen: Attempting to generate YAML for '{current_source_mo2_name}'...")
                                if generate_and_write_skypatcher_yaml(
                                    wrapped_organizer,
                                    selected_category,
                                    target_mod_plugin_name,
                                    current_source_plugin_name,
                                    current_source_mo2_name,
                                    current_source_mod_base_objects_from_xedit,
                                    all_exported_target_bases_by_formid,
                                    broad_category_swap_enabled,
                                    search_keywords,
                                    self.dialog,
                                    Path(output_folder_path_str) # Convert to Path here
                                ):
                                    generated_count += 1
                            else:
                                wrapped_organizer.log(0, f"SkyGen: No relevant base objects found for '{current_source_mo2_name}' in category '{selected_category}'. Skipping.")
                    self.dialog.showInformation("Generation Complete", f"Generated {generated_count} YAML file(s). Check SkyPatcher/Configs.")

                else: # Single generation
                    wrapped_organizer.log(1, f"SkyGen: Generating single YAML for source mod: {selected_source_mod_name}")
                    
                    selected_source_mod_plugin_name = None
                    selected_source_mod_internal_name = None

                    for mod_internal_name_candidate in wrapped_organizer.modList().allMods():
                        if wrapped_organizer.modList().displayName(mod_internal_name_candidate) == selected_source_mod_name:
                            selected_source_mod_internal_name = mod_internal_name_candidate
                            wrapped_organizer.log(0, f"SkyGen: Found internal mod name for source mod '{selected_source_mod_name}': {selected_source_mod_internal_name}")
                            break
                    if not selected_source_mod_internal_name and selected_source_mod_name.lower().endswith(".esm"):
                        if selected_source_mod_name in wrapped_organizer.pluginList().pluginNames():
                            if wrapped_organizer.pluginList().state(selected_source_mod_name) & mobase.PluginState.ACTIVE:
                                selected_source_mod_internal_name = selected_source_mod_name
                                wrapped_organizer.log(0, f"SkyGen: Source mod is active base game ESM: {selected_source_mod_internal_name}")

                    if not selected_source_mod_internal_name:
                        self.dialog.showError("Mod Error", f"Could not find internal mod name for source mod '{selected_source_mod_name}'.")
                        return

                    selected_source_mod_plugin_name = self.dialog._get_plugin_name_from_mod_name(selected_source_mod_name, selected_source_mod_internal_name)
                    if not selected_source_mod_plugin_name:
                        self.dialog.showError("Plugin Selection Cancelled", f"Source mod plugin selection cancelled or failed for '{selected_source_mod_name}'.")
                        return

                    selected_source_mod_base_objects_from_xedit = [
                        item for item in all_exported_target_bases_by_formid.values()
                        if item.get("originMod") == selected_source_mod_plugin_name and item.get("category") == selected_category
                    ]

                    if selected_source_mod_base_objects_from_xedit:
                        if generate_and_write_skypatcher_yaml(
                            wrapped_organizer,
                            selected_category,
                            target_mod_plugin_name,
                            selected_source_mod_plugin_name,
                            selected_source_mod_name,
                            selected_source_mod_base_objects_from_xedit,
                            all_exported_target_bases_by_formid,
                            broad_category_swap_enabled,
                            search_keywords,
                            self.dialog,
                            Path(output_folder_path_str) # Convert to Path here
                        ):
                            self.dialog.showInformation("Generation Complete", f"Successfully generated YAML for '{selected_source_mod_name}'. Check SkyPatcher/Configs.")
                        else:
                            self.dialog.showWarning("Generation Skipped", f"No replacements generated for '{selected_source_mod_name}'. YAML not created.")
                    else:
                        self.dialog.showWarning("No Relevant Bases", f"No relevant base objects found for '{selected_source_mod_name}'. YAML not created for category '{selected_category}'.")
            
            elif selected_output_type == "BOS INI":
                wrapped_organizer.log(1, f"SkyGen: Generating BOS INI files.")
                if generate_bos_ini_files(
                    wrapped_organizer,
                    igpc_data,
                    Path(output_folder_path_str), # Convert to Path here
                    self.dialog
                ):
                    self.dialog.showInformation("Generation Complete", f"Successfully generated BOS INI files. Check output folder.")
                else:
                    self.dialog.showWarning("Generation Skipped", f"No BOS INI files generated.")

        else:
            wrapped_organizer.log(1, "SkyGen: Dialog cancelled.")

        wrapped_organizer.close_log_file()
