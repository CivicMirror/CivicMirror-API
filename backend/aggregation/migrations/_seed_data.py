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
    ("MA", "results",  "ma_sos",    0),
    ("MA", "results",  "civic_api", 1),
    ("MA", "date",     "ma_sos",    0),
    ("MA", "date",     "civic_api", 1),
    ("MA", "contacts", "civic_api", 0),
    ("MA", "contacts", "ma_sos",    1),
    ("MA", "identity", "civic_api", 0),
    ("MA", "identity", "ma_sos",    1),
    ("VA", "results",  "va_elect",  0),
    ("VA", "results",  "civic_api", 1),
    ("VA", "date",     "va_elect",  0),
    ("VA", "date",     "civic_api", 1),
    ("VA", "contacts", "civic_api", 0),
    ("VA", "contacts", "va_elect",  1),
    ("VA", "identity", "civic_api", 0),
    ("VA", "identity", "va_elect",  1),
    ("SC", "results",  "sc_vrems",  0),
    ("SC", "results",  "civic_api", 1),
    ("SC", "date",     "sc_vrems",  0),
    ("SC", "date",     "civic_api", 1),
    ("SC", "contacts", "civic_api", 0),
    ("SC", "contacts", "sc_vrems",  1),
    ("SC", "identity", "civic_api", 0),
    ("SC", "identity", "sc_vrems",  1),
]


def seed(model):
    for state, field_group, source, rank in ROWS:
        model.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )
