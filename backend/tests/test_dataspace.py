import pytest
import requests
import responses
from builders import BOM_V4, SERIAL_PART_V4, shell_descriptor
from responses import matchers
from tractusx_sdk.industry.services import AasService

from catenax_simplified.dataspace import DataspaceError, SubmodelRef
from catenax_simplified.dataspace.dtr import SdkTwinRegistry, twin_from_descriptor
from catenax_simplified.dataspace.submodels import HttpSubmodelReader, rewrite, value_url

DTR = "https://dtr.example"
SHELLS_URL = f"{DTR}/api/v3/shell-descriptors"
GID_1 = "urn:uuid:11111111-0000-4000-8000-000000000001"
GID_2 = "urn:uuid:11111111-0000-4000-8000-000000000002"


def _registry() -> SdkTwinRegistry:
    service = AasService(base_url=DTR, base_lookup_url=DTR, api_path="/api/v3")
    return SdkTwinRegistry(service, page_size=1, bpn="BPNL000000000T1A")


@responses.activate
def test_sdk_registry_follows_cursor_and_maps_descriptors():
    responses.get(
        SHELLS_URL,
        match=[matchers.query_param_matcher({"limit": "1"})],
        json={
            "paging_metadata": {"cursor": "page-2"},
            "result": [
                shell_descriptor(
                    GID_1,
                    {SERIAL_PART_V4: "https://edc.example/api/public/a/submodel"},
                    manufacturer_id="BPNL000000000T1A",
                )
            ],
        },
    )
    responses.get(
        SHELLS_URL,
        match=[matchers.query_param_matcher({"limit": "1", "cursor": "page-2"})],
        json={"paging_metadata": {}, "result": [shell_descriptor(GID_2, {BOM_V4: "https://b"})]},
    )

    twins = list(_registry().iter_twins())

    assert [t.global_asset_id for t in twins] == [GID_1, GID_2]
    assert twins[0].manufacturer_id == "BPNL000000000T1A"
    assert twins[0].submodels == (
        SubmodelRef(
            SERIAL_PART_V4,
            "https://edc.example/api/public/a/submodel",
            "SUBMODEL-3.0",
            "dspEndpoint=https://edc.example/api/v1/dsp;id=x",
        ),
    )
    assert twins[1].manufacturer_id is None
    # The SDK forwards the BPN header used for specificAssetId visibility.
    assert responses.calls[0].request.headers["Edc-Bpn"] == "BPNL000000000T1A"


@responses.activate
def test_sdk_registry_error_becomes_dataspace_error():
    responses.get(SHELLS_URL, status=401, json={"messages": [{"text": "unauthorized"}]})
    with pytest.raises(DataspaceError):
        list(_registry().iter_twins())


@responses.activate
def test_sdk_registry_connection_error_becomes_dataspace_error():
    responses.get(SHELLS_URL, body=requests.ConnectionError("refused"))
    with pytest.raises(DataspaceError, match="refused"):
        list(_registry().iter_twins())


def test_descriptor_without_global_asset_id_is_skipped():
    assert twin_from_descriptor({"id": "x", "submodelDescriptors": []}) is None


@pytest.mark.parametrize(
    ("href", "interface", "expected"),
    [
        ("https://dp/api/public/submodel", "SUBMODEL-3.0", "https://dp/api/public/submodel/$value"),
        ("https://dp/api/public/submodel/", None, "https://dp/api/public/submodel/$value"),
        (
            "https://dp/api/public/submodel/$value",
            "SUBMODEL-VALUE-3.1",
            "https://dp/api/public/submodel/$value",
        ),
        ("https://dp/x/$value", "SUBMODEL-3.1", "https://dp/x/$value"),
    ],
)
def test_value_url(href, interface, expected):
    assert value_url(SubmodelRef("urn:samm:x:1.0.0#X", href, interface)) == expected


def test_rewrite_uses_first_matching_prefix():
    rewrites = [
        ("https://edc/api/public", "http://backend:8080/data"),
        ("https://edc", "http://other"),
    ]
    assert (
        rewrite("https://edc/api/public/a/submodel", rewrites)
        == "http://backend:8080/data/a/submodel"
    )
    assert rewrite("https://unrelated/a", rewrites) == "https://unrelated/a"


@responses.activate
def test_http_reader_rewrites_and_sends_headers():
    responses.get(
        "http://backend/data/a/submodel/$value",
        json={"globalAssetId": GID_1},
        match=[matchers.header_matcher({"X-Api-Key": "secret"})],
    )
    reader = HttpSubmodelReader(
        rewrites=[("https://edc/api/public", "http://backend/data")],
        headers={"X-Api-Key": "secret"},
    )
    payload = reader.read(SubmodelRef(SERIAL_PART_V4, "https://edc/api/public/a/submodel"))
    assert payload == {"globalAssetId": GID_1}


@responses.activate
@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"status": 404}, "HTTP 404"),
        ({"body": "not json"}, "did not return JSON"),
        ({"json": [1, 2]}, "JSON object"),
        ({"body": requests.ConnectionError("down")}, "down"),
    ],
)
def test_http_reader_errors(kwargs, message):
    responses.get("https://edc/x/submodel/$value", **kwargs)
    with pytest.raises(DataspaceError, match=message):
        HttpSubmodelReader().read(SubmodelRef(SERIAL_PART_V4, "https://edc/x/submodel"))
