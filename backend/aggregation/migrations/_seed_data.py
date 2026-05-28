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
]


def seed(model):
    for state, field_group, source, rank in ROWS:
        model.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )
