# Source Aggregation Layer — Implementation Plan (Phase 0 + 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a source-agnostic aggregation layer that merges multiple sources onto one canonical Election→Race→Candidate tree with DB-configurable field-level precedence, and prove it end-to-end on California (Google Civic + CA SOS).

**Architecture:** A new `backend/aggregation/` package owns canonical-key construction (`identity.py`), precedence resolution against a DB table (`precedence.py`), and a normalize-on-write ingest service (`ingest.py`). Adapters emit normalized field dicts + their source name; the ingest service resolves the canonical row and writes each field only if the incoming source out-ranks the field's current provenance owner.

**Tech Stack:** Django 5.2, DRF, Celery, pytest / pytest-django. Local tests run with `pytest --no-migrations` (a pre-existing Postgres-only `RunSQL` migration can't replay on SQLite; CI uses Postgres).

**Spec:** `docs/superpowers/specs/2026-05-27-source-aggregation-layer-design.md`

**Conventions for every task:**
- Run pytest from `backend/` using the venv: `cd backend && .venv/bin/python -m pytest … --no-migrations`.
- Branch is `feat/source-aggregation-layer`.
- Commit message trailer: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/aggregation/__init__.py`, `apps.py` | New Django app |
| `backend/aggregation/identity.py` | Normalization (name/office/party) + canonical-key builders |
| `backend/aggregation/precedence.py` | Field→group map; precedence resolution against DB |
| `backend/aggregation/models.py` | `SourcePrecedence` model |
| `backend/aggregation/admin.py` | Admin for `SourcePrecedence` |
| `backend/aggregation/ingest.py` | `ingest_election/race/candidate` (the merge engine) |
| `backend/aggregation/migrations/` | `SourcePrecedence` table + seeded baseline |
| `backend/aggregation/tests/` | Unit + integration tests |
| `backend/elections/models.py` | Add canonical/provenance fields; `ElectionSourceLink`; Candidate `normalized_party` |
| `backend/elections/migrations/` | Canonical/provenance schema migration |
| `backend/integrations/ca_sos/parsers.py` | Rewrite for `api-endpoints.csv` + date extraction |
| `backend/integrations/ca_sos/client.py` | Default to `api-endpoints.csv` |
| `backend/integrations/ca_sos/mappers.py` | Date-from-title; normalized race fields |
| `backend/integrations/ca_sos/tasks.py` | Route through ingest service |
| `backend/integrations/civic/tasks.py` | Route through ingest service |
| `backend/api/serializers.py` | Expose `sources` + `field_provenance` |

---

# PHASE 0 — Generic Aggregation Layer

## Task 1: Create the `aggregation` app

**Files:**
- Create: `backend/aggregation/__init__.py` (empty)
- Create: `backend/aggregation/apps.py`
- Create: `backend/aggregation/migrations/__init__.py` (empty)
- Create: `backend/aggregation/tests/__init__.py` (empty)
- Modify: `backend/config/settings/base.py` (INSTALLED_APPS list, after `'elections',`)

- [ ] **Step 1: Create the app config**

`backend/aggregation/apps.py`:
```python
from django.apps import AppConfig


class AggregationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "aggregation"
```

- [ ] **Step 2: Register the app**

In `backend/config/settings/base.py`, add `'aggregation',` to the project apps list immediately after `'elections',`:
```python
    'elections',
    'aggregation',
    'results',
```

- [ ] **Step 3: Verify Django loads the app**

Run: `cd backend && .venv/bin/python manage.py check`
Expected: `System check identified no issues`.

- [ ] **Step 4: Commit**

```bash
git add backend/aggregation backend/config/settings/base.py
git commit -m "feat(aggregation): scaffold aggregation app"
```

---

## Task 2: Normalization + canonical-key helpers (`identity.py`)

**Files:**
- Create: `backend/aggregation/identity.py`
- Test: `backend/aggregation/tests/test_identity.py`

- [ ] **Step 1: Write failing tests**

`backend/aggregation/tests/test_identity.py`:
```python
from datetime import date

from aggregation.identity import (
    election_canonical_key,
    name_match_key,
    normalize_name,
    normalize_office_title,
    normalize_party,
    race_canonical_key,
)


def test_election_canonical_key_is_source_independent():
    key = election_canonical_key("CA", "primary", date(2026, 6, 2), "state")
    assert key == "CA:primary:2026-06-02:state"


def test_normalize_office_title_collapses_whitespace_and_case():
    assert normalize_office_title("  Governor   - Statewide  ") == "governor - statewide"


def test_normalize_name_strips_punctuation_and_lowercases():
    assert normalize_name("Xavier Becerra") == "xavier becerra"
    assert normalize_name("Becerra, Xavier") == "becerra xavier"
    assert normalize_name("Robert F. Kennedy Jr.") == "robert f kennedy jr"


def test_name_match_key_is_order_independent():
    # "Last, First" and "First Last" must produce the same match key.
    assert name_match_key("Xavier Becerra") == name_match_key("Becerra, Xavier")
    assert name_match_key("Robert F. Kennedy Jr.") == name_match_key("kennedy robert jr f")


def test_normalize_party_maps_variants_to_codes():
    assert normalize_party("Democratic Party") == "DEM"
    assert normalize_party("Dem") == "DEM"
    assert normalize_party("DEM") == "DEM"
    assert normalize_party("Republican") == "REP"
    assert normalize_party("") == ""
    assert normalize_party("Green") == "GRN"
    assert normalize_party("Some Unknown Party") == "SOME UNKNOWN PARTY"


def test_race_canonical_key_combines_election_key_office_ocd_type():
    ek = "CA:primary:2026-06-02:state"
    key = race_canonical_key(ek, "Governor", "ocd-division/country:us/state:ca", "candidate")
    assert key == f"{ek}|governor|ocd-division/country:us/state:ca|candidate"


def test_race_canonical_key_uses_no_ocd_placeholder_when_blank():
    ek = "CA:primary:2026-06-02:state"
    key = race_canonical_key(ek, "Governor", "", "candidate")
    assert key == f"{ek}|governor|NO_OCD|candidate"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest aggregation/tests/test_identity.py -q --no-migrations`
Expected: FAIL — `ModuleNotFoundError: No module named 'aggregation.identity'`.

- [ ] **Step 3: Implement `identity.py`**

`backend/aggregation/identity.py`:
```python
"""Source-independent normalization and canonical-key construction."""
import re
from datetime import date

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")

# Canonical party codes. Keys are normalized (lowercased) source variants.
_PARTY_CODES = {
    "dem": "DEM", "democratic": "DEM", "democratic party": "DEM", "democrat": "DEM",
    "rep": "REP", "republican": "REP", "republican party": "REP", "gop": "REP",
    "grn": "GRN", "green": "GRN", "green party": "GRN",
    "lib": "LIB", "libertarian": "LIB", "libertarian party": "LIB",
    "pf": "PF", "peace and freedom": "PF",
    "ai": "AI", "american independent": "AI",
    "np": "NP", "nonpartisan": "NP", "no party preference": "NP", "npp": "NP",
    "ind": "IND", "independent": "IND",
}


def _squash(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").strip())


def normalize_office_title(title: str) -> str:
    return _squash(title).lower()


def normalize_name(name: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace. No reordering."""
    stripped = _PUNCT_RE.sub("", name or "")
    return _squash(stripped).lower()


def name_match_key(name: str) -> str:
    """
    Order-independent key for candidate matching: normalized tokens sorted, so
    "Xavier Becerra" and "Becerra, Xavier" collapse to the same key.
    """
    return " ".join(sorted(normalize_name(name).split()))


def normalize_party(party: str) -> str:
    """Map a source party label to a canonical code; unknown labels upper-cased."""
    key = _squash(party).lower()
    if not key:
        return ""
    if key in _PARTY_CODES:
        return _PARTY_CODES[key]
    return _squash(party).upper()


def election_canonical_key(
    state: str, election_type: str, election_date: date, jurisdiction_level: str
) -> str:
    return f"{state}:{election_type}:{election_date.isoformat()}:{jurisdiction_level}"


def race_canonical_key(
    election_key: str, office_title: str, ocd_division_id: str, race_type: str
) -> str:
    return "|".join([
        election_key,
        normalize_office_title(office_title),
        ocd_division_id or "NO_OCD",
        race_type,
    ])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest aggregation/tests/test_identity.py -q --no-migrations`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/aggregation/identity.py backend/aggregation/tests/test_identity.py
git commit -m "feat(aggregation): normalization and canonical-key helpers"
```

---

## Task 3: `SourcePrecedence` model + admin

**Files:**
- Create: `backend/aggregation/models.py`
- Create: `backend/aggregation/admin.py`
- Create (generated): `backend/aggregation/migrations/0001_initial.py`
- Test: `backend/aggregation/tests/test_models.py`

- [ ] **Step 1: Write failing test**

`backend/aggregation/tests/test_models.py`:
```python
import pytest

from aggregation.models import SourcePrecedence


@pytest.mark.django_db
def test_source_precedence_uniqueness():
    SourcePrecedence.objects.create(state="CA", field_group="results", source="ca_sos", rank=0)
    with pytest.raises(Exception):
        SourcePrecedence.objects.create(state="CA", field_group="results", source="ca_sos", rank=5)


@pytest.mark.django_db
def test_source_precedence_str():
    sp = SourcePrecedence.objects.create(state="*", field_group="*", source="civic_api", rank=0)
    assert "civic_api" in str(sp)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest aggregation/tests/test_models.py -q --no-migrations`
Expected: FAIL — `ModuleNotFoundError: No module named 'aggregation.models'`.

- [ ] **Step 3: Implement the model**

`backend/aggregation/models.py`:
```python
from django.db import models


class SourcePrecedence(models.Model):
    """
    Admin-editable, per-(state, field_group) ranking of sources.
    Lower rank = higher precedence. `*` is a wildcard for state or field_group.
    """
    state = models.CharField(max_length=2, default="*", help_text="2-letter state or '*' for all")
    field_group = models.CharField(max_length=40, default="*", help_text="field group or '*' for all")
    source = models.CharField(max_length=40)
    rank = models.IntegerField(default=0, help_text="lower = higher precedence")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["state", "field_group", "source"],
                name="unique_precedence_state_group_source",
            )
        ]
        ordering = ["state", "field_group", "rank"]

    def __str__(self) -> str:
        return f"{self.state}/{self.field_group}: {self.source}={self.rank}"
```

- [ ] **Step 4: Implement admin**

`backend/aggregation/admin.py`:
```python
from django.contrib import admin

from .models import SourcePrecedence


@admin.register(SourcePrecedence)
class SourcePrecedenceAdmin(admin.ModelAdmin):
    list_display = ("state", "field_group", "source", "rank")
    list_filter = ("state", "field_group", "source")
    list_editable = ("rank",)
    ordering = ("state", "field_group", "rank")
```

- [ ] **Step 5: Generate the migration**

Run: `cd backend && .venv/bin/python manage.py makemigrations aggregation`
Expected: creates `aggregation/migrations/0001_initial.py` with `SourcePrecedence`.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest aggregation/tests/test_models.py -q --no-migrations`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add backend/aggregation/models.py backend/aggregation/admin.py backend/aggregation/migrations/0001_initial.py backend/aggregation/tests/test_models.py
git commit -m "feat(aggregation): SourcePrecedence model + admin"
```

---

## Task 4: Precedence resolution (`precedence.py`)

**Files:**
- Create: `backend/aggregation/precedence.py`
- Test: `backend/aggregation/tests/test_precedence.py`

- [ ] **Step 1: Write failing tests**

`backend/aggregation/tests/test_precedence.py`:
```python
import pytest

from aggregation.models import SourcePrecedence
from aggregation.precedence import field_group_for, resolve_rank


def test_field_group_for_maps_known_fields():
    assert field_group_for("election_date") == "date"
    assert field_group_for("office_title") == "identity"
    assert field_group_for("image_url") == "contacts"
    assert field_group_for("party") == "party"
    assert field_group_for("ocd_division_id") == "district"
    assert field_group_for("results_url") == "results"


def test_field_group_for_unknown_field_defaults_to_identity():
    assert field_group_for("some_new_field") == "identity"


@pytest.mark.django_db
def test_resolve_rank_prefers_most_specific_row():
    SourcePrecedence.objects.create(state="*", field_group="*", source="civic_api", rank=0)
    SourcePrecedence.objects.create(state="CA", field_group="results", source="ca_sos", rank=0)
    SourcePrecedence.objects.create(state="CA", field_group="results", source="civic_api", rank=1)
    # CA/results: ca_sos outranks civic
    assert resolve_rank("CA", "results", "ca_sos") < resolve_rank("CA", "results", "civic_api")


@pytest.mark.django_db
def test_resolve_rank_falls_back_through_wildcards():
    SourcePrecedence.objects.create(state="*", field_group="*", source="civic_api", rank=0)
    # No CA-specific row: civic resolves via the global default
    assert resolve_rank("CA", "contacts", "civic_api") == 0


@pytest.mark.django_db
def test_resolve_rank_unranked_source_is_lowest():
    rank = resolve_rank("CA", "results", "nonexistent_source")
    assert rank == float("inf")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest aggregation/tests/test_precedence.py -q --no-migrations`
Expected: FAIL — `ModuleNotFoundError: No module named 'aggregation.precedence'`.

- [ ] **Step 3: Implement `precedence.py`**

`backend/aggregation/precedence.py`:
```python
"""Field→group mapping and precedence resolution against SourcePrecedence."""
from .models import SourcePrecedence

# Model field name -> precedence field group.
_FIELD_GROUPS = {
    # identity
    "name": "identity", "office_title": "identity", "incumbent": "identity",
    # date / status
    "election_date": "date",
    "status": "status", "certification_status": "status", "candidate_status": "status",
    # contacts
    "image_url": "contacts", "website_url": "contacts",
    "contact_phone": "contacts", "contact_office": "contacts", "description": "contacts",
    # party
    "party": "party",
    # district / geography
    "ocd_division_id": "district", "jurisdiction": "district", "geography_scope": "district",
    # results / live
    "results_url": "results", "vote_method": "results", "max_selections": "results",
}

DEFAULT_GROUP = "identity"


def field_group_for(field_name: str) -> str:
    return _FIELD_GROUPS.get(field_name, DEFAULT_GROUP)


def resolve_rank(state: str, field_group: str, source: str) -> float:
    """
    Return the precedence rank of `source` for (state, field_group).
    Lower = higher precedence. Most-specific match wins; an unranked source
    returns +inf (lowest — may only fill empty fields).
    """
    rows = SourcePrecedence.objects.filter(source=source).filter(
        state__in=[state, "*"], field_group__in=[field_group, "*"]
    )
    best = None
    best_specificity = -1
    for row in rows:
        specificity = (row.state != "*") * 2 + (row.field_group != "*")
        if specificity > best_specificity:
            best_specificity = specificity
            best = row
    return float(best.rank) if best is not None else float("inf")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest aggregation/tests/test_precedence.py -q --no-migrations`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/aggregation/precedence.py backend/aggregation/tests/test_precedence.py
git commit -m "feat(aggregation): field-group map + precedence resolution"
```

---

## Task 5: Election/Race/Candidate canonical + provenance schema

**Files:**
- Modify: `backend/elections/models.py` (Election, Race, Candidate; new `ElectionSourceLink`)
- Create (generated): `backend/elections/migrations/00NN_aggregation_fields.py`
- Test: `backend/elections/tests/test_aggregation_fields.py`

- [ ] **Step 1: Write failing test**

`backend/elections/tests/test_aggregation_fields.py`:
```python
from datetime import date

import pytest

from elections.models import Candidate, Election, ElectionSourceLink, Race


@pytest.mark.django_db
def test_election_has_canonical_and_provenance_fields():
    e = Election.objects.create(
        name="2026 California Primary Election", election_date=date(2026, 6, 2),
        election_type="primary", jurisdiction_level="state", state="CA",
        source_id="ca:primary:2026-06-02:state",
        canonical_key="CA:primary:2026-06-02:state",
    )
    assert e.field_provenance == {}
    assert e.contributing_sources == []
    assert e.needs_review is False


@pytest.mark.django_db
def test_election_source_link_unique_per_source():
    e = Election.objects.create(
        name="x", election_date=date(2026, 6, 2), election_type="primary",
        jurisdiction_level="state", state="CA", source_id="k1",
        canonical_key="CA:primary:2026-06-02:state",
    )
    ElectionSourceLink.objects.create(election=e, source="civic_api", source_id="11255")
    with pytest.raises(Exception):
        ElectionSourceLink.objects.create(election=e, source="civic_api", source_id="other")


@pytest.mark.django_db
def test_candidate_normalized_party_field_exists():
    e = Election.objects.create(
        name="x", election_date=date(2026, 6, 2), election_type="primary",
        jurisdiction_level="state", state="CA", source_id="k2",
    )
    r = Race.objects.create(election=e, race_type="candidate", office_title="Governor",
                            jurisdiction="California", geography_scope="statewide", source="ca_sos")
    c = Candidate.objects.create(race=r, name="Jane Doe", party="Dem", normalized_party="DEM")
    assert c.normalized_party == "DEM"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest elections/tests/test_aggregation_fields.py -q --no-migrations`
Expected: FAIL — `ImportError: cannot import name 'ElectionSourceLink'`.

- [ ] **Step 3: Add fields + model to `elections/models.py`**

In `class Election`, add after `results_url` (line ~52):
```python
    canonical_key = models.CharField(max_length=255, unique=True, null=True, blank=True)
    field_provenance = models.JSONField(default=dict, blank=True)
    contributing_sources = models.JSONField(default=list, blank=True)
    needs_review = models.BooleanField(default=False)
```
Make `source_id` nullable (keep `unique=True` — not-yet-migrated adapters such as
`sc_vrems` `bulk_create` on it with `update_conflicts/unique_fields=["source_id"]`;
NULLs are exempt from uniqueness so merged elections with `source_id=NULL`
coexist). The column and its unique constraint are dropped in the Phase-2 finish:
```python
    source_id = models.CharField(max_length=50, unique=True, null=True, blank=True)
```
In `class Race`, add after `submitted_by_uid` (line ~152):
```python
    field_provenance = models.JSONField(default=dict, blank=True)
    contributing_sources = models.JSONField(default=list, blank=True)
```
In `class Candidate`, add after `contact_office` (line ~195):
```python
    normalized_party = models.CharField(max_length=40, blank=True)
    field_provenance = models.JSONField(default=dict, blank=True)
```
Add a new model after `class Candidate` (before `MeasureOption`):
```python
class ElectionSourceLink(models.Model):
    election = models.ForeignKey(Election, on_delete=models.CASCADE, related_name='source_links_rel')
    source = models.CharField(max_length=40)
    source_id = models.CharField(max_length=255, blank=True)
    results_url = models.URLField(blank=True, default='')
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['election', 'source'], name='unique_election_source')
        ]

    def __str__(self) -> str:
        return f'{self.election_id}:{self.source}'
```

- [ ] **Step 4: Generate the migration**

Run: `cd backend && .venv/bin/python manage.py makemigrations elections`
Expected: a migration adding the four Election fields, dropping `source_id` unique, adding Race fields, Candidate `normalized_party` + `field_provenance`, and `ElectionSourceLink`. Note the generated filename (e.g. `0008_...`) for later tasks.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest elections/tests/test_aggregation_fields.py -q --no-migrations`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/elections/models.py backend/elections/migrations/ backend/elections/tests/test_aggregation_fields.py
git commit -m "feat(elections): canonical key, provenance, ElectionSourceLink, normalized_party"
```

---

## Task 6: Ingest service (`ingest.py`) — the merge engine

**Files:**
- Create: `backend/aggregation/ingest.py`
- Test: `backend/aggregation/tests/test_ingest.py`

The ingest service exposes three functions. Each resolves the canonical row,
records the contributing source, and writes each provided field only when the
incoming source out-ranks the field's current provenance owner.

- [ ] **Step 1: Write failing tests**

`backend/aggregation/tests/test_ingest.py`:
```python
from datetime import date

import pytest

from aggregation import ingest
from aggregation.models import SourcePrecedence
from elections.models import Candidate, Election, Race


@pytest.fixture
def ca_precedence(db):
    SourcePrecedence.objects.create(state="*", field_group="*", source="civic_api", rank=0)
    SourcePrecedence.objects.create(state="CA", field_group="results", source="ca_sos", rank=0)
    SourcePrecedence.objects.create(state="CA", field_group="results", source="civic_api", rank=1)
    SourcePrecedence.objects.create(state="CA", field_group="contacts", source="civic_api", rank=0)
    SourcePrecedence.objects.create(state="CA", field_group="contacts", source="ca_sos", rank=1)


def _election_identity():
    return dict(state="CA", election_type="primary",
                election_date=date(2026, 6, 2), jurisdiction_level="state")


@pytest.mark.django_db
def test_ingest_election_creates_canonical_row_and_source_link(ca_precedence):
    e = ingest.ingest_election(
        source="ca_sos", source_id="ca_sos_2026_primary",
        identity=_election_identity(),
        fields={"name": "2026 California Primary Election", "status": "upcoming"},
    )
    assert e.canonical_key == "CA:primary:2026-06-02:state"
    assert "ca_sos" in e.contributing_sources
    assert e.source_links_rel.filter(source="ca_sos", source_id="ca_sos_2026_primary").exists()
    assert e.field_provenance["name"] == "ca_sos"


@pytest.mark.django_db
def test_two_sources_merge_onto_one_election(ca_precedence):
    e1 = ingest.ingest_election(
        source="ca_sos", source_id="ca_sos_2026_primary", identity=_election_identity(),
        fields={"name": "2026 California Primary Election"},
    )
    e2 = ingest.ingest_election(
        source="civic_api", source_id="11255", identity=_election_identity(),
        fields={"name": "California Primary Election"},
    )
    assert e1.pk == e2.pk
    assert set(e2.contributing_sources) == {"ca_sos", "civic_api"}
    # name is an 'identity' field; civic (rank 0) outranks ca_sos (inf default) -> civic wins
    assert e2.name == "California Primary Election"
    assert e2.field_provenance["name"] == "civic_api"


@pytest.mark.django_db
def test_higher_precedence_source_wins_per_field(ca_precedence):
    e = ingest.ingest_election(source="ca_sos", source_id="x", identity=_election_identity(), fields={})
    # results field group: ca_sos outranks civic in CA
    ingest.ingest_race(
        election=e, source="civic_api",
        identity={"office_title": "Governor", "ocd_division_id": "", "race_type": "candidate"},
        fields={"office_title": "Governor", "results_url": "https://civic/results"},
    )
    r = ingest.ingest_race(
        election=e, source="ca_sos",
        identity={"office_title": "Governor", "ocd_division_id": "", "race_type": "candidate"},
        fields={"results_url": "https://api.sos.ca.gov/returns/governor"},
    )
    assert r.results_url == "https://api.sos.ca.gov/returns/governor"
    assert r.field_provenance["results_url"] == "ca_sos"
    # office_title still owned by civic (only civic provided it)
    assert r.field_provenance["office_title"] == "civic_api"


@pytest.mark.django_db
def test_candidate_matching_by_normalized_name_and_party(ca_precedence):
    e = ingest.ingest_election(source="ca_sos", source_id="x", identity=_election_identity(), fields={})
    r = ingest.ingest_race(
        election=e, source="ca_sos",
        identity={"office_title": "Governor", "ocd_division_id": "", "race_type": "candidate"},
        fields={"office_title": "Governor"},
    )
    c1 = ingest.ingest_candidate(race=r, source="ca_sos", name="Xavier Becerra", party="Dem",
                                 fields={"incumbent": False})
    c2 = ingest.ingest_candidate(race=r, source="civic_api", name="Becerra, Xavier", party="Democratic Party",
                                 fields={"image_url": "https://civic/photo.jpg"})
    assert c1.pk == c2.pk
    assert c2.image_url == "https://civic/photo.jpg"           # contacts: civic owns
    assert c2.normalized_party == "DEM"


@pytest.mark.django_db
def test_ingest_election_flags_review_when_date_missing(ca_precedence):
    e = ingest.ingest_election(
        source="ca_sos", source_id="bad",
        identity={"state": "CA", "election_type": "primary",
                  "election_date": None, "jurisdiction_level": "state"},
        fields={"name": "Broken"},
    )
    assert e.needs_review is True
    assert e.canonical_key is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest aggregation/tests/test_ingest.py -q --no-migrations`
Expected: FAIL — `ModuleNotFoundError: No module named 'aggregation.ingest'`.

- [ ] **Step 3: Implement `ingest.py`**

`backend/aggregation/ingest.py`:
```python
"""
Normalize-on-write merge engine.

Adapters call ingest_election/ingest_race/ingest_candidate with their source
name and normalized field dicts. Each field is written only when the incoming
source out-ranks the field's current provenance owner (see precedence.resolve_rank).
"""
import logging

from django.db import transaction
from django.utils import timezone

from elections.models import Candidate, Election, ElectionSourceLink, Race

from .identity import election_canonical_key, name_match_key, normalize_party, race_canonical_key
from .precedence import field_group_for, resolve_rank

logger = logging.getLogger(__name__)


def _apply_fields(instance, state, source, fields):
    """Write each field if `source` out-ranks the current owner. Returns changed field names."""
    provenance = instance.field_provenance or {}
    changed = []
    for name, value in fields.items():
        group = field_group_for(name)
        incoming = resolve_rank(state, group, source)
        owner = provenance.get(name)
        owner_rank = resolve_rank(state, group, owner) if owner else float("inf")
        if owner is None or incoming <= owner_rank:
            setattr(instance, name, value)
            provenance[name] = source
            changed.append(name)
    instance.field_provenance = provenance
    return changed


def _add_source(instance, source):
    sources = list(instance.contributing_sources or [])
    if source not in sources:
        sources.append(source)
        instance.contributing_sources = sources


@transaction.atomic
def ingest_election(*, source, source_id, identity, fields):
    state = identity.get("state")
    election_date = identity.get("election_date")
    election_type = identity.get("election_type")
    jurisdiction_level = identity.get("jurisdiction_level")

    if not (state and election_date and election_type and jurisdiction_level):
        # Cannot form a canonical key — keep as its own row, flagged for review.
        election = Election.objects.create(
            name=fields.get("name", "Needs review"),
            election_date=election_date or timezone.localdate(),
            election_type=election_type or Election.ElectionType.OTHER,
            jurisdiction_level=jurisdiction_level or Election.JurisdictionLevel.STATE,
            state=state, source_id=source_id, needs_review=True,
        )
        logger.warning("aggregation.election.needs_review source=%s source_id=%s", source, source_id)
        return election

    key = election_canonical_key(state, election_type, election_date, jurisdiction_level)
    election = Election.objects.select_for_update().filter(canonical_key=key).first()
    if election is None:
        # Migrated sources leave Election.source_id NULL; the per-source id is
        # recorded on ElectionSourceLink below.
        election = Election(
            canonical_key=key, state=state,
            election_date=election_date, election_type=election_type,
            jurisdiction_level=jurisdiction_level, name=fields.get("name", ""),
        )

    _apply_fields(election, state, source, {**fields, "election_date": election_date})
    _add_source(election, source)
    election.last_synced_at = timezone.now()
    election.save()

    ElectionSourceLink.objects.update_or_create(
        election=election, source=source,
        defaults={
            "source_id": source_id,
            "results_url": fields.get("results_url", "") or "",
            "last_synced_at": timezone.now(),
        },
    )
    return election


@transaction.atomic
def ingest_race(*, election, source, identity, fields):
    state = election.state or "*"
    office_title = identity["office_title"]
    ocd = identity.get("ocd_division_id", "") or ""
    race_type = identity["race_type"]
    key = race_canonical_key(election.canonical_key or f"e{election.pk}", office_title, ocd, race_type)

    race = Race.objects.select_for_update().filter(canonical_key=key).first()
    if race is None:
        race = Race(
            canonical_key=key, election=election, office_title=office_title,
            ocd_division_id=ocd, race_type=race_type,
            jurisdiction=fields.get("jurisdiction", ""),
            geography_scope=fields.get("geography_scope", ""),
            source=source,
        )

    _apply_fields(race, state, source, fields)
    _add_source(race, source)
    # Representative `source` = highest-precedence contributing source for identity group.
    race.source = min(
        race.contributing_sources,
        key=lambda s: resolve_rank(state, "identity", s),
    )
    race.last_synced_at = timezone.now()
    race.save()
    return race


@transaction.atomic
def ingest_candidate(*, race, source, name, party, fields):
    norm_name = normalize_name(name)
    norm_party = normalize_party(party)
    state = race.election.state or "*"

    match = Candidate.objects.select_for_update().filter(
        race=race, name=name
    ).first()
    if match is None:
        # Match on normalized name + party (nonpartisan: name only).
        for cand in race.candidates.all():
            if normalize_name(cand.name) == norm_name and (
                norm_party == "" or normalize_party(cand.party) == norm_party
            ):
                match = cand
                break

    if match is None:
        match = Candidate(race=race, name=name, party=party, normalized_party=norm_party)

    _apply_fields(match, state, source, {**fields, "party": party})
    match.normalized_party = norm_party
    if not match.name:
        match.name = name
    _add_source(match, source)
    match.save()
    return match
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest aggregation/tests/test_ingest.py -q --no-migrations`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/aggregation/ingest.py backend/aggregation/tests/test_ingest.py
git commit -m "feat(aggregation): normalize-on-write ingest/merge engine"
```

---

## Task 7: Seed the precedence baseline (data migration)

**Files:**
- Create: `backend/aggregation/migrations/0002_seed_precedence.py`
- Test: `backend/aggregation/tests/test_seed_precedence.py`

- [ ] **Step 1: Write failing test**

`backend/aggregation/tests/test_seed_precedence.py`:
```python
import pytest

from aggregation.models import SourcePrecedence
from aggregation.migrations import _seed_data  # helper module created in Step 3


@pytest.mark.django_db
def test_seed_rows_define_civic_default_and_ca_overrides():
    _seed_data.seed(SourcePrecedence)
    assert SourcePrecedence.objects.get(state="*", field_group="*", source="civic_api").rank == 0
    assert (
        SourcePrecedence.objects.get(state="CA", field_group="results", source="ca_sos").rank
        < SourcePrecedence.objects.get(state="CA", field_group="results", source="civic_api").rank
    )
    assert SourcePrecedence.objects.get(state="CA", field_group="contacts", source="civic_api").rank == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest aggregation/tests/test_seed_precedence.py -q --no-migrations`
Expected: FAIL — `ModuleNotFoundError: No module named 'aggregation.migrations._seed_data'`.

- [ ] **Step 3: Create the seed helper + migration**

`backend/aggregation/migrations/_seed_data.py`:
```python
# Shared seed data so it can be unit-tested and reused by the migration.
ROWS = [
    ("*",  "*",        "civic_api", 0),
    ("*",  "*",        "fec",       1),
    ("CA", "results",  "ca_sos",    0),
    ("CA", "results",  "civic_api", 1),
    ("CA", "date",     "ca_sos",    0),
    ("CA", "date",     "civic_api", 1),
    ("CA", "contacts", "civic_api", 0),
    ("CA", "contacts", "ca_sos",    1),
    ("CA", "identity", "civic_api", 0),
    ("CA", "identity", "ca_sos",    1),
]


def seed(model):
    for state, field_group, source, rank in ROWS:
        model.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )
```

`backend/aggregation/migrations/0002_seed_precedence.py`:
```python
from django.db import migrations

from ._seed_data import seed


def forward(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    seed(SourcePrecedence)


def backward(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("aggregation", "0001_initial")]
    operations = [migrations.RunPython(forward, backward)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest aggregation/tests/test_seed_precedence.py -q --no-migrations`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/aggregation/migrations/_seed_data.py backend/aggregation/migrations/0002_seed_precedence.py backend/aggregation/tests/test_seed_precedence.py
git commit -m "feat(aggregation): seed Civic-first precedence baseline + CA overrides"
```

---

# PHASE 1 — California Vertical Slice

## Task 8: Rewrite CA SOS catalog parser for `api-endpoints.csv`

**Files:**
- Modify: `backend/integrations/ca_sos/parsers.py`
- Test: `backend/integrations/ca_sos/tests/test_parsers.py`

The real `api-endpoints.csv` format: line 1 = base URL `https://api.sos.ca.gov`;
line 2 = quoted title `"|This file lists all available endpoints for the California June 2, 2026 Primary Election|"`;
blank-separated groups of full endpoint URLs (`https://api.sos.ca.gov/returns/governor`,
`.../returns/us-rep/district/12`, `.../returns/governor/county/alameda`). Keep
statewide + `/district/N`; skip `/county/`, `/status`, `/query`, files, and
`/district/all`.

- [ ] **Step 1: Write failing tests**

`backend/integrations/ca_sos/tests/test_parsers.py` (add to existing file or create):
```python
from integrations.ca_sos.parsers import parse_api_endpoint_catalog, parse_election_date_from_catalog

SAMPLE = b"""https://api.sos.ca.gov
"|This file lists all available endpoints for the California June 2, 2026 Primary Election|"

https://api.sos.ca.gov/returns/governor
https://api.sos.ca.gov/returns/governor/county/alameda

https://api.sos.ca.gov/returns/us-rep/district/all
https://api.sos.ca.gov/returns/us-rep/district/12

https://api.sos.ca.gov/returns/status
"""


def test_parse_api_catalog_keeps_statewide_and_district_skips_county():
    entries = parse_api_endpoint_catalog(SAMPLE)
    paths = [e["path"] for e in entries]
    assert "/returns/governor" in paths
    assert "/returns/us-rep/district/12" in paths
    assert "/returns/governor/county/alameda" not in paths   # county skipped
    assert "/returns/us-rep/district/all" not in paths        # 'all' skipped
    assert "/returns/status" not in paths                     # status skipped


def test_parse_api_catalog_names_default_to_path_tail():
    entries = parse_api_endpoint_catalog(SAMPLE)
    gov = next(e for e in entries if e["path"] == "/returns/governor")
    assert gov["name"].lower() == "governor"


def test_parse_election_date_from_catalog_title():
    assert parse_election_date_from_catalog(SAMPLE).isoformat() == "2026-06-02"


def test_parse_election_date_returns_none_when_absent():
    assert parse_election_date_from_catalog(b"https://api.sos.ca.gov\nno date here\n") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest integrations/ca_sos/tests/test_parsers.py -q --no-migrations`
Expected: FAIL — `ImportError: cannot import name 'parse_api_endpoint_catalog'`.

- [ ] **Step 3: Implement the new parser functions**

Append to `backend/integrations/ca_sos/parsers.py`:
```python
import datetime as _dt

_API_BASE = "https://api.sos.ca.gov"
_DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})",
    re.IGNORECASE,
)
_MONTHS = {m.lower(): i for i, m in enumerate(
    ["", "January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"]
)}


def parse_api_endpoint_catalog(csv_bytes: bytes) -> list[dict]:
    """
    Parse api-endpoints.csv (headerless list of full REST URLs) into contest
    dicts: {"name", "path", "type", "race_id"}. Keeps statewide + /district/N;
    skips /county/, /district/all, /status, /query, and file URLs.
    """
    text = csv_bytes.decode("utf-8-sig", errors="replace")
    results: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip().strip('"').strip()
        if not line or not line.startswith(_API_BASE):
            continue
        path = line[len(_API_BASE):]
        if path in ("", "/"):
            continue
        if _should_skip(path) or "/county/" in path or path.endswith("/district/all"):
            continue
        name = path.rstrip("/").split("/")[-1].replace("-", " ").strip()
        results.append({
            "name": name or path,
            "path": path,
            "type": "measure" if "ballot-measure" in path else "candidate",
            "race_id": "",
        })
    logger.info("ca_sos.parser.api_catalog_parsed contests=%d", len(results))
    return results


def parse_election_date_from_catalog(csv_bytes: bytes):
    """Extract the election date from the catalog title line. Returns date or None."""
    text = csv_bytes.decode("utf-8-sig", errors="replace")
    match = _DATE_RE.search(text)
    if not match:
        return None
    month = _MONTHS[match.group(1).lower()]
    return _dt.date(int(match.group(3)), month, int(match.group(2)))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest integrations/ca_sos/tests/test_parsers.py -q --no-migrations`
Expected: PASS (4 new passed; existing parser tests still green).

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/ca_sos/parsers.py backend/integrations/ca_sos/tests/test_parsers.py
git commit -m "feat(ca_sos): parse api-endpoints.csv + extract election date from title"
```

---

## Task 9: CA SOS client defaults to `api-endpoints.csv`

**Files:**
- Modify: `backend/integrations/ca_sos/client.py:118,135`
- Test: `backend/integrations/ca_sos/tests/test_client.py`

- [ ] **Step 1: Write failing test**

Add to `backend/integrations/ca_sos/tests/test_client.py`:
```python
from unittest.mock import MagicMock, patch

from integrations.ca_sos.client import CaSosClient


def test_fetch_catalog_defaults_to_api_endpoints_csv():
    client = CaSosClient()
    with patch.object(client, "_get") as mock_get:
        resp = MagicMock(status_code=200, content=b"https://api.sos.ca.gov\n")
        mock_get.return_value = resp
        client.fetch_endpoint_catalog_csv()
        called_url = mock_get.call_args[0][0]
        assert called_url.endswith("/api-endpoints.csv")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest integrations/ca_sos/tests/test_client.py -q --no-migrations -k api_endpoints`
Expected: FAIL — URL ends with `/json-endpoints.csv`.

- [ ] **Step 3: Change the defaults**

In `backend/integrations/ca_sos/client.py`, change both default args from
`"json-endpoints.csv"` to `"api-endpoints.csv"`:
```python
    def fetch_endpoint_catalog_csv(self, filename: str = "api-endpoints.csv") -> bytes:
```
```python
    def get_endpoint_catalog_fingerprint(self, filename: str = "api-endpoints.csv") -> str | None:
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest integrations/ca_sos/tests/test_client.py -q --no-migrations`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/ca_sos/client.py backend/integrations/ca_sos/tests/test_client.py
git commit -m "feat(ca_sos): default catalog to api-endpoints.csv"
```

---

## Task 10: CA SOS mappers — date from catalog, normalized race identity

**Files:**
- Modify: `backend/integrations/ca_sos/mappers.py`
- Test: `backend/integrations/ca_sos/tests/test_mappers.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/integrations/ca_sos/tests/test_mappers.py`:
```python
from datetime import date

from integrations.ca_sos.mappers import map_election_identity


def test_map_election_identity_uses_catalog_date_when_provided():
    identity, fields = map_election_identity(2026, "primary", catalog_date=date(2026, 6, 2))
    assert identity["election_date"] == date(2026, 6, 2)
    assert identity["state"] == "CA"
    assert identity["election_type"] == "primary"
    assert identity["jurisdiction_level"] == "state"
    assert fields["name"] == "2026 California Primary Election"


def test_map_election_identity_falls_back_to_statutory_date():
    identity, _ = map_election_identity(2026, "primary", catalog_date=None)
    # statutory fallback (first Tue after first Mon in March 2026)
    assert identity["election_date"] == date(2026, 3, 3)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest integrations/ca_sos/tests/test_mappers.py -q --no-migrations -k identity`
Expected: FAIL — `ImportError: cannot import name 'map_election_identity'`.

- [ ] **Step 3: Add `map_election_identity` to `mappers.py`**

Append to `backend/integrations/ca_sos/mappers.py`:
```python
def map_election_identity(year: int, election_type: str, catalog_date=None):
    """
    Return (identity, fields) for the ingest service.

    identity = canonical natural key parts; fields = mergeable values.
    Uses the catalog-derived date when available, else the statutory fallback.
    """
    election_date = catalog_date or ca_election_date(year, election_type)
    type_label = election_type.title()
    identity = {
        "state": "CA",
        "election_type": election_type,
        "election_date": election_date,
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
    }
    fields = {
        "name": f"{year} California {type_label} Election",
        "status": infer_election_status(election_date),
    }
    return identity, fields
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest integrations/ca_sos/tests/test_mappers.py -q --no-migrations`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/ca_sos/mappers.py backend/integrations/ca_sos/tests/test_mappers.py
git commit -m "feat(ca_sos): map_election_identity with catalog date + statutory fallback"
```

---

## Task 11: Route the CA SOS task through the ingest service

**Files:**
- Modify: `backend/integrations/ca_sos/tasks.py` (`sync_ca_elections`, `sync_ca_races`)
- Test: `backend/integrations/ca_sos/tests/test_tasks.py`

This task rewires `sync_ca_elections` to (1) fetch + fingerprint the catalog,
(2) parse the election date from the catalog, (3) `ingest_election` for primary
and general, and `sync_ca_races` to `ingest_race`/`ingest_candidate`.

- [ ] **Step 1: Write failing integration test**

Add to `backend/integrations/ca_sos/tests/test_tasks.py`:
```python
from datetime import date
from unittest.mock import patch

import pytest
from django.test import override_settings

from aggregation.models import SourcePrecedence
from elections.models import Election


@pytest.fixture
def seed_precedence(db):
    SourcePrecedence.objects.create(state="*", field_group="*", source="civic_api", rank=0)
    SourcePrecedence.objects.create(state="CA", field_group="date", source="ca_sos", rank=0)
    SourcePrecedence.objects.create(state="CA", field_group="identity", source="ca_sos", rank=1)


CATALOG = (
    b'https://api.sos.ca.gov\n'
    b'"|... California June 2, 2026 Primary Election|"\n\n'
    b'https://api.sos.ca.gov/returns/governor\n'
)


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
def test_sync_ca_elections_uses_catalog_date_and_ingests(seed_precedence):
    from integrations.ca_sos.tasks import sync_ca_elections
    with patch("integrations.ca_sos.tasks.CaSosClient") as MockClient:
        inst = MockClient.return_value
        inst.get_endpoint_catalog_fingerprint.return_value = "fp1"
        inst.fetch_endpoint_catalog_csv.return_value = CATALOG
        sync_ca_elections.run()

    primary = Election.objects.get(canonical_key="CA:primary:2026-06-02:state")
    assert primary.election_date == date(2026, 6, 2)
    assert "ca_sos" in primary.contributing_sources
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest integrations/ca_sos/tests/test_tasks.py -q --no-migrations -k catalog_date`
Expected: FAIL (current task uses `update_or_create` + statutory date; no `canonical_key`).

- [ ] **Step 3: Rewrite `sync_ca_elections`**

Replace the body of `sync_ca_elections` in `backend/integrations/ca_sos/tasks.py`. Key changes:
- import `from aggregation import ingest` and the new parser/mapper functions;
- fetch the catalog once, compute fingerprint, and `parse_election_date_from_catalog`;
- for each `election_type in _ELECTION_TYPES`: `identity, fields = map_election_identity(year, election_type, catalog_date=parsed_date)` then `election = ingest.ingest_election(source="ca_sos", source_id=build_election_source_id(year, election_type), identity=identity, fields=fields)`;
- keep the catalog-changed fingerprint/SyncLog logic; queue `sync_ca_races(election.pk, catalog_json, fingerprint)` using `parse_api_endpoint_catalog`.

Full replacement code:
```python
@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_ca_elections(self):
    from aggregation import ingest
    from .mappers import build_election_source_id, map_election_identity
    from .parsers import (
        deduplicate_catalog, parse_api_endpoint_catalog, parse_election_date_from_catalog,
    )

    sync_log = SyncLog.objects.create(
        source="ca_sos", task_name="sync_ca_elections", status=SyncLog.Status.STARTED,
    )
    client = CaSosClient()
    created_count = updated_count = 0
    try:
        year = _current_even_year()

        fingerprint = client.get_endpoint_catalog_fingerprint()
        catalog_bytes = None
        catalog_date = None
        if fingerprint is not None:
            catalog_bytes = client.fetch_endpoint_catalog_csv()
            catalog_date = parse_election_date_from_catalog(catalog_bytes)

        elections = {}
        for election_type in _ELECTION_TYPES:
            cdate = catalog_date if election_type == "primary" else None
            identity, fields = map_election_identity(year, election_type, catalog_date=cdate)
            election = ingest.ingest_election(
                source="ca_sos",
                source_id=build_election_source_id(year, election_type),
                identity=identity, fields=fields,
            )
            elections[election_type] = election
            created_count += int(election.contributing_sources == ["ca_sos"])

        logger.info("ca_sos.sync_elections.seeded year=%d", year)

        if fingerprint is None:
            sync_log.notes = "Endpoint catalog unavailable; races not refreshed"
            sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created": created_count, "queued": 0}

        last_fingerprint = cache.get(_CATALOG_CACHE_KEY)
        if fingerprint == last_fingerprint:
            sync_log.notes = "Catalog unchanged; races not refreshed"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created": created_count, "queued": 0}

        entries = deduplicate_catalog(parse_api_endpoint_catalog(catalog_bytes))
        if not entries:
            sync_log.notes = "Catalog parsed but no usable endpoints found"
            sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created": created_count, "queued": 0}

        election_obj = elections.get("primary") or elections.get("general")
        sync_ca_races.delay(election_obj.pk, json.dumps(entries), fingerprint)

        sync_log.notes = f"Queued sync_ca_races: {len(entries)} contests"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["notes", "status", "completed_at"])
        return {"created": created_count, "queued": 1}

    except CaSosRetryableError as exc:
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception("ca_sos.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
```

- [ ] **Step 4: Rewrite `sync_ca_races` to use the ingest service**

Replace the Race/Candidate `update_or_create` blocks in `sync_ca_races` with ingest calls. Inside the contest loop, replace the `Race.objects.update_or_create(...)` + candidate loop with:
```python
                from aggregation import ingest
                from .mappers import infer_geography_scope, infer_race_type, normalize

                race = ingest.ingest_race(
                    election=election_obj, source="ca_sos",
                    identity={
                        "office_title": contest.get("raceTitle") or entry["name"],
                        "ocd_division_id": "",
                        "race_type": infer_race_type(entry["type"]),
                    },
                    fields={
                        "office_title": contest.get("raceTitle") or entry["name"],
                        "jurisdiction": "California",
                        "geography_scope": infer_geography_scope(entry["name"]),
                        "results_url": f"https://api.sos.ca.gov{entry['path']}",
                        "certification_status": (
                            Race.CertificationStatus.RESULTS_PENDING
                            if election_obj.status == Election.Status.RESULTS_PENDING
                            else Race.CertificationStatus.UPCOMING
                        ),
                    },
                )
                created_count += 1
                for raw_cand in (contest.get("candidates") or []):
                    cand_name = (raw_cand.get("Name") or "").strip()
                    if not cand_name:
                        continue
                    cand = ingest.ingest_candidate(
                        race=race, source="ca_sos", name=cand_name,
                        party=(raw_cand.get("Party") or "").strip(),
                        fields={
                            "incumbent": bool(raw_cand.get("incumbent", False)),
                            "source_metadata": {
                                "ca_votes": raw_cand.get("Votes", ""),
                                "ca_percent": raw_cand.get("Percent", ""),
                            },
                        },
                    )
                    seen_candidate_pks.add(cand.pk)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest integrations/ca_sos/tests/ -q --no-migrations`
Expected: PASS (new + existing CA SOS tests).

- [ ] **Step 6: Commit**

```bash
git add backend/integrations/ca_sos/tasks.py backend/integrations/ca_sos/tests/test_tasks.py
git commit -m "feat(ca_sos): route sync through aggregation ingest service"
```

---

## Task 12: Route the Civic task through the ingest service

**Files:**
- Modify: `backend/integrations/civic/tasks.py`
- Test: `backend/integrations/civic/tests/test_tasks.py`

Civic's `map_election_payload` returns `source_id/name/election_date/state/...`.
Convert that into an `(identity, fields)` pair and call the ingest service; map
each contest via `map_contest_to_race_defaults` into an `ingest_race` call and
candidates via `map_candidate_defaults` into `ingest_candidate`.

- [ ] **Step 1: Write failing test**

Add to `backend/integrations/civic/tests/test_tasks.py`:
```python
from datetime import date

import pytest

from aggregation.models import SourcePrecedence
from elections.models import Election
from integrations.civic.ingest_adapter import ingest_civic_election


@pytest.fixture
def precedence(db):
    SourcePrecedence.objects.create(state="*", field_group="*", source="civic_api", rank=0)


@pytest.mark.django_db
def test_ingest_civic_election_lands_on_canonical_key(precedence):
    payload = {
        "source_id": "11255",
        "name": "California Primary Election",
        "election_date": "2026-06-02",
        "ocd_division_id": "ocd-division/country:us/state:ca",
    }
    election = ingest_civic_election(payload)
    assert election.canonical_key == "CA:primary:2026-06-02:state"
    assert "civic_api" in election.contributing_sources
```

> NOTE: Civic payloads do not carry `election_type`. Add a small helper
> `infer_election_type(name)` in the adapter (below) that maps "primary"→primary,
> "general"→general, else "other"; the test payload name contains "Primary".

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest integrations/civic/tests/test_tasks.py -q --no-migrations -k civic_election`
Expected: FAIL — `ModuleNotFoundError: No module named 'integrations.civic.ingest_adapter'`.

- [ ] **Step 3: Create `integrations/civic/ingest_adapter.py`**

```python
"""Bridge Civic payloads into the aggregation ingest service."""
from datetime import date

from aggregation import ingest
from elections.models import Election
from .mappers import (
    map_contest_to_race_defaults, map_candidate_defaults,
    parse_jurisdiction_level, parse_state_from_ocd, infer_election_status,
)


def infer_election_type(name: str) -> str:
    lowered = (name or "").lower()
    if "primary" in lowered:
        return Election.ElectionType.PRIMARY
    if "general" in lowered:
        return Election.ElectionType.GENERAL
    if "special" in lowered:
        return Election.ElectionType.SPECIAL
    if "municipal" in lowered:
        return Election.ElectionType.MUNICIPAL
    return Election.ElectionType.OTHER


def ingest_civic_election(payload: dict):
    election_date = payload["election_date"]
    if isinstance(election_date, str):
        election_date = date.fromisoformat(election_date)
    ocd = payload.get("ocd_division_id", "")
    identity = {
        "state": parse_state_from_ocd(ocd),
        "election_type": infer_election_type(payload["name"]),
        "election_date": election_date,
        "jurisdiction_level": parse_jurisdiction_level(ocd),
    }
    fields = {"name": payload["name"], "status": infer_election_status(election_date)}
    return ingest.ingest_election(
        source="civic_api", source_id=str(payload["source_id"]),
        identity=identity, fields=fields,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest integrations/civic/tests/test_tasks.py -q --no-migrations -k civic_election`
Expected: PASS.

- [ ] **Step 5: Wire the adapter into `sync_elections`**

In `backend/integrations/civic/tasks.py`, replace the `Election.objects.update_or_create(source_id=source_id, defaults=mapped)` call (line ~54) with:
```python
            from .ingest_adapter import ingest_civic_election
            election = ingest_civic_election(payload)
            created = election.contributing_sources == ["civic_api"]
```
Replace the race `Race.objects.update_or_create(canonical_key=..., ...)` (line ~108) with an `ingest.ingest_race(...)` call using `map_contest_to_race_defaults(election, contest)` to build `identity` (`office_title`, `ocd_division_id`, `race_type`) and `fields` (the remaining mapped keys), and the candidate `update_or_create` with `ingest.ingest_candidate(race=race, source="civic_api", name=<candidate name>, party=<party>, fields=map_candidate_defaults(candidate_payload))`.

- [ ] **Step 6: Run the civic test suite**

Run: `cd backend && .venv/bin/python -m pytest integrations/civic/tests/ -q --no-migrations`
Expected: PASS (existing + new).

- [ ] **Step 7: Commit**

```bash
git add backend/integrations/civic/ingest_adapter.py backend/integrations/civic/tasks.py backend/integrations/civic/tests/test_tasks.py
git commit -m "feat(civic): route sync through aggregation ingest service"
```

---

## Task 13: Phase 1 cutover runbook (wipe + re-sync — no data migration)

Because data is disposable (no user base), there is **no merge/data migration**.
This task authors the deploy-time runbook. The destructive commands inside it are
**executed at deploy time with explicit go-ahead**, not during implementation.

**Files:**
- Create: `docs/runbooks/ca-aggregation-cutover.md`

- [ ] **Step 1: Write the cutover runbook**

`docs/runbooks/ca-aggregation-cutover.md`:
````markdown
# CA Aggregation Cutover (Phase 1)

Run after the Phase 0+1 code is deployed. Destructive — confirm before each step.

## 1. Pause not-yet-migrated scheduler jobs
Leave only the migrated sources enabled (Civic `sync-elections-hourly`, `sync-ca-sos`):
```bash
for job in sync-sc-vrems poll-sc-enr sync-sc-enr-results sync-co-sos \
           sync-ia-sos sync-ma-sos sync-va-elect sync-openstates \
           sync-fec poll-pending-results; do
  gcloud scheduler jobs pause "$job" --project=civicmirror-2026 --location=us-central1
done
```

## 2. Apply migrations
```bash
gcloud run jobs execute civicmirror-migrate --project=civicmirror-2026 --region=us-central1 --wait
```

## 3. Wipe source-siloed election data
Clears old rows so re-sync produces canonical-keyed records. Run in a Django shell
on the worker/api (cascades to Race/Candidate/MeasureOption):
```bash
python manage.py shell -c "from elections.models import Election; Election.objects.all().delete()"
```

## 4. Re-sync the migrated sources
```bash
INTERNAL_TOKEN=$(gcloud secrets versions access latest --secret=INTERNAL_TASK_TOKEN --project=civicmirror-2026)
BASE="https://api.civicmirror.welshrd.com/internal/tasks"
curl -s -X POST "$BASE/sync-elections/" -H "Authorization: Bearer $INTERNAL_TOKEN"   # Civic
curl -s -X POST "$BASE/sync-ca-sos/"    -H "Authorization: Bearer $INTERNAL_TOKEN"   # CA SOS
```

## 5. Verify the merge
```bash
API_KEY=$(gcloud secrets versions access latest --secret=CIVICMIRROR_API_KEY --project=civicmirror-2026)
curl -s "https://api.civicmirror.welshrd.com/api/elections/?state=CA" -H "X-Api-Key: $API_KEY"
```
Expect a single CA primary with `canonical_key = "CA:primary:2026-06-02:state"` and
`sources` containing both `civic_api` and `ca_sos`.
````

- [ ] **Step 2: Commit the runbook**

```bash
git add docs/runbooks/ca-aggregation-cutover.md
git commit -m "docs: CA aggregation cutover runbook (wipe + re-sync)"
```

> Execution of the runbook against staging/production is a separate, gated deploy
> action — not part of implementing this plan.

---

## Task 14: Expose `sources` + `field_provenance` in the API

**Files:**
- Modify: `backend/api/serializers.py`
- Test: `backend/api/tests/test_serializers_provenance.py`

- [ ] **Step 1: Write failing test**

`backend/api/tests/test_serializers_provenance.py`:
```python
from datetime import date

import pytest

from api.serializers import ElectionSerializer
from elections.models import Election


@pytest.mark.django_db
def test_election_serializer_includes_sources_and_provenance():
    e = Election.objects.create(
        name="2026 California Primary Election", election_date=date(2026, 6, 2),
        election_type="primary", jurisdiction_level="state", state="CA",
        source_id="11255", canonical_key="CA:primary:2026-06-02:state",
        contributing_sources=["civic_api", "ca_sos"],
        field_provenance={"name": "civic_api", "election_date": "ca_sos"},
    )
    data = ElectionSerializer(e).data
    assert data["sources"] == ["civic_api", "ca_sos"]
    assert data["field_provenance"]["election_date"] == "ca_sos"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest api/tests/test_serializers_provenance.py -q --no-migrations`
Expected: FAIL — `KeyError: 'sources'`.

- [ ] **Step 3: Update `ElectionSerializer`**

In `backend/api/serializers.py`, update `ElectionSerializer` (lines ~13-23):
```python
class ElectionSerializer(serializers.ModelSerializer):
    race_count = serializers.IntegerField(read_only=True)
    sources = serializers.ListField(source="contributing_sources", read_only=True)

    class Meta:
        model = Election
        fields = [
            'id', 'source_id', 'name', 'election_date', 'jurisdiction_level',
            'state', 'status', 'last_synced_at', 'election_cycle', 'race_count',
            'sources', 'field_provenance',
        ]
```
Apply the same `sources` + `field_provenance` additions to `RaceDetailSerializer`
(it has `contributing_sources`/`field_provenance` on the model) and
`CandidateSerializer` (`field_provenance` only).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest api/tests/test_serializers_provenance.py -q --no-migrations`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/api/serializers.py backend/api/tests/test_serializers_provenance.py
git commit -m "feat(api): expose contributing sources + field provenance"
```

---

## Task 15: End-to-end CA merge integration test

**Files:**
- Test: `backend/aggregation/tests/test_ca_end_to_end.py`

Proves the headline outcome: Civic + CA SOS converge on one canonical CA primary
with the expected field ownership.

- [ ] **Step 1: Write the integration test**

`backend/aggregation/tests/test_ca_end_to_end.py`:
```python
from datetime import date

import pytest

from aggregation import ingest
from aggregation.migrations._seed_data import seed
from aggregation.models import SourcePrecedence
from elections.models import Election


@pytest.mark.django_db
def test_civic_and_ca_sos_merge_into_one_election_with_expected_ownership():
    seed(SourcePrecedence)
    identity = dict(state="CA", election_type="primary",
                    election_date=date(2026, 6, 2), jurisdiction_level="state")

    # Civic first (baseline)
    civic = ingest.ingest_election(
        source="civic_api", source_id="11255", identity=identity,
        fields={"name": "California Primary Election"},
    )
    r = ingest.ingest_race(
        election=civic, source="civic_api",
        identity={"office_title": "Governor", "ocd_division_id": "ocd-division/country:us/state:ca", "race_type": "candidate"},
        fields={"office_title": "Governor", "jurisdiction": "California"},
    )
    ingest.ingest_candidate(race=r, source="civic_api", name="Xavier Becerra",
                            party="Democratic Party", fields={"image_url": "https://civic/p.jpg"})

    # CA SOS augments (results + date authority)
    ca = ingest.ingest_election(
        source="ca_sos", source_id="ca_sos_2026_primary", identity=identity,
        fields={"name": "2026 California Primary Election"},
    )
    r2 = ingest.ingest_race(
        election=ca, source="ca_sos",
        identity={"office_title": "Governor", "ocd_division_id": "ocd-division/country:us/state:ca", "race_type": "candidate"},
        fields={"results_url": "https://api.sos.ca.gov/returns/governor"},
    )
    ingest.ingest_candidate(race=r2, source="ca_sos", name="Becerra, Xavier",
                            party="Dem", fields={"incumbent": False,
                            "source_metadata": {"ca_votes": "89,380"}})

    assert Election.objects.filter(state="CA", election_type="primary").count() == 1
    assert civic.pk == ca.pk
    assert set(ca.contributing_sources) == {"civic_api", "ca_sos"}
    assert r.pk == r2.pk                                   # one merged race
    assert r2.results_url == "https://api.sos.ca.gov/returns/governor"
    assert r2.field_provenance["results_url"] == "ca_sos"
    cand = r2.candidates.get()                             # one merged candidate
    assert cand.image_url == "https://civic/p.jpg"         # contacts: civic
    assert cand.normalized_party == "DEM"
```

- [ ] **Step 2: Run the test**

Run: `cd backend && .venv/bin/python -m pytest aggregation/tests/test_ca_end_to_end.py -q --no-migrations`
Expected: PASS.

- [ ] **Step 3: Run the full suite**

Run: `cd backend && .venv/bin/python -m pytest -q --no-migrations`
Expected: PASS (no regressions).

- [ ] **Step 4: Commit**

```bash
git add backend/aggregation/tests/test_ca_end_to_end.py
git commit -m "test(aggregation): end-to-end CA Civic+CA SOS merge"
```

---

## Final verification

- [ ] Run the full suite: `cd backend && .venv/bin/python -m pytest -q --no-migrations` → all pass.
- [ ] `cd backend && .venv/bin/python manage.py makemigrations --check --dry-run` → no missing migrations.
- [ ] `cd backend && .venv/bin/python manage.py check` → no issues.
- [ ] Confirm deferred items are NOT in this phase: other-state adapter migration, fuzzy matching, GeoJSON/FIPS (Phase 2+).

---

## Notes for the implementer
- The only generated migration here is Task 5's `elections` schema migration (run
  `ls backend/elections/migrations/` for its name). There is **no data migration**
  — cutover is the wipe + re-sync runbook in Task 13.
- `--no-migrations` is required locally; CI runs migrations on Postgres.
- `Election.canonical_key` is DB-`null=True` during this incremental phase (the
  ingest service always sets it; not-yet-migrated adapters leave it NULL — multiple
  NULLs are fine under the unique constraint). It is tightened to NOT NULL in the
  Phase-2 finish.
- `Election.source_id` stays nullable/non-unique (deprecated) so non-CA adapters
  keep working; migrated adapters (CA SOS, Civic) leave it NULL. Dropped in the
  Phase-2 finish.
- The legacy source-scoped `Race.canonical_key` values for non-CA states remain
  untouched; they don't collide with the new `|`-delimited keys. Non-CA adapters
  keep their current behavior until Phase 2.
