from integrations.mn_sos import filenames


def test_parse_groups_filenames_by_section():
    text = (
        "# a comment\n"
        "\n"
        "[federal-state]\n"
        "USPres.txt\n"
        "ussenate.txt   # inline note\n"
        "\n"
        "[local]\n"
        "cntyRaces.txt\n"
    )
    parsed = filenames.parse_filename_dictionary(text)
    assert parsed == {
        "federal-state": ["USPres.txt", "ussenate.txt"],
        "local": ["cntyRaces.txt"],
    }


def test_parse_ignores_blank_and_comment_lines():
    text = "# header\n\n[federal-state]\n# just a note\nUSPres.txt\n"
    parsed = filenames.parse_filename_dictionary(text)
    assert parsed == {"federal-state": ["USPres.txt"]}


def test_in_scope_filenames_reads_bundled_dictionary():
    # The bundled data file must define the six aggregated Federal+State files.
    names = filenames.in_scope_filenames()
    assert set(names) == {
        "USPres.txt",
        "ussenate.txt",
        "ushouse.txt",
        "stsenate.txt",
        "LegislativeByDistrict.txt",
        "judicial.txt",
    }
