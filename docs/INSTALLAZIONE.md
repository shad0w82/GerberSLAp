Italiano | [English](en/INSTALLATION.md)

# Installazione e avvio

Questa guida spiega come installare GerberSLAp ed eseguirlo, in modo nativo o con Docker. Come è fatta l'app dentro è in [ARCHITETTURA.md](ARCHITETTURA.md).

- [Requisiti](#requisiti)
- [Il template della stampante](#il-template-della-stampante)
- [Installazione nativa](#installazione-nativa)
- [Opzioni, variabili d'ambiente e cartella dati](#opzioni-variabili-dambiente-e-cartella-dati)
- [Installazione con Docker](#installazione-con-docker)
- [Rete e sicurezza](#rete-e-sicurezza)
- [Aggiornare](#aggiornare)
- [Problemi frequenti](#problemi-frequenti)
- [Eseguire i test](#eseguire-i-test)

## Requisiti

| | |
|---|---|
| Python | 3.12 o più recente (la libreria `gerbonara` lo richiede). Provato con 3.14. |
| Sistema | Provato su macOS (Apple Silicon). Il codice è Python e JavaScript puri, senza parti specifiche del sistema; per Linux valgono gli stessi comandi. |
| Browser | Uno recente (provato con Chrome). La pagina usa IndexedDB e Web Locks per la copia di lavoro. |
| Template della stampante | Un file `.ctb` fatto con ChiTuBox, vedi sotto. Non è nel repository. |
| Node.js | Solo per eseguire i test della logica della pagina (facoltativo). |

Le dipendenze Python sono fissate in `requirements.txt` (numpy, Pillow, shapely, gerbonara, pydantic, fastapi, uvicorn, python-multipart). `gerbonara` 1.6.3 viene corretto a runtime in `gerberslap/core/gerber_io.py`: non aggiornarlo senza rifare i test.

## Il template della stampante

**Che cos'è.** L'app non scrive il file `.ctb` da zero: parte da un file fatto da ChiTuBox, il *template*, e ne cambia solo le immagini dei layer, il tempo di esposizione e la quota Z. Tutto il resto (le distanze e le velocità di sollevamento, i secondi stadi, i riposi, i campi del formato che non sono documentati) lo copia dal template così com'è: sono i valori che la stampante ha già mostrato di accettare, e inventarli può far muovere il carrello in modo imprevisto. Il template è anche il modo in cui scegli *tu* come si muove la stampante durante l'esposizione. (Per una stampante diversa dalla LD-002H il principio è lo stesso: vedi [NUOVA_STAMPANTE.md](NUOVA_STAMPANTE.md#il-template).)

**Perché non è nel repository.** Un file `.ctb` contiene l'avviso di copyright di CBD Technology, e lo stesso avviso finisce nei file che l'app genera. Per questo né il template né i file generati vanno nel repository o in un'immagine Docker: ognuno prepara il suo e lo installa nella cartella dati.

**Come si prepara.** In ChiTuBox, con la stampante *Creality LD-002H*, affetta un oggetto qualunque (un cubo basta) con queste impostazioni e salva il file `.ctb`:

- *Waiting Mode*: «Resting time», con i tre tempi di riposo a 0;
- distanza di sollevamento del bottom e distanza di sollevamento normale: **0,001 mm** (e 0 il secondo valore, quello dopo il «+»);
- le quattro velocità (sollevamento e ritorno, bottom e normali): **500 mm/min** (e 0 i secondi valori);
- un solo layer bottom.

Non usare mai una distanza di sollevamento 0: la stampante la sostituirebbe con un ciclo da 5 mm. L'app rifiuta un template che la usa.

**Come si installa.** Una volta sola, dalla cartella del progetto:

```bash
.venv/bin/python -m gerberslap.web --install-template ld002h /percorso/del/template.ctb
```

Il comando controlla il file con il driver della stampante prima di scrivere qualsiasi cosa, lo copia in `<cartella dati>/printers/ld002h/template.ctb` e termina senza avviare il server. Esce con 0 (fatto), 1 (file o cartella rifiutati: dice perché) o 2 (non esiste una stampante con quell'id). Rilanciarlo sostituisce il template.

Una volta avviata l'app, in *Impostazioni* la card della stampante dice **Pronta**, e il pulsante «Genera» si può accendere. Senza template l'icona degli avvisi è rossa e il pulsante resta spento con il motivo scritto sotto.

## Installazione nativa

```bash
git clone https://github.com/shad0w82/GerberSLAp.git GerberSLAp
cd GerberSLAp
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Poi si installa il template (sopra) e si avvia:

```bash
.venv/bin/python -m gerberslap.web
```

Il server ascolta su **http://127.0.0.1:8800**, cioè solo su questo computer, e stampa all'avvio la cartella dati in uso e se la libreria delle ricette è accesa. Si apre quell'indirizzo nel browser e si lavora; per fermare il server, `Ctrl+C`.

Note:

- Si avvia **dalla cartella del progetto**: il pacchetto `gerberslap` si trova lì, e la cartella dati predefinita, `./data`, è relativa a dove si lancia il comando.
- Il server è un processo normale, che si chiude con il terminale. Per tenerlo sempre acceso si usa il gestore dei servizi del sistema (launchd, systemd) oppure Docker.
- **Usa sempre lo stesso indirizzo nel browser.** La copia di lavoro dei progetti sta nel browser e dipende dall'indirizzo: `http://127.0.0.1:8800` e `http://localhost:8800` sono per lui due siti diversi, con due copie diverse.

## Opzioni, variabili d'ambiente e cartella dati

```
python -m gerberslap.web [opzioni]
```

| Opzione | Significato |
|---|---|
| `--host INDIRIZZO` | Indirizzo su cui ascoltare. Predefinito `$GERBERSLAP_HOST`, altrimenti `127.0.0.1` (solo questo computer). In un container serve `0.0.0.0` (l'immagine lo imposta già). |
| `--port N` | Porta. Predefinita `$GERBERSLAP_PORT`, altrimenti 8800. |
| `--data CARTELLA` | Cartella dati. Predefinita: `$GERBERSLAP_DATA`, altrimenti `./data`. |
| `--install-template ID FILE` | Installa il template della stampante `ID` e termina (vedi sopra). |
| `--allowed-host NOME` | Un altro nome con cui il server può essere raggiunto (ripetibile; si sommano ai nomi di `$GERBERSLAP_ALLOWED_HOSTS`). Vedi [Rete e sicurezza](#rete-e-sicurezza). |
| `--no-library` | Spegne la libreria delle ricette (vedi sotto). Anche con `GERBERSLAP_NO_LIBRARY=1`. |
| `--dev-samples CARTELLA` | Per provare la pagina: offre gli zip della cartella e `/?sample=nome.zip` ne apre uno da solo. |
| `--dev-printers` | Per provare la pagina: aggiunge tre stampanti inventate (non scrivono nessun file). |

Le ultime due sono strumenti di sviluppo. Le opzioni con cui è partita l'app compaiono in fondo al pannello laterale della pagina (solo i nomi, mai cartelle o porte).

Variabili d'ambiente: sono il modo di configurare un container, ma valgono anche in locale. **Un'opzione scritta sulla riga di comando vince sempre sulla variabile**; una variabile vuota è come se non ci fosse.

| Variabile | Equivale a | Note |
|---|---|---|
| `GERBERSLAP_HOST` | `--host` | |
| `GERBERSLAP_PORT` | `--port` | Un valore che non è una porta (da 1 a 65535) ferma l'avvio con un messaggio chiaro. |
| `GERBERSLAP_ALLOWED_HOSTS` | `--allowed-host` | Più nomi separati da virgole; si sommano a quelli dati con l'opzione. |
| `GERBERSLAP_DATA` | `--data` | |
| `GERBERSLAP_NO_LIBRARY` | `--no-library` | `1`, `true`, `yes` o `on`. |

### La cartella dati

```
data/
  printers/<id stampante>/template.ctb    il template (si installa con --install-template)
  printers/<id stampante>/printer.json    facoltativo: impostazioni diverse da quelle predefinite del driver
  recipes/<id>.json                       una ricetta per file, con i suoi dosaggi dentro
```

È l'unica cosa che l'app conserva sul server, ed è quella da salvare (in Docker, il volume). I progetti degli utenti **non** ci stanno mai: vivono nel browser e nei file `.gslp` che si scaricano. Le scritture sono atomiche (un'interruzione lascia il file vecchio, mai uno a metà) e un file che non si legge viene segnalato, non ignorato né «riparato». Un solo processo per cartella dati.

La cartella è nel `.gitignore`: non va nel repository.

### Impostazioni della stampante (`printer.json`)

Facoltative: servono solo per cambiare i valori predefiniti del driver. Per la LD-002H:

| Impostazione | Predefinito | Significato |
|---|---|---|
| `park_z_mm` | 1,0 | Quota Z, in mm, a cui stanno tutti i layer: il carrello si sposta pochissimo. |
| `start_delay_s` | 0 | Secondi di attesa all'inizio, per appoggiare la basetta dopo lo zero di Z (0 = nessuna). |
| `cycle_s` | 8 | Stima della durata di un ciclo da 5 mm della stampante; serve solo a dimensionare l'attesa iniziale. |

```json
{
  "format": "gerberslap-printer",
  "schema_version": 1,
  "printer": { "settings": { "park_z_mm": 1.0, "start_delay_s": 0, "cycle_s": 8 } }
}
```

Un file illegibile o con valori non validi si segnala tra gli avvisi della stampante e blocca la generazione.

### Con e senza la libreria delle ricette (`--no-library`)

Per impostazione predefinita le ricette e i dosaggi stanno nella cartella dati e sono comuni a tutti i browser che usano quel server (è pensato per un home server di casa o di un laboratorio, dove più persone provano gli stessi resist).

Con `--no-library` il server **spegne soltanto la libreria**: le rotte delle ricette non esistono (rispondono 404) e la pagina non offre né il menu delle ricette né la loro gestione. Nel pannello Esposizione restano l'interruttore del resist e i tre valori (tempo totale, flash, riposo), che il browser ricorda per conto suo; la scala di calibrazione ricorda i suoi. Il file si genera allo stesso modo: la richiesta porta polarità e valori, il server non legge mai la libreria. I template delle stampanti restano nella cartella dati.

Attenzione: **non è una modalità «pubblica» e non rende il server sicuro per Internet.** Vedi la sezione seguente.

## Installazione con Docker

L'immagine gira su **arm64 e amd64** (provata su entrambe: gli stessi progetti danno file identici al byte), tiene la cartella dati in un **volume** e **non contiene nessun file `.ctb`**: il template si installa nel volume, una volta sola. Serve Docker (Docker Desktop su macOS e Windows, Docker Engine su Linux) e, per il metodo con Compose, il plugin `docker compose`.

**Che cosa c'è nell'immagine.** `python:3.14-slim`, le dipendenze di `requirements.txt`, il pacchetto `gerberslap/` (con `printers/`, le foto `icon.png` e il lettore e scrittore dei file di ogni driver) e il file `LICENSE` (la licenza accompagna ogni copia). Non ci sono: i file `.ctb`, `data/`, `tests/`, `docs/` né le cartelle `docs/` dei driver. Il contesto di build lo decide `.dockerignore`, che esclude tutto e lascia entrare solo quel che serve; un test (`tests/test_docker.py`) controlla che sia così.

**Come gira.** Come utente senza privilegi (uid e gid 10001, `gerberslap`), con `GERBERSLAP_HOST=0.0.0.0` (dentro il container ascolta su tutte le interfacce; chi lo raggiunge da fuori lo decide pubblicando la porta), `GERBERSLAP_DATA=/data` (il volume), porta 8800. L'`ENTRYPOINT` è `python -m gerberslap.web` e non c'è un `CMD`: le opzioni si scrivono dopo il nome dell'immagine, per esempio `docker run … gerberslap --no-library`. Un **controllo di salute** (`HEALTHCHECK`) interroga ogni 30 secondi `/api/info` sul proprio indirizzo: `docker ps` mostra `healthy`. Un solo container per volume (due processi sulla stessa cartella dati non sono supportati).

### Con Docker Compose (il modo consigliato)

Il file `compose.yaml` del repository costruisce l'immagine, crea il volume `gerberslap-data` e avvia l'app in modo che si riavvii da sola:

```bash
# costruire l'immagine (dalla cartella del progetto)
docker compose build

# una volta sola: installare il template della stampante nel volume
docker compose run --rm -v "$PWD/template:/in:ro" gerberslap --install-template ld002h /in/template.ctb

# avviare l'app
docker compose up -d
```

Poi si apre **http://127.0.0.1:8800**. Per il template, `$PWD/template` è una cartella che contiene il file `template.ctb` (la si monta in sola lettura); il comando esce con 0 se l'ha installato, e con 1 o 2 dicendo perché se no (vedi [Il template della stampante](#il-template-della-stampante)).

Come si gestisce:

```bash
docker compose logs -f        # i messaggi del server
docker compose ps             # lo stato, con "healthy" quando risponde
docker compose down           # ferma e toglie il container: il volume, con template e ricette, resta
docker compose down -v        # toglie anche il volume (cancella template e ricette)
```

Il file pubblica la porta **solo su questo computer** (`127.0.0.1`). La porta si cambia con la variabile `GERBERSLAP_PORT`, nell'ambiente o in un file `.env` accanto a `compose.yaml` (per esempio `GERBERSLAP_PORT=8812`): vale sia fuori sia dentro il container.

### Con docker run

```bash
docker build -t gerberslap .

# una volta sola: il template
docker run --rm -v gerberslap-data:/data -v "$PWD/template:/in:ro" \
    gerberslap --install-template ld002h /in/template.ctb

# avviare l'app (solo da questo computer)
docker run -d --name gerberslap --restart unless-stopped \
    -p 127.0.0.1:8800:8800 -v gerberslap-data:/data gerberslap
```

Il volume `gerberslap-data` contiene template e ricette: si salva con il normale backup dei volumi Docker. Per cambiare la porta di fuori basta `-p 127.0.0.1:9000:8800`; per cambiarla anche dentro si passa `-e GERBERSLAP_PORT=9000` e si pubblica la stessa porta.

### Raggiungerla da altri computer (un home server)

Si toglie `127.0.0.1:` dalla riga `ports` di `compose.yaml` (o da `-p`) e si dice al server con quale nome lo si raggiunge, altrimenti rifiuta le richieste con `bad_host`. Con Compose si toglie il commento alla riga `GERBERSLAP_ALLOWED_HOSTS` nel file:

```yaml
      GERBERSLAP_ALLOWED_HOSTS: "nas.local,192.168.1.20"
```

e con `docker run`:

```bash
docker run -d --name gerberslap --restart unless-stopped -p 8800:8800 -v gerberslap-data:/data \
    -e GERBERSLAP_ALLOWED_HOSTS=nas.local,192.168.1.20 gerberslap
```

Vale tutto quello che segue su rete e sicurezza: l'app non ha autenticazione.

### Una cartella del computer al posto del volume

Si può montare una cartella (`-v "$PWD/data:/data"`) per vedere i file di ricette e template. Il container gira come utente 10001: la cartella deve poterla scrivere (su Linux `sudo chown -R 10001:10001 data`; con Docker Desktop su macOS di solito non serve). Se non può scriverla, `--install-template` risponde con un errore di permessi e l'app non riesce a salvare le ricette.

## Rete e sicurezza

L'app è pensata per un uso **locale o in una rete fidata** (il computer di chi la usa, o un home server in casa). Per impostazione predefinita ascolta solo su `127.0.0.1`.

Che cosa fa il server per proteggersi, anche quando ascolta solo in locale (perché qualunque programma o pagina sul computer può raggiungere una porta locale):

- **Controllo dell'intestazione `Host`**: accetta solo `localhost`, `127.0.0.1`, `::1` e i nomi dati con `--allowed-host`. Protegge dagli attacchi di tipo DNS rebinding.
- **Richieste che modificano qualcosa solo dalla pagina stessa**: ogni richiesta che non sia di sola lettura (`POST`, `PATCH`, `DELETE`) con un `Origin` diverso dal server, o con `Sec-Fetch-Site` diverso da `same-origin`, si rifiuta (un altro sito aperto nel browser non può usare l'app).
- **Niente cache** delle risposte (tranne le foto delle stampanti) e `X-Content-Type-Options: nosniff`.
- **Zip e file di progetto trattati come input ostile**: uno zip caricato può pesare al massimo 64 MiB; dentro, al massimo 500 file, 64 MiB per file e 200 MiB in totale; i nomi sono filtrati (le voci di macOS e i file nascosti si scartano); progetti `.gslp` riletti e verificati voce per voce; i file ricevuti stanno solo in memoria.
- **Nessun percorso del server nelle risposte**: gli errori dicono un codice, non dove sta un file.

Che cosa **non** c'è, e perché l'app **non va esposta su Internet**: autenticazione, utenti e sessioni, limiti di richieste e quote per persona, e una memoria dei file Gerber che è unica e condivisa da tutti (1 GiB in memoria). Inoltre il server genera file a partire da un template `.ctb` che non si può distribuire (vedi sopra): prima di un uso pubblico la questione va sciolta. `--no-library` spegne la libreria e basta: per questo non si chiama `--public`.

Se la si raggiunge da altri computer, la rete deve essere fidata. Per un accesso da fuori casa si usa una VPN, non una porta aperta.

**Ospitarla su un server pubblico** è a proprio rischio e pericolo: il progetto non lo prevede né lo supporta, per i motivi appena visti. Chi lo fa con una versione modificata deve, per la licenza AGPL-3.0, mettere a disposizione degli utenti il sorgente della sua versione: il link «Codice sorgente e licenza» nella pagina Aiuto punta al repository originale e va cambiato (`gerberslap/web/static/index.html`, elemento con `id="source-link"`).

## Aggiornare

Si aggiorna il codice (`git pull`) e le dipendenze (`.venv/bin/pip install -r requirements.txt`) e si riavvia; con Docker Compose, `docker compose build && docker compose up -d` (il volume resta com'è). La cartella dati resta com'è. I file `.gslp` portano un numero di versione: uno più vecchio si migra aprendolo, uno più nuovo di quello che l'app conosce si rifiuta con un messaggio chiaro. Lo stesso vale per i file della cartella dati (che oggi hanno una sola versione). Dopo una modifica al codice Python il server va riavviato (i file della pagina no: basta ricaricarla).

## Problemi frequenti

| Sintomo | Causa e rimedio |
|---|---|
| `Address already in use` all'avvio | La porta 8800 è occupata (un altro avvio dell'app?). Si ferma l'altro oppure si usa `--port`. |
| Il browser mostra «bad_host» (403) | Si raggiunge il server con un nome che non conosce: `--allowed-host nome` (in Docker, `GERBERSLAP_ALLOWED_HOSTS`). |
| L'icona degli avvisi è rossa e «Genera» è spento: *manca il file template* | Il template non è installato nella cartella dati che il server sta usando (controlla `--data` o `GERBERSLAP_DATA`: il comando di installazione deve usare la stessa). Dopo averlo installato basta ricaricare la pagina: il server rilegge il template a ogni richiesta, non serve riavviarlo. |
| Lo stesso avviso, ma *il file template non è utilizzabile (motivo)* | Il template è stato rifiutato dal driver. I motivi: *non è un file del formato della stampante*; *la versione del formato non è quella attesa* (serve la v5); *il file è danneggiato* (CRC); *la risoluzione non è quella dello schermo* (serve la LD-002H, 1620 × 2560); *non contiene nessun layer*; *i dati dei layer non si leggono*; *la distanza di sollevamento è 0* (rifarlo con 0,001 mm); *la velocità di sollevamento o di ritorno non è valida*. |
| Avviso: *il movimento copiato dal template solleva il carrello di X mm* | Il template ha una distanza di sollevamento grande (oltre 1 mm): ogni flash diventa lento. Si consiglia 0,001 mm; si rifà il template. |
| Avviso sul file `printer.json` | Il file delle impostazioni della stampante non si legge o ha valori non validi (vedi sopra). |
| Docker: `bind: address already in use` | La porta 8800 del computer è occupata: si cambia con `GERBERSLAP_PORT` (Compose) o con `-p 127.0.0.1:9000:8800` (`docker run`). |
| Docker: `docker ps` dice `unhealthy`, o la pagina non si apre | Si guardano i messaggi (`docker compose logs`). Il controllo interroga il server dall'interno, quindi un `unhealthy` vuol dire che il server non è partito: di solito una porta o una variabile d'ambiente sbagliata (`GERBERSLAP_PORT must be a number…`). |
| Docker: `--install-template` dà un errore di permessi | La cartella dati non è scrivibile dall'utente 10001: succede solo montando una cartella del computer al posto del volume (vedi sopra). |
| Docker: la pagina dice che il template manca, anche se l'ho installato | Il template è finito in un altro volume: l'installazione e l'app devono usare lo stesso (`gerberslap-data`, oppure la stessa cartella montata). |
| Uno zip viene rifiutato | I vecchi export di EAGLE (prima del formato di Gerber di EAGLE 9) si rifiutano di proposito; uno zip senza file di rame o non riconoscibile dà un messaggio che lo dice. |
| «Un flash sotto il minimo» | Il flash è `tempo totale / numero di flash`: sotto 1 s non è mai stato provato sulla stampante e il file non si genera. Oltre 20 s si genera con un avviso (non provato). |
| Dopo il riavvio del server la pagina dice che manca un file | Il server tiene i Gerber solo in memoria. Se il progetto è stato salvato (copia di lavoro nel browser) la pagina li ridà da sola; altrimenti si riapre lo zip. |
| I progetti salvati «spariscono» | La copia di lavoro sta nel browser e dipende dall'indirizzo e dal profilo: si usa sempre lo stesso indirizzo e lo stesso browser. Per portare un progetto altrove si scarica il file `.gslp` (che contiene anche i Gerber). |

## Eseguire i test

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Circa 1160 test in un paio di minuti. Si saltano da soli i test che richiedono ciò che manca: i file di terzi in `experiments/fase1/external/` e `experiments/fase2/external/` (non sono nel repository), il template `samples/speedCube.ctb` (idem; i `.ctb` non si pubblicano) e Node.js (per la logica della pagina). Il controllo di sintassi dei moduli JavaScript usa `node --input-type=module --check` con il file su stdin: `node --check file.js` non basta (con Node 26 accetta moduli con errori).

Altri controlli utili sui file generati: `python3 gerberslap/printers/ld002h/ctbio.py info file.ctb` (intestazione e CRC) e `python3 gerberslap/printers/ld002h/ctbio.py layer file.ctb N out.png` (estrae un layer come immagine).
