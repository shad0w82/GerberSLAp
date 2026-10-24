---
icon: material/source-pull
---

# Contribuire allo sviluppo

Questa pagina serve a chi vuole lavorare sul codice o sulla documentazione di GerberSLAp: come preparare l'ambiente, come provare le modifiche, come si estende l'app e che cosa controllare prima di proporre un cambiamento. Come è fatta l'app dentro lo spiega l'[Architettura](../architecture/overview.md).

## Preparare l'ambiente

```bash
git clone https://github.com/shad0w82/GerberSLAp.git
cd GerberSLAp
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

`requirements-dev.txt` contiene le dipendenze dell'app più quelle dei test. Node.js serve solo ai test della logica della pagina. Per provare la pagina senza una stampante vera:

```bash
.venv/bin/python -m gerberslap.web --dev-printers --dev-samples cartella-di-zip
```

`--dev-printers` aggiunge tre stampanti inventate, `--dev-samples` offre gli zip di una cartella (vedi [Configurazione](../installation/configuration.md#opzioni-di-avvio)).

!!! info "Cosa non c'è nel repository"
    Il template della stampante e i file di terzi usati da alcuni test (zip di Gerber di KiCad, Altium ed EAGLE) non sono nel repository: i `.ctb` per il copyright del produttore, gli zip perché non sono nostri. I test che li richiedono si saltano da soli se mancano.

## Eseguire i test

```bash
.venv/bin/python -m pytest -q
```

Sono oltre mille test e richiedono un paio di minuti. Si saltano da soli i test che richiedono ciò che manca: i file di terzi in `experiments/fase1/external/` e `experiments/fase2/external/`, il template `samples/speedCube.ctb` e Node.js. Si può provare un solo file, per esempio `.venv/bin/python -m pytest tests/test_printers.py`.

Il controllo di sintassi dei moduli JavaScript usa `node --input-type=module --check` con il file su stdin: `node --check file.js` non basta, perché con Node 26 accetta moduli con errori.

Per ispezionare un file generato ci sono due comandi sul lettore del formato della LD-002H:

```bash
python3 gerberslap/printers/ld002h/ctbio.py info file.ctb          # intestazione e CRC
python3 gerberslap/printers/ld002h/ctbio.py layer file.ctb N out.png   # estrae un layer come immagine
```

## Come sono fatti i test

- **Dati sintetici** in `tests/support/testdata.py`. Un **oracolo indipendente** (`oracle.py`) calcola le aree esatte con un altro metodo, per controllare il raster. Una scheda con forma nota (`markerboard.py`) fissa dove atterra ogni cosa, e stampanti finte (`fakeprinters.py`) permettono di provare il server senza il template vero.
- Il **test di regressione del formato** ricostruisce `boxsmall.ctb` (un file di ChiTuBox, che non è nel repository) dai suoi stessi pixel e parametri: deve dare 18 byte di differenza, cioè le stime di resina, azzerate di proposito, e tre valori Z arrotondati diversamente.
- I test del server usano il client di prova di FastAPI. La logica della pagina senza DOM si prova con Node.js, e il layout della scala si confronta tra Python e JavaScript.
- Un test controlla che il nucleo, il modello dati, `cad/` e `services/` non nominino la stampante né il formato del suo file, e che ogni driver abbia la sua `icon.png`.
- `tests/test_docker.py` controlla, senza Docker, che cosa entra nell'immagine (calcola il contesto di build da `.dockerignore`: nessun `.ctb`, né dati, né test) e che `Dockerfile` e `compose.yaml` abbiano le proprietà che contano: utente senza privilegi, volume, porta solo locale. `tests/test_startup_env.py` prova le variabili d'ambiente di avvio.

## Estendere l'app

**Aggiungere una stampante.** Una stampante è una cartella `gerberslap/printers/<id>/` con un driver e una foto. L'app la trova da sola all'avvio, e non serve toccare né il nucleo, né il modello dati, né la pagina. La guida completa è [Il driver di una stampante](new-printer/driver.md), con un [esempio funzionante](new-printer/example.md).

**Aggiungere una lingua.** Un catalogo in `gerberslap/web/static/js/i18n.js` con le stesse chiavi di quelli che ci sono, e una voce in `gerberslap/web/static/js/flags.js`.

**Aggiungere un programma CAD.** Un riconoscitore in `gerberslap/cad/`, con la stessa interfaccia degli altri (punteggio e assegnazione dei file), e un test con uno zip vero.

## Scrivere la documentazione

I testi stanno in `docs/it/` (la lingua predefinita) e in `docs/en/`, con gli stessi percorsi e gli stessi nomi di file nelle due lingue: **le due versioni vanno tenute allineate**. Il titolo di ogni pagina è il suo H1; l'icona accanto al titolo nell'elenco di sinistra è la riga `icon:` in cima al file.

Per aggiungere una pagina si creano i due file e si aggiunge una riga al `nav` di `mkdocs.yml`. Una pagina che esiste solo in italiano compare anche nel sito inglese, con il testo italiano, finché non è tradotta.

Per costruire il sito in locale:

```bash
python3 -m venv .venv-docs
.venv-docs/bin/pip install -r mkdocs-require.txt
.venv-docs/bin/mkdocs serve            # anteprima su http://127.0.0.1:8000/GerberSLAp/
.venv-docs/bin/mkdocs build --strict   # costruzione completa, con errore su ogni avviso
```

Lo stile del sito sta in `docs/stylesheets/extra.css`. I caratteri (Inter e JetBrains Mono, licenza SIL OFL) sono inclusi in `docs/assets/fonts/`, quindi il sito non fa richieste a fornitori esterni. Il titolo «In questa pagina» viene da `overrides/partials/toc.html`, una copia di un file di Material 9.7.7 da ricontrollare se si aggiorna Material. Lo script `docs/javascripts/tables.js` impedisce che vada a capo la prima colonna di una tabella quando contiene solo etichette corte.

`mkdocs-require.txt` fissa anche le dipendenze indirette: non si aggiorna nulla senza rifare la prova, perché MkDocs 2.0 non è compatibile con Material for MkDocs né con i suoi plugin.

Le immagini del manuale si rifanno con un comando, dall'app vera e nelle due lingue: `cd tools/docs_screenshots && npm install && node shoot.mjs`. Lo script avvia l'app su una cartella dati temporanea con il template della stampante (serve un file `.ctb` fatto con ChiTuBox, in `samples/speedCube.ctb` o indicato con `GERBERSLAP_TEMPLATE`), apre la scheda di esempio e salva i PNG in `docs/it/usage/img/` e `docs/en/usage/img/`. Ogni capitolo ha il suo file in `tools/docs_screenshots/chapters/`, e `node shoot.mjs interface` rifà solo le immagini di quel capitolo. La scheda di esempio la scrive `tools/demo_board/make_demo_board.py` in `docs/assets/GerberSLAp-demo.zip`, sempre con gli stessi byte; un test controlla che lo zip del sito sia quello dello script.

Qualche regola di scrittura:

- niente storia dello sviluppo, solo ciò che serve a capire come è fatta l'app e come si usa;
- i nomi delle zone dell'interfaccia (MenuBar, SidePanel, CadWindow…) sono sempre quelli del [Tour dell'interfaccia](../usage/interface.md);
- le parole dell'interfaccia sono identiche a quelle di `i18n.js`;
- non si afferma un comportamento della stampante che non è stato provato;
- nelle tabelle di metodi la prima colonna ha solo il nome e i parametri stanno nella colonna di destra: una prima colonna di etichette corte (fino a 60 caratteri) non va a capo.

## Proporre una modifica

Una modifica si propone su GitHub, aprendo una issue per parlarne o una pull request con il cambiamento. Prima di proporla si controlla che:

1. i test passino (`pytest`), e che ce ne sia uno per ciò che si è cambiato;
2. un testo nuovo, o un codice nuovo di avviso o di errore, abbia la sua frase in **tutte e due le lingue** nel catalogo `i18n.js`;
3. il nucleo, il modello dati, `cad/` e `services/` non nominino una stampante o il formato del suo file: tutto ciò che dipende dalla stampante sta nel suo driver;
4. la documentazione sia aggiornata in italiano e in inglese;
5. nessun file `.ctb` finisca nel repository.

Il codice e la documentazione sono distribuiti con la licenza **GNU AGPL-3.0**.
