import struct
from typing import Dict, Optional, Any
from ..utils.logger import LoggingMixin

class Loom(LoggingMixin):
    """Deterministic keyword weaver — reads record DNA, emits the right keyword."""

    # WEAP DNAM offset 0x0C = uint16 animation type
    ANIM_TO_KEYWORD: Dict[int, str] = {
        0: "WKF_WeaponTypeHandToHand",  # unarmed / claw
        1: "WKF_WeaponTypeSword",
        2: "WKF_WeaponTypeDagger",
        3: "WKF_WeaponTypeWarAxe",
        4: "WKF_WeaponTypeMace",
        5: "WKF_WeaponTypeGreatsword",
        6: "WKF_WeaponTypeBattleaxe",
        7: "WKF_WeaponTypeBow",
        8: "WKF_WeaponTypeStaff",
        9: "WKF_WeaponTypeCrossbow",
        10: "WKF_WeaponTypePickaxe",   # mining tools
        11: "WKF_WeaponTypeWoodAxe",   # hatchets
    }

    # ARMO BODT/BOD2 slot bits → human slot name
    SLOT_BITS: Dict[int, str] = {
        0x00000001: "Helmet",
        0x00000002: "Helmet",
        0x00000004: "Cuirass",
        0x00000008: "Gauntlets",
        0x00000010: "Gauntlets",
        0x00000080: "Boots",
        0x00000100: "Boots",
        0x00000200: "Shield",
        0x00001000: "Helmet",
    }

    # KWDA local formID (last 6 hex digits) → material name
    MATERIAL_FORMIDS: Dict[str, str] = {
        "06BBE3": "Iron",
        "06BBDB": "Leather",
        "06BBDD": "Hide",
        "06BBDE": "Scaled",
        "06BBDF": "Studded",
        "06BBE6": "Steel",
        "06BBE2": "Imperial",
        "06BBE0": "Imperial",
        "06BBE1": "StudImperial",
        "06BBD7": "Dwarven",
        "06BBE5": "Orcish",
        "06BBD9": "Elven",
        "06BBDA": "Elven",
        "06BBDC": "Glass",
        "06BBD8": "Ebony",
        "06BBD5": "Dragon",
        "06BBD6": "Dragon",
        "024107": "Stalhrim",
        "024106": "Stalhrim",
        "024104": "Nordic",
        "024105": "Nordic",
        "024100": "Bonemold",
        "024101": "Bonemold",
        "024102": "Chitin",
        "024103": "Chitin",
    }

    # NPC RNAM (race formID) → broad actor type
    # These are Skyrim.esm base race formIDs — adjust if your load order shifts them
    RACE_TO_KEYWORD: Dict[str, str] = {
        "013745": "ActorTypeNPC",      # NordRace
        "013746": "ActorTypeNPC",      # RedguardRace
        "013747": "ActorTypeNPC",      # BretonRace
        "013748": "ActorTypeNPC",      # ImperialRace
        "013749": "ActorTypeElf",      # DunmerRace
        "01374A": "ActorTypeElf",      # AltmerRace
        "01374B": "ActorTypeElf",      # BosmerRace
        "01374C": "ActorTypeOrc",      # OrsimerRace
        "01374D": "ActorTypeKhajiit",  # KhajiitRace
        "01374E": "ActorTypeArgonian",  # ArgonianRace
        "01374F": "ActorTypeNPC",      # NordRaceVampire
        "013750": "ActorTypeNPC",      # RedguardRaceVampire
        "013751": "ActorTypeNPC",      # BretonRaceVampire
        "013752": "ActorTypeNPC",      # ImperialRaceVampire
        "013753": "ActorTypeElf",      # DunmerRaceVampire
        "013754": "ActorTypeElf",      # AltmerRaceVampire
        "013755": "ActorTypeElf",      # BosmerRaceVampire
        "013756": "ActorTypeOrc",      # OrsimerRaceVampire
        "013757": "ActorTypeKhajiit",  # KhajiitRaceVampire
        "013758": "ActorTypeArgonian",  # ArgonianRaceVampire
        "08803D": "ActorTypeNPC",      # ElderRace
        "08803E": "ActorTypeNPC",      # ElderRaceVampire
        "088440": "ActorTypeNPC",      # ChildRace
        "088445": "ActorTypeNPC",      # SnowElfRace
    }

    # DLC origin gates
    ORIGIN_GATES: Dict[str, str] = {
        "Bonemold": "Dragonborn",
        "Chitin": "Dragonborn",
        "Nordic": "Dragonborn",
        "Stalhrim": "Dragonborn",
    }

    def resolve(self, record: Dict[str, Any]) -> Optional[str]:
        """Main entry — pick keyword or return None (safe skip)."""
        sig = record.get("signature", "").upper()
        origin = record.get("origin_plugin", "Unknown")

        if sig == "WEAP":
            return self._gated(self._resolve_weapon(record), origin)
        elif sig in ("ARMO", "ARMA"):
            return self._gated(self._resolve_armor(record), origin)
        elif sig == "NPC_":
            return self._resolve_npc(record)
        elif sig == "RACE":
            return self._resolve_race(record)
        elif sig == "AMMO":
            return "VendorItemAmmo"
        elif sig == "ALCH":
            return self._edid_fallback(record, "VendorItemPotion")
        elif sig == "BOOK":
            self.log_info(f"BOOK_EDID_RAW: '{record.get('EDID', 'MISSING')}'")
            return self._edid_fallback(record, "IsBook")
        elif sig == "CONT":
            return self._edid_fallback(record, "IsChest")
        elif sig == "LIGH":
            return self._edid_fallback(record, "IsLantern")
        elif sig == "MISC":
            return self._edid_fallback(record, "VendorItemGem")
        elif sig == "INGR":
            return "IsIngredient"
        elif sig == "KEYM":
            return "IsKey"
        elif sig == "FURN":
            return self._edid_fallback(record, "IsWorkbench")
        elif sig == "SPEL":
            return self._resolve_spell(record)
        elif sig == "FLST":
            return "ListTypeLoot"
        elif sig == "HAIR":
            return "IsHair"
        elif sig == "HDPT":
            return "IsHeadPart"
        elif sig == "LVLI":
            return "VendorItemList"
        elif sig == "LVLC":
            return "ActorTypeList"
        # these four were falling through to None — now they get EDID love too
        elif sig == "FLOR":
            return self._edid_fallback(record, None)
        elif sig == "TREE":
            return self._edid_fallback(record, "IsTree")
        elif sig == "SCRL":
            return self._edid_fallback(record, "IsScroll")
        elif sig == "SLGM":
            return self._edid_fallback(record, None)
        return None

    def _gated(self, keyword: Optional[str], origin: str) -> Optional[str]:
        """Reject keywords that don't belong to this origin plugin."""
        if not keyword:
            return None
        for material, required in self.ORIGIN_GATES.items():
            if material in keyword and required not in origin:
                return None
        return keyword

    def _resolve_weapon(self, record: Dict[str, Any]) -> Optional[str]:
        """Pull animation type from DNAM raw bytes."""
        dnam = record.get("DNAM", b"")
        if len(dnam) < 14:
            return None
        anim_type = struct.unpack("<H", dnam[12:14])[0]
        return self.ANIM_TO_KEYWORD.get(anim_type)

    def _resolve_armor(self, record: Dict[str, Any]) -> Optional[str]:
        """Slot + material from BODT/BOD2 and KWDA."""
        bodt = record.get("BODT", b"")
        if len(bodt) < 4:
            bodt = record.get("BOD2", b"")
        if len(bodt) < 4:
            return None

        slots_raw = struct.unpack("<I", bodt[:4])[0]
        slot_name = None
        for bit, name in self.SLOT_BITS.items():
            if slots_raw & bit:
                slot_name = name
                break
        if not slot_name:
            return None

        kwda = record.get("KWDA", [])
        material = None
        for fid in kwda:
            local_fid = str(fid).zfill(8)[2:]
            if local_fid in self.MATERIAL_FORMIDS:
                material = self.MATERIAL_FORMIDS[local_fid]
                break

        # If we got a slot but no material, emit slot-only so the record isn't lost
        if material:
            return f"ARKF_{slot_name}{material}"
        return f"ARKF_{slot_name}"

    def _resolve_npc(self, record: Dict[str, Any]) -> Optional[str]:
        """RNAM race formID → actor type. Fallback to generic NPC."""
        rnam = record.get("RNAM", b"")
        if isinstance(rnam, bytes) and len(rnam) >= 4:
            # Unpack 4-byte formID, format as 6-digit hex (strip load-order byte)
            form_id_raw = struct.unpack("<I", rnam[:4])[0]
            local_fid = f"{form_id_raw:06X}"[-6:]
            if local_fid in self.RACE_TO_KEYWORD:
                return self.RACE_TO_KEYWORD[local_fid]
        elif isinstance(rnam, str):
            clean = rnam.replace('"', '').replace("'", "").upper().zfill(6)[-6:]
            if clean in self.RACE_TO_KEYWORD:
                return self.RACE_TO_KEYWORD[clean]
        return "ActorTypeNPC"

    def _resolve_race(self, record: Dict[str, Any]) -> Optional[str]:
        """MODL skeleton path → RKF keyword."""
        modl = record.get("MODL", "").lower()
        if "skeletonbeast" in modl:
            return "RKF_ActorTypeBeastHumanoid"
        if "bear" in modl:
            return "RKF_ActorTypeBear"
        if "chaurus" in modl:
            return "RKF_ActorTypeChaurus"
        if "deer" in modl or "elk" in modl:
            return "RKF_ActorTypeDeer"
        if "dog" in modl:
            return "RKF_ActorTypeDog"
        if "draugr" in modl:
            return "RKF_ActorTypeDraugr"
        if "falmer" in modl:
            return "RKF_ActorTypeFalmer"
        if "giant" in modl:
            return "RKF_ActorTypeGiant"
        if "goat" in modl:
            return "RKF_ActorTypeGoat"
        if "horse" in modl:
            return "RKF_ActorTypeHorse"
        if "horker" in modl:
            return "RKF_ActorTypeHorker"
        if "mammoth" in modl:
            return "RKF_ActorTypeMammoth"
        if "mudcrab" in modl:
            return "RKF_ActorTypeMudCrab"
        if "sabrecat" in modl or "sabre cat" in modl:
            return "RKF_ActorTypeSabreCat"
        if "skeever" in modl:
            return "RKF_ActorTypeSkeever"
        if "spriggan" in modl:
            return "RKF_ActorTypeSpriggan"
        if "troll" in modl:
            return "RKF_ActorTypeTroll"
        if "wolf" in modl and "fox" not in modl:
            return "RKF_ActorTypeWolf"
        if "fox" in modl:
            return "RKF_ActorTypeFox"
        if "rabbit" in modl or "hare" in modl:
            return "RKF_ActorTypeRabbit"
        if "chicken" in modl:
            return "RKF_ActorTypeChicken"
        if "cow" in modl:
            return "RKF_ActorTypeCow"
        if "dragon" in modl:
            return "RKF_ActorTypeDragon"
        if "dwemer" in modl or "dwarven" in modl or "centurion" in modl:
            return "RKF_ActorTypeCenturionDwarven"
        if "sphere" in modl:
            return "RKF_ActorTypeSphereDwarven"
        if "spider" in modl and "dwarven" in modl:
            return "RKF_ActorTypeSpiderDwarven"
        if "atronach" in modl or "flame" in modl:
            return "RKF_ActorTypeFireAtronach"
        if "frost" in modl and "atronach" in modl:
            return "RKF_ActorTypeFrostAtronach"
        if "storm" in modl and "atronach" in modl:
            return "RKF_ActorTypeStormAtronach"
        if "witchlight" in modl:
            return "RKF_ActorTypeWitchlight"
        if "wisp" in modl:
            return "RKF_ActorTypeWisp"
        if "deer" in modl:
            return "RKF_ActorTypeDeer"
        if "vampire" in modl and "lord" in modl:
            return "RKF_ActorTypeLordVampire"
        if "werewolf" in modl or "werebear" in modl:
            return "RKF_ActorTypeWerebeast"
        if "gargoyle" in modl:
            return "RKF_ActorTypeGargoyle"
        if "riekling" in modl:
            return "RKF_ActorTypeRiekling"
        if "netch" in modl:
            return "RKF_ActorTypeNetch"
        if "lurker" in modl:
            return "RKF_ActorTypeBenthicLurker"
        if "ash" in modl and "hopper" in modl:
            return "RKF_ActorTypeAshHopper"
        if "scrib" in modl:
            return "RKF_ActorTypeAshHopper"
        if "boar" in modl:
            return "RKF_ActorTypeBoarDragonborn"
        return None

    def _resolve_spell(self, record: Dict[str, Any]) -> Optional[str]:
        """Basic spell school guess from SPIT or flags. Fallback to generic."""
        # SPIT subrecord at offset 0x00 has flags that hint at school
        spit = record.get("SPIT", b"")
        if len(spit) >= 4:
            flags = struct.unpack("<I", spit[:4])[0]
            # These are rough guesses from SPIT flag bits
            if flags & 0x01:
                return "SKF_CastingTypeFireAndForget"
            if flags & 0x02:
                return "SKF_CastingTypeConcentration"
            if flags & 0x04:
                return "SKF_CastingTypeConstantEffect"
        return "SKF_CastingTypeFireAndForget"

    def _edid_fallback(self, record: Dict[str, Any], base_kw: Optional[str]) -> Optional[str]:
        """DNA gave a generic answer — let EDID narrow it down."""
        edid_raw = record.get("EDID", "")
        if isinstance(edid_raw, bytes):
            edid = edid_raw.decode('ascii', errors='ignore').split('\0')[0].strip().lower()
        else:
            edid = (edid_raw or "").lower()
        if not edid:
            return base_kw

        # BOOK refinement
        if base_kw == "IsBook":
            if "note" in edid:
                return "IsNote"
            if "journal" in edid:
                return "IsJournal"
            if "letter" in edid:
                return "IsLetter"
            if "scroll" in edid:
                return "IsScroll"
            if "tome" in edid or "spelltome" in edid:
                return "IsSpellTome"
            if "recipe" in edid:
                return "IsRecipe"
            if "map" in edid:
                return "IsMap"
            return base_kw

        # CONT refinement
        if base_kw == "IsChest":
            if "barrel" in edid:
                return "IsBarrel"
            if "safe" in edid:
                return "IsSafe"
            if "corpse" in edid:
                return "IsCorpse"
            if "knapsack" in edid:
                return "IsKnapsack"
            if "sack" in edid:
                return "IsSack"
            if "urn" in edid:
                return "IsUrn"
            if "coffin" in edid:
                return "IsCoffin"
            return base_kw

        # FURN refinement
        if base_kw == "IsWorkbench":
            if "smelter" in edid:
                return "IsSmelter"
            if "grindstone" in edid:
                return "IsGrindstone"
            if "enchanter" in edid or "arcane" in edid:
                return "IsArcaneEnchanter"
            if "alchemy" in edid:
                return "IsAlchemy"
            if "cooking" in edid:
                return "IsCooking"
            if "forge" in edid or "anvil" in edid:
                return "IsForge"
            if "tanning" in edid:
                return "IsTanningRack"
            return base_kw

        # MISC refinement
        if base_kw == "VendorItemGem":
            if "ingot" in edid or "ore" in edid:
                return "VendorItemOreIngot"
            if "soulgem" in edid or "soul gem" in edid:
                return "VendorItemSoulGem"
            if "gold" in edid or "coin" in edid:
                return "VendorItemGold"
            if "hide" in edid or "pelt" in edid:
                return "VendorItemAnimalHide"
            return base_kw

        # ALCH refinement
        if base_kw == "VendorItemPotion":
            if "poison" in edid:
                return "VendorItemPoison"
            if "food" in edid or "meal" in edid:
                return "VendorItemFood"
            if "drink" in edid or "wine" in edid or "beer" in edid or "ale" in edid:
                return "VendorItemDrink"
            return base_kw

        # LIGH refinement
        if base_kw == "IsLantern":
            if "torch" in edid:
                return "IsTorch"
            if "candle" in edid:
                return "IsCandle"
            if "campfire" in edid:
                return "IsCampfire"
            if "fire" in edid:
                return "IsFireLight"
            if "ember" in edid:
                return "IsEmberLight"
            if "magelight" in edid or "spell" in edid:
                return "IsSpellLight"
            return base_kw

        # SOULGEM refinement
        if base_kw is None and record.get("signature", "").upper() == "SLGM":
            if "petty" in edid:
                return "IsPettySoulGem"
            if "lesser" in edid:
                return "IsLesserSoulGem"
            if "common" in edid:
                return "IsCommonSoulGem"
            if "greater" in edid:
                return "IsGreaterSoulGem"
            if "grand" in edid:
                return "IsGrandSoulGem"
            if "black" in edid:
                return "IsBlackSoulGem"
            return None

        # FLOR refinement
        if base_kw is None and record.get("signature", "").upper() == "FLOR":
            if "flower" in edid or "lavender" in edid or "deathbell" in edid:
                return "IsFlower"
            if "mushroom" in edid:
                return "IsMushroom"
            if "plant" in edid:
                return "IsPlant"
            if "thistle" in edid:
                return "IsThistle"
            if "nirnroot" in edid:
                return "IsNirnroot"
            return None

        # TREE refinement
        if base_kw == "IsTree":
            if "sap" in edid:
                return "IsTreeSap"
            return base_kw

        return base_kw