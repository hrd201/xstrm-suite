#!/usr/bin/env bash
# Test host only: scope published ports to the existing LAN zone.
set -euo pipefail
cd "$(dirname "$0")/.."
network_id=$(docker network inspect xstrm-test_default --format '{{.Id}}')
test_bridge="br-${network_id:0:12}"
for scope in runtime permanent; do
  flags=()
  if [[ "$scope" == permanent ]]; then flags=(--permanent); fi
  firewall-cmd "${flags[@]}" --zone=docker --add-interface="$test_bridge"
  for mapping in 'gateway 18091 8091' 'emby 18096 8096' 'openlist 15244 5244'; do
    read -r service published internal <<< "$mapping"
    cid=$(docker compose -f deploy/compose.test.yaml ps -q "$service")
    address=$(docker inspect "$cid" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
    [[ "$address" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]
    for old in $(firewall-cmd "${flags[@]}" --zone=lan --list-forward-ports); do
      if [[ "$old" == port="$published":* ]]; then
        firewall-cmd "${flags[@]}" --zone=lan --remove-forward-port="$old"
      fi
    done
    firewall-cmd "${flags[@]}" --zone=lan --add-forward-port="port=$published:proto=tcp:toport=$internal:toaddr=$address"
  done
  if grep -q 'listen 18443 ssl' deploy/test-nginx/conf.d/includes/https.conf; then
    cid=$(docker compose -f deploy/compose.test.yaml ps -q gateway)
    address=$(docker inspect "$cid" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
    [[ "$address" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]
    for zone in lan public; do
      for old in $(firewall-cmd "${flags[@]}" --zone="$zone" --list-forward-ports); do
        if [[ "$old" == port=18443:* ]]; then firewall-cmd "${flags[@]}" --zone="$zone" --remove-forward-port="$old"; fi
      done
      firewall-cmd "${flags[@]}" --zone="$zone" --add-forward-port="port=18443:proto=tcp:toport=18443:toaddr=$address"
    done
  fi
done
