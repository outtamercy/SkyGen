from pathlib import Path
from typing import List, Dict, Any, Optional
import json
from PyQt6.QtWidgets import QApplication # type: ignore
from PyQt6.QtCore import QEventLoop # type: ignore

from ..extractors.reader import iter_records, PluginReader
from ..utils.logger import LoggingMixin, MO2_LOG_INFO, MO2_LOG_DEBUG
from ..core.constants import BOS_CATEGORIES, BOS_SIGNATURES, BOS_RECORD_MAP, BOS_SUPPORTED_RECORD_TYPES

class BosProcessor(LoggingMixin):
    """Handles BOS plugin scanning, and record filtering."""
    def __init__(self, organizer_wrapper):
        super().__init__()
        self.organizer_wrapper = organizer_wrapper

    def scan_m2m(
        self,
        source_plugins: List[Path],
        target_mod_name: str,
        source_mod_name: str,
        category: str,
        abort_flag: Optional[object] = None,
        progress_callback: Optional[callable] = None,
        active_plugins: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """M2M Mode: Pair source objects with target records by index."""
        
        def _ensure_path(plugin_input):
            if isinstance(plugin_input, Path):
                return plugin_input if plugin_input.exists() else None
            if isinstance(plugin_input, str):
                resolved = self.organizer_wrapper.get_plugin_path(plugin_input)
                return Path(resolved) if resolved else None
            return None
        
        # Resolve source plugins to existing files
        resolved_sources = []
        for sp in source_plugins:
            rp = _ensure_path(sp)
            if rp and rp.exists():
                resolved_sources.append(rp)
        
        # --- PLUGINLESS ASSET DETECTION ---
        # If no plugins resolved but category is asset-based, bail to asset scanner
        is_asset_category = category in ("ASSET_SKIN", "ASSET_BODY", "Skin", "Body")
        
        if not resolved_sources and is_asset_category:
            self.log_info(f"ASSET_MODE: Pluginless source for {category}", MO2_LOG_INFO)
            return self._scan_asset_swap(target_mod_name, source_mod_name, category, active_plugins)
        
        if not resolved_sources:
            return []
        
        # Resolve target plugins using MO2 modList (same pattern as panel's _find_plugins_in_mod)
        target_plugins = []
        try:
            mod_obj = self.organizer_wrapper.organizer.modList().getMod(target_mod_name)
            if mod_obj:
                mod_path = Path(mod_obj.absolutePath())
                if mod_path.is_dir():
                    for pattern in ["*.esp", "*.esm", "*.esl"]:
                        target_plugins.extend(list(mod_path.glob(pattern)))
                        target_plugins.extend(list(mod_path.glob(f"Data/{pattern}")))
        except Exception:
            pass  # Fall through to blessed file resolution
        
        # Fallback to direct path for blessed files (Skyrim.esm, etc.)
        if not target_plugins:
            target_path = self.organizer_wrapper.get_plugin_path(target_mod_name)
            if target_path and Path(target_path).exists():
                target_plugins = [Path(target_path)]
        
        if not target_plugins:
            return []
        
        # Determine wanted signatures from category
        wanted_sigs = BOS_CATEGORIES.get(category, BOS_SIGNATURES) if category != "All" else BOS_SIGNATURES
        
        reader = PluginReader(self.organizer_wrapper, active_plugins=active_plugins)
        
        # STEP 1: Scan TARGET for vanilla FormIDs (victims)
        target_records = []
        for plugin_path in target_plugins:
            if abort_flag and getattr(abort_flag, '_abort_scan', False):
                return []
            
            try:
                seen_fids: set[str] = set()
                for rec in iter_records(plugin_path, reader=reader):
                    sig = rec.get("signature", "")
                    if sig in wanted_sigs:
                        form_id = rec.get("form_id", "")
                        if form_id and form_id not in seen_fids:
                            seen_fids.add(form_id)
                            target_records.append({
                                "form_id": form_id,
                                "plugin_name": plugin_path.name,
                            })
            except Exception:
                continue
        
        if not target_records:
            return []
        
        # STEP 2: Scan SOURCE and pair by index
        m2m_records = []
        source_idx = 0
        total_source_records = 0
        
        for plugin_path in resolved_sources:
            if abort_flag and getattr(abort_flag, '_abort_scan', False):
                return []
            
            seen_fids: set[str] = set()
            
            try:
                for rec in iter_records(plugin_path, reader=reader):
                    sig = rec.get("signature", "")
                    if sig in wanted_sigs:
                        form_id = rec.get("form_id", "")
                        if form_id and form_id not in seen_fids:
                            seen_fids.add(form_id)
                            total_source_records += 1
                            if progress_callback and total_source_records % 50 == 0:
                                progress_callback(
                                    total_source_records, 
                                    len(target_records), 
                                    f"pairing from {plugin_path.name}"
                                )                            
                            if source_idx < len(target_records):
                                target_rec = target_records[source_idx]
                                m2m_records.append({
                                    "form_id": form_id,
                                    "target_form_id": target_rec["form_id"],
                                    "signature": sig,
                                    "editor_id": rec.get("editor_id", ""),
                                    "name": rec.get("name", ""),
                                    "plugin_name": plugin_path.name,
                                    "target_plugin": target_mod_name,
                                    "target_plugin_file": target_rec["plugin_name"],
                                    "mod_name": "M2M",
                                })
                                source_idx += 1
            except Exception:
                continue
        
        # --- ASSET-SWAP FALLBACK ---
        # If we have source plugins but 0 records (texture replacers), 
        # fall back to path-based asset swap using target FormIDs
        if resolved_sources and total_source_records == 0 and target_records:
            self.log_info(f"ASSET_FALLBACK: {len(resolved_sources)} plugins, 0 records - using asset swap", MO2_LOG_INFO)
            for target_rec in target_records[:50]:  # Cap at 50 to avoid spam
                m2m_records.append({
                    "form_id": target_rec["form_id"],  # Use target FID as anchor
                    "target_form_id": target_rec["form_id"],
                    "signature": "ASSET",  # Marker for asset swap
                    "editor_id": "AssetSwap",
                    "name": "Asset Replacement",
                    "plugin_name": source_mod_name,  # <-- FIX: Actually the source mod, not victim
                    "target_plugin": target_mod_name,
                    "target_plugin_file": target_rec["plugin_name"],
                    "mod_name": "ASSET_SWAP",
                    "is_asset_swap": True,
                })
        
        return m2m_records

    def _scan_asset_swap(self, target_mod_name: str, source_mod_name: str,
                         category: str, active_plugins: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Handle pluginless body mods — scan target for FormIDs, tag source correctly."""
        target_plugins = []
        try:
            mod_obj = self.organizer_wrapper.organizer.modList().getMod(target_mod_name)
            if mod_obj:
                mod_path = Path(mod_obj.absolutePath())
                if mod_path.is_dir():
                    for pattern in ["*.esp", "*.esm", "*.esl"]:
                        target_plugins.extend(list(mod_path.glob(pattern)))
                        target_plugins.extend(list(mod_path.glob(f"Data/{pattern}")))
        except Exception:
            pass
        
        # Fallback to direct path for blessed files
        if not target_plugins:
            target_path = self.organizer_wrapper.get_plugin_path(target_mod_name)
            if target_path and Path(target_path).exists():
                target_plugins = [Path(target_path)]
        
        # Nuclear fallback: target mod has no plugins of its own.
        # Victim records are scattered across the whole load order.
        if not target_plugins and active_plugins:
            self.log_info(
                f"ASSET_FALLBACK: {target_mod_name} dry — scanning {len(active_plugins)} active plugins",
                MO2_LOG_INFO
            )
            seen_paths: set[Path] = set()
            for plugin_name in active_plugins:
                plugin_path = self.organizer_wrapper.get_plugin_path(plugin_name)
                if plugin_path:
                    p = Path(plugin_path).resolve()
                    if p not in seen_paths:
                        seen_paths.add(p)
                        target_plugins.append(p)
        
        if not target_plugins:
            return []
        
        reader = PluginReader(self.organizer_wrapper, active_plugins=active_plugins)
        asset_records = []
        
        # User picked "Body" or "Skin" in the M2M combo — map it to real signatures
        wanted_sigs = BOS_CATEGORIES.get(category, BOS_SIGNATURES)
        
        for plugin_path in target_plugins:
            try:
                seen_fids: set[str] = set()
                for rec in iter_records(plugin_path, reader=reader):
                    sig = rec.get("signature", "")
                    if sig in wanted_sigs:
                        form_id = rec.get("form_id", "")
                        
                        # Asset swap: user picked the category, we trust it.
                        # No body-part guessing — vanilla EIDs don't have those keywords.
                        if form_id and form_id not in seen_fids:
                            seen_fids.add(form_id)
                            # plugin_name = source mod (the pluginless asset provider)
                            # target_plugin = the victim plugin file
                            asset_records.append({
                                "form_id": form_id,
                                "target_form_id": form_id,
                                "signature": sig,
                                "editor_id": rec.get("editor_id", ""),
                                "name": rec.get("name", ""),
                                "plugin_name": source_mod_name,
                                "target_plugin": plugin_path.name,
                                "target_plugin_file": plugin_path.name,
                                "mod_name": "ASSET_SWAP",
                                "is_asset_swap": True,
                            })
                
                # Per-plugin heartbeat so user knows we ain't frozen
                self.log_info(
                    f"Asset scan: {plugin_path.name} — {len(asset_records)} hits so far",
                    MO2_LOG_DEBUG
                )
            except Exception:
                continue
        
        self.log_info(f"ASSET_MODE: Found {len(asset_records)} records total", MO2_LOG_INFO)
        return asset_records

    def scan_plugins(
        self, 
        plugin_files: List[Path], 
        mod_names: List[str],
        category: str,
        abort_flag: Optional[object] = None,
        progress_callback: Optional[callable] = None,
        active_plugins: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Scan plugins for BOS records. Returns filtered list."""
        
        # Handle pluginless asset mods in scan mode too
        if category in ("ASSET_SKIN", "ASSET_BODY", "Skin") and not plugin_files:
            self.log_info("ASSET_MODE: No plugins to scan, use M2M mode for asset swaps", MO2_LOG_INFO)
            return []
        self.log_info(f"BOS Processor: scanning {len(plugin_files)} plugins", MO2_LOG_INFO)
        
        wanted_sigs = BOS_SIGNATURES if category == "All" else BOS_CATEGORIES.get(category, BOS_SIGNATURES)
        
        all_records = []
        total_scanned = 0
        total_matched = 0
        
        reader = PluginReader(self.organizer_wrapper, active_plugins=active_plugins)
        
        for plugin_path, mod_name in zip(plugin_files, mod_names):
            if abort_flag and getattr(abort_flag, '_abort_scan', False):
                self.log_info("BOS Processor: scan aborted")
                return []
            scanned = 0
            matched = 0                                        
            try:
                for rec in iter_records(plugin_path, reader=reader):
                    scanned += 1
                    total_scanned += 1
                    
                    if rec.get("signature") in wanted_sigs:
                        matched += 1
                        total_matched += 1
                        
                        all_records.append({
                            "form_id": rec.get("form_id", ""),
                            "signature": rec.get("signature", ""),
                            "editor_id": rec.get("editor_id", ""),
                            "name": rec.get("name", ""),
                            "plugin_name": plugin_path.name,
                            "mod_name": mod_name,
                        })
                    
                    if progress_callback and total_scanned % 100 == 0:
                        progress_callback(total_scanned, len(plugin_files), f"Processing {plugin_path.name}")
                    
                    if scanned % 500 == 0:
                        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
                
                self.log_info(f"Plugin {plugin_path.name}: {scanned} records, {matched} matched", MO2_LOG_DEBUG)
                    
            except Exception as e:
                self.log_error(f"BOS Processor: failed on {plugin_path.name}: {e}")
                continue
        
        self.log_info(f"BOS Processor complete: {total_scanned} scanned, {total_matched} matched", MO2_LOG_INFO)
        return all_records

