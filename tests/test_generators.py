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


def test_long_division_is_worked_digit_by_digit():
    from hs.generators.math import division_steps
    assert division_steps(9182, 5) == [
        "*Divide* $9 div 5 = 1$, *multiply* $1 times 5 = 5$, *subtract* $9 - 5 = 4$. *Bring down* the 1 to make 41.",
        "*Divide* $41 div 5 = 8$, *multiply* $8 times 5 = 40$, *subtract* $41 - 40 = 1$. *Bring down* the 8 to make 18.",
        "*Divide* $18 div 5 = 3$, *multiply* $3 times 5 = 15$, *subtract* $18 - 15 = 3$. *Bring down* the 2 to make 32.",
        "*Divide* $32 div 5 = 6$, *multiply* $6 times 5 = 30$, *subtract* $32 - 30 = 2$. Nothing left to bring down, so 2 is the remainder."]
    assert division_steps(1003, 14)[0] == "1 and 10 are smaller than 14, so start with 100."
    assert "$0 div 3 = 0$" in division_steps(9032, 3)[1]          # a zero in the answer is written, not skipped
    assert division_steps(84, 4)[-1].endswith("Nothing left over.")
