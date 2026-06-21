import LegalLayout from '@/components/legal/LegalLayout'

export const metadata = {
  title: 'Termini di Servizio — Diligenx',
  description: 'Condizioni generali di servizio.',
}

export default function TermsPage() {
  return (
    <LegalLayout
      title="Termini di Servizio"
      subtitle="Condizioni generali che regolano l'utilizzo del servizio Diligenx."
    >
      <h2>1. Definizioni</h2>
      <ul>
        <li><strong>Servizio</strong>: la piattaforma SaaS Diligenx erogata in modalità cloud.</li>
        <li><strong>Utente</strong>: la persona fisica o giuridica che accede al Servizio.</li>
        <li><strong>Contenuti</strong>: documenti, testi e materiali caricati dall&apos;Utente.</li>
        <li><strong>Output AI</strong>: l&apos;esito automatico dell&apos;analisi dei Contenuti.</li>
      </ul>

      <h2>2. Oggetto del Servizio</h2>
      <p>
        Diligenx fornisce un&apos;assistenza alla due diligence legale basata su
        intelligenza artificiale. Il Servizio estrae clausole, segnala
        criticità e genera report strutturati a partire dai documenti
        caricati dall&apos;Utente.
      </p>

      <h2>3. Natura assistiva dell&apos;Output AI</h2>
      <p>
        L&apos;Output AI ha natura <strong>esclusivamente assistiva</strong>. Non
        costituisce parere legale, consulenza professionale, garanzia di
        completezza o accuratezza. Le decisioni operative restano in capo
        all&apos;Utente che è tenuto a verificare ogni risultato prima dell&apos;uso.
        Diligenx non si assume alcuna responsabilità per decisioni adottate
        sulla base dell&apos;Output AI.
      </p>

      <h2>4. Obblighi dell&apos;Utente</h2>
      <ul>
        <li>Caricare unicamente Contenuti su cui ha titolo legittimo.</li>
        <li>
          Informare i propri clienti finali del trattamento dei loro dati
          tramite il Servizio, ove necessario.
        </li>
        <li>
          Non caricare Contenuti vietati dalla legge o lesivi di diritti di
          terzi.
        </li>
        <li>Custodire credenziali e API key in modo sicuro.</li>
      </ul>

      <h2>5. Proprietà intellettuale</h2>
      <p>
        I Contenuti caricati restano di proprietà esclusiva dell&apos;Utente. I
        diritti di proprietà intellettuale sull&apos;Output AI sono concessi in
        licenza all&apos;Utente per le finalità del rapporto contrattuale. Il
        software, l&apos;interfaccia e le tecnologie di Diligenx restano di
        proprietà esclusiva di Diligenx.
      </p>

      <h2>6. Disponibilità del Servizio (SLA)</h2>
      <p>
        Diligenx adotta misure ragionevoli per garantire la disponibilità
        del Servizio. Non viene fornita una garanzia di disponibilità
        contrattualmente vincolante in fase di lancio. La presente clausola
        sarà sostituita da uno SLA formale per i piani enterprise.
      </p>

      <h2>7. Limitazione di responsabilità</h2>
      <p>
        Nei limiti consentiti dalla legge, la responsabilità complessiva di
        Diligenx verso l&apos;Utente per qualsiasi danno derivante dal Servizio è
        limitata al corrispettivo effettivamente pagato dall&apos;Utente nei
        dodici mesi precedenti l&apos;evento. Restano esclusi danni indiretti,
        perdite di profitto, perdita di opportunità commerciali.
      </p>

      <h2>8. Sospensione e cessazione</h2>
      <p>
        Diligenx può sospendere o cessare il Servizio in caso di uso non
        conforme, mancato pagamento o per ragioni di sicurezza. L&apos;Utente può
        in qualunque momento cancellare il proprio account e ottenere
        l&apos;esportazione dei propri dati.
      </p>

      <h2>9. Modifiche</h2>
      <p>
        Modifiche sostanziali a questi Termini saranno comunicate via email
        con almeno 30 giorni di preavviso.
      </p>

      <h2>10. Legge applicabile e foro</h2>
      <p>
        I presenti Termini sono regolati dalla legge italiana. Per ogni
        controversia è competente in via esclusiva il Foro di [SEDE], salva
        diversa indicazione di legge per il consumatore.
      </p>
    </LegalLayout>
  )
}
