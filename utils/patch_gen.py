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
        
        use_global_mode = target_mod_plugin_name in ["[GLOBAL_MODE]", "all_categories", ""]

        if generate_all_categories:
            use_global_mode = True
            target_mod_plugin_name = "[GLOBAL_MODE]"

        try:
            sb_filter = sp_filter_type or getattr(self.patch_settings, 'sp_filter_type', '')
            sb_action = sp_action_type or getattr(self.patch_settings, 'sp_action_type', '')
            sb_value_raw = sp_value_formid or getattr(self.patch_settings, 'sp_value_formid', '')
            sb_value = sb_value_raw.split()[0] if sb_value_raw else ''
            
            has_sentence_builder = bool(sb_filter and sb_action and sb_value)

            records_by_pair: Dict[Tuple[str, str], Tuple[str, List[str]]] = {}
            
            for form_id_snake, target_rec in all_exported_target_bases_by_formid.items():
                sig = target_rec.get("signature", "UNKNOWN")
                
                if not generate_all_categories and category and sig.upper() != category.upper():
                    continue

                origin_plugin = target_rec.get("origin_plugin", target_rec.get("file_name", "Unknown"))
                if not origin_plugin or origin_plugin == "Unknown":
                    continue

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

                else:
                    continue

                key = (origin_plugin, file_name)
                if key not in records_by_pair:
                    records_by_pair[key] = (master_plugin, [])
                records_by_pair[key][1].extend(lines)

            # quick peek — what cats actually survived the trip to the writer
            seen_cats = sorted({rec.get("signature", "UNKN") for rec in all_exported_target_bases_by_formid.values()})
            worker.log_info(f"PG Cat Gen input categories: {seen_cats}")

            folder_name = "All" if generate_all_categories else (category.strip('_ ') if category else "All")
            skypatcher_dir = output_folder_path / "SKSE" / "Plugins" / "SkyPatcher" / folder_name
            skypatcher_dir.mkdir(parents=True, exist_ok=True)

            is_mass_gen = generate_all_categories or generate_modlist
            is_single_mode = not is_mass_gen
            
            if is_single_mode:
                all_lines = []
                for form_id_snake in sorted(all_exported_target_bases_by_formid.keys(), key=lambda x: int(x, 16)):
                    target_rec = all_exported_target_bases_by_formid[form_id_snake]
                    sig = target_rec.get("signature", "UNKNOWN")
                    if category and sig.upper() != category.upper():
                        continue
                    
                    origin = target_rec.get("origin_plugin", "Unknown")
                    raw_form = str(target_rec.get('form_id', '00000000'))
                    local_id = raw_form[-6:].upper() if len(raw_form) >= 6 else raw_form.zfill(6).upper()
                    
                    # --- MODE 1: SINGLE ---
                    loom_keyword = target_rec.get("keyword_value")
                    if loom_keyword:
                        auto_filter = target_rec.get("sp_filter", sb_filter or "filterByKeywords")
                        auto_action = target_rec.get("sp_action", sb_action or "addKeywords")
                        line = f"{auto_filter}={origin}|{local_id}:{auto_action}={loom_keyword}"
                    elif use_sentence_builder and sb_filter and sb_action and sb_value:
                        line = f"{sb_filter}={origin}|{local_id}:{sb_action}={sb_value}"
                    else:
                        continue
                    
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

