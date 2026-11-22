from mediakit_cli.edit import _nearest, _snap_to_beats


def _clip(dur, total=10.0, start=0.0):
    return {"dur": dur, "in": start, "info": {"duration": total}}


def test_nearest_picks_closest_beat():
    assert _nearest(1.9, [0.0, 1.0, 2.0]) == 2.0
    assert _nearest(1.2, [0.0, 1.0, 2.0]) == 1.0
    assert _nearest(1.0, []) is None


def test_snap_moves_cuts_onto_beats():
    clips = [_clip(2.0), _clip(2.0), _clip(2.0)]
    beats = [0.0, 1.95, 4.0, 6.0]
    durs, cuts, snapped, clamped = _snap_to_beats(clips, beats, tolerance=0.35)
    assert abs(sum(durs) - cuts[-1]) < 1e-6
    assert snapped >= 1
    assert clamped == 0


def test_snap_clamps_when_clip_too_short():
    clips = [_clip(1.0, total=1.0), _clip(2.0)]
    beats = [0.0, 5.0]
    durs, cuts, snapped, clamped = _snap_to_beats(clips, beats, tolerance=10.0)
    assert clamped == 1
    assert durs[0] <= 1.0
