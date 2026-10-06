"""History, science and French alongside math; the word of the day; the weather on page 1."""

import json

import pytest

from hs import accounts, db, jobs, layout as L, packets, planner, readings, vault, weather, words
from synthetic import fill_in, phone_scan, to_pdf

WEEK = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]  # Monday to Friday


@pytest.fixture
def ao_kid(con, family):
    fid, kids = family
    con.execute("UPDATE student SET ao_year=4, french=1 WHERE id=?", (kids["timothy"],))
    con.commit()
    return fid, kids["timothy"]


def extras(con, ws_id):
    return {s: a["item"] for s, a in db.assignments(con, ws_id).items()}


def test_a_week_follows_the_ao_rhythm_in_order(con, ao_kid):
    fid, sid = ao_kid
    got = [extras(con, packets.make(con, sid, day)) for day in WEEK]
    assert [g.get("history") or g.get("science") or g.get("nature") for g in got] == \
        ["tcoo-29", "fabre-1", "madamhow-1", "fabre-2", None]
    assert all(g["french"] == "lesson-1" for g in got)   # nothing marked done yet, so the lesson repeats

    # A missed week doesn't skip readings: the next Monday gets the next chapter.
    assert extras(con, packets.make(con, sid, "2026-10-19"))["history"] == "tcoo-30"


def test_reading_pages_are_numbered_after_the_math(con, ao_kid):
    fid, sid = ao_kid
    ws_id = packets.make(con, sid, WEEK[0])
    pages = json.loads(db.worksheet(con, ws_id)["pages"])
    kinds = [p["kind"] for p in pages]
    assert kinds[-2:] == ["reading", "narration"] and set(kinds[:-2]) == {"problems"}
    reading, narration = pages[-2:]
    assert reading["pages"] >= 2 and narration["page"] == reading["page"] + reading["pages"]
    assert db.assignments(con, ws_id)["history"]["page"] == narration["page"]
    import pypdfium2 as pdfium
    assert len(pdfium.PdfDocument(vault.get(con, fid, packets.packet_name(ws_id)))) == narration["page"]


def test_french_moves_on_once_marked_done(con, ao_kid):
    fid, sid = ao_kid
    first = packets.make(con, sid, WEEK[0])
    con.execute("UPDATE assignment SET done=1 WHERE worksheet_id=? AND subject='french'", (first,))
    assert extras(con, packets.make(con, sid, WEEK[1]))["french"] == "lesson-2"


def test_math_only_children_get_no_readings(con, family):
    fid, kids = family
    assert set(extras(con, packets.make(con, kids["hannah"], WEEK[0]))) == {"word"}


def test_word_of_the_day(con, ao_kid, family):
    fid, sid = ao_kid
    hannah = family[1]["hannah"]
    days = [extras(con, packets.make(con, sid, day))["word"] for day in WEEK]
    assert len(set(days)) == len(days)                                   # never repeated
    assert all(w in {e["word"] for e in words.bands()["3-5"]} for w in days)
    assert words.appears(days[0], readings.text("tcoo-29"))              # Monday's word is in Monday's chapter
    # A second packet on the same day shares the day's word.
    assert extras(con, packets.make(con, sid, WEEK[0], kind="placement"))["word"] == days[0]
    assert extras(con, packets.make(con, hannah, WEEK[0]))["word"] == words.bands()["6-8"][0]["word"]


def test_page_one_problems_start_below_the_panel(con, family):
    fid, kids = family
    ws_id = packets.make(con, kids["hannah"], WEEK[0])
    per = 6
    first = [p for p in db.problems(con, ws_id) if p["page"] == 1]
    assert [p["slot"] for p in first] == list(range(1 + L.today_slots(per), per + 1))
    assert L.slot_top(first[0]["slot"], per) >= L.BODY_TOP + L.TODAY_H
    assert planner.positions(5, 6, 3) == [(0, 3), (0, 4), (0, 5), (0, 6), (1, 1)]


def hourly(codes, probs, temps):
    return {"time": [f"2026-10-07T{h:02d}:00" for h in range(24)], "weather_code": codes,
            "precipitation_probability": probs, "temperature_2m": temps}


def forecast(codes, probs, temps, high, low, gust=10, uv=3, unit="°F"):
    return {"daily_units": {"temperature_2m_max": unit},
            "daily": {"weather_code": [max(codes)], "temperature_2m_max": [high], "temperature_2m_min": [low],
                      "precipitation_probability_max": [max(probs)], "wind_gusts_10m_max": [gust], "uv_index_max": [uv],
                      "sunrise": ["2026-10-07T06:49"], "sunset": ["2026-10-07T18:16"]},
            "hourly": hourly(codes, probs, temps)}


def test_weather_in_plain_words():
    dry = forecast([1] * 24, [0] * 24, [50] * 24, 66, 48)
    w = weather.summarize(dry)
    assert (w["sky"], w["icon"], w["high"], w["low"]) == ("Mostly sunny", "sun", 66, 48)
    assert w["sunset"] == "6:16 pm" and w["notes"] == ["A lovely day for a nature walk."]

    # Rain from 2 pm: the sky says rain, and the note says when.
    rain = forecast([3] * 14 + [63] * 10, [10] * 14 + [80] * 10, [55] * 24, 58, 50)
    w = weather.summarize(rain)
    assert w["icon"] == "rain" and w["notes"][0] == "Rain likely after 2 pm. Bring an umbrella."

    # One drizzly hour at 3 am doesn't make the school day rainy; a frosty, windy morning is noted.
    night = forecast([51] + [0] * 23, [60] + [0] * 23, [28] * 9 + [50] * 15, 55, 28, gust=35)
    w = weather.summarize(night)
    assert w["icon"] == "sun"
    assert w["notes"] == ["Below freezing this morning. Bundle up!", "Windy, with gusts to 35 mph."]

    hot = forecast([0] * 24, [0] * 24, [75] * 24, 31, 22, uv=9, unit="°C")
    assert weather.summarize(hot)["notes"] == ["Strong sun. Wear sunscreen."]   # 31°C is under the 32°C "hot" line


def test_no_weather_never_holds_up_a_packet(con, family, monkeypatch):
    fid, kids = family
    con.execute("UPDATE family SET place='Concord, Massachusetts', lat=42.46, lon=-71.35, units='fahrenheit' WHERE id=?", (fid,))
    con.commit()

    def offline(*a, **k):
        raise weather.WeatherError("offline")
    monkeypatch.setattr(weather, "fetch", offline)
    ws_id = packets.make(con, kids["hannah"], WEEK[0])
    assert db.worksheet(con, ws_id)["weather"] is None
    assert vault.exists(fid, packets.packet_name(ws_id))


def test_weather_is_printed_when_there_is_a_forecast(con, family, monkeypatch):
    fid, kids = family
    con.execute("UPDATE family SET place='Concord, Massachusetts', lat=42.46, lon=-71.35, units='fahrenheit' WHERE id=?", (fid,))
    con.commit()
    monkeypatch.setattr(weather, "fetch", lambda *a, **k: forecast([2] * 24, [0] * 24, [50] * 24, 61, 44))
    ws_id = packets.make(con, kids["hannah"], WEEK[0])
    assert json.loads(db.worksheet(con, ws_id)["weather"])["sky"] == "Partly cloudy"
    import pypdfium2 as pdfium
    text = pdfium.PdfDocument(vault.get(con, fid, packets.packet_name(ws_id)))[0].get_textpage().get_text_range()
    assert "Partly cloudy" in text and "WORD OF THE DAY" in text


def test_french_circle_and_narration_page_are_read_from_a_scan(con, ao_kid):
    fid, sid = ao_kid
    ws_id = packets.make(con, sid, WEEK[0])
    narration = db.assignments(con, ws_id)["history"]["page"]
    packet = vault.get(con, fid, packets.packet_name(ws_id))
    cx, cy, _ = L.FRENCH
    imgs = fill_in(packet, {}, {}, ticks=[(1, cx, cy)],
                   writing={narration: ["The people of Connecticut wanted", "to choose their own leaders so they",
                                        "moved to the valley with Thomas Hooker."]})
    pages = [phone_scan(imgs[0], 1), phone_scan(imgs[narration - 1], 2)]
    uid = jobs.submit(con, fid, "scan.pdf", to_pdf(pages))
    jobs.process(con, uid, lambda items: {})
    report = con.execute("SELECT report FROM upload WHERE id=?", (uid,)).fetchone()["report"]
    a = db.assignments(con, ws_id)
    assert a["french"]["done"] == 1, report
    assert a["history"]["done"] == 1
    assert "French Pimsleur French 1, lesson 1: done" in report


def test_an_unmarked_circle_and_blank_narration_page_count_for_nothing(con, ao_kid):
    fid, sid = ao_kid
    ws_id = packets.make(con, sid, WEEK[1])
    narration = db.assignments(con, ws_id)["science"]["page"]
    imgs = fill_in(vault.get(con, fid, packets.packet_name(ws_id)), {}, {})
    uid = jobs.submit(con, fid, "scan.pdf", to_pdf([phone_scan(imgs[0], 3), phone_scan(imgs[narration - 1], 4)]))
    jobs.process(con, uid, lambda items: {})
    a = db.assignments(con, ws_id)
    assert a["french"]["done"] == 0 and a["french"]["fill"] < 0.012
    assert a["science"]["done"] is None   # maybe narrated out loud: the parent ticks it on the day page
