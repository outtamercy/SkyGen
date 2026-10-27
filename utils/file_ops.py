import os
import shutil
from pathlib import Path
from typing import List, Optional, Union

from .logger import LoggingMixin, MO2_LOG_DEBUG, MO2_LOG_INFO, MO2_LOG_WARNING, MO2_LOG_ERROR


class FileOperationsManager(LoggingMixin):
    """
    Bare-metal file I/O. No config logic, no plugin awareness.
    Just paths, bytes, and error handling.
    """

    def __init__(self, base_path: Union[str, Path]):
        super().__init__()
        self.base_path = Path(base_path)
        self.log_info(f"FileOperationsManager ready at: {self.base_path}")

    def create_directory(self, path: Union[str, Path]) -> bool:
        target_path = Path(path)
        try:
            target_path.mkdir(parents=True, exist_ok=True)
            self.log_debug(f"Ensured dir: {target_path}")
            return True
        except OSError as e:
            self.log_error(f"mkdir failed {target_path}: {e}", exc_info=True)
            return False

    def write_text_file(self, path: Union[str, Path], content: str, encoding: str = 'utf-8') -> bool:
        target_path = Path(path)
        try:
            self.create_directory(target_path.parent)
            target_path.write_text(content, encoding=encoding)
            self.log_debug(f"Wrote text: {target_path}")
            return True
        except IOError as e:
            self.log_error(f"Write failed {target_path}: {e}", exc_info=True)
            return False

    def save_text_file(self, path: Union[str, Path], content: str, encoding: str = 'utf-8') -> bool:
        """Alias — patch_gen.py calls this."""
        return self.write_text_file(path, content, encoding)

    def read_text_file(self, path: Union[str, Path], encoding: str = 'utf-8') -> Optional[str]:
        target_path = Path(path)
        if not target_path.is_file():
            self.log_warning(f"Missing file: {target_path}")
            return None
        try:
            return target_path.read_text(encoding=encoding)
        except IOError as e:
            self.log_error(f"Read failed {target_path}: {e}", exc_info=True)
            return None

    def copy_file(self, source: Union[str, Path], destination: Union[str, Path]) -> bool:
        source_path, dest_path = Path(source), Path(destination)
        if not source_path.is_file():
            self.log_warning(f"Missing source: {source_path}")
            return False
        try:
            self.create_directory(dest_path.parent)
            shutil.copy2(source_path, dest_path)
            self.log_info(f"Copied: {source_path.name} → {dest_path}")
            return True
        except IOError as e:
            self.log_error(f"Copy failed: {e}", exc_info=True)
            return False

    def delete_file(self, path: Union[str, Path]) -> bool:
        target_path = Path(path)
        if not target_path.is_file():
            self.log_warning(f"Missing delete target: {target_path}")
            return False
        try:
            target_path.unlink()
            self.log_debug(f"Deleted file: {target_path}")
            return True
        except OSError as e:
            self.log_error(f"Delete failed {target_path}: {e}", exc_info=True)
            return False

    def delete_directory(self, path: Union[str, Path], ignore_errors: bool = False) -> bool:
        target_path = Path(path)
        if not target_path.is_dir():
            self.log_warning(f"Missing dir: {target_path}")
            return False
        try:
            shutil.rmtree(target_path, ignore_errors=ignore_errors)
            self.log_info(f"Deleted dir: {target_path}")
            return True
        except OSError as e:
            self.log_error(f"Rmdir failed {target_path}: {e}", exc_info=True)
            return False

    def get_file_size(self, path: Union[str, Path]) -> Optional[int]:
        target_path = Path(path)
        if not target_path.is_file():
            return None
        try:
            return target_path.stat().st_size
        except OSError as e:
            self.log_error(f"Stat failed {target_path}: {e}", exc_info=True)
            return None

    def list_directory_contents(self, path: Union[str, Path]) -> List[str]:
        target_path = Path(path)
        if not target_path.is_dir():
            return []
        try:
            return [item.name for item in target_path.iterdir()]
        except OSError as e:
            self.log_error(f"List failed {target_path}: {e}", exc_info=True)
            return []