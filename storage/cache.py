"""
File-based caching for the SkyGen plugin.

This module provides a simple mechanism to cache data to disk,
useful for speeding up operations by storing intermediate results.
"""

import os
import json
import hashlib
import base64
from pathlib import Path
from typing import Any, Optional, Dict, List


# Import SkyGen's logging for consistent output
from ..utils.logger import LoggingMixin, SkyGenLogger, MO2_LOG_DEBUG, MO2_LOG_INFO, MO2_LOG_WARNING, MO2_LOG_ERROR


def _json_serial(obj: Any) -> Any:
    """JSON serializer for objects not natively serializable."""
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode('ascii')
    raise TypeError(f"Type {type(obj)} not serializable")


class CacheManager(LoggingMixin):
    """
    Manages file-based caching for SkyGen.

    Provides methods to save, load, and clear cached data.
    Data is stored as JSON files in a dedicated cache directory.
    """

    def __init__(self, plugin_path: str):
        """
        Initialize the CacheManager.

        Args:
            plugin_path: The base path of the SkyGen plugin directory.
        """
        super().__init__()
        # Cache directory is within the plugin's data directory for better isolation
        self.cache_dir = Path(plugin_path) / "data" / "cache" 
        self.log_info(f"CacheManager initialized. Cache directory: {self.cache_dir}")
        self._ensure_cache_dir()

    def _ensure_cache_dir(self) -> bool:
        """Ensures the cache directory exists."""
        try:
            if not self.cache_dir.is_dir():
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                self.log_debug(f"Created cache directory: {self.cache_dir}")
            return True
        except Exception as e:
            self.log_error(f"Failed to create cache directory {self.cache_dir}: {e}", exc_info=True)
            return False

    def _get_cache_file_path(self, key: str) -> Path:
        """Generates a unique file path for a cache key."""
        # Use SHA256 hash of the key to ensure valid filenames and avoid path issues
        safe_key = hashlib.sha256(key.encode('utf-8')).hexdigest()
        return self.cache_dir / f"{safe_key}.json"

    # ------------------------------------------------------------------
    #  CC mode-specific cache key
    # ------------------------------------------------------------------
    def generate_key(self, plugins: List[str], category: Optional[str], 
                     target_mod: Optional[str] = None, source_mod: Optional[str] = None) -> str:
        key_data = f"{'_'.join(sorted(plugins))}_{category}"
        if target_mod:
            key_data += f"_{target_mod}"
        if source_mod:
            key_data += f"_{source_mod}"
        return hashlib.sha256(key_data.encode()).hexdigest()

    def save_to_cache(self, key: str, data: Any) -> bool:
        """
        Saves data to the cache.

        Args:
            key: A unique string key for the data.
            data: The data to cache (must be JSON-serializable).

        Returns:
            True if saved successfully, False otherwise.
        """
        if not self._ensure_cache_dir():
            return False

        cache_file = self._get_cache_file_path(key)
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, separators=(',', ':'), default=_json_serial)
            self.log_debug(f"Saved to cache: {key} -> {cache_file}")
            return True
        except Exception as e:
            self.log_error(f"Failed to save data to cache file {cache_file} for key '{key}': {e}", exc_info=True)
            return False

    def load_from_cache(self, key: str) -> Optional[Any]:
        """
        Loads data from the cache.

        Args:
            key: The unique string key of the data.

        Returns:
            The cached data, or None if not found or an error occurs.
        """
        cache_file = self._get_cache_file_path(key)
        if not cache_file.is_file():
            self.log_debug(f"Cache file not found for key '{key}' at {cache_file}")
            return None
        
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.log_debug(f"Loaded from cache: {key} -> {cache_file}")
            return data
        except json.JSONDecodeError as e:
            self.log_error(f"Failed to decode JSON from cache file {cache_file} for key '{key}': {e}. Deleting corrupted file.")
            self.delete_from_cache(key) # Delete corrupted file
            return None
        except Exception as e:
            self.log_error(f"Failed to load data from cache file {cache_file} for key '{key}': {e}", exc_info=True)
            return None

    def clear_cache(self) -> bool:
        """
        Clears all items from the cache directory.

        Returns:
            True if the cache was cleared successfully, False otherwise.
        """
        if not self.cache_dir.is_dir():
            self.log_debug("Cache directory does not exist, nothing to clear.")
            return True # Already clear

        try:
            for item in self.cache_dir.iterdir():
                if item.is_file():
                    item.unlink() # Delete file
            self.log_info(f"Cache cleared: {self.cache_dir}")
            return True
        except Exception as e:
            self.log_error(f"Failed to clear cache directory {self.cache_dir}: {e}", exc_info=True)
            return False

    def delete_from_cache(self, key: str) -> bool:
        """
        Deletes a specific item from the cache.

        Args:
            key: The unique string key of the item to delete.

        Returns:
            True if the item was deleted or did not exist, False on error.
        """
        cache_file = self._get_cache_file_path(key)
        if not cache_file.is_file():
            self.log_debug(f"Cache file for key '{key}' not found, nothing to delete.")
            return True # Already gone

        try:
            cache_file.unlink()
            self.log_debug(f"Deleted item from cache: {key} -> {cache_file}")
            return True
        except Exception as e:
            self.log_error(f"Failed to delete cache file {cache_file} for key '{key}': {e}", exc_info=True)
            return False

    def exists_in_cache(self, key: str) -> bool:
        """Check if key exists without loading."""
        return self._get_cache_file_path(key).is_file()