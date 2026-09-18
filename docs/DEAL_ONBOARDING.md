# Apertura dell'operazione e lettera di intenti

Il modulo **Nuovo Deal** raccoglie separatamente il titolo dell'operazione e le
ragioni sociali delle società target. Nel modulo web il perimetro è obbligatorio:
una ragione sociale completa per riga, fino a 20 società e 500 caratteri per nome.
La validazione API già esistente normalizza spazi, maiuscole e punteggiatura delle
forme giuridiche senza fondere entità con denominazioni o forme diverse. Il
contratto API resta compatibile con i client precedenti e le pratiche senza
perimetro; il campo non diventa obbligatorio retroattivamente.

La **lettera di intenti (LOI)** è facoltativa. Si può selezionare un singolo PDF,
DOCX o TXT fino a 50 MB prima di creare l'operazione. Il file viene caricato dopo
il salvataggio della pratica, con il ruolo esplicito `loi`. Il modulo mantiene
l'identificativo della pratica e lo stesso file se il caricamento non viene
confermato: il retry ripete solo l'upload. Un errore di rete o di accodamento può
avvenire dopo il salvataggio del documento; il messaggio non afferma quindi che
il file sia assente. Il link alla pratica permette di verificare i documenti.
L'analisi si avvia dalla pagina dell'operazione, dopo l'elaborazione dei file.

## Ruolo dei documenti

La migrazione **019**, successiva alla 018, aggiunge `documents.document_role`,
con default `data_room` e valori consentiti `data_room` / `loi`. Tutti i documenti
preesistenti mantengono il ruolo generico. Il nome del file non determina il ruolo.
L'upload singolo accetta il parametro `document_role`; lista, risposta upload ed
export dell'account espongono il valore. Un upload generico dello stesso file non
retrocede una LOI. La promozione esplicita di un file esistente riutilizza la sua
identità ed è bloccata durante l'analisi, sotto lo stesso lock della pratica usato
per le altre modifiche all'inventario. I controlli di proprietà restano invariati.

Applicare la migrazione prima di avviare il worker della nuova versione. La
verifica BETA_MODE richiede che la revisione del database coincida con quella del
codice; non disabilitarla per aggirare un ordine di deploy errato.

## Contesto degli agenti

Ogni esecuzione costruisce uno snapshot immutabile del perimetro confermato e
delle LOI esplicitamente designate e leggibili nella stessa pratica. Lo snapshot
arriva agli agenti della pipeline, alla rigenerazione del report e alle domande
sui documenti. Non modifica il provider globale e non aggiunge chiamate AI.

Il contesto distingue le target dalle controparti. Le altre società possono
essere pertinenti a un rilievo sulla target, ma non entrano automaticamente nel
perimetro. La LOI descrive intenzioni e condizioni negoziali: gli agenti non devono
trattarne tutto il contenuto come fatti verificati o presumere che ogni clausola
sia vincolante oppure non vincolante. Le istruzioni contenute nel file sono dati,
non comandi per gli agenti.

Gli estratti condivisi sono limitati a 7.000 caratteri complessivi e a 20 LOI,
con identificativi delle fonti, indicazione dei troncamenti e conteggio delle
fonti omesse o non leggibili. L'inizio e la fine dei testi sono conservati; una
clausola assente dall'estratto non può essere dichiarata assente dall'originale.
Tutte le LOI integrali della pratica entrano comunque nell'analisi contrattuale,
anche se il classificatore le etichetta come `other`. I rilievi devono essere
supportati dal documento effettivamente analizzato; il contesto di una LOI non
diventa una citazione attribuibile a un altro file. Le risposte QA possono citare
soltanto i segmenti recuperati e numerati.

Il fingerprint della ripresa include il ruolo LOI e la versione del contesto.
I vecchi checkpoint delle pratiche che usano questo nuovo contesto richiedono una
nuova analisi; i report già pubblicati non vengono modificati dal deploy. Le
pratiche legacy senza perimetro e senza LOI mantengono il fingerprint precedente.
