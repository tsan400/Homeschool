import tempfile
from pathlib import Path

import pytest

from hs import config
from hs.generators.math import GENERATORS, generate
from hs.grade import check, parse_number, parse_remainder
from hs.render import FONTS, big, compile_typ

SKILLS = [s["id"] for s in config.skills()]


def test_every_skill_has_a_generator():
    assert set(SKILLS) == set(GENERATORS)


@pytest.mark.parametrize("skill", SKILLS)
def test_answers_are_well_formed(skill):
    form = config.skill(skill)["form"]
    for level in range(1, 6):
        prompts = set()
        for seed in range(40):
            p = generate(skill, level, f"{skill}-{level}-{seed}")
            assert p.form == form, f"{skill}: form {p.form} != skills.yaml {form}"
            assert p.steps
            assert check(p.answer, p.answer, p.form), (skill, level, p)
            if p.form == "remainder":
                assert parse_remainder(p.answer)
            else:
                assert parse_number(p.answer)
            prompts.add(p.prompt)
        assert len(prompts) > 3, f"{skill} level {level} has almost no variety"


@pytest.mark.parametrize("skill", SKILLS)
def test_prompts_and_steps_compile(skill):
    """Every generated prompt and worked example is valid Typst."""
    body = []
    for level in range(1, 6):
        for seed in range(10):
            p = generate(skill, level, seed)
            body.append(big(p.prompt) + "\n\n" + "\n".join(f"+ {big(s)}" for s in p.steps) + "\n\n")
    with tempfile.TemporaryDirectory() as tmp:
        compile_typ(f"#set text(font: {FONTS})\n" + "".join(body), Path(tmp), Path(tmp) / "out.pdf")


def test_deterministic():
    assert generate("frac_add_unlike", 3, "abc") == generate("frac_add_unlike", 3, "abc")
