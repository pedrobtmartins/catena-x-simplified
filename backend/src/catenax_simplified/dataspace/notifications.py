"""Sending quality notifications to a partner's notification assets through the EDC.

Per the Traceability KIT: fetch the partner's catalog filtered by the asset's ``dct:type``,
choose the offer with the highest ``cx-common:version`` we implement (no compatible version →
no negotiation), negotiate for it and POST the payload to the data plane with the access token.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Protocol

import requests

from ..notifications.messages import api_version_of
from .edc import ASSET_ID_KEY, DCT_TYPE_KEYS, ConnectorConsumer, EdcNegotiator, Partner, equals
from .ports import DataspaceError

log = logging.getLogger(__name__)

_VERSION_KEYS = ("cx-common:version", "https://w3id.org/catenax/ontology/common#version")


class NotificationRejected(DataspaceError):
    """The partner's notification endpoint answered with an error status."""

    def __init__(self, bpnl: str, status_code: int, body: str):
        super().__init__(f"{bpnl} rejected the notification: HTTP {status_code} {body}".strip())
        self.status_code = status_code


@dataclass(frozen=True)
class Offer:
    asset_id: str
    offered_version: str | None
    api_version: str | None  # what we would serialize; None if incompatible


class NotificationSender(Protocol):
    def send(
        self, partner: Partner, asset_type: str, build: Callable[[str], dict[str, Any]]
    ) -> str:
        """Deliver ``build(api_version)`` to the partner's asset of this ``dct:type``; returns
        the Notification API version used. Raises ``DataspaceError``."""
        ...


def _datasets(node: Any) -> Iterator[dict]:
    """Every dataset-like object in a (possibly nested or federated) DCAT catalog."""
    if isinstance(node, list):
        for item in node:
            yield from _datasets(item)
    elif isinstance(node, dict):
        if any(key in node for key in _VERSION_KEYS):
            yield node
        for key, value in node.items():
            if key.split(":")[-1] in ("dataset", "catalog", "service") or key.endswith(
                ("#dataset", "#catalog")
            ):
                yield from _datasets(value)


def _scalar(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("@value", value.get("@id"))
    if isinstance(value, list):
        value = value[0] if value else None
    return str(value) if value is not None else None


def offers_in(catalog: Any) -> list[Offer]:
    offers = []
    for dataset in _datasets(catalog):
        asset_id = _scalar(dataset.get("@id") or dataset.get("id"))
        if not asset_id:
            continue
        version = next((_scalar(dataset[k]) for k in _VERSION_KEYS if k in dataset), None)
        offers.append(Offer(asset_id, version, api_version_of(version)))
    return offers


def choose_offer(offers: list[Offer]) -> Offer | None:
    compatible = [o for o in offers if o.api_version]
    if not compatible:
        return None
    return max(compatible, key=lambda o: tuple(int(p) for p in o.api_version.split(".")))


class EdcNotificationSender:
    def __init__(
        self,
        consumer: ConnectorConsumer,
        accepted_policies: list[dict] | None,
        session: requests.Session | None = None,
        timeout: float = 30.0,
    ):
        self._edc = EdcNegotiator(consumer, accepted_policies)
        self._session = session or requests.Session()
        self._timeout = timeout

    def _offers(self, partner: Partner, asset_type: str) -> list[Offer]:
        for key in DCT_TYPE_KEYS:
            catalog = self._edc.catalog(
                partner.bpnl, partner.connector_address, [equals(key, asset_type)]
            )
            offers = offers_in(catalog)
            if offers:
                return offers
        return []

    def send(
        self, partner: Partner, asset_type: str, build: Callable[[str], dict[str, Any]]
    ) -> str:
        offers = self._offers(partner, asset_type)
        offer = choose_offer(offers)
        if offer is None:
            offered = ", ".join(sorted({o.offered_version or "?" for o in offers})) or "none"
            raise DataspaceError(
                f"{partner.bpnl} offers no compatible {asset_type.rsplit('#', 1)[-1]} asset "
                f"(versions offered: {offered})"
            )
        endpoint, token = self._edc.negotiate(
            partner.bpnl, partner.connector_address, [equals(ASSET_ID_KEY, offer.asset_id)]
        )
        try:
            response = self._session.post(
                endpoint,
                json=build(offer.api_version),
                headers={"Authorization": token, "Content-Type": "application/json"},
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise DataspaceError(f"POST to {partner.bpnl} failed: {exc}") from exc
        if not response.ok:
            raise NotificationRejected(partner.bpnl, response.status_code, response.text[:500])
        log.info("sent %s to %s (API %s)", asset_type, partner.bpnl, offer.api_version)
        return offer.api_version
