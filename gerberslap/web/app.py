"""The web app: a thin API over the services, and the static page. Local and single user: the browser holds the layout and sends
it with each call; the server keeps only the Gerber files it has read (by hash) and what it parsed from them.

Because anything on this machine can reach a local port, every request is checked: the Host must be a local name (against DNS
rebinding) and a request that changes anything must come from the page itself (not from another site open in the browser).
"""
import base64
import io
import json
import logging
import re
import secrets
from dataclasses import asdict
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from .. import __version__
from ..cad import ImportRefused
from ..core import GerberError
from ..model import ExposureValues, FileRef, LadderSpec, Polarity, Project, RecipeRef, Role, Size
from ..model.base import Id, Name
from ..printers import Registry, UnknownDriver, registry as printer_registry
from ..printers.base import DriverError
from ..services.checks import check_project, layout_issues
from ..services.generate import GenerationBlocked, generate, reference_config
from ..services.ladder import generate_ladder, ladder_file_name
from ..services.importer import import_zip
from ..services.installation import printer_issues
from ..services.library import Library
from ..services.pipeline import PipelineCache, PipelineError, Reader, render
from ..services.projectfile import BoardInfo, ProjectFileError, open_project, save_project
from ..services.store import AlreadyExists, DataStore, NotFound, Refused, StoreError
from ..services.vector import AreaSpec, layer_vectors
from .filestore import FileStore, StoreFull
from .recipes import recipes_router

log = logging.getLogger("gerberslap.web")
STATIC = Path(__file__).parent / "static"
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_SAMPLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.zip$")
_ID = TypeAdapter(Id)


class ApiError(Exception):
    def __init__(self, status: int, code: str, **params):
        super().__init__(code)
        self.status, self.code, self.params = status, code, params


def _error(status: int, code: str, **params) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "params": params}}, status_code=status)


def _hostname(host_header: str) -> str:
    h = host_header.strip().lower()
    if h.startswith("["):                                   # [::1]:8800
        return h[1:h.find("]")] if "]" in h else h
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


class Request_(BaseModel):
    """What the page may send: nothing unknown, and no NaN or infinity (a NaN in a position would poison every shape)."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AreaRequest(Request_):
    """Only for a mask: the outline file the board's area comes from (none if the board has none) and the board's size."""
    outline: Optional[FileRef] = None
    size: Size


class GeometryRequest(Request_):
    role: Role
    files: list[FileRef] = Field(min_length=1, max_length=8)
    holes: list[FileRef] = Field(default_factory=list, max_length=8)
    center: tuple[float, float]
    min_outline_mm: float = Field(default=0.3, ge=0, le=5)
    area: Optional[AreaRequest] = None


class SaveRequest(Request_):
    """The project and what the page keeps about its boards (the CAD program and the notes made when the zip was opened)."""
    project: Project
    name: Optional[Name] = None
    info: dict[Id, BoardInfo] = Field(default_factory=dict)


def _download_name(name: Optional[str], project: Project, extension: str = ".gslp") -> str:
    """A file name that is safe in a header and on any disk: letters, digits, dot, dash and underscore, whatever the project is called."""
    base = name or (project.boards[0].name if project.boards else "") or "project"
    return (re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._-")[:80] or "project") + extension


class RenderRequest(Request_):
    project: Project
    polarity: Polarity
    supersample: int = Field(default=16, ge=8, le=16)


class CheckRequest(Request_):
    """Without `exposure` (the key left out) only the layout is checked. With it (null if there are no values yet) the checks are all of them:
    what the project refers to (the printer, and the recipe the person chose, if any: `recipe`) and the values."""
    project: Project
    exposure: Optional[ExposureValues] = None
    recipe: Optional[RecipeRef] = None


class LadderRequest(Request_):
    """The file of the calibration ladder: the printer it is for (none: the default one) and the values of the page."""
    printer_id: Optional[Id] = None
    ladder: LadderSpec
    supersample: int = Field(default=16, ge=8, le=16)


class GenerateRequest(Request_):
    """All the server needs to make the file; it reads nothing else (no library). `name` is the project's name, which names the file."""
    project: Project
    polarity: Polarity
    exposure: ExposureValues
    recipe: Optional[RecipeRef] = None
    name: Optional[Name] = None
    supersample: int = Field(default=16, ge=8, le=16)


def _file(made, filename: str) -> Response:
    """A file the server made, as a download: the bytes, the name, and what the driver says of it in a header (JSON, ASCII)."""
    return Response(made.data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"', "X-Build-Summary": json.dumps(asdict(made.summary), separators=(",", ":"))})


def _printer_json(d) -> dict:
    """What the page needs to know of a printer: its name, the plane in mm and the pixel grid of that plane."""
    return {"id": d.id, "name": d.name, "plane": d.plane.model_dump(),
            "grid": {"width": d.grid.width, "height": d.grid.height, "pitch": d.grid.pitch}, "limits": d.limits.model_dump()}


def create_app(*, driver_id: Optional[str] = None, printers: Optional[Registry] = None, allowed_hosts=(),
               dev_samples: Optional[Path] = None, max_upload: int = MAX_UPLOAD_BYTES, store_bytes: int = 1 << 30,
               store: Optional[DataStore] = None, library: bool = True, dev_printers: bool = False) -> FastAPI:
    """`printers`: the printers the app knows (default: the drivers found in `printers/`); `driver_id`: the one a project without a printer
    uses (default: the first by id); `store`: the data folder the person who installed the app prepared (the printers' templates), none
    in a test that needs none: a printer that needs a template is then reported as not ready. `library`: whether the recipe library is on (it
    needs the data folder; with `library=False`, the option `--no-library`, its routes do not exist). `dev_printers`: only says that the made-up printers
    are among `printers` (`--dev-printers`), so that the page can tell how the app was started (`flags` in `/api/info`)."""
    known = printers if printers is not None else printer_registry()
    if not known.drivers:
        raise RuntimeError("no printer driver was found")
    driver = known.get(driver_id or known.ids()[0])

    def printer(printer_id):
        """The driver a project asks for: the default one if it asks for none, an error that names it if it is not one of ours."""
        if not printer_id:
            return driver
        try:
            return known.get(printer_id)
        except UnknownDriver:
            raise ApiError(422, "unknown_printer", printer_id=printer_id[:64]) from None
    allowed = LOCAL_HOSTS | {h.lower() for h in allowed_hosts}
    app = FastAPI(title="GerberSLAp", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.driver, app.state.printers, app.state.data = driver, known, store
    lib = Library(store) if (library and store is not None) else None
    # how the app was started, for the page to say (names only: never a path, a host or a port, which a public page must not show)
    flags = [name for name, on in (("--no-library", not library), ("--dev-printers", dev_printers), ("--dev-samples", dev_samples is not None)) if on]
    app.state.files, app.state.cache = FileStore(store_bytes), PipelineCache(256)
    api = APIRouter(prefix="/api")

    # ---- protection of a local server -----------------------------------------------------------------------------
    @app.middleware("http")
    async def protect(request: Request, call_next):
        if _hostname(request.headers.get("host", "")) not in allowed:
            return _error(403, "bad_host")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin, site = request.headers.get("origin"), request.headers.get("sec-fetch-site")
            if (origin and urlparse(origin).netloc != request.headers.get("host")) or (site and site not in ("same-origin", "none")):
                return _error(403, "cross_site")
        response = await call_next(request)
        if "cache-control" not in response.headers:                          # nothing is kept by the browser, except what a route says it can keep (a printer's picture)
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    # ---- errors ----------------------------------------------------------------------------------------------------
    @app.exception_handler(ApiError)
    async def _api_error(request, exc):
        return _error(exc.status, exc.code, **exc.params)

    @app.exception_handler(ImportRefused)
    async def _refused(request, exc):
        return _error(422, exc.code, **exc.params)

    @app.exception_handler(GerberError)
    async def _gerber(request, exc):
        return _error(422, exc.code, name=exc.name, reason=str(exc.reason)[:200])

    @app.exception_handler(PipelineError)
    async def _pipeline(request, exc):
        return _error(422, exc.code, **exc.params)

    @app.exception_handler(ProjectFileError)
    async def _project_file(request, exc):
        return _error(500 if exc.code == "verification_failed" else 422, exc.code, **exc.params)

    @app.exception_handler(DriverError)
    async def _driver(request, exc):
        if exc.code in ("verification_failed", "write_failed"):             # the server's own failure: said in the log, never in the page (it may name a path)
            log.error("printer driver: %s (%s)", exc.detail, exc.code)
            return _error(500, exc.code)
        return _error(422, exc.code, **exc.params)

    @app.exception_handler(StoreError)
    async def _store(request, exc):
        if isinstance(exc, NotFound):
            return _error(404, exc.code)
        if isinstance(exc, (AlreadyExists, Refused)):
            return _error(409, exc.code)
        if exc.path is None:                                    # a request the library refused for its content (an id that is not one, a value)
            return _error(422, exc.code)
        log.error("data folder: %s (%s, %s)", exc.detail, exc.code, exc.path)             # the path is for the log, never for the page
        return _error(500, "data_damaged")

    @app.exception_handler(RequestValidationError)
    async def _invalid(request, exc):
        fields = [{"loc": [str(p) for p in e["loc"]], "msg": e["msg"]} for e in exc.errors()[:10]]
        return _error(422, "invalid_request", fields=fields)

    @app.exception_handler(Exception)
    async def _internal(request, exc):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return _error(500, "internal")

    # ---- the API ---------------------------------------------------------------------------------------------------
    def printer_state(printer_id):
        """A printer as the page needs it: what it is, and whether it is ready (what its installation lacks, as issues)."""
        d = known.get(printer_id)
        issues = printer_issues(store, d)
        return {**_printer_json(d.descriptor), "picture": f"/api/printers/{d.descriptor.id}/picture" if d.picture_file() else None,      # where its picture is (none: the page draws a generic one)
                "ready": not any(i.blocking for i in issues),
                "issues": [i.model_dump(mode="json") for i in issues]}

    @api.get("/info")
    def info():
        return {"app": "GerberSLAp", "version": __version__, "default_printer": driver.descriptor.id, "library": lib is not None, "flags": flags,
                "printers": [printer_state(i) for i in known.ids()],
                "dev_samples": sorted(p.name for p in dev_samples.glob("*.zip")) if dev_samples else None}

    @api.get("/printers/{printer_id}/picture")
    def printer_picture(printer_id: str):
        try:
            path = known.get(printer_id).picture_file()
        except UnknownDriver:
            path = None
        if path is None:
            raise ApiError(404, "not_found")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})        # a file of the app, the same for everybody: it may be kept for an hour

    @api.post("/boards")
    def open_zip(file: UploadFile = File(...), board_id: Optional[str] = Form(None), mirror: bool = Form(False),
                 printer_id: Optional[str] = Form(None)):
        data = file.file.read(max_upload + 1)
        if len(data) > max_upload:
            raise ApiError(413, "too_large", max_bytes=max_upload)
        if not data:
            raise ApiError(422, "empty_file")
        bid = board_id or "b-" + secrets.token_hex(4)
        try:
            _ID.validate_python(bid)
        except ValidationError:
            raise ApiError(422, "bad_id", field="board_id") from None
        try:
            if printer_id:
                _ID.validate_python(printer_id)
        except ValidationError:
            raise ApiError(422, "bad_id", field="printer_id") from None
        imp = import_zip(data, board_id=bid, source_name=file.filename or None, plane=printer(printer_id).descriptor.plane, mirror=mirror)
        try:
            app.state.files.add(imp.files)
        except StoreFull:
            raise ApiError(507, "store_full") from None
        return {"board": imp.board.model_dump(mode="json"), "issues": [i.model_dump(mode="json") for i in imp.issues],
                "cad": imp.cad, "skipped": list(imp.skipped)}

    @api.post("/geometry")
    def geometry(req: GeometryRequest):
        reader = Reader(app.state.files, app.state.cache)
        area = AreaSpec(req.area.outline, req.area.size.width_mm, req.area.size.height_mm) if req.area else None
        return layer_vectors(reader, req.role, req.files, center=req.center, min_outline_mm=req.min_outline_mm, holes=req.holes, area=area)

    @api.post("/render")
    def render_mask(req: RenderRequest):
        r = render(req.project, app.state.files, printer(req.project.printer_id).descriptor.grid, req.polarity, supersample=req.supersample,
                   cache=app.state.cache)
        buf = io.BytesIO()
        Image.fromarray(r.mask).save(buf, format="PNG", optimize=True)                  # a bool array is a 1-bit image
        return {"png": base64.b64encode(buf.getvalue()).decode("ascii"), "width": r.grid.width, "height": r.grid.height,
                "lit_pixels": r.lit_pixels, "issues": [i.model_dump(mode="json") for i in r.issues]}

    @api.post("/check")
    def check(req: CheckRequest):
        d = printer(req.project.printer_id)
        if "exposure" not in req.model_fields_set:                          # a request that says nothing about the exposure asks for the layout only
            issues = layout_issues(req.project, d.descriptor.plane)
        else:
            issues = check_project(req.project, plane=d.descriptor.plane, printer=reference_config(store, d), recipe=req.recipe, exposure=req.exposure,
                                   limits=d.descriptor.limits)
        return {"issues": [i.model_dump(mode="json") for i in issues]}

    @api.post("/generate")
    def generate_file(req: GenerateRequest):
        d = printer(req.project.printer_id)
        try:
            made = generate(req.project, app.state.files, driver=d, store=store, polarity=req.polarity, exposure=req.exposure, recipe=req.recipe,
                            cache=app.state.cache, supersample=req.supersample)
        except GenerationBlocked as exc:
            return _error(422, "generation_blocked", issues=[i.model_dump(mode="json") for i in exc.issues])
        return _file(made, _download_name(req.name, req.project, d.descriptor.file_extension))

    @api.post("/generate/ladder")
    def generate_ladder_file(req: LadderRequest):
        d = printer(req.printer_id)
        try:
            made = generate_ladder(req.ladder, driver=d, store=store, supersample=req.supersample)
        except GenerationBlocked as exc:
            return _error(422, "generation_blocked", issues=[i.model_dump(mode="json") for i in exc.issues])
        return _file(made, ladder_file_name(req.ladder) + d.descriptor.file_extension)

    @api.post("/project/save")
    def save(req: SaveRequest):
        data = save_project(req.project, app.state.files, name=req.name, info=req.info)
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{_download_name(req.name, req.project)}"'})

    @api.post("/project/open")
    def open_saved(file: UploadFile = File(...)):
        data = file.file.read(max_upload + 1)
        if len(data) > max_upload:
            raise ApiError(413, "too_large", max_bytes=max_upload)
        if not data:
            raise ApiError(422, "empty_file")
        opened = open_project(data)                                       # nothing is kept unless the whole project is good
        try:
            app.state.files.add(opened.files)
        except StoreFull:
            raise ApiError(507, "store_full") from None
        return {"project": opened.project.model_dump(mode="json"), "name": opened.name,
                "info": {k: v.model_dump(mode="json") for k, v in opened.info.items()}}

    if lib is not None:                                                        # registered before the catch-all below
        api.include_router(recipes_router(lib, lambda printer_id: printer(printer_id)), prefix="/recipes")

    @api.api_route("/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def not_found(rest: str):
        raise ApiError(404, "not_found")

    app.include_router(api)

    # ---- sample boards for trying the page, only if the server was started with a folder of them ---------------------
    if dev_samples is not None:
        folder = Path(dev_samples).resolve()

        @app.get("/dev/samples/{name}")
        def sample(name: str):
            if not _SAMPLE.match(name):                      # before touching the file system: a name is checked, never resolved raw
                raise ApiError(404, "not_found")
            path = (folder / name).resolve()
            if path.parent != folder or not path.is_file():
                raise ApiError(404, "not_found")
            return FileResponse(path, media_type="application/zip")

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app
