---
icon: material/download-circle-outline
---

# Installare l'app

GerberSLAp si installa in due modi: **in modo nativo**, con Python sul proprio computer, oppure **con Docker**. In tutti e due i casi serve il [template della stampante](requirements.md#il-template-della-stampante), da installare una volta sola.

## Installazione nativa

```bash
git clone https://github.com/shad0w82/GerberSLAp.git GerberSLAp
cd GerberSLAp
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Poi si [installa il template](requirements.md#come-si-installa) e si avvia l'app:

```bash
.venv/bin/python -m gerberslap.web
```

Il server ascolta su **http://127.0.0.1:8800**, cioè solo su questo computer, e all'avvio stampa la cartella dati in uso e se la libreria delle ricette è accesa. Si apre quell'indirizzo nel browser e si lavora; per fermare il server si preme `Ctrl+C`.

- **Si avvia dalla cartella del progetto.** Il pacchetto `gerberslap` si trova lì, e la cartella dati predefinita, `./data`, è relativa a dove si lancia il comando.
- **Il server è un processo normale**, che si chiude con il terminale. Per tenerlo sempre acceso si usa il gestore dei servizi del sistema (launchd, systemd) oppure Docker.

!!! warning "Si usa sempre lo stesso indirizzo nel browser"
    La copia di lavoro dei progetti sta nel browser e dipende dall'indirizzo: `http://127.0.0.1:8800` e `http://localhost:8800` sono per lui due siti diversi, con due copie diverse.

## Installazione con Docker

L'immagine gira su **arm64 e amd64** (provata su entrambe: gli stessi progetti danno file identici al byte), tiene la cartella dati in un **volume** e **non contiene nessun file `.ctb`**: il template si installa nel volume, una volta sola. Servono Docker (Docker Desktop su macOS e Windows, Docker Engine su Linux) e, per il metodo con Compose, il plugin `docker compose`.

??? info "Che cosa c'è nell'immagine e come gira"
    **Contenuto.** `python:3.14-slim`, le dipendenze di `requirements.txt`, il pacchetto `gerberslap/` (con i driver, le foto delle stampanti e il lettore e scrittore dei file di ogni driver) e il file `LICENSE`. Non ci sono i file `.ctb`, `data/`, `tests/`, `docs/` né le cartelle `docs/` dei driver. Il contesto di build lo decide `.dockerignore`, che esclude tutto e lascia entrare solo ciò che serve; un test (`tests/test_docker.py`) controlla che sia così.

    **Esecuzione.** Come utente senza privilegi (uid e gid 10001, `gerberslap`), con `GERBERSLAP_HOST=0.0.0.0` (dentro il container ascolta su tutte le interfacce; chi lo raggiunge da fuori lo decide pubblicando la porta), `GERBERSLAP_DATA=/data` (il volume) e porta 8800. L'`ENTRYPOINT` è `python -m gerberslap.web` e non c'è un `CMD`: le opzioni si scrivono dopo il nome dell'immagine, per esempio `docker run … gerberslap --no-library`. Un controllo di salute (`HEALTHCHECK`) interroga ogni 30 secondi `/api/info`: `docker ps` mostra `healthy`. Un solo container per volume: due processi sulla stessa cartella dati non sono supportati.

### Con Docker Compose

È il modo consigliato. Il file `compose.yaml` del repository costruisce l'immagine, crea il volume `gerberslap-data` e avvia l'app in modo che si riavvii da sola:

```bash
# costruire l'immagine (dalla cartella del progetto)
docker compose build

# una volta sola: installare il template della stampante nel volume
docker compose run --rm -v "$PWD/template:/in:ro" gerberslap --install-template ld002h /in/template.ctb

# avviare l'app
docker compose up -d
```

Poi si apre **http://127.0.0.1:8800**. Per il template, `$PWD/template` è una cartella che contiene il file `template.ctb`, montata in sola lettura. Il comando esce con 0 se l'ha installato, e con 1 o 2, dicendo perché, se no.

Per gestire l'app:

```bash
docker compose logs -f        # i messaggi del server
docker compose ps             # lo stato, con "healthy" quando risponde
docker compose down           # ferma e toglie il container: il volume, con template e ricette, resta
docker compose down -v        # toglie anche il volume (cancella template e ricette)
```

Il file pubblica la porta **solo su questo computer** (`127.0.0.1`). Si cambia con la variabile `GERBERSLAP_PORT`, nell'ambiente o in un file `.env` accanto a `compose.yaml` (per esempio `GERBERSLAP_PORT=8812`): vale sia fuori sia dentro il container.

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

Il volume `gerberslap-data` contiene template e ricette e si salva con il normale backup dei volumi Docker. Per cambiare la porta di fuori basta `-p 127.0.0.1:9000:8800`; per cambiarla anche dentro si passa `-e GERBERSLAP_PORT=9000` e si pubblica la stessa porta.

### Raggiungerla da altri computer

Per usare l'app da un altro computer, per esempio con un home server, si toglie `127.0.0.1:` dalla riga `ports` di `compose.yaml` (o da `-p`) e si dice al server con quale nome lo si raggiunge, altrimenti rifiuta le richieste con `bad_host`. Con Compose si toglie il commento alla riga `GERBERSLAP_ALLOWED_HOSTS` nel file:

```yaml
      GERBERSLAP_ALLOWED_HOSTS: "nas.local,192.168.1.20"
```

Con `docker run` si passa la variabile:

```bash
docker run -d --name gerberslap --restart unless-stopped -p 8800:8800 -v gerberslap-data:/data \
    -e GERBERSLAP_ALLOWED_HOSTS=nas.local,192.168.1.20 gerberslap
```

!!! warning "L'app non ha autenticazione"
    Vale tutto quello che si legge in [Rete e sicurezza](configuration.md#rete-e-sicurezza): la rete deve essere fidata.

### Una cartella del computer al posto del volume

Si può montare una cartella (`-v "$PWD/data:/data"`) per vedere i file di ricette e template. Il container gira come utente 10001, quindi la cartella deve poterla scrivere: su Linux si usa `sudo chown -R 10001:10001 data`, mentre con Docker Desktop su macOS di solito non serve. Se la cartella non è scrivibile, `--install-template` risponde con un errore di permessi e l'app non riesce a salvare le ricette.
