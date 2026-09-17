-- Cancellazione logica per organizations e users: projects/layers/tasks hanno
-- già archived_at dalla migrazione iniziale (0001_init.sql) - qui si completa
-- lo schema per gli altri due livelli della gerarchia e per l'account utente.
-- Cancellare un'organizzazione/progetto/layer archivia a cascata tutto quello
-- che contiene (vedi gli endpoint DELETE nei rispettivi router): con la
-- gerarchia Organization -> Project -> Layer -> Task, lasciare "orfani"
-- visibili dei figli di una risorsa archiviata sarebbe incoerente.

ALTER TABLE organizations ADD COLUMN archived_at TIMESTAMPTZ;

-- Nome diverso da archived_at apposta: qui non si tratta di archiviare una
-- risorsa di lavoro ma di disattivare un account (impedisce login/refresh,
-- lo esclude dalla ricerca utenti/menzioni) - vedi me.py::deactivate_me.
ALTER TABLE users ADD COLUMN deactivated_at TIMESTAMPTZ;
