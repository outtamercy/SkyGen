import os
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, List
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from .logger import LoggingMixin, MO2_LOG_INFO, MO2_LOG_DEBUG, MO2_LOG_WARNING

class Guard(QObject, LoggingMixin):
    """
    The bouncer. Checks IDs at the door, decides who gets in.
    No work happens until the user actually opens the club.
    """
    
    # Signals to control the welcome flow
    scan_started = pyqtSignal()
    scan_progress = pyqtSignal(str, int)  # message, percent
    scan_complete = pyqtSignal(bool)  # success
    continue_enabled = pyqtSignal()
    # Force welcome screen when ML changes
    welcome_required = pyqtSignal(str)  # reason: 'ml_change', 'logic_change', 'fresh', etc.
    
    def __init__(self, plugin_path: Path, organizer_wrapper: Any):
        QObject.__init__(self)
        LoggingMixin.__init__(self)
        
        self.plugin_path = plugin_path
        self.wrapper = organizer_wrapper
        self.data_dir = plugin_path / "data"
        
        # These get set when we figure out what kind of party this is
        self._is_fresh_install = False
        self._is_bat_complete = False  
        self._manifest_exists = False
        self._silos_exist = False
        self._load_order_changed = False
        self._logic_version_changed = False
        
        # The heavy lifter - created on demand, not now
        self._profile_manager = None
        
    def assess_situation(self) -> str:
        """
        Quick recon - what are we dealing with?
        Returns 'fresh', 'bat_complete', 'ml_change', or 'ready'
        """
        manifest_path = self.data_dir / f"skygen_manifest_{self.wrapper.profile_name}.ini"
        silo_path = self.data_dir / f"skygen_silos_{self.wrapper.profile_name}.ini"
        
        self._manifest_exists = manifest_path.exists()
        self._silos_exist = silo_path.exists()
        
        if not self._manifest_exists and not self._silos_exist:
            self._is_fresh_install = True
            self.log_info("Fresh install detected - full cold boot needed")
            return "fresh"
            
        if self._manifest_exists and not self._silos_exist:
            self._is_bat_complete = True
            self.log_info("Bat-folder completion - manifest exists, silos missing")
            return "bat_complete"
            
        if self._manifest_exists and self._silos_exist:
            # Check if load order drifted since last run
            current_sig = self._get_loadorder_signature()
            stored_sig = self._read_stored_signature()
            
            if current_sig != stored_sig:
                self._load_order_changed = True
                self.log_info(f"Load order changed ({stored_sig[:8]}... -> {current_sig[:8]}...)")
                return "ml_change"
                
            # Check logic version bump
            from ..core.constants import CURRENT_EXTRACTION_LOGIC_VERSION
            stored_ver = self._read_stored_logic_version()
            
            if stored_ver < CURRENT_EXTRACTION_LOGIC_VERSION:
                self._logic_version_changed = True
                self.log_info(f"Logic version bump ({stored_ver} -> {CURRENT_EXTRACTION_LOGIC_VERSION})")
                return "logic_change"
        
        self.log_info("Everything looks current - fast load")
        return "ready"
        
    def start_scan(self) -> None:
        """Assess and signal. Heavy lifting is controller's job."""
        self.scan_started.emit()
        self.log_info("Guard: Starting scan workflow")
        
        situation = self.assess_situation()
        
        if situation == "ready":
            self.log_info("Guard: System ready, no scan needed")
            self.continue_enabled.emit()
            self.scan_complete.emit(True)
            return
            
        # Controller handles the actual async scan via _on_guard_scan_start
        self.log_info(f"Guard: Situation '{situation}' - delegating to controller")
        # Do NOT create PM or call refresh_silos here - that's controller's threadpool job
        
    def _on_scan_finished(self, success: bool):
        """Frankie finished building the silos."""
        if success:
            self.log_info("Guard: Scan complete, unlocking door")
            self.continue_enabled.emit()
        else:
            self.log_warning("Guard: Scan failed, keeping door locked")
            
        self.scan_complete.emit(success)
        
    def _get_loadorder_signature(self) -> str:
        """Hash the plugin list - if this changes, we rescan."""
        plugins = self.wrapper.read_loadorder_txt()
        clean = [p.strip().lower() for p in plugins if p.strip() and not p.startswith('#')]
        sequence = "|".join(clean)
        return hashlib.sha256(sequence.encode()).hexdigest()[:16]
        
    def _read_stored_signature(self) -> str:
        """What did the load order look like last time?"""
        manifest_path = self.data_dir / f"skygen_manifest_{self.wrapper.profile_name}.ini"
        if not manifest_path.exists():
            return ""
        try:
            import configparser
            config = configparser.ConfigParser()
            config.read(manifest_path, encoding='utf-8')
            return config.get('_meta', 'loadorder_signature', fallback='')
        except:
            return ""
            
    def _read_stored_logic_version(self) -> int:
        """What version of the sniffer built this manifest?"""
        manifest_path = self.data_dir / f"skygen_manifest_{self.wrapper.profile_name}.ini"
        if not manifest_path.exists():
            return 1
        try:
            import configparser
            config = configparser.ConfigParser()
            config.read(manifest_path, encoding='utf-8')
            return config.getint('_meta', 'extraction_logic_version', fallback=1)
        except:
            return 1
            
    def get_welcome_text_file(self) -> str:
        """Which readme should we show based on the situation?"""
        situation = self.assess_situation()
        
        text_dir = self.plugin_path / "welcome"
        
        mapping = {
            "fresh": "first_launch.txt",
            "bat_complete": "bat_complete.txt", 
            "ml_change": "ml_changed.txt",
            "logic_change": "ml_changed.txt",  # Same message - needs rescan
            "ready": "welcome_back.txt"
        }
        
        return text_dir / mapping.get(situation, "first_launch.txt")