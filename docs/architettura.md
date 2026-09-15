# Architettura piattaforma collaborativa "WAV"

## 1. Panoramica

Piattaforma di project management gerarchico con collaborazione in tempo reale.

Gerarchia dati:

```
Organization
 └─ Project
     └─ Layer (ricorsivo: Layer → Layer → ...)
         └─ Task
             └─ Comment
```

Ogni nodo della gerarchia (Organization, Project, Layer) ha una propria membership con ruolo (`owner`, `admin`, `editor`, `reader`); il ruolo effettivo su una risorsa si calcola per **ereditarietà con override**: il ruolo più specifico definito lungo la catena (dalla risorsa target fino alla root) vince; se non è definito nulla a un livello, si eredita dal livello superiore.

Principi guida:

- **Stateless dove possibile**: i pod REST e i pod WebSocket non hanno stato locale persistente (solo cache/registro socket in memoria), così si scalano orizzontalmente senza vincoli.
- **Postgres come unica fonte di verità**, Redis come infrastruttura di supporto (cache, pub/sub, coda), mai come store primario.
- **Disaccoppiamento scrittura/notifica**: ogni mutazione pubblica un evento; chi consuma l'evento (WS gateway, worker di audit) non blocca la richiesta HTTP originale.
- **Compose oggi, k8s domani**: stessa topologia logica di servizi, cambia solo l'orchestrazione (Compose = servizi con `deploy.replicas` bassi e networking semplificato, k8s = Deployment/Service/HPA/Ingress).

---

## 2. Modello di dominio

| Entità | Descrizione | Contiene |
|---|---|---|
| Organization | Tenant logico condiviso (non tenant fisico/DB separato) | Team*, Project* |
| Team | Sotto-gruppo di persone dentro un'organizzazione (es. "QA", "Backend") | User* (membri) |
| Project | Obiettivo astratto di gruppo | Layer* (radice) |
| Layer | Sotto-obiettivo astratto, **ricorsivo** | Layer* (figli) + Task* |
| Task | Obiettivo concreto e finito | Comment*, Attachment*, assegnatari, dipendenze |
| Comment | Commento su una task, supporta menzioni e allegati | Comment* (thread), Attachment*, Mention* |
| Board | Kanban custom, definita a livello di **Organization** o **Team** | BoardColumn*, task che rientrano nel suo filtro |
| BoardColumn | Colonna kanban (es. "To do", "In progress", "Done") | posizioni di task (per board) |

Un Layer può contenere **sia** sotto-layer **sia** task direttamente: non è obbligatorio essere "foglia" per avere task.

Un Team è un **raggruppamento di utenti**, usato principalmente come *principal* a cui assegnare permessi (invece di assegnarli utente per utente). Un Team non è un nodo della gerarchia Organization→Project→Layer→Task, ma un oggetto "trasversale" che vive dentro un'Organization.

Le Board non sono più legate a un Project: sono definite a livello di **Organization** (board condivisa a tutta l'org, es. vista generale) o di **Team** (es. la board del team QA), con colonne custom e un filtro che determina quali task vi compaiono (per progetto, layer, assegnatario, team...). Vedi §4.4 e §6.3.

---

## 3. Modello dei permessi (RBAC multilivello)

### 3.1 Ruoli

```
reader (10) < editor (20) < admin (30) < owner (40)
```

Livello numerico usato per confronti (`GREATEST`, `MAX`) e per decidere se un ruolo può assegnarne un altro (un `admin` non può creare un `owner`, ecc.).

| Ruolo | Può |
|---|---|
| reader | Vedere risorsa, task, commenti |
| editor | + creare/modificare task, commentare, spostare su kanban |
| admin | + gestire membership e ruoli allo stesso livello e sotto, creare/eliminare layer e board |
| owner | + eliminare la risorsa stessa (project/organization), trasferire ownership |

### 3.2 Team come principal dei permessi

I permessi non si assegnano più solo a singoli utenti: possono essere assegnati anche a un **Team**. Per questo la membership è modellata come tabella polimorfica `role_assignments` con un `principal_type` (`user` o `team`) — vedi §4.2. Esempio: il team "QA" riceve ruolo `editor` sul layer "Testing API di login"; tutti i membri del team ereditano quel permesso senza bisogno di righe individuali.

### 3.3 Algoritmo di risoluzione del ruolo effettivo

Per calcolare il ruolo di `user` su una `task` appartenente a `layer_id`:

1. Risali la catena: `layer target → ... → layer radice → project → organization`.
2. **Ad ogni livello**, calcola il ruolo candidato come il **massimo** tra: il ruolo assegnato direttamente all'utente a quel livello, e il ruolo assegnato a uno qualsiasi dei team di cui l'utente è membro a quel livello (un utente può stare in più team, e più team possono avere ruoli diversi sulla stessa risorsa: vince il più alto).
3. Il **primo livello** della catena (partendo dal più specifico) che produce un ruolo candidato non nullo è quello effettivo — tra livelli diversi vince la specificità, non la somma (pattern "cartella condivisa" stile Google Drive/GitHub team); **dentro lo stesso livello**, tra utente e team vince il ruolo più alto.
4. Se nessun livello produce un candidato → nessun accesso (404/403).

Per rendere efficiente il passo 1 sull'albero ricorsivo dei Layer si usa l'estensione **Postgres `ltree`**: ogni layer ha una colonna `path` tipo `ltree` (es. `l3.l17.l42`), così risalire gli antenati è una query indicizzata (GiST) invece di una CTE ricorsiva ripetuta ad ogni richiesta.

```sql
-- antenati di un layer, dal più specifico al più generico
SELECT id, path
FROM layers
WHERE path @> (SELECT path FROM layers WHERE id = :layer_id)
ORDER BY nlevel(path) DESC;
```

Il risultato della risoluzione va **cachato in Redis** (`perm:{user_id}:{resource_type}:{resource_id}` → ruolo, TTL breve tipo 60–120s) e invalidato attivamente quando cambia una membership a qualunque livello dell'albero coinvolto (pubblicando un evento di invalidazione, gestito dallo stesso meccanismo pub/sub usato per il realtime).

---

## 4. Schema del database (Postgres, psycopg3)

Estensioni: `ltree`, `pgcrypto` (o `uuid-ossp`) per UUID, `pg_trgm` opzionale per ricerca full-text su titoli.

```sql
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- ricerca testuale su titoli/task per "le mie task"

CREATE TYPE role_level AS ENUM ('reader','editor','admin','owner');

CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT,              -- NULL se utente solo-OAuth2
  display_name TEXT NOT NULL,
  avatar_url TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE oauth_identities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,          -- 'google', 'github', ...
  provider_user_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (provider, provider_user_id)
);

CREATE TABLE organizations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  archived_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE layers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  parent_layer_id UUID REFERENCES layers(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  path LTREE NOT NULL,             -- es: 'a1f3.b2c9' costruito all'inserimento
  archived_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX layers_path_gist ON layers USING GIST (path);
```

> Nota: `parent_layer_id` è mantenuto per integrità referenziale/cascade delete; `path` (ltree) è mantenuto come colonna derivata aggiornata quando si crea/sposta un layer (trigger o logica applicativa nel service).

### 4.1 Team e permessi polimorfici (utente **o** team)

```sql
CREATE TABLE teams (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE team_members (
  team_id UUID REFERENCES teams(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (team_id, user_id)
);

CREATE TYPE principal_type AS ENUM ('user','team');
CREATE TYPE grantable_resource_type AS ENUM ('organization','project','layer');

-- sostituisce organization_members / project_members / layer_members:
-- un'unica tabella polimorfica, il "principal" è un utente o un team
CREATE TABLE role_assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  principal_type principal_type NOT NULL,
  principal_id UUID NOT NULL,                    -- user_id oppure team_id, a seconda di principal_type
  resource_type grantable_resource_type NOT NULL,
  resource_id UUID NOT NULL,                      -- organization_id / project_id / layer_id
  role role_level NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (principal_type, principal_id, resource_type, resource_id)
);
CREATE INDEX role_assignments_resource_idx ON role_assignments(resource_type, resource_id);
CREATE INDEX role_assignments_principal_idx ON role_assignments(principal_type, principal_id);
```

> `principal_id` non ha una FK diretta (punterebbe a due tabelle diverse a seconda del tipo): l'integrità referenziale è garantita a livello applicativo (il service valida l'esistenza di `user_id`/`team_id` prima dell'insert) oppure con un trigger `CHECK` dedicato, se si vuole maggiore rigidità.

### 4.2 Task, assegnatari, dipendenze

```sql
CREATE TABLE tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  layer_id UUID NOT NULL REFERENCES layers(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  description TEXT,
  priority SMALLINT NOT NULL DEFAULT 0,
  due_date DATE,
  created_by UUID NOT NULL REFERENCES users(id),
  archived_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX tasks_layer_idx ON tasks(layer_id);
CREATE INDEX tasks_title_trgm_idx ON tasks USING GIN (title gin_trgm_ops);

CREATE TABLE task_assignees (
  task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (task_id, user_id)
);

-- dipendenze tra task: task_id dipende da (è bloccata da) depends_on_task_id
CREATE TABLE task_dependencies (
  task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
  depends_on_task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (task_id, depends_on_task_id),
  CHECK (task_id <> depends_on_task_id)
);

-- watcher espliciti (oltre ad assegnatari e autori commenti, che sono watcher impliciti)
CREATE TABLE task_watchers (
  task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (task_id, user_id)
);
```

La dipendenza `task_id → depends_on_task_id` (nessuna FK diretta impedisce i cicli): la prevenzione dei cicli va fatta **applicativamente** in `api-service` prima dell'insert, con una CTE ricorsiva che verifica se `depends_on_task_id` dipende già (trans­itivamente) da `task_id`. Il frontend può usare `task_dependencies` per bloccare visivamente lo spostamento su kanban di una task le cui dipendenze non sono ancora "done".

### 4.3 Commenti con allegati e menzioni

```sql
CREATE TABLE comments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  parent_comment_id UUID REFERENCES comments(id) ON DELETE CASCADE,
  author_id UUID NOT NULL REFERENCES users(id),
  body TEXT NOT NULL,              -- markdown; i link sono autolink gestiti lato client
  edited_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX comments_task_idx ON comments(task_id);

CREATE TABLE comment_mentions (
  comment_id UUID REFERENCES comments(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (comment_id, user_id)
);

-- allegati: possono stare su un commento o direttamente sulla task
CREATE TABLE attachments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  comment_id UUID REFERENCES comments(id) ON DELETE CASCADE,
  task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
  uploaded_by UUID NOT NULL REFERENCES users(id),
  storage_key TEXT NOT NULL,       -- chiave/oggetto su storage S3-compatibile (MinIO)
  filename TEXT NOT NULL,
  content_type TEXT,
  size_bytes BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (comment_id IS NOT NULL OR task_id IS NOT NULL)
);
```

Flusso upload: il client chiede a `api-service` un **URL firmato** (presigned URL) verso MinIO/S3, carica il file direttamente allo storage, poi conferma a `api-service` per creare la riga in `attachments` — così i pod REST non fanno mai da proxy per i bytes del file.

Le **menzioni** (`@utente`) vengono estratte lato `api-service` alla creazione del commento (parsing del body) e salvate in `comment_mentions`; ogni riga genera un job di notifica (vedi §4.5). I **link** restano semplice testo/markdown nel body: il rendering di anteprima (titolo/immagine) è opzionale e, se richiesto in futuro, può essere generato in modo asincrono da un worker che fa fetch dell'URL e cachea il risultato in Redis.

### 4.4 Kanban custom a livello di Organization o Team

```sql
CREATE TYPE board_scope_type AS ENUM ('organization','team');

CREATE TABLE boards (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scope_type board_scope_type NOT NULL,
  scope_id UUID NOT NULL,          -- organization_id oppure team_id, a seconda di scope_type
  name TEXT NOT NULL,
  task_filter JSONB NOT NULL DEFAULT '{}',   -- es: {"project_ids": [...], "layer_ids": [...], "assignee_ids": [...]}
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE board_columns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  board_id UUID NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  position INT NOT NULL,
  wip_limit INT
);

-- posizione di una task DENTRO una specifica board: la stessa task
-- può comparire (in colonne/posizioni diverse) su più board contemporaneamente
CREATE TABLE board_task_positions (
  board_id UUID REFERENCES boards(id) ON DELETE CASCADE,
  task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
  column_id UUID NOT NULL REFERENCES board_columns(id),
  position INT NOT NULL,
  PRIMARY KEY (board_id, task_id)
);
```

Una task **non ha più uno stato kanban fisso**: appartiene a zero o più board in base al `task_filter` di ciascuna board (valutato quando la task viene creata/modificata) e la sua colonna/posizione è tracciata per board in `board_task_positions`. Se una task inizia a soddisfare il filtro di una board a cui non apparteneva, `api-service` la inserisce nella colonna di default (`position = 1`) di quella board.

### 4.5 Notifiche persistenti e audit

```sql
CREATE TYPE notification_type AS ENUM ('mention','task_assigned','resource_updated','comment_reply');

CREATE TABLE notifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type notification_type NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id UUID NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}',
  read_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX notifications_user_unread_idx ON notifications(user_id) WHERE read_at IS NULL;

CREATE TABLE audit_logs (
  id BIGSERIAL PRIMARY KEY,
  actor_id UUID REFERENCES users(id),
  entity_type TEXT NOT NULL,
  entity_id UUID NOT NULL,
  action TEXT NOT NULL,            -- 'created', 'updated', 'deleted', 'role_changed'
  diff JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX audit_entity_idx ON audit_logs(entity_type, entity_id);
```

Vedi §4.5/§7 per il flusso di generazione (via job asincrono, non sincrono nella request).

---

## 5. Servizi (microservizi)

| Servizio | Runtime | Scala | Responsabilità |
|---|---|---|---|
| `auth-service` | FastAPI | 1-2 pod | Login password + OAuth2 (Google/GitHub/...), emette **sempre** un JWT proprio (access + refresh) indipendentemente dal metodo di login, così i servizi a valle validano un solo formato di token |
| `api-service` | FastAPI | pool orizzontale (HPA su CPU/req) | CRUD di organization/project/layer/task/comment/board, calcolo permessi, pubblica eventi su Redis Pub/Sub dopo ogni mutazione, accoda job async su Redis Streams |
| `ws-gateway` | FastAPI + `websockets` | pool orizzontale | Gestisce connessioni WSS, autentica il JWT alla connect, riceve subscribe/unsubscribe a risorse, mantiene registro locale socket↔risorse, sottoscrive i canali Redis Pub/Sub necessari, inoltra i messaggi ai socket locali interessati |
| `worker-service` | Python (consumer, no HTTP) | pool con consumer group | Consuma `stream:jobs` (Redis Streams) per audit log, invio notifiche, altri job asincroni; distribuzione round-robin naturale via consumer group |
| `postgres` | Postgres 16 | 1 istanza (+ replica read in futuro) | Store primario |
| `redis` | Redis 7 | 1 istanza in compose, cluster/istanze separate in k8s | cache permessi, pub/sub eventi, streams per code |
| `frontend` | React (Vite) | statico, servito da nginx/CDN | SPA client |
| `reverse-proxy` | nginx (compose) / Ingress (k8s) | - | Routing `/api → api-service`, `/ws → ws-gateway`, `/auth → auth-service`, supporto upgrade WebSocket |
| `object-storage` | MinIO (compose/self-hosted) o S3 gestito (prod) | - | Allegati di commenti/task; `api-service` genera presigned URL, il client carica direttamente qui |

Tutti i servizi backend condividono un package Python interno (es. `wav-core`) con: modelli Pydantic, client Postgres (psycopg3 + pool), client Redis, logica di risoluzione permessi — per evitare duplicazione tra `api-service` e `ws-gateway`.

---

## 6. Flusso realtime: WebSocket + Redis Pub/Sub

### 6.1 Convenzione canali

Un canale per risorsa: `evt:task:{id}`, `evt:layer:{id}`, `evt:board:{board_id}` (per riordini kanban), `evt:project:{id}` (per creazione/cancellazione layer figli, membership, ecc.).

Ogni mutazione pubblicata tramite `publish_resource_event` va **anche** su un canale generico "a tipo", senza id (`evt:{tipo}s`, es. `evt:tasks`): chi vuole essere avvisato di ogni evento su risorse di un certo tipo, senza ancorarsi a una singola risorsa, sottoscrive quello (`{"action":"subscribe","resource":"tasks"}`, senza `id`). È un meccanismo generico e non filtrato per visibilità: diverso da `evt:org:{id}:tasks` (§6.3), che resta lo strumento giusto quando serve rispettare i permessi di chi ascolta.

### 6.2 Ciclo di vita

1. Client apre connessione WSS con JWT (query param o primo messaggio).
2. Client invia `{"action":"subscribe","resource":"task","id":"123"}` per ogni risorsa visualizzata (es. la task aperta, la board del progetto, il layer corrente).
3. Il pod `ws-gateway`:
   - verifica il permesso di lettura (cache permessi in Redis, fallback su query Postgres);
   - se autorizzato, registra `socket → resource` in una mappa locale in memoria **e** esegue `SUBSCRIBE evt:task:123` sulla propria connessione Redis (idempotente se già sottoscritto da un altro client locale);
4. Quando `api-service` esegue una mutazione, dopo il commit Postgres pubblica su Redis: `PUBLISH evt:task:123 {"type":"task.updated","payload":{...}}`.
5. Tutti i pod `ws-gateway` sottoscritti al canale ricevono il messaggio, e ognuno lo inoltra solo ai socket locali effettivamente interessati (lookup nella mappa locale).
6. Alla disconnessione/unsubscribe, il pod rimuove l'entry locale; se non restano più client locali interessati a quel canale, esegue `UNSUBSCRIBE` per non sprecare traffico Redis.

Non serve *sticky session* a livello di load balancer per instradare per-risorsa: ogni connessione WS resta naturalmente ancorata al pod che l'ha accettata; il fan-out cross-pod è delegato interamente a Redis Pub/Sub.

Vedi diagramma di sequenza allegato per il flusso completo.

### 6.3 Pagina "Le mie task" (vista non legata a una risorsa singola)

Questa pagina mostra tutte le task su cui l'utente ha almeno permesso di lettura, con filtri/ricerca — non è ancorata a un task/layer/project specifico, quindi non può semplicemente sottoscrivere `evt:task:{id}`.

Convenzione aggiuntiva: ogni mutazione di una task pubblica **anche** su un canale a livello di organizzazione, oltre che sul canale specifico della risorsa:

```
evt:org:{organization_id}:tasks   →  {type: "task.created"|"task.updated"|"task.deleted", task_id, ...}
```

Flusso:

1. Il client apre la pagina "Le mie task" e invia `{"action":"subscribe","resource":"my_tasks"}`.
2. `ws-gateway` risolve le organizzazioni di cui l'utente è membro (poche, tipicamente 1) e sottoscrive `evt:org:{id}:tasks` per ciascuna.
3. Quando arriva un evento su quel canale, **prima di inoltrarlo** al socket il gateway verifica (via cache permessi, §3) che l'utente abbia ancora visibilità sulla task interessata — perché il canale è a livello di intera org, non tutti i membri vedono tutte le task.
4. Se autorizzato, il messaggio viene inoltrato al client, che aggiorna la lista/i filtri lato client senza dover ricaricare la pagina.

Questo mantiene il numero di canali sottoscritti per client limitato al numero di organizzazioni di appartenenza (non al numero di task/team/progetti visibili), pagando in cambio un controllo permessi extra lato gateway per ogni evento sul canale org.

### 6.4 Notifiche realtime (badge/centro notifiche)

In parallelo agli eventi sulle risorse, quando un job asincrono genera una notifica persistente (§4.5, §7) viene pubblicato anche:

```
evt:user:{user_id}:notifications  →  {type: "notification.created", notification_id, ...}
```

`ws-gateway` sottoscrive questo canale per ogni utente connesso (1 canale per utente loggato), permettendo di aggiornare il badge/centro notifiche in tempo reale indipendentemente dalla pagina che l'utente sta guardando.

---

## 7. Coda job asincroni (audit, notifiche, ecc.)

Si consiglia **Redis Streams** invece di una semplice `LIST` con `LPUSH/BRPOP`, perché offre out-of-the-box:

- **Consumer group** → distribuzione round-robin tra i worker senza logica custom (`XREADGROUP GROUP workers consumer-N COUNT 1 BLOCK 5000 STREAMS stream:jobs >`);
- **ACK esplicito** (`XACK`) → un job non confermato resta "pending" e può essere ripreso da un altro worker (`XPENDING` / `XCLAIM`) in caso di crash del consumer;
- **Persistenza/replay** limitata (a differenza di Pub/Sub puro, un messaggio non si perde se nessun consumer è online al momento del push).

Esempio di job scritto da `api-service` dopo una mutazione:

```json
{"type": "audit", "entity_type": "task", "entity_id": "123", "action": "updated", "actor_id": "...", "diff": {...}}
```

Oltre all'audit, lo stesso stream porta job di tipo `notification`, generati ogni volta che serve avvisare uno o più utenti (menzione in un commento, assegnazione di una task, aggiornamento di una risorsa che l'utente segue come watcher implicito o esplicito):

```json
{"type": "notification", "notification_type": "mention", "recipient_ids": ["u1","u2"], "entity_type": "comment", "entity_id": "c-456", "payload": {"comment_excerpt": "..."}}
```

Il worker che consuma questo job: (1) inserisce una riga in `notifications` per ciascun `recipient_id`, (2) pubblica `evt:user:{recipient_id}:notifications` su Redis Pub/Sub per il push realtime (§6.4). In questo modo `api-service` non calcola mai sincronamente i destinatari né scrive la tabella `notifications` nella request originale — resta solo responsabile di produrre il job con i dati grezzi dell'evento.

Il worker consuma, scrive su Postgres (`audit_logs` e/o `notifications`), ed eventualmente pubblica ulteriori eventi — mantenendo `api-service` completamente disaccoppiato dal tempo di elaborazione di questi job.

---

## 8. Autenticazione

- `auth-service` supporta **sia** login classico (email+password, hash con `argon2`) **sia** OAuth2/OIDC (Google, GitHub, ecc. via `authlib`), ma in entrambi i casi il risultato finale è un **JWT proprio**:
  - access token: breve durata (~15 min), contiene `sub`, `email`, eventuale claim di ruoli di alto livello per bypassare query ovvie;
  - refresh token: lunga durata, rotazione a ogni uso, memorizzato hashato in una tabella `refresh_tokens` (per poterlo revocare);
  - revoca/logout: si aggiunge il `jti` a una blocklist Redis con TTL pari alla scadenza residua del token.
- `api-service` e `ws-gateway` validano solo la firma JWT (chiave pubblica condivisa o segreto condiviso via secret k8s) — non serve chiamare `auth-service` a ogni richiesta.

---

## 9. Deployment

### 9.1 Prototipo (Docker Compose)

Un solo `docker-compose.yml` con: `postgres`, `redis`, `auth-service`, `api-service` (1 replica), `ws-gateway` (1 replica), `worker-service` (1-2 repliche per testare il consumer group), `frontend` (build statico + nginx), `nginx` come reverse proxy davanti a tutto con supporto upgrade WS.

### 9.2 Produzione (Kubernetes)

Stessa topologia, mappata così:

- `api-service`, `ws-gateway`, `worker-service` → `Deployment` + `HorizontalPodAutoscaler`;
- `ws-gateway` → `Service` di tipo ClusterIP dietro un Ingress che supporta WebSocket (es. NGINX Ingress Controller con `nginx.ingress.kubernetes.io/proxy-read-timeout` alto);
- `postgres` → gestito esternamente (RDS/Cloud SQL) o `StatefulSet` con storage persistente se self-hosted;
- `redis` → in produzione conviene **separare logicamente** cache / pub-sub / streams (anche solo con DB index diversi, o istanze separate se il volume di pub/sub è alto, per non far competere la coda con il traffico realtime);
- `worker-service` → nessun Service (non riceve traffico in ingresso), solo `Deployment` che consuma dallo Stream.

La migrazione da Compose a k8s non richiede cambi di codice applicativo: solo variabili di ambiente per gli endpoint di Postgres/Redis.

---

## 10. Decisioni ancora aperte

Punti su cui servirà una scelta più avanti, non bloccanti per iniziare:

1. **Object storage**: MinIO self-hosted (coerente con l'approccio "tutto in Compose/k8s") o S3/bucket gestito in produzione — per il prototipo consiglio MinIO, stesso protocollo S3 quindi la migrazione è solo di configurazione.
2. **Watcher espliciti**: ho aggiunto `task_watchers` per permettere a un utente di "seguire" una task senza esserne assegnatario/commentatore — da confermare se serve subito o si può rimandare (i watcher impliciti, cioè assegnatari + chi ha commentato, coprono già il caso base "avvisami se una mia risorsa cambia").
3. **Prevenzione cicli nelle dipendenze tra task**: verifica applicativa in `api-service` (CTE ricorsiva su `task_dependencies` prima dell'insert) — nessun vincolo a livello DB, da tenere a mente in fase di implementazione/test.
4. **Board: filtro dinamico vs assegnazione manuale**: `task_filter` in JSONB copre il caso "tutte le task del team X" automaticamente; se serve anche poter aggiungere manualmente task fuori filtro a una board, si può estendere `board_task_positions` per permettere righe "manuali" indipendenti dal filtro (già supportato dallo schema, va solo definita la UX).
5. **Rate limiting** su API pubbliche (via Redis, token bucket) — confermato da rimandare, ma da prevedere prima del rilascio in produzione.
