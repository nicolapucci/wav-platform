-- Un gruppo (team) può essere trattato come un utente in due punti:
-- 1) task_assignees diventa polimorfico (principal_type/principal_id, stesso
--    pattern già usato da role_assignments) così una task può essere assegnata
--    a un team intero, non solo a singoli utenti.
-- 2) i permessi (role_assignments) e le menzioni nei commenti già supportavano
--    i team a livello di schema/CTE di visibilità (vedi principal_type in
--    0001_init.sql) - qui si aggiunge solo la UI e, per le menzioni, non serve
--    nessuna migrazione (si espande il team ai suoi membri al momento della
--    creazione del commento, vedi comments.py).

ALTER TABLE task_assignees DROP CONSTRAINT task_assignees_user_id_fkey;
ALTER TABLE task_assignees DROP CONSTRAINT task_assignees_pkey;
ALTER TABLE task_assignees RENAME COLUMN user_id TO principal_id;
ALTER TABLE task_assignees ADD COLUMN principal_type principal_type NOT NULL DEFAULT 'user';
ALTER TABLE task_assignees ALTER COLUMN principal_type DROP DEFAULT;
ALTER TABLE task_assignees ADD PRIMARY KEY (task_id, principal_type, principal_id);

-- NOTA: niente più FK diretta su principal_id (può puntare a users o teams a
-- seconda di principal_type) - stessa scelta e stessa nota di integrità
-- applicativa già fatta per role_assignments in 0001_init.sql.
