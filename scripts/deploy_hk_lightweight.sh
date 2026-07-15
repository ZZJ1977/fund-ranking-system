#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE=".env.production"
ENV_TEMPLATE="deploy/env.production.example"
HTPASSWD_FILE="deploy/secrets/.htpasswd"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Install Docker first, then rerun this script." >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose is not available. Install the Docker Compose plugin first." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not running or your user cannot access Docker." >&2
  echo "Try: sudo systemctl start docker" >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  cp "$ENV_TEMPLATE" "$ENV_FILE"
  echo "Created $ENV_FILE from $ENV_TEMPLATE"
fi

set -a
# shellcheck disable=SC1091
source "$ENV_FILE"
set +a

PUBLIC_PORT="${PUBLIC_HTTP_PORT:-80}"

mkdir -p data reports deploy/secrets

if [ ! -f "$HTPASSWD_FILE" ]; then
  if ! command -v openssl >/dev/null 2>&1; then
    echo "openssl is required to generate the Basic Auth password file." >&2
    exit 1
  fi

  read -r -p "Basic Auth username [fundadmin]: " auth_user
  auth_user="${auth_user:-fundadmin}"
  read -r -s -p "Basic Auth password: " auth_password
  echo
  if [ -z "$auth_password" ]; then
    echo "Password cannot be empty." >&2
    exit 1
  fi

  hashed_password="$(openssl passwd -apr1 "$auth_password")"
  printf "%s:%s\n" "$auth_user" "$hashed_password" > "$HTPASSWD_FILE"
  chmod 600 "$HTPASSWD_FILE"
  echo "Created $HTPASSWD_FILE"
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up --build -d

for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PUBLIC_PORT}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

curl -fsS "http://127.0.0.1:${PUBLIC_PORT}/health" >/dev/null

server_host="${PUBLIC_HOST:-}"
if [ -z "$server_host" ]; then
  server_host="$(hostname -I 2>/dev/null | awk '{print $1}')"
fi
if [ -z "$server_host" ]; then
  server_host="SERVER_IP"
fi

echo
echo "Deployment is running."
echo "Local health: http://127.0.0.1:${PUBLIC_PORT}/health"
echo "Public URL:   http://${server_host}:${PUBLIC_PORT}"
echo
echo "Useful commands:"
echo "  docker compose --env-file $ENV_FILE -f $COMPOSE_FILE ps"
echo "  docker compose --env-file $ENV_FILE -f $COMPOSE_FILE logs -f"
echo "  docker compose --env-file $ENV_FILE -f $COMPOSE_FILE down"
