-- Schema iniziale piattaforma WAV
-- Vedi docs/architettura.md per la spiegazione di ogni scelta.

CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TYPE role_level AS ENUM ('reader','editor','admin','owner');
CREATE TYPE principal_type AS ENUM ('user','team');
CREATE TYPE grantable_resource_type AS ENUM ('organization','project','layer');
CREATE TYPE notification_type AS ENUM ('mention','task_assigned','resource_updated','comment_reply');

-- ---------------------------------------------------------------------------
-- Utenti e autenticazione
-- ---------------------------------------------------------------------------

CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT,
  display_name TEXT NOT NULL,
  avatar_url TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE oauth_identities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  provider_user_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (provider, provider_user_id)
);

-- ---------------------------------------------------------------------------
-- Gerarchia Organization -> Project -> Layer (ricorsivo)
-- ---------------------------------------------------------------------------

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
  path LTREE NOT NULL,
  archived_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX layers_path_gist ON layers USING GIST (path);
CREATE INDEX layers_project_idx ON layers(project_id);

-- Colonne kanban di un progetto: create/modificate/riordinate/eliminate dagli
-- utenti (con permessi, vedi projects.py), non più un set fisso di 3 stati.
-- Ogni progetto ne ha almeno una (seminate alla creazione del progetto);
-- alimentano sia la kanban di default per layer sia la dashboard/board custom.
CREATE TABLE board_columns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  position INT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX board_columns_project_idx ON board_columns(project_id);

-- ---------------------------------------------------------------------------
-- Team e permessi polimorfici (utente o team)
-- ---------------------------------------------------------------------------

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

-- sostituisce organization_members / project_members / layer_members:
-- un'unica tabella polimorfica, il "principal" è un utente o un team.
-- Nota: principal_id non ha FK diretta (punterebbe a due tabelle diverse a
-- seconda del tipo); l'integrità va validata a livello applicativo.
CREATE TABLE role_assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  principal_type principal_type NOT NULL,
  principal_id UUID NOT NULL,
  resource_type grantable_resource_type NOT NULL,
  resource_id UUID NOT NULL,
  role role_level NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (principal_type, principal_id, resource_type, resource_id)
);
CREATE INDEX role_assignments_resource_idx ON role_assignments(resource_type, resource_id);
CREATE INDEX role_assignments_principal_idx ON role_assignments(principal_type, principal_id);

-- ---------------------------------------------------------------------------
-- Task, assegnatari, dipendenze, watcher
-- ---------------------------------------------------------------------------

CREATE TABLE tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  layer_id UUID NOT NULL REFERENCES layers(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  description TEXT,
  status_column_id UUID REFERENCES board_columns(id) ON DELETE SET NULL,
  priority SMALLINT NOT NULL DEFAULT 0,
  due_date DATE,
  created_by UUID NOT NULL REFERENCES users(id),
  archived_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX tasks_layer_idx ON tasks(layer_id);
CREATE INDEX tasks_status_column_idx ON tasks(status_column_id);
CREATE INDEX tasks_title_trgm_idx ON tasks USING GIN (title gin_trgm_ops);

CREATE TABLE task_assignees (
  task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (task_id, user_id)
);

CREATE TABLE task_dependencies (
  task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
  depends_on_task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (task_id, depends_on_task_id),
  CHECK (task_id <> depends_on_task_id)
);

CREATE TABLE task_watchers (
  task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (task_id, user_id)
);

-- ---------------------------------------------------------------------------
-- Tag: legati a un progetto, applicabili a qualsiasi task del progetto
-- ---------------------------------------------------------------------------

CREATE TABLE tags (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  color TEXT,
  created_by UUID NOT NULL REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (project_id, name)
);
CREATE INDEX tags_project_idx ON tags(project_id);

CREATE TABLE task_tags (
  task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
  tag_id UUID REFERENCES tags(id) ON DELETE CASCADE,
  PRIMARY KEY (task_id, tag_id)
);

-- ---------------------------------------------------------------------------
-- Commenti, menzioni, allegati
-- ---------------------------------------------------------------------------

CREATE TABLE comments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  parent_comment_id UUID REFERENCES comments(id) ON DELETE CASCADE,
  author_id UUID NOT NULL REFERENCES users(id),
  body TEXT NOT NULL,
  edited_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX comments_task_idx ON comments(task_id);

CREATE TABLE comment_mentions (
  comment_id UUID REFERENCES comments(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (comment_id, user_id)
);

CREATE TABLE attachments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  comment_id UUID REFERENCES comments(id) ON DELETE CASCADE,
  task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
  uploaded_by UUID NOT NULL REFERENCES users(id),
  storage_key TEXT NOT NULL,
  filename TEXT NOT NULL,
  content_type TEXT,
  size_bytes BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (comment_id IS NOT NULL OR task_id IS NOT NULL)
);

-- ---------------------------------------------------------------------------
-- Board: un FILTRO SALVATO su un progetto (es. "assignee in team QA"), non un
-- set di colonne proprio - le colonne sono quelle del progetto (board_columns,
-- sopra), condivise da tutte le viste (kanban di default per layer, board
-- custom). Lo stesso filtro alimenta sia la vista kanban sia la dashboard
-- (torta) di quel sottoinsieme di task.
-- ---------------------------------------------------------------------------

CREATE TABLE boards (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  created_by UUID NOT NULL REFERENCES users(id),
  name TEXT NOT NULL,
  -- es: {"layer_ids": [...], "assignee_ids": [...], "team_ids": [...], "tag_ids": [...]}
  -- tutte le chiavi sono opzionali e si combinano in AND; layer_ids include
  -- automaticamente i sotto-layer (risoluzione via ltree, vedi projects.py).
  task_filter JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX boards_project_idx ON boards(project_id);

-- ---------------------------------------------------------------------------
-- Notifiche persistenti e audit log
-- ---------------------------------------------------------------------------

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
  action TEXT NOT NULL,
  diff JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX audit_entity_idx ON audit_logs(entity_type, entity_id);
