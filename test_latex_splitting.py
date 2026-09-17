from britfix_core import LaTeXStrategy, SpellingCorrector


def test_every_preserved_alternative_stays_intact():
    source = r"color \textbf{color} behavior \color center $color$ favorite $$behavior$$"
    expected = r"colour \textbf{color} behaviour \color centre $color$ favourite $$behavior$$"
    corrector = SpellingCorrector({
        "color": "colour", "behavior": "behaviour",
        "center": "centre", "favorite": "favourite",
    })
    result, counts = LaTeXStrategy().process(source, corrector)
    assert result == expected
    assert counts == {"color": 1, "behavior": 1, "center": 1, "favorite": 1}
