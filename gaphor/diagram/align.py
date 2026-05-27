from __future__ import annotations

from itertools import pairwise

from gaphor.diagram.presentation import ElementPresentation

DEFAULT_DISTRIBUTE_GAP = 10.0


def align_left(elements: set[ElementPresentation]):
    left_edge = _left_edge(elements)

    for item in elements:
        item.matrix.translate(left_edge - item.matrix[4], 0)


def align_right(elements: set[ElementPresentation]):
    right_edge = _right_edge(elements)

    for item in elements:
        item.matrix.translate(right_edge - (item.matrix[4] + item.width), 0)


def align_vertical_center(elements: set[ElementPresentation]):
    left_edge = _left_edge(elements)
    right_edge = _right_edge(elements)
    center_edge = left_edge + (right_edge - left_edge) / 2

    for item in elements:
        item.matrix.translate(center_edge - item.matrix[4] - item.width / 2, 0)


def align_top(elements: set[ElementPresentation]):
    top_edge = _top_edge(elements)

    for item in elements:
        item.matrix.translate(0, top_edge - item.matrix[5])


def align_bottom(elements: set[ElementPresentation]):
    bottom_edge = _bottom_edge(elements)

    for item in elements:
        item.matrix.translate(0, bottom_edge - (item.matrix[5] + item.height))


def align_horizontal_center(elements: set[ElementPresentation]):
    top_edge = _top_edge(elements)
    bottom_edge = _bottom_edge(elements)
    center_edge = top_edge + (bottom_edge - top_edge) / 2

    for item in elements:
        item.matrix.translate(0, center_edge - item.matrix[5] - item.height / 2)


def resize_max_width(elements: set[ElementPresentation]):
    max_width = _max_width(elements)

    for item in elements:
        item.width = max_width


def resize_max_height(elements: set[ElementPresentation]):
    max_height = _max_height(elements)

    for item in elements:
        item.height = max_height


def resize_max_size(elements: set[ElementPresentation]):
    max_width = _max_width(elements)
    max_height = _max_height(elements)

    for item in elements:
        item.width = max_width
        item.height = max_height


def resize_min_width(elements: set[ElementPresentation]):
    min_width = _min_width(elements)

    for item in elements:
        item.width = min_width


def resize_min_height(elements: set[ElementPresentation]):
    min_height = _min_height(elements)

    for item in elements:
        item.height = min_height


def resize_min_size(elements: set[ElementPresentation]):
    min_width = _min_width(elements)
    min_height = _min_height(elements)

    for item in elements:
        item.width = min_width
        item.height = min_height


def distribute_horizontally(elements: set[ElementPresentation]):
    items = sorted(elements, key=lambda item: (item.matrix[4], item.matrix[5]))
    gap = _min_positive_horizontal_gap(items)

    previous = items[0]
    for item in items[1:]:
        x = previous.matrix[4] + previous.width + gap
        item.matrix.translate(x - item.matrix[4], 0)
        previous = item


def distribute_vertically(elements: set[ElementPresentation]):
    items = sorted(elements, key=lambda item: (item.matrix[5], item.matrix[4]))
    gap = _min_positive_vertical_gap(items)

    previous = items[0]
    for item in items[1:]:
        y = previous.matrix[5] + previous.height + gap
        item.matrix.translate(0, y - item.matrix[5])
        previous = item


def _left_edge(elements: set[ElementPresentation]):
    return min(item.matrix[4] for item in elements)


def _right_edge(elements: set[ElementPresentation]):
    return max(item.matrix[4] + item.width for item in elements)


def _top_edge(elements: set[ElementPresentation]):
    return min(item.matrix[5] for item in elements)


def _bottom_edge(elements: set[ElementPresentation]):
    return max(item.matrix[5] + item.height for item in elements)


def _max_width(elements: set[ElementPresentation]):
    return max(item.width for item in elements)


def _max_height(elements: set[ElementPresentation]):
    return max(item.height for item in elements)


def _min_width(elements: set[ElementPresentation]):
    return min(item.width for item in elements)


def _min_height(elements: set[ElementPresentation]):
    return min(item.height for item in elements)


def _min_positive_horizontal_gap(elements: list[ElementPresentation]) -> float:
    return min(
        (
            right.matrix[4] - (left.matrix[4] + left.width)
            for left, right in pairwise(elements)
            if right.matrix[4] > left.matrix[4] + left.width
        ),
        default=DEFAULT_DISTRIBUTE_GAP,
    )


def _min_positive_vertical_gap(elements: list[ElementPresentation]) -> float:
    return min(
        (
            bottom.matrix[5] - (top.matrix[5] + top.height)
            for top, bottom in pairwise(elements)
            if bottom.matrix[5] > top.matrix[5] + top.height
        ),
        default=DEFAULT_DISTRIBUTE_GAP,
    )
