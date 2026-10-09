"""Parsing playlist selections like "1,3,5-8" (used by the CLI)."""

from __future__ import annotations


class SelectionError(ValueError):
    pass


def parse_selection(text: str, available: list[int]) -> list[int]:
    """Return the playlist indices chosen by `text`, in playlist order.

    Accepts "all", "1,3,5", "2-8", "1-3,7,10-12" and "-4" style exclusions
    ("all,-4" or just "-4" means everything except 4). Raises SelectionError
    with a friendly message when the input can't be used.
    """
    text = (text or "").strip().lower().replace(" ", "")
    avail = set(available)
    if text in ("", "all", "*", "a"):
        return sorted(avail)

    chosen: set[int] = set()
    excluded: set[int] = set()
    only_exclusions = True
    for part in filter(None, text.split(",")):
        target = chosen
        if part == "all":
            chosen |= avail
            continue
        if part.startswith("-") or part.startswith("!"):
            target, part = excluded, part[1:]
        else:
            only_exclusions = False
        try:
            if "-" in part:
                a, b = (int(x) for x in part.split("-", 1))
                if a > b:
                    a, b = b, a
                target.update(range(a, b + 1))
            else:
                target.add(int(part))
        except ValueError:
            raise SelectionError(
                f'Couldn\'t understand "{part}". Use numbers like 1,3,5-8 or "all".'
            ) from None

    if only_exclusions:
        chosen = set(avail)
    result = sorted((chosen - excluded) & avail)
    if not result:
        raise SelectionError("That selection doesn't match any videos in the list.")
    return result
