import LegalLayout from '@/components/legal/LegalLayout'

export const metadata = {
  title: 'Data Processing Agreement',
  description: 'Accordo sul trattamento dei dati personali ai sensi dell’art. 28 GDPR.',
}

export default function DpaPage() {
  return (
    <LegalLayout
      title="Data Processing Agreement"
      subtitle="Accordo sul trattamento dei dati personali ai sensi dell’art. 28 del Reg. (UE) 2016/679 (GDPR)."
      lastUpdated="13/10/2026"
    >
      <h2>1. Parti, ambito e prevalenza</h2>
      <p>
        Il presente accordo (il “<strong>DPA</strong>”) è concluso tra il
        Cliente, come definito nei <a href="/terms">Termini di Servizio</a>, in
        qualità di titolare del trattamento (il “<strong>Titolare</strong>”), e{' '}
        <strong>[RAGIONE SOCIALE]</strong>, con sede in [SEDE], P.IVA [P.IVA]
        (“<strong>Diligenx</strong>”), in qualità di responsabile del
        trattamento. Integra i Termini di Servizio e si intende accettato con
        essi. Disciplina i dati personali contenuti nei documenti che il
        Titolare carica nella piattaforma e nei risultati delle analisi; i dati
        degli account restano regolati dalla{' '}
        <a href="/privacy">Privacy Policy</a>, poiché per essi Diligenx è
        titolare.
      </p>
      <p>
        In caso di contrasto tra il DPA e i Termini di Servizio, per quanto
        riguarda la protezione dei dati personali prevale il DPA. I termini non
        definiti hanno il significato loro attribuito dal GDPR.
      </p>

      <h2>2. Oggetto e istruzioni</h2>
      <p>
        Diligenx tratta i dati personali per conto del Titolare al solo fine di
        erogare il Servizio: conservare i documenti, estrarne il testo,
        indicizzarlo, analizzarlo con modelli di intelligenza artificiale,
        produrre rilievi, risposte e report e renderli disponibili al Titolare.
        Le caratteristiche del trattamento sono descritte nell’Allegato 1.
      </p>
      <p>
        I Termini di Servizio, il presente DPA e l’uso delle funzionalità della
        piattaforma da parte del Titolare costituiscono le sue istruzioni
        documentate. Ulteriori istruzioni vanno date per iscritto e, se
        comportano costi o sviluppi non previsti, sono concordate tra le parti.
        Diligenx informa immediatamente il Titolare se ritiene che
        un’istruzione violi il GDPR o altre norme sulla protezione dei dati, e
        può sospenderne l’esecuzione fino a conferma o modifica. Diligenx non
        tratta i dati per finalità proprie e non li usa per addestrare modelli
        di intelligenza artificiale.
      </p>

      <h2>3. Obblighi del Titolare</h2>
      <p>
        Il Titolare garantisce di disporre di una base giuridica per il
        trattamento dei dati che carica, di aver fornito agli interessati le
        informazioni previste dagli artt. 13 e 14 GDPR o di esserne esonerato, e
        di limitare i dati caricati a quelli necessari per l’incarico. Se i
        documenti contengono dati di categorie particolari (art. 9 GDPR) o
        relativi a condanne penali e reati (art. 10 GDPR), il Titolare verifica
        che il loro trattamento sia consentito e ne tiene conto nella propria
        valutazione dei rischi.
      </p>

      <h2>4. Riservatezza</h2>
      <p>
        Diligenx autorizza al trattamento solo il personale che ne ha bisogno
        per erogare il Servizio o prestare assistenza, vincolato da un obbligo
        di riservatezza contrattuale o di legge. Il personale non accede al
        contenuto dei documenti salvo su richiesta del Titolare o quando sia
        indispensabile per gestire un incidente di sicurezza.
      </p>

      <h2>5. Sicurezza</h2>
      <p>
        Diligenx adotta le misure tecniche e organizzative previste dall’art. 32
        GDPR descritte nell’Allegato 2. Può aggiornarle nel tempo, purché il
        livello complessivo di protezione non diminuisca.
      </p>

      <h2>6. Sub-responsabili</h2>
      <p>
        Il Titolare autorizza in via generale Diligenx a ricorrere ad altri
        responsabili (“<strong>Sub-responsabili</strong>”). Quelli in uso alla
        data del DPA sono elencati nell’Allegato 3. Diligenx impone a ciascuno,
        per contratto, obblighi di protezione dei dati sostanzialmente
        equivalenti a quelli del DPA e risponde verso il Titolare del loro
        inadempimento, ai sensi dell’art. 28.4 GDPR.
      </p>
      <p>
        Diligenx comunica al Titolare via email, con almeno trenta giorni di
        preavviso, l’aggiunta o la sostituzione di un Sub-responsabile. Entro
        quel termine il Titolare può opporsi per motivi ragionevoli legati alla
        protezione dei dati. Le parti cercano in buona fede una soluzione; in
        mancanza, il Titolare può recedere dal contratto con effetto dalla data
        del cambio, con rimborso dei Crediti acquistati e non scaduti. Il
        preavviso può essere più breve quando la sostituzione è imposta da
        un’urgenza di sicurezza o dalla cessazione del servizio di un
        fornitore; in tal caso Diligenx ne informa il Titolare appena possibile.
      </p>

      <h2>7. Trasferimenti fuori dallo Spazio economico europeo</h2>
      <p>
        Alcuni Sub-responsabili trattano dati negli Stati Uniti. I trasferimenti
        si basano sulla decisione di adeguatezza della Commissione europea del
        10 luglio 2023 (EU-U.S. Data Privacy Framework), per i Sub-responsabili
        certificati, e in ogni caso sulle Clausole Contrattuali Standard
        approvate con Decisione di esecuzione (UE) 2021/914 (modulo 3, da
        responsabile a responsabile), con misure supplementari che includono la
        cifratura in transito e a riposo e il divieto contrattuale di usare i
        dati per l’addestramento dei modelli. Il Titolare può chiedere copia
        delle garanzie applicabili.
      </p>

      <h2>8. Diritti degli interessati</h2>
      <p>
        La piattaforma consente al Titolare di consultare, esportare e
        cancellare i documenti e i risultati in autonomia. Se un interessato si
        rivolge direttamente a Diligenx, Diligenx inoltra la richiesta al
        Titolare senza ritardo e non vi dà seguito senza sue istruzioni. Per le
        richieste che il Titolare non può soddisfare con gli strumenti della
        piattaforma, Diligenx presta l’assistenza ragionevolmente necessaria.
      </p>

      <h2>9. Assistenza al Titolare</h2>
      <p>
        Diligenx fornisce al Titolare le informazioni in suo possesso utili per
        la valutazione d’impatto sulla protezione dei dati e per l’eventuale
        consultazione preventiva dell’autorità di controllo (artt. 35 e 36
        GDPR), e lo assiste nell’adempimento degli obblighi degli artt. 32-34
        GDPR, tenuto conto della natura del trattamento e delle informazioni
        disponibili.
      </p>

      <h2>10. Violazioni dei dati personali</h2>
      <p>
        Diligenx informa il Titolare senza ingiustificato ritardo, e comunque
        entro [48] ore da quando ne viene a conoscenza, di ogni violazione che
        riguardi i dati trattati per suo conto. La comunicazione indica, nella
        misura in cui sono note, la natura della violazione, le categorie e il
        numero approssimativo di interessati e di registrazioni coinvolti, le
        probabili conseguenze e le misure adottate o proposte, con un punto di
        contatto. Le informazioni non disponibili subito sono fornite in fasi
        successive. Diligenx adotta senza ritardo le misure per contenere la
        violazione e attenuarne gli effetti. La comunicazione non costituisce
        riconoscimento di responsabilità.
      </p>

      <h2>11. Cancellazione e restituzione dei dati</h2>
      <p>
        Per tutta la durata del rapporto il Titolare può esportare i propri dati
        e i report e cancellare documenti, pratiche o l’intero account. Alla
        cessazione del contratto Diligenx cancella i dati trattati per conto del
        Titolare entro trenta giorni, salvo che il Titolare li abbia già
        cancellati o che la legge ne imponga la conservazione. Le copie di
        backup sono sovrascritte entro [N] giorni secondo i normali cicli di
        rotazione e, nel frattempo, non sono usate per alcuna finalità.
        Diligenx conferma la cancellazione per iscritto su richiesta.
      </p>

      <h2>12. Informazioni e verifiche</h2>
      <p>
        Diligenx mette a disposizione del Titolare le informazioni necessarie a
        dimostrare il rispetto dell’art. 28 GDPR, anche rispondendo a
        questionari di sicurezza e fornendo, se disponibili, le certificazioni e
        le relazioni di verifica dei Sub-responsabili. Se queste informazioni
        non bastano, o se lo richiede un’autorità di controllo, il Titolare può
        svolgere un audit, direttamente o tramite un revisore indipendente
        vincolato alla riservatezza, non più di una volta l’anno salvo dopo una
        violazione, con preavviso scritto di almeno trenta giorni, in orario
        lavorativo e senza accesso ai dati di altri clienti. I costi dell’audit
        sono a carico del Titolare.
      </p>

      <h2>13. Responsabilità, durata e legge applicabile</h2>
      <p>
        La responsabilità delle parti per il DPA è regolata dai Termini di
        Servizio, comprese le limitazioni dell’art. 13, fermi i diritti degli
        interessati ai sensi dell’art. 82 GDPR. Il DPA ha la stessa durata del
        contratto e le sue disposizioni restano efficaci finché Diligenx tratta
        dati per conto del Titolare. È regolato dalla legge italiana; per ogni
        controversia è competente in via esclusiva il Foro di Milano.
      </p>

      <h2>Allegato 1. Descrizione del trattamento</h2>
      <ul>
        <li>
          <strong>Finalità e natura</strong>: archiviazione, estrazione del testo
          (anche con riconoscimento ottico dei caratteri), indicizzazione
          semantica, analisi con modelli linguistici, produzione di rilievi,
          risposte e report per la due diligence condotta dal Titolare.
        </li>
        <li>
          <strong>Interessati</strong>: le persone fisiche citate nei documenti,
          tra cui soci, amministratori, sindaci, procuratori, dipendenti e
          collaboratori, controparti contrattuali e loro rappresentanti,
          consulenti.
        </li>
        <li>
          <strong>Categorie di dati</strong>: dati anagrafici e identificativi
          (nome, codice fiscale, data e luogo di nascita, documenti d’identità),
          dati di contatto, ruoli e cariche, partecipazioni, dati contrattuali,
          retributivi, economici e fiscali.
        </li>
        <li>
          <strong>Dati di categorie particolari o giudiziari</strong>: non
          richiesti dal Servizio, ma possibili se contenuti nei documenti
          caricati (per esempio certificati medici in fascicoli del personale,
          carichi pendenti o certificati penali).
        </li>
        <li>
          <strong>Frequenza</strong>: continuativa, a ogni caricamento,
          analisi, domanda o generazione di report.
        </li>
        <li>
          <strong>Durata</strong>: per la durata del contratto, fino alla
          cancellazione dei dati da parte del Titolare o ai sensi dell’art. 11.
        </li>
      </ul>

      <h2>Allegato 2. Misure di sicurezza</h2>
      <p>
        Le misure sono descritte nella pagina <a href="/security">Sicurezza</a>,
        che costituisce parte integrante di questo allegato nella versione
        vigente. Comprendono in sintesi: localizzazione in UE di database,
        server applicativi e file; cifratura in transito e a riposo;
        autenticazione con cookie di sessione protetti e accesso federato
        Microsoft e Google; isolamento tra clienti con controlli applicativi e
        Row-Level Security forzata nel database; limitazione degli accessi del
        personale; verifica delle citazioni prodotte dall’intelligenza
        artificiale; procedura di gestione degli incidenti e di segnalazione
        delle vulnerabilità.
      </p>

      <h2 id="subprocessor">Allegato 3. Sub-responsabili</h2>
      <div className="overflow-x-auto">
        <table>
          <thead>
            <tr>
              <th>Sub-responsabile</th>
              <th>Attività</th>
              <th>Luogo del trattamento</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Railway Corp.</td>
              <td>Server applicativi, elaborazione delle analisi, coda dei lavori</td>
              <td>UE (Paesi Bassi)</td>
            </tr>
            <tr>
              <td>Neon, Inc.</td>
              <td>Database</td>
              <td>UE (Francoforte, Germania)</td>
            </tr>
            <tr>
              <td>Cloudflare, Inc.</td>
              <td>Archiviazione dei file caricati (R2)</td>
              <td>[REGIONE R2]</td>
            </tr>
            <tr>
              <td>Vercel Inc.</td>
              <td>Interfaccia web e inoltro delle richieste al backend</td>
              <td>Stati Uniti</td>
            </tr>
            <tr>
              <td>OpenAI, L.L.C. / OpenAI Ireland Ltd</td>
              <td>Modelli linguistici per l’analisi e le risposte; indicizzazione semantica</td>
              <td>Stati Uniti</td>
            </tr>
            <tr>
              <td>Anthropic, PBC / Anthropic Ireland, Limited</td>
              <td>Modelli linguistici per la sintesi dei rilievi, la verifica delle citazioni e il riepilogo del report</td>
              <td>Stati Uniti</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p>
        I fornitori di modelli linguistici non usano i dati per l’addestramento
        e li conservano per non più di trenta giorni a fini di sicurezza e
        prevenzione degli abusi, salvo la più lunga conservazione dei soli
        contenuti segnalati per violazione delle loro politiche d’uso.
      </p>
    </LegalLayout>
  )
}
