-- Id leggibili e univoci per le task: <PREFISSO PROGETTO>-<numero progressivo
-- nel progetto>, es. "QA-1". Il prefisso è scelto alla creazione del progetto
-- (lunghezza fissa, vedi PROJECT_PREFIX_LENGTH in projects.py) e non è più
-- modificabile dopo; il numero progressivo è assegnato in modo atomico da
-- projects.next_task_number (vedi tasks.py::create_task). La primary key delle
-- task resta lo UUID: l'id leggibile è solo un identificatore aggiuntivo per
-- link/riferimenti (risolto a UUID lato server, vedi tasks.py::_resolve_task_id).

ALTER TABLE projects ADD COLUMN prefix TEXT;
ALTER TABLE projects ADD COLUMN next_task_number INT NOT NULL DEFAULT 1;

-- backfill dei progetti già esistenti: un prefisso derivato dal nome, reso
-- univoco con un suffisso numerico in caso di collisione, così il passaggio a
-- NOT NULL/UNIQUE qui sotto non fallisce su dati creati prima di questa migrazione.
DO $$
DECLARE
  proj RECORD;
  candidate TEXT;
  base TEXT;
  suffix INT;
BEGIN
  FOR proj IN SELECT id, name FROM projects ORDER BY created_at LOOP
    base := upper(regexp_replace(proj.name, '[^a-zA-Z]', '', 'g'));
    base := rpad(substring(base FROM 1 FOR 4), 4, 'X');
    candidate := base;
    suffix := 1;
    WHILE EXISTS (SELECT 1 FROM projects WHERE prefix = candidate) LOOP
      suffix := suffix + 1;
      candidate := rpad(substring(base FROM 1 FOR 3), 3, 'X') || suffix::text;
    END LOOP;
    UPDATE projects SET prefix = candidate WHERE id = proj.id;
  END LOOP;
END $$;

ALTER TABLE projects ALTER COLUMN prefix SET NOT NULL;
ALTER TABLE projects ADD CONSTRAINT projects_prefix_unique UNIQUE (prefix);

ALTER TABLE tasks ADD COLUMN task_number INT;

-- backfill delle task esistenti: numerazione progressiva per progetto
-- nell'ordine di creazione, e allineamento del contatore del progetto.
WITH numbered AS (
  SELECT t.id, row_number() OVER (PARTITION BY l.project_id ORDER BY t.created_at) AS n
  FROM tasks t
  JOIN layers l ON l.id = t.layer_id
)
UPDATE tasks SET task_number = numbered.n
FROM numbered
WHERE tasks.id = numbered.id;

ALTER TABLE tasks ALTER COLUMN task_number SET NOT NULL;

UPDATE projects p
SET next_task_number = COALESCE(
  (SELECT MAX(t.task_number) + 1 FROM tasks t JOIN layers l ON l.id = t.layer_id WHERE l.project_id = p.id),
  1
);

-- Nessun vincolo UNIQUE a livello DB su (project_id, task_number): tasks non ha
-- una colonna project_id diretta (solo layer_id, il progetto si risale via
-- layers.project_id) e un indice non può usare una subquery/join per calcolarlo.
-- L'unicità per progetto è garantita dall'applicazione: task_number viene
-- assegnato con un UPDATE atomico su projects.next_task_number (lock di riga)
-- nella stessa transazione dell'INSERT, vedi tasks.py::create_task - due
-- richieste concorrenti sullo stesso progetto non possono ottenere lo stesso
-- numero perché la seconda UPDATE resta bloccata finché la prima transazione
-- non committa.
