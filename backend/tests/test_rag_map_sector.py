from app.core.map_sector import infer_map_sector


def test_maps_legacy_sectors_to_new_sector_groups():
    assert infer_map_sector(legacy_sector="force") == "mechanics"
    assert infer_map_sector(legacy_sector="electric") == "electromagnetism"
    assert infer_map_sector(legacy_sector="magnetism") == "electromagnetism"
    assert infer_map_sector(legacy_sector="thermal") == "thermodynamics"
    assert infer_map_sector(legacy_sector="wave") == "optics_wave"
    assert infer_map_sector(legacy_sector="optics") == "optics_wave"
    assert infer_map_sector(legacy_sector="modern") == "modern_physics"


def test_acoustics_is_grouped_into_optics_wave():
    assert infer_map_sector("声学", "机械波与振动") == "optics_wave"
    assert infer_map_sector("驻波", "波动图像") == "optics_wave"


def test_chapter_semantics_fall_back_to_expected_sector():
    assert infer_map_sector("牛顿运动定律") == "mechanics"
    assert infer_map_sector("电磁感应与楞次定律") == "electromagnetism"
    assert infer_map_sector("原子核与衰变") == "modern_physics"
