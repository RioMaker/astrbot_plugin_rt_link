"""Exact source-title matching shared by identity builds and audits."""

from song_alias import normalize


def source_names(song):
    """Only independent catalog names can establish a new ESE binding.

    ESE-derived names and player nicknames must not prove their own mapping.
    Version qualifiers remain in the normalized full name.
    """
    return {
        normalize(name)
        for name, sources in song.get("names", {}).items()
        if any(tag.startswith(("rating:", "sakura:", "kinoko:")) for tag in sources)
        and normalize(name)
    }


def title_matches(chart, song):
    titles = {normalize(chart.get(field)) for field in ("title", "titleJa")}
    return bool((titles - {""}) & source_names(song))


def exact_candidates(charts, song, level):
    meta = song["levels"][str(level)]
    if type(meta.get("totalNotes")) is not int or type(meta.get("stars")) is not int:
        return []
    return [
        chart
        for chart in charts
        if chart["course"] == ("oni" if level == 4 else "edit")
        and chart["totalNotes"] == meta["totalNotes"]
        and chart["level"] == meta["stars"]
        and title_matches(chart, song)
    ]
