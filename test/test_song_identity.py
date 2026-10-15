"""Only independent, unambiguous catalog evidence can create a binding."""

from copy import deepcopy
from pathlib import Path

from scripts.audit_song_mapping import audit_scores
from scripts.song_identity import exact_candidates, title_matches
from song_alias import load_aliases, normalize


def identity():
    return {
        "names": {"Day by Day!": ["sakura:jp"], "unproven": ["ese:title"]},
        "levels": {"5": {"stars": 9, "totalNotes": 833}},
    }


def chart(**changes):
    return dict(
        title="Day by Day!",
        titleJa="",
        course="edit",
        level=9,
        totalNotes=833,
        fingerprint="new",
        **changes,
    )


def test_title_fallback_is_independent_and_preserves_version_qualifiers():
    assert title_matches(chart(), identity())
    assert not title_matches({"title": "unproven"}, identity())
    assert not title_matches({"title": "Day by Day! -Old Chart-"}, identity())
    assert normalize("晩餐歌") == normalize("晚餐歌")


def test_star_and_note_evidence_disambiguate_same_title_without_guessing():
    correct = chart()
    wrong_stars = dict(correct, level=8)
    wrong_notes = dict(correct, totalNotes=834)
    wrong_course = dict(correct, course="oni")
    assert exact_candidates(
        [wrong_stars, wrong_notes, wrong_course, correct], identity(), 5
    ) == [correct]
    # A second matching file must remain ambiguous, even with the same notes.
    assert (
        len(
            exact_candidates([correct, dict(correct, fingerprint="old")], identity(), 5)
        )
        == 2
    )


def test_missing_notes_never_establish_identity_from_title_alone():
    song = deepcopy(identity())
    song["levels"]["5"]["totalNotes"] = None
    assert exact_candidates([dict(chart(), totalNotes=None)], song, 5) == []


def test_score_audit_does_not_export_player_data_or_claim_unplayed_note_validation():
    root = Path(__file__).resolve().parents[1]
    aliases = load_aliases(root / "resource/aliases.v1.json.gz")
    songs = {"1502": {"levels": {"4": {"totalNotes": 1059}}}}
    row = {
        "song_no": 1502,
        "level": 4,
        "high_score": 123,
        "song_detail": {"id": 1502, "song_name": "鈍響ライクリフド"},
    }
    payload = {
        "data": {"playedRecords": {"userid": "PRIVATE_PLAYER", "scoreInfo": [row]}}
    }
    result = audit_scores(payload, songs, aliases)
    assert result["matchedIds"] == 1
    assert result["notesNotComparable"] == 1
    assert result.get("noteComparisons", 0) == 0
    assert "PRIVATE_PLAYER" not in str(result) and "high_score" not in str(result)
    row["song_no"] = 100138
    assert audit_scores(payload, songs, aliases)["missingIds"] == 1
