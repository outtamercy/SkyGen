from pathlib import Path
from typing import Optional, Dict, List, Set, Tuple
from PyQt6.QtCore import QRunnable, pyqtSignal, QObject
from PyQt6.QtWidgets import QApplication
from dataclasses import dataclass, field
import json
import os
import subprocess
import tempfile

# --- PluginDNA: the full genetic fingerprint. ---
# Used to live in frankensnoop. Frankie got his own repo, so the DNA
# stayed behind with us. Family's family, even when they move out.
@dataclass
class PluginDNA:
    signatures: Set[str]
    author: str
    masters: List[str]
    is_esm: bool = False
    is_esl: bool = False
    file_size: int = 0
    mtime: float = 0.0
    file_hash: str = ""

    object_signatures: Set[str] = field(default_factory=set)
    logic_signatures: Set[str] = field(default_factory=set)
    logic_to_content_ratio: float = 0.0
    folder_scents: Set[str] = field(default_factory=set)
    bsa_size: int = 0

    @property
    def is_framework(self) -> bool:
        """Framework check - is this a patcher/engine or a real content mod?"""
        # Hard scents first - folder has BOS swaps or SkyPatcher subdir, it's a framework. Period.
        if "BOS_FRAMEWORK" in self.folder_scents or "SKYPATCHER_FRAMEWORK" in self.folder_scents:
            return True

        # Check if author is on the naughty list
        author_lower = self.author.lower()
        if any(auth.lower() in author_lower for auth in BLACKLIST_AUTHORS):
            return True

        # Masters-only plugins are usually utilities/frameworks
        if len(self.signatures) == 0 and len(self.masters) > 0:
            return True

        return False

    @property
    def is_partial(self) -> bool:
        """Mixed bag - has some content but heavy on scripts/logic."""
        # Needs real objects to be "partial" rather than pure framework
        if not self.object_signatures:
            return False

        # High logic ratio = probably a quest mod or scripted gear
        if self.logic_to_content_ratio > 1.0:
            return True

        # Framework scents mixed with content
        if self.folder_scents and self.logic_to_content_ratio > 0.5:
            return True

        return False

    @property
    def framework_reason(self) -> str:
        """Why did we call it a framework? For the UI tooltip."""
        if not self.is_framework:
            return ""

        if "BOS_FRAMEWORK" in self.folder_scents:
            return "Framework (Base Object Swapper)"
        if "SKYPATCHER_FRAMEWORK" in self.folder_scents:
            return "Framework (SkyPatcher)"

        author_lower = self.author.lower()
        for auth in BLACKLIST_AUTHORS:
            if auth.lower() in author_lower:
                return f"Framework (Author: {self.author})"

        if len(self.signatures) == 0 and len(self.masters) > 0:
            return "Framework (Masters-Only Plugin)"

        if self.folder_scents:
            scent_list = ", ".join(sorted(self.folder_scents))
            return f"Framework (Folder Scents: {scent_list})"

        return "Framework (Unknown)"

    @property
    def is_empty(self) -> bool:
        """No records at all - dummy plugin."""
        return len(self.signatures) == 0

from ..core.constants import GLOBAL_IGNORE_PLUGINS, SCENT_PATTERNS, hash_file_head, BLACKLIST_AUTHORS
from .logger import LoggingMixin, MO2_LOG_DEBUG, SkyGenLogger

__all__ = ['PluginDNA', 'quick_sniff', 'batch_sniff',
           'rust_deep_extract',
           'BatchSnoopWorker', 'sniff_async']

# ---------------------------------------------------------------------------
# sg-extract bridge (rust port of frankensnoop + sigsnoop)
# Same DNA, way faster. Sniffing: no exe = degraded DNA + one loud error, frankie
# retired. Deep extract: no exe = caller falls back to the python extractor.
# ---------------------------------------------------------------------------

_SG_EXE_CANDIDATES = (
    Path(__file__).resolve().parent.parent / "bin" / "sg-extract.exe",
    Path(__file__).resolve().parent.parent / "bin" / "sg-extract",
)
_sg_exe: Optional[Path] = None
_sg_exe_probed = False
_rust_missing_yelled = False


def _find_sg_exe() -> Optional[Path]:
    global _sg_exe, _sg_exe_probed
    if not _sg_exe_probed:
        _sg_exe_probed = True
        for cand in _SG_EXE_CANDIDATES:
            if cand.is_file():
                _sg_exe = cand
                break
    return _sg_exe


# sg-extract is a console app — without this it flashes a cmd window at the
# user every time we sniff. 0 when the flag doesn't exist (non-Windows dev).
_NO_CONSOLE = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _dna_from_rust(d: dict) -> PluginDNA:
    ratio = d.get("logic_to_content_ratio")
    return PluginDNA(
        signatures=set(d.get("signatures", [])),
        author=d.get("author", "Unknown"),
        masters=list(d.get("masters", [])),
        is_esm=bool(d.get("is_esm", False)),
        is_esl=bool(d.get("is_esl", False)),
        file_size=int(d.get("file_size", 0)),
        mtime=float(d.get("mtime", 0.0)),
        file_hash=d.get("file_hash", ""),
        object_signatures=set(d.get("object_signatures", [])),
        logic_signatures=set(d.get("logic_signatures", [])),
        logic_to_content_ratio=float("inf") if ratio is None else float(ratio),
        folder_scents=set(d.get("folder_scents", [])),
        bsa_size=int(d.get("bsa_size", 0)),
    )


def _rust_sniff(path: Path, hint: Optional[Path]) -> Optional[PluginDNA]:
    exe = _find_sg_exe()
    if exe is None:
        return None
    try:
        args = [str(exe), str(path)] + ([str(hint)] if hint else [])
        out = subprocess.run(args, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60,
                             creationflags=_NO_CONSOLE)
        if out.returncode != 0 or not out.stdout.strip():
            return None
        return _dna_from_rust(json.loads(out.stdout.splitlines()[0]))
    except Exception:
        return None


def _rust_batch(paths: List[str],
                hints: Optional[List[Optional[Path]]] = None) -> Optional[Dict[str, PluginDNA]]:
    exe = _find_sg_exe()
    if exe is None or not paths:
        return None
    manifest = None
    try:
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt",
                                         encoding="utf-8") as f:
            for i, p in enumerate(paths):
                hint = hints[i] if hints and i < len(hints) else None
                # windows paths can't hold '|', so it's a safe separator
                if hint:
                    f.write(f"{Path(p)}|{hint}\n")
                else:
                    f.write(f"{Path(p)}\n")
            manifest = f.name
        out = subprocess.run([str(exe), "--batch", manifest], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=600,
                             creationflags=_NO_CONSOLE)
        if out.returncode != 0:
            return None
        results: Dict[str, PluginDNA] = {}
        for line in out.stdout.splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            results[d.get("plugin", "")] = _dna_from_rust(d)
        # partial output = distrust the whole run, let python do it
        if len(results) != len(paths):
            return None
        return results
    except Exception:
        return None
    finally:
        if manifest:
            try:
                os.unlink(manifest)
            except OSError:
                pass


def _rust_deep_extract(jobs, cache_dir, active_plugins, diag_log=None, timeout=1800):
    """Deep-extract bridge. jobs: list of (cachekey, path, filter_str) where
    filter_str is a comma list of record sigs ("" = no filter). Rust writes
    cache files directly (keys come from python — mtime float repr stays our
    problem, not theirs). Returns set of OK paths, or None on any distrust
    (missing exe, bad exit, partial output) so the caller falls back."""
    exe = _find_sg_exe()
    if exe is None or not jobs:
        return None
    listfile = activefile = None
    try:
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt",
                                         encoding="utf-8") as f:
            for key, path, filt in jobs:
                # tab can't appear in windows paths — safe separator
                f.write(f"{key}\t{path}\t{filt or ''}\n")
            listfile = f.name
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt",
                                         encoding="utf-8") as f:
            f.write("\n".join(active_plugins or []))
            activefile = f.name
        out = subprocess.run([str(exe), "--extract", listfile, activefile, str(cache_dir)],
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=timeout,
                             creationflags=_NO_CONSOLE)
        if out.returncode != 0:
            return None
        ok = set()
        for line in out.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0] == "OK":
                ok.add(parts[1])
        if diag_log:
            for line in out.stderr.splitlines():
                if not line.startswith("DIAG\t"):
                    continue
                parts = line.split("\t", 3)
                if len(parts) == 4:
                    diag_log(parts[2], parts[1], parts[3])
        # partial output = distrust the whole run, let python do it
        if len(ok) != len(jobs):
            return None
        return ok
    except Exception:
        return None
    finally:
        for tmp in (listfile, activefile):
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass


def rust_deep_extract(jobs, cache_dir, active_plugins, diag_log=None, timeout=1800):
    """Public wrapper — see _rust_deep_extract."""
    return _rust_deep_extract(jobs, cache_dir, active_plugins, diag_log=diag_log, timeout=timeout)


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
    """One-shot sniff - rust extracts, we add scents."""
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

    # Rust eye first — same DNA, no python grind. None = exe gone or lied, fall through.
    dna = _rust_sniff(path, mod_folder_hint)
    if dna is not None:
        return dna

    # Rust ghosted us and frankie's not on the payroll anymore.
    # Degrade LOUD, not silently — an Unknown DNA is a lie if we don't say so.
    global _rust_missing_yelled
    if not _rust_missing_yelled:
        _rust_missing_yelled = True
        try:
            SkyGenLogger().error(
                "sg-extract.exe missing or refused — no python sniffer left to catch it. "
                "Sniffs return degraded DNA until the exe comes back."
            )
        except Exception:
            pass
    dna = PluginDNA(
        signatures=set(), author="SniffUnavailable", masters=[],
        is_esm=False, is_esl=False, file_size=0, mtime=0.0
    )

    # Merge in our scent detection
    folder_scents = _detect_folder_scents(path, mod_folder_hint)
    if folder_scents:
        dna.folder_scents.update(folder_scents)

    return dna


def batch_sniff(plugin_paths: List[str],
                progress_callback=None,
                chunk_size: int = 5,
                hints: Optional[List[Optional[Path]]] = None) -> Dict[str, PluginDNA]:
    """
    Snoopy's batcher - one rust pass for the whole list when possible,
    otherwise loops through paths one quick_sniff at a time.
    hints: optional per-path mod folder hints (same order as plugin_paths).
    """
    total = len(plugin_paths)

    # Fast path: single rust subprocess for everything, python fallback if it fails.
    if total:
        results = _rust_batch(plugin_paths, hints)
        if results is not None:
            if progress_callback:
                names = [Path(p).name for p in plugin_paths]
                for i in range(0, total, chunk_size):
                    last = min(i + chunk_size, total) - 1
                    progress_callback(last + 1, total, names[last])
            return results

    results: Dict[str, PluginDNA] = {}
    for i, path in enumerate(plugin_paths):
        # One sniff per plugin, no shortcuts
        hint = hints[i] if hints and i < len(hints) else None
        dna = quick_sniff(path, hint)
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