"""The library of recipes and their dosages: what a person does with it, on top of the data folder's storage.

Every operation changes a recipe through `DataStore.update_recipe`, which reads, changes and writes inside one lock: two browsers
adding dosages to the same recipe never lose each other's (for the same dosage, the last save wins). Every operation returns the
recipe as it is afterwards, so that the page needs nothing else.

Rules:
  - the polarity of a recipe never changes; a recipe is duplicated to get another polarity;
  - a dosage is for one printer; those of another printer are never used in silence (that is the page's business: here they are only data);
  - `updated` of a dosage changes only when its values change, not for a new name or note;
  - a copy of a dosage is independent of its source.
"""
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from pydantic import ValidationError

from ..model import MAX_DOSAGES, Dosage, Polarity, Recipe
from .store import DataStore, Invalid, Listing, NotFound, Refused


def _build(model, **fields):
    try:
        return model(**fields)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise Invalid(f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}", code="bad_content") from None


class Library:
    def __init__(self, store: DataStore, *, now: Optional[Callable[[], datetime]] = None, new_id: Optional[Callable[[], str]] = None):
        self.store = store
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._new_id = new_id or (lambda: str(uuid.uuid4()))

    def _moment(self) -> datetime:
        return self._now().astimezone(timezone.utc).replace(microsecond=0)

    # ---- recipes -----------------------------------------------------------------------------------------------
    def list(self) -> Listing:
        return self.store.list_recipes()

    def get(self, recipe_id: str) -> Recipe:
        return self.store.get_recipe(recipe_id)

    def create(self, *, name: str, polarity: Polarity, resist: str = "", development: str = "", notes: str = "") -> Recipe:
        recipe = _build(Recipe, id=self._new_id(), name=name, polarity=polarity, resist=resist, development=development, notes=notes)
        self.store.create_recipe(recipe)
        return recipe

    def edit(self, recipe_id: str, *, name: Optional[str] = None, polarity: Optional[Polarity] = None, resist: Optional[str] = None,
             development: Optional[str] = None, notes: Optional[str] = None) -> Recipe:
        """Change what is given. The polarity may be given only if it is the one the recipe has (a client may send the whole recipe)."""
        def change(old: Recipe) -> Recipe:
            if polarity is not None and Polarity(polarity) != old.polarity:
                raise Refused("a recipe's polarity cannot change: duplicate the recipe and choose the polarity in the copy", code="polarity_locked")
            fields = {k: v for k, v in (("name", name), ("resist", resist), ("development", development), ("notes", notes)) if v is not None}
            return _build(Recipe, **{**old.model_dump(), **fields, "dosages": old.dosages})
        return self.store.update_recipe(recipe_id, change)

    def duplicate(self, recipe_id: str, *, name: str, polarity: Polarity) -> Recipe:
        """A new recipe with the same text and dosages (new ids), and the polarity chosen for the copy."""
        source = self.store.get_recipe(recipe_id)
        copy = _build(Recipe, **{**source.model_dump(exclude={"dosages"}), "id": self._new_id(), "name": name, "polarity": polarity},
                      dosages=tuple(d.model_copy(update={"id": self._new_id()}) for d in source.dosages))
        self.store.create_recipe(copy)
        return copy

    def delete(self, recipe_id: str) -> None:
        self.store.delete_recipe(recipe_id)

    # ---- dosages -----------------------------------------------------------------------------------------------
    def add_dosage(self, recipe_id: str, *, printer_id: str, total_s: float, pulses: int, rest_s: float, name: str = "", note: str = "") -> Recipe:
        def change(old: Recipe) -> Recipe:
            if len(old.dosages) >= MAX_DOSAGES:
                raise Refused(f"a recipe holds at most {MAX_DOSAGES} dosages", code="too_many_dosages")
            dosage = _build(Dosage, id=self._new_id(), printer_id=printer_id, updated=self._moment(), total_s=total_s, pulses=pulses,
                            rest_s=rest_s, name=name, note=note)
            return old.model_copy(update={"dosages": (*old.dosages, dosage)})
        return self.store.update_recipe(recipe_id, change)

    def _with_dosage(self, recipe_id: str, dosage_id: str, make: Callable[[Recipe, Dosage], tuple]) -> Recipe:
        """Change the dosages of a recipe: `make(recipe, dosage)` returns the new tuple of dosages."""
        def change(old: Recipe) -> Recipe:
            dosage = old.dosage(dosage_id)
            if dosage is None:
                raise NotFound(f"no dosage {dosage_id} in the recipe {recipe_id}", code="dosage_not_found")
            return _build(Recipe, **{**old.model_dump(exclude={"dosages"}), "dosages": make(old, dosage)})
        return self.store.update_recipe(recipe_id, change)

    def edit_dosage(self, recipe_id: str, dosage_id: str, *, total_s: Optional[float] = None, pulses: Optional[int] = None,
                    rest_s: Optional[float] = None, name: Optional[str] = None, note: Optional[str] = None) -> Recipe:
        """Change what is given. `updated` becomes now only if a value really changes."""
        def make(recipe: Recipe, old: Dosage) -> tuple:
            values = {k: v for k, v in (("total_s", total_s), ("pulses", pulses), ("rest_s", rest_s)) if v is not None}
            texts = {k: v for k, v in (("name", name), ("note", note)) if v is not None}
            new = _build(Dosage, **{**old.model_dump(), **values, **texts})
            if (new.total_s, new.pulses, new.rest_s) != (old.total_s, old.pulses, old.rest_s):
                new = new.model_copy(update={"updated": self._moment()})
            return tuple(new if d.id == old.id else d for d in recipe.dosages)
        return self._with_dosage(recipe_id, dosage_id, make)

    def delete_dosage(self, recipe_id: str, dosage_id: str) -> Recipe:
        return self._with_dosage(recipe_id, dosage_id, lambda recipe, old: tuple(d for d in recipe.dosages if d.id != old.id))

    def copy_dosage(self, recipe_id: str, dosage_id: str, *, printer_id: str, note: Optional[str] = None) -> Recipe:
        """A new dosage, for `printer_id`, with the values of the source (a copy that from now on changes by itself). The note is the
        one given, else the source's."""
        def make(recipe: Recipe, source: Dosage) -> tuple:
            if len(recipe.dosages) >= MAX_DOSAGES:
                raise Refused(f"a recipe holds at most {MAX_DOSAGES} dosages", code="too_many_dosages")
            copy = _build(Dosage, **{**source.model_dump(), "id": self._new_id(), "printer_id": printer_id, "updated": self._moment(),
                                     **({"note": note} if note is not None else {})})
            return (*recipe.dosages, copy)
        return self._with_dosage(recipe_id, dosage_id, make)
