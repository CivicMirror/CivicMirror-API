from dataclasses import dataclass
from typing import Protocol

from .contracts import (
    CertificationEvidence,
    ElectionRecord,
    PostElectionBatch,
    PreElectionBatch,
)


class ElectionDiscoverySource(Protocol):
    source_system: str

    def acquire(self) -> bytes: ...

    def parse(self, content: bytes) -> tuple[ElectionRecord, ...]: ...


class CandidateSource(Protocol):
    source_system: str

    def acquire(self) -> bytes: ...

    def parse(
        self,
        content: bytes,
        *,
        discovered_elections: tuple[ElectionRecord, ...] = (),
    ) -> PreElectionBatch: ...


class ResultsSource(Protocol):
    source_system: str

    def acquire(self) -> bytes: ...

    def parse(
        self,
        content: bytes,
        *,
        existing_elections: tuple[ElectionRecord, ...] = (),
    ) -> PostElectionBatch: ...


class CertificationSource(Protocol):
    source_system: str

    def acquire(self) -> bytes: ...

    def parse(self, content: bytes) -> tuple[CertificationEvidence, ...]: ...


@dataclass(frozen=True, slots=True)
class StateCapabilities:
    election_discovery: ElectionDiscoverySource | None = None
    candidates: CandidateSource | None = None
    results: ResultsSource | None = None
    certification: CertificationSource | None = None


class UnsupportedStateError(LookupError):
    pass


class UnsupportedCapabilityError(LookupError):
    pass


class DuplicateStateRegistrationError(ValueError):
    pass


class CapabilityRegistry:
    CAPABILITY_NAMES = ("election_discovery", "candidates", "results", "certification")

    def __init__(self, enabled_states: tuple[str, ...]):
        self._enabled_states = frozenset(state.upper() for state in enabled_states)
        self._states: dict[str, StateCapabilities] = {}

    def register(self, state: str, capabilities: StateCapabilities) -> None:
        normalized_state = state.upper()
        if normalized_state not in self._enabled_states:
            raise UnsupportedStateError(f"State {normalized_state} is not enabled")
        if normalized_state in self._states:
            raise DuplicateStateRegistrationError(f"State {normalized_state} is already registered")
        self._states[normalized_state] = capabilities

    def get(self, state: str, capability: str):
        normalized_state = state.upper()
        if capability not in self.CAPABILITY_NAMES:
            raise UnsupportedCapabilityError(f"Capability {capability} is unknown")
        if normalized_state not in self._enabled_states:
            raise UnsupportedStateError(f"State {normalized_state} is not enabled")
        capabilities = self._states.get(normalized_state)
        implementation = getattr(capabilities, capability, None) if capabilities else None
        if implementation is None:
            raise UnsupportedCapabilityError(f"State {normalized_state} does not support {capability}")
        return implementation

    def supported_capabilities(self, state: str) -> tuple[str, ...]:
        normalized_state = state.upper()
        if normalized_state not in self._enabled_states:
            raise UnsupportedStateError(f"State {normalized_state} is not enabled")
        capabilities = self._states.get(normalized_state)
        if capabilities is None:
            return ()
        return tuple(name for name in self.CAPABILITY_NAMES if getattr(capabilities, name) is not None)
