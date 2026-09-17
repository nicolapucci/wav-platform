# WAV — piattaforma collaborativa (scaffold)

Scaffold funzionante dell'architettura descritta in [`docs/architettura.md`](docs/architettura.md)
(schema DB completo, diagrammi in `docs/*.mermaid`). Permessi, cancellazione
logica, realtime e coda sono implementati e testati (vedi le suite in
`services/*/tests`); restano `TODO` espliciti su alcune feature non ancora
costruite (OAuth2, allegati via presigned URL - vedi i TODO in
`services/auth-service/app/main.py` e `services/api-service/app/routers/comments.py`).

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
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/certs/tls.key -out nginx/certs/tls.crt -subj "/CN=localhost"
docker compose up --build
```

(su Git Bash/Windows prefissa il comando `openssl` con `MSYS_NO_PATHCONV=1`,
altrimenti `/CN=localhost` viene interpretato come un path di filesystem.)

Servizi esposti:

- Frontend: https://localhost (via nginx, certificato self-signed - vedi sotto)
  o http://localhost:5173 (dev server Vite diretto). http://localhost
  reindirizza automaticamente a https.
- API REST: http://localhost:8000 (diretto) / https://localhost/api (via nginx)
- Auth: http://localhost:8001 (diretto) / https://localhost/auth (via nginx)
- WebSocket gateway: ws://localhost:8002/ws (diretto) / wss://localhost/ws (via nginx)
- MinIO console: http://localhost:9001 (utente/password in `.env`)

Il certificato TLS di nginx è **self-signed** (per questo browser/`curl` senza
`-k` lo rifiutano) - da sostituire con uno vero (Let's Encrypt) al momento del
deploy pubblico; nel frattempo va rigenerato con il comando `openssl` sopra
(la cartella `nginx/certs/` è gitignorata, non contiene nulla al primo clone).

La prima volta che il container Postgres parte, esegue automaticamente tutte le
migrazioni in `db/migrations/` (grazie al mount su `/docker-entrypoint-initdb.d`).
Per rigenerare il DB da zero: `docker compose down -v && docker compose up --build`.

Per simulare più repliche dei pod stateless (come farebbe l'HPA in k8s):

```bash
docker compose up --scale api-service=3 --scale ws-gateway=2 --scale worker-service=3
```

## Deploy su Kubernetes

Manifest in `k8s/`, applicabili tutti insieme (i riferimenti incrociati tra
risorse, es. un Deployment che monta un Secret, si risolvono da soli quando
l'oggetto referenziato compare - non serve un ordine rigido oltre al namespace):

```bash
kubectl apply -f k8s/00-namespace.yaml

# Secret applicativo (vedi k8s/02-secret-app.example.yaml per i valori attesi)
# e certificato TLS di nginx (vedi k8s/29-secret-nginx-tls.example.yaml) - da
# generare così, mai committati:
kubectl create secret generic app-secrets -n wav-platform \
  --from-env-file=.env --from-literal=POSTGRES_PASSWORD=wav \
  --from-literal=MINIO_ROOT_PASSWORD=wavminio123 \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret tls nginx-tls -n wav-platform \
  --cert=nginx/certs/tls.crt --key=nginx/certs/tls.key \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f k8s/01-configmap-app.yaml -f k8s/03-configmap-db-init.yaml \
  -f k8s/04-configmap-nginx.yaml -f k8s/10-postgres.yaml -f k8s/11-redis.yaml \
  -f k8s/12-minio.yaml -f k8s/20-auth-service.yaml -f k8s/21-api-service.yaml \
  -f k8s/22-ws-gateway.yaml -f k8s/23-worker-service.yaml -f k8s/24-frontend.yaml \
  -f k8s/30-nginx.yaml
```

Su un cluster **kind** (es. Kubernetes di Docker Desktop) il nodo ha un
containerd separato dal Docker daemon: le immagini vanno buildate e importate a
mano, altrimenti i pod restano in `ErrImageNeverPull`:

```bash
docker compose build auth-service api-service ws-gateway worker-service frontend
for svc in auth-service api-service ws-gateway worker-service frontend; do
  docker save wav-platform-$svc:latest | docker exec -i desktop-control-plane ctr -n k8s.io images import -
done
```

Su un cluster reale (non kind) questo passo non serve: basta pushare le
immagini su un registry e puntarci gli `image:` nei manifest.

L'autoscaling (HPA, già configurato su ogni servizio stateless) richiede
metrics-server: `k8s/05-metrics-server-setup.sh` documenta il setup one-shot
necessario su kind (deliberatamente `.sh`, non `.yaml`, per non essere
applicato per errore con gli altri manifest).

Il LoadBalancer `nginx` espone sia 80 (redirect automatico) sia 443
(`kubectl get svc nginx -n wav-platform` per l'IP esterno): stesso
certificato self-signed di compose finché non si integra Let's Encrypt.

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

1. Integrare Let's Encrypt al posto del certificato self-signed di nginx
   (compose e k8s) quando si prepara un deploy pubblico con un dominio vero.
2. Implementare il filtro permessi reale in `ws-gateway/app/main.py::permission_filter`
   per i canali `evt:org:*:tasks`.
3. Risolvere in `ws-gateway` **tutte** le organizzazioni dell'utente per la
   subscribe `my_tasks` (oggi semplificata a un canale placeholder).
4. Endpoint di presigned URL per gli allegati (MinIO/S3) in `api-service`.
5. Rate-limiting su login/register in `auth-service` (nessuna protezione da
   brute-force oggi).
6. OAuth2/OIDC (Google) in `auth-service` — variabili già previste in `.env.example`.

Per il resto del contesto architetturale (algoritmo permessi, flussi realtime,
decisioni aperte) fare riferimento a `docs/architettura.md`.
