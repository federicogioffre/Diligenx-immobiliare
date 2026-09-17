# Diligenx: collaudo prima della beta

La beta si apre dopo un collaudo sull'ambiente che la ospiterà. I test di
regressione e questo runner rendono le verifiche ripetibili; da soli non
dimostrano che una particolare configurazione regga 10 utenti o 3.000 documenti.

## Ambiente e credenziali

Usare uno staging con database, Redis, bucket e account di test dedicati.
API e worker devono usare lo stesso database e lo stesso storage condiviso.
Applicare le migrazioni con il ruolo proprietario e usare il ruolo applicativo
senza superuser/BYPASSRLS per API e worker. Verificare effettivamente le policy
con i test PostgreSQL: il risultato ottenuto usando `postgres` non misura RLS.

Verificare la coda durevole e avviare almeno un worker Arq. Registrare versione
del codice, numero di repliche, CPU/RAM, pool database, concorrenza worker/LLM,
limiti dei provider e configurazione di storage nel verbale del collaudo.
Usare dati sintetici per il primo esercizio. La presenza di chiavi dei provider
può generare chiamate fatturate anche durante l'ingestion, per gli embeddings.

Il runner usa solo la libreria standard di Python 3.11+. Non registra utenti:
preparare 5 o 10 account distinti. Il file contiene i nomi delle variabili
d'ambiente, senza password o token:

```json
{
  "accounts": [
    {"email": "beta01@example.test", "password_env": "BETA_PASSWORD_01"},
    {"email": "beta02@example.test", "password_env": "BETA_PASSWORD_02"},
    {"email": "beta03@example.test", "password_env": "BETA_PASSWORD_03"},
    {"email": "beta04@example.test", "password_env": "BETA_PASSWORD_04"},
    {"email": "beta05@example.test", "password_env": "BETA_PASSWORD_05"}
  ]
}
```

In alternativa ciascuna voce può essere `{"token_env": "BETA_TOKEN_01"}` per
un Bearer token già ottenuto. I token devono restare validi per tutto il run.
Configurare le variabili tramite il secret manager o la shell locale; non
salvare le credenziali nel repository o nel verbale del test.

## Capacità con dati sintetici

Prima controllare i parametri, senza traffico di rete:

```bash
python scripts/beta_load.py --base-url https://STAGING_API \
  --accounts /secure/beta-accounts.json --users 5 --documents 100 \
  --provider-mode fake
```

`--provider-mode` registra una dichiarazione dell'operatore: il runner non può
leggere né verificare la configurazione dei provider sul server. `fake` richiede
uno staging di test appositamente configurato con provider fake; non disattivare
le protezioni della beta destinata agli utenti per ottenere questo risultato.

Eseguire poi lo stesso comando aggiungendo `--execute`:

```bash
python scripts/beta_load.py --base-url https://STAGING_API \
  --accounts /secure/beta-accounts.json --users 5 --documents 100 \
  --provider-mode fake --execute --output results/beta-5x100.json
```

Passare a `--users 10 --documents 300` solo dopo aver risolto le anomalie del
primo scenario. Aggiungere cinque account distinti nel file per il secondo.
`--ingestion-only` consente un primo collaudo di upload/parsing/embeddings senza
avviare l'analisi; il risultato registra esplicitamente questo ambito ridotto.

Ogni utente simulato crea una pratica, carica in sequenza i propri file mentre
gli altri utenti lavorano in parallelo, ripete il primo upload, attende
l'ingestion e avvia l'analisi. Il runner verifica:

- lo stesso upload restituisce lo stesso documento;
- l'inventario finale contiene esattamente tutti gli ID caricati;
- tutti i documenti sintetici risultano `processed` entro il timeout;
- un utente non legge pratica, documenti, report o stato agenti di un altro;
- ogni analisi termina con tutti gli stage completati e un report presente;
- p95 delle letture ordinarie entro il limite configurato (inizialmente 2 s).

Le letture e gli upload idempotenti applicano backoff a 429, 502, 503, 504 e
interruzioni di rete. Le creazioni e l'avvio analisi non vengono ripetuti dopo
una risposta ambigua. Il JSON registra anche tentativi falliti e retry, per
evitare che il backoff nasconda la saturazione. L'exit code è 1 se fallisce una
verifica. Le latenze HTTP misurano i singoli tentativi; i tempi di ingestion e
analisi comprendono attese e backoff.

Il documento sintetico predefinito è un TXT di 8.000 byte (regolabile con
`--document-bytes`): questo misura il percorso concorrente, non il costo OCR
o la qualità su PDF lunghi. Lo script non cancella dati. I workspace sono
riconoscibili dal prefisso `beta-<run_id>`; il risultato elenca gli ID delle
risorse create con successo. Una creazione con risposta persa può lasciare
anche una risorsa da riconciliare tramite quel prefisso.

## Interruzioni da provare sullo staging

Eseguire separatamente questi scenari e annotare stato iniziale/finale, tempi e
log correlati. Il runner non riavvia servizi né cambia la configurazione.

| Scenario | Criterio di accettazione |
| --- | --- |
| Redis indisponibile durante upload/avvio analisi | Errore visibile; nessuna falsa conferma di lavoro durevole; retry dello stesso upload senza duplicati. |
| Arresto del worker durante un job | Recupero verificato con il meccanismo configurato; nessun job bloccato senza una procedura di recupero e nessun output duplicato. |
| Due avvii simultanei della stessa pratica | Una sola esecuzione attiva; seconda richiesta rifiutata o riutilizzo esplicito dello stesso job. |
| Provider risponde 429/timeout o JSON incompleto | Stato di errore visibile; ultimo output valido conservato; retry successivo completa senza duplicare i risultati. |
| Due tab SSE aperti per utente per almeno 10 minuti | Pool database stabile; stream che si riconnette; letture ordinarie rispettano il target. |
| PDF corrotto, scannerizzato, pagina OCR fallita | Errore/copertura incompleta esplicita; il report non dichiara completa una pratica non processata. |
| Ripristino backup database + documenti | Pratiche, autorizzazioni, file e citazioni recuperati e verificati con un account di test. |

Raccogliere in parallelo utilizzo CPU/RAM, connessioni database attive/inattive,
profondità/età della coda, durata per stage, errori provider e token utilizzati.
Il JSON del runner misura solo ciò che vede il client. Queste metriche server,
SSE, recupero dopo crash e backup richiedono osservazioni aggiuntive.

## Qualità e costo con i provider reali

Usare poi un corpus rappresentativo e autorizzato di PDF nativi, scansioni,
DOCX con tabelle, contratti lunghi, documenti fiscali e bilanci. Includere
evidenze critiche dopo i primi 8.000 caratteri, pagine vuote, duplicati, file
corrotti e documenti di più società. Definire prima il numero di pagine e il
budget delle chiamate reali; il runner non applica limiti di spesa ai provider.

Un professionista prepara i rilievi attesi e controlla documento/pagina di ogni
citazione, importi, periodo e gravità. Misurare separatamente omissioni e falsi
positivi: una risposta HTTP 200 non certifica la correttezza del contenuto.
Richiedere almeno copertura di tutti i documenti, nessuna omissione dei casi
critici concordati e citazioni verificabili. Registrare le soglie concordate,
i risultati effettivi, i costi e gli errori da correggere.

`--provider-mode real` abilita la stessa prova sintetica dichiarando l'uso dei
provider reali; non trasforma il corpus sintetico in un benchmark di qualità.
Non usare il primo test da 3.000 documenti per scoprire il costo per pratica.

## Retrieval PostgreSQL

La ricerca ordina nel database per distanza coseno e restituisce solo i primi
K risultati della pratica, escludendo i documenti non processati. I vettori
non vengono trasferiti al processo API. SQLite conserva un fallback a memoria
limitata per sviluppo e test. L'operatore `<=>` richiede pgvector e uno schema
coerente con `VECTOR(1536)`. La migrazione 017 installa l'estensione e converte
la colonna legacy TEXT, che la migrazione 004 aveva creato anche su PostgreSQL.
Il server deve avere pgvector disponibile (la CI usa `pgvector/pgvector:pg16`);
una normale immagine PostgreSQL senza l'estensione non basta.

Provare la conversione su una copia dello staging prima del rilascio: `ALTER
TABLE` acquisisce un lock e converte i dati esistenti. Vettori non validi o con
dimensioni diverse da 1536 fanno fallire l'intera transazione, conservando i
dati precedenti. Correggere o rigenerare quei vettori prima di riprovare, senza
scartarli silenziosamente. Il downgrade riconverte in TEXT e conserva i valori;
lascia installata l'estensione per non interferire con altri oggetti.
Riferimenti: [pgvector](https://github.com/pgvector/pgvector#querying)
e [integrazione SQLAlchemy](https://github.com/pgvector/pgvector-python#sqlalchemy).

Misurare con `EXPLAIN (ANALYZE, BUFFERS)` su una pratica rappresentativa prima
di introdurre un indice approssimato. Il limite SQL riduce memoria e traffico
dell'API, ma il database deve comunque calcolare le distanze candidate; non è
una garanzia di latenza indipendente dalla dimensione del corpus.

## Apertura progressiva

Aprire inizialmente a 5 utenti assistiti, con limite concordato per documenti e
pagine per pratica. Passare a 10 utenti dopo aver verificato capacità, qualità,
costi e recupero dagli errori. Conservare commit testato, configurazione,
risultati e anomalie risolte nel verbale. Considerare superato un criterio solo
quando esiste una misura sullo staging della release candidata.
