# models.py – Dataclasses for config management
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from pathlib import Path


@dataclass
class PatchGenerationOptions:
    # --- SP SkyPatcher ---
    generate_modlist: bool = False
    target_mod: str = ""
    source_mod: str = ""
    category: str = ""
    keywords: str = ""
    skypatcher_output_folder: str = ""
    generate_all_categories: bool = False
    cache_mode: str = "speed"
    sp_filter_type: str = ""
    sp_action_type: str = ""
    sp_value_formid: str = ""
    sp_lmw_winners_only: bool = True
    sp_use_sentence_builder: bool = True

    # --- BOS (legacy fields kept for compat) ---
    bos_original_id: str = ""
    bos_swap_id: str = ""
    bos_cells: str = ""
    bos_chance_type: str = ""
    bos_chance: int = 0
    bos_output_folder: str = ""
    broad_category_swap: bool = False
    bos_scan_all: bool = False
    bos_target_mod: str = ""
    bos_source_mod: str = ""
    bos_xyz: str = "0.0,0.0,0.0"
    bos_formids: str = "[]"

    # --- M2M ---
    m2m_category: str = "All"
    m2m_chance: int = 100

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ApplicationConfig:
    game_version: str = "SkyrimSE"
    output_type: str = "SkyPatcher INI"
    debug_logging: bool = False
    traceback_logging: bool = False
    selected_theme: str = "Default"
    remember_window_size_pos: bool = True
    remember_splitter_state: bool = True
    patch_settings: PatchGenerationOptions = field(default_factory=PatchGenerationOptions)
    dev_settings_hidden: bool = False
    loom_enabled: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)