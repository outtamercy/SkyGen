from pathlib import Path
from typing import Optional, Dict, List, Set, Tuple
from PyQt6.QtCore import QRunnable, pyqtSignal, QObject
from PyQt6.QtWidgets import QApplication
from dataclasses import dataclass, field

# --- FRANKIE OWNS EVERYTHING. Snoopy is just a re-export shell. ---
# --- FRANKIE OWNS EXTRACTION. Snoopy re-exports and adds UI helpers. ---
from ..Start_here_before_install.frankensnoop import (
    PluginDNA,
    extract_grup_signatures_deep,
    parse_tes4_header,
    quick_sniff as _frankie_quick_sniff,
)
from ..core.constants import GLOBAL_IGNORE_PLUGINS, SCENT_PATTERNS, hash_file_head
from .logger import LoggingMixin, MO2_LOG_DEBUG

__all__ = ['PluginDNA', 'quick_sniff', 'batch_sniff', 
           'extract_grup_signatures_deep', 'parse_tes4_header',
           'BatchSnoopWorker', 'sniff_async']


def _detect_folder_scents(plugin_path: Path, mod_folder_hint: Optional[Path] = None) -> Set[str]:
    """Pure function - sniff around the mod folder for framework markers."""
    scents = set()
    plugin_name = plugin_path.name
    plugin_stem = plugin_path.stem
    
    if mod_folder_hint and isinstance(mod_folder_hint, Path):
        mod_path = mod_folder_hint
        if mod_path.is_dir():
            bos_swap = mod_path / f"{plugin_stem}_SWAP.ini"
            if bos_swap.exists():
                scents.add("PRE_PATCHED_BOS")
                scents.add("BOS_FRAMEWORK")

            sp_dir = mod_path / "SKSE" / "Plugins" / "SkyPatcher"
            if sp_dir.exists():
                scents.add("SKYPATCHER_FRAMEWORK")
                for ini in sp_dir.rglob("*.ini"):
                    try:
                        with open(ini, 'r', encoding='utf-8', errors='ignore') as f:
                            chunk = f.read(1024)
                            if plugin_name in chunk or plugin_stem in chunk:
                                scents.add("PRE_PATCHED_SP")
                                break
                    except:
                        continue

            if plugin_path.exists():
                size = plugin_path.stat().st_size
                if size < 50 * 1024:
                    scents.add("MICRO_FILE")

    check_strings = [plugin_name]
    if mod_folder_hint:
        folder_name = mod_folder_hint.name if hasattr(mod_folder_hint, 'name') else str(mod_folder_hint)
        check_strings.append(folder_name)
        
    for check_str in check_strings:
        # Normalize to str — constants may ship bytes
        if isinstance(check_str, bytes):
            check_str = check_str.decode('utf-8', errors='ignore')
        
        for scent_name, pattern in SCENT_PATTERNS.items():
            if hasattr(pattern, 'search'):
                if pattern.search(check_str):
                    scents.add(scent_name)
            elif isinstance(pattern, (list, tuple)):
                for keyword in pattern:
                    if isinstance(keyword, bytes):
                        keyword = keyword.decode('utf-8', errors='ignore')
                    if isinstance(keyword, str) and keyword.lower() in check_str.lower():
                        scents.add(scent_name)
                        break
            elif isinstance(pattern, str):
                if pattern.lower() in check_str.lower():
                    scents.add(scent_name)
                
    return scents


def quick_sniff(plugin_path: str, mod_folder_hint: Optional[Path] = None) -> PluginDNA:
    """One-shot sniff - Frankie extracts, we add scents."""
    path = Path(plugin_path)
    
    if not path.exists():
        return PluginDNA(
            signatures=set(), author="Unknown", masters=[],
            is_esm=False, is_esl=False, file_size=0, mtime=0.0
        )
    
    if path.name in GLOBAL_IGNORE_PLUGINS:
        return PluginDNA(
            signatures=set(), author="GlobalIgnore", masters=[],
            is_esm=False, is_esl=False, file_size=0, mtime=0.0,
            file_hash="GLOBAL_IGNORE", folder_scents={"GLOBAL_IGNORE"}
        )
    
    # Frankie's eye - the only disk touch
    dna = _frankie_quick_sniff(str(path), mod_folder_hint)
    
    # Merge in our scent detection
    folder_scents = _detect_folder_scents(path, mod_folder_hint)
    if folder_scents:
        dna.folder_scents.update(folder_scents)
    
    return dna


def batch_sniff(plugin_paths: List[str], 
                progress_callback=None,
                chunk_size: int = 5) -> Dict[str, PluginDNA]:
    """
    Snoopy's batcher - loops through paths and delegates each sniff to Frankie.
    Frankie has no batch function; we keep it local and simple.
    """
    results: Dict[str, PluginDNA] = {}
    total = len(plugin_paths)
    
    for i, path in enumerate(plugin_paths):
        # Frankie's eye on every plugin - no shortcuts
        dna = quick_sniff(path)
        results[Path(path).name] = dna
        
        # Heartbeat back to the UI every chunk
        if progress_callback and (i % chunk_size == 0 or i == total - 1):
            progress_callback(i + 1, total, Path(path).name)
            
    return results

# --- UI threadpool helpers ---

class SnoopWorkerSignals(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)


class BatchSnoopWorker(QRunnable, LoggingMixin):
    def __init__(self, plugin_paths: List[str], chunk_size: int = 5):
        super().__init__()
        LoggingMixin.__init__(self)
        self.plugin_paths = plugin_paths
        self.chunk_size = chunk_size
        self.signals = SnoopWorkerSignals()
        self._is_cancelled = False
        
    def cancel(self):
        self._is_cancelled = True
        
    def run(self):
        results: Dict[str, PluginDNA] = {}
        total = len(self.plugin_paths)
        try:
            for i, path in enumerate(self.plugin_paths):
                if self._is_cancelled:
                    self.log_info("Batch sniff cancelled by user")
                    break
                dna = quick_sniff(path)
                plugin_name = Path(path).name
                results[plugin_name] = dna
                if i % self.chunk_size == 0 or i == total - 1:
                    self.signals.progress.emit(i + 1, total, plugin_name)
                    QApplication.processEvents()
            if not self._is_cancelled:
                self.signals.finished.emit(results)
        except Exception as e:
            self.log_error(f"Batch sniff failed: {e}")
            self.signals.error.emit(str(e))


def sniff_async(plugin_paths: List[str], 
                on_progress=None,
                on_finished=None,
                on_error=None,
                chunk_size: int = 5) -> BatchSnoopWorker:
    worker = BatchSnoopWorker(plugin_paths, chunk_size)
    if on_progress:
        worker.signals.progress.connect(on_progress)
    if on_finished:
        worker.signals.finished.connect(on_finished)
    if on_error:
        worker.signals.error.connect(on_error)
    return worker