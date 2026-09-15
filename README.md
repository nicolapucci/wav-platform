# WAV — piattaforma collaborativa (scaffold)

Scaffold funzionante dell'architettura descritta in [`docs/architettura.md`](docs/architettura.md)
(schema DB completo, diagrammi in `docs/*.mermaid`). Non è codice production-ready:
i router hanno diversi `TODO` espliciti dove manca logica applicativa (controlli
permessi da collegare, retry sui job, riconnessione WS, ecc.) — la struttura e i
pattern principali (permessi, realtime, coda) sono però già implementati e coerenti
con il documento di architettura.

## Struttura

```
db/migrations/       schema Postgres (0001_init.sql)
services/common/      libreria condivisa wav_core (config, db, redis, jwt, permessi)
services/auth-service/  login/registrazione/refresh JWT
services/api-service/   REST API (organizations, teams, projects, layers, tasks, comments, boards, me)
services/ws-gateway/    gateway WebSocket + bridge Redis Pub/Sub
services/worker-service/ consumer Redis Streams (audit, notifiche)
frontend/               React + Vite (pagina "Le mie task" come esempio end-to-end)
nginx/                  reverse proxy per il prototipo in Compose
docs/                   documento di architettura e diagrammi
```

## Avvio rapido (prototipo, Docker Compose)

Requisiti: Docker e Docker Compose.

```bash
cd wav-platform
cp .env.example .env      # personalizza JWT_SECRET almeno
docker compose up --build
```

Servizi esposti:

- Frontend: http://localhost (via nginx) o http://localhost:5173 (dev server Vite diretto)
- API REST: http://localhost:8000 (diretto) / http://localhost/api (via nginx)
- Auth: http://localhost:8001 (diretto) / http://localhost/auth (via nginx)
- WebSocket gateway: ws://localhost:8002/ws (diretto) / ws://localhost/ws (via nginx)
- MinIO console: http://localhost:9001 (utente/password in `.env`)

La prima volta che il container Postgres parte, esegue automaticamente
`db/migrations/0001_init.sql` (grazie al mount su `/docker-entrypoint-initdb.d`).
Per rigenerare il DB da zero: `docker compose down -v && docker compose up --build`.

Per simulare più repliche dei pod stateless (come farebbe l'HPA in k8s):

```bash
docker compose up --scale api-service=3 --scale ws-gateway=2 --scale worker-service=3
```

## Sviluppo locale senza Docker (singolo servizio)

Ogni servizio Python è indipendente e usa `wav_core` in editable install:

```bash
cd services/api-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e ../common
export $(cat ../../.env | xargs)   # o un .env locale con DATABASE_URL/REDIS_URL puntati a localhost
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## Verificare che tutto funzioni

```bash
curl http://localhost:8001/health   # auth-service
curl http://localhost:8000/health   # api-service
curl http://localhost:8002/health   # ws-gateway
```

Flusso di prova end-to-end via API:

```bash
# registrazione
curl -X POST http://localhost:8001/register -H 'Content-Type: application/json' \
  -d '{"email":"a@test.it","password":"password123","display_name":"Alice"}'
# -> copia access_token dalla risposta

TOKEN="<access_token>"

curl -X POST http://localhost:8000/organizations -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":"Acme","slug":"acme"}'
```

## Prossimi passi consigliati

1. Collegare i controlli permessi (`wav_core.permissions`) nei router ancora privi
   di `_require_role` (projects, layers, comments — segnati con `TODO`).
2. Implementare il filtro permessi reale in `ws-gateway/app/main.py::permission_filter`
   per i canali `evt:org:*:tasks`.
3. Risolvere in `ws-gateway` **tutte** le organizzazioni dell'utente per la
   subscribe `my_tasks` (oggi semplificata a un canale placeholder).
4. Endpoint di presigned URL per gli allegati (MinIO/S3) in `api-service`.
5. Migrazione a Kubernetes: vedi `docs/architettura.md` §9.2 per la mappatura
   servizio → risorsa k8s (Deployment/HPA/Ingress).

Per il resto del contesto architetturale (algoritmo permessi, flussi realtime,
decisioni aperte) fare riferimento a `docs/architettura.md`.
