---
icon: material/pipe
---

# Dal progetto al file

Come un progetto diventa il file di stampa: la pipeline che costruisce la maschera, i driver che la scrivono nel formato della stampante, il modo in cui si descrive l'esposizione e la scala di calibrazione. Gli strati e le convenzioni sono nella [Panoramica](overview.md).

## Dal progetto alla maschera

`services/pipeline.py:render(progetto, file, griglia, polarità)` fa cinque passi:

1. **Il materiale di ogni scheda**, dai layer accesi in ordine di pila.
    - Rame e serigrafia si usano come sono disegnati.
    - Il contorno è una linea di almeno `min_outline_mm`.
    - La **maschera di saldatura** è *l'area della scheda meno le aperture che il suo file disegna*: la polarità dichiarata nel file della maschera non si usa.
    - I fori, se il layer è acceso, si sottraggono.
2. **Il posizionamento** sul piano: posizione, rotazione, specchio.
3. **L'unione** di tutte le schede. Dove si sovrappongono, il risultato è la somma.
4. **La copertura** per pixel dalla geometria vettoriale, mai ricampionando un'immagine, una sola volta.
5. **La polarità**, per ultima: con il resist **positivo** la luce passa dove *non* c'è materiale (dove il rame va asportato); con il **negativo** dove c'è.

I layer di rame, maschera e serigrafia formano la **pila**. Il loro ordine nell'elenco è l'ordine di disegno nella vista Materiale (al contrario se la scheda è specchiata, perché si vede il lato sotto) e non cambia mai cosa si espone. Contorno e fori stanno a parte, in fondo, e non si spostano.

La lettura dei Gerber e la costruzione del materiale sono la parte lenta, e stanno in una cache per hash dei file e per cosa è acceso: spostare una scheda costa un raster, non una rilettura. Fuori dal piano il materiale viene tagliato, con un avviso.

## Le stampanti: i driver e il template

Un driver è un oggetto in `printers/<id>/__init__.py`, esposto come `DRIVER`. La cartella ha per nome l'id del driver e contiene anche `icon.png`, la foto verticale (con sfondo trasparente) che la pagina mostra. I driver si trovano da soli all'avvio; per scriverne uno vedi [Il driver di una stampante](../development/new-printer/driver.md).

**Il descrittore** dice che cosa serve sapere della stampante senza usarla: id e nome, il piano in mm, la griglia dei pixel, i limiti di un flash (minimo e massimo provato), se serve un template, il nome del file del template e l'estensione del file che scrive.

**L'interfaccia** (`printers/base.py`):

| Metodo | Compito |
|---|---|
| `check` | `(esposizione, config, template)`<br>Gli avvisi della stampante (template mancante o non valido, impostazioni errate), come ogni altro controllo. |
| `validate_template` | `(file)`<br>Giudica un template che l'utente ha fornito; rifiuta con un motivo. |
| `to_printer_image` | `(maschera)`<br>La maschera del piano come immagine del file della stampante. |
| `build` | `(maschera, esposizione, config, template, percorso)`<br>Scrive il file per una maschera, lo rilegge, lo confronta e solo allora lo consegna; altrimenti `BuildError`. |
| `build_sequence` | `(maschere, flash, …)`<br>Scrive un file di più maschere in fila (la scala); un driver che non lo sa fare lo dice. |

### Il driver della LD-002H

Sta in `printers/ld002h/`, sopra `ctbio.py` nella stessa cartella: la lettura e la scrittura del `.ctb` v5 (cifratura, RLE, anteprime, CRC), validata byte per byte contro file di ChiTuBox. Nella sottocartella `docs/` ci sono il documento del formato e del comportamento verificato della stampante (`ctb_v5_ld002h_formato.md`) e `pcb_ctb.py`, una riga di comando di prova da cui sono nati il driver e quel documento.

- L'immagine del file è il piano ruotato di un quarto di giro in senso orario, senza riflessione.
- Una dose di *T* secondi in *N* flash sono *N* layer identici da *T/N* secondi: la stampante legge **un solo tempo di esposizione dall'intestazione** e lo applica a tutti i layer. Il **riposo** tra i flash è l'unica pausa di buio, e si scrive come riposo prima del sollevamento.
- Il movimento (distanze e velocità, secondi stadi, gli altri riposi) si copia dal template. Non si scrive mai una distanza di sollevamento 0, perché la stampante farebbe un ciclo da 5 mm. Tutti i layer stanno alla stessa quota Z bassa (predefinita 1 mm).
- L'anteprima del file è il primo layer, visto dall'alto, ritagliato su ciò che è acceso.
- **Il template si giudica prima di usarlo**: file `.ctb` v5, CRC corretto, risoluzione dello schermo, almeno un layer che si decodifica, distanze di sollevamento maggiori di 0 e velocità valide. Un template con una distanza di sollevamento grande (oltre 1 mm) è accettato ma dà un avviso, perché rende lenti i flash.
- Limiti: il flash minimo è 1 s (sotto non si genera); oltre 20 s si genera con un avviso, perché non è stato provato.
- **La verifica prima di consegnare.** Il file si scrive in un file temporaneo nascosto, si rilegge e si confrontano il CRC, il numero di layer, l'esposizione e il numero di bottom nell'intestazione, la risoluzione, il riposo e, di ogni layer, la quota Z, l'esposizione, il movimento copiato e i pixel. Solo se tutto coincide il file prende il suo posto.

Il template `.ctb` non è nel repository, perché contiene l'avviso di copyright del produttore, che finisce anche nei file generati. Si installa nella cartella dati, in `printers/<id>/template.ctb` ([Requisiti e template](../installation/requirements.md#il-template-della-stampante)).

## Esposizione, ricette e dosaggi

- **Stampante**: il tipo di stampante (l'id del driver), non l'unità con il suo numero di serie. Non ha valori di esposizione.
- **Ricetta**: nome, **polarità** (che non si cambia dopo la creazione: se il resist cambia, è un'altra ricetta), resist, sviluppo, note e i suoi dosaggi.
- **Dosaggio**: tempo totale di luce, numero di flash e riposo **trovati provando, per una stampante**, con data, nome e nota facoltativi. I dosaggi di una ricetta per una stampante sono alternative tutte valide (per esempio per piste fini o per grandi piani di massa), non versioni una dell'altra. «Dose» è solo il tempo totale di luce.

Il progetto non contiene mai i valori di esposizione: contiene un riferimento (id e nome della ricetta, polarità, dosaggio scelto), e i valori vengono dal dosaggio o si inseriscono a mano. Quando si apre un progetto, la polarità della ricetta vince su quella salvata, perché una polarità sbagliata rovina la scheda, e lo dice. Una ricetta che la libreria non ha si segnala, e il progetto resta con la polarità salvata e senza ricetta.

**La libreria** sta nella cartella dati (`recipes/<id>.json`, una ricetta per file) e si gestisce dalla pagina con le rotte `/api/recipes`. Ogni operazione risponde con la ricetta com'è dopo. La data di un dosaggio cambia solo se cambiano i valori. Le modifiche si leggono, si cambiano e si scrivono dentro un lock, quindi due browser non si perdono i cambiamenti a vicenda. I tetti sono 500 ricette e 100 dosaggi per ricetta. Con `--no-library` queste rotte non si registrano (404).

**Il server genera con ciò che riceve.** La richiesta di generazione porta il progetto, la polarità, i tre valori e, se c'è, la ricetta scelta (id, nome, polarità). Non legge mai la libreria, e per questo funziona uguale con `--no-library`.

## La scala di calibrazione

Serve a trovare il tempo giusto di un resist: un solo file in cui strisce affiancate ricevono tempi crescenti. Una **striscia** *k* è accesa per *k* volte il tempo della prima. Il **gradino** *i* del file accende le strisce da *i* in poi, con un tempo per layer uguale per tutti, perché la stampante ne usa uno. Ogni gradino è fatto di `pulses` flash da `step / pulses` secondi con il riposo tra l'uno e l'altro, quindi il file ha `bands × pulses` layer.

Ogni striscia (misure a scelta, 13 × 76 mm di partenza, 1 mm di buio tra una e l'altra, centrate sul piano) porta in alto il suo tempo e sotto le **prove** scelte: righe e spazi verticali e orizzontali da 0,10 a 0,40 mm, coppie di pad con distanze strette, un SOIC-8, un passo fine, passivi (0805, 0603, 0402) e pad con foro. Le prove si dispongono in righe (`strip_drawing`), che si adattano alla larghezza e all'altezza; quelle senza posto si dichiarano.

- **Resist positivo**: la striscia è accesa, tranne dove resta il rame (le prove e la scritta). **Negativo**: è acceso solo il rame. **Specchio**: tutto capovolto da sinistra a destra, scritta compresa.
- **Il layout è definito due volte, ed è identico**: in `core/ladder.py` (per il file) e in `static/js/ladder.js` (per l'anteprima della pagina). Un test lancia `ladder.js` con Node e confronta numero per numero prove, disposizione, scritta, posizione delle strisce e avvisi. Cambia solo la forma delle lettere: la pagina usa il carattere del browser, il file quello che Pillow porta con sé, ispessito, quindi non c'è nessun file di carattere da installare.
- Ogni striscia si disegna in una piccola finestra della griglia allineata ai pixel, che dà gli stessi pixel di tutta la griglia ed è molto più veloce.
- Il file è scritto dal driver con `build_sequence` e si chiama `scala_<primo gradino>s_x<gradini>`, per esempio `scala_10s_x8.ctb`.
