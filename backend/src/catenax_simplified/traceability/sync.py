"""Synchronizes the participant's own twins from its DTR into the local cache.

Either the whole DTR, or a subset (``CXS_SYNC_TWIN_IDS``, e.g. to test with a few vehicles of a
registry with millions of twins): the listed twins and, through their bills of material, their
own children.
"""

from __future__ import annotations

import logging
import re
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from .. import aspects
from ..aspects.ids import normalize_global_asset_id
from ..dataspace import DataspaceError, SubmodelReader, TwinRef, TwinRegistry
from ..storage import PartRepository, SyncRunRepository, SyncRunRow

log = logging.getLogger(__name__)

_UUID_URN = re.compile(
    r"urn:uuid:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)


def parse_twin_ids(text: str | None) -> list[str]:
    """The twin IDs in ``text``: every ``urn:uuid:…`` in it (so a pasted CSV works), else the
    text split on whitespace, commas and semicolons. In order, without repeats."""
    if not text or not text.strip():
        return []
    ids = _UUID_URN.findall(text) or [t for t in re.split(r"[\s,;]+", text) if t]
    return list(dict.fromkeys(ids))


@dataclass(frozen=True)
class SyncIssue:
    """A problem with one twin or submodel; the sync records it and carries on."""

    global_asset_id: str
    semantic_id: str | None
    message: str


@dataclass
class SyncReport:
    """What one own-twin sync did. ``complete`` is set when the listing was read without
    error, which is also when stale own parts were removed.
    """

    started_at: datetime
    finished_at: datetime | None = None
    twins: int = 0
    parts: int = 0
    relation_sets: int = 0
    unsupported_submodels: int = 0
    removed_parts: int = 0
    complete: bool = False
    issues: list[SyncIssue] = field(default_factory=list)
    id: int | None = None  # set once the run is recorded


class OwnTwinSync:
    """Reads the own twins from the DTR into the local cache: their part aspect (SerialPart or
    Batch) and their BoM and usage relations, in any supported version.

    With ``twin_ids`` only those twins and, through their BoMs, their own children are
    read; otherwise the whole registry. A twin or submodel that cannot be read is reported
    and skipped; a failed listing aborts without deleting anything.
    """

    def __init__(
        self,
        registry: TwinRegistry,
        reader: SubmodelReader,
        session_factory: sessionmaker[Session],
        own_bpnl: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        twin_ids: list[str] | None = None,
    ):
        """``twin_ids``: load only these twins (AAS IDs or globalAssetIds) and their own
        children; None or empty loads the whole registry."""
        self._registry = registry
        self._reader = reader
        self._session_factory = session_factory
        self._own_bpnl = own_bpnl
        self._clock = clock
        self.current: SyncReport | None = None
        self._twin_ids = list(twin_ids or [])

    @property
    def subset(self) -> list[str]:
        """The twins a subset sync starts from; empty: the whole registry."""
        return list(self._twin_ids)

    def __call__(self) -> SyncReport:
        return self.run()

    def run(self) -> SyncReport:
        """One sync run, recorded in the history. ``current`` is the run going on (or the last
        one), counted up as it goes."""
        report = SyncReport(started_at=self._clock())
        self.current = report
        seen: set[str] = set()
        try:
            if self._twin_ids:
                self._sync_subset(report, seen)
            else:
                for twin in self._registry.iter_twins():
                    report.twins += 1
                    seen.add(normalize_global_asset_id(twin.global_asset_id))
                    self._sync_twin(twin, report)
        except DataspaceError as exc:
            # The listing is incomplete: keep the cache as is instead of deleting unseen parts.
            log.warning("own twin sync aborted: %s", exc)
            report.issues.append(SyncIssue("", None, f"registry listing failed: {exc}"))
        else:
            with self._session_factory.begin() as session:
                report.removed_parts = PartRepository(session).delete_own_parts_except(seen)
            report.complete = True
        report.finished_at = self._clock()
        self._record(report)
        return report

    def _sync_subset(self, report: SyncReport, seen: set[str]) -> None:
        """The listed twins, then (breadth first) the own children in their bills of material.
        A listed ID is an AAS ID, or else a globalAssetId; children are found by globalAssetId."""
        pending: deque[tuple[str, bool]] = deque((i, True) for i in self._twin_ids)
        loaded: set[str] = set()
        while pending:
            requested, listed = pending.popleft()
            if not listed and normalize_global_asset_id(requested) in seen:
                continue
            twins = self._resolve(requested, listed)
            if not twins:
                what = "listed twin" if listed else "own child"
                report.issues.append(
                    SyncIssue(requested, None, f"{what} not found in the registry")
                )
                continue
            for twin in twins:
                twin_id = normalize_global_asset_id(twin.global_asset_id)
                if twin.aas_id in loaded or twin_id in seen:
                    continue
                loaded.add(twin.aas_id)
                seen.add(twin_id)
                report.twins += 1
                for result in self._sync_twin(twin, report):
                    if isinstance(result, aspects.Relations) and result.source == "bom":
                        pending.extend(
                            (r.child_id, False)
                            for r in result.items
                            if r.business_partner == self._own_bpnl
                            and normalize_global_asset_id(r.child_id) not in seen
                        )

    def _resolve(self, requested: str, listed: bool) -> list[TwinRef]:
        if listed:
            twin = self._registry.get_twin(requested)
            if twin is not None:
                return [twin]
        twins = (self._registry.get_twin(i) for i in self._registry.find_aas_ids(requested))
        return [t for t in twins if t is not None]

    def _record(self, report: SyncReport) -> None:
        with self._session_factory.begin() as session:
            row = SyncRunRepository(session).add(
                SyncRunRow(
                    started_at=report.started_at,
                    finished_at=report.finished_at,
                    twins=report.twins,
                    parts=report.parts,
                    relation_sets=report.relation_sets,
                    unsupported_submodels=report.unsupported_submodels,
                    removed_parts=report.removed_parts,
                    complete=report.complete,
                    issues=[asdict(issue) for issue in report.issues],
                )
            )
            report.id = row.id

    def _sync_twin(
        self, twin: TwinRef, report: SyncReport
    ) -> list[aspects.Part | aspects.Relations]:
        twin_id = normalize_global_asset_id(twin.global_asset_id)
        parsed: list[aspects.Part | aspects.Relations] = []
        for ref in twin.submodels:
            if not aspects.is_supported(ref.semantic_id):
                report.unsupported_submodels += 1
                continue
            try:
                result = aspects.parse(ref.semantic_id, self._reader.read(ref))
            except (DataspaceError, aspects.AspectPayloadError) as exc:
                report.issues.append(SyncIssue(twin_id, ref.semantic_id, str(exc)))
                continue
            result_id = (
                result.global_asset_id if isinstance(result, aspects.Part) else result.declared_by
            )
            if result_id != twin_id:
                report.issues.append(
                    SyncIssue(
                        twin_id,
                        ref.semantic_id,
                        f"submodel describes {result_id}, not the twin's globalAssetId",
                    )
                )
                continue
            parsed.append(result)

        synced_at = self._clock()
        with self._session_factory.begin() as session:
            repository = PartRepository(session)
            for result in parsed:
                if isinstance(result, aspects.Part):
                    repository.upsert_part(
                        result,
                        manufacturer_id=twin.manufacturer_id or self._own_bpnl,
                        is_own=True,
                        synced_at=synced_at,
                    )
                    report.parts += 1
                else:
                    repository.replace_relations(result)
                    report.relation_sets += 1
        return parsed
