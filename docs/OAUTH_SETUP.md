# Accesso con Microsoft e Google

Il pulsante di un provider compare nella pagina di login solo quando sul
servizio API sono impostati sia il suo client id sia il suo secret. Senza
configurazione il login resta quello con e-mail e password.

Gli indirizzi di ritorno da registrare presso i provider sono:

```
{FRONTEND_URL}/api/auth/oauth/microsoft/callback
{FRONTEND_URL}/api/auth/oauth/google/callback
```

Con `FRONTEND_URL=https://www.diligenx.it`, ad esempio,
`https://www.diligenx.it/api/auth/oauth/microsoft/callback`. Il percorso passa
dal proxy `/api` del frontend: così il cookie di sessione nasce sul dominio del
frontend, come nel login con password. `FRONTEND_URL` deve coincidere
esattamente con l’indirizzo da cui gli utenti aprono l’app (schema, `www`,
nessuna barra finale).

## Microsoft (Entra ID)

1. Portale Azure → Microsoft Entra ID → **App registrations** → New registration.
   - Supported account types: *Accounts in any organizational directory*
     (multitenant).
   - Redirect URI: piattaforma **Web**, l’indirizzo di ritorno sopra.
2. **Certificates & secrets** → New client secret. Il secret scade (al massimo
   24 mesi): annotare la data e rinnovarlo prima, altrimenti l’accesso con
   Microsoft smette di funzionare.
3. **Token configuration** → Add optional claim → tipo **ID** → selezionare
   `email` e `xms_edov`. Senza `xms_edov` il primo accesso viene rifiutato
   con "e-mail non verificata": in un account aziendale l’indirizzo lo imposta
   l’amministratore del tenant, e `xms_edov` è l’unico segnale che il dominio
   dell’indirizzo appartiene davvero a quel tenant.
4. **Branding & properties** → publisher verification (richiede un ID Microsoft
   Partner Network). Senza, gli utenti vedono l’avviso "app non verificata" e
   molti tenant ne bloccano il consenso.
5. Variabili sul servizio API: `MICROSOFT_CLIENT_ID` (Application (client) ID),
   `MICROSOFT_CLIENT_SECRET` (il *Value* del secret, non il suo ID) e, se serve,
   `MICROSOFT_TENANT`:
   - `organizations` (predefinito): qualunque account aziendale;
   - `common`: anche account Microsoft personali;
   - l’ID di un tenant: solo quel tenant.

Molti studi impediscono agli utenti di autorizzare da soli app esterne. In quel
caso l’amministratore del tenant dello studio concede il consenso una volta per
tutti: Entra admin center → Enterprise applications → Diligenx → Permissions →
Grant admin consent. I permessi richiesti sono solo `openid`, `email` e
`profile`.

## Google

1. Google Cloud Console → APIs & Services → **OAuth consent screen**: tipo
   *External*, nome dell’app, e-mail di supporto, dominio autorizzato
   (`diligenx.it`). Scope: `openid`, `email`, `profile`.
2. Finché lo stato è *Testing* possono accedere solo gli utenti di test
   elencati (massimo 100): per i tester esterni pubblicarla in *Production*.
   Con i soli scope di base non serve la verifica completa dell’app; Google può
   chiedere la verifica del brand (nome e logo).
3. **Credentials** → Create credentials → OAuth client ID → *Web application*,
   con l’indirizzo di ritorno sopra tra gli *Authorized redirect URIs*.
4. Variabili sul servizio API: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.

## Verifica

`GET {FRONTEND_URL}/api/auth/oauth/providers` restituisce i provider attivi,
ad esempio `{"providers": ["google", "microsoft"]}`.

## Come vengono gestiti gli account

- Un accesso è legato all’identificativo stabile che il provider assegna alla
  persona, non all’e-mail.
- Al primo accesso, se esiste già un account con la stessa e-mail, l’accesso
  viene collegato a quell’account; altrimenti ne viene creato uno nuovo. In
  entrambi i casi solo se il provider conferma che l’e-mail è verificata.
- Un account creato così non ha password. Può impostarne una con "Password
  dimenticata?".
- Per eliminare un account senza password bisogna accedere di nuovo con il
  provider: la cancellazione è accettata solo entro dieci minuti dall’accesso.
- L’autenticazione a due fattori, per chi entra con Microsoft o Google, è quella
  imposta dall’account dello studio presso il provider.
