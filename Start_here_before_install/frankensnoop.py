"""
FrankenSnoop - Deep extraction tool for SkyGen manifest.
Run via MO2 executable for full VFS visibility.
Generates profile-specific INI with 100% accurate signatures.
Self-contained: includes sniff logic to avoid import hell.
"""

import configparser
import time
import hashlib
import os
import sys
import argparse
import re
import mmap
import struct
from pathlib import Path
from typing import Set, List, Tuple, Optional, Dict
from dataclasses import dataclass, field

# Dual-mode import for constants only
if __name__ == '__main__' or __package__ is None:
        plugin_root = Path(__file__).resolve().parent.parent
        if str(plugin_root) not in sys.path:
                sys.path.insert(0, str(plugin_root))
        from core.constants import (BASE_GAME_PLUGINS, GLOBAL_IGNORE_PLUGINS, AE_CORE_FILES, 
                                  OFFICIAL_CC_PREFIX, hash_file_head, BLACKLIST_AUTHORS, BLACKLIST_KEYWORDS,
                                  FRAMEWORK_SCENTS, FRAMEWORK_LOGIC_SIGNATURES, SCENT_PATTERNS as DEEP_SCENTS)
else:
        from core.constants import (BASE_GAME_PLUGINS, GLOBAL_IGNORE_PLUGINS, AE_CORE_FILES, 
                                  OFFICIAL_CC_PREFIX, hash_file_head, BLACKLIST_AUTHORS, BLACKLIST_KEYWORDS,
                                  FRAMEWORK_SCENTS, FRAMEWORK_LOGIC_SIGNATURES, SCENT_PATTERNS as DEEP_SCENTS,
                                  )

# ---- SELF-CONTAINED SNOOP LOGIC ----

@dataclass
class PluginDNA:
        """The full genetic fingerprint - duplicated from snoop for standalone operation."""
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
            # Hard scents first - if folder has BOS swaps or SkyPatcher subdir, it's a framework. Period.
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

# Regex patterns for folder sniffing
SCENT_PATTERNS = {
        "SKSE": re.compile(r"SKSE|skse|Script Extender", re.I),
        "DynDOLOD": re.compile(r"DynDOLOD|dyndolod|LOD", re.I),
        "xEdit": re.compile(r"SSEEdit|xEdit|TES5Edit|FO4Edit", re.I),
        "Synthesis": re.compile(r"Synthesis|Mutagen", re.I),
        "Menu": re.compile(r"SkyUI|AddItemMenu|RaceMenu|UIExtensions", re.I),
        "Framework": re.compile(r"Framework|Base Object Swapper|Papyrus Extender|Address Library", re.I),
        "Engine": re.compile(r"Engine Fixes|Bug Fixes|SSE Fixes", re.I),
}

LOGIC_SIGS = {"QUST", "MGEF", "KYWD", "VMAD", "SCRP", "DLBR", "INFO", "DIAL"}
OBJECT_SIGS = {"ARMO", "WEAP", "NPC_", "STAT", "FURN", "MISC", "CONT", "LIGH", "ALCH", "BOOK", "AMMO"}


def extract_grup_signatures_deep(filepath: Path) -> Tuple[Set[str], bool]:
        """Rip through a plugin and grab every GRUP signature."""
        signatures = set()
        try:
                with open(filepath, 'rb') as f:
                        # Try mmap first – fast path for real files
                        try:
                                with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                                        sigs, ok = _scan_memoryview(mm)
                                        if ok and sigs:
                                                return sigs, True
                        except (OSError, ValueError, mmap.error):
                                pass  # VFS handle failed, fall through
                        
                        # Fallback: slurp and scan – works on VFS virtual files
                        f.seek(0)
                        data = f.read()
                        sigs, ok = _scan_memoryview(memoryview(data))
                        return sigs, ok
                        
        except Exception:
                return signatures, False


def _scan_memoryview(mv) -> Tuple[Set[str], bool]:
        """Scan a memoryview/mmap for GRUP signatures."""
        signatures = set()
        if len(mv) < 24 or bytes(mv[:4]) != b'TES4':
                return signatures, False
        
        tes4_size = int.from_bytes(mv[4:8], byteorder='little')
        grup_start = 24 + tes4_size
        if grup_start >= len(mv):
                return signatures, True
        
        offset = grup_start
        file_len = len(mv)
        
        while offset < file_len - 24:
                if bytes(mv[offset:offset+4]) == b'GRUP':
                        record_type = bytes(mv[offset+8:offset+12]).decode('ascii', errors='ignore')
                        if len(record_type) == 4 and record_type.isalnum():
                                signatures.add(record_type)
                        grup_size = int.from_bytes(mv[offset+4:offset+8], byteorder='little')
                        if grup_size < 24:
                                break
                        offset += grup_size
                else:
                        offset += 1
        
        return signatures, True


def parse_tes4_header(filepath: Path, max_size: int = 8192) -> Tuple[str, List[str], bool]:
        """Snag author and masters from header."""
        try:
                with open(filepath, 'rb') as f:
                        data = f.read(max_size)
                if len(data) < 24 or data[:4] != b'TES4':
                        return "Unknown", [], False
                tes4_size = int.from_bytes(data[4:8], byteorder='little')
                offset = 24
                end_offset = min(24 + tes4_size, len(data))
                author = "Unknown"
                masters = []
                while offset < end_offset - 6:
                        sub_type = data[offset:offset+4]
                        sub_size = int.from_bytes(data[offset+4:offset+6], byteorder='little')
                        offset += 6
                        if offset + sub_size > len(data):
                                break
                        if sub_type == b'CNAM':
                                author_bytes = data[offset:offset+sub_size]
                                if author_bytes and author_bytes[-1] == 0:
                                        author_bytes = author_bytes[:-1]
                                try:
                                        author = author_bytes.decode('utf-8', errors='ignore').strip()
                                except:
                                        pass
                        elif sub_type == b'MAST':
                                master_bytes = data[offset:offset+sub_size]
                                if master_bytes and master_bytes[-1] == 0:
                                        master_bytes = master_bytes[:-1]
                                try:
                                        master_name = master_bytes.decode('utf-8', errors='ignore').strip()
                                        if master_name:
                                                masters.append(master_name)
                                except:
                                        pass
                        offset += sub_size
                return author, masters, True
        except Exception:
                return "Unknown", [], False


def _detect_folder_scents(plugin_path: Path, mod_folder_hint: Optional[Path] = None) -> Set[str]:
        """Sniff around the mod folder for framework markers."""
        scents = set()
        plugin_name = plugin_path.name
        plugin_stem = plugin_path.stem
        
        check_strings = [plugin_name]
        if mod_folder_hint:
                folder_name = mod_folder_hint.name if hasattr(mod_folder_hint, 'name') else str(mod_folder_hint)
                check_strings.append(folder_name)
                
                bos_swap = mod_folder_hint / f"{plugin_stem}_SWAP.ini"
                if bos_swap.exists():
                        scents.add("PRE_PATCHED_BOS")
                        scents.add("BOS_FRAMEWORK")

                sp_dir = mod_folder_hint / "SKSE" / "Plugins" / "SkyPatcher"
                if sp_dir.exists():
                        scents.add("SKYPATCHER_FRAMEWORK")
                
                if plugin_path.exists():
                        size = plugin_path.stat().st_size
                        if size < 50 * 1024:
                                scents.add("MICRO_FILE")
        
        for check_str in check_strings:
                for scent_name, pattern in SCENT_PATTERNS.items():
                        if pattern.search(check_str):
                                scents.add(scent_name)
                                
        return scents

def _detect_pluginless_assets(mods_path: Path, modlist: List[str], manifest_config: configparser.ConfigParser) -> None:
    """Scan for pluginless asset mods (body replacers, etc.) and inject synthetic entries."""
    for idx, mod_folder in enumerate(modlist):
        if not mod_folder or mod_folder.endswith('_separator'):
            continue
            
        mod_path = mods_path / mod_folder
        
        # Skip if this mod already has plugins (Frankie handled those)
        has_plugins = any(mod_path.glob("*.esp")) or any(mod_path.glob("*.esm")) or any(mod_path.glob("*.esl"))
        if has_plugins:
            continue
        
        # Look for heavy BSAs with character assets
        bsa_files = list(mod_path.glob("*.bsa")) + list(mod_path.glob("*.ba2"))
        total_bsa_size = sum(f.stat().st_size for f in bsa_files if f.exists())
        
        if total_bsa_size < (100 * 1024 * 1024):  # 100MB threshold
            continue
            
        # Check for character asset paths
        char_paths = list(mod_path.rglob("actors/character*"))
        if not char_paths:
            char_paths = list(mod_path.rglob("actors\\character*"))
        
        if not char_paths:
            continue
        
        # Detect specific asset type from folder structure
        scents = set()
        if any('body' in str(p).lower() for p in char_paths):
            scents.add('ASSET_BODY')
        if any('hair' in str(p).lower() or 'beard' in str(p).lower() for p in char_paths):
            scents.add('ASSET_HAIR')
        if any('skin' in str(p).lower() or 'face' in str(p).lower() for p in char_paths):
            scents.add('ASSET_SKIN')
        
        # Synthesize a ManifestEntry as a new section
        section_name = f"ASSET_{mod_folder}"
        manifest_config.add_section(section_name)
        manifest_config.set(section_name, 'hash', f"ASSET_{mod_folder}")
        manifest_config.set(section_name, 'mtime', str(max((f.stat().st_mtime for f in bsa_files), default=0.0)))
        manifest_config.set(section_name, 'size', str(total_bsa_size))
        manifest_config.set(section_name, 'author', 'Asset Mod')
        manifest_config.set(section_name, 'signatures', ', '.join(scents))
        manifest_config.set(section_name, 'masters', '')
        manifest_config.set(section_name, 'object_signatures', '')
        manifest_config.set(section_name, 'logic_signatures', '')
        manifest_config.set(section_name, 'logic_to_content_ratio', '0.0')
        manifest_config.set(section_name, 'folder_scents', ', '.join(scents))
        manifest_config.set(section_name, 'is_framework', 'False')
        manifest_config.set(section_name, 'framework_reason', '')
        manifest_config.set(section_name, 'is_blessed', 'False')
        manifest_config.set(section_name, 'is_partial', 'False')
        manifest_config.set(section_name, 'lo_index', '-1')  # No load order
        manifest_config.set(section_name, 'layer', 'bos')  # Eligible for BOS
        manifest_config.set(section_name, 'lc_score', '10')
        manifest_config.set(section_name, 'lc_confidence', 'high')
        
        print(f"[FrankenSnoop] ASSET_ANCHOR: {mod_folder} ({total_bsa_size/(1024*1024):.0f}MB, scents: {scents})")

def quick_sniff(plugin_path: str, mod_folder_hint: Optional[Path] = None) -> PluginDNA:
        """One-shot sniff - gives full DNA including scents and ratios."""
        path = Path(plugin_path)
        
        if not path.exists():
                return PluginDNA(signatures=set(), author="Unknown", masters=[])
        
        if path.name in GLOBAL_IGNORE_PLUGINS:
                return PluginDNA(
                        signatures=set(), author="GlobalIgnore", masters=[],
                        folder_scents={"GLOBAL_IGNORE"}, file_hash="GLOBAL_IGNORE"
                )
        
        try:
                file_stat = path.stat()
                signatures, success = extract_grup_signatures_deep(path)
                author, masters, header_ok = parse_tes4_header(path)
                
                if not success and not header_ok:
                        return PluginDNA(signatures=set(), author="Unknown", masters=[])
                
                object_sigs = signatures.intersection(OBJECT_SIGS)
                logic_sigs = signatures.intersection(LOGIC_SIGS)
                
                if len(object_sigs) == 0:
                        ratio = float('inf') if len(logic_sigs) > 0 else 0.0
                else:
                        ratio = len(logic_sigs) / len(object_sigs)
                
                folder_scents = _detect_folder_scents(path, mod_folder_hint)
                
                return PluginDNA(
                        signatures=signatures,
                        author=author,
                        masters=masters,
                        file_size=file_stat.st_size,
                        mtime=file_stat.st_mtime,
                        file_hash=hash_file_head(path),
                        object_signatures=object_sigs,
                        logic_signatures=logic_sigs,
                        logic_to_content_ratio=ratio,
                        folder_scents=folder_scents,
                )
                
        except Exception:
                return PluginDNA(signatures=set(), author="Unknown", masters=[])


# ---- FRANKIE'S BUILD LOGIC WITH ART ----

CURRENT_APP_VERSION = "0.9.0-BETA"
CURRENT_EXTRACTION_LOGIC_VERSION = 2
BLESSED_HASH_PREFIX = "BLESSED_"

def get_loadorder_signature(plugins: List[str]) -> str:
        """Generate hash of plugin sequence."""
        sequence = "|".join(p.lower() for p in plugins if p)
        return hashlib.sha256(sequence.encode()).hexdigest()[:16]

def build_manifest(source_dir: Path, output_path: Path, profile_name: str = "Default", 
                   profile_dir: Optional[Path] = None, mods_dir: Optional[Path] = None) -> None:
        """Build manifest from loadorder.txt - now with rich data."""
        config = configparser.ConfigParser()
        failed_plugins = []
        blessed_plugins: List[Path] = []
        mod_plugins: List[Path] = []
        
        # THE ART - RESTORED
        print(r"""
[FRANKENSNOOP] IS ALIVE!


                         .-=-=-=-=-=-=-=-=-=-=-=-.
                        /                         \
                       /       S K Y G E N         \
                      /                             \
                     |                               |
                     |                               |
                     |         .-----------.         |
                     |        /  .-----.  \        |
                     |       |  /   ___   \  |       |
                     |       | |   /   \   | |       |
                     |       | |  | o o |  | |       |
                     |       | |   \ _ /   | |       |
                     |       | |    | |    | |       |
                     |       |  \  '-'  /  |       |
                     |        \  '-----'  /        |
                     |         '-----------'         |
                     |              |               |
                     |              |               |
                     |         _____|_____          |
                     |        /     |     \         |
                     |       |      |      |        |
                     |       |      |      |        |
                     '-------|      |      |--------'
                             |______|______|
                              /    |    \
                             /____|____\
                             '--'   '--'
        
        "It's alive! It's alive!!"
        Cold Booting: Starting plugin scan...
    """)
        
        # Load order slurp
        loadorder: List[str] = []
        if profile_dir and profile_dir.exists():
                loadorder_txt = profile_dir / "loadorder.txt"
                if loadorder_txt.exists():
                        with open(loadorder_txt, 'r', encoding='utf-8', errors='ignore') as f:
                                for line in f:
                                        line = line.strip()
                                        if not line or line.startswith('#'):
                                                continue
                                        loadorder.append(line)
                        print(f"[FrankenSnoop] Loaded {len(loadorder)} plugins from loadorder.txt")
                else:
                        print(f"[FrankenSnoop] WARNING: No loadorder.txt found")
                        return
        
        # Sort the sheep from the goats
        print(f"[FrankenSnoop] Scanning VFS-merged Data: {source_dir}")
        block_counter = 0
        
        for plugin_name in loadorder:
                block_counter += 1
                if block_counter % 10 == 0:
                        time.sleep(0.01)
                
                if not plugin_name:
                        continue
                
                if plugin_name in GLOBAL_IGNORE_PLUGINS:
                        print(f"[GLOBAL_IGNORE] Skipping {plugin_name}")
                        continue
                
                plugin_path = source_dir / plugin_name
                if not plugin_path.exists() and mods_dir and mods_dir.exists():
                        for mod_folder in mods_dir.iterdir():
                                if not mod_folder.is_dir():
                                        continue
                                candidate = mod_folder / plugin_name
                                if candidate.exists():
                                        plugin_path = candidate
                                        break
                
                if not plugin_path.exists():
                        failed_plugins.append((plugin_name, "File not found"))
                        print(f"[WARNING] {plugin_name} not found")
                        continue
                
                plugin_lower = plugin_name.lower()
                is_blessed = (plugin_name in BASE_GAME_PLUGINS or 
                             plugin_name in AE_CORE_FILES or
                             plugin_lower.startswith(OFFICIAL_CC_PREFIX))
                
                # Detailed blessing tiers
                if is_blessed:
                        if plugin_name in AE_CORE_FILES:
                                print(f"[BLESSED-AE] {plugin_name}")
                        elif plugin_lower.startswith(OFFICIAL_CC_PREFIX):
                                print(f"[BLESSED-CC] {plugin_name}")
                        elif plugin_name in BASE_GAME_PLUGINS:
                                print(f"[BLESSED-BASE] {plugin_name}")
                        else:
                                print(f"[BLESSED] {plugin_name}")
                        blessed_plugins.append(plugin_path)
                else:
                        mod_plugins.append(plugin_path)
                        print(f"[PLUGIN] {plugin_name}")
        
        print(f"\n[FrankenSnoop] Total: {len(loadorder)}, Blessed: {len(blessed_plugins)}, Mods: {len(mod_plugins)}")
        
        # Meta section
        config.add_section('_meta')
        config.set('_meta', 'loadorder_signature', get_loadorder_signature(loadorder))
        config.set('_meta', 'generated_at', str(time.time()))
        config.set('_meta', 'profile', profile_name)
        config.set('_meta', 'is_full_scan', 'true')
        config.set('_meta', 'app_version', CURRENT_APP_VERSION)
        config.set('_meta', 'extraction_logic_version', str(CURRENT_EXTRACTION_LOGIC_VERSION))
        config.set('_meta', 'blessed_count', str(len(blessed_plugins)))
        config.set('_meta', 'plugins_count', str(len(mod_plugins)))

        lo_index_map: Dict[str, int] = {name: idx for idx, name in enumerate(loadorder)}
        
        # Scan blessed - WITH RICH DATA
        for plugin_path in blessed_plugins:
                plugin_name = plugin_path.name
                lo_idx = lo_index_map.get(plugin_name, -1)
                
                print(f"[BLESSED] Scanning {plugin_name} (LO:{lo_idx})...")
                
                dna = quick_sniff(str(plugin_path), plugin_path.parent)
                
                config.add_section(plugin_name)
                config.set(plugin_name, 'hash', hash_file_head(plugin_path))
                config.set(plugin_name, 'mtime', str(os.path.getmtime(plugin_path)))
                config.set(plugin_name, 'size', str(os.path.getsize(plugin_path)))
                config.set(plugin_name, 'author', dna.author)
                config.set(plugin_name, 'signatures', ', '.join(sorted(dna.signatures)))
                config.set(plugin_name, 'object_signatures', ', '.join(sorted(dna.object_signatures)))
                config.set(plugin_name, 'logic_signatures', ', '.join(sorted(dna.logic_signatures)))
                config.set(plugin_name, 'logic_to_content_ratio', str(dna.logic_to_content_ratio))
                config.set(plugin_name, 'folder_scents', ', '.join(sorted(dna.folder_scents)))
                config.set(plugin_name, 'lo_index', str(lo_idx))
                config.set(plugin_name, 'layer', 'hybrid')
                config.set(plugin_name, 'lc_score', '50')
                config.set(plugin_name, 'lc_confidence', 'low')
                config.set(plugin_name, 'masters', ', '.join(dna.masters))
                config.set(plugin_name, 'is_blessed', 'True')
                config.set(plugin_name, 'is_framework', str(dna.is_framework))
                config.set(plugin_name, 'is_partial', str(dna.is_partial))
                config.set(plugin_name, 'framework_reason', dna.framework_reason if dna.is_framework else '')
                
                print(f"    -> {len(dna.signatures)} sigs, {len(dna.folder_scents)} scents, ratio {dna.logic_to_content_ratio:.2f}")

        # Scan mods - WITH RICH DATA
        for plugin_path in mod_plugins:
                plugin_name = plugin_path.name
                lo_idx = lo_index_map.get(plugin_name, -1)
                
                print(f"[PLUGIN] Scanning {plugin_name} (LO:{lo_idx})...")
                
                dna = quick_sniff(str(plugin_path), plugin_path.parent)
                
                config.add_section(plugin_name)
                config.set(plugin_name, 'hash', hash_file_head(plugin_path))
                config.set(plugin_name, 'mtime', str(os.path.getmtime(plugin_path)))
                config.set(plugin_name, 'size', str(os.path.getsize(plugin_path)))
                config.set(plugin_name, 'author', dna.author)
                config.set(plugin_name, 'signatures', ', '.join(sorted(dna.signatures)))
                config.set(plugin_name, 'object_signatures', ', '.join(sorted(dna.object_signatures)))
                config.set(plugin_name, 'logic_signatures', ', '.join(sorted(dna.logic_signatures)))
                config.set(plugin_name, 'logic_to_content_ratio', str(dna.logic_to_content_ratio))
                config.set(plugin_name, 'folder_scents', ', '.join(sorted(dna.folder_scents)))
                config.set(plugin_name, 'lo_index', str(lo_idx))
                config.set(plugin_name, 'layer', 'hybrid')
                config.set(plugin_name, 'lc_score', '50')
                config.set(plugin_name, 'lc_confidence', 'low')
                config.set(plugin_name, 'masters', ', '.join(dna.masters))
                config.set(plugin_name, 'is_blessed', 'False')
                config.set(plugin_name, 'is_framework', str(dna.is_framework))
                config.set(plugin_name, 'is_partial', str(dna.is_partial))
                config.set(plugin_name, 'framework_reason', dna.framework_reason if dna.is_framework else '')
                
                print(f"    -> {len(dna.signatures)} sigs, {len(dna.folder_scents)} scents")
        
        if failed_plugins:
                config.add_section('_errors')
                for name, err in failed_plugins:
                        config.set('_errors', name, err)
                print(f"\n[FrankenSnoop] WARNING: {len(failed_plugins)} plugins failed")
        
        if output_path.is_dir():
                print(f"[FrankenSnoop] ERROR: Output path is a directory")
                return

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
                config.write(f)
        
        print()
        print(f"[FrankenSnoop] Total plugins: {len(loadorder)}")
        print(f"[FrankenSnoop] Blessed plugins: {len(blessed_plugins)}")
        print(f"[FrankenSnoop] Mod plugins: {len(mod_plugins)}")
        if failed_plugins:
                print(f"[FrankenSnoop] Failed: {len(failed_plugins)}")
        print()
        print("[FrankenSnoop] Extraction complete!")

def main():
        parser = argparse.ArgumentParser(description='FrankenSnoop - Build SkyGen manifest')
        parser.add_argument('--source', required=True, help='Path to Skyrim Data directory')
        parser.add_argument('--output', required=True, help='Output INI path')
        parser.add_argument('--profile', default='Default', help='MO2 profile name')
        parser.add_argument('--mods-path', help='Path to MO2 mods directory')
        parser.add_argument('--profile-dir', help='Path to MO2 profile directory')
        args = parser.parse_args()
        
        build_manifest(Path(args.source), Path(args.output), args.profile, 
                       Path(args.profile_dir) if args.profile_dir else None,
                       Path(args.mods_path) if args.mods_path else None)

if __name__ == '__main__':
        main()