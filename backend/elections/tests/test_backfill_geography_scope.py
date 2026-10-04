from io import StringIO

import pytest
from django.core.management import call_command

from elections.models import Election, Race


def _race(election, title, source, scope, n):
    return Race.objects.create(election=election, race_type='candidate', office_title=title, jurisdiction='NC',
                               geography_scope=scope, source=source, canonical_key=f'bf:{n}')


@pytest.mark.django_db
def test_backfill_relabels_only_results_bootstrapped_statewide_races():
    e = Election.objects.create(source_id='bf', name='NC', election_date='2026-03-03',
                                jurisdiction_level='state', state='NC', status='results_pending')
    county = _race(e, 'ALAMANCE COUNTY BOARD OF COMMISSIONERS', 'results_adapter', 'statewide', 1)
    governor = _race(e, 'NC GOVERNOR', 'results_adapter', 'statewide', 2)
    unknown = _race(e, 'Bald Head Island Bond', 'results_adapter', 'statewide', 3)
    other_source = _race(e, 'CITY OF RALEIGH MAYOR', 'nc_sbe', 'statewide', 4)

    call_command('backfill_geography_scope', '--dry-run', stdout=StringIO())
    county.refresh_from_db()
    assert county.geography_scope == 'statewide'  # dry run writes nothing

    call_command('backfill_geography_scope', stdout=StringIO())
    for race in (county, governor, unknown, other_source):
        race.refresh_from_db()
    assert county.geography_scope == 'countywide'
    assert governor.geography_scope == 'statewide'
    assert unknown.geography_scope == ''
    assert other_source.geography_scope == 'statewide'  # only results_adapter rows are touched
