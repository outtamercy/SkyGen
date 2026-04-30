# patch_gen.py – SkyPatcher unified naming fix (index-origin_plugin.ini for ALL)
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from collections import Counter

from ..utils.logger import LoggingMixin, SkyGenLogger
from ..core.constants import (
    MO2_LOG_CRITICAL, MO2_LOG_ERROR, MO2_LOG_WARNING, MO2_LOG_INFO,
    ERROR_MESSAGES, SUCCESS_MESSAGES,
    SKYPATCHER_INI_HEADER, SIGNATURE_TO_FILTER, FILTER_TO_ACTIONS, BLESSED_CORE_FILES
)
from ..src.organizer_wrapper import OrganizerWrapper
from ..utils.file_ops import FileOperationsManager
from ..extractors.plugin_extractor import PluginExtractor


class PatchAndConfigGenerationManager(LoggingMixin):
    """
    Front-door for SkyPatcher INI generation.
    All user feedback via `worker.log_*` callbacks – **no direct prints**.
    """

    def __init__(
        self,
        organizer_wrapper: OrganizerWrapper,
        file_operations_manager: FileOperationsManager,
        plugin_extractor: PluginExtractor,
        patch_settings: Any = None,
    ) -> None:
        super().__init__()
        self.organizer_wrapper = organizer_wrapper
        self.file_ops = file_operations_manager
        self.plugin_extractor = plugin_extractor
        self.patch_settings = patch_settings

    def generate_skypatcher_ini(
            self,
            extracted_data: Dict[str, Any],
            category: Optional[str],
            target_mod_plugin_name: str,
            source_mod_plugin_name: Optional[str],
            source_mod_display_name: Optional[str],
            source_mod_base_objects: Optional[Dict[str, Any]],
            all_exported_target_bases_by_formid: Dict[str, Any],
            dialog_instance: Any,
            output_folder_path: Path,
            generate_all_categories: bool,
            generate_modlist: bool,
            use_sentence_builder: bool = True,
            sp_filter_type: str = "",
            sp_action_type: str = "",
            sp_value_formid: str = "",
            sp_lmw_winners_only: bool = True,
        ) -> bool:
        worker = dialog_instance
        worker.log_info(f"Firing up the SkyPatcher forge for '{category or 'All'}'...")
        
        # Global mode means we're blasting across everything
        use_global_mode = target_mod_plugin_name in ["[GLOBAL_MODE]", "all_categories", ""]

        # Hard override: all-cats is always global, no matter what target string leaked in
        if generate_all_categories:
            use_global_mode = True
            target_mod_plugin_name = "[GLOBAL_MODE]"

        try:
            # Grab the sentence builder bits if the user filled 'em out
            sb_filter = sp_filter_type or getattr(self.patch_settings, 'sp_filter_type', '')
            sb_action = sp_action_type or getattr(self.patch_settings, 'sp_action_type', '')
            sb_value_raw = sp_value_formid or getattr(self.patch_settings, 'sp_value_formid', '')
            sb_value = sb_value_raw.split()[0] if sb_value_raw else ''
            sb_value_padded = sb_value.zfill(8).upper() if sb_value else sb_value
            
            # LMW flag now passed explicitly
            lmw_winners_only = sp_lmw_winners_only
            
            has_sentence_builder = bool(sb_filter and sb_action and sb_value)

            # Group records by where they were born (origin) vs where we found them (file_name)
            records_by_pair: Dict[Tuple[str, str], Tuple[str, List[str]]] = {}
            
            for form_id_snake, target_rec in all_exported_target_bases_by_formid.items():
                sig = target_rec.get("signature", "UNKNOWN")
                
                # Skip strays if running single-category mode
                if not generate_all_categories and category and sig.upper() != category.upper():
                    continue

                # Trust DE — it already resolved this from FormID prefix
                origin_plugin = target_rec.get("origin_plugin", target_rec.get("file_name", "Unknown"))
                if not origin_plugin or origin_plugin == "Unknown":
                    continue

                # Strip the load order byte - SkyPatcher wants local FormIDs only
                # Format local FormID (last 6 digits of full ID, or pad short IDs)
                raw_form = str(target_rec.get('form_id', '00000000'))
                if len(raw_form) > 6:
                    local_id = raw_form[-6:].upper()
                else:
                    local_id = raw_form.zfill(6).upper()
                
                master_plugin = target_rec.get("master_plugin", "Unknown")
                file_name = target_rec.get("file_name", "Unknown")
                header_plugin = master_plugin if use_global_mode else target_mod_plugin_name

                lines: List[str] = []
                
                # --- MODE 3: CAT GEN ---
                if generate_all_categories:
                    auto_filter = target_rec.get(
                        "sp_filter",
                        SIGNATURE_TO_FILTER.get(sig.upper(), "filterByKeywords")
                    )
                    auto_action = FILTER_TO_ACTIONS.get(auto_filter, ["addKeywords"])[0]
                    keyword_value = target_rec.get("keyword_value")
                    if keyword_value:
                        base_line = f"{auto_filter}={origin_plugin}|{local_id}"
                        base_line += f":{auto_action}={keyword_value}"
                        lines.append(base_line)
                        lines.append("")
                    else:
                        continue

                # --- MODE 2: ML GEN ---
                elif generate_modlist:
                    # auto-filter from record type — SB is disabled in ML mode so can't rely on it
                    auto_filter = target_rec.get(
                        "sp_filter",
                        SIGNATURE_TO_FILTER.get(sig.upper(), "filterByKeywords")
                    )
                    auto_action = FILTER_TO_ACTIONS.get(auto_filter, ["addKeywords"])[0]
                    keyword_value = target_rec.get("keyword_value")
                
                    if keyword_value:
                        lines.append(
                            f"{auto_filter}={origin_plugin}|{local_id}:{auto_action}={keyword_value}"
                        )
                        lines.append("")
                    else:
                        continue

                # --- SHIELD: Single mode does NOT touch records_by_pair ---
                else:
                    continue

                # Only mass-gen records reach here
                key = (origin_plugin, file_name)
                if key not in records_by_pair:
                    records_by_pair[key] = (master_plugin, [])
                records_by_pair[key][1].extend(lines)

            # SkyPatcher dumps everything in its SKSE corner
            folder_name = "All" if generate_all_categories else (category.strip('_ ') if category else "All")
            skypatcher_dir = output_folder_path / "SKSE" / "Plugins" / "SkyPatcher" / folder_name
            skypatcher_dir.mkdir(parents=True, exist_ok=True)

            # Trust the flags — single mode can have multi-origin records (DLC records in base ESM)
            is_mass_gen = generate_all_categories or generate_modlist
            is_single_mode = not is_mass_gen
            
            if is_single_mode:
                all_lines = []
                for form_id_snake, target_rec in all_exported_target_bases_by_formid.items():
                    sig = target_rec.get("signature", "UNKNOWN")
                    if category and sig.upper() != category.upper():
                        continue
                    
                    # DE already resolved origin — just write it
                    origin = target_rec.get("origin_plugin", "Unknown")
                    raw_form = str(target_rec.get('form_id', '00000000'))
                    local_id = raw_form[-6:].upper() if len(raw_form) >= 6 else raw_form.zfill(6).upper()
                    
                    # --- MODE 1: SINGLE ---
                    if use_sentence_builder and sb_filter and sb_action and sb_value:
                        line = f"{sb_filter}={origin}|{local_id}:{sb_action}={sb_value}"
                    
                    all_lines.append(line)
                    all_lines.append("")
                
                header = [
                    SKYPATCHER_INI_HEADER,
                    f"; Terrigenesis is live",
                    f"; Target: {target_mod_plugin_name}",
                    f"; Source: {source_mod_plugin_name or 'None'}",
                    "",
                ]
                out_file = skypatcher_dir / f"{target_mod_plugin_name}.ini"
                self.file_ops.save_text_file(out_file, "\n".join(header + all_lines))
                worker.log_info(f"Single-mode INI forged: {out_file.name}")
                return True

            # Multi-mode: Frankie-style per-origin-plugin INIs
            active_list = self.organizer_wrapper.active_plugins
            
            for (origin_plugin, file_name), (master_plugin, lines) in records_by_pair.items():
                header = [
                    SKYPATCHER_INI_HEADER,
                    f"; Terrigenesis is live",
                    f"; Target: {target_mod_plugin_name}",
                    f"; Source: {source_mod_plugin_name or 'None'}",
                    f"; Master: {master_plugin}",
                    f"; Origin: {origin_plugin}",
                    ";",
                    "",
                ]

                try:
                    origin_index = active_list.index(origin_plugin)
                except ValueError:
                    worker.log_warning(f"{origin_plugin} not in the lineup - parking at 999")
                    origin_index = 999

                content = "\n".join(header + lines)
                filename = f"{origin_index:02X}-{origin_plugin}.ini"
                out_file = skypatcher_dir / filename
                self.file_ops.save_text_file(out_file, content)
                worker.log_info(f"Hammered out: {filename}")
                
            worker.log_info(f"Forge complete. Total INIs: {len(records_by_pair)}")
            return True

        except Exception as exc:
            worker.log_critical(f"Forge exploded: {exc}", exc_info=True)
            return False

