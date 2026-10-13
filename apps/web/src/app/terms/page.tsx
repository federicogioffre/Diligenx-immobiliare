import LegalLayout from '@/components/legal/LegalLayout'

export const metadata = {
  title: 'Termini di Servizio',
  description: 'Condizioni generali di servizio della piattaforma Diligenx.',
}

export default function TermsPage() {
  return (
    <LegalLayout
      title="Termini di Servizio"
      subtitle="Condizioni generali che regolano l’uso della piattaforma Diligenx."
      lastUpdated="13/10/2026"
    >
      <h2>1. Fornitore e ambito</h2>
      <p>
        Il servizio Diligenx è fornito da <strong>[RAGIONE SOCIALE]</strong>, con
        sede legale in [SEDE], P.IVA [P.IVA], iscritta al Registro delle Imprese
        di [CITTÀ] al n. REA [REA], PEC [PEC] (“<strong>Diligenx</strong>”). Per
        comunicazioni ordinarie: <a href="mailto:privacy@diligenx.it">privacy@diligenx.it</a>.
      </p>
      <p>
        I presenti termini (i “<strong>Termini</strong>”) regolano l’accesso e
        l’uso della piattaforma raggiungibile su diligenx.it e dei relativi
        servizi (il “<strong>Servizio</strong>”). Ne fanno parte integrante la{' '}
        <a href="/privacy">Privacy Policy</a>, la <a href="/cookies">Cookie Policy</a>{' '}
        e il <a href="/dpa">Data Processing Agreement</a> (“<strong>DPA</strong>”).
        In caso di contrasto, prevale l’accordo sottoscritto per iscritto con il
        singolo cliente, se esistente, poi il DPA per quanto riguarda i dati
        personali, poi i presenti Termini.
      </p>

      <h2>2. Destinatari: solo professionisti e imprese</h2>
      <p>
        Il Servizio è riservato a professionisti, studi professionali, società
        e altri enti che agiscono nell’esercizio della propria attività
        imprenditoriale o professionale (il “<strong>Cliente</strong>”). Non è
        destinato a consumatori ai sensi del D.Lgs. 206/2005. Chi crea un
        account per conto di uno studio o di una società dichiara di avere il
        potere di vincolarli ai presenti Termini; le persone autorizzate dal
        Cliente a usare il Servizio sono gli “<strong>Utenti</strong>”.
      </p>

      <h2>3. Il Servizio</h2>
      <p>
        Diligenx è uno strumento di supporto alla due diligence legale. Il
        Cliente carica documenti (contratti, atti societari, documenti fiscali e
        finanziari e simili, i “<strong>Contenuti</strong>”); il Servizio li
        estrae, li indicizza e li analizza con modelli di intelligenza
        artificiale, segnala clausole e criticità (red flag), risponde a domande
        sui documenti con l’indicazione delle fonti e genera un report
        esportabile (insieme, l’“<strong>Output</strong>”).
      </p>
      <p>
        Diligenx può aggiornare il Servizio, i modelli impiegati e le
        funzionalità, purché le modifiche non riducano in modo sostanziale le
        funzioni essenziali per cui il Cliente ha acquistato crediti ancora
        validi. Le funzioni indicate come “beta” o sperimentali sono fornite
        così come sono e possono essere modificate o ritirate in qualsiasi
        momento.
      </p>

      <h2>4. Natura dell’Output e responsabilità professionale</h2>
      <p>
        L’Output è generato automaticamente e ha natura <strong>esclusivamente
        assistiva</strong>. Non è un parere legale, fiscale o contabile e non
        sostituisce la due diligence svolta dai professionisti incaricati.
        Diligenx non è uno studio professionale e non presta consulenza.
      </p>
      <p>
        I sistemi di intelligenza artificiale possono commettere errori,
        omettere elementi rilevanti o interpretare in modo scorretto un
        documento, anche quando citano una fonte. Il Servizio applica controlli
        di verifica delle citazioni, che riducono il rischio ma non lo
        eliminano. Il Cliente si impegna a:
      </p>
      <ul>
        <li>
          verificare l’Output sui documenti originali prima di usarlo, tramite
          un professionista competente;
        </li>
        <li>
          non basare decisioni che producono effetti giuridici su persone
          fisiche esclusivamente sull’Output, senza un esame umano;
        </li>
        <li>
          adempiere ai propri obblighi professionali e deontologici, incluso
          l’obbligo di informare i propri clienti sull’uso di sistemi di
          intelligenza artificiale previsto dall’art. 13 della L. 23 settembre
          2025, n. 132.
        </li>
      </ul>
      <p>
        Le valutazioni professionali, le scelte negoziali e i contenuti dei
        documenti consegnati ai propri clienti restano di esclusiva
        responsabilità del Cliente.
      </p>

      <h2>5. Account e credenziali</h2>
      <p>
        L’accesso avviene con email e password oppure con un account Microsoft
        o Google. Il Cliente custodisce le credenziali, risponde dell’attività
        svolta con il proprio account e comunica senza ritardo a{' '}
        <a href="mailto:security@diligenx.it">security@diligenx.it</a> ogni uso
        non autorizzato di cui venga a conoscenza. I dati di registrazione
        devono essere veritieri e aggiornati.
      </p>

      <h2>6. Uso consentito</h2>
      <p>Il Cliente non può, direttamente o tramite terzi:</p>
      <ul>
        <li>
          caricare Contenuti che non ha titolo per trattare, o il cui
          trattamento violi obblighi di legge, di riservatezza o di segreto
          professionale;
        </li>
        <li>
          usare il Servizio per finalità illecite o per sviluppare un prodotto
          concorrente;
        </li>
        <li>
          aggirare le misure di sicurezza, i limiti di utilizzo o il sistema di
          crediti, né accedere ai dati di altri clienti;
        </li>
        <li>
          sottoporre il Servizio a test di carico, scansioni o tentativi di
          intrusione senza autorizzazione scritta (per le segnalazioni di
          vulnerabilità vale quanto indicato nella pagina{' '}
          <a href="/security">Sicurezza</a>);
        </li>
        <li>
          estrarre in modo automatizzato l’Output o il codice del Servizio,
          decompilarlo o decodificarlo, salvo nei limiti inderogabili di legge.
        </li>
      </ul>

      <h2>7. Contenuti del Cliente e dati personali</h2>
      <p>
        I Contenuti e l’Output restano del Cliente. Il Cliente concede a
        Diligenx, per la durata del rapporto, il diritto non esclusivo di
        conservare, elaborare e trasmettere i Contenuti ai fornitori indicati
        nel DPA nella sola misura necessaria a erogare il Servizio, a garantirne
        la sicurezza e ad assistere il Cliente.
      </p>
      <p>
        <strong>Nessun addestramento.</strong> Diligenx non usa i Contenuti né
        l’Output per addestrare o migliorare modelli di intelligenza artificiale,
        propri o di terzi. I fornitori dei modelli (OpenAI e Anthropic) sono
        vincolati contrattualmente a non usarli per l’addestramento e li
        conservano solo per il tempo indicato nella Privacy Policy, per finalità
        di sicurezza e prevenzione degli abusi.
      </p>
      <p>
        Per i dati personali contenuti nei documenti caricati il Cliente è
        titolare del trattamento e Diligenx è responsabile ai sensi dell’art. 28
        del Reg. (UE) 2016/679 (“<strong>GDPR</strong>”), alle condizioni del
        DPA, che il Cliente accetta insieme ai presenti Termini. Il Cliente
        garantisce di disporre di una base giuridica per il trattamento, di
        aver fornito agli interessati le informazioni dovute (o di essere
        esonerato, per esempio in forza del segreto professionale) e di
        limitare i dati caricati a quelli necessari per l’incarico.
      </p>

      <h2>8. Crediti</h2>
      <p>
        Le analisi e alcune altre funzioni si pagano con crediti prepagati
        (“<strong>Crediti</strong>”), secondo le regole che seguono.
      </p>
      <ul>
        <li>
          <strong>Costo.</strong> Un’analisi costa un Credito per ogni pagina dei
          documenti analizzati. Per i documenti senza numero di pagine si
          considera una pagina ogni 3.000 caratteri, con un minimo di una pagina
          per documento. Una domanda sui documenti e la rigenerazione di un
          report hanno il costo indicato nella piattaforma prima della
          conferma. Il costo di un’analisi è mostrato, insieme al saldo, prima
          dell’avvio.
        </li>
        <li>
          <strong>Addebito e riaccredito.</strong> I Crediti sono addebitati
          all’avvio dell’operazione. Sono riaccreditati automaticamente se
          l’analisi non può essere avviata o se la domanda o la generazione del
          report non vanno a buon fine; la ripresa di un’analisi interrotta non
          comporta nuovi addebiti.
        </li>
        <li>
          <strong>Acquisto.</strong> Ai nuovi account può essere attribuito un
          numero di Crediti gratuiti indicato al momento della registrazione.
          Ulteriori Crediti si acquistano alle condizioni economiche indicate
          nell’offerta o nell’ordine; i prezzi si intendono al netto di IVA.
        </li>
        <li>
          <strong>Scadenza.</strong> I Crediti scadono <strong>dodici mesi</strong>{' '}
          dopo l’accredito; quelli non utilizzati entro tale termine non sono
          più utilizzabili né rimborsabili.
        </li>
        <li>
          <strong>Rimborsi.</strong> I Crediti acquistati non sono rimborsabili
          né convertibili in denaro e non sono cedibili a terzi, salvo il caso di
          addebito errato o di disservizio imputabile a Diligenx che abbia
          impedito di usarli, e salvo quanto previsto all’art. 11 per il recesso
          di Diligenx.
        </li>
      </ul>
      <p>
        Il saldo e i movimenti sono consultabili nella pagina Account. Eventuali
        contestazioni su un addebito vanno inviate entro sessanta giorni dal
        movimento.
      </p>

      <h2>9. Disponibilità e assistenza</h2>
      <p>
        Diligenx si impegna con diligenza professionale a mantenere il Servizio
        disponibile e funzionante, ma non garantisce un livello minimo di
        disponibilità salvo che sia pattuito per iscritto. Il Servizio può essere
        sospeso per manutenzione, preferibilmente in orari di basso utilizzo e,
        per gli interventi programmati di durata significativa, con preavviso
        nella piattaforma. Il Servizio dipende anche da fornitori terzi
        (hosting, archiviazione, modelli di intelligenza artificiale), le cui
        interruzioni possono incidere sulla disponibilità.
      </p>
      <p>
        L’assistenza è prestata via email, nei giorni lavorativi, senza tempi
        di risposta garantiti salvo diverso accordo.
      </p>

      <h2>10. Riservatezza</h2>
      <p>
        Diligenx tratta come riservati i Contenuti, l’Output e ogni informazione
        non pubblica del Cliente, li usa solo per erogare il Servizio e ne
        consente l’accesso al proprio personale e ai propri fornitori solo se
        necessario e sotto vincolo di riservatezza. L’obbligo non si applica alle
        informazioni già pubbliche senza colpa di Diligenx o che devono essere
        comunicate per ordine dell’autorità; in quest’ultimo caso Diligenx, se
        consentito, avvisa prima il Cliente.
      </p>

      <h2>11. Durata, sospensione e cessazione</h2>
      <p>
        I Termini si applicano dalla registrazione e restano efficaci a tempo
        indeterminato. Il Cliente può cessare in qualsiasi momento cancellando
        l’account dalla pagina Account: la cancellazione elimina subito
        documenti, analisi e report; le copie di backup sono sovrascritte entro
        [N] giorni secondo i cicli di rotazione. Prima di cancellare, il Cliente
        può esportare i propri dati e i report.
      </p>
      <p>
        Diligenx può recedere con un preavviso di trenta giorni comunicato via
        email; in tal caso rimborsa i Crediti acquistati e non ancora scaduti,
        e il Cliente può esportare i propri dati fino alla data di efficacia del
        recesso, dopo la quale i dati sono cancellati.
      </p>
      <p>
        Diligenx può sospendere l’account, con effetto immediato e limitatamente
        a quanto necessario, se il Cliente viola gli artt. 6 o 7, se l’uso del
        Servizio mette a rischio la sicurezza di Diligenx o di altri clienti, o
        se lo impone un’autorità. Diligenx informa il Cliente della sospensione
        e dei motivi e la revoca quando la causa viene meno. In caso di
        violazione grave o non rimediata entro quindici giorni dalla
        contestazione, Diligenx può risolvere il rapporto ai sensi
        dell’art. 1456 c.c.; i Crediti residui non sono rimborsati.
      </p>

      <h2>12. Proprietà intellettuale</h2>
      <p>
        Il software, l’interfaccia, i modelli di analisi, i prompt e la
        documentazione del Servizio, con i relativi marchi, appartengono a
        Diligenx o ai suoi licenzianti. Al Cliente è concesso un diritto
        personale, non esclusivo e non trasferibile di usare il Servizio per
        la durata del rapporto e per la propria attività. I suggerimenti che il
        Cliente invia per migliorare il Servizio possono essere usati da
        Diligenx liberamente, senza obblighi di compenso, purché non contengano
        Contenuti o informazioni riservate del Cliente.
      </p>

      <h2>13. Garanzie e limitazione di responsabilità</h2>
      <p>
        Salvo quanto previsto espressamente nei presenti Termini, il Servizio è
        fornito senza garanzie di idoneità a uno scopo particolare né di
        completezza o accuratezza dell’Output (art. 4).
      </p>
      <p>
        Diligenx non risponde dei danni indiretti, del mancato guadagno, della
        perdita di opportunità o di clientela, né dei danni derivanti da
        decisioni assunte sulla base dell’Output senza la verifica prevista
        all’art. 4. La responsabilità complessiva di Diligenx per tutte le
        pretese relative al Servizio è limitata all’importo pagato dal Cliente
        a Diligenx nei dodici mesi precedenti l’evento che l’ha originata o,
        se superiore, a [100] euro.
      </p>
      <p>
        Le limitazioni di questo articolo non si applicano in caso di dolo o
        colpa grave di Diligenx, né ai casi in cui la legge non consente di
        limitare la responsabilità (art. 1229 c.c.).
      </p>

      <h2>14. Manleva</h2>
      <p>
        Il Cliente tiene indenne Diligenx dalle pretese di terzi, inclusi gli
        interessati e le autorità, derivanti dal caricamento di Contenuti in
        violazione dell’art. 7 o da un uso del Servizio contrario all’art. 6,
        compresi i ragionevoli costi di difesa.
      </p>

      <h2>15. Modifiche ai Termini</h2>
      <p>
        Diligenx può modificare i presenti Termini per adeguarli a cambiamenti
        normativi, tecnici o del Servizio. Le modifiche sostanziali sono
        comunicate via email con almeno trenta giorni di preavviso; entro
        quel termine il Cliente può recedere senza costi, con rimborso dei
        Crediti acquistati e non scaduti. In mancanza di recesso, le modifiche
        si applicano dalla data indicata. Le modifiche imposte dalla legge o
        dall’autorità possono avere effetto immediato.
      </p>

      <h2>16. Disposizioni generali</h2>
      <p>
        Le comunicazioni al Cliente sono inviate all’indirizzo email
        dell’account; quelle a Diligenx a{' '}
        <a href="mailto:privacy@diligenx.it">privacy@diligenx.it</a> o alla PEC
        indicata all’art. 1. Il Cliente non può cedere il rapporto senza il
        consenso di Diligenx, che può cederlo a una società del proprio gruppo
        o all’acquirente della propria azienda, dandone comunicazione.
        L’eventuale invalidità di una clausola non incide sulle altre. Nessuna
        delle parti risponde dei ritardi causati da eventi fuori dal proprio
        ragionevole controllo. Gli artt. 4, 7, 10, 12, 13, 14 e 17 restano
        efficaci anche dopo la cessazione.
      </p>

      <h2>17. Legge applicabile e foro competente</h2>
      <p>
        I presenti Termini sono regolati dalla legge italiana. Per ogni
        controversia relativa alla loro interpretazione, esecuzione o
        cessazione è competente in via esclusiva il Foro di Milano.
      </p>

      <h2>18. Approvazione specifica</h2>
      <p>
        Ai sensi e per gli effetti degli artt. 1341 e 1342 c.c., il Cliente
        approva specificamente le seguenti clausole: art. 3 (modifiche al
        Servizio); art. 4 (natura dell’Output e responsabilità professionale);
        art. 8 (scadenza dei Crediti, esclusione dei rimborsi, termine per le
        contestazioni); art. 9 (assenza di garanzia di disponibilità); art. 11
        (sospensione, recesso e clausola risolutiva espressa); art. 13
        (limitazione di responsabilità); art. 14 (manleva); art. 15
        (modifiche ai Termini); art. 16 (cessione del rapporto); art. 17 (foro
        esclusivo di Milano).
      </p>
    </LegalLayout>
  )
}
