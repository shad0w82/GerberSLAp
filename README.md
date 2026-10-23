Italiano | [English](README.en.md)

# GerberSLAp

GerberSLAp usa una stampante a resina (schermo LCD monocromatico e luce UV a 405 nm) come **unità di esposizione per circuiti stampati** con rame presensibilizzato. Si apre lo zip dei Gerber, si posiziona la scheda sul piano che rappresenta l'LCD, si sceglie il resist e l'esposizione e si ottiene il **file di stampa da copiare sulla chiavetta USB** della stampante (che non ha rete). La stampante «stampa» un solo strato per tutto il tempo scelto, e la luce passa dove il file ha pixel bianchi: sulla basetta resta l'immagine del circuito.

È un'app con interfaccia web: un piccolo server Python locale (FastAPI) e una pagina in JavaScript puro. Si usa dal browser, in locale o da un container Docker su un home server.

Oggi è supportata la **Creality LD-002H** (LCD mono 2K, file `.ctb` versione 5). Le altre stampanti si aggiungono con un driver, senza toccare il resto (vedi [Architettura](docs/ARCHITETTURA.md) e la [guida per aggiungerne una](docs/NUOVA_STAMPANTE.md)).

## Cosa fa

- **Legge gli zip dei Gerber** di KiCad, Altium ed EAGLE 9 (Gerber RS-274X ed Excellon): riconosce da sé il programma e che cos'è ogni file (rame, contorno, maschera di saldatura, serigrafia, fori). I vecchi export di EAGLE si rifiutano.
- **Piano 2D** che è l'LCD visto dall'alto, con righelli in millimetri, griglia, zoom e scatto: si dispongono una o più schede, con posizione, rotazione e specchio (per il rame rivolto verso il basso). Tre viste: *Materiale* (i layer come li disegna il CAD), *Luce UV* (dove passa la luce) ed *Esatta* (la maschera al pixel che finirà nel file).
- **Maschera al pixel**: calcolata dal server dalla geometria vettoriale, a passo esatto di 0,051 mm, con campionamento 16 × 16 per pixel. Resist positivo (la luce passa dove il rame va tolto) o negativo.
- **Esposizione**: tempo totale di luce, numero di flash e riposo tra i flash, a mano oppure da una **libreria di ricette e dosaggi** (un dosaggio è la terna di valori trovata provando, per una stampante).
- **Scala di calibrazione**: un file di prova con strisce esposte per tempi crescenti, con righe, distanze, impronte (SOIC-8, passo fine, passivi) e pad con foro, per trovare il tempo giusto di un resist.
- **Controlli**: avvisi su schede fuori dal piano o sovrapposte, layer di tipi diversi accesi insieme, flash fuori dai limiti della stampante e altro; la generazione si blocca solo per ciò che renderebbe il file sbagliato.
- **Progetti**: si salvano nel browser (copia di lavoro) e si scaricano come file `.gslp`, uno zip autosufficiente che contiene anche i Gerber. Il server non conserva nessun progetto.
- **Italiano e inglese.**

Limiti attuali: è una versione a singola faccia (un file espone i layer accesi in quel momento; il modello dati prevede già due facce, ma l'allineamento tra esposizioni successive della stessa basetta non è gestito); i piani interni negativi non sono supportati; una sola stampante (la LD-002H).

## Requisiti

- **Python 3.12 o più recente** (provato con 3.14).
- Un browser recente (provato con Chrome): la pagina usa IndexedDB e Web Locks.
- **Il template della stampante**: un file `.ctb` fatto con ChiTuBox, da cui l'app copia il movimento. Non è nel repository (contiene l'avviso di copyright di CBD Technology) e va preparato una volta: vedi [Installazione](docs/INSTALLAZIONE.md#il-template-della-stampante).
- Facoltativo, solo per i test: Node.js.

Provato su macOS (Apple Silicon). Il codice è Python e JavaScript puri e non usa nulla di specifico del sistema.

## Installazione e avvio nativi in breve

```bash
git clone https://github.com/shad0w82/GerberSLAp.git GerberSLAp && cd GerberSLAp
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# una volta sola: il template della stampante (vedi docs/INSTALLAZIONE.md)
.venv/bin/python -m gerberslap.web --install-template ld002h /percorso/del/template.ctb

# avvio (da questa cartella)
.venv/bin/python -m gerberslap.web
```

Si apre poi **http://127.0.0.1:8800** nel browser. Il server ascolta solo su questo computer; per fermarlo, `Ctrl+C`. Le opzioni di avvio, la cartella dati, la configurazione della stampante, l'installazione con Docker e la risoluzione dei problemi sono in [docs/INSTALLAZIONE.md](docs/INSTALLAZIONE.md).

## Con Docker in breve

```bash
docker compose build

# una volta sola: il template della stampante, nel volume (la cartella template/ contiene template.ctb)
docker compose run --rm -v "$PWD/template:/in:ro" gerberslap --install-template ld002h /in/template.ctb

docker compose up -d
```

Si apre poi **http://127.0.0.1:8800**. L'immagine (arm64 e amd64) non contiene nessun `.ctb`; template e ricette stanno nel volume `gerberslap-data`. Per raggiungerla da altri computer, le variabili d'ambiente e il resto: [docs/INSTALLAZIONE.md](docs/INSTALLAZIONE.md#installazione-con-docker).

## Uso in breve

1. **Aggiungi lo zip dei Gerber** (si trascina sulla pagina o si sceglie dal pulsante): la scheda compare sul piano, con i suoi layer riconosciuti e accesi o spenti.
2. **Posizionala** nella sezione *Posizione* (o trascinandola): posizione, rotazione e, se il rame è rivolto verso il basso, specchio.
3. **Scegli resist ed esposizione** nella sezione *Esposizione*: polarità (positivo o negativo), tempo totale, flash e riposo, oppure una ricetta con il suo dosaggio.
4. **Genera il file di stampa**: il pulsante scarica il `.ctb` col nome del progetto e mostra i numeri del file (layer, luce totale, durata stimata, area accesa).
5. **Copialo sulla chiavetta USB** e avvia la stampa dalla stampante. Con la scala di calibrazione, che si genera allo stesso modo, si trova prima il tempo giusto del resist; il risultato si salva come dosaggio in una ricetta.

Un manuale d'uso completo non c'è ancora.

## Documentazione

- [docs/INSTALLAZIONE.md](docs/INSTALLAZIONE.md): requisiti, il template della stampante, installazione nativa e con Docker, opzioni, rete e sicurezza, problemi frequenti.
- [docs/ARCHITETTURA.md](docs/ARCHITETTURA.md): come è fatta l'app: strati, flusso dei dati, modello dati, pipeline, driver, server, pagina, test e come estenderla.
- [docs/NUOVA_STAMPANTE.md](docs/NUOVA_STAMPANTE.md): per chi sviluppa: come scrivere il driver di una stampante nuova, e come creare e installare il suo template.
- [gerberslap/printers/ld002h/docs/ctb_v5_ld002h_formato.md](gerberslap/printers/ld002h/docs/ctb_v5_ld002h_formato.md): il formato `.ctb` v5 e il comportamento verificato della LD-002H.

## Test

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Circa 1160 test, un paio di minuti. Alcuni usano file di terzi o il template della stampante e si saltano se mancano; quelli sulla logica della pagina usano Node.js e si saltano se non c'è.

## Licenza

GerberSLAp è software libero, distribuito con la licenza **GNU Affero General Public License v3.0** (AGPL-3.0): il testo completo, che è quello che fa fede, è nel file [LICENSE](LICENSE). In breve: si può usare, studiare, modificare e ridistribuire; chi lo modifica e lo distribuisce, oppure lo offre a chi lo usa via rete (per esempio con un server pubblico), deve mettere a disposizione di quegli utenti il sorgente della propria versione con la stessa licenza.

Copyright (C) 2026 shad0w82.

**Ospitarlo su un server pubblico è a proprio rischio e pericolo**, e il progetto non lo prevede né lo supporta: l'app non ha autenticazione né utenti, e il server genera file a partire da un template `.ctb` che contiene l'avviso di copyright di CBD Technology (vedi [Installazione](docs/INSTALLAZIONE.md#rete-e-sicurezza)). Chi lo fa con una versione modificata deve anche cambiare il link «Codice sorgente e licenza» della pagina Aiuto (`gerberslap/web/static/index.html`, `id="source-link"`) perché punti al sorgente della sua versione.

## Terze parti

I file `.ctb` non fanno parte del repository.

GerberSLAp non è affiliato né approvato da CBD Technology, Creality o ChiTuBox: i loro nomi e marchi appartengono ai rispettivi titolari e qui servono solo a indicare con che cosa è compatibile.
