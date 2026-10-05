from dataclasses import dataclass

import pytest

from cm2_ingestion.capabilities import (
    CapabilityRegistry,
    DuplicateStateRegistrationError,
    StateCapabilities,
    UnsupportedCapabilityError,
    UnsupportedStateError,
)
from cm2_nc.capabilities import build_nc_capabilities
from cm2_nc.sources.candidate_filings import NcCandidateFilingsSource
from cm2_nc.sources.upcoming_elections import NcUpcomingElectionsSource


@dataclass
class FixtureCandidateSource:
    source_system: str = "nc_sbe"


def test_registry_returns_only_the_requested_supported_capability():
    candidate_source = FixtureCandidateSource()
    registry = CapabilityRegistry(enabled_states=("NC",))
    registry.register("nc", StateCapabilities(candidates=candidate_source))

    assert registry.get("NC", "candidates") is candidate_source
    assert registry.supported_capabilities("NC") == ("candidates",)


def test_missing_capability_is_explicit_and_never_substituted():
    registry = CapabilityRegistry(enabled_states=("NC",))
    registry.register("NC", StateCapabilities(candidates=FixtureCandidateSource()))

    with pytest.raises(UnsupportedCapabilityError, match="results"):
        registry.get("NC", "results")


def test_disabled_state_cannot_register():
    registry = CapabilityRegistry(enabled_states=("NC",))

    with pytest.raises(UnsupportedStateError, match="SC"):
        registry.register("SC", StateCapabilities())


def test_duplicate_state_registration_is_rejected():
    registry = CapabilityRegistry(enabled_states=("NC",))
    registry.register("NC", StateCapabilities())

    with pytest.raises(DuplicateStateRegistrationError, match="NC"):
        registry.register("NC", StateCapabilities())


def test_unknown_capability_name_is_rejected():
    registry = CapabilityRegistry(enabled_states=("NC",))
    registry.register("NC", StateCapabilities())

    with pytest.raises(UnsupportedCapabilityError, match="unknown"):
        registry.get("NC", "unknown")


def test_nc_factory_registers_only_pre_election_capabilities():
    registry = CapabilityRegistry(enabled_states=("NC",))
    registry.register("NC", build_nc_capabilities())

    assert isinstance(registry.get("NC", "election_discovery"), NcUpcomingElectionsSource)
    assert isinstance(registry.get("NC", "candidates"), NcCandidateFilingsSource)
    assert registry.supported_capabilities("NC") == ("election_discovery", "candidates")
    with pytest.raises(UnsupportedCapabilityError, match="results"):
        registry.get("NC", "results")
    with pytest.raises(UnsupportedCapabilityError, match="certification"):
        registry.get("NC", "certification")
