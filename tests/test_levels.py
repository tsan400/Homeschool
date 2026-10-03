from hs import config
from hs.levels import State, placement_result, update

RULES = config.settings()["levels"]


def run(state, *sessions):
    for n, k, easy in sessions:
        state = update(state, n, k, easy, RULES)
    return state


def test_three_good_sessions_level_up():
    s = run(State(2), (5, 5, 0), (5, 5, 0))
    assert s.level == 2 and s.up == 2
    assert run(s, (5, 5, 0)) == State(3)


def test_streak_breaks_on_a_middling_session():
    assert run(State(2), (5, 5, 0), (5, 5, 0), (5, 3, 0), (5, 5, 0)).level == 2


def test_two_bad_sessions_level_down_but_not_below_one():
    assert run(State(3), (5, 2, 0)).level == 3
    assert run(State(3), (5, 2, 0), (5, 1, 0)) == State(2)
    assert run(State(1), (5, 0, 0), (5, 0, 0)).level == 1


def test_too_easy_fast_tracks():
    assert run(State(2), (5, 5, 3)) == State(3)
    assert run(State(2), (5, 5, 2)).level == 2      # not more than half
    assert run(State(2), (5, 3, 5)).level == 2      # too easy but under 85%


def test_small_sessions_do_not_count():
    assert run(State(2, up=2), (3, 3, 0)) == State(2, up=2)


def test_mastery_at_top_level():
    assert run(State(5, up=2), (5, 5, 0)) == State(5, mastered=True)


def test_placement():
    assert placement_result(2).mastered
    assert placement_result(1) == State(3)
    assert placement_result(0) == State(1)
