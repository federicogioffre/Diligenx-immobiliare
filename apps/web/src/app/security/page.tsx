import LegalLayout from '@/components/legal/LegalLayout'

export const metadata = {
  title: 'Sicurezza',
  description: 'Come Diligenx protegge i documenti e i dati dei clienti: infrastruttura, cifratura, isolamento, modelli AI, gestione degli incidenti.',
}

export default function SecurityPage() {
  return (
    <LegalLayout
      title="Sicurezza"
      subtitle="Come Diligenx protegge i documenti delle data room e i dati dei clienti."
      lastUpdated="13/10/2026"
    >
      <p>
        Una data room contiene informazioni riservate e dati personali di terzi.
        Questa pagina descrive le misure tecniche e organizzative con cui
        Diligenx le protegge, a beneficio dei responsabili IT, privacy e
        compliance dei clienti. Le stesse misure costituiscono l’allegato
        sulla sicurezza del <a href="/dpa">Data Processing Agreement</a>.
      </p>

      <h2>1. Infrastruttura e localizzazione dei dati</h2>
      <div className="overflow-x-auto">
        <table>
          <thead>
            <tr>
              <th>Componente</th>
              <th>Fornitore</th>
              <th>Regione</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>API, elaborazione delle analisi, coda dei lavori</td>
              <td>Railway</td>
              <td>UE (Paesi Bassi)</td>
            </tr>
            <tr>
              <td>Database (metadati, testo estratto, indici semantici, risultati)</td>
              <td>Neon (su AWS)</td>
              <td>UE (Francoforte)</td>
            </tr>
            <tr>
              <td>File originali caricati</td>
              <td>Cloudflare R2</td>
              <td>[REGIONE R2]</td>
            </tr>
            <tr>
              <td>Interfaccia web</td>
              <td>Vercel</td>
              <td>Stati Uniti (Washington, D.C.)</td>
            </tr>
            <tr>
              <td>Modelli linguistici</td>
              <td>OpenAI, Anthropic</td>
              <td>Stati Uniti</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p>
        Documenti, testo estratto e risultati delle analisi sono conservati in
        UE. L’interfaccia web su Vercel inoltra le richieste al backend e non
        conserva i documenti; il testo da analizzare è inviato ai fornitori di
        modelli linguistici alle condizioni descritte al punto 5. La sicurezza
        fisica dei data center è affidata ai fornitori, che dispongono di
        certificazioni ISO 27001 e/o SOC 2 sulle proprie infrastrutture.
      </p>

      <h2>2. Cifratura</h2>
      <ul>
        <li>
          <strong>In transito.</strong> Tutto il traffico, tra browser e
          piattaforma e tra la piattaforma e i fornitori, viaggia su HTTPS/TLS.
          Il sito impone HSTS, così che il browser non apra mai una connessione
          in chiaro.
        </li>
        <li>
          <strong>A riposo.</strong> Database e file sono cifrati con AES-256 dai
          rispettivi fornitori, che ne gestiscono le chiavi.
        </li>
        <li>
          <strong>Password.</strong> Mai conservate in chiaro: se ne salva solo
          l’hash bcrypt.
        </li>
      </ul>

      <h2>3. Accesso e autenticazione</h2>
      <ul>
        <li>
          Accesso con email e password o con un account Microsoft o Google
          tramite OpenID Connect con PKCE. Chi accede con Microsoft o Google
          applica le regole del proprio account, compresa l’autenticazione a più
          fattori imposta dal proprio studio.
        </li>
        <li>
          La sessione è un cookie <code>HttpOnly</code>, <code>Secure</code> e{' '}
          <code>SameSite=Lax</code>, non leggibile da script, che scade dopo 24
          ore. Il cambio o il reset della password invalida le sessioni aperte.
        </li>
        <li>
          Gli endpoint di accesso, registrazione e reset della password hanno
          limiti di frequenza contro i tentativi automatizzati.
        </li>
        <li>
          La cancellazione dell’account richiede la password o, per gli account
          Microsoft e Google, un accesso effettuato negli ultimi dieci minuti.
        </li>
        <li>
          L’accesso del personale di Diligenx ai sistemi di produzione è
          limitato alle persone che ne hanno bisogno, con autenticazione a più
          fattori [DA CONFERMARE] sulle console dei fornitori. Il personale non consulta i
          documenti dei clienti, salvo su richiesta del cliente per assistenza
          o quando sia indispensabile per gestire un incidente.
        </li>
      </ul>

      <h2>4. Isolamento tra clienti</h2>
      <p>
        Ogni documento, pratica e risultato appartiene a un workspace, e ogni
        richiesta verifica che il workspace appartenga a chi la fa. A questo
        controllo applicativo se ne aggiunge uno nel database:{' '}
        <strong>Row-Level Security di PostgreSQL</strong>, attiva e forzata su
        tutte le tabelle che contengono dati dei clienti. Il backend si collega
        con un ruolo privo di privilegi di amministratore e all’avvio rifiuta di
        partire se il ruolo potrebbe aggirare queste regole o se una tabella ne
        è priva. Anche un errore nel codice applicativo, quindi, non basterebbe
        a esporre i dati di un cliente a un altro.
      </p>
      <p>
        Le notifiche di avanzamento delle analisi usano credenziali temporanee
        valide per una sola pratica e per sessanta secondi, distinte dalla sessione.
      </p>

      <h2>5. Intelligenza artificiale</h2>
      <ul>
        <li>
          <strong>Nessun addestramento.</strong> I documenti sono elaborati
          tramite le API commerciali di OpenAI e Anthropic, che per contratto non
          usano i dati dei clienti per addestrare i modelli. Diligenx non
          addestra modelli propri sui dati dei clienti.
        </li>
        <li>
          <strong>Conservazione presso i fornitori.</strong> I fornitori
          conservano richieste e risposte per un periodo limitato, non
          superiore a trenta giorni, a fini di sicurezza e prevenzione degli
          abusi. Le richieste a OpenAI sono inviate con l’opzione che esclude il
          salvataggio della conversazione.
        </li>
        <li>
          <strong>Verifica delle citazioni.</strong> Ogni rilievo prodotto
          dall’analisi passa una revisione indipendente che deve ritrovare nel
          documento, testualmente, i passaggi che lo sostengono; i rilievi che
          non superano la verifica non entrano nel report e sono segnalati come
          domande aperte. I riferimenti di pagina sono confrontati con le pagine
          reali del documento.
        </li>
        <li>
          <strong>Separazione dei contesti.</strong> Ogni analisi lavora solo
          sui documenti della propria pratica; le ricerche semantiche sono
          limitate alla pratica e al cliente.
        </li>
      </ul>

      <h2>6. Applicazione web</h2>
      <ul>
        <li>
          Intestazioni di sicurezza su tutte le pagine: Content Security Policy,
          HSTS, protezione dal framing, <code>X-Content-Type-Options</code>,
          Referrer-Policy e Permissions-Policy.
        </li>
        <li>
          Caricamenti limitati a PDF, DOCX e TXT, con dimensione massima per
          file.
        </li>
        <li>
          Nessun tracker, strumento di analisi di terze parti o pixel
          pubblicitario; i font sono serviti dal sito, senza richieste a
          servizi esterni dal browser dell’utente.
        </li>
        <li>
          Le versioni di anteprima del sito sono protette da autenticazione e
          non accessibili al pubblico.
        </li>
      </ul>

      <h2>7. Sviluppo e rilascio</h2>
      <p>
        Ogni modifica passa da una pull request e da una pipeline di
        integrazione continua che esegue la suite di test automatici (oltre
        1.600 test), compresi i test di isolamento tra clienti su un database
        PostgreSQL reale con Row-Level Security attiva, e la build
        dell’applicazione. Le credenziali di produzione sono conservate come
        variabili d’ambiente presso i fornitori di hosting e non compaiono nel
        codice.
      </p>

      <h2>8. Ciclo di vita dei dati</h2>
      <div className="overflow-x-auto">
        <table>
          <thead>
            <tr>
              <th>Dato</th>
              <th>Conservazione</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Documenti, testo estratto, indici semantici</td>
              <td>Fino alla cancellazione del documento, della pratica o dell’account</td>
            </tr>
            <tr>
              <td>Rilievi, domande, report</td>
              <td>Fino alla cancellazione della pratica o dell’account</td>
            </tr>
            <tr>
              <td>Copie di backup del database</td>
              <td>[N] giorni, poi sovrascritte</td>
            </tr>
            <tr>
              <td>Log tecnici</td>
              <td>[N] giorni</td>
            </tr>
            <tr>
              <td>Dati presso i fornitori di modelli linguistici</td>
              <td>Non oltre 30 giorni</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p>
        La cancellazione di un account elimina in un’unica operazione i file
        archiviati e tutti i dati collegati. Prima di cancellare, l’utente può
        scaricare dalla pagina Account una copia dei propri dati.
      </p>

      <h2>9. Continuità del servizio</h2>
      <p>
        Il database è replicato e dotato di ripristino a un punto nel tempo
        all’interno della finestra di backup. I file su Cloudflare R2 sono
        archiviati con ridondanza. Le analisi sono gestite da una coda
        persistente: se un processo si interrompe, l’analisi può essere ripresa
        senza ripartire da capo e senza nuovi addebiti.
      </p>

      <h2>10. Gestione degli incidenti</h2>
      <p>
        Diligenx registra e valuta ogni evento che possa compromettere la
        riservatezza, l’integrità o la disponibilità dei dati. In caso di
        violazione dei dati personali che riguardi documenti dei clienti,
        Diligenx informa il cliente titolare senza ingiustificato ritardo e
        comunque entro [48] ore da quando ne viene a conoscenza, con le
        informazioni disponibili sulla natura della violazione, sui dati
        coinvolti e sulle misure adottate, per consentirgli di notificare il
        Garante entro le 72 ore previste dall’art. 33 GDPR. Per le violazioni
        dei dati di cui è titolare, Diligenx procede direttamente alla notifica.
      </p>

      <h2>11. Segnalazione di vulnerabilità</h2>
      <p>
        Chi individua una vulnerabilità può scrivere a{' '}
        <a href="mailto:security@diligenx.it">security@diligenx.it</a>, con una
        descrizione sufficiente a riprodurla. Diligenx conferma la ricezione
        entro cinque giorni lavorativi e aggiorna il segnalante sulla
        risoluzione. Non agisce contro chi segnala in buona fede, senza
        accedere a dati di altri oltre il minimo necessario a dimostrare il
        problema, senza degradare il servizio e senza divulgare la
        vulnerabilità prima della correzione. Le stesse indicazioni sono
        pubblicate in <a href="/.well-known/security.txt">security.txt</a>.
      </p>

      <h2>12. Certificazioni e verifiche</h2>
      <p>
        Diligenx non dispone al momento di certificazioni proprie (ISO 27001,
        SOC 2) né ha ancora commissionato un penetration test indipendente;
        si affida alle certificazioni dei fornitori per l’infrastruttura. I
        clienti possono chiedere a{' '}
        <a href="mailto:security@diligenx.it">security@diligenx.it</a> la
        compilazione di questionari di sicurezza e le informazioni necessarie
        per le proprie verifiche, nei limiti previsti dal DPA.
      </p>
    </LegalLayout>
  )
}
