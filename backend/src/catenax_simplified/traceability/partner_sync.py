"""Caches the twins of direct partners that own parts are linked to (one level only).

For every partner named in the own parts' BoM (suppliers) and usage (customers) relations, the
counterpart twins are looked up in the partner's registry and their SerialPart/Batch submodel is
read. Partners' own BoM or usage is never read: deeper levels travel through notifications.

A sync can also be limited to a selection of those twins (the supplier parts under one assembly,
picked in the UI): it then reads only them, and leaves the rest of the cache and the partners'
last-sync summary as they are.

Several partners are read at once, and several twins of one partner (both bounded: the second is
load on the partner's registry and data plane). The parts read are saved in batches, so a run
that breaks off keeps what it has read. A run is planned (``prepare``) before it is carried out
(``execute``), so the API can answer as soon as it is planned and let it run in the background;
``PartnerSyncProgress`` follows it twin by twin, for the UI to poll.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Collection, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from .. import aspects
from ..aspects.ids import normalize_global_asset_id
from ..dataspace import DataspaceError
from ..dataspace.partners import DataPlaneError, Partner, PartnerDataClient
from ..storage import PartnerRepository, PartRepository

log = logging.getLogger(__name__)

PART_ASPECTS = {aspects.AspectType.SERIAL_PART, aspects.AspectType.BATCH}
# The partner's registry answering one twin's lookup with an error is that twin's problem; this
# many in a row means it is failing for all of them, so the rest are not tried.
MAX_LOOKUP_ERRORS_IN_A_ROW = 5
# Parts read are saved this many at a time: a run that breaks off keeps what it has read.
SAVE_BATCH = 50


@dataclass
class PartnerSyncResult:
    """What a partner sync read for one partner."""

    bpnl: str
    roles: list[str]
    linked_twins: int
    twins_found: int = 0
    twins_missing: int = 0
    removed_parts: int = 0
    # Twins found whose SerialPart/Batch submodel was read and cached.
    parts_cached: int = 0
    duration_seconds: float = 0.0
    status: str = "ok"  # ok | partial | failed | no_connector
    issues: list[str] = field(default_factory=list)


@dataclass
class PartnerSyncReport:
    """One partner sync run, per partner."""

    started_at: datetime
    finished_at: datetime | None = None
    partners: list[PartnerSyncResult] = field(default_factory=list)
    # The twins asked for that no own part is linked to (a selection only).
    not_linked: list[str] = field(default_factory=list)


@dataclass
class PartnerSyncPlan:
    """A run as planned: the partners to read, in order, their counterpart twins by role and
    their connector addresses. ``whole``: every counterpart (not a selection)."""

    run_id: int
    started_at: datetime
    partners: list[str]
    counterparts: dict[str, dict[str, set[str]]]
    addresses: dict[str, str | None]
    whole: bool
    not_linked: list[str] = field(default_factory=list)


class PartnerSyncProgress:
    """Where the running partner sync is (or how the last one ended), safe to read from another
    thread while the sync writes. ``snapshot`` is what the UI polls."""

    def __init__(self, monotonic: Callable[[], float] = time.monotonic):
        self._lock = threading.Lock()
        self._monotonic = monotonic
        self._state: dict | None = None
        self._runs = 0
        self._t0 = 0.0
        self._partner_t0: dict[str, float] = {}

    def start(self, started_at: datetime, plan: list[tuple[str, int]], selection: bool) -> int:
        """``plan``: the partners to sync, in order, with how many twins each. Returns the
        run's ID."""
        with self._lock:
            self._runs += 1
            self._t0 = self._monotonic()
            self._partner_t0 = {}
            self._state = {
                "run_id": self._runs,
                "running": True,
                "selection": selection,
                "started_at": started_at,
                "finished_at": None,
                "error": None,
                "report": None,
                "partners": [
                    {
                        "bpnl": bpnl,
                        "state": "pending",
                        "linked_twins": n,
                        "twins_done": 0,
                        "twins_cached": 0,
                        "twins_missing": 0,
                        "twins_failed": 0,
                        "removed_parts": 0,
                        "current_twin": None,
                        "duration_seconds": None,
                        "message": None,
                    }
                    for bpnl, n in plan
                ],
            }
            return self._runs

    def partner_started(self, bpnl: str) -> None:
        with self._lock:
            if row := self._row(bpnl):
                row["state"] = "running"
                self._partner_t0[bpnl] = self._monotonic()

    def twin_started(self, bpnl: str, gid: str) -> None:
        with self._lock:
            if row := self._row(bpnl):
                row["current_twin"] = gid

    def twin_done(self, bpnl: str, outcome: str) -> None:
        """``outcome``: cached (found and read) | missing | failed (lookup or read)."""
        with self._lock:
            if row := self._row(bpnl):
                row["twins_done"] += 1
                row[f"twins_{outcome}"] += 1

    def partner_finished(self, result: PartnerSyncResult) -> None:
        with self._lock:
            if row := self._row(result.bpnl):
                row["state"] = result.status
                # Twins not tried (no connector, stopped early) count as done: the run is past them.
                row["twins_done"] = row["linked_twins"]
                row["current_twin"] = None
                row["duration_seconds"] = result.duration_seconds
                row["removed_parts"] = result.removed_parts
                row["message"] = result.issues[0] if result.issues else None

    def finish(
        self, finished_at: datetime, report: PartnerSyncReport, error: str | None = None
    ) -> None:
        """The run is over; ``error``: why it broke off, if it did."""
        with self._lock:
            if self._state:
                for row in self._state["partners"]:
                    if row["state"] in ("pending", "running"):  # the run broke off
                        row["state"] = "failed"
                        row["current_twin"] = None
                self._state.update(
                    running=False, finished_at=finished_at, error=error, report=report
                )
                self._state["elapsed_seconds"] = self._monotonic() - self._t0

    def snapshot(self) -> dict | None:
        """A copy of the state with totals, or ``None`` before the first run."""
        with self._lock:
            if self._state is None:
                return None
            state = {**self._state, "partners": [dict(p) for p in self._state["partners"]]}
            if state["running"]:
                now = self._monotonic()
                state["elapsed_seconds"] = now - self._t0
                for row in state["partners"]:
                    if row["state"] == "running":
                        row["duration_seconds"] = now - self._partner_t0[row["bpnl"]]
        rows = state["partners"]
        state["partners_total"] = len(rows)
        state["partners_running"] = sum(r["state"] == "running" for r in rows)
        state["partners_done"] = sum(r["state"] not in ("pending", "running") for r in rows)
        for key in (
            "linked_twins",
            "twins_done",
            "twins_cached",
            "twins_missing",
            "twins_failed",
            "removed_parts",
        ):
            state[key] = sum(r[key] for r in rows)
        return state

    def _row(self, bpnl: str) -> dict | None:
        if self._state is None:
            return None
        return next((r for r in self._state["partners"] if r["bpnl"] == bpnl), None)


@dataclass
class _TwinRead:
    """How reading one twin went. ``kind``: cached | missing | unreadable (found, but no part
    read from it) | lookup_failed (the partner's data plane answered with an error) |
    unreachable (the registry cannot be reached at all)."""

    gid: str
    kind: str
    part: aspects.Part | None = None
    issues: list[str] = field(default_factory=list)


class PartnerSync:
    """Caches the direct partners' counterpart twins (one level, through
    ``PartnerDataClient``) and records per partner how it went. Partner parts no longer
    linked to an own part are removed.
    """

    def __init__(
        self,
        client: PartnerDataClient,
        session_factory: sessionmaker[Session],
        own_bpnl: str,
        configured_connectors: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        progress: PartnerSyncProgress | None = None,
        parallel_partners: int = 4,
        parallel_twins: int = 4,
    ):
        """``configured_connectors``: BPNL → DSP address from the settings; an address stored
        for the partner (set through the API) takes precedence. ``progress`` is kept up to date
        while a run goes (one is made when not given). ``parallel_partners``: partners read at
        once; ``parallel_twins``: twins of one partner read at once."""
        self._client = client
        self._session_factory = session_factory
        self._own_bpnl = own_bpnl
        self._configured = dict(configured_connectors or {})
        self._clock = clock
        self.progress = progress or PartnerSyncProgress()
        self._parallel_partners = max(1, parallel_partners)
        self._parallel_twins = max(1, parallel_twins)
        # One writer at a time: partners read in parallel save through the same database.
        self._db_lock = threading.Lock()

    def __call__(
        self, only_bpnl: str | None = None, only_twins: Collection[str] | None = None
    ) -> PartnerSyncReport:
        return self.run(only_bpnl, only_twins)

    def run(
        self, only_bpnl: str | None = None, only_twins: Collection[str] | None = None
    ) -> PartnerSyncReport:
        """Syncs every direct partner, or only ``only_bpnl``; the own BPNL is never a partner.
        With ``only_twins``, reads only those counterpart twins, from the partners that own
        them."""
        return self.execute(self.prepare(only_bpnl, only_twins))

    def prepare(
        self, only_bpnl: str | None = None, only_twins: Collection[str] | None = None
    ) -> PartnerSyncPlan:
        """Plans a run (see ``run``) and starts following it in ``progress``."""
        started_at = self._clock()
        with self._session_factory() as session:
            counterparts = PartRepository(session).partner_counterparts()
            stored = {row.bpnl: row.connector_address for row in PartnerRepository(session).all()}
        selection = set(only_twins) if only_twins is not None else None
        not_linked: list[str] = []
        if selection is not None:
            linked = {
                gid
                for bpnl, roles in counterparts.items()
                if bpnl != self._own_bpnl
                for gid in roles["supplier"] | roles["customer"]
            }
            not_linked = sorted(selection - linked)
            counterparts = {
                bpnl: {role: ids & selection for role, ids in roles.items()}
                for bpnl, roles in counterparts.items()
            }
        partners = [
            bpnl
            for bpnl in sorted(counterparts)
            if bpnl != self._own_bpnl
            and not (only_bpnl and bpnl != only_bpnl)
            and (
                selection is None
                or counterparts[bpnl]["supplier"]
                or counterparts[bpnl]["customer"]
            )
        ]
        run_id = self.progress.start(
            started_at,
            [(b, len(counterparts[b]["supplier"] | counterparts[b]["customer"])) for b in partners],
            selection=selection is not None,
        )
        return PartnerSyncPlan(
            run_id=run_id,
            started_at=started_at,
            partners=partners,
            counterparts={b: counterparts[b] for b in partners},
            addresses={b: stored.get(b) or self._configured.get(b) for b in partners},
            whole=selection is None,
            not_linked=not_linked,
        )

    def execute(self, plan: PartnerSyncPlan) -> PartnerSyncReport:
        """Carries out a planned run; ``progress`` follows it and holds its report at the end."""
        report = PartnerSyncReport(started_at=plan.started_at, not_linked=plan.not_linked)
        error = None
        try:
            with ThreadPoolExecutor(
                self._parallel_partners, thread_name_prefix="partner-sync"
            ) as pool:
                futures = [pool.submit(self._sync_one, plan, bpnl) for bpnl in plan.partners]
                report.partners = [f.result() for f in futures]
        except Exception as exc:
            error = f"the partner sync broke off: {exc}"
            raise
        finally:
            report.finished_at = self._clock()
            self.progress.finish(report.finished_at, report, error)
        return report

    def _sync_one(self, plan: PartnerSyncPlan, bpnl: str) -> PartnerSyncResult:
        """One partner of the run; an unexpected error fails that partner, not the run."""
        self.progress.partner_started(bpnl)
        t0 = time.monotonic()
        roles = plan.counterparts[bpnl]
        try:
            result = self._sync_partner(bpnl, roles, plan.addresses[bpnl], plan.whole)
        except Exception as exc:
            log.exception("partner sync of %s failed", bpnl)
            result = PartnerSyncResult(
                bpnl=bpnl,
                roles=[role for role in ("supplier", "customer") if roles[role]],
                linked_twins=len(roles["supplier"] | roles["customer"]),
                status="failed",
                issues=[f"unexpected error: {exc}"],
            )
        result.duration_seconds = round(time.monotonic() - t0, 3)
        self.progress.partner_finished(result)
        return result

    def _sync_partner(
        self, bpnl: str, roles: Mapping[str, set[str]], address: str | None, whole: bool
    ) -> PartnerSyncResult:
        """``whole``: every counterpart of the partner, so parts no longer linked are removed
        and the partner's last-sync summary is updated; a selection does neither."""
        twin_ids = sorted(roles["supplier"] | roles["customer"])
        result = PartnerSyncResult(
            bpnl=bpnl,
            roles=[role for role in ("supplier", "customer") if roles[role]],
            linked_twins=len(twin_ids),
        )
        if not address:
            result.status = "no_connector"
            result.issues.append("no connector address known for this partner")
            if whole:
                self._record(result)
            return result

        partner = Partner(bpnl=bpnl, connector_address=address)
        parts: list[aspects.Part] = []
        not_tried = self._read_twins(partner, twin_ids, result, parts)
        if not_tried and result.status == "failed":
            result.issues.append(f"{not_tried} twins not tried")
        self._save(bpnl, parts)
        if whole and result.status != "failed":
            with self._db_lock, self._session_factory.begin() as session:
                result.removed_parts = PartRepository(session).delete_partner_parts_except(
                    bpnl, set(twin_ids)
                )
        if result.status == "ok" and (result.issues or result.twins_missing):
            result.status = "partial"
        if whole:
            self._record(result)
        return result

    def _read_twins(
        self,
        partner: Partner,
        twin_ids: list[str],
        result: PartnerSyncResult,
        parts: list[aspects.Part],
    ) -> int:
        """Reads the twins, ``parallel_twins`` at a time, and handles their outcomes in order;
        parts are saved in batches as they come. Stops on an unreachable registry or after
        ``MAX_LOOKUP_ERRORS_IN_A_ROW`` failed lookups. Returns how many twins were not tried."""
        progress = self.progress
        pending = iter(twin_ids)
        submitted = 0
        stopped = False
        errors_in_a_row = 0
        in_flight: deque[Future[_TwinRead]] = deque()
        with ThreadPoolExecutor(
            self._parallel_twins, thread_name_prefix=f"twins-{partner.bpnl}"
        ) as pool:

            def fill() -> None:
                nonlocal submitted
                while not stopped and len(in_flight) < self._parallel_twins:
                    gid = next(pending, None)
                    if gid is None:
                        return
                    in_flight.append(pool.submit(self._read_twin, partner, gid))
                    submitted += 1

            fill()
            while in_flight:
                read = in_flight.popleft().result()
                if read.kind == "unreachable":
                    # The registry itself is unreachable: no point trying the remaining twins.
                    if not stopped:
                        result.status = "failed"
                        result.issues.extend(read.issues)
                    stopped = True
                    submitted -= 1  # it was not read
                    continue
                result.issues.extend(read.issues)
                if read.kind == "lookup_failed":
                    progress.twin_done(partner.bpnl, "failed")
                    errors_in_a_row += 1
                    if errors_in_a_row >= MAX_LOOKUP_ERRORS_IN_A_ROW and not stopped:
                        stopped = True
                        result.status = "failed"
                        result.issues.append(
                            f"stopped after {errors_in_a_row} lookups failed in a row"
                        )
                    fill()
                    continue
                errors_in_a_row = 0
                if read.kind == "missing":
                    result.twins_missing += 1
                    progress.twin_done(partner.bpnl, "missing")
                else:
                    result.twins_found += 1
                    if read.part is not None:
                        parts.append(read.part)
                        result.parts_cached += 1
                        if len(parts) >= SAVE_BATCH:
                            self._save(partner.bpnl, parts)
                    progress.twin_done(partner.bpnl, "cached" if read.part else "failed")
                fill()
        return len(twin_ids) - submitted

    def _read_twin(self, partner: Partner, gid: str) -> _TwinRead:
        """Looks one twin up and reads its part; runs in a worker thread."""
        self.progress.twin_started(partner.bpnl, gid)
        try:
            twin = self._client.find_twin(partner, gid)
        except DataPlaneError as exc:
            return _TwinRead(gid, "lookup_failed", issues=[f"{gid}: {exc}"])
        except DataspaceError as exc:
            return _TwinRead(gid, "unreachable", issues=[str(exc)])
        except Exception as exc:  # a bug or an unexpected answer: that twin's problem
            log.exception("reading %s from %s failed", gid, partner.bpnl)
            return _TwinRead(gid, "lookup_failed", issues=[f"{gid}: unexpected error: {exc}"])
        if twin is None:
            return _TwinRead(gid, "missing")
        issues: list[str] = []
        part = self._read_part(partner, twin, gid, issues)
        return _TwinRead(gid, "cached" if part else "unreadable", part=part, issues=issues)

    def _read_part(self, partner: Partner, twin, gid: str, issues: list[str]):
        refs = [
            ref
            for ref in twin.submodels
            if (supported := aspects.lookup(ref.semantic_id)) and supported.type in PART_ASPECTS
        ]
        if not refs:
            issues.append(f"{gid}: no supported SerialPart or Batch submodel")
            return None
        for ref in refs:
            try:
                part = aspects.parse(ref.semantic_id, self._client.read_submodel(partner, ref))
            except (DataspaceError, aspects.AspectPayloadError) as exc:
                issues.append(f"{gid}: {exc}")
                continue
            if part.global_asset_id != normalize_global_asset_id(gid):
                issues.append(f"{gid}: submodel describes {part.global_asset_id}")
                continue
            return part
        return None

    def _save(self, bpnl: str, parts: list[aspects.Part]) -> None:
        """Saves the parts read so far and empties the list."""
        if not parts:
            return
        synced_at = self._clock()
        with self._db_lock, self._session_factory.begin() as session:
            repository = PartRepository(session)
            for part in parts:
                repository.upsert_part(
                    part, manufacturer_id=bpnl, is_own=False, synced_at=synced_at
                )
        parts.clear()

    def _record(self, result: PartnerSyncResult) -> None:
        with self._db_lock, self._session_factory.begin() as session:
            row = PartnerRepository(session).get_or_create(result.bpnl)
            row.last_sync_at = self._clock()
            row.last_status = result.status
            row.last_message = "; ".join(result.issues)[:2000] or None
            row.twins_found = result.twins_found
            row.twins_missing = result.twins_missing
        log.info(
            "partner %s: %s (%d found, %d missing)",
            result.bpnl,
            result.status,
            result.twins_found,
            result.twins_missing,
        )
