---
hide:
  - navigation
  - toc
---

# GerberSLAp

**Dai file Gerber al file di stampa.** GerberSLAp usa una stampante a resina con schermo LCD monocromatico e luce UV a 405 nm come unità di esposizione per circuiti stampati con rame presensibilizzato: si apre lo zip dei Gerber, si posiziona la scheda sul piano che rappresenta lo schermo, si sceglie l'esposizione e si copia il file di stampa sulla chiavetta USB della stampante.

[Comincia dal manuale](usage/introduction.md){ .md-button .md-button--primary }
[Installa l'app](installation/requirements.md){ .md-button }

<div class="grid cards" markdown>

-   :material-download-circle-outline: **Installazione**

    ---

    Requisiti, template della stampante, installazione nativa o con Docker, configurazione e aggiornamenti.

    [:octicons-arrow-right-24: Installare l'app](installation/requirements.md)

-   :material-book-open-variant: **Utilizzo**

    ---

    Il manuale: dallo zip dei Gerber al file di stampa, passando per posizione, esposizione e scala di calibrazione.

    [:octicons-arrow-right-24: Introduzione e concetti](usage/introduction.md)

-   :material-source-pull: **Sviluppo**

    ---

    Contribuire al progetto, provare le modifiche e aggiungere il driver di una nuova stampante.

    [:octicons-arrow-right-24: Contribuire allo sviluppo](development/contributing.md)

-   :material-sitemap-outline: **Architettura**

    ---

    Come è fatta l'app: i principi, gli strati del codice, la pipeline che costruisce la maschera, il server e la pagina.

    [:octicons-arrow-right-24: Panoramica](architecture/overview.md)

</div>

!!! warning "Prima versione"
    Oggi è supportata una sola stampante, la Creality LD-002H, e il lavoro è a singola faccia. Il file della scala di calibrazione non è ancora stato provato sulla stampante: i limiti sono elencati in [Introduzione e concetti](usage/introduction.md#limiti-attuali).

GerberSLAp è software libero (GNU AGPL-3.0) e il suo codice è su [GitHub](https://github.com/shad0w82/GerberSLAp). Non è affiliato né approvato da CBD Technology, Creality o ChiTuBox: i loro nomi e marchi appartengono ai rispettivi titolari e qui servono solo a indicare con che cosa è compatibile.
