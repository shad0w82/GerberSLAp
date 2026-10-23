# Formato CTB v5 (ChiTuBox / Creality LD-002H): specifica e comportamento della stampante

9 ottobre 2026 · shad0w82

## Panoramica

Il file .ctb che ChiTuBox genera per la Creality LD-002H è un contenitore binario con magic 0x12FD0106 e versione 5: intestazione in chiaro, dati dei pixel cifrati con uno XOR per layer e un CRC32 in coda. Questo documento descrive ogni campo identificato e come la stampante li usa.

Tutti i valori sono little-endian (u32 = intero senza segno a 32 bit, f32 = float IEEE 754). Gli offset sono in byte dall'inizio del file. Le distanze sono in mm, le velocità in mm/min, i tempi in secondi.

**File analizzati** (tutti esportati da ChiTuBox per la LD-002H, risoluzione 1620 × 2560, layer 0,05 mm):

| File | Layer | A cosa è servito |
| --- | --- | --- |
| box.ctb | 991 | Struttura di base, cifratura, RLE |
| cube.ctb | 400 | Seconda chiave di cifratura, formule di tempo e dimensioni |
| boxsmall.ctb | 20 | Riposi (1,5 / 2,5 / 3,5 s), distanze di sollevamento bottom 6 mm e normale 7 mm |
| prova.ctb | 400 | Tutti i parametri di movimento con valori diversi tra loro |
| speedCube.ctb | 400 | Distanza di sollevamento 0,001 mm a 500 mm/min, riposi a zero |

**Livelli di certezza** usati nelle tabelle: *file* = coincide in più file ChiTuBox; *stampante* = provato con un file di prova sulla LD-002H; *dedotto* = ricavato dalla struttura, non confermato; *ignoto* = campo presente ma non interpretato.

**Verifica del programma di scrittura** (`ctbio.py`, nella cartella del driver, `gerberslap/printers/ld002h/`): ricostruendo boxsmall.ctb dai suoi stessi pixel e parametri, il risultato differisce dall'originale in 18 byte su 18003 (le stime di resina, che si azzerano di proposito, e tre valori di Z che differiscono di un'unità dell'ultimo bit del float). Con prova.ctb differiscono 171 byte, tutti dello stesso tipo più il tempo di stampa stimato a schermo.

Il formato è proprietario di CBD Technology; il file contiene un avviso di copyright che il programma copia dal template senza modificarlo. Le versioni precedenti sono documentate pubblicamente da catibo e da UVtools; la versione 5 qui descritta differisce da quelle (costante di cifratura, blocchi aggiuntivi, record per layer di 84 byte).

## Layout generale

Il file è una sequenza di blocchi; la parte iniziale (fino alla tabella dei layer) ha dimensione variabile perché le anteprime e le stringhe cambiano da file a file, quindi gli offset vanno sempre letti dai puntatori.

| Offset | Dimensione | Blocco | Puntatore |
| --- | --- | --- | --- |
| 0 | 112 | Intestazione fissa | — |
| 112 | 60 | ExtConfig (movimento, stime di resina) | Intestazione 0x54 / 0x58 |
| 172 | 76 | ExtConfig2 (secondi stadi, riposi, stringhe, cifratura) | Intestazione 0x68 / 0x6C |
| 248 | 464 | ExtConfig3 (velocità di ritorno bottom, riposi, tempi totali); i campi noti arrivano a 332, il resto è a zero | ExtConfig2 +64 |
| 712 | 32 + L1 | Anteprima 1: intestazione da 32 byte + dati | Intestazione 0x3C |
| dopo | 32 + L2 | Anteprima 2 (stesse dimensioni della prima) | Intestazione 0x48 |
| dopo | 16 | Stringa del modello, ASCII, "CREALITY LD-002H" | ExtConfig2 +28 / +32 |
| dopo | 320 | Avviso del produttore (testo ASCII) | ExtConfig3 +72 / +76 |
| dopo | 40 + Σ | Blocco resina (vedi sotto) | ExtConfig3 +80 |
| table_off | 36 × N | Tabella dei layer | Intestazione 0x40 |
| dopo la tabella | N × (84 + len + 8) | Blob dei layer: record, dati RLE cifrati, trailer | Tabella dei layer |
| fine − 4 | 4 | CRC32 di tutto ciò che precede | — |

Il primo blob dei layer inizia subito dopo la tabella, e ogni blob inizia dove finisce il precedente: non c'è riempimento tra i blocchi. La tabella dei layer coincide con la fine del blocco resina.

## Intestazione fissa (offset 0, 112 byte)

La stampante legge da qui esposizione, esposizione bottom e numero di layer bottom; il valore nella tabella dei layer viene ignorato. I campi segnati ★ sono quelli che la stampante usa (certezza: stampante).

| Offset | Tipo | Campo | Valore osservato / note |
| --- | --- | --- | --- |
| 0x00 | u32 | Magic | 0x12FD0106 |
| 0x04 | u32 | Versione | 5 |
| 0x08 | f32 ×3 | Volume stampabile X, Y, Z (mm) | 82,62 · 130,56 · 160,00 |
| 0x14, 0x18 | u32 ×2 | Riservati | 0 |
| 0x1C | f32 | Altezza totale | 0 in tutti i file |
| 0x20 | f32 | Altezza layer (mm) | 0,05 |
| 0x24 | f32 | ★ Tempo di esposizione normale (s) | Vale per tutti i layer non bottom |
| 0x28 | f32 | ★ Tempo di esposizione bottom (s) | Vale per i primi N layer |
| 0x2C | f32 | Ritardo di spegnimento | 0 in tutti i file (non testato con la modalità "Light off delay") |
| 0x30 | u32 | ★ Numero di layer bottom | Copia in ExtConfig +40 |
| 0x34, 0x38 | u32 ×2 | Risoluzione X, Y (px) | 1620 · 2560 |
| 0x3C | u32 | Offset anteprima 1 | 712 |
| 0x40 | u32 | Offset tabella dei layer | table_off |
| 0x44 | u32 | Numero di layer | N |
| 0x48 | u32 | Offset anteprima 2 | — |
| 0x4C | u32 | Tempo di stampa stimato (s) | Solo visualizzazione a schermo |
| 0x50 | u32 | Proiezione | 1 ("LCD_mirror" in ChiTuBox) |
| 0x54, 0x58 | u32 ×2 | Offset e dimensione di ExtConfig | 112 · 60 |
| 0x5C | u32 | Ignoto | 1 in tutti i file |
| 0x60 | u16 | Potenza LED (PWM) | 255 |
| 0x62 | u16 | Potenza LED bottom | 255 |
| 0x64 | u32 | Chiave di cifratura dei layer | Casuale per ogni file |
| 0x68, 0x6C | u32 ×2 | Offset e dimensione di ExtConfig2 | 172 · 76 |

Il tempo di stampa stimato (0x4C) è la somma di esposizioni, riposi e tempi di movimento; con velocità o secondi stadi insoliti la formula di ChiTuBox non è stata riprodotta, ma il campo è solo informativo.

## ExtConfig (offset 112, 60 byte)

Contiene le distanze e le velocità del primo stadio di sollevamento e la velocità di ritorno, più le stime di resina. Il programma di scrittura azzera le stime, che la stampante non usa.

| Offset | Tipo | Parametro ChiTuBox | Note |
| --- | --- | --- | --- |
| 112 (+0) | f32 | Bottom Lift Distance (primo valore) | mm; 0 fa scattare il ciclo di ripiego da 5 mm (vedi la sezione sul comportamento) |
| 116 (+4) | f32 | Bottom Lift Speed (primo valore) | mm/min |
| 120 (+8) | f32 | Lifting Distance (primo valore) | mm |
| 124 (+12) | f32 | Lifting Speed (primo valore) | mm/min |
| 128 (+16) | f32 | Retract Speed (primo valore) | mm/min; la velocità di ritorno bottom sta in ExtConfig3 |
| 132 (+20) | f32 | Volume di resina stimato | ml |
| 136 (+24) | f32 | Massa di resina stimata | g (volume × densità) |
| 140 (+28) | f32 | Costo stimato | Dal costo per kg impostato in ChiTuBox |
| 144, 148 | u32 ×2 | Riservati | 0 |
| 152 (+40) | u32 | Numero di layer bottom | Copia di 0x30 |
| 156 (+44) | u32 | Riservato | 0 |
| 160 (+48) | u32 | Ignoto | 1 in tutti i file |
| 164, 168 | u32 ×2 | Riservati | 0 |

La distanza di ritorno del primo stadio ("Retract Distance", in grigio nell'interfaccia di ChiTuBox) non è memorizzata: è sempre uguale alla distanza di sollevamento corrispondente.

## ExtConfig2 (offset 172, 76 byte)

Contiene i secondi stadi di sollevamento e ritorno (il valore dopo il "+" nell'interfaccia di ChiTuBox), il riposo prima del sollevamento, due riposi, il puntatore alla stringa del modello e la modalità di cifratura.

| Offset | Tipo | Parametro ChiTuBox | Certezza |
| --- | --- | --- | --- |
| 172 (+0) | f32 | Bottom Lift Distance, secondo valore | dedotto |
| 176 (+4) | f32 | Bottom Lift Speed, secondo valore | dedotto |
| 180 (+8) | f32 | Lifting Distance, secondo valore | dedotto |
| 184 (+12) | f32 | Lifting Speed, secondo valore | dedotto |
| 188 (+16) | f32 | Retract Distance, secondo valore | dedotto |
| 192 (+20) | f32 | Retract Speed, secondo valore | dedotto |
| 196 (+24) | f32 | ★ Rest Time Before Lift (s) | stampante |
| 200 (+28) | u32 | Offset della stringa del modello | file |
| 204 (+32) | u32 | Lunghezza della stringa (16) | file |
| 208 (+36) | u32 | Modalità di cifratura | 7 in tutti i file |
| 212 (+40) | u32 | Identificativo: aumenta da un file all'altro | ignoto |
| 216 (+44) | u32 | Livello di anti-aliasing | 8 in tutti i file |
| 224 (+52) | f32 | ★ Rest Time After Retract (s) | file |
| 228 (+56) | f32 | ★ Rest Time After Lift (s) | file |
| 236 (+64) | u32 | Offset di ExtConfig3 | 248 |

I quattro secondi stadi di sollevamento e i due del ritorno sono stati assegnati con prova.ctb, dove i valori scelti erano 0,1 / 0,2 (distanze) e 0,5 / 0,6 (velocità) per il sollevamento bottom e normale, 0,4 e 0,8 per il ritorno normale. L'assegnazione dei nomi ai valori segue l'ordine nelle tre posizioni (blocco, record bottom, record normale) ed è coerente, ma non è stata confrontata con lo screenshot dei parametri di quel file.

## ExtConfig3 (offset 248)

Contiene la velocità di ritorno dei layer bottom e il suo secondo stadio, una seconda copia dei riposi, i totali (tempo, dimensione massima, numero di layer) e i puntatori all'avviso e al blocco resina.

| Offset | Tipo | Campo | Certezza |
| --- | --- | --- | --- |
| 248 (+0) | f32 | Bottom Retract Speed (primo valore) | file |
| 252 (+4) | f32 | Bottom Retract Speed, secondo valore | dedotto |
| 260 (+12) | f32 | Costante 4,0 | ignoto |
| 268 (+20) | f32 | Costante 4,0 | ignoto |
| 272 (+24) | f32 | Rest Time After Retract (copia) | file |
| 276 (+28) | f32 | Rest Time After Lift (copia) | file |
| 280 (+32) | f32 | Rest Time Before Lift (copia) | file |
| 284 (+36) | f32 | Bottom Retract Distance, secondo valore | dedotto |
| 288 (+40) | f32 | Tempo totale = somma delle esposizioni + somma dei riposi (s) | file |
| 292 (+44) | u32 | Dimensione massima dei dati RLE di un layer (byte) | file |
| 296 (+48) | u32 | Ignoto: valori 6, 6, 0, 1, 0 nei cinque file | ignoto |
| 300 (+52) | u32 | Numero di layer | file |
| 320 (+72) | u32 | Offset dell'avviso del produttore | file |
| 324 (+76) | u32 | Lunghezza dell'avviso (320) | file |
| 328 (+80) | u32 | Offset del blocco resina | file |

Il tempo totale (288) è 313 s in boxsmall.ctb: 163 s di esposizione più 150 s di riposi (20 layer × 7,5 s). Con riposi nulli coincide con la somma delle esposizioni. Il campo 296 non segue la geometria né il numero di layer in modo evidente; il programma lo copia dal template.

## Anteprime, stringhe e blocco resina

**Anteprime.** Due immagini identiche per dimensioni e lunghezza, una dopo l'altra. Ognuna ha un'intestazione di 32 byte con otto u32: larghezza, altezza, offset dei dati, lunghezza dei dati, quattro zeri. L'altezza è 500 in tutti i file di ChiTuBox; la larghezza varia con l'oggetto affettato (297, 479, 470). I dati sono parole a 16 bit little-endian. In una parola il pixel è R5 (bit 15–11), G5 (10–6) e B5 (4–0); il bit 5 è il flag di ripetizione. Con il flag a 0 la parola è un singolo pixel. Con il flag a 1 è seguita da una seconda parola 0x3000 | (n − 1): il colore si ripete n volte, con n da 2 a 4095 (ChiTuBox non supera i 4095). I pixel sono in ordine di riga dall'angolo in alto a sinistra. Ricodificando le dieci anteprime dei cinque file si ottengono gli stessi byte di ChiTuBox.

**Anteprima generata dal programma.** Il programma sostituisce entrambe le anteprime con il primo layer di esposizione (bianco dove passa la luce, quasi nero altrove), visto dall'alto come sul vetro, ritagliato sulla zona illuminata e scalato a 500 pixel sul lato lungo, senza altre rotazioni. Poi ricalcola ogni puntatore che segue le anteprime: il secondo header, la stringa del modello, l'avviso, il blocco resina con le sue tre stringhe e l'offset della tabella dei layer. L'anteprima segue sempre la vista dall'alto: un oggetto più profondo (fronte-retro) che largo (sinistra-destra) dà un'anteprima verticale, anche se sul piccolo schermo risulta meno leggibile.

**Come la mostra la stampante.** Il riquadro dell'anteprima è orizzontale: circa 2,3 : 1 nella miniatura della griglia 2 × 2 dei file, 1,5 : 1 nella vista grande. La stampante scala l'immagine per farla entrare, mantenendo le proporzioni, e l'area libera appare grigia; uno schermo intero verticale, come il primo tentativo, spreca quindi gran parte del riquadro.

**Stringa del modello e avviso.** Subito dopo le anteprime c'è la stringa ASCII del modello (16 byte, "CREALITY LD-002H", puntata da ExtConfig2) e il testo dell'avviso di copyright di CBD Technology (320 byte, puntato da ExtConfig3). La stampante non li verifica; il programma li copia dal template.

**Blocco resina** (puntato da ExtConfig3 +80, termina dove inizia la tabella dei layer):

| Offset relativo | Tipo | Contenuto |
| --- | --- | --- |
| +0 | 8 byte | Zeri |
| +8 | u32 ×2 | Offset e lunghezza della stringa "tipo di resina" ("normal") |
| +16 | u32 ×2 | Offset e lunghezza del nome della resina ("normal") |
| +24 | u32 ×2 | Offset e lunghezza del nome del profilo materiale (7 caratteri, "Profile", nei primi tre file; 11 e 5 caratteri in prova.ctb e speedCube.ctb): la lunghezza cambia da file a file |
| +32 | f32 | Densità della resina (g/ml), 1,1 |
| +36 | u32 | Zero |
| +40 | stringhe | Le tre stringhe una dopo l'altra, senza terminatore |

Poiché la lunghezza del nome del profilo cambia, anche la dimensione della parte iniziale del file e l'offset della tabella dei layer cambiano tra un file e l'altro.

## Tabella dei layer e blob per layer

**Tabella** (offset table_off, 36 byte × N). Per ogni layer:

| Offset | Tipo | Campo | Note |
| --- | --- | --- | --- |
| +0 | f32 | Z del layer (mm) | ★ La stampante lo segue esattamente: Z = 30 mm porta il carrello a 30 mm sopra lo zero |
| +4 | f32 | Esposizione del layer (s) | Ignorata dalla stampante, che usa l'intestazione |
| +8 | f32 | Ritardo di spegnimento | 0 in tutti i file |
| +12 | u32 | Offset dei dati RLE | = inizio del record + 84 |
| +16 | u32 | Lunghezza dei dati RLE (byte) | solo i dati, senza record e trailer |
| +20 | u32 | Zero | |
| +24 | u32 | 84 (0x54) | Dimensione del record |
| +28, +32 | u32 ×2 | Zeri | |

**Blob del layer** (inizia a data_offset − 84): un record di 84 byte, i dati RLE cifrati, un trailer di 8 byte.

| Offset nel record | Tipo | Contenuto |
| --- | --- | --- |
| 0 – 35 | 36 byte | Copia della voce della tabella |
| +36 | u32 | Dimensione del blob = 84 + len + 8 |
| +40 | f32 | Distanza di sollevamento, primo stadio (bottom o normale a seconda del layer) |
| +44 | f32 | Velocità di sollevamento, primo stadio |
| +48 | f32 | Distanza di sollevamento, secondo stadio |
| +52 | f32 | Velocità di sollevamento, secondo stadio |
| +56 | f32 | Velocità di ritorno, primo stadio |
| +60 | f32 | Distanza di ritorno, secondo stadio |
| +64 | f32 | Velocità di ritorno, secondo stadio |
| +68 | f32 | Rest Time Before Lift |
| +72 | f32 | Rest Time After Lift |
| +76 | f32 | Rest Time After Retract |
| +80 | f32 | Potenza LED (255,0) |

I layer bottom (i primi N, con N dall'intestazione) portano i valori "Bottom …" di ChiTuBox nei campi +40…+64; gli altri portano i valori normali. In prova.ctb i due gruppi di record sono diversi (9,1 contro 10,2 mm, 200 contro 210 mm/min) e tutti i layer di ciascun gruppo sono identici.

**Trailer** (8 byte dopo i dati RLE): f32 con l'area illuminata del layer in mm² (pixel con valore maggiore di zero × passo² con passo 0,051 mm; ChiTuBox conta anche pixel quasi a zero, quindi può risultare di poco superiore) e un u32 a zero.

## Dati dei pixel: RLE e cifratura

Ogni layer è un'immagine 1620 × 2560 a 7 bit per pixel (0 = nero, cristalli opachi, la luce UV non passa; 127 = bianco, cristalli trasparenti; i valori intermedi sono semitrasparenze), letta in ordine di riga dall'angolo in alto a sinistra del file. Si codifica a run-length sull'intera immagine appiattita, quindi un run può attraversare più righe. Poi i byte si cifrano con uno XOR a flusso diverso per ogni layer.

**Codifica run-length (RLE7)**

```python
def rle7_decode(buf, total=1620*2560):
    out, i = [], 0
    while len(out) < total:
        b0 = buf[i]; i += 1
        v = b0 & 0x7F
        if not (b0 & 0x80):          # pixel singolo
            out.append(v); continue
        b1 = buf[i]
        if   b1 & 0x80 == 0x00: n = b1;                                  i += 1
        elif b1 & 0xC0 == 0x80: n = ((b1 & 0x3F) << 8)  | buf[i+1];       i += 2
        elif b1 & 0xE0 == 0xC0: n = ((b1 & 0x1F) << 16) | (buf[i+1] << 8) | buf[i+2]; i += 3
        else:                   n = ((b1 & 0x0F) << 24) | (buf[i+1] << 16) | (buf[i+2] << 8) | buf[i+3]; i += 4
        out.extend([v] * n)
    return out
```

Un run lungo 1 si scrive come pixel singolo. ChiTuBox spezza i run dove i valori a 8 bit differiscono di 1 (che a 7 bit diventano uguali): per questo i suoi file sono un po' più lunghi del minimo, ma il decodificatore produce gli stessi pixel. Il programma di scrittura emette sempre il minimo e non usa mai la forma a 4 byte (run massimo 0x1FFFFF); quei file sono stati accettati dalla stampante.

**Cifratura**

```python
M = 0xFFFFFFFF
def crypt(data, key, layer_index):               # cifra e decifra: è uno XOR
    c = (key * 0x2D83CDAC + 0xD8A83423) & M
    x = (((layer_index * 0x1E1530CD + 0xEC3D47CD) & M) * c) & M
    out = bytearray()
    for off in range(0, len(data), 4):           # parole da 32 bit little-endian
        w = int.from_bytes(data[off:off+4].ljust(4, b'\0'), 'little') ^ x
        out += w.to_bytes(4, 'little')
        x = (x + c) & M
    return bytes(out[:len(data)])
```

- La chiave è l'u32 a 0x64 dell'intestazione; l'indice del layer parte da 0. Si cifrano solo i dati RLE: il record di 84 byte e il trailer restano in chiaro.
- La costante additiva è 0xD8A83423. Nella documentazione pubblicata per le versioni precedenti compare 0xD8A83424: con quella i dati di questi file non si decodificano.
- La chiave cambia a ogni file ChiTuBox e la formula funziona con tutte (cinque chiavi diverse verificate). I file generati dal programma riutilizzano la chiave del template.

## CRC32 finale

Gli ultimi 4 byte del file sono il CRC32 standard (lo stesso di `zlib.crc32`) di tutti i byte che li precedono, in little-endian. Va calcolato per ultimo, dopo aver scritto ogni altro campo.

```python
import zlib, struct
blob += struct.pack('<I', zlib.crc32(blob) & 0xFFFFFFFF)
```

## Dove sta ogni parametro di ChiTuBox

Ogni parametro compare in più posti: nei blocchi dell'intestazione e nel record di ogni layer. Il programma di scrittura li tiene sempre uguali. "Secondo valore" è il numero dopo il segno + nell'interfaccia di ChiTuBox (secondo stadio del movimento). Gli offset sono assoluti per i blocchi fissi (ExtConfig 112, ExtConfig2 172, ExtConfig3 248) e relativi al record per i layer.

| Parametro ChiTuBox | Intestazione e blocchi | Record del layer | Certezza |
| --- | --- | --- | --- |
| Layer Height | 0x20; Z della tabella | Z in tabella | file |
| Exposure Time | 0x24 | — | stampante |
| Bottom Exposure Time | 0x28 | — | stampante |
| Bottom Layer Count | 0x30; 152 | — | stampante |
| Rest Time Before Lift | 196; 280 | +68 | stampante |
| Rest Time After Lift | 228; 276 | +72 | file |
| Rest Time After Retract | 224; 272 | +76 | file |
| Bottom Lift Distance | 112; secondo valore 172 | +40; +48 | primo: stampante; secondo: dedotto |
| Lifting Distance | 120; secondo valore 180 | +40; +48 | primo: stampante; secondo: dedotto |
| Bottom Lift Speed | 116; secondo valore 176 | +44; +52 | dedotto |
| Lifting Speed | 124; secondo valore 184 | +44; +52 | dedotto |
| Bottom Retract Distance | primo non memorizzato (= sollevamento); secondo valore 284 | +60 | dedotto |
| Retract Distance | primo non memorizzato (= sollevamento); secondo valore 188 | +60 | dedotto |
| Bottom Retract Speed | 248; secondo valore 252 | +56; +64 | dedotto |
| Retract Speed | 128; secondo valore 192 | +56; +64 | dedotto |
| Potenza del LED | 0x60 (normale), 0x62 (bottom) | +80 (f32) | file |
| Resolution X / Y | 0x34, 0x38 | — | file |
| Mirror ("LCD_mirror") | 0x50 = 1 | — | file |
| Anti-aliasing | 216 | — | file |
| Resin Density | blocco resina +32 | — | file |
| Resin Type / Name / profilo | blocco resina +8 … +24 | — | file |
| Waiting Mode "Light off delay" (Light-off Delay, Bottom Light-off Delay) | non esaminato: forse 0x2C e il campo +8 della tabella | — | ignoto |

Per esposizioni e riposi è dimostrato che la stampante usa l'intestazione e ignora i valori per layer. Per distanze e velocità i due insiemi di copie coincidono in tutti i file provati, quindi non sappiamo quale la stampante legga.

## Come si comporta la LD-002H

La stampante legge dall'intestazione esposizioni e riposi, segue la Z e l'immagine di ogni layer, e rispetta distanze e velocità di sollevamento fino a 0,001 mm. Lo Z0 iniziale e la risalita finale sono suoi e non dipendono dal file.

**Termini usati:** *Nero* = LCD e UV accesi con cristalli opachi (la luce non passa); *Bianco* = LCD e UV accesi con cristalli trasparenti; *Mask* = LCD e UV accesi con il pattern del layer; *Spento* = LCD e UV spenti.

**Sequenza all'avvio.** Z0 (la quota calibrata nella stampante, non nel file) → salita alla Z del primo layer, a circa 60 mm/min (30 mm in 30 s), indipendentemente dalle velocità del file → primo layer. **A fine stampa** l'LCD si spegne e il carrello sale al massimo. Nella scheda Advance di ChiTuBox non esiste un parametro per l'altezza finale e nessun campo del file la controlla.

**Sequenza per ogni layer** (definizioni di ChiTuBox: *lift* = il piano si allontana dall'LCD, *retract* = si avvicina):

1. Mask (o Nero) per il tempo di esposizione.
2. Spento per *Rest Time Before Lift*: dalla fine dell'esposizione all'inizio della salita.
3. Salita di *Lifting Distance* (primo stadio, poi il secondo).
4. *Rest Time After Lift*: dalla fine della salita all'inizio della discesa.
5. Discesa fino alla Z del layer.
6. *Rest Time After Retract*: dalla fine della discesa all'accensione della luce.

La luce resta spenta per tutto l'intervallo tra due esposizioni, movimento compreso. Con riposi a zero e distanza 0,001 mm i flash si susseguono a distanza di frazioni di secondo.

**Prove sulla stampante**

| Prova | Cosa abbiamo scritto | Cosa si è visto | Conclusione |
| --- | --- | --- | --- |
| Parcheggio | Z = 30 mm | Il carrello sale da 16 a 13 cm sul righello | La Z del layer è rispettata al millimetro |
| Esposizione per layer | Tabella: 3, 6, 9 s; intestazione: 20 s | Ogni flash dura 20 s | Vale l'intestazione, non la tabella |
| Layer bottom | 2 bottom da 3 s, poi 8 s; riposo 6 s nell'intestazione e 2 s per layer | Mask 3 s, 3 s, 8 s, 8 s, Spento sempre 6 s | Numero e tempo dei bottom e il riposo sono quelli dell'intestazione |
| Primo ritardo iniziale | Layer nero di 1 s nella tabella, 20 s nell'intestazione | Nero per 20 s | L'esposizione del singolo layer è ignorata |
| Distanza 0 | Distanza 0 nell'intestazione, 0–20 mm solo nei record dei layer | Sempre salita di 5 mm e ritorno | Con distanza 0 la stampante usa un ciclo di ripiego da 5 mm; i valori nei record non contano |
| Distanze nell'intestazione | Bottom 12 mm, normali 2 mm | I bottom salgono a 42 mm (11,8 cm), i normali di pochi mm | Le distanze dell'intestazione sono rispettate |
| Velocità | Sollevamento e ritorno a due velocità diverse | Ogni salita e ogni discesa ha un tratto a una velocità e un tratto a un'altra (bottom: i primi 5 mm in salita e i primi 7–8 mm in discesa a una velocità, il resto all'altra); nei layer normali, che salgono di pochi mm, una sola velocità | Il movimento ha due velocità; l'assegnazione ai valori del file è ancora da chiarire |
| speedCube.ctb | Distanza 0,001 mm a 500 mm/min, riposi 0 | Il carrello sale di 0,05 mm a layer; il sollevamento è impercettibile | Il ciclo non è fisso nel firmware |
| pulse_check_fast, ladder_fast | Flash con riposo 4 s, motion copiato da speedCube | Mask 2 s o 5 s, Spento 4 s, nessun movimento visibile | Come previsto |

## Orientamento dell'immagine sullo schermo

L'immagine del file arriva sullo schermo ruotata di 90° in senso antiorario, senza riflessione, vista dall'alto con te davanti alla stampante. Il pixel in alto a sinistra del file è l'angolo sinistro-fronte dello schermo.

| Bordo dell'immagine nel file | Lato della stampante |
| --- | --- |
| Alto (riga 0) | Sinistra |
| Destra (colonna 1619) | Retro |
| Basso (riga 2559) | Destra |
| Sinistra (colonna 0) | Fronte |

Di conseguenza l'asse lungo dello schermo (2560 px, 130,56 mm) corre da sinistra a destra e quello corto (1620 px, 82,62 mm) da fronte a retro. Il passo del pixel è 0,051 mm su entrambi gli assi (82,62 / 1620 = 130,56 / 2560).

**Come è stato determinato** (certezza: stampante). Un pattern con una F non specchiata nel file appare come una F non specchiata guardando lo schermo dall'alto, quindi il passaggio è una rotazione. Nel pattern specchiato da sinistra a destra, il quadrato pieno che nel file sta in alto a destra compare nell'angolo sinistro sul retro, e il cerchio pieno (alto a sinistra nel file) nell'angolo sinistro sul fronte. La scala graduata dei 50 mm del pattern risulta corretta.

**Scheda con il rame verso il basso.** Visto dall'alto, il disegno sul vetro è il riflesso di ciò che vede il rame guardato dal suo lato. Per ottenere sulla scheda il disegno corretto bisogna specchiare l'immagine da sinistra a destra nel file (colonna x → 1619 − x) prima di metterla nel file. Il programma applica questa trasformazione con `--mirror-x`.

## Uso per l'esposizione di PCB

Per esporre un PCB basta un file con pochi layer che hanno tutti la stessa esposizione; il movimento si copia da un file prodotto da ChiTuBox con distanza di sollevamento 0,001 mm.

1. **File template.** In ChiTuBox affetta un oggetto qualsiasi con: Waiting Mode "Resting time" e i tre riposi a 0; Bottom Lift Distance e Lifting Distance 0,001 (+ 0); le quattro velocità 500 (+ 0); layer bottom 1. Passalo al programma con `--motion-from-template`: copia distanze, velocità, secondi stadi e riposi senza toccarli, e cambia solo immagini, esposizione e quota Z. Non scrivere mai una distanza 0: la stampante la sostituisce con un ciclo da 5 mm.
2. **Dose.** Dipende solo dal tempo totale in cui la luce passa (somma dei flash Mask). Dato che il tempo di esposizione vale per tutti i layer, una dose T si ottiene con un layer da T oppure con N layer da T/N.
3. **Pausa tra i flash.** Il riposo prima del sollevamento (`--rest`) è l'unica pausa di buio, perché il movimento dura frazioni di secondo. Non cambia la dose: serve a far raffreddare LCD e LED. Con riposi a zero i flash sono quasi continui.
4. **Scala di esposizione.** Tutti i layer hanno lo stesso tempo; i gradini si ottengono con maschere diverse: il layer i apre le bande da i in poi, quindi la banda j riceve (j + 1) volte il tempo del layer. Per confrontare i tempi usa lo stesso numero di flash e lo stesso riposo della produzione.
   *Come la scrive l'app (dal 22 ottobre 2026, `POST /api/generate/ladder`):* una maschera per gradino (il gradino i accende le strisce da i in poi), ognuna per `pulses` layer consecutivi da `step / pulses` secondi, tutti con lo stesso tempo (quello dell'intestazione), il riposo `rest` scritto come riposo prima del sollevamento, il primo layer (quello che accende di più) come anteprima; per `bands` gradini i layer sono `bands × pulses`. Le strisce hanno le prove e la scritta del tempo (con il carattere che Pillow porta con sé, ispessito) di `js/ladder.js`. **Questo layout non è stato provato sulla stampante**: la scala provata il 14 ottobre aveva strisce piene con righe, senza queste prove né la scritta.
5. **Quota Z.** Tutti i layer alla stessa Z piccola (predefinita 1 mm): la salita iniziale dura circa un secondo invece dei 30 s a 30 mm. La stampante rispetta la Z scritta.
6. **Polarità.** Con resist positivo la luce deve passare (pixel 127) dove il rame va asportato; con resist negativo è il contrario.
7. **Specchio.** Con il rame verso il basso specchia l'immagine come descritto sopra.
8. **Pausa iniziale (facoltativa).** Se servisse il tempo per appoggiare la scheda dopo lo Z0, si possono scrivere K layer bottom neri da 1 s: ognuno dura 1 s di Nero più il riposo più il movimento (`--start-delay`). Con il piano rimosso e il finecorsa non è necessaria.

**Comandi del programma** (`pcb_ctb.py`, in questa cartella; si lancia da qualunque posto con `python gerberslap/printers/ld002h/docs/pcb_ctb.py ...`, e `python gerberslap/printers/ld002h/ctbio.py info file.ctb` mostra l'intestazione di un file):

```
pcb_ctb.py test   -t speedCube.ctb -o out.ctb --exposure 20 --mirror-x --motion-from-template
pcb_ctb.py ladder -t speedCube.ctb -o out.ctb --step 10 --bands 8 --pulses 2 --rest 4 --mirror-x --motion-from-template
pcb_ctb.py png board.png -t speedCube.ctb -o out.ctb --dpi 1200 --exposure 60 --pulses 4 --rest 5 --mirror-x --center --motion-from-template
```

Il programma rifiuta layer con esposizioni diverse (la stampante ne userebbe una sola) e controlla ogni file decodificandolo dopo la scrittura.

**Anteprima del file.** Per impostazione predefinita il programma mette come anteprima il primo layer di esposizione, visto dall'alto come sul vetro e ritagliato sulla zona illuminata (sezione sulle anteprime). `--preview-full-panel` mostra invece tutta l'area dello schermo; `--keep-template-preview` lascia l'anteprima del template.

## Punti aperti

Ciò che non è verificato o non è interpretato, in ordine di utilità per il progetto:

- **Secondi stadi.** L'assegnazione dei sei valori di ExtConfig2 e dei due di ExtConfig3 a "distanza o velocità, sollevamento o ritorno, bottom o normale" è dedotta dall'ordine; da confermare con lo screenshot dei parametri di prova.ctb.
- **Due velocità nel movimento.** Si vedono due velocità per ogni salita e discesa (con secondi stadi a zero nei file di prova): non sappiamo a quali valori del file corrispondano né perché il tratto cambi a 5 mm in salita e a 7–8 mm in discesa.
- **Quale copia legge la stampante.** Distanze e velocità compaiono nei blocchi dell'intestazione e nel record di ogni layer, uguali in tutti i file; non è dimostrato quale delle due copie venga usata.
- **Modalità "Light off delay".** Non esaminata: i due valori di ritardo (normale e bottom) sono forse nel campo 0x2C o nel campo +8 della tabella.
- **Campi non interpretati.** Intestazione 0x1C, 0x2C, 0x5C; ExtConfig +160; ExtConfig2 +40 (identificativo crescente); ExtConfig3 +12 e +20 (costante 4,0) e +48 (6, 6, 0, 1, 0).
- **Anteprime.** Il formato è decodificato e ricodificato byte per byte, e la stampante accetta anteprime generate dal programma (provate la forma verticale 316 × 500 e quella orizzontale ritagliata: entrambe si vedono correttamente); un'anteprima verticale ritagliata su un oggetto profondo non è stata provata.
- **Cifratura disattivata.** Non provata sulla stampante la chiave 0, che la documentazione delle versioni precedenti indica come "nessuna cifratura".
- **Limiti di esposizione.** Esposizioni di un layer sotto 1 s o sopra 20 s non sono state provate (20 s è il massimo usato).
- **Tempo di stampa stimato.** La formula di ChiTuBox per il campo 0x4C non è stata riprodotta quando i secondi stadi sono diversi da zero.
- **Altri modelli.** Tutto questo vale per la LD-002H usata nelle prove (versione del firmware non rilevata); altri modelli Creality o versioni di ChiTuBox possono avere altri valori.
