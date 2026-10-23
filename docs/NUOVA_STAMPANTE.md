Italiano | [English](en/NEW_PRINTER.md)

# Aggiungere una stampante

Guida per chi sviluppa: come scrivere il driver di una stampante nuova e come creare e installare il suo *template*. Per l'architettura generale vedi [ARCHITETTURA.md](ARCHITETTURA.md); per installare ed eseguire l'app, [INSTALLAZIONE.md](INSTALLAZIONE.md).

Una stampante è **una cartella**: `gerberslap/printers/<id>/` con un driver e una foto. L'app la trova da sola all'avvio e la pagina la mostra (card in *Impostazioni*, scelta della stampante, stato «Pronta»). Non si tocca né il nucleo, né il modello dati, né la pagina.

- [Che cosa fa un driver](#che-cosa-fa-un-driver)
- [Prima di scrivere codice](#prima-di-scrivere-codice)
- [Struttura di un driver](#struttura-di-un-driver)
- [Il descrittore](#il-descrittore)
- [I metodi](#i-metodi)
- [Il template](#il-template)
- [Impostazioni del driver](#impostazioni-del-driver)
- [Avvisi, errori e frasi](#avvisi-errori-e-frasi)
- [La foto](#la-foto)
- [Un esempio completo](#un-esempio-completo)
- [Test da scrivere](#test-da-scrivere)
- [Documentare](#documentare)
- [Errori frequenti](#errori-frequenti)

## Che cosa fa un driver

| Lo decide l'app | Lo decide il driver |
|---|---|
| Dove sta ogni scheda sul piano; la **maschera** del piano: un array booleano `(altezza, larghezza)` della griglia della stampante, riga 0 = **retro**, colonna 0 = **sinistra**, vero dove la luce deve passare. | Quanto è grande lo schermo e come si chiama la stampante. |
| La **dose** richiesta: tempo totale di luce, numero di flash e riposo (`ExposureValues`). | **Come realizzarla** in layer: per esempio *N* layer identici da *T/N* secondi. |
| I controlli, gli avvisi, la pagina, la cartella dati, il download. | **Orientamento** dell'immagine nel file (rotazione, riflessione), formato del file, anteprima. |
| La lingua e le frasi. | Il **movimento** (copiato dal template), i **limiti** di un flash, la verifica del file scritto. |

Il nucleo, il modello dati, i riconoscitori CAD e i servizi **non nominano mai la stampante né il formato del suo file**: un test lo controlla. Tutto ciò che dipende da una stampante sta nella sua cartella.

## Prima di scrivere codice

Le risposte a queste domande vanno trovate prima, e **provate sulla stampante**: non si afferma un comportamento che non è stato verificato (nel repository, i fatti verificati della LD-002H sono in [ctb_v5_ld002h_formato.md](../gerberslap/printers/ld002h/docs/ctb_v5_ld002h_formato.md), ognuno con il suo livello di certezza).

| Domanda | Perché serve | Come scoprirla |
|---|---|---|
| **Dimensioni dello schermo** (mm) e **risoluzione** (pixel). Il pixel è quadrato? | Danno il piano e la griglia. La griglia ha **un solo passo** per i due assi: uno schermo con pixel non quadrati non è supportato. | Scheda tecnica; poi si misura un'immagine con un quadrato di lato noto. |
| **Il formato del file** e come si scrive | È il cuore del driver. | Documentazione pubblica, oppure si decodificano file prodotti dallo slicer del produttore e si verifica **ricostruendo un file dai suoi stessi pixel e parametri**: il risultato deve coincidere con l'originale (per la LD-002H differisce di 18 byte, tutti spiegati). Controlla la licenza e il copyright del formato. |
| **Orientamento**: come arriva l'immagine sullo schermo? | La maschera ha il retro in riga 0 e la sinistra in colonna 0, visti dall'alto con l'utente davanti: il driver la deve girare come il file vuole. | Un file con un'immagine **asimmetrica** (una «F», un quadrato in un angolo, un cerchio in un altro, una scala graduata da 50 mm), guardata sullo schermo dall'alto. Con la F si distinguono rotazione e riflessione, con la scala si controlla il passo. |
| **Dove legge il tempo di esposizione**: nell'intestazione o in ogni layer? E il riposo? | Decide come si realizza una dose e dove si scrive il riposo. | Un file con layer di tempi diversi e uno con intestazione e layer in disaccordo, cronometrando i flash. |
| **Limiti di un flash**: minimo e massimo provati | Diventano `limits` nel descrittore: sotto il minimo il file non si genera, sopra il massimo si genera con un avviso. | Si provano i valori estremi; quelli non provati non si dichiarano. |
| **Movimento**: distanza e velocità di sollevamento, quota Z, secondi stadi | Si **copia dal template**, non si inventa. Bisogna sapere quali valori sono pericolosi. | Si cambia un valore alla volta e si osserva. Per la LD-002H una distanza 0 fa fare alla stampante un ciclo di ripiego da 5 mm: il driver non la scrive mai e rifiuta i template che la usano. |
| **Anteprima** che la stampante mostra | È un campo del file. | Si prova una forma e una dimensione e si guarda lo schermo della stampante. |

Per la LD-002H, queste prove sono nella riga di comando [`pcb_ctb.py`](../gerberslap/printers/ld002h/docs/pcb_ctb.py) (`test` per l'orientamento, `expprobe`, `bottomprobe`, `headerlift`, `speedprobe`): sono strumenti di ricerca dello stesso tipo di quelli da scrivere per una stampante nuova. Il metodo è sempre lo stesso: si prepara un file di prova, lo si fa eseguire alla stampante e si annota cosa è successo, **poi** si scrive il codice. Quando si scopre qualcosa di nuovo, si aggiorna il documento del formato.

## Struttura di un driver

```
gerberslap/printers/<id>/
  __init__.py     from .driver import DRIVER
  driver.py       la classe del driver e DRIVER = <la classe>()
  icon.png        la foto verticale della stampante
```

Se serve, nella stessa cartella ci stanno anche i moduli del driver, per esempio la lettura e scrittura del file della stampante (`ctbio.py` nella LD-002H), e una sottocartella `docs/` con il documento del formato e gli strumenti di prova (come `ctb_v5_ld002h_formato.md` e `pcb_ctb.py`): le cartelle `docs/` non entrano nell'immagine Docker.

Regole della scoperta (`printers/__init__.py`):

- L'**id** è il nome della cartella e deve coincidere con `descriptor.id`; è anche il nome di un pacchetto Python, quindi lettere minuscole, cifre e trattino basso, che comincia con una lettera. È anche la cartella dei suoi dati: `<cartella dati>/printers/<id>/`.
- `DRIVER` deve essere un'istanza di `PrinterDriver`. Una cartella che non si carica (errore, id sbagliato, niente `DRIVER`) si segnala e **non ferma le altre**; le cartelle che cominciano con `_` si ignorano.
- La stampante predefinita, quella di un progetto che non ne nomina una, è la **prima per id in ordine alfabetico**: aggiungerne una con un id che precede quello delle altre cambia la predefinita.
- Il driver è un oggetto unico, usato da più richieste insieme: **non deve tenere stato** tra una chiamata e l'altra.

Dopo aver aggiunto la cartella **si riavvia il server** (i driver si cercano all'avvio). In *Impostazioni* compare la card, con «Non pronta» finché il template non è installato.

## Il descrittore

`DriverDescriptor` (in `printers/base.py`) dice tutto ciò che serve sapere senza usare la stampante:

| Campo | Significato |
|---|---|
| `id`, `name` | L'id (come la cartella) e il nome mostrato. |
| `plane` | `Plane(width_mm, height_mm)`: lo schermo **visto dall'alto con l'utente davanti**. `width_mm` va da sinistra a destra, `height_mm` dal fronte al retro. Uno schermo verticale nel suo telaio si descrive comunque così, girato come sta sul piano di lavoro. |
| `grid` | `Grid(width, height, pitch)`: i pixel della maschera, nella stessa orientazione del piano. **`width × pitch` deve valere `width_mm` e `height × pitch` `height_mm`** (il test del driver della LD-002H lo controlla: scrivi lo stesso per il tuo). |
| `limits` | `ExposureLimits(min_flash_s, max_proven_flash_s)`; `None` dove non si conosce un limite. |
| `requires_template` | Se la stampante ha bisogno di un template. |
| `template_name` | Il nome del file del template nella cartella dati: obbligatorio se serve un template, vietato altrimenti. Lettere, cifre, `_`, `.` e `-`, fino a 64 caratteri; non `printer.json`. |
| `file_extension` | L'estensione del file che scrive, con il punto, in minuscolo (`.ctb`, `.zip`…): con questa l'app dà il nome al download. Predefinita `.bin`. |

## I metodi

Il driver estende `PrinterDriver`. Gli errori sono eccezioni con un `code` stabile e dei parametri (numeri e stringhe): **mai un testo da mostrare**, le frasi le scrive la pagina.

| Metodo | Compito |
|---|---|
| `parse_settings(impostazioni)` | Valida le impostazioni del driver (un dizionario che sta in `printer.json`, vedi sotto) e le restituisce in forma tipizzata. `SettingsError` se non vanno. |
| `validate_template(percorso)` | Giudica un template fornito da una persona. `TemplateError` con un `reason` stabile se non va; se va, restituisce ciò che ha imparato. **Si chiama prima di installarlo**: un template rifiutato non lascia traccia. |
| `check(esposizione, config, template)` | Gli avvisi di questa stampante, come lista di `Issue` (vedi sotto): template mancante o non valido, impostazioni errate, regole proprie sui valori. `esposizione` è `None` quando si chiede solo «è pronta?», e i valori veri quando si sta generando. Chi la usa sa se è «pronta» guardando se qualche avviso blocca. |
| `to_printer_image(maschera)` | La maschera del piano come immagine del file: qui sta la rotazione o la riflessione che hai scoperto. Rifiuta una maschera della forma sbagliata (`mask_shape`). Non modifica l'argomento. |
| `build(maschera, esposizione, config, template, percorso)` | Scrive il file in `percorso`, **lo rilegge e lo confronta** con ciò che voleva scrivere, e solo allora lo mette dove gli è stato chiesto: se non coincide solleva `BuildError` e **non lascia nulla**. Si scrive prima in un file temporaneo accanto (`.<nome>.part`) e si rinomina con `os.replace`. Restituisce `BuildResult(percorso, BuildSummary, verified=True)`. |
| `build_sequence(maschere, flash, flash_s, riposo_s, config, template, percorso)` | **Facoltativo.** Scrive un file di più maschere in fila (la scala di calibrazione: ogni gradino accende più piano del precedente): ogni maschera per `flash` layer da `flash_s` secondi, con `riposo_s` di buio dopo ognuno, tutte con lo stesso tempo. Se non lo implementi, la scala risponde `sequence_unsupported` (con la frase pronta); tutto il resto funziona. |

**Realizzare la dose.** L'app dice «T secondi di luce in N flash con R secondi di riposo»; come farlo dipende dalla stampante. Per la LD-002H, che legge **un solo tempo dall'intestazione**, sono *N* layer identici da *T/N* secondi, e il riposo è la pausa di buio tra un layer e l'altro. Una stampante che legge il tempo da ogni layer si comporta in un altro modo: è esattamente ciò che la prova della sezione precedente deve chiarire.

**Il riepilogo.** `BuildSummary` dice cosa farà il file, in numeri: layer, layer iniziali di attesa, flash, riposo, luce totale, durata stimata dalla stampante (in secondi), pixel e area accesi, dimensione del file e un dizionario `details` libero per le particolarità del driver. La pagina lo mostra dopo «Genera».

**Codici degli errori di scrittura.** Quelli che la pagina sa già dire: `mask_shape`, `mask_all_dark` (la maschera non accende nulla), `flash_below_minimum`, `template_missing`, `write_failed`, `verification_failed`, `sequence_unsupported`. `write_failed` e `verification_failed` sono guasti del server (500, senza parametri nella risposta, perché potrebbero nominare un percorso); gli altri sono rifiuti (422) con i loro parametri. Ne puoi aggiungere altri: servono le frasi (vedi sotto).

## Il template

### A che cosa serve

Per molte stampanti il file da dare in pasto è un formato che solo lo slicer del produttore scrive bene, con campi che nessuno documenta e un movimento che non va inventato. Il driver allora **non scrive il file da zero**: parte da un file fatto dallo slicer, il *template*, e ne cambia soltanto ciò che è suo (le immagini, l'esposizione, la quota Z); il resto lo copia tale e quale. Il template è anche il modo in cui chi usa l'app sceglie come si muove la stampante durante l'esposizione.

Se invece il formato è aperto e il driver sa scriverlo tutto, **non serve nessun template**: `requires_template=False`, `template_name` omesso, e `validate_template` può non fare nulla.

### Come si crea il template di una stampante nuova

Il template è un file che si produce con lo slicer del produttore. La ricetta, in generale:

1. **Scegli il profilo giusto della stampante** nello slicer: così risoluzione, volume e nome del modello di stampante nel file sono quelli veri. Un profilo sbagliato dà un file che il driver rifiuterà (o, peggio, accetterà).
2. **Affetta un oggetto semplice** (un cubo basta): il contenuto delle immagini non conta, le sostituisce l'app.
3. **Imposta il movimento come lo vuoi in esposizione**: la distanza di sollevamento **più piccola che la stampante accetta** (e **mai zero** se, come nella LD-002H, zero fa fare un ciclo di ripiego), velocità ragionevoli, e i tempi di riposo **a zero** (il riposo lo decide l'app) con la modalità che attende «solo il riposo», se lo slicer la offre. Un solo layer iniziale (bottom), se il formato li distingue.
4. **Salva il file** nel formato della stampante. Quello è il template.

Per la LD-002H, in ChiTuBox: *Waiting Mode* «Resting time» con i tre riposi a 0; distanza di sollevamento del bottom e normale 0,001 mm (e 0 il secondo valore, quello dopo il «+»); le quattro velocità a 500 mm/min (e 0 i secondi valori); un layer bottom. (Vedi [INSTALLAZIONE.md](INSTALLAZIONE.md#il-template-della-stampante).)

Annota nel documento del formato **quali impostazioni dello slicer** servono, così chi installa l'app per quella stampante sa come fare.

### Che cosa deve fare il driver con il template

- **`validate_template`** rifiuta, con un `reason` stabile, tutto ciò che renderebbe il file sbagliato o pericoloso: un file che non è del formato, di un'altra versione, danneggiato (se il formato ha un controllo di integrità), con la risoluzione di un altro schermo, senza layer, con dati che non si leggono, **con un movimento pericoloso** (la distanza 0 della LD-002H, una velocità non valida). Un template che funziona ma non è l'ideale (per la LD-002H, una distanza di sollevamento grande rende lenti i flash) si accetta e si segnala con un avviso da `check`.
- **`check`** dà `template_missing` se il file non c'è e `template_invalid` (con `reason`) se `validate_template` lo rifiuta.
- **`build`** copia dal template la parte che non è sua e ne sostituisce solo ciò che è suo, ricalcola ciò che dipende dal contenuto (offset, dimensioni, CRC) e poi **rilegge** il file scritto.
- Non si inventa nulla: se un campo non è capito, si copia dal template com'è.

### Dove sta e come si installa

Il template sta nella cartella dati: `<cartella dati>/printers/<id>/<template_name>`. Si installa con il comando dell'app, che lo giudica con il driver **prima** di scrivere qualsiasi cosa:

```bash
.venv/bin/python -m gerberslap.web --install-template <id> /percorso/del/template
```

Esce con 0 (installato), 1 (file o cartella rifiutati: dice perché) o 2 (non esiste una stampante con quell'id); rilanciarlo lo sostituisce. In Docker si usa lo stesso comando con la cartella dati nel volume (vedi [INSTALLAZIONE.md](INSTALLAZIONE.md#installazione-con-docker-previsto)). Poi basta ricaricare la pagina: il template si rilegge a ogni richiesta e la card della stampante diventa «Pronta».

### Copyright

I file di uno slicer contengono spesso l'avviso di copyright del produttore, che finisce anche nei file che l'app genera. Per questo **il template non va mai nel repository né in un'immagine Docker**: ognuno prepara il suo. Per un formato nuovo, **aggiungi la sua estensione al `.gitignore`** (oggi c'è `*.ctb`) e, se serve, nei campioni di prova.

## Impostazioni del driver

Le regolazioni che una persona può voler cambiare (per esempio la quota Z a cui stanno i layer) sono le *impostazioni* del driver:

- Si dichiarano con un modello `pydantic` (`gerberslap.model.base.Model`) con valori predefiniti e limiti, e `parse_settings` lo valida.
- Chi installa le scrive in `<cartella dati>/printers/<id>/printer.json`, un file **facoltativo**:

  ```json
  { "format": "gerberslap-printer", "schema_version": 1, "printer": { "settings": { "compress_level": 9 } } }
  ```
- Impostazioni illeggibili o non valide non fanno cadere l'app: `check` le segnala con `printer_settings_invalid` (con il campo e il motivo) e la generazione si blocca.

## Avvisi, errori e frasi

Il server manda **codici con parametri**; la pagina li trasforma in frasi in italiano e in inglese.

- I codici degli avvisi stanno in `gerberslap/model/issues.py` (classe `C`). Un driver può riusare quelli che già ci sono: `TEMPLATE_MISSING`, `TEMPLATE_INVALID` (con `reason`), `TEMPLATE_LIFT_LARGE`, `PRINTER_SETTINGS_INVALID`. Un avviso è un `Issue(code, severity, blocking, params)`: `blocking=True` **ferma la generazione**, gli altri informano.
- Per un **codice nuovo** (un avviso, un `reason` di template, un errore di `build`) servono le sue frasi in `gerberslap/web/static/js/i18n.js`, **in tutte e due le lingue**: `i_<codice>` per gli avvisi, `i_template_invalid_<reason>` per i motivi di un template rifiutato, `err_<codice>` per gli errori di scrittura. Senza la frase, la pagina mostra il codice grezzo. I parametri dei codici si usano nelle frasi come `{nome}`.
- I parametri sono numeri e stringhe: niente percorsi del server e niente testi già scritti.

## La foto

Ogni driver porta con sé `icon.png`: la foto **verticale** della stampante (un PNG più alto che largo, con sfondo trasparente, fino a 512 KB; quella della LD-002H è 107 × 180 pixel). Il driver la trova da sé accanto al suo modulo, l'app la serve su `/api/printers/<id>/picture` e la pagina la mostra sulla card e nel menu della stampante; senza foto disegna una stampante generica. **Un test fallisce se un driver del repository non ha la sua `icon.png`.**

## Un esempio completo

Un driver minimo ma completo, con un template: una stampante immaginaria che prende uno **zip di layer PNG** con un `manifest.json`, e il cui template è un piccolo `template.json` con le impostazioni di sollevamento. Mostra tutto: descrittore, impostazioni, validazione del template, avvisi, orientamento (qui il file ha il *fronte* come prima riga), scrittura con rilettura e confronto. Provato: scoperto dal registro, «Non pronta» senza template, template rifiutato e poi installato, file generato dall'app, flash troppo corto bloccato, scala di calibrazione che risponde `sequence_unsupported` (non implementa `build_sequence`).

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
- **L'orientamento**: una maschera con un solo pixel in un angolo noto arriva nell'angolo che hai misurato sulla stampante; la forma sbagliata si rifiuta con `mask_shape`. Se possibile, un secondo controllo calcolato in un altro modo (un oracolo indipendente).
- **Il template**: un caso per ogni `reason` di `validate_template`, e uno buono. Il template di prova **si costruisce nel test** (non si committa un file del produttore); i test che richiedono un template vero si saltano se manca, come fa `needs_template` in `tests/test_printers.py`.
- **I controlli**: `template_missing`, `template_invalid`, `printer_settings_invalid`, e «nessun avviso» quando tutto va.
- **La scrittura**: il file si rilegge e coincide con ciò che si voleva; **i rifiuti avvengono prima di scrivere** (nessun file lasciato, nessun `.part`); la dose si realizza come deve (numero e tempo dei layer, riposo).
- **La rilettura**: un test che altera il file scritto (o simula un errore) e verifica che `build` non consegni nulla.
- **Da zero fino all'app**: il driver in un `Registry`, un `DataStore` temporaneo, il template installato con `install_template`, uno zip caricato e `POST /api/generate` (vedi `tests/test_generate.py` e `tests/support/fakeprinters.py`, che ha una stampante finta che scrive pochi byte).
- **La scala**, se implementi `build_sequence`: più maschere, nell'ordine, con i flash giusti.
- **I confini**: aggiungi il nome della stampante e l'estensione del formato all'espressione di `test_the_generic_packages_never_name_a_printer_or_its_file_format` in `tests/test_printers.py` (oggi `ctb|ld-?002h|creality`), così nessuno li scrive per sbaglio nel nucleo, nel modello dati o nei servizi.
- **La foto**: la controlla già il test che scorre tutti i driver.

Esempio, per il driver sopra (`tests/test_zipdemo.py`):

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

Per provare l'integrazione a mano: riavvia il server con una cartella dati di prova, installa il template, apri uno zip di Gerber, scegli la stampante dalla pillola in alto a sinistra e genera il file; poi aprilo con gli strumenti del formato (per il `.ctb` della LD-002H, `python3 gerberslap/printers/ld002h/ctbio.py info file.ctb` e `... layer file.ctb N out.png`).

## Documentare

- Il **formato del file** e il **comportamento verificato** della stampante in un documento come `ctb_v5_ld002h_formato.md`: ogni fatto con il suo livello di certezza (provato sulla stampante, coincide in più file, dedotto, ignoto) e i punti aperti.
- Le **impostazioni dello slicer** per fare il template, in [INSTALLAZIONE.md](INSTALLAZIONE.md#il-template-della-stampante) (una sezione per stampante) e l'elenco delle stampanti supportate in `README.md`.
- Se cambia qualcosa dell'architettura, [ARCHITETTURA.md](ARCHITETTURA.md).

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
