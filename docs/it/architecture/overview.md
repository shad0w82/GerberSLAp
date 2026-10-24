---
icon: material/sitemap-outline
---

# Panoramica

Come è fatto GerberSLAp: i principi su cui si regge, gli strati in cui è diviso il codice e il flusso dei dati dallo zip dei Gerber al file di stampa. Le pagine seguenti scendono nei dettagli: [Dal progetto al file](pipeline.md) e [Server e pagina](web-app.md). Per installare e avviare l'app, vedi [Installare l'app](../installation/install.md); per il formato del file e il comportamento verificato della stampante, il [documento del formato](https://github.com/shad0w82/GerberSLAp/blob/main/gerberslap/printers/ld002h/docs/ctb_v5_ld002h_formato.md).

## Principi

1. **Il server non conserva nulla dell'utente.** Il progetto (le schede, dove stanno, quali layer sono accesi) vive nel browser, che lo manda al server a ogni richiesta. Il server tiene in memoria solo i file Gerber che ha letto, indicizzati per hash, e li perde al riavvio: la pagina li ridà dalla copia di lavoro. Sul disco del server c'è solo la cartella dati, con i template delle stampanti e la libreria delle ricette. Un server pubblico non avrebbe progetti altrui da proteggere.
2. **Il raster finale si calcola sul server dalla geometria vettoriale**, con la trasformazione definitiva. L'anteprima del browser non si ricampiona mai per produrre il file: la vista *Esatta* e il file generato vengono dalla stessa maschera.
3. **Tutto ciò che dipende dalla stampante sta in un driver** (`printers/<id>/`): nome, dimensioni dello schermo, formato del file, limiti. Il nucleo, il modello dati, i riconoscitori CAD e i servizi non nominano mai né il formato `.ctb` né la LD-002H (un test lo controlla). Aggiungere una stampante non richiede modifiche al resto.
4. **Il movimento si copia sempre da un template** fatto in ChiTuBox, non si inventa. L'app cambia solo le immagini, l'esposizione e la quota Z.
5. **Ogni file scritto si rilegge e si confronta** prima di consegnarlo: il driver decodifica il file e lo paragona con quello voluto, e un file che non coincide non esce.
6. **Il server manda codici, la pagina scrive le frasi.** Avvisi, errori e stati dei layer arrivano come codici con parametri; il testo, in italiano e in inglese, sta tutto nel catalogo della pagina. Il server non conosce nessuna lingua.
7. **Niente si decide in silenzio.** Un file che non si legge, un layer disegnato in negativo, una maschera che copre quasi tutta la scheda: ogni cosa dubbia è segnata con un codice sul layer o tra gli avvisi, e un layer con un errore parte spento. Si blocca la generazione solo per ciò che renderebbe il file sbagliato.

## Vista d'insieme

```text
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

Tutte le coordinate sono in **millimetri sul piano di esposizione visto dall'alto, con l'utente davanti alla stampante**.

- `u` (o `x`) va da sinistra a destra, `v` (o `y`) dal fronte al retro. Lo zero è l'angolo in basso a sinistra del piano, quello dei Rulers.
- La **maschera** è un array booleano `(altezza, larghezza)` della griglia del piano: la riga 0 è il **retro**, la colonna 0 la **sinistra**. È la stessa orientazione della pagina, uguale per tutte le stampanti; ogni driver la gira come il suo file vuole.
- Il passo e la griglia sono parametri di ogni stampante: per la LD-002H, 0,051 mm e 2560 × 1620 pixel, cioè 130,56 × 82,62 mm.
- **Posizione di una scheda**: il centro del suo ingombro sul piano. L'angolo è in gradi, antiorario visto dall'alto. Lo specchio è sinistra-destra, applicato prima della rotazione, e anche questo attorno al centro dell'ingombro. Specchiare è una **scelta dell'utente sulla scheda posizionata** (tipicamente quando il rame sta verso il basso), non una conseguenza automatica.
- Tutto viene convertito in poligoni **prima** di qualunque trasformazione, quindi lo specchio non inverte il verso degli archi e qualunque angolo funziona.

## I moduli, strato per strato

Le dipendenze vanno verso il basso: ogni strato conosce solo quelli sotto.

```text
web/          rotte HTTP e pagina              (FastAPI; static/ = la pagina)
services/     controlli, importazione, pipeline, libreria, generazione, progetto su file
printers/     un driver per stampante          (printers/<id>/)
cad/          riconoscimento dei file di uno zip
model/        dati validati e immutabili       (pydantic)
core/         geometria, Gerber/Excellon, raster, scala   (nessuna stampante)
```

### `core/`: il nucleo, indipendente dalla stampante

- `gerber_io.py`: lettura di Gerber (RS-274X) ed Excellon con `gerbonara`, e apertura degli zip in sicurezza (limiti al numero e alla dimensione dei file, nomi filtrati). `gerbonara` 1.6.3 ha due difetti che qui si correggono a runtime (blocchi di step-and-repeat non espansi, macro di aperture con la primitiva 22): ogni correzione ha un test, e una versione diversa da quella provata dà un avviso. Non si aggiorna senza rifare i test.
- `geometry.py`: da file letti a geometria `shapely`. Contorno (linee con spessore minimo), fori (che si sottraggono), materiale, **area della scheda** (l'interno del contorno chiuso, con ripiego sul rettangolo d'ingombro e un avviso), posizionamento sul piano.
- `raster.py`: copertura per pixel di una geometria su una griglia regolare. Ogni pixel si campiona su 16 × 16 punti (minimo 8: con 4 × 4 si sbaglia sulle linee sottili) con la regola pari-dispari sui bordi, senza immagini intermedie; poi la maschera è «almeno metà coperto».
- `ladder.py`: il layout della scala di calibrazione e i pixel di ogni gradino ([La scala di calibrazione](pipeline.md#la-scala-di-calibrazione)).

### `cad/`: il riconoscimento

Dato l'elenco dei file di uno zip, ogni riconoscitore (KiCad, Altium, EAGLE, generico) dice quanto gli somiglia e assegna a ogni file un ruolo (rame, contorno, maschera, serigrafia, fori, ignorato), un lato (sopra, sotto, interno), una fiducia e un motivo. I segnali, in ordine di forza: gli **attributi X2** dentro i file, i nomi e le estensioni tipici del programma, il contenuto. Non legge mai la geometria.

Rifiuta i vecchi export di EAGLE, che non portano le informazioni necessarie (`ImportRefused`, con il motivo). Un file `.gbrjob` (KiCad, EAGLE) dà la misura dichiarata della scheda, che si confronta con il contorno.

### `model/`: i dati

Modelli `pydantic` immutabili, senza geometria e senza stampanti: i layer fanno riferimento ai file per hash.

| Modulo | Che cosa contiene |
|---|---|
| `project.py` | `Project` (stampante, ricetta e dosaggio di riferimento, polarità, spessore minimo del contorno, schede), `Board` (misura, centro, posizione, layer), `Layer` (ruolo, lato, acceso, stato, file per hash), `BoardPlacement` (x, y, angolo, specchio). |
| `layout.py` | `Plane`, ingombri, margini, sovrapposizioni: la geometria semplice su cui si basano gli avvisi. |
| `exposure.py` | `ExposureValues` (tempo totale, flash, riposo) e `ExposureLimits` (che cosa dice una stampante di un flash). |
| `catalog.py` | `Recipe`, `Dosage`, `RecipeRef`, `PrinterConfig`, `PrinterFile`. |
| `issues.py` | `Issue` (codice, gravità, se blocca, parametri) e l'elenco dei codici. |
| `ladder.py` | `LadderSpec`: i valori della scala, con i limiti. |

### `services/`

- `importer.py`: da uno zip a una `Board` (layer per hash, nessuna geometria) più i file da mettere in cache; segna ogni problema con un codice sul layer.
- `pipeline.py`: dal progetto alla maschera ([Dal progetto alla maschera](pipeline.md#dal-progetto-alla-maschera)). `vector.py`: i poligoni di un layer per il browser, relativi al centro della scheda, con i fori già tagliati e leggermente semplificati (2 µm, molto meno di un pixel).
- `checks.py`: i controlli come codice: layout, riferimenti (stampante, ricetta, polarità) e valori di esposizione. Una lista di `Issue` in ordine fisso.
- `generate.py` e `ladder.py`: il file della scheda e quello della scala.
- `installation.py`: la configurazione di una stampante, il suo stato «pronta» e l'installazione del template. `store.py`: la cartella dati. `library.py`: le operazioni sulla libreria. `projectfile.py`: il file `.gslp`. `files.py`: le scritture atomiche.
