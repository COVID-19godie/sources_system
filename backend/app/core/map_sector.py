from __future__ import annotations

import re


LEGACY_TO_MAP_SECTOR = {
    "force": "mechanics",
    "electric": "electromagnetism",
    "magnetism": "electromagnetism",
    "thermal": "thermodynamics",
    "wave": "optics_wave",
    "optics": "optics_wave",
    "modern": "modern_physics",
}

MAP_SECTOR_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("modern_physics", ("近代", "原子", "原子核", "光电", "波粒", "核", "衰变", "裂变", "聚变")),
    ("electromagnetism", ("电", "磁", "电场", "电流", "电磁", "感应", "洛伦兹", "安培", "电势", "电容")),
    ("thermodynamics", ("热", "热学", "内能", "分子动理论", "气体", "热力学", "温度", "压强")),
    ("optics_wave", ("光", "波", "声", "振动", "机械波", "电磁波", "干涉", "衍射", "透镜", "折射", "反射", "声学")),
    ("mechanics", ("力", "运动", "牛顿", "动量", "能量", "圆周", "万有引力", "机械能", "做功")),
]


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "").strip().lower())


def infer_map_sector(*values: str | None, legacy_sector: str | None = None) -> str:
    if legacy_sector:
        mapped = LEGACY_TO_MAP_SECTOR.get((legacy_sector or "").strip().lower())
        if mapped:
            return mapped

    merged = "".join(_normalize_text(value) for value in values if value)
    for sector_key, keywords in MAP_SECTOR_KEYWORDS:
        if any(keyword.lower() in merged for keyword in keywords):
            return sector_key
    return "mechanics"
