from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from openpyxl import load_workbook

from results.adapters.base import ResultRow

from .exceptions import AlSosError
from .mappers import is_core_certification_office, normalize_certification_office

_MAX_CERTIFICATION_PDF_BYTES = 40 * 1024 * 1024
_MAX_CERTIFICATION_PDF_PAGES = 60
_OCR_DPI = 220
_CERTIFICATION_WORD_RE = re.compile(r"[A-Za-z]")

_PARTY_SUFFIX_RE = re.compile(r"\s+\(([A-Z]{2,5})\)\s*$")

_YEAR_PAGE_BASE_URL = "https://www.sos.alabama.gov"
_DASH_RE = re.compile(r"\s–\s")  # en dash only -- do not add ASCII hyphen-minus here,
# real election names may contain a plain " - " (e.g. "District 63 - Runoff") and a
# hyphen-inclusive class would split on the wrong dash and silently drop the election.


@dataclass(frozen=True)
class AlEnrParsedResult:
    rows: list[ResultRow]
    source_version: str
    is_complete: bool
    county_stats: dict[str, dict]


def parse_candidate_certification_table(
    table_rows: list[tuple[str, str]],
    *,
    party: str,
    document_label: str,
    source_url: str,
    sha256: str,
) -> list[dict]:
    """Normalize office/name cell pairs from a scanned certification table."""
    records = []
    for office, candidate_name in table_rows:
        office_title = normalize_certification_office(office)
        candidate_name = _clean_certification_name(candidate_name)
        if not office_title or not candidate_name:
            continue
        if not is_core_certification_office(office_title):
            continue
        if office_title.lower() in {"office", "state", "name"}:
            continue
        records.append({
            "office_title": office_title,
            "candidate_name": candidate_name,
            "party": party,
            "document_label": document_label,
            "source_url": source_url,
            "source_sha256": sha256,
        })
    return records


def parse_independent_candidate_certificate(
    lines: list[str],
    *,
    document_label: str,
    source_url: str,
    sha256: str,
) -> list[dict]:
    """Parse the office/name pairs used by Alabama's independent certificate."""
    records = []
    index = 0
    while index < len(lines):
        office = " ".join((lines[index] or "").split())
        if not re.match(r"^Alabama State (?:Senate|House of Representatives)\b", office, re.I):
            index += 1
            continue
        candidate_name = _clean_certification_name(lines[index + 1] if index + 1 < len(lines) else "")
        office_title = normalize_certification_office(office)
        if office_title and candidate_name and is_core_certification_office(office_title):
            records.append({
                "office_title": office_title,
                "candidate_name": candidate_name,
                "party": "IND",
                "document_label": document_label,
                "source_url": source_url,
                "source_sha256": sha256,
            })
            index += 2
        else:
            index += 1
    return records


def parse_candidate_certification_pdf(
    pdf_bytes: bytes,
    *,
    party: str,
    document_label: str,
    source_url: str,
    sha256: str,
) -> list[dict]:
    """OCR an Alabama candidate-certification PDF and return normalized candidates.

    Alabama SOS certifications are scanned images rather than text PDFs. The
    renderer and OCR engine are bounded subprocesses supplied by Poppler and
    Tesseract in the API runtime image.
    """
    if not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("candidate certification response is not a PDF")
    if len(pdf_bytes) > _MAX_CERTIFICATION_PDF_BYTES:
        raise ValueError("candidate certification PDF exceeds the 40 MiB limit")

    missing_tools = [tool for tool in ("pdftoppm", "tesseract") if shutil.which(tool) is None]
    if missing_tools:
        raise AlSosError(f"Alabama certification OCR requires: {', '.join(missing_tools)}")

    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            page_count = len(pdf.pages)
    except Exception as exc:
        raise ValueError(f"could not read candidate certification PDF: {exc}") from exc
    if page_count < 1 or page_count > _MAX_CERTIFICATION_PDF_PAGES:
        raise ValueError(f"candidate certification PDF has unsupported page count: {page_count}")

    records = []
    with tempfile.TemporaryDirectory(prefix="al-certification-") as temp_dir:
        temp_path = Path(temp_dir)
        pdf_path = temp_path / "certification.pdf"
        pdf_path.write_bytes(pdf_bytes)
        image_prefix = temp_path / "page"
        try:
            subprocess.run(
                [
                    "pdftoppm", "-f", "1", "-l", str(page_count), "-r", str(_OCR_DPI),
                    "-png", str(pdf_path), str(image_prefix),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise AlSosError(f"Alabama certification PDF rendering failed: {exc}") from exc

        images = sorted(temp_path.glob("page-*.png"))
        if len(images) != page_count:
            raise AlSosError(f"Alabama certification PDF rendered {len(images)} of {page_count} pages")

        for image_path in images:
            geometry = _certification_table_geometry(image_path)
            ocr_image_path = image_path
            rotation = _page_rotation(image_path) if geometry is None else 0
            if rotation:
                from PIL import Image

                ocr_image_path = image_path.with_name(f"{image_path.stem}-rotated.png")
                with Image.open(image_path) as image:
                    image.rotate(-rotation, expand=True).save(ocr_image_path)
            try:
                completed = subprocess.run(
                    ["tesseract", str(ocr_image_path), "stdout", "--psm", "4", "tsv"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise AlSosError(f"Alabama certification OCR failed on {image_path.name}: {exc}") from exc

            if geometry:
                rules, divider_x = geometry
                table_rows = _table_rows_from_tsv(completed.stdout, rules, divider_x)
                fallback_rows = _two_column_table_rows_from_tsv(
                    completed.stdout,
                    allow_headerless=True,
                )
                if len(fallback_rows) > len(table_rows):
                    table_rows = fallback_rows
                records.extend(parse_candidate_certification_table(
                    table_rows,
                    party=party,
                    document_label=document_label,
                    source_url=source_url,
                    sha256=sha256,
                ))
            elif rotation:
                records.extend(parse_candidate_certification_table(
                    _rotated_table_rows_from_tsv(completed.stdout),
                    party=party,
                    document_label=document_label,
                    source_url=source_url,
                    sha256=sha256,
                ))
            else:
                has_table_divider = _has_upright_table_divider(ocr_image_path)
                table_rows = _two_column_table_rows_from_tsv(
                    completed.stdout,
                    allow_headerless=has_table_divider,
                )
                if table_rows:
                    records.extend(parse_candidate_certification_table(
                        table_rows,
                        party=party,
                        document_label=document_label,
                        source_url=source_url,
                        sha256=sha256,
                    ))
                elif party == "IND":
                    records.extend(parse_independent_candidate_certificate(
                        _ocr_lines(completed.stdout),
                        document_label=document_label,
                        source_url=source_url,
                        sha256=sha256,
                    ))

    if not records:
        raise AlSosError(f"Alabama certification OCR found no candidate rows in {source_url}")
    return records


def _clean_certification_name(value: str) -> str:
    cleaned = " ".join((value or "").replace("\u00a0", " ").split()).strip(" |_{}'\t")
    cleaned = re.sub(r"\s+(?:RECEIVED|STORY|ELECTIONS|ALABAMA)\b.*$", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+(?:il|l)\s*$", "", cleaned)
    if not cleaned or not _CERTIFICATION_WORD_RE.search(cleaned):
        return ""
    if re.search(r"\d", cleaned):
        return ""
    if cleaned.lower() in {"office", "name", "candidate", "witness", "signature"}:
        return ""
    return cleaned


def _read_ocr_words(tsv_text: str) -> list[dict]:
    words = []
    for row in csv.DictReader(io.StringIO(tsv_text), delimiter="\t"):
        if row.get("level") != "5" or not row.get("text", "").strip():
            continue
        try:
            words.append({
                "left": int(row["left"]),
                "top": int(row["top"]),
                "width": int(row["width"]),
                "height": int(row["height"]),
                "text": row["text"].strip(),
                "line": (row["block_num"], row["par_num"], row["line_num"]),
            })
        except (KeyError, ValueError):
            continue
    return words


def _table_rows_from_tsv(tsv_text: str, horizontal_rules: list[int], divider_x: int) -> list[tuple[str, str]]:
    words = _read_ocr_words(tsv_text)
    table_rows = []
    for top, bottom in zip(horizontal_rules, horizontal_rules[1:]):
        if bottom - top < 4:
            continue
        left_words = []
        right_words = []
        for word in words:
            center_y = word["top"] + word["height"] / 2
            if not top < center_y < bottom:
                continue
            center_x = word["left"] + word["width"] / 2
            (left_words if center_x < divider_x else right_words).append(word)
        # OCR boxes on the same printed baseline can have different top values;
        # sorting top-first can reverse words such as "Jerry Carl".
        left_words.sort(key=lambda word: word["left"])
        right_words.sort(key=lambda word: word["left"])
        office = " ".join(word["text"] for word in left_words)
        candidate_name = " ".join(word["text"] for word in right_words)
        if office or candidate_name:
            table_rows.append((office, candidate_name))
    return table_rows


def _ocr_lines(tsv_text: str) -> list[str]:
    words = _read_ocr_words(tsv_text)
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for word in words:
        grouped[word["line"]].append(word)
    lines = []
    for line_words in sorted(grouped.values(), key=lambda group: min(word["top"] for word in group)):
        line_words.sort(key=lambda word: word["left"])
        lines.append(" ".join(word["text"] for word in line_words))
    return lines


def _page_rotation(image_path: Path) -> int:
    """Ask Tesseract OSD whether a scanned page is rotated from readable orientation."""
    try:
        completed = subprocess.run(
            ["tesseract", str(image_path), "stdout", "--psm", "0"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    match = re.search(r"^Rotate:\s*(0|90|180|270)\s*$", completed.stdout, re.MULTILINE)
    return int(match.group(1)) if match else 0


def _rotated_table_rows_from_tsv(tsv_text: str) -> list[tuple[str, str]]:
    """Read Alabama's rotated Office / District / Place / Ballot Name table."""
    words = _read_ocr_words(tsv_text)
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for word in words:
        groups[word["line"]].append(word)

    ordered_groups = sorted(groups.values(), key=lambda group: min(word["top"] for word in group))
    flattened = [word for group in ordered_groups for word in group]
    place_header = next(
        (word["left"] for word in flattened if word["text"].lower().strip("|{}[],:;") == "place"), None
    )
    ballot_header = next(
        (word["left"] for word in flattened if word["text"].lower().strip("|{}[],:;") == "ballot"), None
    )
    district_header = next(
        (word["left"] for word in flattened if word["text"].lower().startswith("district")), None
    )
    # Continuation pages omit the column headings, but use the same fixed page
    # layout and column positions as the first table page.
    district_header = district_header or 1040
    place_header = place_header or 1388
    ballot_header = ballot_header or 1498
    candidate_start = ballot_header - 50

    rows = []
    for group in ordered_groups:
        group.sort(key=lambda word: word["left"])
        text = " ".join(word["text"] for word in group)
        if re.search(r"\boffice\b", text, re.I) and re.search(r"\bballot\b", text, re.I):
            continue
        office = [word["text"] for word in group if word["left"] < district_header]
        district = [
            word["text"] for word in group
            if district_header <= word["left"] < place_header
        ]
        place = [word["text"] for word in group if place_header <= word["left"] < ballot_header]
        candidate = [word["text"] for word in group if word["left"] >= candidate_start]
        while office and re.fullmatch(r"[ilI|{}]+", office[-1]):
            office.pop()
        office_title = " ".join(office)
        district_numbers = [value for value in district if value.isdigit()]
        place_numbers = [value for value in place if value.isdigit()]
        district_value = district_numbers[0] if len(district_numbers) == 1 else ""
        place_value = place_numbers[0] if len(place_numbers) == 1 else ""
        if district_value:
            if office_title.lower().startswith("united states representative"):
                office_title = f"United States Representative Congressional District {district_value}"
            elif office_title.lower().startswith("circuit"):
                office_title = f"{office_title} Circuit {district_value}"
            else:
                office_title = f"{office_title} District {district_value}"
        if place_value:
            office_title = f"{office_title} Place {place_value}"
        if office_title and candidate:
            rows.append((office_title, " ".join(candidate)))
    return rows


def _two_column_table_rows_from_tsv(
    tsv_text: str,
    *,
    allow_headerless: bool = False,
) -> list[tuple[str, str]]:
    """Read an upright Office / Name table when faint grid rules evade detection."""
    words = _read_ocr_words(tsv_text)
    name_header = next((word for word in words if word["text"].lower() == "name"), None)
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for word in words:
        groups[word["line"]].append(word)

    ordered_groups = sorted(groups.values(), key=lambda items: min(word["top"] for word in items))
    candidate_groups = []
    for group in ordered_groups:
        group.sort(key=lambda word: word["left"])
        gaps = [
            (group[index + 1]["left"] - (group[index]["left"] + group[index]["width"]), index)
            for index in range(len(group) - 1)
        ]
        if not gaps:
            continue
        largest_gap, split_index = max(gaps)
        if largest_gap >= 80:
            candidate_groups.append((group, split_index, group[split_index + 1]["left"]))

    if name_header:
        candidate_start = name_header["left"] - 20
        candidate_groups = [
            item for item in candidate_groups
            if abs(item[2] - candidate_start) <= 180
        ]
    else:
        if not allow_headerless:
            return []
        starts = [item[2] for item in candidate_groups]
        if len(starts) < 3:
            return []
        clusters = [
            [start for start in starts if abs(start - center) <= 100]
            for center in starts
        ]
        cluster = max(clusters, key=len)
        if len(cluster) < 3:
            return []
        candidate_start = sorted(cluster)[len(cluster) // 2]
        candidate_groups = [
            item for item in candidate_groups if abs(item[2] - candidate_start) <= 100
        ]

    rows = []
    for group, split_index, _right_start in candidate_groups:
        left, right = group[: split_index + 1], group[split_index + 1 :]
        office = " ".join(word["text"] for word in sorted(left, key=lambda word: word["left"]))
        candidate = " ".join(word["text"] for word in sorted(right, key=lambda word: word["left"]))
        if office and candidate and office.lower() != "office":
            rows.append((office, candidate))
    return rows


def _has_upright_table_divider(image_path: Path) -> bool:
    """Find a long interior vertical rule before using headerless row grouping."""
    from PIL import Image

    with Image.open(image_path) as source:
        image = source.convert("L")
    width, height = image.size
    minimum = int(height * 0.2)
    for x in range(round(width * 0.3), round(width * 0.75)):
        dark = sum(image.crop((x, 0, x + 1, height)).histogram()[:192])
        if dark >= minimum:
            return True
    return False


def _certification_table_geometry(image_path: Path) -> tuple[list[int], int] | None:
    """Find full-width horizontal table rules and the office/name divider."""
    from PIL import Image

    with Image.open(image_path) as source:
        image = source.convert("L")
    width, height = image.size
    horizontal_threshold = int(width * 0.55)
    line_pixels = []
    for y in range(height):
        histogram = image.crop((0, y, width, y + 1)).histogram()
        if sum(histogram[:128]) >= horizontal_threshold:
            line_pixels.append(y)

    rules = []
    for y in line_pixels:
        if not rules or y > rules[-1][-1] + 2:
            rules.append([y])
        else:
            rules[-1].append(y)
    rule_positions = [round(sum(group) / len(group)) for group in rules]
    if len(rule_positions) < 3:
        return None

    top, bottom = rule_positions[0], rule_positions[-1]
    candidates = []
    for x in range(round(width * 0.25), round(width * 0.8)):
        histogram = image.crop((x, top, x + 1, bottom + 1)).histogram()
        dark_pixels = sum(histogram[:128])
        if dark_pixels >= (bottom - top) * 0.55:
            candidates.append((dark_pixels, x))
    if not candidates:
        return None
    divider_x = max(candidates)[1]
    return rule_positions, divider_x


def normalize_contest_title(title: str) -> tuple[str, str]:
    normalized = " ".join(str(title or "").split())
    match = _PARTY_SUFFIX_RE.search(normalized)
    if not match:
        return normalized, ""
    return _PARTY_SUFFIX_RE.sub("", normalized).strip(), match.group(1)


def parse_enr_workbook(content: bytes) -> AlEnrParsedResult:
    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    if "AllResults" not in workbook.sheetnames:
        raise AlSosError("Alabama ENR workbook missing AllResults sheet")
    if "Statistics" not in workbook.sheetnames:
        raise AlSosError("Alabama ENR workbook missing Statistics sheet")

    county_stats, statistics_row_count = _parse_statistics(workbook["Statistics"])
    is_complete = all(
        stat["precincts_reported"] >= stat["total_precincts"]
        for stat in county_stats.values()
        if stat["total_precincts"] is not None
    )
    result_type = "official" if is_complete else "unofficial"

    totals: dict[tuple[str, str, str, str], int] = defaultdict(int)
    metadata: dict[tuple[str, str, str, str], dict] = {}
    election_codes: set[str] = set()
    all_results_row_count = 0

    for raw in _iter_dict_rows(workbook["AllResults"]):
        all_results_row_count += 1
        contest_code = _clean(raw.get("Contest Code"))
        contest_title = _clean(raw.get("Contest Title"))
        candidate_name = _clean(raw.get("Candidate Name"))
        party_code = _clean(raw.get("Party Code"))
        votes = _safe_int(raw.get("Votes"))
        election_code = _clean(raw.get("Election Code"))
        county_code = _clean(raw.get("County Code"))
        if not contest_code or not contest_title or not candidate_name:
            continue

        office_title, party_from_title = normalize_contest_title(contest_title)
        party = party_code or party_from_title
        key = (contest_code, office_title, candidate_name, party)
        totals[key] += votes
        election_codes.add(election_code)
        metadata.setdefault(
            key,
            {
                "contest_code": contest_code,
                "contest_title": contest_title,
                "party_code": party,
                "source": "al_sos_enr",
                "county_codes": [],
            },
        )
        metadata[key]["county_codes"].append(county_code)

    rows = [
        ResultRow(
            office_title=office_title,
            candidate_name=None if _is_write_in(candidate_name) else candidate_name,
            option_label=None,
            vote_count=vote_count,
            vote_pct=None,
            is_winner=None,
            result_type=result_type,
            is_write_in_aggregate=_is_write_in(candidate_name),
            raw=metadata[key],
        )
        for key, vote_count in sorted(totals.items(), key=lambda item: item[0])
        for _contest_code, office_title, candidate_name, _party in [key]
    ]

    return AlEnrParsedResult(
        rows=rows,
        source_version=_source_version(
            election_codes,
            county_stats,
            all_results_row_count=all_results_row_count,
            statistics_row_count=statistics_row_count,
        ),
        is_complete=is_complete,
        county_stats=county_stats,
    )


def _parse_statistics(sheet) -> tuple[dict[str, dict], int]:
    stats: dict[str, dict] = {}
    row_count = 0
    for raw in _iter_dict_rows(sheet):
        row_count += 1
        county_code = _clean(raw.get("County Code"))
        if not county_code:
            continue
        last_updated = raw.get("Last Updated")
        if isinstance(last_updated, dt.datetime):
            last_updated_value = last_updated.isoformat()
        else:
            last_updated_value = _clean(last_updated)
        stats[county_code] = {
            "ballots_cast": _safe_int(raw.get("Ballots Cast")),
            "total_precincts": _safe_int(raw.get("Total Precincts")),
            "precincts_reported": _safe_int(raw.get("Precincts Reported")),
            "last_updated": last_updated_value,
        }
    return stats, row_count


def _iter_dict_rows(sheet):
    rows = sheet.iter_rows(values_only=True)
    headers = [_clean(value) for value in next(rows, [])]
    for row in rows:
        yield dict(zip(headers, row))


def _source_version(
    election_codes: set[str],
    county_stats: dict[str, dict],
    *,
    all_results_row_count: int,
    statistics_row_count: int,
) -> str:
    code = ",".join(sorted(election_codes))
    latest = max((stat["last_updated"] for stat in county_stats.values()), default="")
    return f"{code}:{latest}:all_results={all_results_row_count}:statistics={statistics_row_count}"


def _safe_int(value) -> int:
    if value in (None, ""):
        return 0
    return int(str(value).replace(",", "").strip())


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _is_write_in(value: str) -> bool:
    return "write-in" in value.lower() or "write in" in value.lower()


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _infer_election_type(heading_text: str) -> str:
    lowered = heading_text.lower()
    if "special" in lowered:
        return "special"
    if "runoff" in lowered and "general" in lowered:
        return "general_runoff"
    if "runoff" in lowered:
        return "primary_runoff"
    if "primary" in lowered:
        return "primary"
    if "general" in lowered:
        return "general"
    if "municipal" in lowered:
        return "municipal"
    return "other"


def _infer_jurisdiction_level(heading_text: str) -> str:
    return "national" if "congressional" in heading_text.lower() else "state"


def parse_election_year_page(html: str) -> list[dict]:
    """
    Parse an Alabama SOS year-specific Election Information page
    (www.sos.alabama.gov/alabama-votes/voter/election-information/{year}).

    Each <h3> heading is "{Name} – {Month Day, Year}"; the immediately
    following <blockquote> holds that election's official document links.

    jurisdiction_level is inferred from the heading text (anything mentioning
    "Congressional" is "national", otherwise "state") so that two same-date
    special elections at different jurisdiction levels (e.g. a Congressional
    special and a State Senate special on the same day) get distinct
    canonical keys instead of colliding. This is a targeted fix, not a
    general solution: two same-date specials at the SAME jurisdiction level
    (e.g. two State Senate specials scheduled together) would still collide.
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []

    for heading in soup.find_all("h3"):
        text = " ".join(heading.get_text().split())
        parts = _DASH_RE.split(text, maxsplit=1)
        if len(parts) != 2:
            continue
        name, date_text = parts[0].strip(), parts[1].strip()
        try:
            election_date = dt.datetime.strptime(date_text, "%B %d, %Y").date()
        except ValueError:
            continue

        blockquote = heading.find_next_sibling("blockquote")
        document_links = []
        if blockquote is not None:
            for a in blockquote.find_all("a", href=True):
                label = " ".join(a.get_text().split())
                url = urljoin(_YEAR_PAGE_BASE_URL, a["href"])
                document_links.append({"label": label, "url": url})

        results.append({
            "name": name,
            "election_date": election_date,
            "election_type": _infer_election_type(name),
            "jurisdiction_level": _infer_jurisdiction_level(name),
            "source_id": f"al_sos_{election_date.year}_{_slugify(name)}",
            "document_links": document_links,
        })

    return results


def parse_fcpa_race_search_response(json_text: str) -> tuple[list[dict], int]:
    """Parse a com.acf.common.page.politicalracesearchresults JSON response."""
    payload = json.loads(json_text)
    if not payload.get("success"):
        raise AlSosError("Alabama FCPA race search response reported success=false")

    data = payload.get("data") or {}
    rows = [
        {
            "committee_id": row["COMMITTEEID"],
            "candidate_name": _clean(row.get("CANDIDATE", "")),
            "candidate_status": row.get("CANDIDATESTATUS", ""),
            "year": row.get("YEAR"),
        }
        for row in data.get("list", [])
    ]
    return rows, int(data.get("totalRecords", 0))


def _extract_balanced_object(text: str, marker: str) -> str:
    """Extract the {...} object literal immediately following `marker`."""
    start = text.find(marker)
    if start == -1:
        raise AlSosError(f"Alabama FCPA committee detail page missing {marker!r}")
    brace_start = text.find("{", start)
    if brace_start == -1:
        raise AlSosError("Alabama FCPA committee detail page missing object literal")

    depth = 0
    for i in range(brace_start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[brace_start:i + 1]
    raise AlSosError("Alabama FCPA committee detail page has unterminated object literal")


def parse_fcpa_committee_detail(html: str) -> dict:
    """
    Parse the committeeDetailsObj JSON embedded in a committee detail page
    (page.acfPublicCommitteeDetails). Verified strict JSON against the real
    capture in docs/state-research/AL/fcpa.alabamavotes.gov_Archive
    [26-07-20 12-42-17].har -- json.loads works directly, no JS-literal
    normalization needed.
    """
    raw = _extract_balanced_object(html, "committeeDetailsObj")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AlSosError(f"Alabama FCPA committeeDetailsObj is not valid JSON: {exc}") from exc

    return {
        "committee_id": data.get("id"),
        "candidateFirstName": data.get("candidateFirstName", ""),
        "candidateMiddleName": data.get("candidateMiddleName", ""),
        "candidateLastName": data.get("candidateLastName", ""),
        "suffix": data.get("suffix", ""),
        "office": data.get("office", ""),
        "jurisdiction": data.get("jurisdiction", ""),
        "district": data.get("district", ""),
        "place": data.get("place", ""),
        "party": data.get("party", ""),
        "committeeStatus": data.get("committeeStatus", ""),
        "dissolved": bool(data.get("dissolved", False)),
    }
