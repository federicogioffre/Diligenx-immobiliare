import LegalLayout from '@/components/legal/LegalLayout'

export const metadata = {
  title: 'Security Overview — Diligenx',
  description: 'Architettura, misure di sicurezza, retention, subprocessor.',
}

export default function SecurityPage() {
  return (
    <LegalLayout
      title="Security Overview"
      subtitle="Architettura, misure di sicurezza e gestione dei dati di Diligenx."
      draft={false}
      lastUpdated={new Date().toLocaleDateString('it-IT')}
    >
      <p>
        Questo documento descrive l&apos;architettura tecnica di Diligenx, le
        misure di sicurezza adottate e il ciclo di vita dei dati. È
        destinato a CISO, responsabili compliance e team IT dei clienti che
        valutano l&apos;adozione del servizio.
      </p>

      <h2>1. Architettura del servizio</h2>
      <p>
        Diligenx è una piattaforma SaaS multi-tenant cloud-native, composta
        da quattro componenti principali.
      </p>
      <ul>
        <li>
          <strong>Frontend Next.js 15</strong> servito da Vercel (rete edge
          globale). Tutte le pagine richiedono autenticazione lato server
          via middleware, eccezion fatta per la landing e le pagine
          informative pubbliche.
        </li>
        <li>
          <strong>Backend FastAPI</strong> su Railway. Espone le API REST,
          orchestra la pipeline di analisi multi-agente, gestisce
          autenticazione JWT.
        </li>
        <li>
          <strong>Database PostgreSQL</strong> su Railway con estensione
          pgvector per la ricerca semantica. Contiene metadati di utenti,
          deal e documenti, embedding vettoriali e output strutturato delle
          analisi.
        </li>
        <li>
          <strong>Storage Cloudflare R2</strong> in jurisdiction europea per
          i file originali caricati dagli utenti.
        </li>
      </ul>

      <h2>2. Autenticazione e autorizzazione</h2>
      <ul>
        <li>
          <strong>Hash password</strong>: bcrypt con cost factor 12, nessuna
          password in chiaro è mai memorizzata o loggata.
        </li>
        <li>
          <strong>Sessioni</strong>: JWT firmati HS256, durata 7 giorni,
          memorizzati come cookie SameSite=Lax con flag Secure su HTTPS.
        </li>
        <li>
          <strong>Autorizzazione</strong>: ogni endpoint API richiede un
          token valido e applica filtri di proprietà
          (<code>owner_id</code>, <code>workspace_id</code>, <code>deal_id</code>)
          su ogni query. La risorsa richiesta deve appartenere al chiamante.
        </li>
      </ul>

      <h2>3. Isolamento multi-tenant</h2>
      <p>
        Diligenx è un SaaS multi-tenant con isolamento <strong>logico</strong>{' '}
        (modello &quot;pooled tenancy&quot;): tutti i clienti condividono la
        stessa istanza di database e bucket, separati a livello applicativo
        tramite chiavi di proprietà su ogni query e prefissi di nomi
        oggetto su R2 (<code>deals/{'{'}deal_id{'}'}/...</code>).
      </p>
      <p>
        È inoltre in roadmap l&apos;attivazione di{' '}
        <strong>PostgreSQL Row-Level Security</strong> come secondo strato
        di difesa: il codice è già pronto, l&apos;attivazione richiede la
        rotazione del ruolo di connessione del backend a un ruolo
        non-superuser.
      </p>

      <h2>4. Cifratura</h2>
      <ul>
        <li>
          <strong>In transito</strong>: TLS 1.3 su tutti i path
          (browser→Vercel, Vercel→Railway, Railway→R2, Railway→Anthropic,
          Railway→OpenAI). Certificati gestiti dai rispettivi provider.
        </li>
        <li>
          <strong>At rest</strong>: cifratura applicata di default dai
          provider di storage (Cloudflare R2: AES-256;
          Railway PostgreSQL: cifratura a livello disco). Le chiavi sono
          gestite dai provider.
        </li>
      </ul>

      <h2>5. Ciclo di vita dei dati</h2>
      <table>
        <thead>
          <tr>
            <th>Categoria</th>
            <th>Dove vive</th>
            <th>Retention</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>File originali (PDF/DOCX)</td>
            <td>Cloudflare R2 (EU)</td>
            <td>Finché l&apos;utente non li cancella. Auto-pulizia configurabile in roadmap.</td>
          </tr>
          <tr>
            <td>Testo estratto e chunk vettoriali</td>
            <td>PostgreSQL (Railway)</td>
            <td>Cancellati in cascade alla cancellazione del documento.</td>
          </tr>
          <tr>
            <td>Output strutturato (clausole, red flag, report)</td>
            <td>PostgreSQL (Railway)</td>
            <td>Cancellati in cascade alla cancellazione del deal.</td>
          </tr>
          <tr>
            <td>Backup database</td>
            <td>Railway (snapshot quotidiani)</td>
            <td>7 giorni rolling.</td>
          </tr>
          <tr>
            <td>Log applicativi</td>
            <td>Railway / Vercel</td>
            <td>30 giorni.</td>
          </tr>
        </tbody>
      </table>

      <h2>6. Uso dei modelli AI</h2>
      <ul>
        <li>
          Diligenx invia il contenuto dei documenti ad <strong>Anthropic
          Claude</strong> per l&apos;analisi e ad <strong>OpenAI</strong> per il
          calcolo degli embedding semantici.
        </li>
        <li>
          Entrambi i fornitori operano sulle loro API in modalità{' '}
          <strong>no-training</strong>: i contenuti inviati non vengono
          utilizzati per addestrare i loro modelli.
        </li>
        <li>
          Anthropic e OpenAI conservano gli input per periodi limitati
          (30 giorni per Anthropic, 30 giorni per OpenAI) ai soli fini di
          monitoraggio abusi, oltre i quali i dati sono cancellati.
        </li>
      </ul>

      <h2>7. Subprocessor</h2>
      <p>
        L&apos;elenco aggiornato dei subprocessor è disponibile nel{' '}
        <a href="/dpa#subprocessor">Data Processing Agreement</a>. Le
        modifiche sono comunicate ai clienti con preavviso di 30 giorni.
      </p>

      <h2>8. Gestione delle vulnerabilità</h2>
      <ul>
        <li>
          <strong>Dipendenze</strong>: Renovate / Dependabot monitorano le
          dipendenze frontend e backend; aggiornamenti di sicurezza
          applicati entro 7 giorni dalla pubblicazione della CVE.
        </li>
        <li>
          <strong>Penetration test</strong>: pianificato annualmente da
          società terza specializzata (in attesa di esecuzione).
        </li>
        <li>
          <strong>Vulnerability disclosure</strong>: segnalazioni a{' '}
          <a href="mailto:security@diligenx.example">security@diligenx.example</a>;
          risposta entro 5 giorni lavorativi.
        </li>
      </ul>

      <h2>9. Incident response</h2>
      <ul>
        <li>Detection tramite alert su metriche di sistema e log.</li>
        <li>Triage entro 4 ore dall&apos;allertamento per incidenti di sicurezza.</li>
        <li>
          Notifica ai clienti impattati senza ingiustificato ritardo e
          comunque entro 72 ore dalla scoperta, conforme all&apos;art. 33 GDPR.
        </li>
        <li>Post-mortem pubblico per incidenti che impattano il servizio.</li>
      </ul>

      <h2>10. Disponibilità e backup</h2>
      <ul>
        <li>Backup PostgreSQL automatici quotidiani, conservati 7 giorni.</li>
        <li>R2 fornisce 11×9 di durability sui file.</li>
        <li>
          RTO target: 4 ore in caso di disaster recovery completo. RPO
          target: 24 ore.
        </li>
      </ul>

      <h2>11. Conformità in evoluzione</h2>
      <p>
        Diligenx è una società in fase early-stage. Le seguenti
        certificazioni sono in roadmap ma non ancora ottenute:
      </p>
      <ul>
        <li>SOC 2 Type 1 — pianificato Q4.</li>
        <li>Penetration test annuale — pianificato Q3.</li>
        <li>ISO 27001 — orizzonte 18-24 mesi.</li>
      </ul>

      <h2>12. Contatti</h2>
      <p>
        Domande tecniche o di security: <a href="mailto:security@diligenx.example">security@diligenx.example</a>.
        Per richieste di compliance / audit: <a href="mailto:privacy@diligenx.example">privacy@diligenx.example</a>.
      </p>
    </LegalLayout>
  )
}
