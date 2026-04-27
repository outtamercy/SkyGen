from pathlib import Path
from typing import List, Dict, Any, Tuple
from ..core.constants import BASE_GAME_PLUGINS

class BosWriter:
    """Writes BOS INI files in pipe-delimited [Forms] format."""
    
    @staticmethod
    def write_ini(records: List[Dict[str, Any]], output_path: Path, 
                  mode: str = "scanned", target_mod: str = "",
                  xyz: tuple[str, str, str] = ("0.0", "0.0", "0.0"),
                  chance: int = 100) -> Tuple[bool, str]:
        """Write BOS INI file."""
        try:
            lines = ["[Forms]", ""]
            valid_records = 0
            
            # Parse XYZ
            x, y, z = xyz
            has_offset = (x.strip() != "0.0" or y.strip() != "0.0" or z.strip() != "0.0")
            
            for rec in records:
                form_id = rec.get("formId", rec.get("form_id", "")).strip()
                if not form_id:
                    continue
                
                target_form_id = rec.get("target_form_id", "").strip()
                is_asset_swap = rec.get("is_asset_swap", False)
                
                # M2M uses different FIDs; Scan/FID uses same FID
                if mode == "modswap" and target_form_id:
                    orig_fid = target_form_id[-6:].upper() if len(target_form_id) >= 6 else target_form_id.upper()
                    swap_fid = form_id[-6:].upper() if len(form_id) >= 6 else form_id.upper()
                    target_plugin = rec.get("target_plugin", target_mod).strip()
                    source_plugin = rec.get("plugin_name", "Unknown").strip()
                else:
                    short_id = form_id[-6:].upper() if len(form_id) >= 6 else form_id.upper()
                    orig_fid = short_id
                    swap_fid = short_id
                    raw_target = rec.get("target_plugin") or target_mod
                    target_plugin = (raw_target or "Skyrim.esm").strip()
                    # For asset swaps, source is the mod folder (not a plugin)
                    raw_source = rec.get("plugin_name", "Unknown")
                    source_plugin = raw_source.strip()
                
                # Build pipe parts
                orig_part = f"0x{orig_fid}~{target_plugin}"
                swap_part = f"0x{swap_fid}~{source_plugin}"
                
                # BOS parser is picky about pipe count.
                # 2 segments = orig|swap (chance defaults 100)
                # 4 segments = orig|swap|props|chance
                # 3 segments = parser reads chance as a broken property string and drops it silently
                if has_offset:
                    props = f"posR({x},{y},{z})"
                    lines.append(f"{orig_part}|{swap_part}|{props}|{chance}")
                elif chance != 100:
                    lines.append(f"{orig_part}|{swap_part}|NONE|{chance}")
                else:
                    lines.append(f"{orig_part}|{swap_part}")
                
                valid_records += 1
            
            if valid_records == 0:
                return False, f"No valid records to write to {output_path.name}"
            
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("\n".join(lines), encoding="utf-8")
            
            return True, f"BOS INI written: {output_path} ({valid_records} records)"
            
        except Exception as e:
            return False, f"BOS write failed: {e}"