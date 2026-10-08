"""Occupancy grid helpers: rasterize boxes, dilate and label components.

Working on a coarse grid (a few points per cell) keeps clustering linear in
the page area, regardless of whether a figure is 1 image or 10,000 paths.
"""

from __future__ import annotations

import numpy as np

from sfi.extract.layout import Box


class Grid:
    def __init__(self, width: float, height: float, cell: float):
        self.cell = cell
        self.cols = int(np.ceil(width / cell)) + 1
        self.rows = int(np.ceil(height / cell)) + 1

    def empty(self) -> np.ndarray:
        return np.zeros((self.rows, self.cols), dtype=bool)

    def cells(self, box: Box) -> tuple[slice, slice]:
        r0 = max(0, int(box.y0 // self.cell))
        r1 = min(self.rows, int(np.ceil(box.y1 / self.cell)) + 1)
        c0 = max(0, int(box.x0 // self.cell))
        c1 = min(self.cols, int(np.ceil(box.x1 / self.cell)) + 1)
        return slice(r0, max(r0 + 1, r1)), slice(c0, max(c0 + 1, c1))

    def fill(self, mask: np.ndarray, box: Box) -> None:
        mask[self.cells(box)] = True

    def box_of(self, rows: np.ndarray, cols: np.ndarray) -> Box:
        return Box(
            cols.min() * self.cell,
            rows.min() * self.cell,
            (cols.max() + 1) * self.cell,
            (rows.max() + 1) * self.cell,
        )


def dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    """Square dilation by ``radius`` cells (separable max filter)."""
    if radius <= 0:
        return mask.copy()
    out = mask.copy()
    for shift in range(1, radius + 1):
        out[shift:, :] |= mask[:-shift, :]
        out[:-shift, :] |= mask[shift:, :]
    rows = out.copy()
    for shift in range(1, radius + 1):
        out[:, shift:] |= rows[:, :-shift]
        out[:, :-shift] |= rows[:, shift:]
    return out


def label_components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """4-connected component labelling via run-length union-find.

    Returns (labels, count) with labels 1..count and 0 for background.
    """
    rows = mask.shape[0]
    runs: list[tuple[int, int, int]] = []  # (row, start, end_exclusive)
    row_runs: list[range] = []
    parent: list[int] = []

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for r in range(rows):
        padded = np.concatenate(([0], mask[r].astype(np.int8), [0]))
        diff = np.diff(padded)
        starts = np.flatnonzero(diff == 1)
        ends = np.flatnonzero(diff == -1)
        first = len(runs)
        for s, e in zip(starts, ends, strict=True):
            runs.append((r, int(s), int(e)))
            parent.append(len(parent))
        row_runs.append(range(first, len(runs)))
        if r == 0:
            continue
        prev = row_runs[r - 1]
        i, j = prev.start, first
        while i < prev.stop and j < len(runs):
            _, ps, pe = runs[i]
            _, cs, ce = runs[j]
            if ps < ce and cs < pe:
                a, b = find(i), find(j)
                if a != b:
                    parent[b] = a
            if pe < ce:
                i += 1
            else:
                j += 1

    labels = np.zeros(mask.shape, dtype=np.int32)
    roots: dict[int, int] = {}
    for idx, (r, s, e) in enumerate(runs):
        root = find(idx)
        label = roots.setdefault(root, len(roots) + 1)
        labels[r, s:e] = label
    return labels, len(roots)
