"""Printer-independent core: read Gerber/Excellon, build geometry, place it, rasterize it.

Nothing in here knows about any printer or its file format: coordinates are millimetres on the exposure plane
(u = left to right, v = front to back, seen from above) and the pixel grid is a parameter.
"""
from .errors import GerberError
from .geometry import (BoardArea, Placement, area_or_rectangle, board_area, compose_material, extent_center, extent_size,
                       holes_geometry, layer_geometry, outline_lines, outline_strokes, place)
from .gerber_io import ReadResult, ZipContents, read_file, sniff_kind, zip_members
from .raster import Grid, binarize, coverage, exposure_mask

__all__ = ["GerberError", "BoardArea", "Placement", "area_or_rectangle", "board_area", "compose_material", "extent_center", "extent_size", "holes_geometry",
           "layer_geometry", "outline_lines", "outline_strokes", "place", "ReadResult", "ZipContents", "read_file",
           "sniff_kind", "zip_members", "Grid", "binarize", "coverage", "exposure_mask"]
