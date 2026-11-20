"""'From your history': small samples never read as a trend."""

from __future__ import annotations

from app.history.analysis import insights
from app.history.similar import MIN_SAMPLE, assess, similar


def row(pnl: str, staked: str = "1.00", series: str = "KXNBAGAME",
        type_: str = "game winner") -> dict:
    return {"pnl": pnl, "staked": staked, "series": series, "type": type_,
            "series_title": "NBA Game"}


def test_no_rows_and_open_rows_are_none() -> None:
    assert assess([])["verdict"] == "none"
    assert assess([{"pnl": None, "staked": "1"}])["verdict"] == "none"


def test_a_few_big_wins_are_too_few_with_no_rate_or_roi() -> None:
    g = assess([row("3.00"), row("2.50"), row("4.00")])  # +$9.50 on 3: looks amazing, means nothing
    assert g["verdict"] == "too_few" and g["roi"] is None and g["mean_return"] is None
    assert "too few" in g["text"] and "%" not in g["text"]


def test_noisy_record_is_called_noise_even_if_positive() -> None:
    rows = [row("1.10"), row("-1.00")] * (MIN_SAMPLE // 2) + [row("0.30")]
    g = assess(rows)
    assert g["n"] >= MIN_SAMPLE and float(g["pnl"]) > 0
    assert g["verdict"] == "noise" and "isn't a pattern" in g["text"]


def test_consistent_records_beat_luck_either_way() -> None:
    good = assess([row("0.20"), row("0.25"), row("0.30")] * 5)
    assert good["verdict"] == "better" and "not a forecast" in good["text"] and good["roi"] > 0
    bad = assess([row("-0.80"), row("-1.00"), row("-0.90")] * 5)
    assert bad["verdict"] == "worse"


def test_one_tiny_longshot_win_cannot_hide_big_losses() -> None:
    # 27 losses of ~$2.60 and one 13x win on 10 cents: the money clearly went badly.
    rows = [row("-2.60", staked="2.60") for _ in range(27)] + [row("1.30", staked="0.10")]
    g = assess(rows)
    assert g["verdict"] == "worse" and g["roi"] < -0.9


def test_similar_groups_series_type_and_combo_size() -> None:
    rows = [row("0.50"), row("-1.00", series="KXNBAPTS", type_="player prop"),
            row("1.20", series="KXMVESPORTS", type_="combo")]
    out = similar(rows, ["KXNBAGAME-26NOV19-NYK", "KXNBAPTS-26NOV19-KAT-25"], [],
                  [{"legs": "2", "n": 4, "won": 1}], {"KXNBAGAME": "NBA Game"})
    keys = [(g["kind"], g["key"]) for g in out["groups"]]
    assert keys == [("series", "KXNBAGAME"), ("series", "KXNBAPTS"), ("type", "game winner"),
                    ("type", "player prop"), ("combo", "combo"), ("combo_size", "2")]
    size = out["groups"][-1]
    assert size["verdict"] == "too_few" and "4 settled 2-leg combos, 1 won" in size["text"]
    assert out["groups"][0]["label"] == "NBA Game"


def test_insights_never_call_a_small_profitable_record_a_strength() -> None:
    wr = {"n": 41, "won": 6, "win_rate": 0.15, "avg_price": 0.16, "edge": 0.02, "se": 0.06,
          "small_sample": False}
    by_type = [{"name": "game winner", "series": "KXNBAGAME", "markets": 7, "staked": "20",
                "pnl": "9.87", "roi": 0.49}]
    done = [row("3.00"), row("-1.00"), row("2.00"), row("4.00"), row("-1.00"), row("2.88"),
            row("0.00")]
    out = insights({"win_rate": wr}, {}, [], by_type, [], done)
    best = next(i for i in out if "game winner" in i["text"])
    assert best["level"] == "info" and "Too few or too noisy" in best["text"]
    overall = next(i for i in out if i["text"].startswith("Your picks won"))
    assert overall["level"] == "info"  # +2 pts with ±6 pts standard error is noise
