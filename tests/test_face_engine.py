import numpy as np
from app.face.engine import best_match_among


class _Cand:
    def __init__(self, name, vec):
        self.name = name
        self.face_encoding = np.asarray(vec, dtype=np.float64).tobytes()


def _vec(fill):
    return np.full(128, float(fill), dtype=np.float64)


def test_best_match_picks_closest_within_threshold():
    submitted = _vec(0.0)
    cands = [_Cand("a", _vec(0.0)), _Cand("b", _vec(5.0))]
    matched, info = best_match_among(cands, submitted)
    assert matched.name == "a"
    assert info["best_dist"] < 0.45


def test_no_match_when_all_beyond_threshold():
    submitted = _vec(0.0)
    cands = [_Cand("a", _vec(9.0))]
    matched, info = best_match_among(cands, submitted)
    assert matched is None
    assert info["best_dist"] > 0.45


def test_ambiguous_close_call_rejected():
    # 兩個候選與 submitted 距離幾乎相同 → 撞臉整批拒
    submitted = _vec(0.0)
    v = np.zeros(128); v[0] = 0.30
    v2 = np.zeros(128); v2[0] = 0.31
    cands = [_Cand("a", v), _Cand("b", v2)]
    matched, info = best_match_among(cands, submitted)
    assert matched is None
    assert info.get("ambiguous") is True


def test_empty_candidates():
    matched, info = best_match_among([], _vec(0.0))
    assert matched is None
    assert info.get("reason") == "no enrolled users"
