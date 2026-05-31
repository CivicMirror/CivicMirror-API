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
    ("CO", "results",  "co_sos",    0),
    ("CO", "results",  "civic_api", 1),
    ("CO", "date",     "co_sos",    0),
    ("CO", "date",     "civic_api", 1),
    ("CO", "contacts", "civic_api", 0),
    ("CO", "contacts", "co_sos",    1),
    ("CO", "identity", "civic_api", 0),
    ("CO", "identity", "co_sos",    1),
]


def seed(model):
    for state, field_group, source, rank in ROWS:
        model.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )
