import LegalLayout from '@/components/legal/LegalLayout'

export const metadata = {
  title: 'Data Processing Agreement — Diligenx',
  description: 'Accordo sul trattamento dei dati ex art. 28 GDPR.',
}

export default function DpaPage() {
  return (
    <LegalLayout
      title="Data Processing Agreement"
      subtitle="Accordo sul trattamento dei dati ex art. 28 Reg. (UE) 2016/679 (GDPR)."
    >
      <h2>1. Parti</h2>
      <p>
        Il presente DPA è concluso tra l&apos;Utente in qualità di{' '}
        <strong>Titolare del trattamento</strong> (in particolare per i dati
        dei propri clienti finali contenuti nei documenti caricati) e{' '}
        <strong>Diligenx</strong> in qualità di{' '}
        <strong>Responsabile del trattamento</strong>.
      </p>

      <h2>2. Oggetto</h2>
      <p>
        Diligenx tratta i dati personali per conto del Titolare al solo
        scopo di erogare il Servizio descritto nei{' '}
        <a href="/terms">Termini di Servizio</a> (analisi documentale,
        estrazione clausole, generazione report).
      </p>

      <h2>3. Durata</h2>
      <p>
        Il presente DPA ha la stessa durata del contratto principale e cessa
        al momento della cessazione del medesimo.
      </p>

      <h2>4. Natura e categoria dei dati</h2>
      <ul>
        <li><strong>Categorie di interessati</strong>: parti contrattuali, amministratori, dipendenti, terzi citati nei documenti caricati.</li>
        <li><strong>Categorie di dati</strong>: dati di identificazione (nome, cognome, codice fiscale, P.IVA), dati di contatto, dati professionali, dati contrattuali.</li>
        <li>Diligenx <strong>non tratta categorie particolari</strong> ex art. 9 GDPR salvo casi in cui esse siano incidentalmente contenute nei documenti caricati dal Titolare.</li>
      </ul>

      <h2>5. Obblighi di Diligenx</h2>
      <ul>
        <li>Trattare i dati esclusivamente sulla base di istruzioni documentate del Titolare.</li>
        <li>Garantire la riservatezza del personale autorizzato.</li>
        <li>Adottare misure tecniche e organizzative adeguate ex art. 32 GDPR (cfr. <a href="/security">Security Overview</a>).</li>
        <li>Notificare al Titolare ogni violazione dei dati senza ingiustificato ritardo e comunque entro 72 ore.</li>
        <li>Assistere il Titolare nel riscontro delle richieste degli interessati.</li>
        <li>Mettere a disposizione le informazioni necessarie a dimostrare la conformità.</li>
      </ul>

      <h2>6. Subprocessor</h2>
      <p id="subprocessor">
        L&apos;Utente autorizza Diligenx ad avvalersi dei seguenti subprocessor.
        Eventuali modifiche saranno comunicate con preavviso di almeno 30
        giorni, con facoltà di opposizione motivata da parte del Titolare.
      </p>
      <div className="overflow-x-auto">
        <table>
          <thead>
            <tr>
              <th>Subprocessor</th>
              <th>Funzione</th>
              <th>Sede</th>
              <th>Region dati</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Vercel Inc.</td>
              <td>Hosting frontend</td>
              <td>USA</td>
              <td>Edge globale</td>
            </tr>
            <tr>
              <td>Railway Corp.</td>
              <td>Hosting backend e database</td>
              <td>USA</td>
              <td>us-east4 (Virginia)</td>
            </tr>
            <tr>
              <td>Cloudflare R2</td>
              <td>Storage file</td>
              <td>USA / EU</td>
              <td>EU (jurisdiction)</td>
            </tr>
            <tr>
              <td>Anthropic PBC</td>
              <td>Modelli linguistici (Claude)</td>
              <td>USA</td>
              <td>USA</td>
            </tr>
            <tr>
              <td>OpenAI L.L.C.</td>
              <td>Embedding semantici</td>
              <td>USA</td>
              <td>USA</td>
            </tr>
          </tbody>
        </table>
      </div>

      <h2>7. Trasferimenti extra-SEE</h2>
      <p>
        Per i trasferimenti verso gli Stati Uniti, Diligenx adotta le
        Clausole Contrattuali Standard (Decisione UE 2021/914) ed eventuali
        misure supplementari (cifratura in transito TLS 1.3, accordi
        contrattuali di no-training con i fornitori di modelli AI).
      </p>

      <h2>8. Audit</h2>
      <p>
        Il Titolare ha il diritto di richiedere informazioni sulle misure
        adottate e, previo congruo preavviso scritto, di svolgere audit con
        frequenza non superiore a una volta all&apos;anno, secondo modalità
        concordate.
      </p>

      <h2>9. Cessazione e restituzione dei dati</h2>
      <p>
        Alla cessazione del rapporto, Diligenx provvederà — a scelta del
        Titolare — alla restituzione o alla cancellazione di tutti i dati
        personali trattati per conto del Titolare, salvo diversi obblighi
        di legge.
      </p>

      <h2>10. Legge applicabile</h2>
      <p>
        Il presente DPA è regolato dalla legge italiana e dal Regolamento
        UE 2016/679.
      </p>
    </LegalLayout>
  )
}
