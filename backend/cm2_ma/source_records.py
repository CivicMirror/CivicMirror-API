from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OcpfDistrict:
    district_code: int
    office_type: str
    district_description: str
