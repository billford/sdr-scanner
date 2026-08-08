from sanitize import soften


def test_masks_middle_letters():
    assert soften("kill") == "k*ll"


def test_short_words_get_a_single_star():
    """Starring every interior letter of a 4-letter word can spell something
    worse than the word being masked: "shot" -> "s**t" went out on a live post."""
    assert soften("shot") == "s*ot"
    assert soften("stab") == "s*ab"
    assert soften("dead") == "d*ad"


def test_long_words_keep_the_full_run_of_stars():
    assert soften("shooting") == "s******g"
    assert soften("assault") == "a*****t"


def test_keeps_first_and_last_character():
    assert soften("suicide") == "s*****e"
    assert soften("gun") == "gun"  # not in the stem list


def test_inflections_are_covered():
    assert soften("shooting") == "s******g"
    assert soften("killed") == "k****d"


def test_case_and_punctuation_preserved_around_word():
    out = soften("Shooting reported, victim dead.")
    assert out == "S******g reported, victim d*ad."


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
