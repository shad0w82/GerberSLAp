---
icon: material/tune-variant
---

# Configurazione

Come si avvia l'app, dove tiene i suoi dati e che cosa fa il server per proteggersi. Le opzioni valgono in tutti i modi di installazione; per Docker, le variabili d'ambiente sono il modo normale di configurarle.

## Opzioni di avvio

```bash
python -m gerberslap.web [opzioni]
```

| Opzione | Significato |
|---|---|
| `--host INDIRIZZO` | Indirizzo su cui ascoltare. Predefinito `$GERBERSLAP_HOST`, altrimenti `127.0.0.1` (solo questo computer). In un container serve `0.0.0.0`: l'immagine lo imposta già. |
| `--port N` | Porta. Predefinita `$GERBERSLAP_PORT`, altrimenti 8800. |
| `--data CARTELLA` | Cartella dati. Predefinita `$GERBERSLAP_DATA`, altrimenti `./data`. |
| `--install-template ID FILE` | Installa il [template](requirements.md#il-template-della-stampante) della stampante `ID` e termina. |
| `--allowed-host NOME` | Un altro nome con cui il server può essere raggiunto. Si può ripetere e si somma ai nomi di `$GERBERSLAP_ALLOWED_HOSTS`. Vedi [Rete e sicurezza](#rete-e-sicurezza). |
| `--no-library` | Spegne la libreria delle ricette ([vedi sotto](#con-e-senza-la-libreria-delle-ricette)). Anche con `GERBERSLAP_NO_LIBRARY=1`. |
| `--dev-samples CARTELLA` | Per provare la pagina: offre gli zip della cartella, e `/?sample=nome.zip` ne apre uno da solo. |
| `--dev-printers` | Per provare la pagina: aggiunge tre stampanti inventate, che non scrivono nessun file. |

Le ultime due sono strumenti di sviluppo. Le opzioni con cui l'app è partita compaiono in fondo al pannello laterale della pagina (la SideStatusBar): solo i nomi, mai cartelle o porte.

## Variabili d'ambiente

Sono il modo di configurare un container, ma valgono anche in locale. **Un'opzione scritta sulla riga di comando vince sempre sulla variabile**; una variabile vuota è come se non ci fosse.

| Variabile | Equivale a | Note |
|---|---|---|
| `GERBERSLAP_HOST` | `--host` | |
| `GERBERSLAP_PORT` | `--port` | Un valore che non è una porta (da 1 a 65535) ferma l'avvio con un messaggio chiaro. |
| `GERBERSLAP_ALLOWED_HOSTS` | `--allowed-host` | Più nomi separati da virgole, che si sommano a quelli dati con l'opzione. |
| `GERBERSLAP_DATA` | `--data` | |
| `GERBERSLAP_NO_LIBRARY` | `--no-library` | `1`, `true`, `yes` o `on`. |

## La cartella dati

```text
data/
  printers/<id stampante>/template.ctb    il template (si installa con --install-template)
  printers/<id stampante>/printer.json    facoltativo: impostazioni diverse da quelle predefinite del driver
  recipes/<id>.json                       una ricetta per file, con i suoi dosaggi dentro
```

È l'unica cosa che l'app conserva sul server, ed è quella da salvare (in Docker, il volume). I progetti degli utenti **non** ci stanno mai: vivono nel browser e nei file `.gslp` che si scaricano.

Le scritture sono atomiche: un'interruzione lascia il file vecchio, mai uno a metà. Un file che non si legge viene segnalato, non ignorato né «riparato». Un solo processo per cartella dati. La cartella è nel `.gitignore`: non va nel repository.

## Impostazioni della stampante

Il file `printer.json` è facoltativo e serve solo a cambiare i valori predefiniti del driver. Per la LD-002H:

| Impostazione | Predefinito | Significato |
|---|---|---|
| `park_z_mm` | 1,0 | Quota Z, in mm, a cui stanno tutti i layer: il carrello si sposta pochissimo. |
| `start_delay_s` | 0 | Secondi di attesa all'inizio, per appoggiare la basetta dopo lo zero di Z (0 = nessuna attesa). |
| `cycle_s` | 8 | Stima della durata di un ciclo da 5 mm della stampante: serve solo a dimensionare l'attesa iniziale. |

```json
{
  "format": "gerberslap-printer",
  "schema_version": 1,
  "printer": { "settings": { "park_z_mm": 1.0, "start_delay_s": 0, "cycle_s": 8 } }
}
```

Un file illeggibile o con valori non validi si segnala tra gli avvisi della stampante e blocca la generazione.

## Con e senza la libreria delle ricette

Per impostazione predefinita le ricette e i dosaggi stanno nella cartella dati e sono comuni a tutti i browser che usano quel server. È pensato per un home server di casa o di laboratorio, dove più persone provano gli stessi resist.

Con `--no-library` il server **spegne soltanto la libreria**:

- le rotte delle ricette non esistono (rispondono 404) e la pagina non offre né il menu delle ricette né la loro gestione;
- nel pannello Esposizione restano l'interruttore del resist e i tre valori (tempo totale, flash, riposo), che il browser ricorda per conto suo; la scala di calibrazione ricorda i suoi;
- il file si genera allo stesso modo: la richiesta porta polarità e valori, e il server non legge mai la libreria;
- i template delle stampanti restano nella cartella dati.

!!! warning "Non è una modalità «pubblica»"
    `--no-library` non rende il server sicuro per Internet. Vedi la sezione seguente.

## Rete e sicurezza

L'app è pensata per un uso **locale o in una rete fidata**: il computer di chi la usa, oppure un home server in casa. Per impostazione predefinita ascolta solo su `127.0.0.1`.

### Che cosa fa il server per proteggersi

Anche quando ascolta solo in locale, perché qualunque programma o pagina sul computer può raggiungere una porta locale:

- **Controllo dell'intestazione `Host`.** Accetta solo `localhost`, `127.0.0.1`, `::1` e i nomi dati con `--allowed-host`. Protegge dagli attacchi di tipo DNS rebinding.
- **Richieste che modificano qualcosa solo dalla pagina stessa.** Ogni richiesta che non sia di sola lettura (`POST`, `PATCH`, `DELETE`) con un `Origin` diverso dal server, o con `Sec-Fetch-Site` diverso da `same-origin`, si rifiuta: un altro sito aperto nel browser non può usare l'app.
- **Niente cache** delle risposte, tranne le foto delle stampanti, e `X-Content-Type-Options: nosniff`.
- **Zip e file di progetto trattati come input ostile.** Uno zip caricato pesa al massimo 64 MiB; dentro ci sono al massimo 500 file, 64 MiB per file e 200 MiB in totale. I nomi sono filtrati (le voci di macOS e i file nascosti si scartano), i progetti `.gslp` sono riletti e verificati voce per voce e i file ricevuti stanno solo in memoria.
- **Nessun percorso del server nelle risposte.** Gli errori dicono un codice, non dove sta un file.

### Che cosa non c'è

Mancano autenticazione, utenti e sessioni, limiti di richieste e quote per persona. La memoria dei file Gerber è unica e condivisa da tutti (1 GiB in memoria). Inoltre il server genera file a partire da un template `.ctb` che non si può distribuire, e prima di un uso pubblico la questione va sciolta. Per questo l'app **non va esposta su Internet** e `--no-library` non si chiama `--public`.

Se la si raggiunge da altri computer, la rete deve essere fidata. Per accedere da fuori casa si usa una VPN, non una porta aperta.

!!! danger "Ospitarla su un server pubblico è a proprio rischio e pericolo"
    Il progetto non lo prevede né lo supporta. Chi lo fa con una versione modificata deve, per la licenza AGPL-3.0, mettere a disposizione degli utenti il sorgente della sua versione: il link «Codice sorgente e licenza» nella pagina Aiuto punta al repository originale e va cambiato (`gerberslap/web/static/index.html`, elemento con `id="source-link"`).
