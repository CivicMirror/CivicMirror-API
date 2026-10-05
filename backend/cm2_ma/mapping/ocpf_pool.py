from dataclasses import dataclass

from cm2_ma.source_records import OcpfCandidateRow, OcpfDistrict


def _normalize_name(first_name: str, last_name: str) -> str:
    return " ".join(f"{first_name} {last_name}".casefold().split())


@dataclass(frozen=True, slots=True)
class OcpfCandidatePool:
    """
    In-memory matching aid combining OCPF's district-code reference table
    and its "plausibly active" (Closed Date empty) candidate-filer pool.

    Never persists anything -- a later plan queries this to pre-resolve
    candidate identity while building Secretary-page CandidateFilingRecords.
    See docs/superpowers/specs/2026-08-17-cm2-ma-pilot-design.md, "Candidate
    identity: OCPF as source, Secretary as confirmation".
    """

    districts: dict[int, OcpfDistrict]
    active_candidates: tuple[OcpfCandidateRow, ...]

    @classmethod
    def build(
        cls,
        *,
        districts: tuple[OcpfDistrict, ...],
        candidates: tuple[OcpfCandidateRow, ...],
    ) -> "OcpfCandidatePool":
        district_by_code = {district.district_code: district for district in districts}
        active = tuple(candidate for candidate in candidates if not candidate.closed_date)
        return cls(districts=district_by_code, active_candidates=active)

    def find_by_name_and_district_code(
        self, *, full_name: str, district_code: int
    ) -> OcpfCandidateRow | None:
        target_name = " ".join(full_name.casefold().split())
        matches = [
            candidate
            for candidate in self.active_candidates
            if candidate.district_code_sought == district_code
            and _normalize_name(candidate.first_name, candidate.last_name) == target_name
        ]
        if len(matches) != 1:
            return None
        return matches[0]
