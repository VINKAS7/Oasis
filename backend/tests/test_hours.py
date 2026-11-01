"""Opening hours: unpadded times, past-midnight closing (checked on the next day too)."""

from app.gateway import directory

HOURS = {
    "fri": {"closed": False, "open": "18:00", "close": "02:00"},
    "sat": {"closed": True},
    "mon": {"closed": False, "open": "7:00", "close": "18:00"},
}


def test_unpadded_times():
    assert directory.is_open(HOURS, "mon", "8:30") is True
    assert directory.is_open(HOURS, "mon", "09:00") is True
    assert directory.is_open(HOURS, "mon", "6:59") is False


def test_open_past_midnight_same_day():
    assert directory.is_open(HOURS, "fri", "23:30") is True


def test_open_past_midnight_next_day():
    # Saturday 01:00 is still Friday night's opening, even though Saturday itself is closed
    assert directory.is_open(HOURS, "sat", "01:00") is True
    assert directory.is_open(HOURS, "sat", "03:00") is False


def test_unknown_day():
    assert directory.is_open(HOURS, "tue", "12:00") is None


def test_bad_time_is_unknown():
    assert directory.is_open(HOURS, "mon", "noon") is None
