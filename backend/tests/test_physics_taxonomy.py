from app.core.physics_taxonomy import find_chapter_taxonomy, load_physics_taxonomy, match_kp_taxonomy_labels


def test_load_physics_taxonomy_parses_core_sections():
    taxonomy = load_physics_taxonomy()
    chapter = taxonomy.get("运动的描述")
    assert chapter is not None
    assert "描述运动的理论基础" in chapter.knowledge_tags
    assert any("速度与加速度" in item for item in chapter.focus_tags)
    assert any("运动图像" in item for item in chapter.exam_tags)


def test_find_chapter_taxonomy_parses_experiments():
    chapter = find_chapter_taxonomy("选择性必修一演示实验")
    assert chapter is not None
    assert any("双缝干涉实验" in item for item in chapter.experiment_tags)
    assert any("单缝衍射实验" in item for item in chapter.experiment_tags)


def test_match_kp_taxonomy_labels_prefers_matching_exam_labels():
    chapter = find_chapter_taxonomy("机械波")
    assert chapter is not None
    matched = match_kp_taxonomy_labels("波长、周期与波速", chapter, description="机械波传播规律")
    assert any("波长" in item or "波速" in item for item in matched["exam_tags"])
