import os
import shutil
from pathlib import Path
from typing import List, Optional, Union, Dict, Any # Dict will still be needed if other classes use its generic dict operations

from .logger import LoggingMixin, SkyGenLogger, MO2_LOG_DEBUG, MO2_LOG_INFO, MO2_LOG_WARNING, MO2_LOG_ERROR
# Removed import for PLUGIN_CONFIG_FILE_NAME as this class no longer handles plugin-specific config directly


class FileOperationsManager(LoggingMixin):
    """
    Manages file system operations for the SkyGen plugin, ensuring consistent
    logging and error handling. This class provides generic file system utilities.
    Specific plugin-related file paths (like config files) should be managed
    by other dedicated classes (e.g., ConfigManager).
    """

    # CRITICAL FIX: Reverted __init__ signature to only accept base_path
    def __init__(self, base_path: Union[str, Path]):
        super().__init__()
        self.base_path = Path(base_path)
        self.log_info(f"{self.__class__.__name__} initialized with base path: {self.base_path}")

        # CRITICAL FIX: Removed plugin_root_path, config_directory, and config_file_path attributes.
        # This class should not implicitly know about the plugin's config file location.


    def create_directory(self, path: Union[str, Path]) -> bool:
        """Creates a directory and any necessary parent directories."""
        target_path = Path(path)
        try:
            target_path.mkdir(parents=True, exist_ok=True)
            self.log_info(f"Directory created or already exists: {target_path}")
            return True
        except OSError as e:
            self.log_error(f"Failed to create directory {target_path}: {e}", exc_info=True)
            return False

    def write_text_file(self, path: Union[str, Path], content: str, encoding: str = 'utf-8') -> bool:
        """Writes text content to a file."""
        target_path = Path(path)
        try:
            self.create_directory(target_path.parent) # Ensure parent directory exists before writing
            target_path.write_text(content, encoding=encoding)
            self.log_info(f"File written: {target_path}")
            return True
        except IOError as e:
            self.log_error(f"Failed to write file {target_path}: {e}", exc_info=True)
            return False

    def save_text_file(self, path: Union[str, Path], content: str, encoding: str = 'utf-8') -> bool:
        """Alias for write_text_file to match patch_gen.py calls."""
        return self.write_text_file(path, content, encoding)

    def read_text_file(self, path: Union[str, Path], encoding: str = 'utf-8') -> Optional[str]:
        """Reads text content from a file."""
        target_path = Path(path)
        if not target_path.is_file():
            self.log_warning(f"Attempted to read non-existent file: {target_path}")
            return None
        try:
            content = target_path.read_text(encoding=encoding)
            self.log_debug(f"File read: {target_path}")
            return content
        except IOError as e:
            self.log_error(f"Failed to read file {target_path}: {e}", exc_info=True)
            return None

    def copy_file(self, source: Union[str, Path], destination: Union[str, Path]) -> bool:
        """Copies a file from source to destination."""
        source_path = Path(source)
        destination_path = Path(destination)
        if not source_path.is_file():
            self.log_warning(f"Attempted to copy non-existent source file: {source_path}")
            return False
        try:
            self.create_directory(destination_path.parent) # Ensure destination directory exists
            shutil.copy2(source_path, destination_path)
            self.log_info(f"File copied from {source_path} to {destination_path}")
            return True
        except IOError as e:
            self.log_error(f"Failed to copy file from {source_path} to {destination_path}: {e}", exc_info=True)
            return False

    def delete_file(self, path: Union[str, Path]) -> bool:
        """Deletes a file."""
        target_path = Path(path)
        if not target_path.is_file():
            self.log_warning(f"Attempted to delete non-existent file: {target_path}")
            return False
        try:
            target_path.unlink()
            self.log_info(f"File deleted: {target_path}")
            return True
        except OSError as e:
            self.log_error(f"Failed to delete file {target_path}: {e}", exc_info=True)
            return False

    def delete_directory(self, path: Union[str, Path], ignore_errors: bool = False) -> bool:
        """Deletes a directory and all its contents."""
        target_path = Path(path)
        if not target_path.is_dir():
            self.log_warning(f"Attempted to delete non-existent directory: {target_path}")
            return False
        try:
            shutil.rmtree(target_path, ignore_errors=ignore_errors)
            self.log_info(f"Directory deleted: {target_path}")
            return True
        except OSError as e:
            self.log_error(f"Failed to delete directory {target_path}: {e}", exc_info=True)
            return False

    def get_file_size(self, path: Union[str, Path]) -> Optional[int]:
        """Returns the size of a file in bytes."""
        target_path = Path(path)
        if not target_path.is_file():
            self.log_warning(f"Attempted to get size of non-existent file: {target_path}")
            return None
        try:
            return target_path.stat().st_size
        except OSError as e:
            self.log_error(f"Failed to get file size for {target_path}: {e}", exc_info=True)
            return None

    def list_directory_contents(self, path: Union[str, Path]) -> List[str]:
        """Lists the names of all files and directories within a given path."""
        target_path = Path(path)
        if not target_path.is_dir():
            self.log_warning(f"Attempted to list contents of non-existent directory: {target_path}")
            return []
        try:
            return [item.name for item in target_path.iterdir()]
        except OSError as e:
            self.log_error(f"Failed to list directory contents for {target_path}: {e}", exc_info=True)
            return []

    # CRITICAL FIX: Removed save_configuration and load_configuration.
    # These methods, which handle the specific structure of config data,
    # belong in ConfigManager. This class only provides raw file R/W.
