"""The data folder: what the person who installs the app puts there, and the library of recipes.

    data/
      printers/<id>/<template file>       the template of a printer: the driver says its file name; never in the repository
      printers/<id>/printer.json           optional: only the settings someone wants to change from the driver's defaults
      recipes/<id>.json                    one file per recipe, with its dosages inside

Rules: every write is atomic (a crash leaves the old file, never half a new one); a file that cannot be read is reported, never skipped
in silence and never repaired by guessing; a recipe's polarity never changes (it is fixed when the recipe is created). The store knows
nothing about printers' file formats: whoever installs a template passes the check that belongs to the driver.

Single user, one process per folder: calls are serialised with a lock, so that web threads do not trample each other, and a change to a
recipe is read, changed and written inside the lock (two browsers never lose each other's changes). Two processes on the same folder
are not supported.
"""
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Generic, Optional, TypeVar

from pydantic import TypeAdapter, ValidationError

from ..model import MAX_RECIPES, SCHEMA_VERSION, PrinterFile, Recipe
from ..model.base import FileName, Id
from .files import write_atomic, write_temp

T = TypeVar("T")

MAX_TEMPLATE_BYTES = 128 * 1024 * 1024
RESERVED_PRINTER_FILES = frozenset({"printer.json"})
_ID = TypeAdapter(Id)
_FILE = TypeAdapter(FileName)


class StoreError(Exception):
    """Something the caller can act on. `code` is stable (the API maps it to a status and the interface to a text)."""
    code = "store_error"

    def __init__(self, detail="", *, path=None, code=None):
        super().__init__(detail or self.code)
        self.detail, self.path = detail, path
        if code:
            self.code = code


class NotFound(StoreError):
    code = "not_found"


class AlreadyExists(StoreError):
    code = "already_exists"


class Invalid(StoreError):
    code = "invalid"


class Refused(StoreError):
    code = "refused"


@dataclass(frozen=True)
class Problem:
    """A file in the folder that could not be used, with why."""
    path: str
    code: str
    detail: str


@dataclass(frozen=True)
class Listing(Generic[T]):
    items: tuple = ()
    problems: tuple = field(default=())


def default_root() -> Path:
    return Path(os.environ.get("GERBERSLAP_DATA", "data"))


def _check_id(value, what="id") -> str:
    try:
        return _ID.validate_python(value)
    except ValidationError:
        raise Invalid(f"not a valid {what}: {value!r}", code="bad_id") from None


def _check_file_name(value) -> str:
    try:
        return _FILE.validate_python(value)
    except ValidationError:
        raise Invalid(f"not a valid file name: {value!r}", code="bad_file_name") from None


def _envelope(kind: str, key: str, payload) -> bytes:
    body = {"format": f"gerberslap-{kind}", "schema_version": SCHEMA_VERSION, key: payload}
    return (json.dumps(body, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _open_envelope(kind: str, key: str, raw: bytes, path: Path):
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Invalid(f"not valid JSON: {exc}", path=str(path), code="bad_json") from None
    if not isinstance(body, dict) or body.get("format") != f"gerberslap-{kind}" or key not in body:
        raise Invalid(f"not a {kind} file", path=str(path), code="wrong_format")
    version = body.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise Invalid("missing or bad schema_version", path=str(path), code="bad_version")
    if version > SCHEMA_VERSION:
        raise Invalid(f"written by a newer version (schema {version}, this one reads up to {SCHEMA_VERSION})",
                      path=str(path), code="newer_schema")
    return body[key]            # schema 1 is the only one so far: older versions will be migrated here


def _validate(model, payload, path: Path):
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise Invalid(f"{where}: {first['msg']}", path=str(path), code="bad_content") from None


class DataStore:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root if root is not None else default_root()).absolute()
        self._lock = threading.RLock()

    # ---- paths -------------------------------------------------------------------------------------------------
    def _inside(self, path: Path) -> Path:
        """`path` must stay under the root once symbolic links are followed (defence in depth: ids are already safe)."""
        resolved = path.resolve()
        try:
            resolved.relative_to(self.root.resolve())
        except ValueError:
            raise Invalid("path leaves the data folder", path=str(path), code="outside_root") from None
        return path

    def _printer_dir(self, printer_id: str) -> Path:
        return self._inside(self.root / "printers" / _check_id(printer_id, "printer id"))

    def _read(self, path: Path) -> bytes:
        try:
            return self._inside(path).read_bytes()
        except FileNotFoundError:
            raise NotFound(str(path), path=str(path)) from None
        except OSError as exc:
            raise Invalid(f"cannot read: {exc}", path=str(path), code="unreadable") from None

    # ---- printers: the template and the optional settings ---------------------------------------------------------
    def printer_settings(self, printer_id: str) -> dict:
        """The settings someone wrote in `printers/<id>/printer.json`; none (the driver's defaults) when there is no such file.
        A file that is there and cannot be read is an error, never the defaults in silence."""
        path = self._printer_dir(printer_id) / "printer.json"
        try:
            raw = self._read(path)
        except NotFound:
            return {}
        return dict(_validate(PrinterFile, _open_envelope("printer", "printer", raw, path), path).settings)

    def printer_file(self, printer_id: str, name: str) -> Path:
        """Path of a file in a printer's folder (its template, for one)."""
        name = _check_file_name(name)
        path = self._inside(self._printer_dir(printer_id) / name)
        if not path.is_file():
            raise NotFound(f"no file {name} for printer {printer_id}")
        return path

    def set_template(self, printer_id: str, name: str, data: bytes, *,
                     validate: Optional[Callable[[Path], None]] = None) -> Path:
        """Install the user's template for a printer under `name`, replacing the one there. `validate(path)` is the driver's check; it
        raises to reject the file, and then nothing changes. Returns where the template is."""
        name = _check_file_name(name)
        if name.startswith(".") or name in RESERVED_PRINTER_FILES:
            raise Invalid(f"{name!r} cannot be used as a template name", code="bad_file_name")
        if not data:
            raise Invalid("the template is empty", code="template_rejected")
        if len(data) > MAX_TEMPLATE_BYTES:
            raise Invalid("the template is too large", code="template_too_large")
        with self._lock:
            directory = self._printer_dir(printer_id)
            tmp = write_temp(directory, data)
            try:
                if validate is not None:
                    try:
                        validate(tmp)
                    except Exception as exc:
                        raise Invalid(str(exc), code="template_rejected") from exc
                os.replace(tmp, self._inside(directory / name))
            finally:
                tmp.unlink(missing_ok=True)
            return directory / name

    # ---- recipes -----------------------------------------------------------------------------------------------
    def _recipes_dir(self) -> Path:
        return self._inside(self.root / "recipes")

    def _recipe_path(self, recipe_id: str) -> Path:
        return self._inside(self._recipes_dir() / f"{_check_id(recipe_id, 'recipe id')}.json")

    def _load_recipe(self, path: Path) -> Recipe:
        recipe = _validate(Recipe, _open_envelope("recipe", "recipe", self._read(path), path), path)
        if recipe.id != path.stem:
            raise Invalid(f"{path.name} holds the recipe {recipe.id!r}", path=str(path), code="id_mismatch")
        return recipe

    def _recipe_files(self) -> list:
        directory = self._recipes_dir()
        if not directory.is_dir():
            return []
        return sorted(p for p in directory.iterdir() if p.suffix == ".json" and not p.name.startswith("."))

    def list_recipes(self) -> Listing:
        """The recipes by name, and the files that could not be used, said apart (never skipped in silence)."""
        items, problems = [], []
        for path in self._recipe_files():
            try:
                _check_id(path.stem, "recipe file name")
                items.append(self._load_recipe(path))
            except StoreError as exc:
                problems.append(Problem(path=str(path), code=exc.code, detail=exc.detail))
        items.sort(key=lambda r: (r.name.casefold(), r.id))
        return Listing(tuple(items), tuple(problems))

    def get_recipe(self, recipe_id: str) -> Recipe:
        path = self._recipe_path(recipe_id)
        try:
            return self._load_recipe(path)
        except NotFound:
            raise NotFound(f"no recipe {recipe_id}", code="recipe_not_found") from None

    def create_recipe(self, recipe: Recipe) -> None:
        """A new recipe; it never replaces one."""
        with self._lock:
            if len(self._recipe_files()) >= MAX_RECIPES:
                raise Refused(f"the library holds at most {MAX_RECIPES} recipes", code="too_many_recipes")
            try:
                write_atomic(self._recipe_path(recipe.id), _envelope("recipe", "recipe", recipe.model_dump(mode="json")), exclusive=True)
            except FileExistsError:
                raise AlreadyExists(f"the recipe {recipe.id} exists", code="recipe_exists") from None

    def update_recipe(self, recipe_id: str, change: Callable[[Recipe], Recipe]) -> Recipe:
        """Read the recipe, apply `change` (which returns the new one) and write it, all inside the lock, so that two changes never
        lose one another. The id and the polarity cannot change."""
        with self._lock:
            old = self.get_recipe(recipe_id)
            new = change(old)
            if new.id != old.id:
                raise Invalid("a recipe's id cannot change", code="bad_content")
            if new.polarity != old.polarity:
                raise Refused("a recipe's polarity cannot change: if the resist is another, it is another recipe", code="polarity_locked")
            write_atomic(self._recipe_path(recipe_id), _envelope("recipe", "recipe", new.model_dump(mode="json")))
            return new

    def delete_recipe(self, recipe_id: str) -> None:
        with self._lock:
            path = self._recipe_path(recipe_id)
            try:
                path.unlink()
            except FileNotFoundError:
                raise NotFound(f"no recipe {recipe_id}", code="recipe_not_found") from None
