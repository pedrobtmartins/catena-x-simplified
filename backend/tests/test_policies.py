import pytest

from catenax_simplified.dataspace import DataspaceError
from catenax_simplified.dataspace.edc import (
    DCT_TYPE_KEY,
    JUPITER_NEGOTIATION_CONTEXT,
    EdcNegotiator,
    equals,
)
from catenax_simplified.dataspace.policies import canonical, describe, offers_of, same_policy

DTR_TYPE = "https://w3id.org/catenax/taxonomy#DigitalTwinRegistry"

# A DTR offer from a Jupiter connector (DSP 0.8), as the own (Saturn) EDC returns it.
JUPITER_OFFER = {
    "@id": "ZHRy:ZHRyLWFzc2V0:NDA2",
    "@type": "odrl:Offer",
    "odrl:permission": {
        "odrl:action": {"@id": "odrl:use"},
        "odrl:constraint": {
            "odrl:and": [
                {
                    "odrl:leftOperand": {"@id": "cx-policy:FrameworkAgreement"},
                    "odrl:operator": {"@id": "odrl:eq"},
                    "odrl:rightOperand": "DataExchangeGovernance:1.0",
                },
                {
                    "odrl:leftOperand": {"@id": "cx-policy:UsagePurpose"},
                    "odrl:operator": {"@id": "odrl:eq"},
                    "odrl:rightOperand": "cx.core.digitalTwinRegistry:1",
                },
            ]
        },
    },
    "odrl:prohibition": [],
    "odrl:obligation": [],
}


def _accepted(*constraints, iri=True):
    prefix = "https://w3id.org/catenax/policy/" if iri else ""
    return {
        "permission": [
            {
                "action": "use",
                "constraint": [
                    {
                        "and": [
                            {
                                "leftOperand": f"{prefix}{left}",
                                "operator": "eq",
                                "rightOperand": right,
                            }
                            for left, right in constraints
                        ]
                    }
                ],
            }
        ]
    }


FRAMEWORK = ("FrameworkAgreement", "DataExchangeGovernance:1.0")
DTR_PURPOSE = ("UsagePurpose", "cx.core.digitalTwinRegistry:1")
MEMBERSHIP = ("Membership", "active")


@pytest.mark.parametrize("iri", [True, False])
def test_a_jupiter_offer_matches_the_same_policy_in_saturn_spelling(iri):
    # Order of the constraints does not matter either.
    assert same_policy(JUPITER_OFFER, _accepted(DTR_PURPOSE, FRAMEWORK, iri=iri))


def test_a_missing_or_different_constraint_does_not_match():
    assert not same_policy(JUPITER_OFFER, _accepted(FRAMEWORK, DTR_PURPOSE, MEMBERSHIP))
    assert not same_policy(
        JUPITER_OFFER, _accepted(FRAMEWORK, ("UsagePurpose", "cx.core.industrycore:1"))
    )


def test_canonical_form():
    assert canonical(JUPITER_OFFER) == {
        "permission": {
            "action": "use",
            "constraint": {
                "and": [
                    {
                        "leftOperand": "FrameworkAgreement",
                        "operator": "eq",
                        "rightOperand": "DataExchangeGovernance:1.0",
                    },
                    {
                        "leftOperand": "UsagePurpose",
                        "operator": "eq",
                        "rightOperand": "cx.core.digitalTwinRegistry:1",
                    },
                ]
            },
        }
    }


def test_describe():
    assert describe(JUPITER_OFFER) == (
        "FrameworkAgreement=DataExchangeGovernance:1.0, UsagePurpose=cx.core.digitalTwinRegistry:1"
    )
    isanyof = {
        "permission": {
            "action": "use",
            "constraint": {
                "leftOperand": "UsagePurpose",
                "operator": "isAnyOf",
                "rightOperand": ["a:1", "b:1"],
            },
        }
    }
    assert describe(isanyof) == "UsagePurpose isAnyOf a:1|b:1"


def test_offers_of_a_dataset():
    assert offers_of({"odrl:hasPolicy": JUPITER_OFFER}) == [JUPITER_OFFER]
    assert offers_of({"hasPolicy": [JUPITER_OFFER, JUPITER_OFFER]}) == [JUPITER_OFFER] * 2
    assert offers_of({}) == []


class Consumer:
    """A Jupiter partner's catalog; ``do_dsp`` succeeds only with the offered policy itself, as
    the SDK compares literally."""

    def __init__(self, offer=JUPITER_OFFER, start_fails=False):
        self.offer = offer
        self.start_fails = start_fails
        self.negotiations = []

    def get_discovery_info(self, bpnl, counter_party_address=None):
        return counter_party_address, bpnl, "dataspace-protocol-http"

    def get_catalog_with_filter(
        self,
        counter_party_id,
        counter_party_address,
        filter_expression,
        timeout=None,
        protocol=None,
    ):
        return {"dcat:dataset": {"@id": "dtr-asset", "odrl:hasPolicy": self.offer}}

    def do_dsp(
        self,
        counter_party_id,
        counter_party_address,
        filter_expression,
        policies,
        protocol,
        negotiation_context=None,
    ):
        assert negotiation_context == JUPITER_NEGOTIATION_CONTEXT  # DSP 0.8 partner
        self.negotiations.append((filter_expression, policies))
        body = {k: v for k, v in self.offer.items() if k not in ("@id", "@type")}
        if body not in policies:
            raise RuntimeError("PolicyMismatchError: no valid policy")
        if self.start_fails:
            raise RuntimeError("It was not possible to start the EDR Negotiation!")
        return "https://dtr.partner/api/v3", "token"


PARTNER = ("BPNL0000002RFANS", "https://edc.partner/api/v1/dsp")


def test_negotiation_with_a_jupiter_partner_accepts_the_equivalent_offer():
    consumer = Consumer()
    accepted = [_accepted(FRAMEWORK, DTR_PURPOSE, MEMBERSHIP), _accepted(FRAMEWORK, DTR_PURPOSE)]
    edc = EdcNegotiator(consumer, accepted)
    assert edc.negotiate(*PARTNER, [equals(DCT_TYPE_KEY, DTR_TYPE)]) == (
        "https://dtr.partner/api/v3",
        "token",
    )
    [(_, policies)] = consumer.negotiations
    assert policies[:2] == accepted
    assert policies[2]["odrl:permission"] == JUPITER_OFFER["odrl:permission"]


def test_a_policy_mismatch_lists_what_is_offered_and_accepted():
    edc = EdcNegotiator(Consumer(), [_accepted(FRAMEWORK, DTR_PURPOSE, MEMBERSHIP)])
    with pytest.raises(DataspaceError) as error:
        edc.negotiate(*PARTNER, [equals(DCT_TYPE_KEY, DTR_TYPE)])
    message = str(error.value)
    assert (
        "Offered: FrameworkAgreement=DataExchangeGovernance:1.0, "
        "UsagePurpose=cx.core.digitalTwinRegistry:1." in message
    )
    assert "Accepted: FrameworkAgreement=DataExchangeGovernance:1.0, Membership=active, " in message


def test_a_failure_after_a_matching_policy_does_not_list_the_offers():
    edc = EdcNegotiator(Consumer(start_fails=True), [_accepted(FRAMEWORK, DTR_PURPOSE)])
    with pytest.raises(DataspaceError) as error:
        edc.negotiate(*PARTNER, [equals(DCT_TYPE_KEY, DTR_TYPE)])
    assert "not possible to start the EDR Negotiation" in str(error.value)
    assert "Offered:" not in str(error.value)


def test_the_jupiter_context_declares_the_edc_prefix():
    # Jupiter offers use edc: operands (edc:BusinessPartnerNumber, edc:inForceDate).
    assert {"edc": "https://w3id.org/edc/v0.0.1/ns/"}.items() <= JUPITER_NEGOTIATION_CONTEXT[
        -1
    ].items()
