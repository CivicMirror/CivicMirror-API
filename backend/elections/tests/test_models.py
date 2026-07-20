def test_race_source_has_alabama_choice():
    from elections.models import Race

    assert Race.Source.AL_SOS == "al_sos"
