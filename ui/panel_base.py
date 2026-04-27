# panel_base.py – Phase-2: splitter-only, no geometry_key mismatch
from PyQt6.QtCore import QSize, QByteArray  # type: ignore
from PyQt6.QtWidgets import QApplication # type: ignore
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .main_dialog import SkyGenMainDialog


class PanelGeometryMixin:
    """Phase-2: splitter-only, consistent save/restore keys."""

    def __init__(self, main_dialog: 'SkyGenMainDialog'):
        self._md = main_dialog  # only store dialog reference

    def save_splitter_state(self) -> None:
        """Manual splitter size tracking - bypass Qt bug."""
        splitter = getattr(self, 'bos_inner_splitter', getattr(self, 'splitter', None))
        if not splitter:
            return
            
        ot = self._md._get_current_output_type_name()
        if not ot:
            return
        
        # FIX: Skip early manual saves for BOS panel
        if ot == "BOS INI" and hasattr(self, '_mods_loaded_once') and not self._mods_loaded_once:
            return  # Prevents 10-byte garbage during initialization
            
        sizes = splitter.sizes()
        if len(sizes) == 2 and sizes[0] > 50:
            key = f"{ot}_INNER_MANUAL"
            namespace = "SkyPatcher" if ot == "SkyPatcher INI" else "BOS"
            key = "inner_splitter_manual"
            geom = QByteArray(bytes(str(sizes), 'utf-8'))
            self._md.geometry_manager.save(namespace, key, geom)
            self._md.log_info(f"GEO-SPLITTER-MANUAL-SAVE: {sizes} ({ot})")

    def restore_splitter_state(self) -> None:
        """Manual splitter size restoration."""
        splitter = getattr(self, 'bos_inner_splitter', getattr(self, 'splitter', None))
        if not splitter:
            return
            
        ot = self._md._get_current_output_type_name()
        if not ot:
            return
            
        key = f"{ot}_INNER_MANUAL"
        namespace = "SkyPatcher" if ot == "SkyPatcher INI" else "BOS"
        key = "inner_splitter_manual"
        state = self._md.geometry_manager.load(namespace, key)
        
        if state and not state.isEmpty():
            try:
                sizes_str = state.data().decode('utf-8')
                sizes = eval(sizes_str)
                if len(sizes) == 2:
                    splitter.setSizes(sizes)
                    self._md.log_info(f"GEO-SPLITTER-MANUAL-RESTORED: {sizes} ({ot})")
                    return
            except:
                pass 
            
    def get_minimum_size(self) -> QSize:
        """Safe minimum size."""
        width = max(400, getattr(self, 'MIN_WIDTH', 600))
        height = max(150, getattr(self, 'MIN_HEIGHT', 180))
        return QSize(width, height)