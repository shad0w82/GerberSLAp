---
icon: material/alert-circle-outline
---

# Avvisi e problemi

## Avvisi

!!! note "In scrittura"
    L'elenco degli avvisi, con che cosa significano e che cosa fare, è in preparazione.

## Problemi frequenti

I problemi di installazione e avvio sono in [Aggiornare e problemi](../installation/maintenance.md#problemi-frequenti).

| Sintomo | Causa e rimedio |
|---|---|
| Uno zip viene rifiutato | I vecchi export di EAGLE (prima del formato Gerber di EAGLE 9) si rifiutano di proposito. Uno zip senza file di rame, o non riconoscibile, dà un messaggio che lo dice. |
| «Un flash sotto il minimo» | Il flash è `tempo totale / numero di flash`. Sotto 1 s non è mai stato provato sulla stampante e il file non si genera; oltre 20 s si genera con un avviso (non provato). |
| Dopo il riavvio manca un file | Il server tiene i Gerber solo in memoria. Se il progetto è stato salvato (copia di lavoro nel browser) la pagina li ridà da sola; altrimenti si riapre lo zip. |
| I progetti salvati «spariscono» | La copia di lavoro sta nel browser e dipende dall'indirizzo e dal profilo: si usa sempre lo stesso indirizzo e lo stesso browser. Per portare un progetto altrove si scarica il file `.gslp`, che contiene anche i Gerber. |
