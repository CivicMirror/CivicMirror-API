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
