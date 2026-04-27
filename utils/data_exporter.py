# data_exporter.py 
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ..utils.logger import LoggingMixin, SkyGenLogger, MO2_LOG_INFO, MO2_LOG_DEBUG
from ..src.organizer_wrapper import OrganizerWrapper
from ..extractors.plugin_extractor import PluginExtractor
from ..core.constants import SKYPATCHER_SUPPORTED_RECORD_TYPES, SIGNATURE_TO_FILTER, FILTER_TO_ACTIONS
from ..extractors.reader import iter_records
from ..extractors.reader import PluginReader

try:
    from lz4 import block as lz4_block
except ImportError:
    lz4_block = None


class DataExporter(LoggingMixin):
    """
    Thin orchestrator:
      - decides whether to run fast whitelist scan (use_fast_scan=True)
      - always filters by category/keywords *after* extraction
      - returns flat list of records ready for patch builder
      - caches extracted data for speed/space-saver modes
    """

    def __init__(
        self,
        organizer_wrapper: OrganizerWrapper,
        plugin_extractor: PluginExtractor,
        cache_manager: Any = None,
        active_plugins: Optional[List[str]] = None,  # <-- ADD
    ) -> None:
        super().__init__()
        self.organizer_wrapper = organizer_wrapper
        self.plugin_extractor = plugin_extractor
        self.cache_manager = cache_manager
        self.active_plugins = active_plugins  # <-- ADD
        self.logger = LoggingMixin()

    # ------------------------------------------------------------------
    #  Public entry – added use_fast_scan bool
    # ------------------------------------------------------------------
    def export_plugin_data(
        self,
        plugin_names_to_extract: List[str],
        game_version: str,
        target_category: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        include_all_records: bool = False,
        progress_callback: Any = None,
        worker_instance: Any = None,
        use_fast_scan: bool = True,
        generate_all_categories: bool = False,
        profile_mgr: Optional[Any] = None,  # <-- ADD: For manifest pre-filter
    ) -> List[Dict[str, Any]]:
        """
        Hybrid scan with manifest pre-filter and Last-Mod-Wins logic.
        """
        self.log_info(f"Export begin – {len(plugin_names_to_extract)} plugins, fast-scan={use_fast_scan}")

        # Determine mode
        if generate_all_categories:
            mode_str = "allcats"
        elif len(plugin_names_to_extract) > 2:
            mode_str = "modlist"
        else:
            mode_str = "single"

        cache_key = f"extracted_{mode_str}_{'_'.join(sorted(plugin_names_to_extract))}_{target_category or 'all'}_fast{use_fast_scan}"
        lo_hash = hash(tuple(self.active_plugins or [])) & 0xFFFFFFFF
        cache_key += f"_lo{lo_hash}"

        # Try cache
        if self.cache_manager:
            cached = self.cache_manager.load_from_cache(cache_key)
            if cached:
                return cached

        # LMW FIX: Reverse plugin order for Last-Mod-Wins (Mode 3 & multi-plugin)
        # Process last plugin first so its records "win" the dedup
        if generate_all_categories or len(plugin_names_to_extract) > 1:
            plugin_names_to_extract = list(reversed(plugin_names_to_extract))
            self.log_debug(f"LMW order: reversed to {len(plugin_names_to_extract)} plugins (last mod wins)")

        target_offsets: List[Dict[str, Any]] = []
        reader_instance = PluginReader(self.organizer_wrapper, active_plugins=getattr(self, 'active_plugins', None))
        scan_categories = SKYPATCHER_SUPPORTED_RECORD_TYPES if generate_all_categories else {target_category} if target_category else set()
        
        # VIP offset scan (unchanged)
        if use_fast_scan and scan_categories:
            for idx, plugin_name in enumerate(plugin_names_to_extract, 1):
                if progress_callback and idx % 5 == 0:
                    progress_callback(idx, len(plugin_names_to_extract), f"Scanning: {plugin_name}")
                path = self.organizer_wrapper.get_plugin_path(plugin_name)
                if path:
                    # HYBRID FIX: Check manifest before scanning file
                    if profile_mgr:
                        entry = profile_mgr.get_plugin_data(plugin_name)
                        if entry and entry.object_signatures is not None:
                            # Skip if this mod has zero relevant objects (pure script mod)
                            if not entry.object_signatures.intersection(scan_categories):
                                self.log_debug(f"MANIFEST_SKIP: {plugin_name} (no relevant objects for {scan_categories})")
                                continue
                    
                    for rec in iter_records(path, mod_name=plugin_name, worker_instance=worker_instance,
                                           lz4_block=lz4_block, reader=reader_instance):
                        if rec["signature"].strip('_ ') in scan_categories:
                            target_offsets.append({
                                "path": path,
                                "offset": rec["offset"],
                                "mod_name": plugin_name
                            })

        extracted_records: List[Dict[str, Any]] = []

        # Mode 1: Single plugin/category (no LMW needed, no manifest filter needed for single)
        if not generate_all_categories and len(plugin_names_to_extract) <= 2:
            target_cat_clean = target_category.strip('_ ') if target_category else ''  # Cache strip result once
            for plugin_name in plugin_names_to_extract:
                path = self.organizer_wrapper.get_plugin_path(plugin_name)
                if not path:
                    continue
                for rec in iter_records(path, mod_name=plugin_name, worker_instance=worker_instance,
                                       lz4_block=lz4_block, reader=reader_instance):
                    if rec["signature"].strip('_ ') == target_cat_clean:
                        record = self.plugin_extractor.extract_at_offset(path, rec["offset"], worker_instance)
                        if record:
                            record["file_name"] = plugin_name
                            # Pre-compute SkyPatcher metadata so PG stays dumb
                            sig = record.get("signature", "")
                            record["sp_filter"] = SIGNATURE_TO_FILTER.get(sig.upper(), "filterByKeywords")
                            record["sp_action"] = FILTER_TO_ACTIONS.get(record["sp_filter"], ["addKeywords"])[0]
                            form_id = record.get('form_id', '00000000')
                            prefix = form_id[:2].upper()
                            try:
                                idx = int(prefix, 16)
                                record['origin_plugin'] = self.active_plugins[idx] if (0 <= idx < len(self.active_plugins)) else "Unknown"
                            except (ValueError, IndexError):
                                record['origin_plugin'] = "Unknown"
                            extracted_records.append(record)

        # Mode 2: Modlist generation (with LMW reversal + manifest pre-filter)
        elif not generate_all_categories and target_category:
            target_cat_clean = target_category.strip('_ ')
            for plugin_name in plugin_names_to_extract:
                path = self.organizer_wrapper.get_plugin_path(plugin_name)
                if not path:
                    continue
                
                if profile_mgr:
                    entry = profile_mgr.get_plugin_data(plugin_name)
                    if entry and entry.object_signatures:
                        if target_category not in entry.object_signatures:
                            continue
                
                for rec in iter_records(path, mod_name=plugin_name, worker_instance=worker_instance,
                                       lz4_block=lz4_block, reader=reader_instance):
                    if rec["signature"].strip('_ ') == target_cat_clean:
                        record = self.plugin_extractor.extract_at_offset(path, rec["offset"], worker_instance)
                        if record:
                            record["file_name"] = plugin_name
                            # Pre-compute SkyPatcher metadata so PG stays dumb
                            sig = record.get("signature", "")
                            record["sp_filter"] = SIGNATURE_TO_FILTER.get(sig.upper(), "filterByKeywords")
                            record["sp_action"] = FILTER_TO_ACTIONS.get(record["sp_filter"], ["addKeywords"])[0]
                            record["category"] = target_category
                            form_id = record.get('form_id', '00000000')
                            prefix = form_id[:2].upper()
                            try:
                                idx = int(prefix, 16)
                                record['origin_plugin'] = self.active_plugins[idx] if (0 <= idx < len(self.active_plugins)) else "Unknown"
                            except (ValueError, IndexError):
                                record['origin_plugin'] = "Unknown"
                            extracted_records.append(record)

        # Mode 3: All categories (LMW reversal + manifest filter + dedup)
        else:
            seen_formids: Set[str] = set()
            skipped_count = 0
            
            for plugin_name in plugin_names_to_extract:
                path = self.organizer_wrapper.get_plugin_path(plugin_name)
                if not path:
                    continue
                
                # HYBRID: Manifest pre-filter (skip if no relevant signatures at all)
                if profile_mgr:
                    entry = profile_mgr.get_plugin_data(plugin_name)
                    if entry and entry.object_signatures is not None:
                        # Empty set = pure script mod, skip
                        if not entry.object_signatures:
                            skipped_count += 1
                            continue
                
                for rec in iter_records(path, mod_name=plugin_name, worker_instance=worker_instance,
                                       lz4_block=lz4_block, reader=reader_instance):
                    form_id_key = rec.get("form_id", "")
                    if form_id_key in seen_formids:
                        continue
                    seen_formids.add(form_id_key)
                    
                    record = self.plugin_extractor.extract_at_offset(path, rec["offset"], worker_instance)
                    if record:
                        record["file_name"] = plugin_name
                        # Pre-compute SkyPatcher metadata so PG stays dumb
                        sig = record.get("signature", "")
                        record["sp_filter"] = SIGNATURE_TO_FILTER.get(sig.upper(), "filterByKeywords")
                        record["sp_action"] = FILTER_TO_ACTIONS.get(record["sp_filter"], ["addKeywords"])[0]
                        record["category"] = rec.get("signature", "UNKN")
                        form_id = record.get('form_id', '00000000')
                        prefix = form_id[:2].upper()
                        try:
                            idx = int(prefix, 16)
                            record['origin_plugin'] = self.active_plugins[idx] if (0 <= idx < len(self.active_plugins)) else "Unknown"
                        except (ValueError, IndexError):
                            record['origin_plugin'] = "Unknown"
                        extracted_records.append(record)
            
            if skipped_count > 0:
                self.log_info(f"Manifest-filtered: skipped {skipped_count} non-content mods")

        # Cache save
        if self.cache_manager and extracted_records:
            self.cache_manager.save_to_cache(cache_key, extracted_records)

        return extracted_records

    def _resolve_formid_to_plugin(self, form_id_hex: str) -> str:
        """Resolve FormID prefix (e.g., '03') to plugin name using active_plugins list."""
        if not form_id_hex or len(form_id_hex) < 2:
            return "Unknown"
        prefix = form_id_hex[:2].upper()
        try:
            index = int(prefix, 16)
            if self.active_plugins and 0 <= index < len(self.active_plugins):
                return self.active_plugins[index]
        except (ValueError, IndexError):
            pass
        return "Unknown"