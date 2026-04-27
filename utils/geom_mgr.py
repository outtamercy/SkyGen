# geometry_manager.py – Centralized geometry with namespace isolation
from PyQt6.QtCore import QByteArray, QTimer
from pathlib import Path
from typing import Dict, Set, Optional
import json

from ..utils.logger import LoggingMixin


class GeometryManager(LoggingMixin):
    """
    Centralized geometry persistence with namespace isolation.
    
    Structure:
    {
        "global": {
            "main_window_geometry": <base64>,
            "main_vertical_splitter": <base64>
        },
        "SkyPatcher": {
            "inner_splitter": <base64>,
            "outer_splitter": <base64>
        },
        "BOS": {
            "inner_splitter": <base64>,
            "outer_splitter": <base64>
        }
    }
    """
    
    MIN_SIZE = 20  # Reject Qt's uninitialized state (33 bytes for QSplitter)
    GLOBAL_KEY = "global"
    
    def __init__(self, plugin_path: Path):
        super().__init__()
        
        # Storage path
        data_path = Path(__file__).resolve().parent.parent / "data"
        data_path.mkdir(parents=True, exist_ok=True)
        self._file = data_path / "geometry.dat"
        
        # State
        self._namespaces: Set[str] = set()
        self._pending_restore: Dict[str, Dict[str, QByteArray]] = {}
        self._data: Dict[str, Dict[str, str]] = {}
        
        # Load existing
        self._load()
        self._migrate_flat_keys()
        
        self.log_info(f"GEO-INIT: {len(self._data)} sections, file={self._file.name}")
    
    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register_namespace(self, namespace: str) -> None:
        """Register a panel namespace. Required before save/load."""
        self._namespaces.add(namespace)
        if namespace not in self._data:
            self._data[namespace] = {}
            self.log_debug(f"GEO-REGISTER: {namespace}")
    
    def register_global(self) -> None:
        """Register global namespace for main window chrome."""
        self.register_namespace(self.GLOBAL_KEY)
    
    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def save(self, namespace: str, key: str, geom: QByteArray) -> bool:
        """
        Save geometry to namespace.
        Returns False if namespace not registered or geom invalid.
        """
        if namespace not in self._namespaces:
            self.log_error(f"GEO-SAVE-REJECT: unregistered namespace '{namespace}'")
            return False
        
        size = len(geom)
        if size < self.MIN_SIZE:
            self.log_warning(f"GEO-SAVE-REJECT: {size} bytes for {namespace}.{key}")
            return False
        
        # Store as base64 string
        b64 = geom.toBase64().data().decode('ascii')
        
        if namespace not in self._data:
            self._data[namespace] = {}
        
        self._data[namespace][key] = b64
        self._persist()
        
        self.log_info(f"GEO-SAVE: {namespace}.{key} = {size} bytes")
        return True
    
    def load(self, namespace: str, key: str) -> QByteArray:
        """Load geometry from namespace. Returns empty QByteArray if missing."""
        if namespace not in self._namespaces:
            self.log_error(f"GEO-LOAD-REJECT: unregistered namespace '{namespace}'")
            return QByteArray()
        
        b64 = self._data.get(namespace, {}).get(key)
        if not b64:
            self.log_debug(f"GEO-LOAD-MISS: {namespace}.{key}")
            return QByteArray()
        
        try:
            geom = QByteArray.fromBase64(b64.encode('ascii'))
            self.log_info(f"GEO-LOAD: {namespace}.{key} = {len(geom)} bytes")
            return geom
        except Exception as e:
            self.log_error(f"GEO-LOAD-FAIL: {namespace}.{key} - {e}")
            return QByteArray()
    
    def save_global(self, key: str, geom: QByteArray) -> bool:
        """Shorthand for global namespace."""
        return self.save(self.GLOBAL_KEY, key, geom)
    
    def load_global(self, key: str) -> QByteArray:
        """Shorthand for global namespace."""
        return self.load(self.GLOBAL_KEY, key)
    
    # ------------------------------------------------------------------
    # Deferred Restore (timing-safe)
    # ------------------------------------------------------------------
    def stage_restore(self, namespace: str, widget, key: str) -> None:
        """
        Stage geometry for deferred apply.
        Call from showEvent, then apply_pending_restore() after layout settles.
        """
        geom = self.load(namespace, key)
        if geom and not geom.isEmpty():
            if namespace not in self._pending_restore:
                self._pending_restore[namespace] = {}
            self._pending_restore[namespace][key] = geom
            self.log_debug(f"GEO-STAGE: {namespace}.{key}")
    
    def apply_pending(self, namespace: str, widget_map: Dict[str, object]) -> None:
        """
        Apply staged geometry to widgets.
        widget_map: {"inner_splitter": self.splitter, ...}
        """
        pending = self._pending_restore.get(namespace, {})
        if not pending:
            return
        
        for key, geom in pending.items():
            widget = widget_map.get(key)
            if widget and hasattr(widget, 'restoreState'):
                success = widget.restoreState(geom)
                self.log_info(f"GEO-APPLY: {namespace}.{key} success={success}")
        
        # Clear applied
        self._pending_restore[namespace] = {}
    
    def apply_pending_splitter(self, namespace: str, key: str, splitter) -> None:
        """Convenience for single splitter restore."""
        self.apply_pending(namespace, {key: splitter})
    
    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _persist(self) -> None:
        """Write all data to disk."""
        try:
            with open(self._file, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            self.log_error(f"GEO-PERSIST-FAIL: {e}")
    
    def _load(self) -> None:
        """Load data from disk."""
        if not self._file.exists():
            self._data = {}
            return
        
        try:
            with open(self._file, 'r', encoding='utf-8') as f:
                self._data = json.load(f)
        except Exception as e:
            self.log_error(f"GEO-LOAD-FAIL: {e}")
            self._data = {}
    
    def _migrate_flat_keys(self) -> None:
        """
        One-time migration from flat key format.
        Old: {"SkyPatcher INI_INNER": "base64..."}
        New: {"SkyPatcher": {"inner_splitter": "base64..."}}
        """
        migrations = {
            "SkyPatcher INI_INNER": ("SkyPatcher", "inner_splitter"),
            "SkyPatcher INI_OUTER": ("SkyPatcher", "outer_splitter"),
            "BOS INI_INNER": ("BOS", "inner_splitter"),
            "BOS INI_OUTER": ("BOS", "outer_splitter"),
            "main_window_geometry": (self.GLOBAL_KEY, "main_window_geometry"),
            "main_vertical_splitter_global": (self.GLOBAL_KEY, "main_vertical_splitter"),
        }
        
        migrated = False
        for old_key, (namespace, new_key) in migrations.items():
            if old_key in self._data:
                # Old format was flat string, migrate to nested
                value = self._data.pop(old_key)
                if namespace not in self._data:
                    self._data[namespace] = {}
                self._data[namespace][new_key] = value
                migrated = True
                self.log_info(f"GEO-MIGRATE: {old_key} -> {namespace}.{new_key}")
        
        if migrated:
            self._persist()
            self.log_info("GEO-MIGRATE-COMPLETE")