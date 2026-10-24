---
icon: material/clipboard-check-outline
---

# Requisiti e template

Per installare GerberSLAp servono pochi requisiti e un file che l'app non può portarsi dietro: il **template** della stampante. Questa pagina spiega entrambe le cose; poi si sceglie fra installazione nativa e Docker in [Installare l'app](install.md).

## Requisiti

| Requisito | Dettaglio |
|---|---|
| **Python** | 3.12 o più recente (lo richiede la libreria `gerbonara`); provato con 3.14. Serve solo per l'installazione nativa: l'immagine Docker lo contiene già. |
| **Sistema** | Provato su macOS (Apple Silicon). Il codice è fatto solo di Python e JavaScript, senza parti specifiche del sistema: su Linux valgono gli stessi comandi. |
| **Browser** | Uno recente; Chrome è quello provato. La pagina usa IndexedDB e Web Locks per la copia di lavoro dei progetti. |
| **Template** | Un file `.ctb` fatto con ChiTuBox, come spiegato sotto. Non è nel repository. |
| **Node.js** | Solo per eseguire i test della logica della pagina: facoltativo. |

Le dipendenze Python sono fissate in `requirements.txt`.

## Il template della stampante

L'app non scrive il file `.ctb` da zero: parte da un file fatto con ChiTuBox, il **template**, e ne cambia solo le immagini dei layer, il tempo di esposizione e la quota Z. Tutto il resto lo copia così com'è: le distanze e le velocità di sollevamento, i secondi stadi, i riposi e i campi del formato che nessuno documenta. Sono i valori che la stampante ha già mostrato di accettare, e inventarli può far muovere il carrello in modo imprevisto. Il template è anche il modo in cui si sceglie come si muove la stampante durante l'esposizione.

!!! info "Perché non è nel repository"
    Un file `.ctb` contiene l'avviso di copyright di CBD Technology, e lo stesso avviso finisce nei file che l'app genera. Per questo né il template né i file generati stanno nel repository o in un'immagine Docker: ognuno prepara il suo e lo installa nella cartella dati.

### Come si prepara

In ChiTuBox, scegliendo la stampante *Creality LD-002H*, si affetta un oggetto qualunque (un cubo basta) con queste impostazioni e si salva il file `.ctb`:

- *Waiting Mode*: «Resting time», con i tre tempi di riposo a 0;
- distanza di sollevamento del bottom e distanza di sollevamento normale: **0,001 mm** (e 0 il secondo valore, quello dopo il «+»);
- le quattro velocità (sollevamento e ritorno, bottom e normali): **500 mm/min** (e 0 i secondi valori);
- un solo layer bottom.

!!! danger "Mai una distanza di sollevamento 0"
    La stampante la sostituirebbe con un ciclo da 5 mm. L'app rifiuta un template che la usa.

Per una stampante diversa dalla LD-002H il principio è lo stesso: lo spiega [Il driver di una stampante](../development/new-printer/driver.md#il-template).

### Come si installa

Una volta sola, dalla cartella del progetto:

```bash
.venv/bin/python -m gerberslap.web --install-template ld002h /percorso/del/template.ctb
```

Il comando controlla il file con il driver della stampante prima di scrivere qualsiasi cosa, lo copia in `<cartella dati>/printers/ld002h/template.ctb` e termina senza avviare il server. Esce con 0 (installato), 1 (file o cartella rifiutati: dice perché) o 2 (non esiste una stampante con quell'id). Rilanciarlo sostituisce il template. Con Docker lo stesso comando si lancia dentro il container: vedi [Installazione con Docker](install.md#installazione-con-docker).

Quando l'app è avviata, nelle Impostazioni la card della stampante dice **Pronta** e il pulsante «Genera» si può accendere. Senza template l'icona degli avvisi è rossa e il pulsante resta spento, con il motivo scritto sotto.
