---
icon: material/code-braces
---

# Esempio, test e documentazione

Questa pagina completa [Il driver di una stampante](driver.md): un driver scritto per intero, i test da scrivere, che cosa documentare e gli errori da evitare.

## Un esempio completo

Un driver minimo ma completo, con un template: una stampante immaginaria che prende uno **zip di layer PNG** con un `manifest.json`, e il cui template è un piccolo `template.json` con le impostazioni di sollevamento. Mostra tutto: descrittore, impostazioni, validazione del template, avvisi, orientamento (qui il file ha il *fronte* come prima riga), scrittura con rilettura e confronto.

Provato: scoperto dal registro, «Non pronta» senza template, template rifiutato e poi installato, file generato dall'app, flash troppo corto bloccato, scala di calibrazione che risponde `sequence_unsupported` (non implementa `build_sequence`).

`gerberslap/printers/zipdemo/__init__.py`:

```python
"""Demo printer: takes a zip of PNG layers and a manifest, with the lift settings copied from a template."""
from .driver import DRIVER

__all__ = ["DRIVER"]
```

`gerberslap/printers/zipdemo/driver.py`:

```python
import io
import json
import os
import zipfile
from pathlib import Path
from typing import Mapping, Optional

import numpy as np
from PIL import Image
from pydantic import Field, ValidationError

from gerberslap.core import Grid
from gerberslap.model import C, ExposureLimits, ExposureValues, Issue, Plane, PrinterConfig, Severity
from gerberslap.model.base import Model
from gerberslap.printers.base import (BuildError, BuildResult, BuildSummary, DriverDescriptor, PrinterDriver,
                                      SettingsError, TemplateError)

PITCH = 0.05                          # mm per pixel, the same on both axes
MIN_FLASH_S = 0.5                     # under this the printer was never tried
MAX_PROVEN_FLASH_S = 30.0


class DemoSettings(Model):
    """The driver's own settings (`printers/zipdemo/printer.json`), all optional."""
    compress_level: int = Field(default=6, ge=0, le=9)


class ZipDemoDriver(PrinterDriver):
    descriptor = DriverDescriptor(
        id="zipdemo", name="Zip demo printer",
        plane=Plane(width_mm=100.0, height_mm=60.0),            # the screen seen from above, the user in front (mm)
        grid=Grid(width=2000, height=1200, pitch=PITCH),        # 2000 x 1200 px: width x PITCH = 100 mm, height x PITCH = 60 mm
        limits=ExposureLimits(min_flash_s=MIN_FLASH_S, max_proven_flash_s=MAX_PROVEN_FLASH_S),
        requires_template=True, template_name="template.json", file_extension=".zip")

    # ---- settings and template ----------------------------------------------------------------------------------
    def parse_settings(self, settings: Optional[Mapping]) -> DemoSettings:
        try:
            return DemoSettings.model_validate(dict(settings or {}))
        except ValidationError as exc:
            first = exc.errors()[0]
            raise SettingsError(f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}",
                                field=".".join(str(p) for p in first["loc"]) or None, message=first["msg"]) from None

    def validate_template(self, path: Path) -> dict:
        def refuse(reason, **params):
            raise TemplateError(f"the template cannot be used: {reason}", reason=reason, **params)
        try:
            body = json.loads(Path(path).read_text())
        except FileNotFoundError:
            refuse("missing")
        except (OSError, ValueError):
            refuse("not_json")
        if not isinstance(body, dict) or not isinstance(body.get("lift_mm"), (int, float)) or not isinstance(body.get("lift_mm_per_min"), (int, float)):
            refuse("fields_missing")
        if not body["lift_mm"] > 0:
            refuse("lift_distance_zero")                         # the printer does its own long cycle with a lift of 0
        if not body["lift_mm_per_min"] >= 1:
            refuse("lift_speed_invalid")
        return body

    def check(self, exposure: Optional[ExposureValues], config: PrinterConfig, template_path: Optional[Path]) -> list:
        out = []
        try:
            self.parse_settings(config.settings)
        except SettingsError as exc:
            out.append(Issue(code=C.PRINTER_SETTINGS_INVALID, severity=Severity.ERROR, blocking=True,
                             params={"field": exc.params.get("field"), "message": exc.params.get("message")}))
        if template_path is None or not Path(template_path).is_file():
            out.append(Issue(code=C.TEMPLATE_MISSING, severity=Severity.ERROR, blocking=True, params={"printer_id": config.id}))
            return out
        try:
            self.validate_template(template_path)
        except TemplateError as exc:
            out.append(Issue(code=C.TEMPLATE_INVALID, severity=Severity.ERROR, blocking=True, params={"reason": exc.params.get("reason")}))
        return out

    # ---- the image and the file ---------------------------------------------------------------------------------
    def to_printer_image(self, mask: np.ndarray) -> np.ndarray:
        m = np.asarray(mask)
        if m.shape != (1200, 2000):
            raise BuildError("the mask is not the size of the plane", code="mask_shape", shape=list(m.shape), expected=[1200, 2000])
        return np.ascontiguousarray(np.flipud(m.astype(bool)))   # this printer's file has the FRONT as row 0 (the plane has the back)

    def build(self, mask, exposure: ExposureValues, config: PrinterConfig, template_path: Optional[Path], out_path: Path) -> BuildResult:
        settings = self.parse_settings(config.settings)
        if template_path is None:
            raise BuildError("this printer has no template", code="template_missing", printer_id=config.id)
        template = self.validate_template(template_path)
        flash = exposure.total_s / exposure.pulses
        if flash < MIN_FLASH_S:
            raise BuildError("a flash this short has not been tried", code="flash_below_minimum", flash_s=flash, min_s=MIN_FLASH_S)
        image = self.to_printer_image(mask)
        if not image.any():
            raise BuildError("nothing would be lit", code="mask_all_dark")
        png = io.BytesIO()
        Image.fromarray(image.astype(np.uint8) * 255).save(png, format="PNG")
        manifest = {"layers": exposure.pulses, "flash_s": flash, "rest_s": exposure.rest_s,
                    "lift_mm": template["lift_mm"], "lift_mm_per_min": template["lift_mm_per_min"]}   # the movement is the template's, copied
        out_path = Path(out_path)
        tmp = out_path.with_name(f".{out_path.name}.part")
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=settings.compress_level) as z:
                z.writestr("manifest.json", json.dumps(manifest, indent=2))
                for i in range(exposure.pulses):                  # one layer per flash, all the same
                    z.writestr(f"layer_{i:03d}.png", png.getvalue())
            self._verify(tmp, image, manifest)                    # read back and compare BEFORE it takes its place
            os.replace(tmp, out_path)
        except BuildError:
            raise
        except Exception as exc:                                  # noqa: BLE001 - nothing may escape half done
            raise BuildError(f"could not write the file: {exc}", code="write_failed", reason=str(exc)[:200]) from exc
        finally:
            tmp.unlink(missing_ok=True)
        lit = int(np.count_nonzero(image))
        summary = BuildSummary(layers=exposure.pulses, delay_layers=0, flash_s=flash, rest_s=exposure.rest_s, total_light_s=exposure.total_s,
                               estimated_s=int(exposure.pulses * (flash + exposure.rest_s)), lit_pixels=lit, lit_area_mm2=lit * PITCH ** 2,
                               file_bytes=out_path.stat().st_size, details={"template": Path(template_path).name})
        return BuildResult(path=out_path, summary=summary, verified=True)

    @staticmethod
    def _verify(path: Path, image: np.ndarray, manifest: dict) -> None:
        def bad(reason, **params):
            raise BuildError(f"the file written does not match what was meant: {reason}", code="verification_failed", reason=reason, **params)
        with zipfile.ZipFile(path) as z:
            if json.loads(z.read("manifest.json")) != manifest:
                bad("manifest")
            names = sorted(n for n in z.namelist() if n.startswith("layer_"))
            if len(names) != manifest["layers"]:
                bad("layer_count", got=len(names))
            for n in names:
                if not np.array_equal(np.asarray(Image.open(io.BytesIO(z.read(n)))) > 0, image):
                    bad("layer_image", layer=n)


DRIVER = ZipDemoDriver()
```

Il template di questa stampante (un file `template.json`, da installare con `--install-template zipdemo template.json`):

```json
{ "lift_mm": 0.001, "lift_mm_per_min": 500 }
```

Per una stampante vera, `build` non scrive un manifest ma il formato del produttore, copiando dal template tutto ciò che non è suo; la struttura è identica. Il driver reale di riferimento è `gerberslap/printers/ld002h/driver.py`.

## Test da scrivere

I test di un driver sono come quelli di `tests/test_printers.py`. L'elenco minimo:

- **Il descrittore**: `grid × pitch = plane`; un `template_name` o un'estensione non validi si rifiutano (il costruttore lo fa da solo).
- **L'orientamento**: una maschera con un solo pixel in un angolo noto arriva nell'angolo misurato sulla stampante; la forma sbagliata si rifiuta con `mask_shape`. Se possibile, un secondo controllo calcolato in un altro modo (un oracolo indipendente).
- **Il template**: un caso per ogni `reason` di `validate_template`, e uno buono. Il template di prova **si costruisce nel test** (non si committa un file del produttore); i test che richiedono un template vero si saltano se manca, come fa `needs_template` in `tests/test_printers.py`.
- **I controlli**: `template_missing`, `template_invalid`, `printer_settings_invalid`, e «nessun avviso» quando tutto va.
- **La scrittura**: il file si rilegge e coincide con ciò che si voleva; **i rifiuti avvengono prima di scrivere** (nessun file lasciato, nessun `.part`); la dose si realizza come deve (numero e tempo dei layer, riposo).
- **La rilettura**: un test che altera il file scritto (o simula un errore) e verifica che `build` non consegni nulla.
- **Da zero fino all'app**: il driver in un `Registry`, un `DataStore` temporaneo, il template installato con `install_template`, uno zip caricato e `POST /api/generate` (vedi `tests/test_generate.py` e `tests/support/fakeprinters.py`, che ha una stampante finta che scrive pochi byte).
- **La scala**, se si implementa `build_sequence`: più maschere, nell'ordine, con i flash giusti.
- **I confini**: si aggiungono il nome della stampante e l'estensione del formato all'espressione di `test_the_generic_packages_never_name_a_printer_or_its_file_format` in `tests/test_printers.py` (oggi `ctb|ld-?002h|creality`), così nessuno li scrive per sbaglio nel nucleo, nel modello dati o nei servizi.
- **La foto**: la controlla già il test che scorre tutti i driver.

Un esempio, per il driver di sopra (`tests/test_zipdemo.py`):

```python
"""Tests of a new driver (the example of the guide), written the way tests/test_printers.py writes them."""
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

from gerberslap.printers.zipdemo import DRIVER
from gerberslap.model import ExposureValues, PrinterConfig
from gerberslap.printers.base import BuildError, SettingsError, TemplateError

CFG = PrinterConfig(id="zipdemo", name="Zip demo printer", driver="zipdemo")
GOOD = {"lift_mm": 0.001, "lift_mm_per_min": 500}


def template(tmp_path, body, name="template.json"):
    path = tmp_path / name
    path.write_text(body if isinstance(body, str) else json.dumps(body))
    return path


def test_the_plane_and_the_grid_describe_the_same_screen():
    d = DRIVER.descriptor
    assert d.grid.width * d.grid.pitch == pytest.approx(d.plane.width_mm) and d.grid.height * d.grid.pitch == pytest.approx(d.plane.height_mm)


def test_the_image_of_the_file_is_the_plane_turned_the_way_the_printer_wants():
    mask = np.zeros((1200, 2000), bool)
    mask[0, 0] = True                                                  # the back-left corner of the plane (row 0 is the back, column 0 the left)
    image = DRIVER.to_printer_image(mask)
    assert image[1199, 0] and image.sum() == 1                         # this printer's file has the front as its first row: the corner is on the last
    with pytest.raises(BuildError) as e:
        DRIVER.to_printer_image(np.zeros((10, 10), bool))
    assert e.value.code == "mask_shape"


@pytest.mark.parametrize("body, reason", [("not json", "not_json"), ({"lift_mm": 1}, "fields_missing"), ({**GOOD, "lift_mm": 0}, "lift_distance_zero"),
                                          ({**GOOD, "lift_mm_per_min": 0}, "lift_speed_invalid")])
def test_a_template_that_cannot_be_used_is_refused_with_its_reason(tmp_path, body, reason):
    with pytest.raises(TemplateError) as e:
        DRIVER.validate_template(template(tmp_path, body))
    assert e.value.params["reason"] == reason
    assert DRIVER.validate_template(template(tmp_path, GOOD, "ok.json")) == GOOD


def test_the_checks_say_what_is_missing(tmp_path):
    assert [i.code for i in DRIVER.check(None, CFG, None)] == ["template_missing"]
    assert [i.code for i in DRIVER.check(None, CFG, template(tmp_path, {**GOOD, "lift_mm": 0}))] == ["template_invalid"]
    assert DRIVER.check(None, CFG, template(tmp_path, GOOD)) == []
    assert [i.code for i in DRIVER.check(None, CFG.model_copy(update={"settings": {"compress_level": 99}}), template(tmp_path, GOOD))] == ["printer_settings_invalid"]
    with pytest.raises(SettingsError):
        DRIVER.parse_settings({"compress_level": "high"})


def test_the_file_is_read_back_and_is_what_was_meant(tmp_path):
    mask = np.zeros((1200, 2000), bool)
    mask[100:300, 200:900] = True
    result = DRIVER.build(mask, ExposureValues(total_s=6, pulses=3, rest_s=1), CFG, template(tmp_path, GOOD), tmp_path / "out.zip")
    assert result.verified and result.summary.layers == 3 and result.summary.flash_s == 2.0 and result.summary.lit_pixels == 200 * 700
    with zipfile.ZipFile(result.path) as z:
        assert json.loads(z.read("manifest.json"))["lift_mm"] == 0.001                 # the movement is the template's
        assert len([n for n in z.namelist() if n.startswith("layer_")]) == 3
    assert not list(tmp_path.glob(".*.part"))                                          # nothing left behind


def test_what_a_driver_refuses_it_refuses_before_writing_anything(tmp_path):
    lit = np.ones((1200, 2000), bool)
    for mask, values, code in ((lit, ExposureValues(total_s=1, pulses=10, rest_s=0), "flash_below_minimum"), (np.zeros_like(lit), ExposureValues(total_s=6, pulses=3, rest_s=1), "mask_all_dark")):
        with pytest.raises(BuildError) as e:
            DRIVER.build(mask, values, CFG, template(tmp_path, GOOD), tmp_path / "x.zip")
        assert e.value.code == code and not (tmp_path / "x.zip").exists()
    with pytest.raises(BuildError) as e:
        DRIVER.build(lit, ExposureValues(total_s=6, pulses=3, rest_s=1), CFG, None, tmp_path / "x.zip")
    assert e.value.code == "template_missing"
```

Per provare l'integrazione a mano: si riavvia il server con una cartella dati di prova, si installa il template, si apre uno zip di Gerber, si sceglie la stampante dalla pillola in alto a sinistra e si genera il file; poi lo si apre con gli strumenti del formato (per il `.ctb` della LD-002H, `python3 gerberslap/printers/ld002h/ctbio.py info file.ctb` e `... layer file.ctb N out.png`).

## Documentare

- Il **formato del file** e il **comportamento verificato** della stampante, in un documento come [`ctb_v5_ld002h_formato.md`](https://github.com/shad0w82/GerberSLAp/blob/main/gerberslap/printers/ld002h/docs/ctb_v5_ld002h_formato.md): ogni fatto con il suo livello di certezza (provato sulla stampante, coincide in più file, dedotto, ignoto) e i punti aperti.
- Le **impostazioni dello slicer** per fare il template, in [Requisiti e template](../../installation/requirements.md#come-si-prepara) (una sezione per stampante), e l'elenco delle stampanti supportate nel `README.md`.
- Se cambia qualcosa dell'architettura, la [Panoramica](../../architecture/overview.md).

## Errori frequenti

- **Orientamento e specchio confusi.** La maschera ha già il retro in riga 0 e la sinistra in colonna 0; lo **specchio** di una scheda (il rame verso il basso) è una scelta dell'utente fatta *prima*, sulla scheda posizionata: il driver **non** specchia mai da sé.
- **`grid × pitch` diverso da `plane`.** Le schede risulterebbero della misura sbagliata.
- **Scrivere un movimento inventato.** Si copia sempre dal template; un valore pericoloso (come la distanza 0) va rifiutato in `validate_template`.
- **Lasciare un file a metà.** Si scrive in un temporaneo, si rilegge, si rinomina con `os.replace`; in caso di errore non resta niente.
- **Un solo tempo di esposizione.** Se la stampante lo legge da un solo posto, tutti i layer normali hanno lo stesso tempo: una dose è «N layer da T/N», non layer di tempi diversi.
- **Dichiarare limiti non provati.** `max_proven_flash_s` è «il massimo provato», non «il massimo teorico».
- **Dimenticare le frasi** di un codice nuovo, in una delle due lingue.
- **Stato nel driver.** È usato da più richieste insieme: niente variabili che cambiano tra una chiamata e l'altra.
- **Il template nel repository.** Estensione nel `.gitignore`, mai nell'immagine Docker.
- **Id e cartella diversi**, o un id che sorpassa `ld002h` in ordine alfabetico senza volerlo (diventa la stampante predefinita).
