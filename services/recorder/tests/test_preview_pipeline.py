from recorder.preview_pipeline import DEFAULT_BACKOFF, next_backoff


def test_next_backoff_progresses_then_saturates():
    sched = (2, 4, 8, 16, 30)
    assert next_backoff(0, sched) == 2
    assert next_backoff(1, sched) == 4
    assert next_backoff(2, sched) == 8
    assert next_backoff(3, sched) == 16
    assert next_backoff(4, sched) == 30
    # satura no último valor — não cresce indefinidamente
    assert next_backoff(5, sched) == 30
    assert next_backoff(99, sched) == 30


def test_next_backoff_clamps_negative_attempt():
    assert next_backoff(-1, (2, 4, 8)) == 2


def test_next_backoff_empty_schedule_is_zero():
    assert next_backoff(0, ()) == 0


def test_default_backoff_is_bounded():
    assert DEFAULT_BACKOFF[-1] == 30
