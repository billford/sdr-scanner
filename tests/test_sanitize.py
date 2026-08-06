from sanitize import soften


def test_masks_middle_letters():
    assert soften("kill") == "k**l"


def test_keeps_first_and_last_character():
    assert soften("suicide") == "s*****e"
    assert soften("gun") == "gun"  # not in the stem list


def test_inflections_are_covered():
    assert soften("shooting") == "s******g"
    assert soften("killed") == "k****d"


def test_case_and_punctuation_preserved_around_word():
    out = soften("Shooting reported, victim dead.")
    assert out == "S******g reported, victim d**d."


def test_longest_stem_wins():
    assert soften("gunshot") == "g*****t"


def test_word_boundaries_respected():
    assert soften("skill") == "skill"
    assert soften("shotgun") == "s*****n"


def test_untouched_text_passes_through():
    assert soften("Engine 3 dispatched to 123 Main Street") == (
        "Engine 3 dispatched to 123 Main Street"
    )


def test_empty_input():
    assert soften("") == ""
