import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
import scenario
from fakes import FakePartnerClient, FakeReader, FakeRegistry

from catenax_simplified.storage import (
    PartnerRepository,
    PartnerSyncRunRepository,
    PartRepository,
    init_schema,
    make_engine,
    make_session_factory,
)
from catenax_simplified.traceability import OwnTwinSync, PartnerSync, part_tree, partner_sync

CLOCK = datetime(2026, 10, 14, tzinfo=UTC)


@pytest.fixture
def session_factory():
    engine = make_engine("sqlite:///:memory:")
    init_schema(engine)
    factory = make_session_factory(engine)
    OwnTwinSync(
        FakeRegistry(scenario.shells()),
        FakeReader(scenario.payloads()),
        factory,
        own_bpnl=scenario.TIER1,
        clock=lambda: CLOCK,
    ).run()
    return factory


def _partner_sync(session_factory, client=None, connectors=None, **kwargs) -> PartnerSync:
    """One partner and one twin at a time unless asked otherwise: outcomes in a set order."""
    kwargs = {"parallel_partners": 1, "parallel_twins": 1, **kwargs}
    return PartnerSync(
        client or FakePartnerClient(scenario.tier2_twins(), scenario.tier2_payloads()),
        session_factory,
        scenario.TIER1,
        configured_connectors=connectors
        if connectors is not None
        else {scenario.TIER2: scenario.TIER2_CONNECTOR},
        clock=lambda: CLOCK,
        **kwargs,
    )


def test_counterparts_come_from_own_relations(session_factory):
    with session_factory() as session:
        counterparts = PartRepository(session).partner_counterparts()
    assert counterparts == {
        scenario.TIER2: {
            "supplier": {scenario.CELL_1, scenario.CELL_2, scenario.CELL_3},
            "customer": set(),
        },
        scenario.OEM: {"supplier": set(), "customer": {scenario.VEHICLE}},
    }


def test_partner_twins_are_cached_one_level_only(session_factory):
    client = FakePartnerClient(scenario.tier2_twins(), scenario.tier2_payloads())
    report = _partner_sync(session_factory, client).run()

    by_bpnl = {r.bpnl: r for r in report.partners}
    tier2 = by_bpnl[scenario.TIER2]
    assert (tier2.roles, tier2.linked_twins) == (["supplier"], 3)
    assert (tier2.twins_found, tier2.twins_missing, tier2.status) == (2, 1, "partial")
    assert by_bpnl[scenario.OEM].status == "no_connector"
    # Only the partner's own twins were looked up — never their children.
    assert {gid for _, gid in client.lookups} == {
        scenario.CELL_1,
        scenario.CELL_2,
        scenario.CELL_3,
    }

    with session_factory() as session:
        repo = PartRepository(session)
        cell_1 = repo.get_part(scenario.CELL_1)
        assert (cell_1.is_own, cell_1.manufacturer_id) == (False, scenario.TIER2)
        assert cell_1.semantic_id.endswith("serial_part:3.0.0#SerialPart")
        assert repo.get_part(scenario.CELL_3).semantic_id.endswith("serial_part:4.0.0#SerialPart")
        assert repo.get_part(scenario.CELL_2) is None

        tree = part_tree(repo, scenario.MODULE_A)
        names = {c.global_asset_id: c.part and c.part.name_at_manufacturer for c in tree.children}
        assert names == {scenario.CELL_1: "Li-ion cell", scenario.CELL_2: None}

        rows = {row.bpnl: row for row in PartnerRepository(session).all()}
        assert rows[scenario.TIER2].last_status == "partial"
        assert rows[scenario.TIER2].twins_found == 2
        assert rows[scenario.OEM].last_status == "no_connector"


def test_stored_address_wins_over_settings(session_factory):
    with session_factory.begin() as session:
        PartnerRepository(session).get_or_create(scenario.OEM).connector_address = "https://oem/dsp"
    client = FakePartnerClient({}, {})
    report = _partner_sync(session_factory, client, connectors={scenario.OEM: "https://x"}).run(
        only_bpnl=scenario.OEM
    )
    assert [r.bpnl for r in report.partners] == [scenario.OEM]
    assert report.partners[0].twins_missing == 1
    assert client.lookups == [(scenario.OEM, scenario.VEHICLE)]


def test_a_selection_reads_only_those_twins_and_keeps_the_rest(session_factory):
    _partner_sync(session_factory).run()
    with session_factory() as session:
        before = PartnerRepository(session).get(scenario.TIER2).last_sync_at
    client = FakePartnerClient(scenario.tier2_twins(), scenario.tier2_payloads())

    report = _partner_sync(session_factory, client).run(
        only_twins=[scenario.CELL_3, scenario.MODULE_A]
    )

    assert client.lookups == [(scenario.TIER2, scenario.CELL_3)]
    assert [(r.bpnl, r.linked_twins, r.twins_found) for r in report.partners] == [
        (scenario.TIER2, 1, 1)
    ]
    assert report.not_linked == [scenario.MODULE_A]  # an own part, not a counterpart
    with session_factory() as session:
        assert PartRepository(session).get_part(scenario.CELL_1) is not None  # kept
        assert PartnerRepository(session).get(scenario.TIER2).last_sync_at == before


def test_a_failed_lookup_is_that_twins_problem_and_the_rest_are_read(session_factory):
    client = FakePartnerClient(
        scenario.tier2_twins(), scenario.tier2_payloads(), failing={scenario.CELL_1}
    )
    report = _partner_sync(session_factory, client).run(only_bpnl=scenario.TIER2)

    result = report.partners[0]
    assert {gid for _, gid in client.lookups} == {scenario.CELL_1, scenario.CELL_2, scenario.CELL_3}
    assert (result.status, result.twins_found) == ("partial", 1)
    assert result.issues[0].startswith(f"{scenario.CELL_1}: GET /lookup/shells returned HTTP 500")


def test_lookups_failing_in_a_row_stop_the_partner(session_factory, monkeypatch):
    monkeypatch.setattr(partner_sync, "MAX_LOOKUP_ERRORS_IN_A_ROW", 2)
    cells = sorted([scenario.CELL_1, scenario.CELL_2, scenario.CELL_3])
    client = FakePartnerClient(
        scenario.tier2_twins(), scenario.tier2_payloads(), failing=set(cells[:2])
    )
    report = _partner_sync(session_factory, client).run(only_bpnl=scenario.TIER2)

    result = report.partners[0]
    assert result.status == "failed"
    assert len(client.lookups) == 2
    assert result.issues[-2:] == ["stopped after 2 lookups failed in a row", "1 twins not tried"]


def test_unreachable_partner_keeps_its_cached_parts(session_factory):
    _partner_sync(session_factory).run()
    client = FakePartnerClient({}, {}, unreachable={scenario.TIER2})
    report = _partner_sync(session_factory, client).run(only_bpnl=scenario.TIER2)

    result = report.partners[0]
    assert result.status == "failed"
    assert "timeout" in result.issues[0]
    with session_factory() as session:
        assert PartRepository(session).get_part(scenario.CELL_1) is not None


def test_bad_submodel_is_reported(session_factory):
    payloads = scenario.tier2_payloads()
    for url in payloads:
        if scenario.CELL_3 in url:
            payloads[url] = {"globalAssetId": scenario.CELL_1}  # describes another twin
    report = _partner_sync(
        session_factory, FakePartnerClient(scenario.tier2_twins(), payloads)
    ).run(only_bpnl=scenario.TIER2)

    issues = report.partners[0].issues
    assert any(scenario.CELL_3 in issue and "describes" in issue for issue in issues)
    with session_factory() as session:
        assert PartRepository(session).get_part(scenario.CELL_3) is None


def test_own_bpnl_is_never_a_partner(session_factory):
    report = PartnerSync(
        FakePartnerClient({}, {}), session_factory, scenario.TIER2, clock=lambda: CLOCK
    ).run()
    assert scenario.TIER2 not in {r.bpnl for r in report.partners}


def test_progress_follows_the_run_twin_by_twin(session_factory):
    seen = []

    class Watching(FakePartnerClient):
        def find_twin(self, partner, global_asset_id):
            seen.append(sync.progress.snapshot())
            return super().find_twin(partner, global_asset_id)

    sync = _partner_sync(
        session_factory, Watching(scenario.tier2_twins(), scenario.tier2_payloads())
    )
    assert sync.progress.snapshot() is None
    report = sync.run()

    # OEM (no connector) comes first in BPNL order, then the three TIER2 twins one by one.
    cells = sorted([scenario.CELL_1, scenario.CELL_2, scenario.CELL_3])
    tier2 = [next(p for p in snap["partners"] if p["bpnl"] == scenario.TIER2) for snap in seen]
    assert [(p["state"], p["twins_done"], p["current_twin"]) for p in tier2] == [
        ("running", 0, cells[0]),
        ("running", 1, cells[1]),
        ("running", 2, cells[2]),
    ]
    assert all(s["running"] and s["linked_twins"] == 4 for s in seen)
    assert (seen[0]["partners_done"], seen[0]["partners_running"]) == (1, 1)

    done = sync.progress.snapshot()
    assert (done["running"], done["finished_at"], done["report"]) == (
        False,
        report.finished_at,
        report,
    )
    assert (done["partners_done"], done["twins_done"]) == (2, 4)
    # CELL_2 has no twin at TIER2: two cached, one missing.
    assert (done["twins_cached"], done["twins_missing"], done["twins_failed"]) == (2, 1, 0)
    assert {p["bpnl"]: p["state"] for p in done["partners"]} == {
        scenario.TIER2: "partial",
        scenario.OEM: "no_connector",
    }
    result = next(r for r in report.partners if r.bpnl == scenario.TIER2)
    assert (result.parts_cached, result.duration_seconds >= 0) == (2, True)


def test_progress_counts_failed_lookups_and_twins_not_tried(session_factory, monkeypatch):
    monkeypatch.setattr(partner_sync, "MAX_LOOKUP_ERRORS_IN_A_ROW", 2)
    cells = sorted([scenario.CELL_1, scenario.CELL_2, scenario.CELL_3])
    client = FakePartnerClient(
        scenario.tier2_twins(), scenario.tier2_payloads(), failing=set(cells[:2])
    )
    sync = _partner_sync(session_factory, client)
    sync.run(only_bpnl=scenario.TIER2)

    done = sync.progress.snapshot()
    assert (done["partners_total"], done["twins_failed"], done["twins_done"]) == (1, 2, 3)
    assert done["partners"][0]["state"] == "failed"


def test_partners_and_twins_are_read_in_parallel(session_factory):
    lock = threading.Lock()
    running = {"now": 0, "most": 0}

    class Slow(FakePartnerClient):
        def find_twin(self, partner, global_asset_id):
            with lock:
                running["now"] += 1
                running["most"] = max(running["most"], running["now"])
            time.sleep(0.05)
            try:
                return super().find_twin(partner, global_asset_id)
            finally:
                with lock:
                    running["now"] -= 1

    report = _partner_sync(
        session_factory,
        Slow(scenario.tier2_twins(), scenario.tier2_payloads()),
        parallel_partners=2,
        parallel_twins=3,
    ).run()

    assert running["most"] == 3
    tier2 = next(r for r in report.partners if r.bpnl == scenario.TIER2)
    # The same outcome as one at a time.
    assert (tier2.twins_found, tier2.twins_missing, tier2.parts_cached) == (2, 1, 2)
    assert [r.bpnl for r in report.partners] == sorted([scenario.TIER2, scenario.OEM])


def test_parts_are_saved_in_batches_as_they_are_read(session_factory, monkeypatch):
    monkeypatch.setattr(partner_sync, "SAVE_BATCH", 1)
    cells = sorted([scenario.CELL_1, scenario.CELL_3])  # the two TIER2 has
    saved_before_last = []

    class Watching(FakePartnerClient):
        def find_twin(self, partner, global_asset_id):
            if global_asset_id == cells[-1]:
                with session_factory() as session:
                    saved_before_last.append(PartRepository(session).get_part(cells[0]))
            return super().find_twin(partner, global_asset_id)

    _partner_sync(session_factory, Watching(scenario.tier2_twins(), scenario.tier2_payloads())).run(
        only_bpnl=scenario.TIER2
    )
    assert saved_before_last[0] is not None


def test_an_unexpected_error_fails_that_twin_not_the_run(session_factory):
    class Broken(FakePartnerClient):
        def find_twin(self, partner, global_asset_id):
            if global_asset_id == scenario.CELL_1:
                raise KeyError("endpoint")
            return super().find_twin(partner, global_asset_id)

    report = _partner_sync(
        session_factory, Broken(scenario.tier2_twins(), scenario.tier2_payloads())
    ).run()
    tier2 = next(r for r in report.partners if r.bpnl == scenario.TIER2)
    assert (tier2.status, tier2.twins_found) == ("partial", 1)
    assert any("unexpected error" in issue for issue in tier2.issues)


def test_a_sync_that_is_not_full_skips_twins_read_recently(session_factory):
    _partner_sync(session_factory).run(only_bpnl=scenario.TIER2)
    client = FakePartnerClient(scenario.tier2_twins(), scenario.tier2_payloads())
    sync = _partner_sync(session_factory, client)

    report = sync.run(only_bpnl=scenario.TIER2, full=False)

    result = report.partners[0]
    # The two cached parts are fresh; the twin TIER2 does not have is looked up again.
    assert {gid for _, gid in client.lookups} == {scenario.CELL_2}
    assert (result.twins_fresh, result.twins_found, result.twins_missing) == (2, 0, 1)
    assert (result.status, result.removed_parts) == ("partial", 0)
    progress = sync.progress.snapshot()
    assert (progress["full"], progress["twins_fresh"], progress["twins_done"]) == (False, 2, 3)
    with session_factory() as session:
        assert PartRepository(session).get_part(scenario.CELL_1) is not None  # kept
        assert PartnerRepository(session).get(scenario.TIER2).twins_found == 2


def test_twins_read_longer_ago_than_the_maximum_age_are_read_again(session_factory):
    _partner_sync(session_factory).run(only_bpnl=scenario.TIER2)
    client = FakePartnerClient(scenario.tier2_twins(), scenario.tier2_payloads())
    later = PartnerSync(
        client,
        session_factory,
        scenario.TIER1,
        configured_connectors={scenario.TIER2: scenario.TIER2_CONNECTOR},
        clock=lambda: CLOCK + timedelta(hours=25),
    )
    report = later.run(only_bpnl=scenario.TIER2, full=False)
    assert report.partners[0].twins_fresh == 0
    assert len(client.lookups) == 3


def test_the_periodic_sync_leaves_a_failing_partner_alone_for_a_while(session_factory):
    now = {"t": CLOCK}
    client = FakePartnerClient({}, {}, unreachable={scenario.TIER2})
    sync = PartnerSync(
        client,
        session_factory,
        scenario.TIER1,
        configured_connectors={scenario.TIER2: scenario.TIER2_CONNECTOR},
        clock=lambda: now["t"],
        backoff_after=2,
    )

    def tier2(report):
        return next(r for r in report.partners if r.bpnl == scenario.TIER2)

    assert tier2(sync()).status == "failed"
    assert tier2(sync()).status == "failed"
    with session_factory() as session:
        assert PartnerRepository(session).get(scenario.TIER2).consecutive_failures == 2
    skipped = tier2(sync())
    assert skipped.status == "backoff"
    assert "left alone after 2 failed syncs in a row" in skipped.issues[0]
    # A sync someone asks for still tries it.
    assert tier2(sync.run()).status == "failed"
    # Three failures now: it waits 15 min × 2 after the last one.
    now["t"] = CLOCK + timedelta(minutes=29)
    assert tier2(sync()).status == "backoff"
    now["t"] = CLOCK + timedelta(minutes=31)
    client.unreachable = set()
    client.twins, client.reader = scenario.tier2_twins(), FakeReader(scenario.tier2_payloads())
    assert tier2(sync()).status == "partial"
    with session_factory() as session:
        assert PartnerRepository(session).get(scenario.TIER2).consecutive_failures == 0


def test_every_run_is_stored_in_the_history(session_factory):
    sync = _partner_sync(session_factory)
    sync.run()
    sync()
    with session_factory() as session:
        runs = PartnerSyncRunRepository(session).recent()
    assert [(r.trigger, r.full) for r in runs] == [("periodic", False), ("manual", True)]
    manual = runs[1]
    assert (manual.partners_total, manual.linked_twins, manual.twins_cached) == (2, 4, 2)
    assert {p["bpnl"]: p["state"] for p in manual.partners} == {
        scenario.TIER2: "partial",
        scenario.OEM: "no_connector",
    }
    assert runs[0].twins_fresh == 2
