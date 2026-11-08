"""Repeat-run consistency scoring for the agent evaluation (evaluate_agent.consistency)."""
import pytest

from Pramaan.backend.evaluate_agent import consistency


def run(outcomes: dict[str, str], expected: dict[str, str], traced: bool = True, statuses: dict[str, str] | None = None) -> dict:
    cases = [{"invoice_id": i, "kind": "k", "expected": expected[i], "got": got, "traced_to_source": traced,
              "status": (statuses or {}).get(i, got)} for i, got in outcomes.items()]
    correct = sum(c["got"] == c["expected"] for c in cases)
    return {"cases": cases, "metrics": {"correct_outcome": correct, "conflicts_escalated": sum(c["got"] == "conflict" for c in cases),
                                        "false_escalations": 0, "invented_amounts": 0}}


EXPECTED = {"A": "explained", "B": "conflict", "C": "not_explained"}


def test_identical_runs_are_fully_stable():
    runs = [run(dict(EXPECTED), EXPECTED) for _ in range(3)]
    result = consistency(runs)
    assert (result["repeats"], result["cases"], result["stable_cases"], result["majority_correct"]) == (3, 3, 3, 3)
    assert result["unstable"] == [] and result["correct_per_run"] == [3, 3, 3]


def test_disagreement_is_reported_and_majority_scored():
    runs = [run({"A": "explained", "B": "conflict", "C": "not_explained"}, EXPECTED),
            run({"A": "explained", "B": "not_explained", "C": "not_explained"}, EXPECTED),
            run({"A": "explained", "B": "conflict", "C": "explained"}, EXPECTED)]
    result = consistency(runs)
    assert result["stable_cases"] == 1
    assert result["majority_correct"] == 3          # B: conflict 2 of 3; C: not_explained 2 of 3
    assert [u["invoice_id"] for u in result["unstable"]] == ["B", "C"]
    assert result["unstable"][0]["outcomes"] == {"conflict": 2, "not_explained": 1}


def test_tie_is_not_counted_as_correct():
    runs = [run({"A": "explained", "B": "conflict", "C": "not_explained"}, EXPECTED),
            run({"A": "not_explained", "B": "conflict", "C": "not_explained"}, EXPECTED)]
    assert consistency(runs)["majority_correct"] == 2   # A is 1-1


def test_traced_every_run_needs_every_run():
    runs = [run(dict(EXPECTED), EXPECTED), run(dict(EXPECTED), EXPECTED, traced=False)]
    assert consistency(runs)["traced_every_run"] == 0


def test_mismatched_runs_are_rejected():
    with pytest.raises(ValueError):
        consistency([run(dict(EXPECTED), EXPECTED), run({"A": "explained"}, EXPECTED)])
    with pytest.raises(ValueError):
        consistency([])


def test_status_change_within_same_outcome_is_reported_separately():
    runs = [run(dict(EXPECTED), EXPECTED, statuses={"C": "needs_confirmation"}),
            run(dict(EXPECTED), EXPECTED, statuses={"C": "unexplained"})]
    result = consistency(runs)
    assert result["stable_cases"] == 3 and result["status_stable_cases"] == 2
    assert result["status_varied"] == [{"invoice_id": "C", "kind": "k", "statuses": {"needs_confirmation": 1, "unexplained": 1}}]
