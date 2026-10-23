Italiano | [English](en/ARCHITECTURE.md)

# Architettura

Come è fatto GerberSLAp: i principi, gli strati e il flusso dei dati dallo zip dei Gerber al file di stampa. Per installarlo e avviarlo vedi [INSTALLAZIONE.md](INSTALLAZIONE.md); per il formato del file e il comportamento verificato della stampante, [ctb_v5_ld002h_formato.md](../ctb_v5_ld002h_formato.md).

- [Principi](#principi)
- [Vista d'insieme](#vista-dinsieme)
- [Convenzioni geometriche](#convenzioni-geometriche)
- [I moduli, strato per strato](#i-moduli-strato-per-strato)
- [Dal progetto alla maschera: la pipeline](#dal-progetto-alla-maschera-la-pipeline)
- [Le stampanti: i driver e il template](#le-stampanti-i-driver-e-il-template)
- [Esposizione, ricette e dosaggi](#esposizione-ricette-e-dosaggi)
- [La scala di calibrazione](#la-scala-di-calibrazione)
- [Il server](#il-server)
- [La pagina](#la-pagina)
- [Il file di progetto `.gslp`](#il-file-di-progetto-gslp)
- [La cartella dati](#la-cartella-dati)
- [Test](#test)
- [Come estenderla](#come-estenderla)

## Principi

1. **Il server non conserva nulla dell'utente.** Il progetto (le schede, dove stanno, quali layer sono accesi) vive nel browser, che lo manda al server a ogni richiesta; il server tiene in memoria solo i file Gerber che ha letto, indicizzati per hash, e li perde al riavvio (la pagina li ridà dalla copia di lavoro). Sul disco del server c'è solo la cartella dati: i template delle stampanti e la libreria delle ricette. Un server pubblico non avrebbe progetti altrui da proteggere.
2. **Il raster finale si calcola sul server dalla geometria vettoriale**, con la trasformazione definitiva. L'anteprima del browser non si ricampiona mai per produrre il file: la vista *Esatta* e il file generato vengono dalla stessa maschera.
3. **Tutto ciò che dipende dalla stampante sta in un driver** (`printers/<id>/`): nome, dimensioni dello schermo, formato del file, limiti. Il nucleo, il modello dati, i riconoscitori CAD e i servizi non nominano mai né il formato `.ctb` né la LD-002H (un test lo controlla). Aggiungere una stampante non richiede modifiche al resto.
4. **Il movimento si copia sempre da un template** fatto in ChiTuBox, non si inventa. L'app cambia solo le immagini, l'esposizione e la quota Z.
5. **Ogni file scritto si rilegge e si confronta** prima di consegnarlo (il driver decodifica il file e lo paragona con quello voluto); un file che non coincide non esce.
6. **Il server manda codici, la pagina scrive le frasi.** Avvisi, errori e stati dei layer arrivano come codici con parametri; il testo, in italiano e in inglese, sta tutto nel catalogo della pagina. Il server non conosce nessuna lingua.
7. **Niente si decide in silenzio.** Un file che non si legge, un layer disegnato in negativo, una maschera che copre quasi tutta la scheda: ogni cosa dubbia è segnata con un codice sul layer o tra gli avvisi, e un layer con un errore parte spento. Si blocca la generazione solo per ciò che renderebbe il file sbagliato.

## Vista d'insieme

```
BROWSER (la pagina)                        SERVER (FastAPI)
───────────────────                        ────────────────
progetto: schede, posizione,               cad/ + importer
rotazione, specchio, layer      ────────►  riconoscono e leggono i file dello zip
accesi (solo nel browser)       ◄────────  scheda: layer per hash, avvisi
                                /boards

disegno del piano               ────────►  vector
(poligoni dei layer)            ◄────────  poligoni di un layer
                                /geometry

vista Esatta                    ────────►  pipeline
(la maschera al pixel)          ◄────────  geometria → copertura 16×16 → maschera
                                /render

pulsante «Genera»               ────────►  controlli → pipeline → driver
scarica il file                 ◄────────  file della stampante, riletto e confrontato
                                /generate
```

Il file generato va sulla chiavetta USB e poi alla stampante. Nel browser stanno anche la copia di lavoro (IndexedDB), i progetti `.gslp` scaricati e le preferenze (localStorage); sul server, nella cartella dati, i template delle stampanti e le ricette.

Il server è sottile: le rotte non contengono logica di dominio, che sta nei moduli sotto `gerberslap/` e si prova senza avviare nulla.

## Convenzioni geometriche

Tutte le coordinate sono in **millimetri sul piano di esposizione visto dall'alto, con l'utente davanti alla stampante**:

- `u` (o `x`) va da sinistra a destra; `v` (o `y`) dal fronte al retro. Lo zero è l'angolo in basso a sinistra del piano (quello dei righelli).
- La **maschera** è un array booleano `(altezza, larghezza)` della griglia del piano: la riga 0 è il **retro**, la colonna 0 la **sinistra**. È la stessa orientazione della pagina, uguale per tutte le stampanti; ogni driver la gira come il suo file vuole.
- Il passo e la griglia sono parametri di ogni stampante (per la LD-002H, 0,051 mm e 2560 × 1620 pixel, cioè 130,56 × 82,62 mm).
- Posizione di una scheda: il centro del suo ingombro sul piano. Angolo in gradi, antiorario visto dall'alto. Lo specchio è sinistra-destra, applicato prima della rotazione, e anche questo attorno al centro dell'ingombro. Specchiare è una **scelta dell'utente sulla scheda posizionata** (tipicamente quando il rame sta verso il basso), non una conseguenza automatica.
- Tutto viene convertito in poligoni **prima** di qualunque trasformazione, quindi lo specchio non inverte il verso degli archi e qualunque angolo funziona.

## I moduli, strato per strato

Le dipendenze vanno verso il basso: ogni strato conosce solo quelli sotto.

```
web/          rotte HTTP e pagina              (FastAPI; static/ = la pagina)
services/     controlli, importazione, pipeline, libreria, generazione, progetto su file
printers/     un driver per stampante          (printers/<id>/)
cad/          riconoscimento dei file di uno zip
model/        dati validati e immutabili       (pydantic)
core/         geometria, Gerber/Excellon, raster, scala   (nessuna stampante)
```

### `core/`: nucleo indipendente dalla stampante

- `gerber_io.py`: lettura di Gerber (RS-274X) ed Excellon con `gerbonara`, e apertura degli zip in sicurezza (limiti al numero e alla dimensione dei file, nomi filtrati). `gerbonara` 1.6.3 ha due difetti che qui si correggono a runtime (blocchi di step-and-repeat non espansi, macro di aperture con la primitiva 22); ogni correzione ha un test e una versione diversa da quella provata dà un avviso.
- `geometry.py`: da file letti a geometria `shapely`; contorno (linee con spessore minimo), fori (che si sottraggono), materiale, **area della scheda** (l'interno del contorno chiuso, con ripiego sul rettangolo d'ingombro e avviso), posizionamento sul piano.
- `raster.py`: copertura per pixel di una geometria su una griglia regolare. Ogni pixel si campiona su 16 × 16 punti (minimo 8: con 4 × 4 si sbaglia sulle linee sottili) con la regola pari-dispari sui bordi, senza immagini intermedie; poi la maschera è «almeno metà coperto».
- `ladder.py`: il layout della scala di calibrazione e i pixel di ogni gradino (vedi sotto).

### `cad/`: riconoscimento

Dato l'elenco dei file di uno zip, ogni riconoscitore (KiCad, Altium, EAGLE, generico) dice quanto gli somiglia e assegna a ogni file ruolo (rame, contorno, maschera, serigrafia, fori, ignorato), lato (sopra, sotto, interno), fiducia e motivo. I segnali, in ordine di forza: gli **attributi X2** dentro i file, i nomi e le estensioni tipici del programma, il contenuto. Non legge mai la geometria. Rifiuta i vecchi export di EAGLE, che non portano le informazioni necessarie (`ImportRefused`, con il motivo). Un file `.gbrjob` (KiCad, EAGLE) dà la misura dichiarata della scheda, che si confronta con il contorno.

### `model/`: i dati

Modelli `pydantic` immutabili, senza geometria e senza stampanti: i layer fanno riferimento ai file per hash.

| Modulo | Che cosa contiene |
|---|---|
| `project.py` | `Project` (stampante, ricetta e dosaggio di riferimento, polarità, spessore minimo del contorno, schede), `Board` (misura, centro, posizione, layer), `Layer` (ruolo, lato, acceso, stato, file per hash), `BoardPlacement` (x, y, angolo, specchio). |
| `layout.py` | `Plane`, ingombri, margini, sovrapposizioni: la geometria semplice su cui si basano gli avvisi. |
| `exposure.py` | `ExposureValues` (tempo totale, flash, riposo) e `ExposureLimits` (cosa dice una stampante di un flash). |
| `catalog.py` | `Recipe`, `Dosage`, `RecipeRef`, `PrinterConfig`, `PrinterFile`. |
| `issues.py` | `Issue` (codice, gravità, se blocca, parametri) e l'elenco dei codici. |
| `ladder.py` | `LadderSpec`: i valori della scala, con i limiti. |

### `services/`

- `importer.py`: da uno zip a una `Board` (layer per hash, nessuna geometria) più i file da mettere in cache; segna ogni problema con un codice sul layer.
- `pipeline.py`: dal progetto alla maschera (sotto). `vector.py`: i poligoni di un layer per il browser, relativi al centro della scheda, con i fori già tagliati e leggermente semplificati (2 µm, molto meno di un pixel).
- `checks.py`: i controlli come codice: layout, riferimenti (stampante, ricetta, polarità) e valori di esposizione. Una lista di `Issue` in ordine fisso.
- `generate.py` e `ladder.py`: il file della scheda e quello della scala (sotto, e nel server).
- `installation.py`: configurazione di una stampante, il suo stato «pronta» e l'installazione del template. `store.py`: la cartella dati. `library.py`: le operazioni sulla libreria. `projectfile.py`: il file `.gslp`. `files.py`: scritture atomiche.

## Dal progetto alla maschera: la pipeline

`services/pipeline.py:render(progetto, file, griglia, polarità)`:

1. **Materiale di ogni scheda**, dai layer accesi in ordine di pila: rame e serigrafia come disegnati; il contorno come una linea di almeno `min_outline_mm`; la **maschera di saldatura** come *l'area della scheda meno le aperture che il suo file disegna* (la polarità dichiarata nel file della maschera non si usa); i fori, se il layer è acceso, si sottraggono. I layer di rame, maschera e serigrafia formano la **pila**: il loro ordine nell'elenco è l'ordine di disegno nella vista Materiale (al contrario se la scheda è specchiata) e non cambia mai cosa si espone; contorno e fori stanno a parte.
2. **Posizionamento** sul piano (posizione, rotazione, specchio).
3. **Unione** di tutte le schede (dove si sovrappongono il risultato è la somma).
4. **Copertura** per pixel dalla geometria vettoriale (mai ricampionando un'immagine), una sola volta.
5. **Polarità**, per ultima: con il resist **positivo** la luce passa dove *non* c'è materiale (dove il rame va asportato); con il **negativo** dove c'è.

La lettura dei Gerber e la costruzione del materiale sono la parte lenta, e stanno in una cache per hash dei file e per cosa è acceso: spostare una scheda costa un raster, non una rilettura. Fuori dal piano il materiale viene tagliato, con un avviso.

## Le stampanti: i driver e il template

Un driver è un oggetto in `printers/<id>/__init__.py` (esposto come `DRIVER`); la cartella ha per nome l'id del driver e contiene anche `icon.png`, la foto verticale (sfondo trasparente) che la pagina mostra. I driver si trovano da soli all'avvio.

**Il descrittore** dice cosa serve sapere della stampante senza usarla: id e nome, il piano in mm, la griglia dei pixel, i limiti di un flash (minimo, e massimo provato), se serve un template, il nome del file del template e l'estensione del file che scrive.

**L'interfaccia** (`printers/base.py`):

| Metodo | Compito |
|---|---|
| `check(esposizione, config, template)` | Gli avvisi della stampante (template mancante o non valido, impostazioni errate), come ogni altro controllo. |
| `validate_template(file)` | Giudica un template che l'utente ha fornito; rifiuta con un motivo. |
| `to_printer_image(maschera)` | La maschera del piano come immagine del file della stampante. |
| `build(maschera, esposizione, config, template, percorso)` | Scrive il file per una maschera, lo rilegge, lo confronta e solo allora lo consegna; altrimenti `BuildError`. |
| `build_sequence(maschere, flash, …)` | Scrive un file di più maschere in fila (la scala); un driver che non lo sa fare lo dice. |

**Il driver della LD-002H** (`printers/ld002h/`), sopra `ctbio.py`, che sta nella stessa cartella (lettura e scrittura del `.ctb` v5: cifratura, RLE, anteprime, CRC; validato byte per byte contro file di ChiTuBox). Nella sottocartella `docs/` ci sono il documento del formato e il comportamento verificato della stampante (`ctb_v5_ld002h_formato.md`) e `pcb_ctb.py`, una riga di comando di prova da cui sono nati il driver e quel documento:

- L'immagine del file è il piano ruotato di un quarto di giro in senso orario, senza riflessione.
- Una dose di *T* secondi in *N* flash sono *N* layer identici da *T/N* secondi: la stampante legge **un solo tempo di esposizione dall'intestazione** e lo applica a tutti i layer. Il **riposo** tra i flash è l'unica pausa di buio (si scrive come riposo prima del sollevamento).
- Il movimento (distanze e velocità, secondi stadi, gli altri riposi) si copia dal template; non si scrive mai una distanza di sollevamento 0 (la stampante farebbe un ciclo da 5 mm). Tutti i layer stanno alla stessa quota Z bassa (predefinita 1 mm).
- L'anteprima del file è il primo layer, visto dall'alto, ritagliato su ciò che è acceso.
- **Il template** si giudica prima di usarlo: file `.ctb` v5, CRC corretto, risoluzione dello schermo, almeno un layer che si decodifica, distanze di sollevamento maggiori di 0 e velocità valide. Un template con una distanza di sollevamento grande (oltre 1 mm) è accettato ma dà un avviso, perché rende lenti i flash.
- Limiti: il flash minimo è 1 s (sotto non si genera); oltre 20 s si genera con un avviso (non provato).
- **La verifica prima di consegnare**: il file si scrive in un file temporaneo nascosto, si rilegge e si confrontano il CRC, il numero di layer, l'esposizione e il numero di bottom nell'intestazione, la risoluzione, il riposo, e di ogni layer la quota Z, l'esposizione, il movimento copiato e i pixel. Solo se tutto coincide il file prende il suo posto.

**Il template `.ctb` non è nel repository** (contiene l'avviso di copyright del produttore, che finisce anche nei file generati) e si installa nella cartella dati: `printers/<id>/template.ctb`.

## Esposizione, ricette e dosaggi

- **Stampante**: il tipo di stampante (l'id del driver), non l'unità con il suo numero di serie. Non ha valori di esposizione.
- **Ricetta**: nome, **polarità** (che non si cambia dopo la creazione: se il resist cambia, è un'altra ricetta), resist, sviluppo, note e i suoi dosaggi.
- **Dosaggio**: tempo totale di luce, numero di flash e riposo **trovati provando, per una stampante**, con data, nome e nota facoltativi. I dosaggi di una ricetta per una stampante sono alternative tutte valide (per esempio per piste fini o per grandi piani di massa), non versioni una dell'altra. «Dose» è solo il tempo totale di luce.

Il progetto non contiene mai i valori di esposizione: contiene un riferimento (id e nome della ricetta, polarità, dosaggio scelto) e i valori vengono dal dosaggio o si inseriscono a mano. Quando si apre un progetto, la polarità della ricetta vince su quella salvata (una polarità sbagliata rovina la scheda) e lo dice; una ricetta che la libreria non ha si segnala e il progetto resta con la polarità salvata e senza ricetta.

**La libreria** sta nella cartella dati (`recipes/<id>.json`, una ricetta per file) e si gestisce dalla pagina con le rotte `/api/recipes`. Ogni operazione risponde con la ricetta com'è dopo; la data di un dosaggio cambia solo se cambiano i valori; le modifiche si leggono-cambiano-scrivono dentro un lock, quindi due browser non si perdono i cambiamenti a vicenda. Tetti: 500 ricette e 100 dosaggi per ricetta. Con `--no-library` queste rotte non si registrano (404).

**Il server genera con ciò che riceve**: la richiesta di generazione porta il progetto, la polarità, i tre valori e, se c'è, la ricetta scelta (id, nome, polarità). Non legge mai la libreria, e per questo funziona uguale con `--no-library`.

## La scala di calibrazione

Serve a trovare il tempo giusto di un resist: un solo file in cui strisce affiancate ricevono tempi crescenti. Una **striscia** *k* è accesa per *k* volte il tempo della prima: il **gradino** *i* del file accende le strisce da *i* in poi, con un tempo per layer uguale per tutti (la stampante ne usa uno). Ogni gradino è fatto di `pulses` flash da `step / pulses` secondi con il riposo tra l'uno e l'altro, quindi il file ha `bands × pulses` layer.

Ogni striscia (misure a scelta, 13 × 76 mm di partenza, 1 mm di buio tra una e l'altra, centrate sul piano) porta in alto il suo tempo e sotto le **prove** scelte: righe e spazi verticali e orizzontali da 0,10 a 0,40 mm, coppie di pad con distanze strette, un SOIC-8, un passo fine, passivi (0805, 0603, 0402) e pad con foro. Le prove si dispongono in righe (`strip_drawing`), che si adattano alla larghezza e all'altezza; quelle senza posto si dichiarano.

- **Resist positivo**: la striscia è accesa, tranne dove resta il rame (le prove e la scritta). **Negativo**: è acceso solo il rame. **Specchio**: tutto capovolto da sinistra a destra, scritta compresa.
- **Il layout è definito due volte, e identico**: in `core/ladder.py` (per il file) e in `static/js/ladder.js` (per l'anteprima della pagina). Un test lancia `ladder.js` con Node e confronta numero per numero prove, disposizione, scritta, posizione delle strisce e avvisi. Cambia solo la forma delle lettere (la pagina usa il carattere del browser, il file quello che Pillow porta con sé, ispessito: non c'è nessun file di carattere da installare).
- Ogni striscia si disegna in una piccola finestra della griglia allineata ai pixel, che dà gli stessi pixel di tutta la griglia ed è molto più veloce.
- Il file è scritto dal driver con `build_sequence`; si chiama `scala_<primo gradino>s_x<gradini>` (per esempio `scala_10s_x8.ctb`).

## Il server

`gerberslap/web/app.py`: una app FastAPI sottile, locale e per un solo utente, che serve anche la pagina statica. `python -m gerberslap.web` la avvia con `uvicorn` (un solo processo).

### Rotte

| Rotta | Che cosa fa |
|---|---|
| `GET /api/info` | Versione, stampante predefinita, stampanti (piano, griglia, limiti, **se sono pronte e perché no**, foto), se la libreria c'è, con quali opzioni è partita l'app. Si rilegge a ogni richiesta: installare il template non richiede un riavvio. |
| `GET /api/printers/<id>/picture` | La foto della stampante (tenuta dal browser un'ora). |
| `POST /api/boards` | Apre uno zip: riconosce, legge, ritorna la scheda (layer per hash) con avvisi e programma CAD. I file restano nella cache del server. |
| `POST /api/geometry` | I poligoni di un layer, per disegnarli. |
| `POST /api/render` | La maschera esatta (PNG a 1 bit in base64) per un progetto e una polarità, con gli avvisi del raster. |
| `POST /api/check` | I controlli di un progetto. Se la richiesta porta `exposure` (anche `null`) sono tutti: layout, riferimenti e valori; senza, solo il layout. |
| `POST /api/generate` | Il file di stampa di un progetto. |
| `POST /api/generate/ladder` | Il file della scala di calibrazione. |
| `POST /api/project/save`, `POST /api/project/open` | Scrive e legge il file `.gslp`. |
| `/api/recipes…` | La libreria: elenco, crea, modifica, elimina, duplica una ricetta; aggiungi, modifica, elimina e copia un dosaggio. Solo con la libreria accesa. |
| `GET /dev/samples/<nome>` | Solo con `--dev-samples`. |

Le richieste sono validate con `pydantic` (campi sconosciuti rifiutati, niente NaN o infiniti). Gli errori hanno sempre la forma `{"error": {"code": "...", "params": {...}}}`: un codice stabile, mai un percorso del server né un testo da mostrare.

**La generazione** (`services/generate.py`): fa tutti i controlli (layout, riferimenti, valori e quelli del driver sulla stampante); se qualcosa **blocca** risponde 422 `generation_blocked` con *tutti* gli avvisi; altrimenti disegna la maschera con la pipeline, chiede al driver di scrivere in una cartella temporanea che poi sparisce, e risponde con i byte del file (`application/octet-stream`), `Content-Disposition` (il nome del progetto reso sicuro, con l'estensione del driver) e il riepilogo in `X-Build-Summary` (JSON: layer, flash, riposo, luce totale, durata stimata dalla stampante, pixel e area accesi, dimensione). Un rifiuto del driver è 422 con il suo codice; un guasto del server (`write_failed`, `verification_failed`) è 500 senza parametri.

### Stato in memoria

- **`FileStore`** (`web/filestore.py`): i file Gerber letti, per hash, con un limite (1 GiB) e scarto dei meno usati. Un progetto i cui file sono stati scartati riceve `file_missing` e va riaperto: la pagina lo fa da sola dalla copia di lavoro.
- **`PipelineCache`**: i file già interpretati e i materiali già costruiti (256 voci).

### Protezioni

Server locale, ma ogni richiesta si controlla: l'intestazione `Host` deve essere un nome locale (o uno dato con `--allowed-host`: protegge dal DNS rebinding), e una richiesta che modifica qualcosa deve venire dalla pagina stessa (`Origin` e `Sec-Fetch-Site`). Niente cache delle risposte (tranne le foto), `nosniff`, zip e progetti trattati come input ostile (limiti e verifica voce per voce). Non ci sono autenticazione né utenti: vedi [Rete e sicurezza](INSTALLAZIONE.md#rete-e-sicurezza).

## La pagina

JavaScript puro in moduli ES, senza framework né passi di compilazione, in `gerberslap/web/static/` (`index.html`, `css/style.css`, `js/`). Disegna il piano con Canvas 2D.

| Modulo | Ruolo |
|---|---|
| `app.js` | Collega la pagina al server: stato, pannelli, eventi. |
| `api.js` | Le chiamate al server; ogni errore diventa un `ApiError` con codice e parametri. |
| `model.js` | Le schede nel browser e la matematica del posizionamento (centro dell'ingombro, rotazione, specchio). |
| `plane.js` | La vista del piano: zoom attorno al cursore, trascinamento con scatto, righelli, vista esatta. |
| `exposure.js` | Ricette, dosaggi, valori, richieste al server e motivo per cui «Genera» è spento: logica senza DOM. |
| `ladder.js` | La scala: valori, layout, anteprima SVG, zoom: logica senza DOM. |
| `placement.js`, `printercards.js` | Il disegno dei margini; le card delle stampanti: restituiscono markup e numeri. |
| `workcopy.js` | La copia di lavoro nel browser. |
| `i18n.js`, `flags.js` | I cataloghi di testo (italiano e inglese) e le bandiere. |

I moduli «senza DOM» si provano con Node.js, dai test.

- **Stato**: le schede sono dati semplici; annulla e ripeti sono istantanee (fino a 80). Le preferenze (lingua, ultima ricetta, ultimi valori a mano, valori della scala, larghezza dei pannelli…) stanno in `localStorage`; non sono una libreria e, se mancano, la pagina funziona lo stesso.
- **Copia di lavoro** (`workcopy.js`): il progetto all'ultimo «Salva», nel browser (IndexedDB, una copia per scheda del browser, con Web Locks per il ripristino dopo una chiusura) e da nessun'altra parte. Il pulsante «Scarica» produce il file `.gslp`.
- **Testi**: nel codice non c'è nessuna frase; ogni stringa è una chiave del catalogo. Il server manda codici (`ls_*` per lo stato dei layer, `i_*` per gli avvisi, `err_*` per gli errori) e la pagina li trasforma in frasi.
- **Cosa decide la pagina e cosa il server**: la pagina tiene dove sta ogni scheda e cosa è acceso; il server legge i file, manda le forme da disegnare, calcola la maschera esatta e i controlli. Niente su una scheda è inventato dalla pagina.

## Il file di progetto `.gslp`

Un progetto e i file Gerber che usa, in un solo zip che non ha bisogno di nient'altro per riaprirsi: `project.json` (il progetto così com'è nel modello dati, con `format`, `schema_version`, `name` e, per ogni scheda, il programma CAD e le note fatte all'apertura dello zip) e, per ogni file Gerber o Excellon a cui un layer fa riferimento, `files/<sha256>` (uno per contenuto distinto: schede che condividono file non costano nulla).

La scrittura è deterministica (stesso progetto, stessi byte) e il file si rilegge e si confronta prima di consegnarlo. La lettura è rigorosa, perché l'archivio viene da fuori: solo quelle voci, niente duplicati, dimensioni limitate, ogni file controllato contro il suo hash, niente di non usato; un file che manca o è alterato rifiuta tutto il progetto, dicendo quale. Una versione più nuova del formato si rifiuta, una più vecchia si migra.

## La cartella dati

```
data/
  printers/<id>/template.ctb      il template (mai nel repository)
  printers/<id>/printer.json      facoltativo: impostazioni del driver
  recipes/<id>.json               una ricetta per file
```

È l'unico stato sul disco del server. Un solo processo per cartella (le chiamate sono serializzate con un lock); le scritture sono atomiche; un file illeggibile si segnala senza mai ripararlo a occhio. Diventa il volume Docker. Dettagli in [INSTALLAZIONE.md](INSTALLAZIONE.md#la-cartella-dati).

## Test

`pytest` (circa 1160 test, un paio di minuti). Dati sintetici in `tests/support/testdata.py`; un **oracolo indipendente** (`oracle.py`) calcola le aree esatte con un altro metodo, per controllare il raster; una scheda con forma nota (`markerboard.py`) fissa dove atterra ogni cosa; stampanti finte (`fakeprinters.py`) permettono di provare il server senza il template vero.

- Il **test di regressione del formato**: ricostruire `boxsmall.ctb` (un file di ChiTuBox, che non è nel repository) dai suoi stessi pixel e parametri deve dare 18 byte di differenza (le stime di resina, azzerate di proposito, e tre valori Z arrotondati diversamente).
- I test del server usano il client di prova di FastAPI; la logica della pagina senza DOM si prova con Node.js; il layout della scala si confronta tra Python e JavaScript.
- Alcuni test usano file di terzi (zip di Gerber di KiCad, Altium ed EAGLE, in `experiments/fase1/external/` e `experiments/fase2/external/`) o il template della stampante (`samples/speedCube.ctb`): non sono nel repository, e quelle cartelle sono nel `.gitignore`. Quei test si saltano se mancano.
- Un test controlla che il nucleo, il modello dati, `cad/` e `services/` non nominino la stampante né il formato del suo file, e che ogni driver abbia la sua `icon.png`.
- `tests/test_docker.py` controlla, senza Docker, che cosa entra nell'immagine (calcola il contesto di build da `.dockerignore`: nessun `.ctb`, né dati, né test) e che il `Dockerfile` e `compose.yaml` abbiano le proprietà che contano (utente senza privilegi, volume, porta solo locale); `tests/test_startup_env.py` prova le variabili d'ambiente di avvio.

## Come estenderla

**Aggiungere una stampante.** La guida completa, con un esempio funzionante, i test da scrivere e come creare e installare il template, è [NUOVA_STAMPANTE.md](NUOVA_STAMPANTE.md). In breve: una cartella `gerberslap/printers/<id>/` con `__init__.py` che espone `DRIVER` (un `PrinterDriver`: descrittore, `check`, `validate_template`, `to_printer_image`, `build` ed eventualmente `build_sequence`) e `icon.png` (foto verticale, PNG più alto che largo, sfondo trasparente, fino a 512 KB). Il resto dell'app la trova da sé: compare nella pagina, ha il suo stato «pronta» e la sua cartella dati. Se serve un template, il driver dice il nome del suo file e il template si installa con `--install-template <id> <file>`. Non serve toccare il nucleo, il modello dati né la pagina.

**Aggiungere una lingua.** Un catalogo in `static/js/i18n.js` con le stesse chiavi e una voce in `static/js/flags.js`.

**Aggiungere un programma CAD.** Un riconoscitore in `gerberslap/cad/` con la stessa interfaccia degli altri (punteggio e assegnazione dei file) e un test con uno zip vero.
