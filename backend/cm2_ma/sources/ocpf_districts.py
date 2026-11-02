import io
import zipfile

from cm2_ingestion.contracts import ContractValidationError
from cm2_ma.constants import OCPF_DISTRICT_CODE_LIST_URL
from cm2_ma.source_records import OcpfDistrict

from .http import MaPublicBytesSource

REQUIRED_COLUMNS = ("District_Code", "Office_Type_Description", "District_Description")


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def parse_district_codes(zip_bytes: bytes) -> tuple[OcpfDistrict, ...]:
    archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    txt_names = [name for name in archive.namelist() if name.endswith(".txt")]
    if not txt_names:
        raise ContractValidationError("district code ZIP has no .txt entry")

    with archive.open(txt_names[0]) as handle:
        lines = handle.read().decode("ascii", errors="replace").splitlines()
    if not lines:
        return ()

    headers = lines[0].split("\t")
    if list(headers) != list(REQUIRED_COLUMNS):
        raise ContractValidationError("district code file is missing required columns")

    districts = []
    for row_number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != len(headers):
            raise ContractValidationError(f"district code row {row_number} has the wrong column count")
        code_text, office_type, district_description = parts
        try:
            district_code = int(code_text.strip())
        except ValueError as exc:
            raise ContractValidationError(
                f"district code row {row_number} has an invalid District_Code"
            ) from exc
        districts.append(
            OcpfDistrict(
                district_code=district_code,
                office_type=office_type.strip(),
                district_description=_strip_quotes(district_description.strip()),
            )
        )
    return tuple(districts)


class OcpfDistrictCodeListSource(MaPublicBytesSource):
    url = OCPF_DISTRICT_CODE_LIST_URL

    def parse(self, content: bytes) -> tuple[OcpfDistrict, ...]:
        return parse_district_codes(content)
