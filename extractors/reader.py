import struct
from pathlib import Path
from typing import Iterator, Dict, Any, Optional, List, Tuple
import zlib
from functools import lru_cache
from ..core.constants import GLOBAL_IGNORE_PLUGINS
from PyQt6.QtCore import QThread # type: ignore
HEADER_SIZE = 24
COMPRESSED_FLAG = 0x00040000
MAX_DECOMPRESS = 256 * 1024 * 1024  # Fix #9: 256 MB bomb cap


class PluginReader:
    """Thin wrapper to carry organizer state and cached load-order lookup."""
    def __init__(self, organizer: Any, active_plugins: Optional[List[str]] = None) -> None:
        self.organizer = organizer
        # Use provided list (audit cache) or fall back to text file
        self.active_plugins = active_plugins or []
        # silo owns the truth — no more text file fallback
        self.list_standard, self.list_light = self._split_by_esl(self.active_plugins)

    def _read_loadorder_txt(self) -> List[str]:
        """Fallback: read from text file."""
        profile_path = Path(self.organizer.profile_path())
        plugins_txt = profile_path / "loadorder.txt"
        if not plugins_txt.exists():
            return []
        return [line.strip() for line in plugins_txt.read_text(encoding='utf-8').splitlines() 
                if line.strip() and not line.startswith('#')]

    def _split_by_esl(self, plugins: List[str]) -> Tuple[List[str], List[str]]:
        """Split plugin list by ESL extension."""
        standard, light = [], []
        for name in plugins:
            if name.lower().endswith('.esl'):
                light.append(name)
            else:
                standard.append(name)
        return standard, light

    @lru_cache(maxsize=8192)

    def _resolve_origin_plugin(self, form_id: str) -> str:
        """Resolve FormID hex prefix to plugin name using cached load order."""
        load_order_hex = form_id.split('|')[0]
        load_order_index = int(load_order_hex, 16)
        if load_order_index < len(self.active_plugins):
            return self.active_plugins[load_order_index]
        return "Unknown"
    def resolve_master(self, form_id: str) -> str:
        """Resolve FormID to defining master using 0xFE ESL rule."""
        form_id_clean = form_id.replace('|', '').replace(' ', '').upper()
        prefix = form_id_clean[:2]
        if prefix == "FE":
            sub_index = int(form_id_clean[2:5], 16)
            if sub_index < len(self.list_light):
                return self.list_light[sub_index]
        else:
            index = int(prefix, 16)
            if index < len(self.list_standard):
                return self.list_standard[index]
        return "Unknown"

def iter_records(plugin_path: Path, mod_name: str = "", worker_instance: Optional[Any] = None,
                 lz4_block: Optional[Any] = None,
                 reader: Optional[Any] = None) -> Iterator[Dict[str, Any]]:
    """Yield dict with form_id, signature, editor_id, name, mod_name, offset, origin_plugin."""
    
    # GLOBAL IGNORE SHIELD: Abort immediately for utility mods (SkyUI, RaceMenu, etc.)
    # These never contain patchable records, so we skip all file I/O and decompression
    if plugin_path.name in GLOBAL_IGNORE_PLUGINS:
        print(f"GLOBAL_IGNORE: Dropping {plugin_path.name} (utility mod, no records)")
        return
        # Empty return creates empty iterator - caller gets zero records instantly
    
    with plugin_path.open('rb') as f:
        if reader is None:
            raise RuntimeError("iter_records requires a valid reader instance")
        
        # Skip TES4 header
        header = f.read(HEADER_SIZE)
        if len(header) == HEADER_SIZE and header[0:4] == b'TES4':
            data_size = struct.unpack('<I', header[4:8])[0]
            f.seek(data_size, 1)

        while True:
            if worker_instance and getattr(worker_instance, '_interrupted', False):
                print(f"Reader interrupted: {plugin_path.name}")
                break

            # Yield GIL every 200 records
            record_count = getattr(iter_records, '_counter', 0) + 1
            iter_records._counter = record_count
            if record_count % 200 == 0:
                QThread.msleep(0)
            header_start = f.tell()
            header = f.read(HEADER_SIZE)
            if len(header) < HEADER_SIZE:
                break

            sig_bytes = header[0:4]
            
            # ✅ FOXHUNT_FIX: Strict signature validation (uppercase/digits/space/underscore only)
            valid = True
            for b in sig_bytes:
                # Allow uppercase A-Z (65-90), digits 0-9 (48-57), space (32), underscore (95)
                if not (65 <= b <= 90 or 48 <= b <= 57 or b == 32 or b == 95):
                    valid = False
                    break
            
            if not valid:
                # Resync: skip 4 bytes and retry
                f.seek(header_start + 4)
                continue
            
            sig = sig_bytes.decode('ascii')
            if sig[3] == ' ':
                sig = sig[:3] + '_'
            
            data_size = struct.unpack('<I', header[4:8])[0]
            flags, form_id_raw = struct.unpack('<II', header[8:16])
            form_id_str = f'{form_id_raw:08X}'
            next_record_pos = header_start + 24 + data_size

            if sig == 'GRUP':
                # don't jump over the whole block — skip header and chew children naturally
                continue

            edid = ""
            full = ""
            is_compressed = bool(flags & COMPRESSED_FLAG)
            
            if is_compressed:
                try:
                    payload = f.read(data_size)
                    if len(payload) != data_size:
                        raise ValueError("truncated compressed payload")
                    
                    uncompressed_len = struct.unpack('<I', payload[:4])[0]
                    if uncompressed_len > MAX_DECOMPRESS:
                        f.seek(next_record_pos)
                        continue

                    compressed_data = payload[4:]
                    chunk = None
                    
                    if lz4_block is not None:
                        try:
                            chunk = lz4_block.decompress(compressed_data, uncompressed_len)
                        except Exception:
                            chunk = None
                    
                    if chunk:
                        chunk_left = len(chunk)
                        stream = memoryview(chunk)  # You already have this
                        off = 0
                        while off + 8 <= chunk_left:
                            # FIX 1: Kill the bytes() wrapper
                            sub_sig = stream[off:off+4].decode(errors='ignore')
                            
                            if sub_sig == 'XXXX':
                                # FIX 2: int.from_bytes instead of struct.unpack
                                large_size = int.from_bytes(stream[off+4:off+8], 'little')
                                off += 8
                                # FIX 3: Kill the bytes() wrapper here too
                                sub_sig = stream[off:off+4].decode(errors='ignore')
                                off += 6
                                sub_sz = large_size
                            else:
                                # FIX 4: int.from_bytes instead of struct.unpack
                                sub_sz = int.from_bytes(stream[off+4:off+6], 'little')
                                off += 6
                            
                            if sub_sig == 'EDID':
                                edid = bytes(stream[off:off+sub_sz]).decode(errors='ignore').split('\0')[0].strip()
                            elif sub_sig == 'FULL':
                                full = bytes(stream[off:off+sub_sz]).decode(errors='ignore').split('\0')[0].strip()
                            
                            off += sub_sz
                            if off >= chunk_left:
                                break
                                
                except Exception as e:
                    yield {
                        "form_id": form_id_str, "signature": sig, "editor_id": "DECOMP_ERROR",
                        "name": "DECOMP_ERROR", "mod_name": mod_name, "offset": header_start,
                        "origin_plugin": reader._resolve_origin_plugin(form_id_str),
                        "data_size": data_size, "is_compressed": is_compressed,
                        "master_plugin": reader.resolve_master(form_id_str), "error": str(e)
                    }
                    f.seek(next_record_pos)
                    continue
            else:
                try:
                    record_data = f.read(data_size)
                    if len(record_data) != data_size:
                        raise ValueError("truncated uncompressed data")
                    
                    off = 0
                    chunk_left = data_size
                    while off + 8 <= chunk_left:
                        sub_sig = record_data[off:off+4].decode(errors='ignore')
                        
                        if sub_sig == 'XXXX':
                            large_size = struct.unpack('<I', record_data[off+4:off+8])[0]
                            off += 8
                            sub_sig = record_data[off:off+4].decode(errors='ignore')
                            off += 6
                            sub_sz = large_size
                        else:
                            sub_sz = struct.unpack('<H', record_data[off+4:off+6])[0]
                            off += 6
                        
                        if sub_sig == 'EDID':
                            edid = record_data[off:off+sub_sz].decode(errors='ignore').split('\0')[0].strip()
                        elif sub_sig == 'FULL':
                            full = record_data[off:off+sub_sz].decode(errors='ignore').split('\0')[0].strip()
                        
                        off += sub_sz
                        if off >= chunk_left:
                            break
                            
                except Exception as e:
                    yield {
                        "form_id": form_id_str, "signature": sig, "editor_id": "READ_ERROR",
                        "name": "READ_ERROR", "mod_name": mod_name, "offset": header_start,
                        "origin_plugin": reader._resolve_origin_plugin(form_id_str),
                        "data_size": data_size, "is_compressed": is_compressed,
                        "master_plugin": reader.resolve_master(form_id_str), "error": str(e)
                    }
                    f.seek(next_record_pos)
                    continue

            yield {
                "form_id": form_id_str, "signature": sig, "editor_id": edid or sig,
                "name": full or edid or sig, "mod_name": mod_name, "offset": header_start,
                "origin_plugin": reader._resolve_origin_plugin(form_id_str),
                "data_size": data_size, "is_compressed": is_compressed,
                "master_plugin": reader.resolve_master(form_id_str),
            }
            f.seek(next_record_pos)