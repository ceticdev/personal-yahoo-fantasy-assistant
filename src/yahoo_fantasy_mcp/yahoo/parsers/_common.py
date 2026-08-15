"""Shared helpers for walking Yahoo's XML-shaped-as-JSON payloads.

Yahoo's Fantasy Sports API is XML-native; the `format=json` responses keep
XML's "list of elements, some of which are lists" shape instead of producing
clean JSON objects. Numeric string keys ("0", "1", "count") stand in for
array indices. These helpers centralize that walk so each parser module can
stay focused on field mapping instead of re-deriving traversal.
"""

from __future__ import annotations

from typing import Any, Iterator


def iter_indexed(container: dict[str, Any]) -> Iterator[Any]:
    """Yield values from a Yahoo `{"0": ..., "1": ..., "count": N}` mapping."""

    for key, value in container.items():
        if key == "count":
            continue
        yield value


def flatten_element_list(elements: Any) -> dict[str, Any]:
    """Flatten Yahoo's list-of-single-key-dicts (with occasional nested lists)
    into one dict. This is the shape used for both `player` and `settings`
    detail arrays.
    """

    flat: dict[str, Any] = {}

    def _visit(node: Any) -> None:
        if isinstance(node, dict):
            flat.update(node)
        elif isinstance(node, list):
            for item in node:
                _visit(item)

    _visit(elements)
    return flat


def as_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
