import io
import zipfile

import pytest

from cm2_ingestion.contracts import ContractValidationError
from cm2_ma.constants import OCPF_DISTRICT_CODE_LIST_URL
from cm2_ma.sources.ocpf_districts import OcpfDistrictCodeListSource, parse_district_codes


def _district_zip_bytes(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("district_code_list.txt", text)
    return buffer.getvalue()


# Real header + real sample rows captured live from the source, including the
# CRLF line endings and the literal double-quote wrapping a comma-containing
# description that the live file actually uses.
_SAMPLE_TEXT = (
    "District_Code\tOffice_Type_Description\tDistrict_Description\r\n"
    "104\tSenate\t1st Plymouth & Bristol\r\n"
    "125\tSenate\t\"Norfolk, Bristol & Plymouth\"\r\n"
    "231\tHouse\t9th Essex\r\n"
    "1114\tStatewide\tAuditor\r\n"
)


def test_parses_rows_and_strips_quoted_comma_descriptions():
    districts = parse_district_codes(_district_zip_bytes(_SAMPLE_TEXT))

    assert len(districts) == 4
    by_code = {district.district_code: district for district in districts}
    assert by_code[104].office_type == "Senate"
    assert by_code[104].district_description == "1st Plymouth & Bristol"
    assert by_code[125].district_description == "Norfolk, Bristol & Plymouth"
    assert by_code[231].office_type == "House"
    assert by_code[1114].office_type == "Statewide"
    assert by_code[1114].district_description == "Auditor"


def test_rejects_missing_header_columns():
    bad_text = "Code\tType\tDescription\r\n104\tSenate\t1st Plymouth & Bristol\r\n"

    with pytest.raises(ContractValidationError, match="missing required columns"):
        parse_district_codes(_district_zip_bytes(bad_text))


def test_rejects_zip_with_no_txt_entry():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("district_code_list.xlsx", b"not actually an xlsx")

    with pytest.raises(ContractValidationError, match="no .txt entry"):
        parse_district_codes(buffer.getvalue())


def test_skips_blank_trailing_lines():
    text = _SAMPLE_TEXT + "\r\n"
    districts = parse_district_codes(_district_zip_bytes(text))
    assert len(districts) == 4


def test_source_url_and_parse_delegate_correctly():
    source = OcpfDistrictCodeListSource()
    assert source.url == OCPF_DISTRICT_CODE_LIST_URL

    districts = source.parse(_district_zip_bytes(_SAMPLE_TEXT))
    assert len(districts) == 4
