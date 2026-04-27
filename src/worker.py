from __future__ import annotations

import traceback
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional
from lz4 import block as lz4_block

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, Qt, QThread     # type: ignore

from ..utils.logger import (LoggingMixin, SkyGenLogger,
    MO2_LOG_DEBUG, MO2_LOG_INFO, MO2_LOG_ERROR, MO2_LOG_TRACE, MO2_LOG_WARNING, MO2_LOG_CRITICAL
)
from ..src.organizer_wrapper import OrganizerWrapper
from ..extractors.plugin_extractor import PluginExtractor
from ..extractors.reader import PluginReader, iter_records
from ..utils.data_exporter import DataExporter
from ..utils.patch_gen import PatchAndConfigGenerationManager
from ..core.models import ApplicationConfig, PatchGenerationOptions
from ..core.constants import (SKYPATCHER_SUPPORTED_RECORD_TYPES, FILTER_TO_ACTIONS, SIGNATURE_TO_CATEGORIES,
                              SIGNATURE_TO_FILTER, BASE_GAME_PLUGINS, MOD_INDEX_OFFSET)
from ..utils.file_ops import FileOperationsManager
from ..storage.cache import CacheManager



# ==================================================================
#  GENERATION WORKER (QRunnable) 
# ==================================================================
class GenerationWorkerSignals(QObject):
    """Signals for the GenerationWorker."""
    log_line = pyqtSignal(str, int)
    gen_progress = pyqtSignal(dict)
    generation_finished = pyqtSignal(bool, str, str)  # success, out_type, message
    error_occurred = pyqtSignal(str, str)


class GenerationWorker(QRunnable, LoggingMixin):
    """
    Worker for the patch generation process.
    Supports SkyPatcher output.
    Restores the full 15KB logic brain while adding dual-path initialization.
    """
    def __init__(
        self,
        active_plugins: List[str],              # <-- ADD
        target_plugins: List[str],              # <-- ADD  
        organizer_wrapper: Optional[OrganizerWrapper] = None,
        file_operations_manager: Optional[FileOperationsManager] = None,
        plugin_extractor: Optional[PluginExtractor] = None,
        patch_generator: Optional[PatchAndConfigGenerationManager] = None,
        data_exporter: Optional[DataExporter] = None,
        app_config: Optional[ApplicationConfig] = None,
        patch_settings: Optional[PatchGenerationOptions] = None,
        cache_manager: Optional[CacheManager] = None, 
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__()
        LoggingMixin.__init__(self)
        self.signals = GenerationWorkerSignals()
        self._interrupted = False
        self.active_plugins = active_plugins      
        self.target_plugins = target_plugins      
        self.cache_manager = cache_manager        
        
        if parent:
            self.signals.moveToThread(parent.thread())
            self.organizer_wrapper = organizer_wrapper
            self.file_ops = file_operations_manager
            self.plugin_extractor = plugin_extractor
            self.patch_gen = patch_generator
            self.data_exporter = data_exporter
            self.app_config = app_config
            self.patch_settings = patch_settings
    # ------------------------------------------------------------------
    # logging interface 
    # ------------------------------------------------------------------
    def _log(self, level: int, msg: str) -> None:
        self.signals.log_line.emit(msg, level)

    def log_info(self, msg: str) -> None: self._log(MO2_LOG_INFO, msg)
    def log_debug(self, msg: str) -> None: self._log(MO2_LOG_DEBUG, msg)
    def log_trace(self, msg: str) -> None: self._log(MO2_LOG_TRACE, msg)
    def log_error(self, msg: str) -> None: self._log(MO2_LOG_ERROR, msg)
    def log_warning(self, msg: str) -> None: self._log(MO2_LOG_WARNING, msg)
    def log_critical(self, msg: str, exc_info: bool = False) -> None:
        self._log(MO2_LOG_CRITICAL, msg)
        if exc_info:
            self._log(MO2_LOG_CRITICAL, traceback.format_exc())

    def run(self) -> None:
        """Main execution loop."""
        start_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_info(f"GenerationWorker (Muscle) started at {start_ts}")
        
        # ✅ FIX: Remove options dict, use app_config directly
        out_type = getattr(self.app_config, "output_type", "SkyPatcher INI")
        success, message = False, "Unknown error"

        try:
            success, message = self._generate_patch(out_type)
        except Exception as exc:
            tb = traceback.format_exc()
            self.log_error(f"Worker crash: {exc}\n{tb}")
            message = f"Error: {exc}"
            self.signals.error_occurred.emit("Patch Generation Error", message)
        finally:
            self.signals.generation_finished.emit(success, out_type, message)

    def _get_selected_plugins(self) -> List[str]:
        """Derive selected plugins list from patch settings and organizer."""
        if not self.patch_settings:
            self.log_error("Patch settings not initialized")
            return []
        
        # Modlist or all-categories mode: use filtered silo (already BL-screened)
        if getattr(self.patch_settings, 'generate_modlist', False) or getattr(self.patch_settings, 'generate_all_categories', False):
            self.log_debug("Mode: modlist – using filtered silo targets")
            if self.target_plugins:
                return list(self.target_plugins)
            self.log_warning("No target_plugins injected by controller - empty return")
            return []
        
        # Single mode: use target and required source
        self.log_debug("Mode: single plugin/category")
        plugins = []
        
        target = getattr(self.patch_settings, 'target_mod', '').strip()
        if target:
            plugins.append(target)
        
        source = getattr(self.patch_settings, 'source_mod', '').strip()
        if source and source not in plugins:
            plugins.append(source)
        
        return plugins

    def _extract_records_direct(self, plugin_name: str, category: str) -> List[Dict[str, Any]]:
        """
        Surgical extraction for single mode – uses PluginExtractor directly.
        Bypasses Reader's 10MB limit and uses working decompression chain.
        """
        records = []
        
        if not plugin_name or not category:
            return records
        
        path = self.organizer_wrapper.get_plugin_path(plugin_name)
        if not path:
            self.log_warning(f"Direct extraction: path not found for {plugin_name}")
            return records
        
        try:
            self.log_debug(f"Direct scanning {plugin_name} for {category} records")
            
            # Use PluginExtractor directly - no 10MB limit, proper GRUP handling
            data = self.plugin_extractor.extract_data_from_plugins(
                plugin_names=[plugin_name],
                game_version="SkyrimSE",  # TODO: get from app_config.game_version if needed
                worker_instance=self,
                record_types=[category.encode('utf-8')]
            )
            
            records = data.get("baseObjects", [])
            self.log_info(f"Direct extraction: {len(records)} {category} records from {plugin_name}")
            
        except Exception as e:
            self.log_error(f"Error during direct extraction from {plugin_name}: {e}")
            import traceback
            self.log_debug(traceback.format_exc())
        
        return records

    def _generate_patch(self, ot: str) -> tuple[bool, str]:
        """
        Internal generation logic. 
        Fully restored extraction, filtering, and writing paths from 15KB backup.
        """
        # ------------------------------------------------------------------
        # 1. initialization & extraction
        # ------------------------------------------------------------------
        self._emit_progress(0.0, 3, "Initializing", "Preparing plugin scan...")
        
        # Grab extractor or create a local one if missing
        extractor = self.plugin_extractor or PluginExtractor(self.organizer_wrapper)

        # CRITICAL: Sync both Extractor AND DataExporter for origin resolution
        if self.plugin_extractor and self.active_plugins:
            self.plugin_extractor.active_plugins = self.active_plugins
        if self.data_exporter and self.active_plugins:
            self.data_exporter.active_plugins = self.active_plugins
            self.log_debug(f"Synced {len(self.active_plugins)} plugins to DataExporter")   
            
        # ✅ FIX: Derive selected plugins from settings
        selected_plugins = self._get_selected_plugins()
        
        self.log_info(f"Worker starting extraction of {len(selected_plugins)} plugins.")
        self._emit_progress(0.5, 3, "Extracting", f"Scanning {len(selected_plugins)} plugins...")
        
        # ✅ FIX: Explicit mode flags — hoist before use
        generate_all_categories = getattr(self.patch_settings, 'generate_all_categories', False)
        generate_modlist = getattr(self.patch_settings, 'generate_modlist', False)
        target_category = getattr(self.patch_settings, 'category', '')
        
        extracted_records = []
        lz4_block = getattr(self.patch_settings, 'use_fast_scan', True)
        reader_instance = PluginReader(self.organizer_wrapper) if (generate_modlist or generate_all_categories) else None

        # Mode 1: Single plugin/category — direct extraction + LMW merge
        if not generate_all_categories and not generate_modlist:
            target_name = selected_plugins[0] if selected_plugins else ""
            source_name = selected_plugins[1] if len(selected_plugins) > 1 else ""
            self.log_info(f"Single mode: Target={target_name}, Source={source_name}, Category={target_category}")
            
            # Extract target records
            # Route single mode through DE — fresh extraction, correct origins
            de_records = self.data_exporter.export_plugin_data(
                plugin_names_to_extract=selected_plugins,
                game_version=getattr(self.app_config, 'game_version', 'SkyrimSE'),
                target_category=target_category,
                worker_instance=self,
                use_fast_scan=False,
            )
            if de_records is None:
                de_records = []
            
            # LMW: last plugin in list wins (source over target)
            merged_by_fid = {}
            for rec in de_records:
                fid = rec.get('form_id')
                if fid:
                    merged_by_fid[fid] = rec
            
            extracted_records = list(merged_by_fid.values())
            self.log_info(f"Single mode complete: {len(extracted_records)} records (DE returned {len(de_records)})")

        # Mode 2: Modlist — Reader path with filtered silo targets
        elif generate_modlist and target_category:
            scan_cats = {target_category.strip('_ ')}
            self.log_info(f"Modlist mode: scanning {len(selected_plugins)} plugins for {target_category}")
            for plugin_idx, plugin_name in enumerate(selected_plugins):
                if self._interrupted:
                    return False, "User cancelled."
                
                if plugin_idx % 10 == 0:
                    self.log_info(f"Scan progress: {plugin_idx}/{len(selected_plugins)} – {plugin_name}")
                
                path = self.organizer_wrapper.get_plugin_path(plugin_name)
                if not path:
                    continue
                
                for rec in iter_records(path, mod_name=plugin_name, worker_instance=self,
                                       lz4_block=lz4_block, reader=reader_instance):
                    if self._interrupted:
                        return False, "User cancelled."
                    
                    if rec["signature"].strip(' ') in scan_cats:
                        record = self.plugin_extractor.extract_at_offset(path, rec["offset"], self)
                        if record:
                            record["file_name"] = plugin_name
                            extracted_records.append(record)
                            
                            if len(extracted_records) % 50 == 0:
                                self.log_info(f"Extracted {len(extracted_records)} {target_category} records...")

        # Mode 3: All categories — Reader path with filtered silo targets
        elif generate_all_categories:
            scan_cats = SKYPATCHER_SUPPORTED_RECORD_TYPES
            self.log_info(f"All-cats mode: scanning {len(selected_plugins)} plugins for all types")
            for plugin_idx, plugin_name in enumerate(selected_plugins):
                if self._interrupted:
                    return False, "User cancelled."
                
                if plugin_idx % 10 == 0:
                    self.log_info(f"Scan progress: {plugin_idx}/{len(selected_plugins)} – {plugin_name}")
                
                path = self.organizer_wrapper.get_plugin_path(plugin_name)
                if not path:
                    continue
                
                for rec in iter_records(path, mod_name=plugin_name, worker_instance=self,
                                       lz4_block=lz4_block, reader=reader_instance):
                    if self._interrupted:
                        return False, "User cancelled."
                    
                    if rec["signature"].strip(' ') in scan_cats:
                        record = self.plugin_extractor.extract_at_offset(path, rec["offset"], self)
                        if record:
                            record["file_name"] = plugin_name
                            extracted_records.append(record)
                            
                            if len(extracted_records) % 50 == 0:
                                self.log_info(f"Extracted {len(extracted_records)} total records...")

        else:
            return False, "No generation mode selected"
        self.log_info(f"TARGET_AUDIT: patch_settings.target_mod='{self.patch_settings.target_mod}'")
        self.log_info(f"SOURCE_AUDIT: patch_settings.source_mod='{self.patch_settings.source_mod}'")
        if self._interrupted:
            return False, "User cancelled."

        # ------------------------------------------------------------------
        # 2. deduplication & processing (Heartbeat restored)
        # ------------------------------------------------------------------
        self._emit_progress(1.5, 3, "Processing", f"Filtering {len(extracted_records)} total records...")
        
        seen_formids = {}
        kept_records = []
        
        for i, rec in enumerate(extracted_records):
            if self._interrupted:
                break
            
            form_id = rec.get("form_id")
            if form_id and form_id not in seen_formids:
                seen_formids[form_id] = True
                kept_records.append(rec)
            
            # Heartbeat to keep UI alive and allow interruption checks
            if i % 250 == 0:
                QThread.msleep(1)

        if self._interrupted:
            return False, "User cancelled."

        # 3. File generation (SkyPatcher only – BOS uses direct panel path)
        self._emit_progress(2.5, 3, "Writing", f"Generating {ot} files...")
        output_folder = Path(self.patch_settings.skypatcher_output_folder)
        success = False

        if ot == "SkyPatcher INI":
            # ✅ FIX: Pass SB args explicitly to patch_gen
            success = self.patch_gen.generate_skypatcher_ini(
                extracted_data={"baseObjects": kept_records},
                category=self.patch_settings.category,
                target_mod_plugin_name=self.patch_settings.target_mod,
                source_mod_plugin_name=self.patch_settings.source_mod,
                source_mod_display_name=self.patch_settings.source_mod,
                source_mod_base_objects=None,
                all_exported_target_bases_by_formid={r["form_id"]: r for r in kept_records if "form_id" in r},
                dialog_instance=self,
                output_folder_path=output_folder,
                generate_all_categories=self.patch_settings.generate_all_categories,
                generate_modlist=generate_modlist,
                use_sentence_builder=getattr(self.patch_settings, 'sp_use_sentence_builder', True),
                sp_filter_type=getattr(self.patch_settings, 'sp_filter_type', ''),
                sp_action_type=getattr(self.patch_settings, 'sp_action_type', ''),
                sp_value_formid=getattr(self.patch_settings, 'sp_value_formid', ''),
                sp_lmw_winners_only=getattr(self.patch_settings, 'sp_lmw_winners_only', True),
            )
            
            # Cache vault lock: Store records for instant replay
            if success and self.cache_manager and kept_records:
                cache_key = self.cache_manager.generate_key(
                    plugins=self._get_selected_plugins(),
                    category=self.patch_settings.category if not self.patch_settings.generate_all_categories else None,
                    target_mod=self.patch_settings.target_mod,
                    source_mod=self.patch_settings.source_mod
                )
                self.log_info(f"Locking {len(kept_records)} records into vault (key: {cache_key[:16]}...)")
                self.cache_manager.save_to_cache(cache_key, kept_records)
                self.log_info("Cache locked successfully")


        # ------------------------------------------------------------------
        # 4. finish
        # ------------------------------------------------------------------
        self._emit_progress(3.0, 3, "Complete",
                            f"{'Succeeded' if success else 'Failed'} – output folder: {output_folder}")
        return success, f"{ot} generated successfully to {output_folder}" if success else "Generation failed."

    # ------------------------------------------------------------------
    # utils
    # ------------------------------------------------------------------
    def _emit_progress(self, cur: float, total: int, status: str, details: str = "") -> None:
        progress_info = {"cur": cur, "total": total, "status": status, "details": details, "level": MO2_LOG_INFO}
        self.signals.gen_progress.emit(progress_info)

    def request_interruption(self) -> None:
        self._interrupted = True
        self.log_info("GenerationWorker: Interruption requested.")
        self.signals.gen_progress.emit({
            "cur": 0.0,
            "total": 1,
            "status": "Cancelling...",
            "details": "",
            "level": MO2_LOG_INFO
        })