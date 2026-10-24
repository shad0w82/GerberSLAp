---
icon: material/book-open-variant
---

# Introduzione e concetti

GerberSLAp trasforma i file Gerber di un circuito stampato nel **file di stampa** di una stampante a resina con schermo LCD monocromatico e luce UV a 405 nm. La stampante diventa così un'**unità di esposizione** per basette di rame **presensibilizzate**, cioè già ricoperte di resist fotosensibile.

Questo capitolo spiega come funziona in breve, che cosa serve e quali sono le parole che il resto del manuale usa: piano, scheda, polarità, esposizione, ricetta, dosaggio.

## Come funziona

Il lavoro si svolge in una pagina web: si apre lo zip dei Gerber, si posiziona la scheda su un piano che rappresenta lo schermo, si sceglie il resist e l'esposizione e si ottiene un file da copiare sulla chiavetta USB della stampante, che non ha rete.

La stampante «stampa» **un solo layer**, per tutto il tempo scelto. Sullo schermo LCD i pixel bianchi lasciano passare la luce UV e quelli neri la fermano: dove la luce arriva, il resist della basetta si impressiona. Poi la basetta si sviluppa e si incide, e resta il disegno del circuito.

Il file di stampa non si scrive da zero: l'app parte da un file fatto una volta con ChiTuBox, il **template** della stampante, e ne cambia le immagini e il tempo di esposizione. Tutto il resto, come il movimento del carrello, lo copia dal template.

## Cosa serve

- **Una stampante supportata.** Oggi è supportata la Creality LD-002H (LCD mono 2K). Altre stampanti si aggiungono con un driver, senza modificare il resto dell'app.
- **Il template della stampante**: un file `.ctb` fatto con ChiTuBox e installato una volta. Non fa parte dell'app perché contiene l'avviso di copyright del produttore. Come prepararlo lo spiega [Requisiti e template](../installation/requirements.md#il-template-della-stampante).
- **L'app in esecuzione**, in locale o in un container Docker: vedi [Installare l'app](../installation/install.md).
- **Un browser recente.** Chrome è quello provato.
- **I Gerber del circuito**, in uno zip. KiCad, Altium ed EAGLE 9 sono riconosciuti da soli; i vecchi export di EAGLE si rifiutano.
- **Basette presensibilizzate**, e quanto serve per svilupparle e inciderle. Questo manuale non tratta quella parte.

## I concetti

### Piano

Il **piano** è lo schermo LCD visto dall'alto, con i righelli in millimetri. Sulla LD-002H misura 130,56 × 82,62 mm e ha 2560 × 1620 pixel, ciascuno largo 0,051 mm. Tutto si posiziona sul piano, e ciò che resta fuori non viene esposto.

### Scheda e layer

Una **scheda** è uno zip di Gerber aggiunto al piano. Ha una posizione, una rotazione e, se serve, lo specchio. Sul piano si possono avere più schede, anche copie della stessa. Le schede si aggiungono e si gestiscono nella sezione [Schede](boards.md); la loro posizione si sceglie in [Posizione](placement.md).

I file dello zip sono i **layer**, e l'app riconosce da sola che cos'è ciascuno: **rame**, **maschera** di saldatura, **serigrafia**, **contorno** e **fori**. Ogni layer si accende o si spegne e ha uno stato che dice se è stato letto bene. Il file di stampa espone i layer accesi in quel momento.

### Specchio

Se la basetta si appoggia con il rame verso lo schermo, l'immagine va **specchiata** da sinistra a destra. Lo specchio è una scelta dell'utente sulla scheda posizionata e si vede subito nell'anteprima.

### Polarità del resist

È la proprietà del resist che decide dove deve passare la luce:

- con il resist **positivo** la luce passa dove **non** c'è rame;
- con il resist **negativo** la luce passa dove **c'è** rame.

Dipende dal prodotto che si usa. Il selettore del resist mostra il positivo in bianco e il negativo in nero.

### Esposizione

L'**esposizione** si descrive con tre valori:

| Valore | Che cos'è |
|---|---|
| **Tempo totale** | I secondi in cui la luce passa in tutto. È la «dose». |
| **Flash** | In quanti impulsi si divide il tempo totale: un flash da *T* secondi, oppure *N* flash da *T/N*. |
| **Riposo** | I secondi di buio tra un flash e l'altro. Serve solo a far raffreddare LCD e LED. |

I tre valori si scelgono nel pannello [Esposizione](exposure.md).

### Ricetta e dosaggio

Una **ricetta** è ciò che si fa con un resist: ha un nome, la polarità (che non si cambia dopo averla creata), il resist, lo sviluppo e delle note. Una ricetta non dice nulla sulla stampante.

Un **dosaggio** sono i tre valori di esposizione (tempo totale, flash, riposo) trovati provando, per **una stampante**, con la data e una nota facoltativa. Una ricetta può avere più dosaggi: sono alternative che restano tutte valide, per esempio per piste fini o per grandi piani di massa.

Le ricette stanno sul server dell'app, nella sua cartella dati, e valgono per tutti i browser che lo usano. Con l'opzione `--no-library` la libreria è spenta e restano i tre valori scritti a mano ([Configurazione](../installation/configuration.md#con-e-senza-la-libreria-delle-ricette)).

### Scala di calibrazione

La **scala di calibrazione** è un file di prova con strisce esposte per tempi crescenti, che si usa per trovare il tempo giusto di un resist. Il risultato si salva come dosaggio in una ricetta. Si usa nella pagina [Scala di calibrazione](calibration-ladder.md).

### Stampante e template

La **stampante** è il tipo di macchina (il suo driver), non l'unità con il suo numero di serie. Il **template** è il file da cui l'app copia il movimento della stampante, come si è visto sopra.

### Progetto

Un **progetto** è l'insieme delle schede con le loro posizioni, l'esposizione e la ricetta scelta. Si salva nel browser, come copia di lavoro, e si scarica come file `.gslp`, che contiene anche i Gerber ([Progetti](projects.md)). **Il server non conserva i progetti.**

## Il flusso di lavoro

1. **Aggiungere la scheda**: si trascina lo zip dei Gerber sulla pagina ([Schede](boards.md)).
2. **Posizionarla** sul piano, con rotazione e specchio ([Posizione](placement.md)).
3. **Scegliere resist ed esposizione**, a mano oppure da una ricetta ([Esposizione](exposure.md)).
4. **La prima volta con un resist nuovo**, trovare il tempo giusto con la scala di calibrazione e salvarlo come dosaggio ([Scala di calibrazione](calibration-ladder.md)).
5. **Generare il file di stampa** ([Esposizione](exposure.md)).
6. **Copiarlo sulla chiavetta USB** e avviare la stampa dalla stampante ([Dal file alla stampante](printing.md)).
7. **Sviluppare e incidere** la basetta, fuori da GerberSLAp.

## Limiti attuali

- È una versione **a singola faccia**: un file espone i layer accesi in quel momento. L'allineamento tra esposizioni successive della stessa basetta, per esempio per la doppia faccia, non è gestito.
- I **piani interni negativi** non sono supportati.
- È supportata **una sola stampante**, la Creality LD-002H.

!!! warning "Che cosa non è stato provato"
    Il file della scala di calibrazione, con le sue prove e la scritta del tempo su ogni striscia, **non è ancora stato provato sulla stampante**. Il formato del file, l'orientamento dell'immagine e il movimento sono invece stati verificati sulla stampante con file di prova; resta da misurare con il calibro una scheda reale.

## Come leggere il manuale

- I nomi come **MenuBar**, **SidePanel** o **CadWindow** indicano le zone dell'interfaccia. Il [Tour dell'interfaccia](interface.md) le mostra una per una.
- I pulsanti che compiono un'azione hanno solo un'icona: il loro nome compare in un suggerimento quando ci si ferma sopra con il mouse.
- I riquadri colorati segnalano note, avvisi e pericoli; quelli rossi sono da non trascurare.

Il prossimo capitolo, [Primi passi](first-steps.md), accompagna la preparazione del primo file, dallo zip all'esposizione.
