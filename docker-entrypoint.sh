#!/bin/sh
set -e
if [ -f "$APP_ENV_FILE" ]; then
  set -a
  . "$APP_ENV_FILE"
  set +a
fi
exec "$@"
