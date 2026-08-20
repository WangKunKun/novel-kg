from novel_kg.config import load_config


def test_load_config_parses_entity_types_and_taxonomy():
    cfg = load_config("config/novels/xuanjian.yaml")
    assert "人物" in cfg.entity_types
    assert cfg.entity_types["仙基"].classify_by == ["五行", "品阶", "传承"]
    assert cfg.classification_dimensions["五行"] == ["金", "木", "水", "火", "土"]
    assert cfg.taxonomy_parents["五行"]["玄水"] == "水"
    names = [rt.name for rt in cfg.relation_types]
    assert "所属" in names and "克制" in names


def test_faction_relation_type_replaces_hostile():
    cfg = load_config("config/novels/xuanjian.yaml")
    names = [rt.name for rt in cfg.relation_types]
    assert "势力关系" in names
    assert "敌对" not in names
    fr = next(rt for rt in cfg.relation_types if rt.name == "势力关系")
    assert fr.from_type == "势力" and fr.to_type == "势力"
    assert "attrs" in fr.description  # 性质须写 attrs 的约束要在描述里
