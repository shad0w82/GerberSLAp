"""Problems found by the checks. They carry a code and parameters, never a text: the interface owns the wording
(Italian and English catalogues), and the backend stays free of user-facing strings."""
from enum import Enum
from typing import Optional

from pydantic import Field

from .base import Code, Id, JsonValue, Model


class Severity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


class Issue(Model):
    code: Code
    severity: Severity
    blocking: bool = False            # a blocking issue stops the generation of the file; the others only inform
    board_id: Optional[Id] = None
    layer_id: Optional[Id] = None
    params: dict[str, JsonValue] = Field(default_factory=dict)


class C:
    """The codes the checks can produce."""
    NO_LAYER_ON = "no_layer_on"                          # no drawing layer is on anywhere (blocks)
    BOARD_NO_LAYER_ON = "board_no_layer_on"              # a board has no drawing layer on (blocks)
    LAYER_ERROR_ON = "layer_error_on"                    # a layer with an error is switched on (blocks)
    LAYER_ISSUE = "layer_issue"                          # a layer's own warning or error; params.status_code says which
    BOARD_OUTSIDE_PLANE = "board_outside_plane"
    BOARDS_OVERLAP = "boards_overlap"                    # params: board_a, board_b
    BOARD_LAYER_SUM = "board_layer_sum"                  # several layer types on in one board: the result is the sum
    LAYER_TYPES_MIXED = "layer_types_mixed"              # different layer types across boards of the same file
    PRINTER_MISSING = "printer_missing"                  # blocks
    RECIPE_MISSING = "recipe_missing"                    # blocks
    POLARITY_MISMATCH = "polarity_mismatch"              # params: project, recipe
    DOSAGE_MISSING = "dosage_missing"                    # the recipe has no dosage for this printer
    EXPOSURE_INVALID = "exposure_invalid"                # blocks; params.reason: missing
    FLASH_BELOW_MINIMUM = "flash_below_minimum"          # blocks; params: flash_s, min_s
    FLASH_BEYOND_PROVEN = "flash_beyond_proven"          # params: flash_s, max_s
    LADDER_TOO_BIG = "ladder_too_big"                    # the strips do not fit the plane; blocks; params: width_mm, height_mm, plane_w_mm, plane_h_mm
    LADDER_NO_TESTS = "ladder_no_tests"                  # no test is switched on: the strips are empty
    LADDER_TESTS_DROPPED = "ladder_tests_dropped"        # tests that have no room in a strip; params: ids
    BOARD_CLIPPED = "board_clipped"                      # the placed material goes past the plane; params: extent_mm, plane_mm
    TEMPLATE_MISSING = "template_missing"                # the printer has no template file; blocks. Raised by drivers
    TEMPLATE_INVALID = "template_invalid"                # blocks; params: reason
    TEMPLATE_LIFT_LARGE = "template_lift_large"          # the motion copied from the template makes every flash slow; params: lift_mm
    PRINTER_SETTINGS_INVALID = "printer_settings_invalid"  # blocks; params: field, message
    PRINTER_CONFIG_INVALID = "printer_config_invalid"    # the printer's file in the data folder cannot be used; blocks; params: reason
    # findings when a zip is opened
    NO_OUTLINE = "no_outline"                            # the board size comes from the copper
    NO_DRILL = "no_drill"                                # no drill file: the pads stay full
    JOB_SIZE_MISMATCH = "job_size_mismatch"              # the job file's board size differs from the outline; params
    FILES_UNRECOGNISED = "files_unrecognised"            # Gerber files whose role could not be told; params: names
    BOARD_AREA_ESTIMATED = "board_area_estimated"        # the mask uses the extent rectangle as the board; params.reason: why


class LC:
    """The codes a layer's own status can carry."""
    UNREADABLE = "unreadable"                            # the parser failed; params: reason
    NEGATIVE_IMAGE = "negative_image"                    # drawn as a negative (planes): needs the board area, unsupported
    MASK_COVERS_BOARD = "mask_covers_board"              # a warning: the mask draws most of the board, it may be inverted; params: percent
    DRILL_OUTSIDE_BOARD = "drill_outside_board"          # holes beyond the board: the file is not read as it should be
