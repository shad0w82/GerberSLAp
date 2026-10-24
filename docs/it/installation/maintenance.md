---
icon: material/wrench-outline
---

# Aggiornare e problemi

## Aggiornare

Si aggiorna il codice e le dipendenze e si riavvia l'app:

=== "Installazione nativa"

    ```bash
    git pull
    .venv/bin/pip install -r requirements.txt
    ```

    Poi si riavvia il server. Dopo una modifica al codice Python il riavvio serve sempre; per i file della pagina basta ricaricarla.

=== "Docker Compose"

    ```bash
    git pull
    docker compose build && docker compose up -d
    ```

    Il volume resta com'è, con template e ricette.

La cartella dati resta com'è. I file `.gslp` portano un numero di versione: uno più vecchio si migra aprendolo, uno più nuovo di quello che l'app conosce si rifiuta con un messaggio chiaro. Lo stesso vale per i file della cartella dati, che oggi hanno una sola versione.

## Problemi frequenti

I problemi che si incontrano usando l'app, per esempio uno zip rifiutato o un avviso sull'esposizione, sono in [Avvisi e problemi](../usage/troubleshooting.md). Qui ci sono quelli di installazione e avvio.

### Avvio e rete

| Sintomo | Causa e rimedio |
|---|---|
| `Address already in use` all'avvio | La porta 8800 è occupata, forse da un altro avvio dell'app. Si ferma l'altro, oppure si usa `--port`. |
| Il browser mostra «bad_host» (403) | Si raggiunge il server con un nome che non conosce: `--allowed-host nome` (in Docker, `GERBERSLAP_ALLOWED_HOSTS`). |

### Template e impostazioni della stampante

| Sintomo | Causa e rimedio |
|---|---|
| Icona rossa e «Genera» spento: *manca il template* | Il template non è installato nella cartella dati che il server sta usando. Si controlla `--data` o `GERBERSLAP_DATA`: il comando di installazione deve usare la stessa cartella. Dopo averlo installato basta ricaricare la pagina: il server rilegge il template a ogni richiesta, non serve riavviarlo. |
| Avviso: *il template non è utilizzabile (motivo)* | Il driver ha rifiutato il template. I motivi: *non è un file del formato della stampante*; *la versione del formato non è quella attesa* (serve la v5); *il file è danneggiato* (CRC); *la risoluzione non è quella dello schermo* (serve la LD-002H, 1620 × 2560); *non contiene nessun layer*; *i dati dei layer non si leggono*; *la distanza di sollevamento è 0* (va rifatto con 0,001 mm); *la velocità di sollevamento o di ritorno non è valida*. |
| Avviso: *il movimento solleva il carrello di X mm* | Il template ha una distanza di sollevamento grande (oltre 1 mm) e ogni flash diventa lento. Si consiglia 0,001 mm: si rifà il template. |
| Avviso sul file `printer.json` | Il file delle [impostazioni della stampante](configuration.md#impostazioni-della-stampante) non si legge o ha valori non validi. |

### Docker

| Sintomo | Causa e rimedio |
|---|---|
| `bind: address already in use` | La porta 8800 del computer è occupata: si cambia con `GERBERSLAP_PORT` (Compose) o con `-p 127.0.0.1:9000:8800` (`docker run`). |
| `unhealthy`, o la pagina non si apre | Si guardano i messaggi con `docker compose logs`. Il controllo interroga il server dall'interno, quindi `unhealthy` vuol dire che il server non è partito: di solito una porta o una variabile d'ambiente sbagliata (`GERBERSLAP_PORT must be a number…`). |
| `--install-template` dà un errore di permessi | La cartella dati non è scrivibile dall'utente 10001. Succede solo montando una cartella del computer al posto del volume: vedi [Una cartella del computer al posto del volume](install.md#una-cartella-del-computer-al-posto-del-volume). |
| Template mancante, anche se l'ho installato | Il template è finito in un altro volume: l'installazione e l'app devono usare lo stesso (`gerberslap-data`, oppure la stessa cartella montata). |
