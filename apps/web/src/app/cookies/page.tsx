import LegalLayout from '@/components/legal/LegalLayout'

export const metadata = {
  title: 'Cookie Policy — Diligenx',
  description: 'Tipologie di cookie utilizzati e finalità.',
}

export default function CookiePolicyPage() {
  return (
    <LegalLayout
      title="Cookie Policy"
      subtitle="Informazioni sull'uso dei cookie ai sensi delle linee guida del Garante (maggio 2021) e Direttiva e-Privacy."
    >
      <h2>1. Cosa sono i cookie</h2>
      <p>
        I cookie sono piccoli file di testo che i siti visitati salvano nel
        browser dell&apos;utente per consentirne il corretto funzionamento e per
        raccogliere informazioni sulle visite.
      </p>

      <h2>2. Cookie utilizzati da Diligenx</h2>
      <p>
        Diligenx utilizza <strong>esclusivamente cookie tecnici</strong>,
        strettamente necessari al funzionamento del servizio. Non sono
        utilizzati cookie di profilazione, cookie di terze parti per
        marketing o tracker analytics che richiedano consenso preventivo.
      </p>

      <h3>2.1 Cookie tecnici di sessione</h3>
      <div className="overflow-x-auto">
        <table>
          <thead>
            <tr>
              <th>Nome</th>
              <th>Finalità</th>
              <th>Durata</th>
              <th>Tipo</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><code>dm_token</code></td>
              <td>Mantenere la sessione autenticata (JWT)</td>
              <td>7 giorni (o fino al logout)</td>
              <td>Tecnico, prima parte</td>
            </tr>
            <tr>
              <td><code>dm_workspace</code></td>
              <td>Memorizzare il workspace selezionato dall&apos;utente</td>
              <td>7 giorni</td>
              <td>Tecnico, prima parte</td>
            </tr>
            <tr>
              <td><code>dm_cookie_notice_dismissed</code></td>
              <td>
                Memorizzare che l&apos;utente ha visto questo avviso (in
                <code> localStorage</code>, non strettamente un cookie HTTP)
              </td>
              <td>Permanente</td>
              <td>Tecnico, prima parte</td>
            </tr>
          </tbody>
        </table>
      </div>

      <h2>3. Consenso</h2>
      <p>
        Trattandosi di cookie strettamente tecnici e necessari ex art. 122
        Codice Privacy, <strong>non è richiesto consenso preventivo</strong>{' '}
        dell&apos;utente. È stato comunque predisposto un avviso informativo
        sintetico al primo accesso.
      </p>

      <h2>4. Disabilitazione dei cookie</h2>
      <p>
        L&apos;utente può disabilitare i cookie tramite le impostazioni del
        proprio browser. Si segnala tuttavia che la disabilitazione dei
        cookie tecnici impedisce l&apos;utilizzo del servizio (in particolare
        l&apos;autenticazione).
      </p>

      <h2>5. Aggiornamento di questa policy</h2>
      <p>
        Qualora Diligenx introduca cookie di terze parti o analytics, questa
        Cookie Policy sarà aggiornata e verrà implementato un sistema di
        gestione del consenso conforme alle linee guida del Garante.
      </p>
    </LegalLayout>
  )
}
