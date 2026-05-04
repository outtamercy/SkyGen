from __future__ import annotations

import traceback
from pathlib import Path
import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from lz4 import block as lz4_block

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, Qt, QThread     # type: ignore

from ..utils.logger import (LoggingMixin, SkyGenLogger,
    MO2_LOG_DEBUG, MO2_LOG_INFO, MO2_LOG_ERROR, MO2_LOG_TRACE, MO2_LOG_WARNING, MO2_LOG_CRITICAL
)
from ..src.organizer_wrapper import OrganizerWrapper
from ..extractors.plugin_extractor import PluginExtractor
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
        keyword_cache: Optional[Dict[str, List[str]]] = None,
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
            self.keyword_cache = keyword_cache or {}
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
        
        # Explicit mode lock — no bleed
        is_allcats = getattr(self.patch_settings, 'generate_all_categories', False)
        is_modlist = getattr(self.patch_settings, 'generate_modlist', False)
        
        if is_allcats and is_modlist:
            self.log_warning("MODE_BLEED_GET_SELECTED: both True — forcing all-cats")
            is_modlist = False
        
        # Mass modes: use filtered silo (already BL-screened)
        if is_allcats or is_modlist:
            mode_name = "allcats" if is_allcats else "modlist"
            self.log_debug(f"Mode: {mode_name} — using filtered silo targets")
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

    def _extract_records_direct(
        self,
        plugin_names: List[str],
        category: Optional[str] = None,
        generate_modlist: bool = False,
        generate_all_categories: bool = False,
        progress_callback: Any = None,
    ) -> List[Dict[str, Any]]:
        """Raw extraction — PE recursive parser only, reader.py killed for SP."""
        if generate_all_categories or len(plugin_names) > 1:
            plugin_names = list(reversed(plugin_names))
            self.log_debug(f"LMW order: reversed to {len(plugin_names)} plugins")

        raw: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        cat_clean = category.strip('_ ') if category else ''

        # PE filter: pass category as bytes set so it skips non-matching signatures early
        record_types_bytes = {cat_clean.encode('utf-8')} if cat_clean else None
        
        self.log_info(f"PE_FILTER: cat='{cat_clean}' bytes={record_types_bytes}")

        for idx, name in enumerate(plugin_names, 1):
            if progress_callback and idx % 10 == 0:
                progress_callback(idx, len(plugin_names), f"scanning {name}")
            path = self.organizer_wrapper.get_plugin_path(name)
            if not path:
                continue

            # KILL READER — use PE's recursive GRUP parser directly
            data = self.plugin_extractor.extract_metadata(
                path,
                worker_instance=self,
                record_types_bytes=record_types_bytes,
                cache_manager=self.cache_manager,
            )

            # Flatten nested GRUP tree into flat dict by form_id
            def _flatten(records):
                flat = {}
                for rec in records:
                    if rec.get("is_grup"):
                        flat.update(_flatten(rec.get("children", [])))
                    else:
                        fid = rec.get("form_id")
                        if fid and fid not in seen:
                            seen.add(fid)
                            rec["file_name"] = name
                            flat[fid] = rec
                return flat

            raw.extend(_flatten(data.get("records", [])).values())

        return raw

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
        
        # ✅ FIX: Derive selected plugins from settings
        selected_plugins = self._get_selected_plugins()
        
        self.log_info(f"Worker starting extraction of {len(selected_plugins)} plugins.")
        self._emit_progress(0.5, 3, "Extracting", f"Scanning {len(selected_plugins)} plugins...")
        
        # ✅ FIX: Explicit mode flags — hoist before use
        generate_all_categories = getattr(self.patch_settings, 'generate_all_categories', False)
        generate_modlist = getattr(self.patch_settings, 'generate_modlist', False)
        target_category = getattr(self.patch_settings, 'category', '')
        
        # ✅ CURE: Explicit mode resolution — no elif bleed possible
        generate_all_categories = getattr(self.patch_settings, 'generate_all_categories', False)
        generate_modlist = getattr(self.patch_settings, 'generate_modlist', False)
        
        # Guard against impossible state — log and force priority
        if generate_all_categories and generate_modlist:
            self.log_warning("MODE_BLEED: both all-cats and modlist True — forcing all-cats")
            generate_modlist = False
        
        if generate_all_categories:
            mode = "allcats"
        elif generate_modlist:
            mode = "modlist"
        else:
            mode = "single"
        
        self.log_info(f"MODE_LOCKED: {mode}")

        # ---- Worker owns raw cache ----
        plugins_slug = hashlib.md5(','.join(sorted(selected_plugins)).encode()).hexdigest()[:12]
        lo_slug = hashlib.md5(','.join(self.active_plugins or []).encode()).hexdigest()[:12]
        cache_key = f"raw_v2_{mode}_{plugins_slug}_{target_category or 'all'}_lo{lo_slug}"

        self.log_info(f"RAW_AUDIT: mode={mode}, plugins={len(selected_plugins)}, cat='{target_category}'")
        raw_records: List[Dict[str, Any]] = []
        if self.cache_manager:
            cached = self.cache_manager.load_from_cache(cache_key)
            if cached:
                self.log_info(f"CACHE_HIT: raw {len(cached)} records")
                raw_records = cached

        if not raw_records:
            raw_records = self._extract_records_direct(
                selected_plugins, target_category,
                generate_modlist=generate_modlist,
                generate_all_categories=generate_all_categories,
                progress_callback=lambda cur, total, msg: self.log_info(f"Extract: {cur}/{total} — {msg}")
            )
            if self.cache_manager and raw_records:
                self.cache_manager.save_to_cache(cache_key, raw_records)

        # Dumb pipe — PE already set origin_plugin and file_name.
        # PG owns Loom, filter/action injection, and filename math.
        # Worker's "helpful" prefix reassignment was lying about ESLs and phantoms.
        extracted_records = raw_records
        self.log_info(f"Dumb pipe: {len(extracted_records)} records to PG")

        if mode == "single":
            target_name = selected_plugins[0] if selected_plugins else ""
            source_name = selected_plugins[1] if len(selected_plugins) > 1 else ""
            self.log_info(f"Single mode: Target={target_name}, Source={source_name}, Category={target_category}")
            
            merged_by_fid = {}
            for rec in extracted_records:
                fid = rec.get('form_id')
                if fid:
                    merged_by_fid[fid] = rec
            extracted_records = list(merged_by_fid.values())
            
            self.log_info(f"Single mode complete: {len(extracted_records)} records (raw returned {len(raw_records)})")

        elif mode == "modlist":
            self.log_info(f"Modlist mode: grinding {len(selected_plugins)} plugins for {target_category}")
            self.log_info(f"Modlist: returned {len(extracted_records)} records")

        elif mode == "allcats":
            self.log_info(f"All-cats mode: grinding {len(selected_plugins)} plugins")
            self.log_info(f"All-cats: returned {len(extracted_records)} records")

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

        # Mass-mode sanitization: all-cats strips everything, ML keeps SB
        is_allcats_mode = generate_all_categories
        is_mass_mode = generate_all_categories or generate_modlist
        pg_target_mod = "" if is_mass_mode else self.patch_settings.target_mod
        pg_source_mod = "" if is_mass_mode else self.patch_settings.source_mod
        pg_category = "" if is_allcats_mode else target_category
        pg_sb_filter = "" if is_allcats_mode else getattr(self.patch_settings, 'sp_filter_type', '')
        pg_sb_action = "" if is_allcats_mode else getattr(self.patch_settings, 'sp_action_type', '')
        pg_sb_value = "" if is_allcats_mode else getattr(self.patch_settings, 'sp_value_formid', '')

        if ot == "SkyPatcher INI":
            # ✅ FIX: Pass SB args explicitly to patch_gen

            success = self.patch_gen.generate_skypatcher_ini(
                extracted_data={"baseObjects": kept_records},
                category=pg_category,
                target_mod_plugin_name=pg_target_mod,
                source_mod_plugin_name=pg_source_mod,
                source_mod_display_name=pg_source_mod,
                source_mod_base_objects=None,
                all_exported_target_bases_by_formid={r["form_id"]: r for r in kept_records if "form_id" in r},
                dialog_instance=self,
                output_folder_path=output_folder,
                generate_all_categories=self.patch_settings.generate_all_categories,
                generate_modlist=generate_modlist,
                use_sentence_builder=getattr(self.patch_settings, 'sp_use_sentence_builder', True),
                sp_filter_type=pg_sb_filter,
                sp_action_type=pg_sb_action,
                sp_value_formid=pg_sb_value,
                active_plugins=self.active_plugins,
            )

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