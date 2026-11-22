from mediakit.auto import cut_points, pace_map


def test_pace_map_treats_near_equal_sections_as_uniform():
    sections = [
        {"start": 0, "end": 10, "energy": 0.111},
        {"start": 10, "end": 20, "energy": 0.122},
    ]
    assert [s["beats_per_cut"] for s in pace_map(sections, default_k=4)] == [4, 4]


def test_pace_map_spreads_energy_to_slow_and_fast():
    sections = [
        {"start": 0, "end": 10, "energy": 0.1},
        {"start": 10, "end": 20, "energy": 0.9},
    ]
    assert [s["beats_per_cut"] for s in pace_map(sections)] == [8, 3]


def test_cut_points_start_at_zero_and_end_at_duration():
    beats = [i * 0.5 for i in range(1, 10)]
    cuts = cut_points(beats, 4.5, beats_per_cut=2)
    assert cuts[0] == 0.0
    assert cuts[-1] == 4.5
    assert cuts == sorted(cuts)


def test_cut_points_fall_back_when_no_beats():
    cuts = cut_points([], 10.0, beats_per_cut=4, fallback=2.5)
    assert cuts[0] == 0.0
    assert cuts[-1] == 10.0
    assert len(cuts) >= 3
