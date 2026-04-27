"""
SkyGen Logging Utilities Module

This module provides centralized logging functionality for the SkyGen plugin.
It now uses direct file I/O for its custom log file, mirroring the robust
behavior observed in previous working versions, and falls back to console
printing for immediate MO2 console feedback.
"""
import hashlib  # For spam detection fingerprinting
from pathlib import Path
from typing import Optional, Callable, Any, TextIO, Dict, List
import time
import threading # For potential future thread safety improvements
import re  # For potential future log message parsing
import os
import sys # For direct console printing
from datetime import datetime # For timestamps in logs
import traceback # REQUIRED: Import traceback module for format_exc()

# Import MO2 log levels from the central constants module
# Assuming skygen_constants.py exists and defines these
from ..core.constants import (
    MO2_LOG_CRITICAL, MO2_LOG_ERROR, MO2_LOG_WARNING, MO2_LOG_INFO,
    MO2_LOG_DEBUG, MO2_LOG_TRACE, PLUGIN_LOGGER_NAME, DEBUG_MODE # Import DEBUG_MODE from constants
)


class SkyGenLogger:
    """
    Centralized logging handler for the SkyGen plugin, using direct file I/O.
    
    This class manages a custom log file and provides fallback console printing.
    It implements the log levels as defined by MO2 for consistency.
    """
    
    _instance: Optional['SkyGenLogger'] = None # Singleton instance
    _logging_configured = False
    _debug_mode = DEBUG_MODE # Initialize from constants.DEBUG_MODE
    _debug_mode = DEBUG_MODE  # Initialize from constants.DEBUG_MODE
    _spam_cache: dict[str, tuple[int, float]] = {}  # Class-level safety net

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize_logger()
        return cls._instance

    def _initialize_logger(self):
        """Surgical: Initialize spam guard BEFORE any potential logging calls."""
        # Ensure instance cache exists (belt and suspenders for singleton)
        if not hasattr(self, '_spam_cache') or self._spam_cache is None:
            self._spam_cache: dict[str, tuple[int, float]] = {}
        # Forensic deduplication for WARNING/ERROR/CRITICAL
        self._error_buffer: Dict[str, List[Any]] = {}
        self._error_lock = threading.Lock()
        
        if SkyGenLogger._logging_configured:
            return
            
        try:
            # Determine log directory (assuming it's in the same parent as this file)
            plugin_root_dir = Path(__file__).parent.parent
            self.log_dir = plugin_root_dir / "logs"
            self.log_file_path = self.log_dir / "SkyGen_Debug.txt" # Use fixed name here

            # Ensure the logs directory exists before attempting to open the file
            self.log_dir.mkdir(parents=True, exist_ok=True)
            
            # Open the log file in write mode (this will overwrite the file if it exists)
            self.log_file_handle = open(self.log_file_path, 'w', encoding='utf-8')
            self._log_to_file(f"\n--- {PLUGIN_LOGGER_NAME} Session Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            self._log_to_console(f"[{PLUGIN_LOGGER_NAME}] INFO: SkyGenLogger initialized for '{PLUGIN_LOGGER_NAME}'. Log file: {self.log_file_path}")
            
            # Set initial debug mode based on constant
            self.set_debug_mode(DEBUG_MODE) # This will call the new set_debug_mode method

            # Spam guard: track message frequency to prevent log explosions
            self._spam_cache: dict[str, tuple[int, float]] = {}  # msg_hash: (count, first_seen)
            
        except Exception as e:
            self._log_to_console(f"[{PLUGIN_LOGGER_NAME}] CRITICAL ERROR: Failed to initialize logger: {e}")
            traceback.print_exc(file=sys.stderr) # Print traceback to console if logger init fails
            sys.stderr.flush()
 
    def _is_spam(self, msg: str) -> bool:
        """Rate-limit identical messages to prevent memory explosions."""
        import time
        
        # Fast path: empty messages or very short ones bypass spam check
        if len(msg) < 10:
            return False
            
        msg_hash = hashlib.md5(msg.encode()).hexdigest()[:16]
        now = time.time()
        count, first_seen = self._spam_cache.get(msg_hash, (0, now))
        
        # Reset window after 1 second
        if now - first_seen > 1.0:
            self._spam_cache[msg_hash] = (1, now)
            return False
            
        # Silence after 5 identical messages within window
        if count >= 5:
            return True
            
        self._spam_cache[msg_hash] = (count + 1, first_seen)
        return False

    def _normalize_for_dedup(self, message: str) -> str:
        """
        Strip variable bits so errors differing only by FormID/path count as one signature.
        Keeps the message skeleton for grouping.
        """
        text = message
        # Plugin filenames (.esp, .esm, .esl, .bsa, etc)
        text = re.sub(r'\S+\.(esp|esm|esl|bsa|ba2)\b', '[PLUGIN]', text, flags=re.IGNORECASE)
        # 8-char hex FormIDs (common in Skyrim: 000123AB)
        text = re.sub(r'\b[0-9a-fA-F]{8}\b', '[FORMID]', text)
        # 0x prefixed hex
        text = re.sub(r'0x[0-9a-fA-F]+', '[HEX]', text)
        # Windows absolute paths (crude but effective)
        text = re.sub(r'[a-zA-Z]:\\[^\s:]+', '[PATH]', text)
        # Large numbers (4+ digits) – usually offsets, counts, timestamps
        text = re.sub(r'\b\d{4,}\b', '[NUM]', text)
        return text

    def _log_significant_event(self, level: int, message: str, exc_info: bool, module_name: str):
        """
        WARNING/ERROR/CRITICAL handler with deduplication.
        First occurrence hits file immediately (forensics); repeats are tallied silently.
        """
        norm_key = f"{module_name}|{self._normalize_for_dedup(message)}"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with self._error_lock:
            if norm_key in self._error_buffer:
                self._error_buffer[norm_key][0] += 1
                # Suppress entirely – no console spam, no file bloat
                return
            
            # First hit – capture everything
            self._error_buffer[norm_key] = [1, message, level, module_name, timestamp]
            
            level_name = self._get_level_name(level)
            entry = f"[{timestamp}] [Level {level_name}] [{module_name}] [FIRST_HIT] {message}"
            
            if self.log_file_handle:
                self._log_to_file(entry)
                if exc_info:
                    self._log_to_file(traceback.format_exc())
                # Nuclear fsync so crashes don't eat the evidence
                self.flush()
            
            # Console fallback for live debugging
            self._log_to_console(entry, is_error=(level >= MO2_LOG_ERROR))

    def finalize_error_summary(self):
        """
        Call at end of generation (success or fail) to write repeat tallies.
        Clears buffer for next run.
        """
        with self._error_lock:
            if not self._error_buffer:
                return
                
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            lines = [f"[{timestamp}] === ERROR DEDUPLICATION SUMMARY ==="]
            
            repeaters = [(k, v) for k, v in self._error_buffer.items() if v[0] > 1]
            if repeaters:
                lines.append(f"Repeated error types: {len(repeaters)}")
                # Sort by repeat count descending (worst offenders first)
                for key, data in sorted(repeaters, key=lambda x: x[1][0], reverse=True):
                    count, first_msg, _, _, _ = data
                    short_sig = self._normalize_for_dedup(first_msg)[:60]
                    lines.append(f"  +{count-1} repeats (total {count}): {short_sig}")
            else:
                lines.append("All errors were unique (no repeats detected).")
            
            lines.append("====================================")
            
            if self.log_file_handle:
                for line in lines:
                    self._log_to_file(line)
                self.flush()
            
            if repeaters:
                total_collapsed = sum(d[0]-1 for _, d in repeaters)
                self._log_to_console(f"[SUMMARY] Collapsed {total_collapsed} redundant error lines", is_error=False)
            
            self._error_buffer.clear()
            
    def _log_message(self, level: int, message: str, exc_info: bool, module_name: str = PLUGIN_LOGGER_NAME):
        # Significant events (WARNING+) get forensic dedup treatment
        if level >= MO2_LOG_WARNING:
            self._log_significant_event(level, message, exc_info, module_name)
            return
        
        # Below: chatty levels only (INFO/DEBUG/TRACE) – throttle spam
        if self._is_spam(message):
            return
            
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] [Level {self._get_level_name(level)}] [{module_name}] {message}"
        
        # File: INFO excluded by design (goes to viewer buffer only), DEBUG only if debug mode
        if self.log_file_handle and level != MO2_LOG_INFO:
            if level == MO2_LOG_DEBUG and not self._debug_mode:
                pass  # Skip debug file write if mode off
            else:
                self._log_to_file(log_entry)
                if exc_info:
                    self._log_to_file(traceback.format_exc())
                self.flush()
        
        # Console: DEBUG/TRACE only when debug mode enabled
        # INFO stays out of console (viewer handles it)
        if self._debug_mode and level <= MO2_LOG_DEBUG:
            self._log_to_console(log_entry)
        elif self._debug_mode and level <= MO2_LOG_TRACE:
            self._log_to_console(log_entry)

        if exc_info and not self.log_file_handle: # If no log file, print traceback to console
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()

    def _log_to_file(self, message: str):
        if self.log_file_handle:
            self.log_file_handle.write(message + "\n")

    def _log_to_console(self, message: str, is_error: bool = False):
        # MO2's internal logger captures print() to stdout/stderr.
        # We'll use print for simplicity, MO2 will redirect it.
        if is_error:
            print(message, file=sys.stderr)
        else:
            print(message, file=sys.stdout)
        sys.stdout.flush() # Ensure immediate flush
        sys.stderr.flush() # Ensure immediate flush

    def _get_level_name(self, level: int) -> str:
        if level == MO2_LOG_CRITICAL: return "CRITICAL"
        if level == MO2_LOG_ERROR: return "ERROR"
        if level == MO2_LOG_WARNING: return "WARNING"
        if level == MO2_LOG_INFO: return "INFO"
        if level == MO2_LOG_DEBUG: return "DEBUG"
        if level == MO2_LOG_TRACE: return "TRACE"
        return str(level)

    # --- Public logging methods ---
    def trace(self, message: str, exc_info: bool = False, module_name: str = PLUGIN_LOGGER_NAME):
        if self._debug_mode: # Only process trace if debug mode is on
            self._log_message(MO2_LOG_TRACE, message, exc_info, module_name)

    def debug(self, message: str, exc_info: bool = False, module_name: str = PLUGIN_LOGGER_NAME):
        if self._debug_mode: # Only process debug if debug mode is on
            self._log_message(MO2_LOG_DEBUG, message, exc_info, module_name)

    def info(self, message: str, exc_info: bool = False, module_name: str = PLUGIN_LOGGER_NAME): # Default to_ui to True for info
        self._log_message(MO2_LOG_INFO, message, exc_info, module_name)

    def warning(self, message: str, exc_info: bool = False, module_name: str = PLUGIN_LOGGER_NAME): # Default to_ui to True for warning
        self._log_message(MO2_LOG_WARNING, message, exc_info, module_name)

    def error(self, message: str, exc_info: bool = False, module_name: str = PLUGIN_LOGGER_NAME): # Default to_ui to True for error
        self._log_message(MO2_LOG_ERROR, message, exc_info, module_name)

    def critical(self, message: str, exc_info: bool = False, module_name: str = PLUGIN_LOGGER_NAME): # Default to_ui to True for critical
        self._log_message(MO2_LOG_CRITICAL, message, exc_info, module_name)

    def flush(self):
        """Forces a flush of the log file buffer."""
        if self.log_file_handle:
            self.log_file_handle.flush()
            os.fsync(self.log_file_handle.fileno()) # Ensure data is written to disk

    def close(self):
        """Closes the log file handle."""
        if self.log_file_handle:
            self.log_file_handle.close()
            self.log_file_handle = None
            SkyGenLogger._logging_configured = False # Reset for potential re-init

    def set_debug_mode(self, enable: bool):
        """
        Sets the debug mode for the logger.
        If True, DEBUG and TRACE messages will be processed.
        """
        self._debug_mode = enable
        self.info(f"Logger debug mode set to: {enable}", module_name="SkyGenLoggerConfig")

    def set_traceback_logging(self, on: bool) -> None:
        self._log_traceback = bool(on)


class LoggingMixin:
    """
    A mixin class to provide logging functionality to other classes.
    Each instance of a class using this mixin will use the global SkyGenLogger instance.
    """
    def __init__(self):
        self._logger = SkyGenLogger() 
        self._module_name = self.__class__.__name__ 

    # The log methods here will now simply call the singleton logger's methods.
    # The 'to_ui' argument is for SkyGenToolDialog's specific log methods, not the core mixin.
    def log_trace(self, message: str, exc_info: bool = False, to_ui: bool = False):
        self._logger.trace(message, exc_info, self._module_name)

    def log_debug(self, message: str, exc_info: bool = False, to_ui: bool = False):
        self._logger.debug(message, exc_info, self._module_name)
    def log_info(self, message: str, exc_info: bool = False, to_ui: bool = True): # Default to_ui to True for info
        self._logger.info(message, exc_info, self._module_name)

    def log_warning(self, message: str, exc_info: bool = False, to_ui: bool = True): # Default to_ui to True for warning
        self._logger.warning(message, exc_info, self._module_name)

    def log_error(self, message: str, exc_info: bool = False, to_ui: bool = True): # Default to_ui to True for error
        self._logger.error(message, exc_info, self._module_name)

    def log_critical(self, message: str, exc_info: bool = False, to_ui: bool = True): # Default to_ui to True for critical
        self._logger.critical(message, exc_info, self._module_name)