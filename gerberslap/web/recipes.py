"""The routes of the recipe library: recipes and their dosages, kept in the server's data folder (one library for the whole house).

They exist only when the app was started with a data folder and without `--no-library`: in that mode the routes are not there at all (404),
which is the point (hiding the controls in the page would not be enough). Every route answers with the recipe as it is afterwards, so
that the page needs nothing else; the server's rules (polarity fixed, dates, limits) live in `services/library.py` and `services/store.py`.
Errors are `StoreError`s that the app turns into a status and a code.
"""
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from ..model import Development, DosageName, DosageNote, Polarity, RecipeNotes, Resist
from ..model.base import Id, Name
from ..model.exposure import PulseCount, RestSeconds, TotalSeconds
from ..services.library import Library


class _Body(BaseModel):
    """What the page may send: nothing unknown, and no NaN or infinity."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RecipeCreate(_Body):
    name: Name
    polarity: Polarity
    resist: Resist = ""
    development: Development = ""
    notes: RecipeNotes = ""


class RecipeEdit(_Body):
    """What to change. The polarity may be there only if it is the one the recipe has: it is fixed when the recipe is created."""
    name: Optional[Name] = None
    polarity: Optional[Polarity] = None
    resist: Optional[Resist] = None
    development: Optional[Development] = None
    notes: Optional[RecipeNotes] = None


class RecipeDuplicate(_Body):
    name: Name
    polarity: Polarity


class DosageCreate(_Body):
    printer_id: Id
    total_s: TotalSeconds
    pulses: PulseCount
    rest_s: RestSeconds
    name: DosageName = ""
    note: DosageNote = ""


class DosageEdit(_Body):
    total_s: Optional[TotalSeconds] = None
    pulses: Optional[PulseCount] = None
    rest_s: Optional[RestSeconds] = None
    name: Optional[DosageName] = None
    note: Optional[DosageNote] = None


class DosageCopy(_Body):
    printer_id: Id
    note: Optional[DosageNote] = None


def recipes_router(library: Library, check_printer: Callable[[str], object]) -> APIRouter:
    """`check_printer(id)` raises the app's error if the app has no such printer: a dosage is for a printer this version knows."""
    r = APIRouter()
    out = lambda recipe: recipe.model_dump(mode="json")                      # noqa: E731

    @r.get("")
    def list_recipes():
        listing = library.list()
        return {"recipes": [out(x) for x in listing.items],
                "problems": [{"file": Path(p.path).name, "code": p.code} for p in listing.problems]}      # the file name, never the path

    @r.post("", status_code=201)
    def create_recipe(body: RecipeCreate):
        return out(library.create(**body.model_dump()))

    @r.get("/{recipe_id}")
    def get_recipe(recipe_id: str):
        return out(library.get(recipe_id))

    @r.patch("/{recipe_id}")
    def edit_recipe(recipe_id: str, body: RecipeEdit):
        return out(library.edit(recipe_id, **body.model_dump()))

    @r.delete("/{recipe_id}")
    def delete_recipe(recipe_id: str):
        library.delete(recipe_id)
        return {"deleted": recipe_id}

    @r.post("/{recipe_id}/duplicate", status_code=201)
    def duplicate_recipe(recipe_id: str, body: RecipeDuplicate):
        return out(library.duplicate(recipe_id, **body.model_dump()))

    @r.post("/{recipe_id}/dosages", status_code=201)
    def add_dosage(recipe_id: str, body: DosageCreate):
        check_printer(body.printer_id)
        return out(library.add_dosage(recipe_id, **body.model_dump()))

    @r.patch("/{recipe_id}/dosages/{dosage_id}")
    def edit_dosage(recipe_id: str, dosage_id: str, body: DosageEdit):
        return out(library.edit_dosage(recipe_id, dosage_id, **body.model_dump()))

    @r.delete("/{recipe_id}/dosages/{dosage_id}")
    def delete_dosage(recipe_id: str, dosage_id: str):
        return out(library.delete_dosage(recipe_id, dosage_id))

    @r.post("/{recipe_id}/dosages/{dosage_id}/copy", status_code=201)
    def copy_dosage(recipe_id: str, dosage_id: str, body: DosageCopy):
        check_printer(body.printer_id)
        return out(library.copy_dosage(recipe_id, dosage_id, **body.model_dump()))

    return r
