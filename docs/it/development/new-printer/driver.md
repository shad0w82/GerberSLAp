---
icon: material/chip
---

# Il driver di una stampante

Una stampante è **una cartella**: `gerberslap/printers/<id>/`, con un driver e una foto. L'app la trova da sola all'avvio e la pagina la mostra (card nelle Impostazioni, scelta della stampante, stato «Pronta»). Non si tocca né il nucleo, né il modello dati, né la pagina.

Questa pagina spiega che cosa fa un driver, che cosa serve scoprire prima di scriverlo, come si scrive e come si crea il suo *template*. Un driver completo, con i test, è nella pagina [Esempio, test e documentazione](example.md); l'architettura generale è in [Panoramica](../../architecture/overview.md).

## Che cosa fa un driver

| Lo decide l'app | Lo decide il driver |
|---|---|
| Dove sta ogni scheda sul piano e la **maschera** del piano: un array booleano `(altezza, larghezza)` della griglia della stampante, con la riga 0 = **retro**, la colonna 0 = **sinistra** e vero dove la luce deve passare. | Quanto è grande lo schermo e come si chiama la stampante. |
| La **dose** richiesta: tempo totale di luce, numero di flash e riposo (`ExposureValues`). | **Come realizzarla** in layer: per esempio *N* layer identici da *T/N* secondi. |
| I controlli, gli avvisi, la pagina, la cartella dati, il download. | **Orientamento** dell'immagine nel file (rotazione, riflessione), formato del file, anteprima. |
| La lingua e le frasi. | Il **movimento** (copiato dal template), i **limiti** di un flash, la verifica del file scritto. |

Il nucleo, il modello dati, i riconoscitori CAD e i servizi **non nominano mai la stampante né il formato del suo file**: un test lo controlla. Tutto ciò che dipende da una stampante sta nella sua cartella.

## Prima di scrivere codice

Le risposte a queste domande vanno trovate prima, e **provate sulla stampante**: non si afferma un comportamento che non è stato verificato. I fatti verificati della LD-002H sono nel [documento del formato](https://github.com/shad0w82/GerberSLAp/blob/main/gerberslap/printers/ld002h/docs/ctb_v5_ld002h_formato.md), ognuno con il suo livello di certezza.

| Domanda | Perché serve | Come scoprirla |
|---|---|---|
| **Dimensioni dello schermo** (mm) e **risoluzione** (pixel). Il pixel è quadrato? | Danno il piano e la griglia. La griglia ha **un solo passo** per i due assi: uno schermo con pixel non quadrati non è supportato. | Scheda tecnica; poi si misura un'immagine con un quadrato di lato noto. |
| **Il formato del file** e come si scrive. | È il cuore del driver. | Documentazione pubblica, oppure si decodificano file prodotti dallo slicer del produttore e si verifica **ricostruendo un file dai suoi stessi pixel e parametri**: il risultato deve coincidere con l'originale (per la LD-002H differisce di 18 byte, tutti spiegati). Si controllano licenza e copyright del formato. |
| **Orientamento**: come arriva l'immagine sullo schermo? | La maschera ha il retro in riga 0 e la sinistra in colonna 0, vista dall'alto con l'utente davanti: il driver la deve girare come il file vuole. | Un file con un'immagine **asimmetrica** (una «F», un quadrato in un angolo, un cerchio in un altro, una scala graduata da 50 mm), guardata sullo schermo dall'alto. Con la F si distinguono rotazione e riflessione, con la scala si controlla il passo. |
| **Dove legge il tempo di esposizione**: nell'intestazione o in ogni layer? E il riposo? | Decide come si realizza una dose e dove si scrive il riposo. | Un file con layer di tempi diversi e uno con intestazione e layer in disaccordo, cronometrando i flash. |
| **Limiti di un flash**: minimo e massimo provati. | Diventano `limits` nel descrittore: sotto il minimo il file non si genera, sopra il massimo si genera con un avviso. | Si provano i valori estremi; quelli non provati non si dichiarano. |
| **Movimento**: distanza e velocità di sollevamento, quota Z, secondi stadi. | Si **copia dal template**, non si inventa. Bisogna sapere quali valori sono pericolosi. | Si cambia un valore alla volta e si osserva. Per la LD-002H una distanza 0 fa fare alla stampante un ciclo di ripiego da 5 mm: il driver non la scrive mai e rifiuta i template che la usano. |
| **Anteprima** che la stampante mostra. | È un campo del file. | Si prova una forma e una dimensione e si guarda lo schermo della stampante. |

Per la LD-002H queste prove stanno nella riga di comando [`pcb_ctb.py`](https://github.com/shad0w82/GerberSLAp/blob/main/gerberslap/printers/ld002h/docs/pcb_ctb.py) (`test` per l'orientamento, `expprobe`, `bottomprobe`, `headerlift`, `speedprobe`): sono strumenti di ricerca dello stesso tipo di quelli da scrivere per una stampante nuova. Il metodo è sempre lo stesso: si prepara un file di prova, lo si fa eseguire alla stampante e si annota cosa è successo, **poi** si scrive il codice. Quando si scopre qualcosa di nuovo, si aggiorna il documento del formato.

## Struttura di un driver

```text
gerberslap/printers/<id>/
  __init__.py     from .driver import DRIVER
  driver.py       la classe del driver e DRIVER = <la classe>()
  icon.png        la foto verticale della stampante
```

Se serve, nella stessa cartella ci stanno anche i moduli del driver, per esempio la lettura e scrittura del file della stampante (`ctbio.py` nella LD-002H), e una sottocartella `docs/` con il documento del formato e gli strumenti di prova. Le cartelle `docs/` non entrano nell'immagine Docker.

Le regole con cui l'app scopre i driver (`printers/__init__.py`):

- L'**id** è il nome della cartella e deve coincidere con `descriptor.id`. È anche il nome di un pacchetto Python, quindi lettere minuscole, cifre e trattino basso, e comincia con una lettera. È anche la cartella dei suoi dati: `<cartella dati>/printers/<id>/`.
- `DRIVER` deve essere un'istanza di `PrinterDriver`. Una cartella che non si carica (errore, id sbagliato, niente `DRIVER`) si segnala e **non ferma le altre**; le cartelle che cominciano con `_` si ignorano.
- La stampante predefinita, quella di un progetto che non ne nomina una, è la **prima per id in ordine alfabetico**: aggiungerne una con un id che precede quello delle altre cambia la predefinita.
- Il driver è un oggetto unico, usato da più richieste insieme: **non deve tenere stato** tra una chiamata e l'altra.

Dopo aver aggiunto la cartella **si riavvia il server**, perché i driver si cercano all'avvio. Nelle Impostazioni compare la card, con «Non pronta» finché il template non è installato.

## Il descrittore

`DriverDescriptor` (in `printers/base.py`) dice tutto ciò che serve sapere senza usare la stampante:

| Campo | Significato |
|---|---|
| `id`, `name` | L'id (come la cartella) e il nome mostrato. |
| `plane` | `Plane(width_mm, height_mm)`: lo schermo **visto dall'alto con l'utente davanti**. `width_mm` va da sinistra a destra, `height_mm` dal fronte al retro. Uno schermo verticale nel suo telaio si descrive comunque così, girato come sta sul piano di lavoro. |
| `grid` | `Grid(width, height, pitch)`: i pixel della maschera, nella stessa orientazione del piano. **`width × pitch` deve valere `width_mm` e `height × pitch` `height_mm`**: il test del driver della LD-002H lo controlla, e il test del tuo driver deve fare lo stesso. |
| `limits` | `ExposureLimits(min_flash_s, max_proven_flash_s)`; `None` dove non si conosce un limite. |
| `requires_template` | Se la stampante ha bisogno di un template. |
| `template_name` | Il nome del file del template nella cartella dati: obbligatorio se serve un template, vietato altrimenti. Lettere, cifre, `_`, `.` e `-`, fino a 64 caratteri; non `printer.json`. |
| `file_extension` | L'estensione del file che scrive, con il punto e in minuscolo (`.ctb`, `.zip`…): con questa l'app dà il nome al download. Predefinita `.bin`. |

## I metodi

Il driver estende `PrinterDriver`. Gli errori sono eccezioni con un `code` stabile e dei parametri (numeri e stringhe): **mai un testo da mostrare**, perché le frasi le scrive la pagina.

| Metodo | Compito |
|---|---|
| `parse_settings` | `(impostazioni)`<br>Valida le impostazioni del driver (un dizionario che sta in `printer.json`, vedi sotto) e le restituisce in forma tipizzata. `SettingsError` se non vanno. |
| `validate_template` | `(percorso)`<br>Giudica un template fornito da una persona. `TemplateError` con un `reason` stabile se non va; se va, restituisce ciò che ha imparato. **Si chiama prima di installarlo**: un template rifiutato non lascia traccia. |
| `check` | `(esposizione, config, template)`<br>Gli avvisi di questa stampante, come lista di `Issue` (vedi sotto): template mancante o non valido, impostazioni errate, regole proprie sui valori. `esposizione` è `None` quando si chiede solo «è pronta?» e porta i valori veri quando si sta generando. Chi la usa sa se la stampante è «pronta» guardando se qualche avviso blocca. |
| `to_printer_image` | `(maschera)`<br>La maschera del piano come immagine del file: qui sta la rotazione o la riflessione scoperta con le prove. Rifiuta una maschera della forma sbagliata (`mask_shape`). Non modifica l'argomento. |
| `build` | `(maschera, esposizione, config, template, percorso)`<br>Scrive il file in `percorso`, **lo rilegge e lo confronta** con ciò che voleva scrivere, e solo allora lo mette dove gli è stato chiesto. Se non coincide solleva `BuildError` e **non lascia nulla**: si scrive prima in un file temporaneo accanto (`.<nome>.part`) e si rinomina con `os.replace`. Restituisce `BuildResult(percorso, BuildSummary, verified=True)`. |
| `build_sequence` | `(maschere, flash, flash_s, riposo_s, config, template, percorso)`<br>**Facoltativo.** Scrive un file di più maschere in fila (la scala di calibrazione: ogni gradino accende più piano del precedente): ogni maschera per `flash` layer da `flash_s` secondi, con `riposo_s` di buio dopo ognuno, tutte con lo stesso tempo. Se non lo si implementa, la scala risponde `sequence_unsupported` (con la frase pronta) e tutto il resto funziona. |

### Realizzare la dose

L'app dice «T secondi di luce in N flash con R secondi di riposo»; come farlo dipende dalla stampante. Per la LD-002H, che legge **un solo tempo dall'intestazione**, sono *N* layer identici da *T/N* secondi, e il riposo è la pausa di buio tra un layer e l'altro. Una stampante che legge il tempo da ogni layer si comporta in un altro modo: è esattamente ciò che la prova della sezione precedente deve chiarire.

### Il riepilogo

`BuildSummary` dice in numeri che cosa farà il file: layer, layer iniziali di attesa, flash, riposo, luce totale, durata stimata dalla stampante (in secondi), pixel e area accesi, dimensione del file e un dizionario `details` libero per le particolarità del driver. La pagina lo mostra dopo «Genera».

### Codici degli errori di scrittura

Quelli che la pagina sa già dire sono `mask_shape`, `mask_all_dark` (la maschera non accende nulla), `flash_below_minimum`, `template_missing`, `write_failed`, `verification_failed` e `sequence_unsupported`. `write_failed` e `verification_failed` sono guasti del server (500, senza parametri nella risposta, perché potrebbero nominare un percorso); gli altri sono rifiuti (422) con i loro parametri. Se ne possono aggiungere altri, ma servono le loro frasi (vedi [Avvisi, errori e frasi](#avvisi-errori-e-frasi)).

## Il template

### A che cosa serve

Per molte stampanti il file da dare in pasto è un formato che solo lo slicer del produttore scrive bene, con campi che nessuno documenta e un movimento che non va inventato. Il driver allora **non scrive il file da zero**: parte da un file fatto dallo slicer, il *template*, e ne cambia soltanto ciò che è suo (le immagini, l'esposizione, la quota Z); il resto lo copia tale e quale. Il template è anche il modo in cui chi usa l'app sceglie come si muove la stampante durante l'esposizione.

Se invece il formato è aperto e il driver sa scriverlo tutto, **non serve nessun template**: `requires_template=False`, `template_name` omesso, e `validate_template` può non fare nulla.

### Come si crea il template di una stampante nuova

Il template è un file che si produce con lo slicer del produttore. La ricetta, in generale:

1. **Si sceglie il profilo giusto della stampante** nello slicer, così risoluzione, volume e nome del modello di stampante nel file sono quelli veri. Un profilo sbagliato dà un file che il driver rifiuterà o, peggio, accetterà.
2. **Si affetta un oggetto semplice**: un cubo basta, perché il contenuto delle immagini non conta e le sostituisce l'app.
3. **Si imposta il movimento come lo si vuole in esposizione**: la distanza di sollevamento **più piccola che la stampante accetta** (e **mai zero** se, come nella LD-002H, zero fa fare un ciclo di ripiego), velocità ragionevoli, e i tempi di riposo **a zero** (il riposo lo decide l'app), con la modalità che attende «solo il riposo» se lo slicer la offre. Un solo layer iniziale (bottom), se il formato li distingue.
4. **Si salva il file** nel formato della stampante. Quello è il template.

Per la LD-002H le impostazioni di ChiTuBox sono in [Requisiti e template](../../installation/requirements.md#come-si-prepara). Quelle di una stampante nuova vanno annotate nel documento del formato, così chi installa l'app per quella stampante sa come fare.

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

Esce con 0 (installato), 1 (file o cartella rifiutati: dice perché) o 2 (non esiste una stampante con quell'id); rilanciarlo lo sostituisce. Con Docker si usa lo stesso comando, con la cartella dati nel volume ([Installazione con Docker](../../installation/install.md#installazione-con-docker)). Poi basta ricaricare la pagina: il template si rilegge a ogni richiesta e la card della stampante diventa «Pronta».

### Copyright

!!! warning "Il template non va mai nel repository"
    I file di uno slicer contengono spesso l'avviso di copyright del produttore, che finisce anche nei file che l'app genera. Per questo il template non va mai nel repository né in un'immagine Docker: ognuno prepara il suo. Per un formato nuovo si **aggiunge la sua estensione al `.gitignore`** (oggi c'è `*.ctb`) e, se serve, ai campioni di prova.

## Impostazioni del driver

Le regolazioni che una persona può voler cambiare (per esempio la quota Z a cui stanno i layer) sono le *impostazioni* del driver:

- si dichiarano con un modello `pydantic` (`gerberslap.model.base.Model`) con valori predefiniti e limiti, e `parse_settings` lo valida;
- chi installa le scrive in `<cartella dati>/printers/<id>/printer.json`, un file **facoltativo**:

  ```json
  { "format": "gerberslap-printer", "schema_version": 1, "printer": { "settings": { "compress_level": 9 } } }
  ```

- impostazioni illeggibili o non valide non fanno cadere l'app: `check` le segnala con `printer_settings_invalid` (con il campo e il motivo) e la generazione si blocca.

## Avvisi, errori e frasi

Il server manda **codici con parametri**; la pagina li trasforma in frasi in italiano e in inglese.

- I codici degli avvisi stanno in `gerberslap/model/issues.py` (classe `C`). Un driver può riusare quelli che già ci sono: `TEMPLATE_MISSING`, `TEMPLATE_INVALID` (con `reason`), `TEMPLATE_LIFT_LARGE`, `PRINTER_SETTINGS_INVALID`. Un avviso è un `Issue(code, severity, blocking, params)`: `blocking=True` **ferma la generazione**, gli altri informano.
- Per un **codice nuovo** (un avviso, un `reason` di template, un errore di `build`) servono le sue frasi in `gerberslap/web/static/js/i18n.js`, **in tutte e due le lingue**: `i_<codice>` per gli avvisi, `i_template_invalid_<reason>` per i motivi di un template rifiutato, `err_<codice>` per gli errori di scrittura. Senza la frase, la pagina mostra il codice grezzo. I parametri dei codici si usano nelle frasi come `{nome}`.
- I parametri sono numeri e stringhe: niente percorsi del server e niente testi già scritti.

## La foto

Ogni driver porta con sé `icon.png`: la foto **verticale** della stampante, un PNG più alto che largo, con sfondo trasparente e fino a 512 KB (quella della LD-002H è 107 × 180 pixel). Il driver la trova da sé accanto al suo modulo, l'app la serve su `/api/printers/<id>/picture` e la pagina la mostra sulla card e nel menu della stampante; senza foto disegna una stampante generica. **Un test fallisce se un driver del repository non ha la sua `icon.png`.**
