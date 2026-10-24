---
icon: material/web
---

# Server e pagina

Il server FastAPI, la pagina in JavaScript puro, il file di progetto `.gslp` e la cartella dati: ciò che sta ai due lati della richiesta HTTP. I principi e gli strati sono nella [Panoramica](overview.md).

## Il server

`gerberslap/web/app.py` è una app FastAPI sottile, locale e per un solo utente, che serve anche la pagina statica. `python -m gerberslap.web` la avvia con `uvicorn`, in un solo processo.

### Rotte

| Rotta | Che cosa fa |
|---|---|
| `GET /api/info` | Versione, stampante predefinita, stampanti (piano, griglia, limiti, **se sono pronte e perché no**, foto), se la libreria c'è, con quali opzioni è partita l'app. Si rilegge a ogni richiesta: installare il template non richiede un riavvio. |
| `GET /api/printers/<id>/picture` | La foto della stampante, tenuta dal browser per un'ora. |
| `POST /api/boards` | Apre uno zip: riconosce, legge, ritorna la scheda (layer per hash) con avvisi e programma CAD. I file restano nella cache del server. |
| `POST /api/geometry` | I poligoni di un layer, per disegnarli. |
| `POST /api/render` | La maschera esatta (PNG a 1 bit in base64) per un progetto e una polarità, con gli avvisi del raster. |
| `POST /api/check` | I controlli di un progetto. Se la richiesta porta `exposure` (anche `null`) sono tutti: layout, riferimenti e valori; senza, solo il layout. |
| `POST /api/generate` | Il file di stampa di un progetto. |
| `POST /api/generate/ladder` | Il file della scala di calibrazione. |
| `POST /api/project/save`, `POST /api/project/open` | Scrive e legge il file `.gslp`. |
| `/api/recipes…` | La libreria: elenco, crea, modifica, elimina, duplica una ricetta; aggiungi, modifica, elimina e copia un dosaggio. Solo con la libreria accesa. |
| `GET /dev/samples/<nome>` | Solo con `--dev-samples`. |

Le richieste sono validate con `pydantic`: campi sconosciuti rifiutati, niente NaN o infiniti. Gli errori hanno sempre la forma `{"error": {"code": "...", "params": {...}}}`: un codice stabile, mai un percorso del server né un testo da mostrare.

### La generazione

`services/generate.py` fa tutti i controlli: layout, riferimenti, valori e quelli del driver sulla stampante. Se qualcosa **blocca**, risponde 422 `generation_blocked` con *tutti* gli avvisi. Altrimenti disegna la maschera con la pipeline, chiede al driver di scrivere in una cartella temporanea che poi sparisce, e risponde con i byte del file (`application/octet-stream`), il `Content-Disposition` (il nome del progetto reso sicuro, con l'estensione del driver) e il riepilogo in `X-Build-Summary` (JSON: layer, flash, riposo, luce totale, durata stimata dalla stampante, pixel e area accesi, dimensione).

Un rifiuto del driver è 422 con il suo codice; un guasto del server (`write_failed`, `verification_failed`) è 500 senza parametri.

### Stato in memoria

- **`FileStore`** (`web/filestore.py`): i file Gerber letti, per hash, con un limite di 1 GiB e lo scarto dei meno usati. Un progetto i cui file sono stati scartati riceve `file_missing` e va riaperto: la pagina lo fa da sola dalla copia di lavoro.
- **`PipelineCache`**: i file già interpretati e i materiali già costruiti (256 voci).

### Protezioni

Il server è locale, ma ogni richiesta si controlla. L'intestazione `Host` deve essere un nome locale (o uno dato con `--allowed-host`: protegge dal DNS rebinding), e una richiesta che modifica qualcosa deve venire dalla pagina stessa (`Origin` e `Sec-Fetch-Site`). Niente cache delle risposte (tranne le foto), `nosniff`, zip e progetti trattati come input ostile (limiti e verifica voce per voce). Non ci sono autenticazione né utenti: vedi [Rete e sicurezza](../installation/configuration.md#rete-e-sicurezza).

## La pagina

JavaScript puro in moduli ES, senza framework né passi di compilazione, in `gerberslap/web/static/` (`index.html`, `css/style.css`, `js/`). Disegna il piano con Canvas 2D.

| Modulo | Ruolo |
|---|---|
| `app.js` | Collega la pagina al server: stato, pannelli, eventi. |
| `api.js` | Le chiamate al server; ogni errore diventa un `ApiError` con codice e parametri. |
| `model.js` | Le schede nel browser e la matematica del posizionamento (centro dell'ingombro, rotazione, specchio). |
| `plane.js` | La vista del piano: zoom attorno al cursore, trascinamento con scatto, Rulers, vista Esatta. |
| `exposure.js` | Ricette, dosaggi, valori, richieste al server e motivo per cui «Genera» è spento: logica senza DOM. |
| `ladder.js` | La scala: valori, layout, anteprima SVG, zoom: logica senza DOM. |
| `placement.js`, `printercards.js` | Il disegno dei margini e le card delle stampanti: restituiscono markup e numeri. |
| `workcopy.js` | La copia di lavoro nel browser. |
| `i18n.js`, `flags.js` | I cataloghi di testo (italiano e inglese) e le bandiere. |

I moduli «senza DOM» si provano con Node.js, dai test.

- **Stato.** Le schede sono dati semplici; annulla e ripeti sono istantanee, fino a 80. Le preferenze (lingua, ultima ricetta, ultimi valori a mano, valori della scala, larghezza dei pannelli…) stanno in `localStorage`: non sono una libreria e, se mancano, la pagina funziona lo stesso.
- **Copia di lavoro** (`workcopy.js`). Il progetto all'ultimo «Salva» sta nel browser (IndexedDB, una copia per scheda del browser, con Web Locks per il ripristino dopo una chiusura) e da nessun'altra parte. Il pulsante «Scarica» produce il file `.gslp`.
- **Testi.** Nel codice non c'è nessuna frase: ogni stringa è una chiave del catalogo. Il server manda codici (`ls_*` per lo stato dei layer, `i_*` per gli avvisi, `err_*` per gli errori) e la pagina li trasforma in frasi.
- **Che cosa decide la pagina e che cosa il server.** La pagina tiene dove sta ogni scheda e che cosa è acceso; il server legge i file, manda le forme da disegnare, calcola la maschera esatta e i controlli. Niente su una scheda è inventato dalla pagina.

## Il file di progetto `.gslp`

Un progetto e i file Gerber che usa stanno in un solo zip, che non ha bisogno di nient'altro per riaprirsi:

- `project.json`: il progetto così com'è nel modello dati, con `format`, `schema_version`, `name` e, per ogni scheda, il programma CAD e le note fatte all'apertura dello zip;
- `files/<sha256>`: uno per ogni file Gerber o Excellon a cui un layer fa riferimento, uno per contenuto distinto, quindi schede che condividono file non costano nulla.

La scrittura è deterministica (stesso progetto, stessi byte) e il file si rilegge e si confronta prima di consegnarlo. La lettura è rigorosa, perché l'archivio viene da fuori: solo quelle voci, niente duplicati, dimensioni limitate, ogni file controllato contro il suo hash, niente di non usato. Un file che manca o è alterato rifiuta tutto il progetto, dicendo quale. Una versione più nuova del formato si rifiuta, una più vecchia si migra.

## La cartella dati

```text
data/
  printers/<id>/template.ctb      il template (mai nel repository)
  printers/<id>/printer.json      facoltativo: impostazioni del driver
  recipes/<id>.json               una ricetta per file
```

È l'unico stato sul disco del server. Un solo processo per cartella: le chiamate sono serializzate con un lock. Le scritture sono atomiche, e un file illeggibile si segnala senza mai ripararlo a occhio. Diventa il volume Docker. Dettagli in [Configurazione](../installation/configuration.md#la-cartella-dati).
