import LegalLayout from '@/components/legal/LegalLayout'

export const metadata = {
  title: 'Privacy Policy',
  description: 'Informativa sul trattamento dei dati personali ai sensi degli artt. 13 e 14 GDPR.',
}

export default function PrivacyPolicyPage() {
  return (
    <LegalLayout
      title="Privacy Policy"
      subtitle="Informativa sul trattamento dei dati personali ai sensi degli artt. 13 e 14 del Reg. (UE) 2016/679 (GDPR)."
      lastUpdated="13/10/2026"
    >
      <h2>1. Titolare del trattamento</h2>
      <p>
        Il titolare del trattamento è <strong>[RAGIONE SOCIALE]</strong>, con
        sede legale in [SEDE], P.IVA [P.IVA], PEC [PEC] (“<strong>Diligenx</strong>”).
        Per qualsiasi richiesta sul trattamento dei dati personali:{' '}
        <a href="mailto:privacy@diligenx.it">privacy@diligenx.it</a>.
        Diligenx non ha nominato un responsabile della protezione dei dati
        (DPO), non essendovi tenuta ai sensi dell’art. 37 GDPR.
      </p>

      <h2>2. A chi si rivolge questa informativa</h2>
      <p>
        L’informativa riguarda i dati personali che Diligenx tratta come
        titolare: quelli degli utenti che si registrano e usano la piattaforma,
        dei referenti dei clienti e di chi visita il sito o scrive a Diligenx.
      </p>
      <p>
        <strong>Non riguarda i documenti caricati nella piattaforma.</strong>{' '}
        Contratti, atti societari, documenti fiscali e gli altri materiali di una
        data room contengono spesso dati di terzi (soci, amministratori,
        dipendenti, controparti). Per questi dati il titolare è il cliente che li
        carica, normalmente lo studio o la società che svolge la due diligence,
        e Diligenx li tratta come responsabile ai sensi dell’art. 28 GDPR, solo
        su istruzione del cliente e alle condizioni del{' '}
        <a href="/dpa">Data Processing Agreement</a>. Chi ritiene che i propri
        dati compaiano in un documento analizzato con Diligenx può rivolgersi al
        cliente titolare; se scrive a Diligenx, la richiesta viene inoltrata al
        cliente interessato.
      </p>

      <h2>3. Dati trattati e loro origine</h2>
      <ul>
        <li>
          <strong>Dati dell’account</strong>: indirizzo email, nome (se
          indicato), password, conservata solo in forma di hash bcrypt e mai in
          chiaro.
        </li>
        <li>
          <strong>Accesso con Microsoft o Google</strong>: se l’utente sceglie
          questo metodo, Diligenx riceve dal fornitore l’identificativo
          dell’account, l’indirizzo email e l’indicazione che l’indirizzo è
          verificato. Sono dati che Diligenx non raccoglie presso l’utente ma
          presso Microsoft o Google (art. 14 GDPR), su sua iniziativa. Diligenx
          non riceve la password dell’account Microsoft o Google né accede alla
          posta, ai contatti o ai file.
        </li>
        <li>
          <strong>Crediti e fatturazione</strong>: saldo dei crediti, movimenti
          (accrediti, addebiti, riaccrediti, con data e pratica di
          riferimento), dati di fatturazione del cliente.
        </li>
        <li>
          <strong>Utilizzo del Servizio</strong>: workspace e pratiche create,
          stato delle analisi, domande poste sui documenti, report generati.
        </li>
        <li>
          <strong>Dati tecnici e di sicurezza</strong>: indirizzo IP, data e ora
          delle richieste, pagine e funzioni richieste, esito, tipo di browser,
          registrati nei log dei server.
        </li>
        <li>
          <strong>Comunicazioni</strong>: il contenuto delle email inviate a
          Diligenx per assistenza o altre richieste.
        </li>
        <li>
          <strong>Cookie tecnici</strong>: i soli cookie necessari alla sessione
          e alle preferenze, descritti nella <a href="/cookies">Cookie Policy</a>.
          Diligenx non usa cookie di profilazione, strumenti di analisi di terze
          parti né pixel pubblicitari.
        </li>
      </ul>

      <h2>4. Finalità e basi giuridiche</h2>
      <div className="overflow-x-auto">
        <table>
          <thead>
            <tr>
              <th>Finalità</th>
              <th>Base giuridica</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                Creare e gestire l’account, autenticare l’utente, erogare il
                Servizio, gestire i crediti, prestare assistenza e inviare le
                comunicazioni di servizio (per esempio reset della password,
                avvisi sulle modifiche ai Termini)
              </td>
              <td>Esecuzione del contratto (art. 6.1.b GDPR)</td>
            </tr>
            <tr>
              <td>Fatturazione, contabilità e adempimenti fiscali</td>
              <td>Obbligo di legge (art. 6.1.c GDPR)</td>
            </tr>
            <tr>
              <td>
                Proteggere il Servizio e i dati dei clienti: prevenire accessi
                non autorizzati e abusi, individuare e gestire incidenti di
                sicurezza
              </td>
              <td>
                Legittimo interesse di Diligenx e dei suoi clienti alla sicurezza
                del Servizio (art. 6.1.f GDPR)
              </td>
            </tr>
            <tr>
              <td>Accertare, esercitare o difendere un diritto in sede giudiziaria</td>
              <td>Legittimo interesse (art. 6.1.f GDPR)</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p>
        Diligenx non invia comunicazioni promozionali. Se in futuro intendesse
        farlo, chiederà un consenso specifico o, per i clienti, si limiterà a
        servizi analoghi offrendo in ogni messaggio la possibilità di opporsi.
      </p>

      <h2>5. Conferimento dei dati</h2>
      <p>
        L’indirizzo email e una password (o un account Microsoft o Google) sono
        necessari per creare l’account; senza, non è possibile usare il
        Servizio. I dati tecnici sono raccolti automaticamente durante l’uso. Il
        nome è facoltativo.
      </p>

      <h2>6. A chi sono comunicati i dati</h2>
      <p>
        I dati sono trattati dal personale di Diligenx autorizzato e vincolato
        alla riservatezza, e dai fornitori che seguono, nominati responsabili
        del trattamento con contratto ai sensi dell’art. 28 GDPR. Ogni fornitore
        riceve solo i dati necessari alla propria funzione.
      </p>
      <div className="overflow-x-auto">
        <table>
          <thead>
            <tr>
              <th>Fornitore</th>
              <th>Funzione</th>
              <th>Dove sono trattati i dati</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Vercel Inc.</td>
              <td>Hosting dell’interfaccia web</td>
              <td>Stati Uniti (Washington, D.C.), con rete di distribuzione globale</td>
            </tr>
            <tr>
              <td>Railway Corp.</td>
              <td>Server applicativi, elaborazione delle analisi, code di lavoro</td>
              <td>UE (Paesi Bassi)</td>
            </tr>
            <tr>
              <td>Neon Inc.</td>
              <td>Database</td>
              <td>UE (Francoforte, Germania)</td>
            </tr>
            <tr>
              <td>Cloudflare Inc.</td>
              <td>Archiviazione dei file caricati (R2)</td>
              <td>[REGIONE R2]</td>
            </tr>
            <tr>
              <td>OpenAI, L.L.C. / OpenAI Ireland Ltd</td>
              <td>Modelli linguistici per l’analisi dei documenti e le risposte; indicizzazione semantica</td>
              <td>Stati Uniti</td>
            </tr>
            <tr>
              <td>Anthropic, PBC / Anthropic Ireland, Limited</td>
              <td>Modelli linguistici per la sintesi dei rilievi, la verifica delle citazioni e il riepilogo del report</td>
              <td>Stati Uniti</td>
            </tr>
            <tr>
              <td>[FORNITORE EMAIL]</td>
              <td>Invio delle email di servizio (es. reset password)</td>
              <td>[PAESE]</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p>
        I fornitori di modelli linguistici ricevono il testo dei documenti da
        analizzare, non i dati dell’account. Per contratto non usano i dati per
        addestrare i propri modelli e li conservano per un periodo limitato, non
        superiore a trenta giorni, a fini di sicurezza e prevenzione degli abusi,
        salvo la più lunga conservazione dei soli contenuti segnalati per
        violazione delle loro politiche d’uso.
      </p>
      <p>
        Per l’accesso con Microsoft o Google, Microsoft Corporation e Google LLC
        operano come titolari autonomi del trattamento dei dati del proprio
        account, secondo le rispettive informative. I dati possono infine essere
        comunicati alle autorità che ne facciano richiesta in base alla legge.
        Non sono venduti né ceduti a terzi per finalità proprie.
      </p>

      <h2>7. Trasferimenti fuori dallo Spazio economico europeo</h2>
      <p>
        Alcuni fornitori hanno sede negli Stati Uniti o vi trattano dati. I
        trasferimenti avvengono sulla base della decisione di adeguatezza della
        Commissione europea del 10 luglio 2023 (EU-U.S. Data Privacy Framework),
        per i fornitori che vi hanno aderito, e in ogni caso delle Clausole
        Contrattuali Standard approvate con Decisione di esecuzione (UE)
        2021/914, con misure supplementari come la cifratura dei dati in
        transito. Copia delle garanzie può essere richiesta a{' '}
        <a href="mailto:privacy@diligenx.it">privacy@diligenx.it</a>.
      </p>

      <h2>8. Per quanto tempo sono conservati</h2>
      <ul>
        <li>
          <strong>Account, utilizzo del Servizio e movimenti dei crediti</strong>:
          fino alla cancellazione dell’account, che l’utente può chiedere o
          eseguire in qualsiasi momento.
        </li>
        <li>
          <strong>Documenti di fatturazione e scritture contabili</strong>: dieci
          anni, come previsto dall’art. 2220 c.c.
        </li>
        <li>
          <strong>Log tecnici</strong>: [N] giorni, salvo che servano per
          accertare un incidente o un abuso, per il tempo necessario.
        </li>
        <li>
          <strong>Copie di backup</strong>: sovrascritte entro [N] giorni
          secondo i cicli di rotazione.
        </li>
        <li>
          <strong>Comunicazioni</strong>: per il tempo necessario a gestire la
          richiesta e, se riguardano il contratto, per la sua durata.
        </li>
      </ul>
      <p>
        Trascorsi questi termini i dati sono cancellati o resi anonimi. Nel
        caso di contestazioni, i dati utili possono essere conservati fino alla
        definizione della controversia.
      </p>

      <h2>9. Sicurezza</h2>
      <p>
        Diligenx adotta misure tecniche e organizzative adeguate al rischio
        (art. 32 GDPR), descritte nella pagina <a href="/security">Sicurezza</a>.
      </p>

      <h2>10. Decisioni automatizzate</h2>
      <p>
        Il Servizio usa l’intelligenza artificiale per analizzare documenti per
        conto dei clienti. Diligenx non adotta nei confronti degli utenti
        decisioni basate unicamente su un trattamento automatizzato che
        producano effetti giuridici o incidano in modo analogo sulla loro
        persona (art. 22 GDPR) e non effettua profilazione.
      </p>

      <h2>11. Diritti dell’interessato</h2>
      <p>
        L’interessato può chiedere in ogni momento l’accesso ai propri dati, la
        rettifica, la cancellazione, la limitazione del trattamento e la
        portabilità dei dati forniti (artt. 15-20 GDPR).
      </p>
      <p>
        <strong>Diritto di opposizione.</strong> L’interessato può opporsi in
        qualsiasi momento, per motivi connessi alla sua situazione particolare,
        ai trattamenti basati sul legittimo interesse (art. 21 GDPR).
      </p>
      <p>
        Dalla pagina Account l’utente può scaricare in autonomia una copia dei
        propri dati in formato strutturato e cancellare l’account con tutti i
        contenuti. Per ogni altra richiesta può scrivere a{' '}
        <a href="mailto:privacy@diligenx.it">privacy@diligenx.it</a>; Diligenx
        risponde entro un mese, prorogabile nei casi previsti dall’art. 12 GDPR.
        Resta salvo il diritto di proporre reclamo al{' '}
        <a href="https://www.garanteprivacy.it" target="_blank" rel="noopener noreferrer">
          Garante per la protezione dei dati personali
        </a>{' '}
        o all’autorità di controllo dello Stato UE in cui l’interessato risiede o
        lavora.
      </p>

      <h2>12. Modifiche</h2>
      <p>
        Diligenx può aggiornare questa informativa, per esempio quando cambia un
        fornitore. La data dell’ultimo aggiornamento è indicata in testa alla
        pagina; delle modifiche sostanziali gli utenti registrati sono informati
        via email.
      </p>
    </LegalLayout>
  )
}
