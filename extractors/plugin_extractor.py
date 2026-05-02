from __future__ import annotations

import struct
import zlib
import time
from lz4 import frame as lz4_frame
from lz4 import block as lz4_block
import lz4
from pathlib import Path
from typing import Dict, Any, List, Type, Optional, Tuple, Any  # Any added for worker_instance
import os
import sys
import tempfile
import subprocess
import platform          # NEW – for Windows-only hide
from PyQt6.QtCore import QThread # type: ignore

from ..utils.logger import LoggingMixin
from ..core.constants import (MO2_LOG_DEBUG, MO2_LOG_INFO, MO2_LOG_WARNING, MO2_LOG_ERROR, MO2_LOG_CRITICAL, 
DEBUG_MODE, GLOBAL_IGNORE_PLUGINS
)
from ..core.base import FileMetadataExtractor
from ..src.organizer_wrapper import OrganizerWrapper

MAX_RECORD_DATA_SIZE = 20 * 1024 * 1024
EXCLUDED_RECORD_TYPES = {b'CELL', b'LAND', b'WRLD'}
LZ4_EXE_NAME = "lz4.exe"
LZ4_TOOLS_SUBFOLDER = "lz4_tools"

def _make_cache_key(plugin_path: Path) -> str:
    """Generate cache key from file path and modification time."""
    try:
        mtime = plugin_path.stat().st_mtime
        return f"{plugin_path.resolve()}|{mtime}"
    except Exception:
        return f"{plugin_path}|0"

class PluginExtractor(LoggingMixin):
    """
    Extracts metadata and records from Skyrim plugin files (.esm, .esp, .esl).
    Handles compressed records using LZ4. Implements recursive parsing for GRUPs.
    """

    def __init__(self, organizer_wrapper: Optional[OrganizerWrapper] = None, active_plugins: Optional[List[str]] = None):
        super().__init__()
        
        # 🦊 Deduplication – MUST be before any logging
        self._warn_counts: Dict[str, int] = {}
        self._error_counts: Dict[str, int] = {}
        
        # immediate-stop flag
        self._stop_requested = False

        self.organizer_wrapper = organizer_wrapper
        self.active_plugins = active_plugins
        # _fallback_load_order is dead — silo owns the truth now
        self.log_info("PluginExtractor initialized.")

        plugin_root = Path(__file__).parent.parent
        self.lz4_exe_path = plugin_root / LZ4_TOOLS_SUBFOLDER / LZ4_EXE_NAME

        if not self.lz4_exe_path.is_file():
            self.log_warning(f"Could not find '{LZ4_EXE_NAME}' at expected path: '{self.lz4_exe_path}'. External LZ4 decompression will not be available. Please ensure '{LZ4_EXE_NAME}' is placed in the '{LZ4_TOOLS_SUBFOLDER}' subfolder within the plugin's root directory.")
            self.lz4_exe_path = None
        else:
            self.log_info(f"Found LZ4 executable at: {self.lz4_exe_path}. Prioritizing external decompression.")

    # immediate-stop API
    def stop_extraction(self) -> None:
        self._stop_requested = True
        self.log_info("Extractor received immediate stop signal")

    def log_warning(self, msg: str, **kwargs) -> None:
        key = "decompress_fail" if "decompression failed" in msg else msg[:60]
        self._warn_counts[key] = self._warn_counts.get(key, 0) + 1
        if self._warn_counts[key] == 1:
            super().log_warning(msg, **kwargs)

    def log_error(self, msg: str, **kwargs) -> None:
        key = msg[:60]
        self._error_counts[key] = self._error_counts.get(key, 0) + 1
        if self._error_counts[key] == 1:
            super().log_error(msg, **kwargs)

    def _read_le_uint32(self, data: bytes, offset: int) -> int:
        return struct.unpack('<I', data[offset:offset+4])[0]
    
    def _read_le_uint16(self, data: bytes, offset: int) -> int:
        return struct.unpack('<H', data[offset:offset+2])[0]
    
    def _read_le_int32(self, data: bytes, offset: int) -> int:
        return struct.unpack('<i', data[offset:offset+4])[0]

    def _parse_sub_records(self, record_content: bytes) -> Dict[str, Any]:
        """
        Parses sub-records (fields) within a record's content using TLV format.
        Includes more robust error handling and debug logging for sub-records.
        """
        sub_records_data = {}
        current_pos = 0
        parsed_count = 0
        while current_pos + 6 <= len(record_content):
            # 🔥 Stop button can abort during sub-record parsing
            if self._stop_requested:
                self.log_info("Sub-record parsing interrupted by stop signal.")
                break
            
            # Yield GIL every 100 sub-records
            parsed_count += 1
            if parsed_count % 100 == 0:
                from PyQt6.QtCore import QThread # type: ignore
                QThread.msleep(0)

            sub_tag = record_content[current_pos:current_pos+4]

            # XXXX = next subrecord carries a 32-bit length instead of 16-bit
            if sub_tag == b'XXXX':
                if current_pos + 8 > len(record_content):
                    break
                sub_length = self._read_le_uint32(record_content, current_pos + 4)
                current_pos += 8
                if current_pos + 4 > len(record_content):
                    break
                sub_tag = record_content[current_pos:current_pos+4]
                current_pos += 6  # skip tag + dummy 2-byte length field
            else:
                sub_length = self._read_le_uint16(record_content, current_pos + 4)
                current_pos += 6

            if sub_length < 0 or current_pos + sub_length > len(record_content):
                self.log_warning(f"  Invalid sub-record length for {sub_tag.decode(errors='ignore')} (length {sub_length}) at offset {current_pos}. Content length: {len(record_content)}. Skipping remaining sub-records for this record.")
                break

            sub_value = record_content[current_pos : current_pos + sub_length]
            current_pos += sub_length
            
            # actually keep the data instead of parsing into the void
            tag_str = sub_tag.decode('ascii', errors='ignore')
            if tag_str == 'ATXT':
                # textures can show up multiple times — don't stomp
                sub_records_data.setdefault('ATXT', []).append(sub_value)
            elif tag_str in {'EDID', 'FULL', 'MODL', 'MOD2', 'MOD3', 'MOD4',
                             'ICON', 'MICO', 'DESC', 'CNAM', 'SNAM', 'INAM'}:
                # text fields — decode now so downstream doesn't choke on bytes
                sub_records_data[tag_str] = sub_value.decode('ascii', errors='ignore').split('\0')[0].strip()
            else:
                # binary fields — DNAM, BODT, RNAM, KWDA, SPIT, etc.
                sub_records_data[tag_str] = sub_value
                
        return sub_records_data

    def _parse_record(self, f: Any, record_start_offset: int, record_signature: bytes, record_data_size: int, 
                      record_flags: int, form_id_raw: int, vc_info: int, form_version: int, unknown_field: int,
                      record_types_bytes: Optional[set[bytes]],
                      worker_instance: Any = None) -> Optional[Dict[str, Any]]:
        """
        Parses a single data record and its sub-records.
        Prioritizes external LZ4.exe for decompression if available.
        Returns the parsed record data or None if skipped by filter.
        """
        # 🔥 Debug filter mismatch
        # Throttled: only log every 500th record
        self._rec_counter = getattr(self, '_rec_counter', 0) + 1
        if self._rec_counter % 500 == 0:
            self.log_debug(f"Processing milestone: {self._rec_counter} records")

        record_expected_end_in_file = record_start_offset + 24 + record_data_size

        if record_data_size > MAX_RECORD_DATA_SIZE or record_data_size < 0:
            self.log_error(f"  Sanity check failed for {record_signature.decode(errors='ignore')} (FormID: {form_id_raw:08X}) at {record_start_offset}. Claimed DataSize ({record_data_size} bytes) is suspiciously large or negative. Skipping record.")
            f.seek(record_expected_end_in_file)
            return None

        is_compressed = bool(record_flags & 0x00040000)

        record_content_bytes = f.read(record_data_size)
        if len(record_content_bytes) < record_data_size:
            self.log_error(f"Failed to read full record data for {record_signature.decode(errors='ignore')} (FormID: {form_id_raw:08X}) at {record_start_offset}. Expected {record_data_size} bytes, got {len(record_content_bytes)}. File might be truncated. Skipping record.")
            f.seek(record_expected_end_in_file)
            return None

        # 🔥 Early exit if worker asked to stop (rate-limited)
        if worker_instance and getattr(worker_instance, '_interrupted', False):
            # Only log every 100ms to avoid spam
            now = time.time_ns() // 1_000_000
            if now - getattr(self, '_last_interrupt_log', 0) > 100:
                self.log_info("Extraction interrupted inside _parse_record.")
                self._last_interrupt_log = now
            f.seek(record_expected_end_in_file)
            return None

        if is_compressed:
            uncompressed_size = self._read_le_uint32(record_content_bytes, 0)
            compressed_payload = record_content_bytes[4:]
            
            # 🔥 Stop signal check
            if worker_instance and getattr(worker_instance, '_interrupted', False):
                self.log_info("Skipping decompression – stop requested.")
                f.seek(record_expected_end_in_file)
                return None
            
            decompressed_data = None

            # Tier 1: lz4.block (fastest for modern records)
            try:
                decompressed_data = lz4_block.decompress(compressed_payload, uncompressed_size)
            except Exception:
                # Tier 2: external lz4.exe (backup for edge cases)
                if self.lz4_exe_path and self.lz4_exe_path.is_file():
                    try:
                        decompressed_data = self._decompress_external_lz4(record_content_bytes)
                    except Exception:
                        decompressed_data = None
                
                # 🦊 Tier 3: zlib for LE legacy compression (NPCs, etc.)
                if decompressed_data is None:
                    try:
                        decompressed_data = zlib.decompress(compressed_payload)
                        if len(decompressed_data) != uncompressed_size:
                            self.log_warning(f"Zlib size mismatch: expected {uncompressed_size}, got {len(decompressed_data)}")
                            decompressed_data = None
                    except Exception:
                        decompressed_data = None

            # Deduplicate failure warnings (keeps log quiet)
            if decompressed_data is None:
                key = f"decomp_fail_{record_signature}_{form_id_raw:08X}"
                self._warn_counts[key] = self._warn_counts.get(key, 0) + 1
                if self._warn_counts[key] == 1:
                    self.log_warning(f"Decompression failed for {record_signature.decode(errors='ignore')} (FormID: {form_id_raw:08X}) – skipping record")
                f.seek(record_expected_end_in_file)
                return None

            if len(decompressed_data) != uncompressed_size:
                self.log_warning(f"Size mismatch: expected {uncompressed_size}, got {len(decompressed_data)}")
            record_content = decompressed_data
        else:
            record_content = record_content_bytes

        parsed_sub_records = self._parse_sub_records(record_content)

        # Determine origin plugin from FormID load order index
        load_order_index = (form_id_raw >> 24) & 0xFF
        origin_index = load_order_index
        
        # Use provided active_plugins list if available, else fall back
        if self.active_plugins and load_order_index < len(self.active_plugins):
            origin_plugin = self.active_plugins[load_order_index]
            master_plugin = origin_plugin 
        
        else:
            # silo didn't cover this index — loud and honest, no text file sniffing
            origin_plugin = "Unknown"
            master_plugin = "Unknown"

        # Extract visual fields for bulk filter mode
        model = parsed_sub_records.get('MODL', '')
        inventory_art = parsed_sub_records.get('INAM', '')  # Verify this field name
        textures = ','.join(parsed_sub_records.get('ATXT', []))  # Now safe – list of strings

        record_data = {
            "signature": record_signature.decode('utf-8', errors='ignore'),
            "form_id": f"{form_id_raw:08X}",
            "flags": record_flags,
            "data_size": record_data_size,
            "is_compressed": is_compressed,
            "version_control_info": vc_info, 
            "form_version": form_version,     
            "unknown_field": unknown_field,         
            "content_raw": record_content,
            "origin_plugin": origin_plugin,  
            "origin_plugin_index": origin_index,
            "master_plugin": master_plugin,
            "model": model,                   
            "inventory_art": inventory_art,   
            "alternate_textures": textures,   
            **parsed_sub_records
        }
        
        # Always return record (no filter)
        return record_data

    def _try_python_lz4_decompression(self, compressed_payload: bytes, uncompressed_size: int, record_signature: bytes, form_id_raw: int) -> Optional[bytes]:
        """
        Helper method to attempt decompression using python-lz4 libraries.
        """
        decompressed_data = None
        try:
            decompressed_data = lz4_frame.decompress(compressed_payload)
            self.log_debug(f"  Python LZ4 frame decompressed {len(compressed_payload)} bytes to {len(decompressed_data)} (expected {uncompressed_size}).")
            if len(decompressed_data) != uncompressed_size:
                self.log_warning(f"  Python LZ4 frame size mismatch for {record_signature.decode(errors='ignore')} (FormID: {form_id_raw:08X}). Expected {uncompressed_size}, got {len(decompressed_data)}. Proceeding.")
            
        except Exception as lz4_frame_e: 
            self.log_debug(f"  Python LZ4 frame failed for {record_signature.decode(errors='ignore')} (FormID: {form_id_raw:08X}): {type(lz4_frame_e).__name__}. Trying Python LZ4 block.")
            
            try:
                decompressed_data = lz4_block.decompress(compressed_payload, uncompressed_size) 
                self.log_debug(f"  Python LZ4 block decompressed {len(compressed_payload)} bytes to {len(decompressed_data)} (expected {uncompressed_size}).")
                
                if decompressed_data and len(decompressed_data) != uncompressed_size: 
                    self.log_warning(f"  Python LZ4 block size mismatch for {record_signature.decode('utf-8', errors='ignore')} (FormID: {form_id_raw:08X}). Expected {uncompressed_size}, got {len(decompressed_data)}. Proceeding.")

            except Exception as lz4_block_e: 
                self.log_warning(f"  Python LZ4 block decompression failed for {record_signature.decode(errors='ignore')} (FormID: {form_id_raw:08X}): {type(lz4_block_e).__name__}. Cannot decompress with Python LZ4.")
                return None

        return decompressed_data

    def _decompress_external_lz4(self, record_content_bytes: bytes) -> Optional[bytes]:
        """
        External LZ4.exe decompression helper used for NPC records.
        Returns decompressed bytes or None on failure.
        """
        uncompressed_size = self._read_le_uint32(record_content_bytes, 0)
        compressed_payload = record_content_bytes[4:]
        try:
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(compressed_payload)
                tmp_path = Path(tmp.name)

            if platform.system() == "Windows":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            else:
                startupinfo = None

            result = subprocess.run(
                [self.lz4_exe_path, "-d", str(tmp_path)],
                capture_output=True,
                check=True,
                startupinfo=startupinfo,
                timeout=10
            )
            return result.stdout
        except Exception:
            return None
        finally:
            tmp_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    #  Surgical extraction – NEW METHOD
    # ------------------------------------------------------------------
    def extract_at_offset(
        self,
        plugin_path: Path,
        offset: int,
        worker_instance: Optional[Any] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Surgical extraction: Seek to offset, read 24-byte header,
        decompress if needed, parse subrecords, return record dict.
        """
        offset = int(offset)
        
        # GLOBAL IGNORE SHIELD: Block surgical extraction on utility mods
        # Prevents accidental record pulls from SkyUI/RaceMenu even if offset is known
        if plugin_path.name in GLOBAL_IGNORE_PLUGINS:
            self.log_debug(f"GLOBAL_IGNORE: Blocking surgical extraction for {plugin_path.name}")
            return None
        
        try:
            with plugin_path.open('rb') as f:
                f.seek(offset)
                header = f.read(24)
                if len(header) < 24:
                    return None

                sig_bytes = header[0:4]
                sig = sig_bytes.decode('utf-8', errors='ignore')
                if sig == 'NPC ':
                    sig = 'NPC_'

                data_size = struct.unpack('<I', header[4:8])[0]
                flags = struct.unpack('<I', header[8:12])[0]
                form_id_raw = struct.unpack('<I', header[12:16])[0]
                vc_info = struct.unpack('<I', header[16:20])[0]
                form_version = struct.unpack('<H', header[20:22])[0]
                unknown_field = struct.unpack('<H', header[22:24])[0]

                if sig not in {'NPC_', 'ARMO', 'WEAP', 'AMMO', 'BOOK', 'ALCH',
                               'HAIR', 'HDPT', 'CONT', 'LIGH', 'MISC', 'KEYM',
                               'FURN', 'SPEL', 'FLST', 'LVLI', 'LVLC', 'INGR',
                               'SLGM', 'SCRL', 'RACE'}:
                    return None

                return self._parse_record(
                    f, offset, sig_bytes, data_size, flags, form_id_raw,
                    vc_info, form_version, unknown_field,
                    record_types_bytes={sig_bytes},
                    worker_instance=worker_instance
                )
        except Exception as e:
            self.log_warning(f"extract_at_offset failed at {offset}: {e}")
            return None


    # ------------------------------------------------------------------
    #  Fox-Cut repaired signature – parameter order restored
    # ------------------------------------------------------------------
    def _parse_group(self, f: Any, group_start_offset: int, group_signature: bytes, group_size: int, 
                     group_label_raw: bytes, group_type: int, parent_or_version: int, timestamp_or_flags: int,
                     record_types_bytes: Optional[set[bytes]],    # 🪜  FIXED – present and in correct position
                     worker_instance: Optional[Any] = None) -> Dict[str, Any]:
        """
        Recursively parses a GRUP record and its children (records or nested GRUPs).
        Returns the parsed GRUP data including its children.
        """
        # 🔥 Debug inserts requested
        # Throttled GRUP logging
        self._grup_counter = getattr(self, '_grup_counter', 0) + 1
        if self._grup_counter % 100 == 0:
            self.log_debug(f"GRUP milestone #{self._grup_counter}: {group_label_raw}")
        #self.log_debug(f"Starting record scan at offset {group_start_offset}")

        group_end_offset = group_start_offset + group_size

        group_children = []

        while f.tell() < group_end_offset:
            # 🔥 Quick interruption check each iteration
            if worker_instance and getattr(worker_instance, '_interrupted', False):
                self.log_info("GRUP parsing interrupted.")
                break

            child_start_offset = f.tell()
            
            if child_start_offset + 24 > group_end_offset:
                self.log_warning(f"  Not enough bytes for full child header in GRUP {group_label_raw.decode(errors='ignore')} at {child_start_offset}. Remaining bytes: {group_end_offset - child_start_offset}. Breaking group parsing.")
                f.seek(group_end_offset)
                break

            child_header_bytes = f.read(24)
            if len(child_header_bytes) < 24:
                self.log_warning(f"  Truncated child header in GRUP {group_label_raw.decode(errors='ignore')} at {child_start_offset}. Breaking group parsing.")
                f.seek(group_end_offset)
                break

            child_signature = child_header_bytes[0:4]
            # Normalize Bethesda signatures: NPC␣ → NPC_
            if child_signature == b'NPC ':
                child_signature = b'NPC_'
            child_data_size = self._read_le_uint32(child_header_bytes, 4)
            
            child_remaining_header_bytes = child_header_bytes[8:24]

            # Calculate correct child total size
            child_total_size = child_data_size if child_signature == b'GRUP' else (24 + child_data_size)
            if child_start_offset + child_total_size > group_end_offset:
                self.log_warning(f"  Child {child_signature.decode(errors='ignore')} (size {child_data_size}) at {child_start_offset} extends beyond parent GRUP {group_label_raw.decode(errors='ignore')}'s boundary ({group_end_offset}). Skipping this child.")
                f.seek(group_end_offset)
                break

            # 🔥 Debug: inside loop, after reading record header
            #self.log_debug(f"Record signature: {child_signature} at offset {child_start_offset}")

            if child_signature == b'GRUP':
                child_label_raw = child_remaining_header_bytes[0:4]
                child_type = self._read_le_uint32(child_remaining_header_bytes, 4)
                child_parent_or_version = self._read_le_uint32(child_remaining_header_bytes, 8)
                child_timestamp_or_flags = self._read_le_uint32(child_remaining_header_bytes, 12)

                try:
                    # 🪜  FIXED – parameters now match the corrected signature
                    parsed_child_group = self._parse_group(
                        f, child_start_offset, child_signature, child_data_size, 
                        child_label_raw, child_type, child_parent_or_version, child_timestamp_or_flags,
                        record_types_bytes, worker_instance
                    )
                    group_children.append(parsed_child_group)
                except Exception as e:
                    self.log_error(f"Error parsing nested GRUP {child_signature.decode(errors='ignore')} at {child_start_offset}: {type(e).__name__}: {e}. Attempting to skip.", exc_info=True)
                    f.seek(child_start_offset + 24 + child_data_size)

            else:
                child_flags = self._read_le_uint32(child_remaining_header_bytes, 0)
                child_form_id_raw = self._read_le_uint32(child_remaining_header_bytes, 4)
                child_vc_info = self._read_le_uint32(child_remaining_header_bytes, 8)
                child_form_version = self._read_le_uint16(child_remaining_header_bytes, 12)
                child_unknown = self._read_le_uint16(child_remaining_header_bytes, 14)
                # Skip excluded types (CELL/LAND/WRLD) regardless of filter
                if child_signature in EXCLUDED_RECORD_TYPES:
                    f.seek(child_start_offset + 24 + child_data_size)
                    continue
                # Parse all records when no filter, otherwise only matching signatures
                should_parse = record_types_bytes is None or child_signature in record_types_bytes
                if should_parse:
                    #self.log_debug(f"✓ Signature MATCH - parsing: {child_signature}")
                    try:
                        parsed_child_record = self._parse_record(
                            f, child_start_offset, child_signature, child_data_size,
                            child_flags, child_form_id_raw, child_vc_info, child_form_version, child_unknown,
                            record_types_bytes, worker_instance
                        )
                        if parsed_child_record:
                            group_children.append(parsed_child_record)
                    except Exception as e:
                        self.log_error(f"Error parsing child record {child_signature.decode(errors='ignore')} at {child_start_offset}: {type(e).__name__}: {e}. Attempting to skip.", exc_info=True)
                        f.seek(child_start_offset + 24 + child_data_size)
                else:
                    #self.log_debug(f"✗ Signature SKIP - {child_signature} not in {record_types_bytes}")
                    f.seek(child_start_offset + 24 + child_data_size)
            
            # Check interruption after each child
            if worker_instance and getattr(worker_instance, '_interrupted', False):
                self.log_info("GRUP child processing interrupted.")
                break
            
            # 🦊 Correct end-of-child calculation
            if child_signature == b'GRUP':
                expected_child_end = child_start_offset + child_data_size
            else:
                expected_child_end = child_start_offset + 24 + child_data_size

            if f.tell() != expected_child_end:
                self.log_warning(f"  File pointer mismatch after parsing child {child_signature.decode(errors='ignore')} (start: {child_start_offset}). Expected {expected_child_end}, actual {f.tell()}. Seeking to expected position.")
                f.seek(expected_child_end)

        if f.tell() != group_end_offset:
            self.log_warning(f"  File pointer mismatch at end of GRUP {group_label_raw.decode(errors='ignore')} (start: {group_start_offset}). Expected {group_end_offset}, actual {f.tell()}. Seeking to expected end.")
            f.seek(group_end_offset)

        return {
            "signature": group_signature.decode('utf-8', errors='ignore'),
            "size": group_size,
            "label": group_label_raw.decode('utf-8', errors='ignore').strip('\x00'),
            "type": group_type,
            "parent_or_version": parent_or_version,
            "timestamp_or_flags": timestamp_or_flags,
            "start_offset": group_start_offset,
            "end_offset": group_end_offset,
            "is_grup": True,
            "children": group_children
        }


    def extract_metadata(self, file_path: Path,
                         worker_instance: Optional[Any] = None,
                         record_types_bytes: Optional[set[bytes]] = None,
                         cache_manager: Optional[Any] = None) -> Dict[str, Any]:
        """
        Extracts records and metadata from a Skyrim plugin file.
        This is the main entry point for recursive parsing.
        """
        self.log_info(f"Extracting records from file: {file_path}")
        
        # GLOBAL IGNORE SHIELD: Utility mods get empty result, zero disk hit
        # SkyUI, RaceMenu, etc. never contain patchable records for SP or BOS
        if file_path.name in GLOBAL_IGNORE_PLUGINS:
            self.log_info(f"GLOBAL_IGNORE: Dropping {file_path.name} (utility mod)")
            return {
                "file_path": str(file_path),
                "file_name": file_path.name,
                "records": [],
                "ignored": True  # Flag for upstream to know this was filtered
            }
        
        extracted_data = {
            "file_path": str(file_path),
            "file_name": file_path.name,
            "records": []
        }
        
        # Check cache first
        if cache_manager:
            cache_key = _make_cache_key(file_path)
            cached = cache_manager.load_from_cache(cache_key)
            if cached and isinstance(cached, dict) and "records" in cached:
                self.log_info(f"Cache HIT for {file_path.name}")
                return cached
            self.log_debug(f"Cache MISS for {file_path.name} – extracting from disk")        
        total_blocks_processed = 0

        try: 
            with open(file_path, 'rb') as f:
                file_size = os.fstat(f.fileno()).st_size
                self.log_debug(f"File size: {file_size} bytes")

                tes4_header_start_offset = f.tell()
                tes4_header_bytes = f.read(24)
                if len(tes4_header_bytes) < 24:
                    self.log_error(f"Failed to read full 24-byte TES4 header from {file_path}. File might be truncated or corrupt.")
                    return extracted_data

                try:
                    (signature, data_size, flags, form_id_raw, version_float, num_records) = \
                        struct.unpack('<4sIIIfI', tes4_header_bytes)
                    
                    form_id = f"{form_id_raw:08X}"
                except struct.error as e:
                    self.log_critical(f"Error unpacking TES4 header for {file_path}: {e}", exc_info=True)
                    return extracted_data

                if signature != b'TES4':
                    self.log_error(f"File {file_path} does not start with TES4 signature. Found: {signature.decode(errors='ignore')}")
                    return extracted_data

                tes4_record_data = f.read(data_size)
                if len(tes4_record_data) < data_size:
                    self.log_error(f"Failed to read full TES4 record data ({data_size} bytes) from {file_path}. File might be truncated.")
                    return extracted_data

                tes4_sub_records = self._parse_sub_records(tes4_record_data)
                masters = tes4_sub_records.get('MAST', [])
                author = tes4_sub_records.get('SNAM', '')
                description = tes4_sub_records.get('CNAM', '')

                extracted_data["header"] = {
                    "signature": signature.decode('utf-8', errors='ignore'),
                    "data_size": data_size,
                    "flags": flags,
                    "form_id": form_id,
                    "version_float": version_float,
                    "num_records": num_records,
                    "masters": masters,
                    "author": author,
                    "description": description,
                    "sub_records": tes4_sub_records
                }
                self.log_debug(f"TES4 Header Parsed: {extracted_data['header']}")
                
                self.log_info(f"Starting main record/GRUP parsing from file: {file_path.name}. File size: {file_size} bytes.")

                while f.tell() < file_size:
                    current_header_start_offset = f.tell()
                    
                    # Yield GIL every 50 blocks (was 100 with 1ms sleep)
                    if total_blocks_processed % 50 == 0:
                        QThread.msleep(0)  # Zero-cost yield
                    
                    if current_header_start_offset + 24 > file_size:
                        self.log_debug(f"Not enough bytes for full top-level header at {current_header_start_offset}. Breaking main parsing loop.")
                        break

                    header_bytes = f.read(24)
                    if len(header_bytes) < 24:
                        self.log_debug(f"Reached end of file or truncated top-level header at {current_header_start_offset}. Breaking main parsing loop.")
                        break
                    
                    current_signature = header_bytes[0:4]
                    # Normalize Bethesda signatures: NPC␣ → NPC_
                    if current_signature == b'NPC ':
                        current_signature = b'NPC_'
                    current_data_size = self._read_le_uint32(header_bytes, 4)
                    # Throttle block spam
                    self._block_counter = getattr(self, '_block_counter', 0) + 1
                    if self._block_counter % 500 == 0:
                        self.log_debug(f"Block milestone #{self._block_counter} at offset {current_header_start_offset}")
                    remaining_header_bytes = header_bytes[8:24]

                    # THEN calculate boundary
                    if current_signature == b'GRUP':
                        expected_end = current_header_start_offset + current_data_size
                    else:
                        expected_end = current_header_start_offset + 24 + current_data_size

                    if expected_end > file_size:
                        self.log_warning(f"Block {current_signature.decode(errors='ignore')} extends beyond file boundary. Skipping.")
                        break

                    if current_signature == b'GRUP':
                        # Parse GRUPs always
                        try:
                            g_label_raw = remaining_header_bytes[0:4]
                            g_type = self._read_le_uint32(remaining_header_bytes, 4)
                            g_parent_or_version = self._read_le_uint32(remaining_header_bytes, 8)
                            g_timestamp_or_flags = self._read_le_uint32(remaining_header_bytes, 12)

                            parsed_grup = self._parse_group(
                                f, current_header_start_offset, current_signature, current_data_size, 
                                g_label_raw, g_type, g_parent_or_version, g_timestamp_or_flags,
                                record_types_bytes, worker_instance
                            )
                            extracted_data["records"].append(parsed_grup)
                        except Exception as e:
                            self.log_error(f"Error parsing GRUP at {current_header_start_offset}: {type(e).__name__}: {e}. Skipping to next block.", exc_info=True)
                            f.seek(current_header_start_offset + 24 + current_data_size)
                            continue
                    else:
                        # Skip excluded types (CELL/LAND/WRLD) regardless of filter
                        if current_signature in EXCLUDED_RECORD_TYPES:
                            f.seek(current_header_start_offset + 24 + current_data_size)
                            continue
                        # Only filter individual records, always parse GRUPs
                        try:
                            r_flags = self._read_le_uint32(remaining_header_bytes, 0)
                            r_form_id_raw = self._read_le_uint32(remaining_header_bytes, 4)
                            r_vc_info = self._read_le_uint32(remaining_header_bytes, 8)
                            r_form_version = self._read_le_uint16(remaining_header_bytes, 12)
                            r_unknown = self._read_le_uint16(remaining_header_bytes, 14)

                            parsed_record = self._parse_record(
                                f, current_header_start_offset, current_signature, current_data_size,
                                r_flags, r_form_id_raw, r_vc_info, r_form_version, r_unknown,
                                record_types_bytes, worker_instance
                            )
                            if parsed_record:
                                extracted_data["records"].append(parsed_record)
                        except Exception as e:
                            self.log_error(f"Error parsing record {current_signature.decode(errors='ignore')} at {current_header_start_offset}: {type(e).__name__}: {e}. Skipping to next block.", exc_info=True)
                            f.seek(current_header_start_offset + 24 + current_data_size)
                            continue

                self.log_info(f"Finished extracting records from {file_path}. Processed {total_blocks_processed} top-level blocks (GRUPs and records).")

            # Cache save ONLY happens after successful extraction
            if cache_manager and extracted_data["records"]:
                cache_key = _make_cache_key(file_path)
                cache_manager.save_to_cache(cache_key, extracted_data)
                self.log_info(f"Cache SAVED for {file_path.name} ({len(extracted_data['records'])} records)")

        except FileNotFoundError:
            self.log_error(f"File not found: {file_path}")
            
        return extracted_data  # Single return at end for all paths
    ################################################################################
    def extract_data_from_plugins(
        self,
        plugin_names: List[str],
        game_version: str,
        progress_callback: Any = None,
        worker_instance: Optional[Any] = None,
        record_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        self.log_debug(f"PluginExtractor called with {len(plugin_names)} plugins, game_version={game_version}")
        aggregated: Dict[str, Dict[str, Any]] = {}
        if not self.organizer_wrapper:
            self.log_critical("OrganizerWrapper not initialised – cannot resolve plugin paths.")
            return {}

        # Convert string list to bytes set for low-level filtering
        record_types_bytes = {rt if isinstance(rt, bytes) else rt.encode('utf-8') for rt in record_types} if record_types else None


        # 🦊 MOVE flatten here - method level, not inside loop
        def _flatten(records, plugin_name):
            flat = {}
            for rec in records:
                if rec.get("is_grup"):
                    # self.log_debug(f"GRUP: {rec.get('label')} has {len(rec.get('children', []))} children")
                    flat.update(_flatten(rec.get("children", []), plugin_name))
                else:
                    fid = rec.get("form_id")
                    if fid:
                        flat[fid] = {"file_name": plugin_name, **rec}
            return flat

        total = len(plugin_names)
        for idx, name in enumerate(plugin_names, 1):
            # 🔥 CHECK INTERRUPTION BETWEEN PLUGINS
            if worker_instance and getattr(worker_instance, '_interrupted', False):
                self.log_info("Plugin extraction interrupted between files.")
                return {"baseObjects": list(aggregated.values())}

            if progress_callback:
                progress_callback(idx, total, f"Extracting: {name}")
            path = self.organizer_wrapper.get_plugin_path(name)
            if not path:
                self.log_warning(f"Could not resolve path for plugin '{name}' – skipping.")
                continue
            try:
                data = self.extract_metadata(path, worker_instance=worker_instance, 
                                           record_types_bytes=record_types_bytes, 
                                           cache_manager=getattr(worker_instance, 'cache_manager', None))
                aggregated.update(_flatten(data.get("records", []), name))
            except Exception as e:
                self.log_error(f"Error during extraction of '{name}': {e}", exc_info=True)
                continue

        self.log_info(f"Finished aggregating records. Total unique records (last mod wins): {len(aggregated)}")
        
        # 🦊 Emit summary
        total_warnings = sum(c for c in self._warn_counts.values() if c > 1)
        total_errors   = sum(c for c in self._error_counts.values() if c > 1)
        if total_warnings or total_errors:
            self.log_info("=== Log Summary ===")
            if total_warnings:
                self.log_info(f"Suppressed {total_warnings} duplicate warnings")
            if total_errors:
                self.log_info(f"Suppressed {total_errors} duplicate errors")
            self._warn_counts.clear()
            self._error_counts.clear()
        
        return {"baseObjects": list(aggregated.values())}