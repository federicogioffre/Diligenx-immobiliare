# Correzioni del collaudo con provider reali — 19 settembre 2026

Il collaudo della release `54bf78e4` ha completato il percorso tecnico, ma ha prodotto un profilo societario vuoto, raccomandazioni in inglese e sintesi che alteravano condizioni delle fonti. Questa modifica affronta i sette rilievi documentati nel verbale locale del collaudo.

## Comportamento corretto

- Il selettore societario riconosce profili informali e gruppi di dati societari nell'intero documento, anche oltre i primi 1.500 caratteri. L'estrazione mantiene il perimetro delle target e il riferimento alla fonte, senza trattare il profilo come certificazione ufficiale.
- Prima di sostituire i risultati salvati, l'aggregazione sottopone i testi a una revisione aggiuntiva contro le fonti. Il revisore deve conservare termini di rimedio, presupposti, stato di esercizio dei diritti e informazioni non documentate. Può correggere i campi narrativi, ma non cambiare autonomamente importi o classificazioni.
- La risposta del revisore viene controllata: copertura di tutti i risultati e dei campi fattuali, citazioni presenti nel testo originale, coordinate ricavate dai chunk, lingua coerente e assenza di campi eliminati. Risposte incomplete o non supportate interrompono la fase prima di sostituire i risultati precedenti.
- I documenti lunghi sono trattati tramite finestre contestuali e, quando necessario, passaggi limitati per dimensione. Le citazioni si verificano sempre sul testo originale, mai su concatenazioni sintetiche. Una riscrittura non può riutilizzare automaticamente le prove assegnate al testo precedente.
- L'executive summary riceve una revisione separata contro i rilievi, le osservazioni e il contesto confermato. Anche le sintesi senza rilievi vengono controllate. Durante generazione e revisione la connessione DB è restituita al pool.
- Prima della pubblicazione viene riacquisito il lock della pratica e vengono riverificati dati e identità delle fasi di analisi: modifiche concorrenti o una nuova analisi sullo stesso corpus fanno fallire la generazione preservando il report precedente.
- Esempi di raccomandazioni e istruzioni rispettano la lingua richiesta. Un controllo conservativo intercetta contaminazioni evidenti italiano/inglese senza bloccare sigle, nomi di file e citazioni originali.
- Le citazioni possono conservare più documenti e pagine nel payload JSON esistente; report e pagina dei rilievi le mostrano senza ridurle a un'unica pagina. Le fonti prive di pagina restano visibili.
- Il template non dichiara la copertura automatica di tutti i periodi fiscalmente accertabili. Le richieste non contengono più soglie fittizie o riferimenti a una materialità non definita.
- Il DOCX interpreta il corsivo Markdown senza alterare gli underscore interni ai nomi dei file, ripete le intestazioni delle tabelle e tiene unite le righe ordinarie. I titoli PDF restano con il contenuto successivo.

## Compatibilità e rilascio

Non è necessaria una migrazione di database. Le prove e le citazioni multiple usano `structured_payload_json`; il campo `source_page` rimane compatibile per i rilievi con una sola pagina verificata.

La revisione dell'analisi entra nell'impronta dei checkpoint. Dopo l'aggiornamento, i report prodotti con le regole precedenti rimangono conservati ma risultano obsoleti: richiedono una **nuova analisi completa** prima di rigenerazione ed export. La ripresa ordinaria non può riusare checkpoint precedenti. L'adozione manuale di un checkpoint senza impronta conserva soltanto ingestione e classificazione; le fasi di analisi vengono rieseguite.

La revisione aggiunge chiamate al provider, in funzione del numero di fonti, risultati e finestre. Il controllo semantico resta affidato a un modello: le verifiche deterministiche garantiscono il protocollo e l'esistenza delle citazioni, non dimostrano da sole che ogni inferenza sia corretta.

## Verifica

Le fixture `live_sample_2026_09_19.json` e `grounding_replay_2026_09_19.json` contengono esclusivamente i dati sintetici del collaudo. Le regressioni riproducono i testi difettosi e verificano contesto completo, correzione prima del salvataggio, rigetto delle risposte non valide, citazioni multiple, conservazione dei report precedenti e invalidazione dei checkpoint.

Le risposte AI nei test sono simulate esplicitamente: questi test verificano il comportamento applicativo e non costituiscono una nuova valutazione con provider reale. PDF e DOCX del campione salvato sono stati rigenerati localmente e controllati visivamente su tutte le pagine. I risultati della suite completa e dei controlli web sono riportati nella pull request.
