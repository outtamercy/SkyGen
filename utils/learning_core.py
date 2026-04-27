# The brain that remembers what Frankie found so we don't sniff the same junk twice

import hashlib, time, os
from pathlib import Path
from typing import Dict, Optional, List, Set, Any
import json
from dataclasses import dataclass, asdict, field
from enum import Enum
from ..core.constants import (
    SKYPATCHER_SUPPORTED_RECORD_TYPES,
    BOS_SUPPORTED_RECORD_TYPES,
    GLOBAL_FRAMEWORK_SIGNATURES,
    BLACKLIST_AUTHORS,
    FRAMEWORK_SCENTS, FRAMEWORK_LOGIC_SIGNATURES,
)
from ..utils.sigsnoop import PluginDNA
from ..utils.logger import LoggingMixin, MO2_LOG_DEBUG, MO2_LOG_INFO, MO2_LOG_WARNING

class Layer(Enum):
    GLOBAL = "global"      # Hard locked, neither can patch
    BOS = "bos"            # Base Object Swapper only
    SP = "sp"              # SkyPatcher only  
    HYBRID = "hybrid"      # Both could theoretically patch

@dataclass
class Verdict:
    layer: Layer
    score: int              # 0-100 framework likelihood
    confidence: str         # high, medium, low
    hard_locked: bool       # True for GLOBAL (user can't override)
    dominant_sigs: List[str]
    reason: str
    cached: bool = False    # Was this from cache or fresh?

@dataclass
class KnowledgeEntry:
    """What we stash in the INI about each plugin"""
    hash: str
    size: int
    mtime: float
    layer: str
    score: int
    confidence: str
    dominant_sigs: str      # comma-separated for INI storage
    reason: str
    scan_count: int = 1
    last_seen: float = field(default_factory=time.time)
    author_pattern: str = ""  # "framework_heavy", "content_heavy", "mixed"
    
    def is_stale(self, current_size: int, current_mtime: float, current_hash: str) -> bool:
        """Check if plugin changed enough to warrant re-sniff"""
        # Hash changed = definitely rescan
        if current_hash != self.hash:
            return True
        # Size jump > 20% = probably added/removed content
        if current_size > 0:
            size_delta = abs(current_size - self.size) / current_size
            if size_delta > 0.20:
                return True
        # Newer mtime = touched by update
        if current_mtime > self.mtime:
            return True
        return False

class LearningCore(LoggingMixin):
    """
    Pre-processor that scores plugins and caches the verdict.
    Sits between Frankie and the Snoop - keeps Snoop clean.
    """
    
    # Signature scoring weights
    GLOBAL_SIGS = GLOBAL_FRAMEWORK_SIGNATURES
    BOS_SIGS = set(BOS_SUPPORTED_RECORD_TYPES)
    SP_SIGS = set(SKYPATCHER_SUPPORTED_RECORD_TYPES)
    
    # Folder scent bonuses (framework detection)
    SCENT_PENALTIES = {
        'SKSE': 20, 'DynDOLOD': 20, 'Framework': 20, 'Engine': 15,
        'Menu': 15, 'xEdit': 15, 'Synthesis': 15, 'Patch': 10, 'Fix': 10
    }
    
    def __init__(self, plugin_path: Path, profile_name: str):
        LoggingMixin.__init__(self)
        self.plugin_path = plugin_path
        self.data_dir = plugin_path / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.knowledge_file = self.data_dir / f"sg_knowledge_{profile_name}.jsonl"
        self.cache: Dict[str, KnowledgeEntry] = {}
        self._dirty_entries: Set[str] = set()
        self.author_reputation: Dict[str, int] = {}
        self._stats = {"hits": 0, "stales": 0, "fresh": 0, "globals": 0}
        
        self._load_knowledge()
        self.log_info(f"LearningCore booted with {len(self.cache)} cached verdicts")
    
    def _load_knowledge(self) -> None:
        """Slurp JSONL line by line. Last-write-wins for duplicate keys."""
        if not self.knowledge_file.exists():
            return
        
        try:
            with open(self.knowledge_file, 'r', encoding='utf-8') as f:
                for line_num, raw_line in enumerate(f, 1):
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        data = json.loads(raw_line)
                        plugin_key = data.pop('plugin_name', '').lower()
                        if not plugin_key:
                            continue
                        # Rebuild entry from dict
                        entry = KnowledgeEntry(**data)
                        self.cache[plugin_key] = entry
                    except Exception as e:
                        self.log_debug(f"Corrupt JSONL line {line_num}: {e}")
        except Exception as e:
            self.log_warning(f"Failed to load knowledge file: {e}")
        
        self.log_info(f"LC cache warmed: {len(self.cache)} entries from JSONL")

    def _save_knowledge(self) -> None:
        """Append-only flush. No temp files, no rewrites."""
        if not self._dirty_entries:
            return
        
        self.knowledge_file.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(self.knowledge_file, 'a', encoding='utf-8') as f:
                for plugin_key in sorted(self._dirty_entries):
                    entry = self.cache.get(plugin_key)
                    if not entry:
                        continue
                    payload = asdict(entry)
                    payload['plugin_name'] = plugin_key
                    f.write(json.dumps(payload, ensure_ascii=False) + '\n')
            
            self._dirty_entries.clear()
            self.log_debug(f"LC appended entries")
            
        except Exception as e:
            self.log_error(f"Knowledge append failed (keeping in RAM): {e}")
    
    def _calculate_score(self, dna: PluginDNA) -> tuple[int, List[str], str]:
        """
        Run the math: 0 = pure content, 100 = pure framework
        Returns (score, dominant_sigs, reason)
        """
        score = 0
        reasons = []
        sigs = set(dna.signatures)
        
        # --- Signature Analysis ---
        global_hits = sigs.intersection(self.GLOBAL_SIGS)
        bos_hits = sigs.intersection(self.BOS_SIGS)
        sp_hits = sigs.intersection(self.SP_SIGS)

        # --- Archive Mass Check (Asset Anchor) ---
        # Massive BSA + few records = Content mod, NOT framework
        # Prevents blacklisting Project Clarity types
        bsa_size = getattr(dna, 'bsa_size', 0)
        record_count = len(sigs)
        
        if bsa_size > (100 * 1024 * 1024) and record_count < 50:
            score = 0  # Zero framework likelihood
            reasons.append(f"Asset anchor: {bsa_size/(1024*1024):.0f}MB BSA, {record_count} records")
            # Fall through to normal layer assignment - don't return early
            #         
        # Heavy global = framework
        if len(global_hits) > 2:
            score += len(global_hits) * 8
            reasons.append(f"Global signatures: {','.join(global_hits)}")
        
        # Masters only = utility
        if len(sigs) == 0 and len(dna.masters) > 0:
            score += 25
            reasons.append("Masters-only plugin")
        
        # Ratio check (logic vs content)
        if dna.logic_to_content_ratio > 2.0:
            score += 30
            reasons.append(f"High logic ratio ({dna.logic_to_content_ratio:.2f})")
        elif dna.logic_to_content_ratio > 1.0:
            score += 15
            reasons.append("Moderate scripts")
        
        # --- Folder Scents ---
        scent_bonus = 0
        for scent, penalty in self.SCENT_PENALTIES.items():
            if scent in dna.folder_scents:
                scent_bonus += penalty
                reasons.append(f"Scent: {scent}")
        
        score += min(scent_bonus, 40)  # Cap scent penalty at 40
        
        # --- Author Reputation ---
        author_lower = (dna.author or "unknown").lower()
        if author_lower in self.author_reputation:
            rep_score = self.author_reputation[author_lower]
            # Blend current calc with historical (70% current, 30% rep)
            score = int(score * 0.7 + rep_score * 0.3)
            if rep_score > 70:
                reasons.append(f"Author rep: {dna.author}")
        
        # Determine dominant signatures
        all_hits = list(global_hits) + list(bos_hits) + list(sp_hits)
        dominant = all_hits[:3]  # Top 3
        
        # Clamp
        score = max(0, min(100, score))
        
        reason_str = "; ".join(reasons) if reasons else "Content plugin"
        return score, dominant, reason_str
    
    def _assign_layer(self, score: int, dna: PluginDNA) -> tuple[Layer, bool]:
        """
        Decide which silo(s) this belongs to.
        Returns (layer, hard_locked)
        """
        sigs = set(dna.signatures)
        
        # GLOBAL: High framework score or pure utility
        if score >= 85:
            return Layer.GLOBAL, True  # Hard locked
        
        # Check what content it actually has
        has_bos = bool(sigs.intersection(self.BOS_SIGS))
        has_sp = bool(sigs.intersection(self.SP_SIGS))
        
        if has_bos and not has_sp:
            return Layer.BOS, False
        elif has_sp and not has_bos:
            return Layer.SP, False
        elif has_bos and has_sp:
            return Layer.HYBRID, False
        
        # No recognizable signatures = assume GLOBAL (safe default)
        return Layer.GLOBAL, True
    
    def get_verdict(self, plugin_name: str, dna: PluginDNA, 
                    file_stat: os.stat_result) -> Verdict:
        """
        Main entry point. Returns verdict, using cache if fresh.
        """
        plugin_key = plugin_name.lower()
        current_hash = dna.file_hash or hashlib.md5(str(file_stat.st_mtime).encode()).hexdigest()[:16]
        
        # Check cache first
        if plugin_key in self.cache:
            entry = self.cache[plugin_key]
            
            if not entry.is_stale(file_stat.st_size, file_stat.st_mtime, current_hash):
                # Cache hit - fresh data
                layer = Layer(entry.layer)
                hard = layer == Layer.GLOBAL and entry.confidence == 'high'
                self._stats["hits"] += 1
                return Verdict(
                    layer=layer,
                    score=entry.score,
                    confidence=entry.confidence,
                    hard_locked=hard,
                    dominant_sigs=entry.dominant_sigs.split(',') if entry.dominant_sigs else [],
                    reason=entry.reason,
                    cached=True
                )
            else:
                self._stats["stales"] += 1
                self.log_debug(f"Knowledge stale: {plugin_name} changed, re-sniffing")
        
        # Fresh calculation
        score, dominant, reason = self._calculate_score(dna)
        layer, hard_locked = self._assign_layer(score, dna)
        
        # Confidence based on score clarity and data completeness
        if score >= 90 or score <= 10:
            confidence = 'high'
        elif score >= 70 or score <= 30:
            confidence = 'medium'
        else:
            confidence = 'low'
        
        # Update author reputation for future scoring
        author = (dna.author or "unknown").lower()
        if author != "unknown":
            if author in self.author_reputation:
                # Rolling average
                old = self.author_reputation[author]
                self.author_reputation[author] = (old + score) // 2
            else:
                self.author_reputation[author] = score
        
        # Store for next time
        self.cache[plugin_key] = KnowledgeEntry(
            hash=current_hash,
            size=file_stat.st_size,
            mtime=file_stat.st_mtime,
            layer=layer.value,
            score=score,
            confidence=confidence,
            dominant_sigs=','.join(dominant),
            reason=reason,
            scan_count=(self.cache[plugin_key].scan_count + 1) if plugin_key in self.cache else 1,
            author_pattern="framework" if score > 70 else "content" if score < 30 else "mixed"
        )

        self._dirty_entries.add(plugin_key)
        
        # Flush periodically (every 10 new entries or on high-confidence global)
        if len(self.cache) % 10 == 0 or (layer == Layer.GLOBAL and confidence == 'high'):
            self._save_knowledge()
        
            self._stats["fresh"] += 1
        if layer == Layer.GLOBAL:
            self._stats["globals"] += 1
        
        return Verdict(
            layer=layer,
            score=score,
            confidence=confidence,
            hard_locked=hard_locked,
            dominant_sigs=dominant,
            reason=reason,
            cached=False
        )
        

    def force_re_save(self) -> None:
        """Compaction rewrite at shutdown. Direct write — no temp file rename dance."""
        if not self.cache:
            return
        
        self.knowledge_file.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(self.knowledge_file, 'w', encoding='utf-8') as f:
                for plugin_key, entry in sorted(self.cache.items()):
                    payload = asdict(entry)
                    payload['plugin_name'] = plugin_key
                    f.write(json.dumps(payload, ensure_ascii=False) + '\n')
            
            # Compaction consumed all dirty entries
            self._dirty_entries.clear()
            
        except Exception as e:
            self.log_error(f"Knowledge compaction failed: {e}")
        
        total = self._stats["hits"] + self._stats["fresh"]
        self.log_info(
            f"LC Summary: {self._stats['hits']} cached + {self._stats['fresh']} fresh = {total} "
            f"({self._stats['globals']} global, {self._stats['stales']} stale)"
        )