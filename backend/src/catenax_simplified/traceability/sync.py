"""Synchronizes the participant's own twins from its DTR into the local cache."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from .. import aspects
from ..aspects.ids import normalize_global_asset_id
from ..dataspace import DataspaceError, SubmodelReader, TwinRef, TwinRegistry
from ..storage import PartRepository, SyncRunRepository, SyncRunRow

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncIssue:
    global_asset_id: str
    semantic_id: str | None
    message: str


@dataclass
class SyncReport:
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
    def __init__(
        self,
        registry: TwinRegistry,
        reader: SubmodelReader,
        session_factory: sessionmaker[Session],
        own_bpnl: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._registry = registry
        self._reader = reader
        self._session_factory = session_factory
        self._own_bpnl = own_bpnl
        self._clock = clock

    def run(self) -> SyncReport:
        report = SyncReport(started_at=self._clock())
        seen: set[str] = set()
        try:
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

    def _sync_twin(self, twin: TwinRef, report: SyncReport) -> None:
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
