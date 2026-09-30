from tk.durations import format_duration


def test_format_duration():
    assert format_duration(0) == "0s"
    assert format_duration(5400) == "1h30m"
    assert format_duration(90061) == "1d1h1m1s"
