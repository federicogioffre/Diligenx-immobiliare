import LegalLayout from '@/components/legal/LegalLayout'

export const metadata = {
  title: 'Privacy Policy — Diligenx',
  description: 'Informativa sul trattamento dei dati personali ex art. 13 GDPR.',
}

export default function PrivacyPolicyPage() {
  return (
    <LegalLayout
      title="Privacy Policy"
      subtitle="Informativa sul trattamento dei dati personali ex art. 13 Reg. (UE) 2016/679 (GDPR)."
    >
      <h2>1. Titolare del trattamento</h2>
      <p>
        Il titolare del trattamento è <strong>Diligenx</strong>, con sede legale
        in [INDIRIZZO], P.IVA [P.IVA]. Contatti: <a href="mailto:privacy@diligenx.example">privacy@diligenx.example</a>.
      </p>

      <h2>2. Categorie di dati trattati</h2>
      <ul>
        <li>
          <strong>Dati di registrazione</strong> — email, password (memorizzata in
          forma hashed con bcrypt), nome opzionale.
        </li>
        <li>
          <strong>Documenti caricati dall&apos;utente</strong> — file PDF, DOCX e TXT,
          incluso il loro contenuto. Possono contenere dati personali di terzi
          (es. clienti dello studio legale utente).
        </li>
        <li>
          <strong>Output strutturato dell&apos;analisi AI</strong> — clausole
          estratte, red flag, report.
        </li>
        <li>
          <strong>Log applicativi e di accesso</strong> — timestamp di accesso,
          azioni effettuate.
        </li>
      </ul>

      <h2>3. Finalità del trattamento</h2>
      <ul>
        <li>Erogazione del servizio (autenticazione, gestione workspace, analisi documenti).</li>
        <li>Adempimento di obblighi contrattuali e fiscali.</li>
        <li>Adempimento di obblighi di legge.</li>
        <li>Sicurezza del servizio (rilevamento abusi, prevenzione frodi).</li>
      </ul>

      <h2>4. Base giuridica</h2>
      <p>
        Esecuzione del contratto (art. 6.1.b GDPR) per l&apos;erogazione del
        servizio; obbligo di legge (art. 6.1.c) per fatturazione e
        conservazione; legittimo interesse (art. 6.1.f) per la sicurezza e
        prevenzione frodi.
      </p>

      <h2>5. Responsabile del trattamento (per dati dei clienti finali dello studio)</h2>
      <p>
        Quando l&apos;Utente è uno studio legale o consulente che carica documenti
        relativi a propri clienti, l&apos;Utente è <em>Titolare</em> e Diligenx opera
        in qualità di <em>Responsabile del trattamento</em> ex art. 28 GDPR. La
        nomina è regolata dal{' '}
        <a href="/dpa">Data Processing Agreement (DPA)</a>.
      </p>

      <h2>6. Subprocessor</h2>
      <p>
        Diligenx si avvale dei seguenti subprocessor per l&apos;erogazione del
        servizio. La lista aggiornata è disponibile nella{' '}
        <a href="/dpa#subprocessor">sezione subprocessor del DPA</a>.
      </p>
      <ul>
        <li><strong>Vercel Inc.</strong> (USA) — hosting frontend.</li>
        <li><strong>Railway Corp.</strong> (USA) — hosting backend e database.</li>
        <li><strong>Cloudflare R2</strong> (jurisdiction EU) — storage file.</li>
        <li><strong>Anthropic PBC</strong> (USA) — modelli linguistici per analisi.</li>
        <li><strong>OpenAI L.L.C.</strong> (USA) — embedding semantici.</li>
      </ul>

      <h2>7. Trasferimenti extra-SEE</h2>
      <p>
        Parte dei dati transita su infrastrutture localizzate negli Stati
        Uniti. Per tali trasferimenti Diligenx fa affidamento sulle Clausole
        Contrattuali Standard (SCC) approvate dalla Commissione Europea con
        Decisione 2021/914, integrate da misure supplementari (cifratura in
        transito TLS 1.3, accordi di no-training con i fornitori di AI).
      </p>

      <h2>8. Periodo di conservazione</h2>
      <p>
        I dati vengono conservati per la durata del rapporto contrattuale e
        per i periodi successivi imposti da obblighi di legge. L&apos;utente può
        richiedere in qualunque momento la cancellazione del proprio account
        e dei contenuti caricati.
      </p>

      <h2>9. Diritti dell&apos;interessato</h2>
      <p>
        L&apos;Utente può esercitare in qualunque momento i diritti di cui agli
        artt. 15-22 GDPR (accesso, rettifica, cancellazione, limitazione,
        portabilità, opposizione) scrivendo a{' '}
        <a href="mailto:privacy@diligenx.example">privacy@diligenx.example</a>.
        È inoltre possibile presentare reclamo al{' '}
        <a href="https://www.garanteprivacy.it" target="_blank" rel="noopener noreferrer">
          Garante per la Protezione dei Dati Personali
        </a>.
      </p>

      <h2>10. Modifiche a questa informativa</h2>
      <p>
        Diligenx si riserva di aggiornare la presente informativa. Modifiche
        sostanziali saranno comunicate via email agli utenti registrati.
      </p>
    </LegalLayout>
  )
}
