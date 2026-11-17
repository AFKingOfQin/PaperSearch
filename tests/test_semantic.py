# AI-generated code (Codex): deterministic semantic scope and input recipe.
from papersearch.encoder import eligible, passage


def test_fixture_and_recent_cross_listed_papers_are_eligible():
    assert eligible("fixture:river", {"published": None, "categories": []})
    assert eligible(
        "arxiv:2401.00001",
        {"published": "2024-01-01", "categories": ["math.OC", "cs.LG"]},
    )
    assert not eligible(
        "arxiv:2401.00001", {"published": None, "categories": ["cs.LG"]}
    )


def test_passage_keeps_title_and_abstract_separate():
    assert (
        passage("River models", "A study of streams.")
        == "River models\nA study of streams."
    )
    assert passage("River models", "") == "River models"
