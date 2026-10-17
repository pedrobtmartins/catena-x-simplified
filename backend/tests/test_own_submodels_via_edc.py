import pytest
import responses
import scenario

from catenax_simplified.config import Settings
from catenax_simplified.dataspace import DataspaceError, SubmodelRef
from catenax_simplified.dataspace.partners import EdcPartnerClient
from catenax_simplified.dataspace.submodels import (
    EdcFallbackSubmodelReader,
    HttpSubmodelReader,
    SubmodelHttpError,
)
from catenax_simplified.wiring import build_submodel_reader

PLANE = "https://dataplane.example/public"
OTHER_PLANE = "https://other-plane.example/public"
BODY = "dspEndpoint=https://edc.example/api/v1/dsp;id=asset-1"


def _ref(base, twin):
    return SubmodelRef(
        semantic_id="urn:samm:io.catenax.serial_part:3.0.0#SerialPart",
        href=f"{base}/{twin}/submodel",
        interface="SUBMODEL-3.0",
        subprotocol_body=BODY,
    )


@responses.activate
def test_refused_data_plane_is_read_through_the_edc_from_then_on():
    responses.get(f"{PLANE}/t1/submodel/$value", status=401)
    responses.get(f"{OTHER_PLANE}/t3/submodel/$value", json={"direct": True})
    via_edc = []
    reader = EdcFallbackSubmodelReader(
        HttpSubmodelReader(), lambda ref: via_edc.append(ref.href) or {"via": "edc"}
    )
    assert reader.read(_ref(PLANE, "t1")) == {"via": "edc"}
    # The same data plane is not asked directly again.
    assert reader.read(_ref(PLANE, "t2")) == {"via": "edc"}
    assert reader.read(_ref(OTHER_PLANE, "t3")) == {"direct": True}
    assert via_edc == [f"{PLANE}/t1/submodel", f"{PLANE}/t2/submodel"]
    assert len(responses.calls) == 2


@responses.activate
def test_other_errors_are_not_retried_through_the_edc():
    responses.get(f"{PLANE}/t1/submodel/$value", status=404)
    reader = EdcFallbackSubmodelReader(HttpSubmodelReader(), lambda ref: pytest.fail("no EDC"))
    with pytest.raises(SubmodelHttpError) as error:
        reader.read(_ref(PLANE, "t1"))
    assert error.value.status == 404


def test_the_edc_fallback_needs_an_edc_and_the_own_dsp_endpoint():
    settings = Settings(own_bpnl=scenario.TIER1)
    assert isinstance(build_submodel_reader(settings), HttpSubmodelReader)
    client = EdcPartnerClient(consumer=object(), accepted_policies=[{"permission": {}}])
    reader = build_submodel_reader(settings, client)
    assert isinstance(reader, EdcFallbackSubmodelReader)
    no_endpoint = SubmodelRef("urn:x", f"{PLANE}/t1/submodel", "SUBMODEL-3.0", "id=asset-1")
    with responses.RequestsMock() as mock:
        mock.get(f"{PLANE}/t1/submodel/$value", status=401)
        with pytest.raises(DataspaceError, match="names no dspEndpoint of the own connector"):
            reader.read(no_endpoint)


def test_a_refused_read_negotiates_with_the_own_connector(monkeypatch):
    settings = Settings(own_bpnl=scenario.TIER1)
    client = EdcPartnerClient(consumer=object(), accepted_policies=None)
    calls = []
    monkeypatch.setattr(
        client, "read_submodel", lambda partner, ref: calls.append((partner, ref)) or {"v": 1}
    )
    reader = build_submodel_reader(settings, client)
    ref = _ref(PLANE, "t1")
    with responses.RequestsMock() as mock:
        mock.get(f"{PLANE}/t1/submodel/$value", status=403)
        assert reader.read(ref) == {"v": 1}
    [(partner, read_ref)] = calls
    assert partner.bpnl == scenario.TIER1
    assert read_ref is ref
