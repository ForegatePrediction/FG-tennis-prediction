#!/usr/bin/env bash
# Install root-owned as /usr/local/libexec/fg-tennis-model-update.sh.
set -euo pipefail
exec 9>/run/lock/fg-gateway-update.lock
flock -n 9 || exit 0
store=/var/lib/foregate/tennis/models
old=$(readlink "$store/current")
[[ "$old" =~ ^[a-f0-9]{64}$ ]]
result=$(sudo -u fggateway env PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 /opt/fg-tennis-current/production_models.py --pull "$store")
echo "$result"
changed=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["changed"])' <<<"$result")
if [ "$changed" != True ]; then exit 0; fi
rollback() {
  ln -sfn "$old" "$store/current.rollback"
  mv -Tf "$store/current.rollback" "$store/current"
  systemctl restart fg-gateway
  echo 'Tennis model health verification failed; previous generation restored' >&2
}
trap rollback ERR
systemctl restart fg-gateway
healthy=0
for attempt in $(seq 1 45); do
  if curl --fail --silent --max-time 5 http://127.0.0.1:8000/health > /run/fg-tennis-health.json; then
    if python3 - <<'PY'
import json
h=json.load(open('/run/fg-tennis-health.json'))
assert h['status']=='ok'
assert h['engines']['tennis']['status']=='ok'
PY
    then healthy=1;break;fi
  fi
  sleep 2
done
if [ "$healthy" != 1 ]; then false;fi
trap - ERR
echo 'Verified and installed daily tennis model'
