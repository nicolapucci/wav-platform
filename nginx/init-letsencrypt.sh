#!/bin/sh
# Primo certificato Let's Encrypt per il deploy con Docker Compose. Da lanciare una
# volta sola, da qualunque cartella:  sh nginx/init-letsencrypt.sh
#
# Prerequisiti (vedi il README): DOMAIN nel .env (e volendo LETSENCRYPT_EMAIL), un
# nome DNS che punta a questa macchina, porte 80 e 443 raggiungibili da internet.
# Per provare tutto senza consumare i limiti di richieste di Let's Encrypt: metti
# LETSENCRYPT_STAGING=1 nel .env, lancia lo script, poi toglilo e rilancialo.
set -eu
cd "$(dirname "$0")/.."

echo "==> 1/4 certificato provvisorio (se manca): nginx non parte senza"
docker compose run --rm --no-deps certbot bootstrap

echo "==> 2/4 avvio dello stack: nginx deve rispondere su :80 alla challenge"
docker compose up -d --build

echo "==> 3/4 richiesta del certificato a Let's Encrypt"
docker compose run --rm --no-deps certbot issue

echo "==> 4/4 nginx ricarica il certificato nuovo"
docker compose exec -T nginx nginx -s reload

echo "Fatto. Il rinnovo e' automatico se nel .env c'e' COMPOSE_PROFILES=letsencrypt"
echo "(servizio certbot); senza, lancia: docker compose --profile letsencrypt up -d certbot"
