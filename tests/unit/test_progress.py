from __future__ import annotations

import pytest

from mupstudio.jobs.progress import ProgressTracker, parse_line

# Verbatim lines from an mf6rtm run's stdout: the only progress signal the
# engine offers, so the parser is pinned to the real text.
TRANSPORT = (
    "Transport       | Stress period:  2     | Time step:      7          "
    "| Completed in : 0.01 mins"
)
REACTIONS = (
    "Reactions       | Stress period:  2     | Time step:      7          "
    "| Completed in : 0.12 mins"
)


class TestParseLine:
    def test_reads_a_transport_step(self) -> None:
        event = parse_line(TRANSPORT)

        assert event is not None
        assert (event.kind, event.kper, event.kstp, event.phase) == ("step", 2, 7, "transport")

    def test_maps_reactions_to_the_chemistry_phase(self) -> None:
        event = parse_line(REACTIONS)

        assert event is not None
        assert event.phase == "chemistry"

    def test_notices_a_convergence_failure(self) -> None:
        event = parse_line("MODFLOW 6 failed to converge 3 times")

        assert event is not None
        assert event.kind == "warning"
        assert "3 times" in event.message

    def test_notices_a_successful_finish(self) -> None:
        event = parse_line("MODEL RUN FINISHED BUT CHECK THE RESULTS")

        assert event is not None
        assert event.kind == "finished"

    def test_notices_a_failure(self) -> None:
        event = parse_line("SOMETHING WENT WRONG. BUMMER")

        assert event is not None
        assert event.kind == "failed"

    @pytest.mark.parametrize(
        "line",
        [
            "",
            "   ",
            "normal solution output nobody needs to see",
            "Solving:  Stress period: 1",  # close, but not the step format
        ],
    )
    def test_stays_quiet_about_lines_that_say_nothing(self, line: str) -> None:
        assert parse_line(line) is None

    def test_tolerates_extra_whitespace(self) -> None:
        event = parse_line("Transport|Stress period: 11|Time step: 2|Completed in : 0.01 mins")

        assert event is not None
        assert (event.kper, event.kstp) == (11, 2)


class TestProgressTracker:
    def test_follows_the_latest_position(self) -> None:
        tracker = ProgressTracker()

        tracker.apply(parse_line(TRANSPORT))  # type: ignore[arg-type]

        assert (tracker.kper, tracker.kstp, tracker.phase) == (2, 7, "transport")

    def test_offers_no_fraction_without_a_total(self) -> None:
        tracker = ProgressTracker()
        tracker.apply(parse_line(TRANSPORT))  # type: ignore[arg-type]

        assert tracker.fraction is None

    def test_reports_a_fraction_once_the_total_is_known(self) -> None:
        tracker = ProgressTracker(total_kper=4)
        tracker.apply(parse_line(TRANSPORT))  # type: ignore[arg-type]

        assert tracker.fraction == pytest.approx(0.5)

    def test_never_reports_more_than_complete(self) -> None:
        tracker = ProgressTracker(total_kper=1)
        tracker.apply(parse_line(TRANSPORT))  # type: ignore[arg-type]

        assert tracker.fraction == 1.0

    def test_accumulates_warnings(self) -> None:
        tracker = ProgressTracker()
        tracker.apply(parse_line("MODFLOW 6 failed to converge 2 times"))  # type: ignore[arg-type]
        tracker.apply(parse_line("MODFLOW 6 failed to converge 5 times"))  # type: ignore[arg-type]

        assert len(tracker.warnings) == 2

    def test_records_the_outcome(self) -> None:
        finished = ProgressTracker()
        finished.apply(parse_line("MODEL RUN FINISHED"))  # type: ignore[arg-type]
        failed = ProgressTracker()
        failed.apply(parse_line("SOMETHING WENT WRONG"))  # type: ignore[arg-type]

        assert finished.finished and not finished.failed
        assert failed.failed and not failed.finished

    def test_snapshot_carries_everything_the_ui_shows(self) -> None:
        tracker = ProgressTracker(total_kper=10)
        tracker.apply(parse_line(REACTIONS))  # type: ignore[arg-type]

        snapshot = tracker.snapshot()

        assert set(snapshot) == {
            "kper",
            "kstp",
            "phase",
            "fraction",
            "warnings",
            "finished",
            "failed",
        }
