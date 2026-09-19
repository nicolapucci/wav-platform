#!/bin/sh
# Gira DENTRO il container "certbot" (vedi docker-compose.yml). Sottocomandi:
#
#   bootstrap    crea un certificato self-signed provvisorio se non ce n'e' gia' uno:
#                nginx non parte se il file di ssl_certificate non esiste, e certbot
#                ha bisogno di nginx acceso per la challenge su :80.
#   issue        chiede a Let's Encrypt il certificato per $DOMAIN (nginx gia' acceso).
#   deploy-hook  lo lancia certbot stesso a ogni emissione/rinnovo: copia il
#                certificato dove lo legge nginx.
#   renew-loop   comando di default del servizio: prova a rinnovare ogni 12h.
#
# Parametri (dal .env, passati dal servizio in docker-compose.yml):
#   DOMAIN               nome DNS del sito (obbligatorio per bootstrap e issue)
#   LETSENCRYPT_EMAIL    per gli avvisi di scadenza (facoltativa)
#   LETSENCRYPT_STAGING  se valorizzata usa il server di prova di Let's Encrypt:
#                        certificato non valido nei browser, ma senza i limiti di
#                        richieste di quello vero (per provare tutto la prima volta)
#   CERTBOT_EXTRA_ARGS   argomenti aggiuntivi per certbot, ad es. un altro server ACME
set -eu

CERTS_DIR=/nginx-certs

case "${1:-}" in
  bootstrap)
    : "${DOMAIN:?DOMAIN non impostato (vedi .env.example)}"
    if [ ! -f "$CERTS_DIR/tls.crt" ] || [ ! -f "$CERTS_DIR/tls.key" ]; then
      openssl req -x509 -nodes -newkey rsa:2048 -days 30 \
        -keyout "$CERTS_DIR/tls.key" -out "$CERTS_DIR/tls.crt" -subj "/CN=localhost"
    fi
    ;;

  issue)
    : "${DOMAIN:?DOMAIN non impostato (vedi .env.example)}"
    email_args="--register-unsafely-without-email"
    if [ -n "${LETSENCRYPT_EMAIL:-}" ]; then
      email_args="--email $LETSENCRYPT_EMAIL"
    fi
    staging_args=""
    if [ -n "${LETSENCRYPT_STAGING:-}" ]; then
      staging_args="--staging"
    fi
    # --force-renewal: chiede sempre un certificato nuovo. Senza, se esiste gia' un
    # certificato con questo nome (ad es. quello di prova emesso con
    # LETSENCRYPT_STAGING) certbot risponde "non ancora in scadenza" e lo lascia li'
    # - e passando da staging a produzione resterebbe quello non valido.
    # $email_args/$staging_args/CERTBOT_EXTRA_ARGS sono liste di argomenti: vanno
    # spezzate dalla shell, quindi non sono tra virgolette.
    certbot certonly --webroot -w /var/www/certbot \
      -d "$DOMAIN" --cert-name "$DOMAIN" \
      --non-interactive --agree-tos --force-renewal \
      $email_args $staging_args ${CERTBOT_EXTRA_ARGS:-} \
      --deploy-hook "sh /certbot/entrypoint.sh deploy-hook"
    ;;

  deploy-hook)
    : "${RENEWED_LINEAGE:?impostata da certbot, non va lanciato a mano}"
    # copia + mv: nginx non deve mai leggere un file a meta'
    cp "$RENEWED_LINEAGE/fullchain.pem" "$CERTS_DIR/tls.crt.new"
    cp "$RENEWED_LINEAGE/privkey.pem" "$CERTS_DIR/tls.key.new"
    chmod 600 "$CERTS_DIR/tls.key.new"
    mv "$CERTS_DIR/tls.crt.new" "$CERTS_DIR/tls.crt"
    mv "$CERTS_DIR/tls.key.new" "$CERTS_DIR/tls.key"
    ;;

  renew-loop)
    trap exit TERM
    while :; do
      # prima dorme, poi rinnova: cosi' non si scontra con "issue" lanciato a mano
      # subito dopo l'avvio dello stack (certbot tiene un lock sulla propria cartella)
      sleep 12h &
      wait $!
      certbot renew --quiet || echo "certbot renew fallito, riprovo al prossimo giro" >&2
    done
    ;;

  *)
    echo "uso: entrypoint.sh bootstrap|issue|deploy-hook|renew-loop" >&2
    exit 2
    ;;
esac
