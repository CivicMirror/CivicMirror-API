"""infer_geography_scope: real titles from bootstrapped results races (NC/IA/PA/GA/MA/AR)."""
import pytest

from elections.geography import infer_geography_scope


@pytest.mark.parametrize("title,expected", [
    # federal
    ("US HOUSE OF REPRESENTATIVES DISTRICT 01", "federal"),
    ("U.S. Senate", "federal"),
    ("President and Vice President", "federal"),
    # statewide
    ("NC SUPREME COURT ASSOCIATE JUSTICE SEAT 06", "statewide"),
    ("NC COURT OF APPEALS JUDGE SEAT 2", "statewide"),
    ("Governor - REP", "statewide"),
    ("Lieutenant Governor", "statewide"),
    ("Commissioner of Agriculture - Rep", "statewide"),
    ("Secretary of the Commonwealth", "statewide"),
    # district
    ("NC HOUSE OF REPRESENTATIVES DISTRICT 059 (REP)", "district"),
    ("State House - District 38", "district"),
    ("NC SUPERIOR COURT JUDGE DISTRICT 30A", "district"),
    ("NC DISTRICT COURT JUDGE DISTRICT 20 SEAT 01 (UNEXPIRED)", "district"),
    ("Prosecuting Attorney, Dist. 11-West", "district"),
    ("Governor's Council", "district"),
    # countywide
    ("ALAMANCE COUNTY BOARD OF COMMISSIONERS", "countywide"),
    ("JOHNSTON COUNTY BOARD OF COMMISSIONERS DISTRICT 5 (REP)", "countywide"),
    ("GRAHAM COUNTY SHERIFF", "countywide"),
    ("BURKE COUNTY REGISTER OF DEEDS", "countywide"),
    ("COUNTYWIDE UNFORTIFIED WINE ELECTION", "countywide"),
    ("R ASSESSOR", "countywide"),
    # local
    ("CITY OF FAYETTEVILLE CITY COUNCIL DISTRICT 02", "local"),
    ("TOWN OF MOUNT OLIVE COMMISSIONER DISTRICT 01", "local"),
    ("VILLAGE OF CHIMNEY ROCK VILLAGE COUNCILMAN", "local"),
    ("BURKE COUNTY BOARD OF EDUCATION AT-LARGE", "local"),
    ("Brooklyn-Guernsey-Malcom School Director At-Large", "local"),
    ("TOWN OF STANLEY ABC STORE ELECTION", "local"),
    ("BRUNSWICK SOIL AND WATER CONSERVATION DISTRICT SUPERVISOR", "local"),
    ("City of Algona - Mayor", "local"),
    # unknown: never guessed as statewide
    ("Party Question 1 - Rep", ""),
    ("Bald Head Island Bond", ""),
    ("", ""),
    (None, ""),
])
def test_infer_geography_scope(title, expected):
    assert infer_geography_scope(title) == expected
