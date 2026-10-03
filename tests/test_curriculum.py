"""The K-12 curriculum is the map; skills.yaml is the part of it the engine generates."""

from hs import config

MODES = {"paper", "written", "oral", "hands-on"}


def topics():
    return [(g["grade"], t) for g in config.curriculum() for t in g["topics"]]


def test_grades_k_to_12_in_order():
    assert [g["grade"] for g in config.curriculum()] == list(range(13))


def test_topics_are_well_formed_and_unique():
    ids = [t["id"] for _, t in topics()]
    assert len(ids) == len(set(ids))
    for _, t in topics():
        assert t["mode"] in MODES and t["name"] and t["strand"], t


def test_every_engine_skill_is_on_the_map_at_its_grade_and_in_order():
    placed = {t["id"]: (grade, i) for i, (grade, t) in enumerate(topics())}
    skills = config.skills()
    for sk in skills:
        assert sk["id"] in placed, f"{sk['id']} missing from curriculum.yaml"
        assert placed[sk["id"]][0] == sk["grade"], sk["id"]
    order = [placed[sk["id"]][1] for sk in skills]
    assert order == sorted(order), "skills.yaml must follow the curriculum's teaching order"


def test_engine_skills_are_paper_topics():
    modes = {t["id"]: t["mode"] for _, t in topics()}
    assert all(modes[sk["id"]] == "paper" for sk in config.skills())
