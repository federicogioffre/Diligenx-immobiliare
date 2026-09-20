# Deployment e recupero della beta

Questa configurazione è una candidata al collaudo. Non è una certificazione di
capacità e non avvia servizi nell'ambiente attuale senza un comando esplicito.
Seguire poi [il piano di collaudo](BETA_TESTING.md).

## Preparazione dello staging

Usare database, bucket e account dedicati. La PR dipende dalle protezioni della
PR 38: includere entrambe prima del deploy. Il backend richiede ora le
migrazioni 016 (contesto RLS vuoto) e 017 (embedding nativi pgvector).

Prima della migrazione 017, fare un backup e provarne il ripristino su un
database isolato. Il server PostgreSQL deve avere pgvector disponibile. Gli
embedding già presenti devono essere vettori validi di dimensione 1536: dati
incompatibili fanno fallire la conversione senza essere cancellati. Indagare e
rigenerare tali embedding prima di ripetere la migrazione. La conversione
prende un lock sulla tabella: misurarne il tempo sulla copia del database.

Su Railway mantenere servizi distinti per API, worker Arq, PostgreSQL e Redis;
il frontend può rimanere su Vercel. API e worker usano lo stesso bucket R2 e lo
stesso ruolo database applicativo. Eseguire Alembic con il ruolo proprietario,
tramite `MIGRATIONS_DATABASE_URL`. Configurare `BETA_MODE=true` su API e worker:
l'avvio controlla chiavi provider, Redis, storage condiviso, cookie HTTPS,
migrazioni e ruolo PostgreSQL senza SUPERUSER/BYPASSRLS con RLS forzata.

Per uno staging riproducibile con Docker Compose, creare un `.env` locale
ignorato da Git con queste variabili, valorizzate dal secret manager:

```dotenv
BETA_DB_PASSWORD=<password casuale URL-safe del ruolo applicativo>
BETA_DB_ADMIN_PASSWORD=<password casuale URL-safe del proprietario>
SECRET_KEY=<segreto casuale di almeno 32 caratteri>
ANALYSIS_MODEL=gpt-5.6-luna
OPENAI_API_KEY=<chiave staging>
S3_BUCKET=<bucket staging>
S3_ENDPOINT_URL=<endpoint R2 oppure vuoto per AWS>
S3_ACCESS_KEY_ID=<credenziale staging>
S3_SECRET_ACCESS_KEY=<credenziale staging>
S3_REGION=auto
BETA_WEB_URL=https://beta.example.com
BETA_API_URL=https://beta-api.example.com
SENTRY_DSN=<DSN opzionale del progetto staging>
```

```bash
docker compose -f docker-compose.yml -f docker-compose.beta.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.beta.yml up --build -d
```

API e worker usano GPT-5.6 Luna per analisi e Q&A, con la stessa configurazione.
`ANTHROPIC_API_KEY` serve solo se si imposta esplicitamente un modello `claude-*`;
la chiave OpenAI resta necessaria per gli embedding. Non esiste fallback automatico
a un altro modello quando la chiave selezionata manca.

Il Compose avvia PostgreSQL con pgvector, crea il ruolo applicativo, applica le
migrazioni una sola volta tramite il servizio `migrate`, poi avvia API, worker
e frontend. Configurare DNS e reverse proxy HTTPS per le due URL prima di
invitare utenti. PostgreSQL e Redis non pubblicano porte sull'host. Il reverse
proxy deve consentire SSE senza buffering e upload fino al limite configurato.
Il frontend incorpora l'URL API durante la build: modificarla richiede rebuild.

I volumi Redis e PostgreSQL persistono tra riavvii. Redis usa AOF `everysec`:
un guasto host può comunque perdere l'ultimo secondo, quindi Redis richiede
backup/replica e verifica di recupero; la coda non equivale a una garanzia di
esecuzione esattamente una volta. Non usare `down -v` su dati da conservare.

## Limiti iniziali e osservazione

Partire con una replica API e una replica worker. Il worker ammette al massimo
4 lavori; ogni analisi usa al massimo 4 chiamate LLM contemporanee. Ogni lavoro
ha un processo separato: il tetto potenziale è quindi 16 chiamate dal worker,
più le chiamate API. Per un account provider con limiti inferiori abbassare
`WORKER_MAX_JOBS` e `LLM_MAX_CONCURRENCY` prima del test. `LLM_MAX_IN_FLIGHT`
limita il singolo processo, non l'intera flotta. Aumentare le repliche solo
dopo aver misurato memoria, tempi, quote provider e costo.

`GET /health` controlla database, Redis e presenza dell'heartbeat worker
(aggiornato ogni 15 secondi). È un segnale di disponibilità, non la prova che
ogni lavoro proceda. Monitorare anche età/profondità della coda, documenti in
`pending/processing`, durata degli `AgentRun`, errori e connessioni database.
I log `llm_usage` espongono modello, durata e token, senza contenuti dei prompt.
Impostare gli allarmi di spesa nel progetto del provider: il codice non applica
un tetto monetario globale. Il timeout predefinito di un lavoro è 3.600 secondi;
dimensionarlo dopo i test sulle pratiche più grandi.

## Recupero operativo

- Upload interrotto o coda non disponibile: ripetere lo stesso file con lo
  stesso nome. Il caricamento è idempotente nella pratica e riusa il documento;
  gli errori temporanei del browser hanno retry con attesa. Verificare comunque
  che lo stato finale sia `processed`, non soltanto che l'upload sia accettato.
- Documento `failed`: verificare i log per l'ID, correggere il file o la causa
  esterna e ricaricarlo. Un PDF con una pagina senza testo dopo OCR è rifiutato,
  incluse le pagine davvero vuote: in questa versione sostituire il file con
  una copia verificata o effettuare una revisione del documento. Non viene
  esclusa silenziosamente una pagina dal report.
- Analisi incompleta: conservare il report precedente, risolvere il problema e
  rilanciare l'analisi. Le fasi fallite non pubblicano risultati parziali.
- Analisi rimasta `analyzing` dopo crash/risposta Redis ambigua: attendere la
  finestra di timeout più 60 secondi, verificare il worker e usare, autenticati
  come proprietario, `POST /deals/{id}/recover-analysis`. Il comando verifica
  che Redis non abbia più il lavoro e riporta la pratica a `draft`; non avvia
  una nuova analisi. Se il lavoro è ancora in coda o in esecuzione risponde
  409; senza Redis verificabile risponde 503. Rilanciare solo dopo il recupero.

Rimane una finestra tra il salvataggio nel database e l'invio a Redis: un crash
API in quel punto richiede la riconciliazione sopra. Il sistema non ha ancora
un outbox transazionale che ripari automaticamente quel caso. Questo va
provato nello staging e accettato come limite operativo prima della beta.

## Criteri per invitare i primi utenti

Completare regressioni CI, migrazione/ripristino e scenari di guasto; eseguire
5 utenti × 100 documenti, poi 10 × 300, registrando risultati e costi.
Convalidare separatamente con un professionista un corpus realistico con
scansioni, tabelle, documenti lunghi ed evidenze note. Invitare inizialmente
5 utenti con assistenza disponibile; ampliare dopo aver chiuso gli errori
osservati. Conservare commit, configurazione e verbale di ogni collaudo.
