"""Building blocks shared by the whole data model.

Every model is immutable (a project is a value that is sent around, never edited in place), rejects fields it does not
know and rejects NaN and infinity. Identifiers end up in file paths (data/printers/<id>/...), so they are restricted to
a safe alphabet with no separators and no leading dot.
"""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, JsonValue, StringConstraints

Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
# text shown to the user: no control characters (a newline in a name would break the summaries and the file names)
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200, pattern=r"^[^\x00-\x1f\x7f]+$")]
# a file name as it appears in a zip or in the data folder: never a path
FileName = Annotated[str, StringConstraints(min_length=1, max_length=255, pattern=r"^[^\x00-\x1f\x7f/\\]+$")]
# machine-readable code of a status or of an issue; the interface turns it into a text
Code = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.]{0,63}$")]

SCHEMA_VERSION = 1                 # of the files in the data folder (recipes, printer settings)
PROJECT_SCHEMA_VERSION = 2         # of the project file: version 2 names a recipe and a dosage instead of a profile (see services/projectfile.py)


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


__all__ = ["Id", "Sha256", "Color", "Name", "FileName", "Code", "JsonValue", "Model", "SCHEMA_VERSION", "PROJECT_SCHEMA_VERSION"]
