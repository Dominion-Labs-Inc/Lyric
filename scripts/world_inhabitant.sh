#!/bin/sh
# Lyric's attachment to its world (Tet), kept running by launchd
# (~/Library/LaunchAgents/org.dmnlabs.lyric.inhabitant.plist).
#
# Lyric runs by itself, on this host; Tet runs in its containers. This attaches Lyric's appraisal authority
# to the world as its inhabitant, through the inhabitant's door on loopback, so what a person sends through
# the gate for Lyric (their reward allowance) reaches it. It starts none of Lyric's own work.
#
# The inhabitant's key is read from Tet's secrets at each start, so it lives in one place.
set -eu
cd "$(dirname "$0")/.."
TET_SECRETS="../Tet/deploy/.env"
TET_OPERATOR_PRIVATE_KEY="$(/usr/bin/grep '^TET_OPERATOR_PRIVATE_KEY=' "$TET_SECRETS" | /usr/bin/cut -d= -f2-)"
[ -n "$TET_OPERATOR_PRIVATE_KEY" ] || { echo "no TET_OPERATOR_PRIVATE_KEY in $TET_SECRETS" >&2; exit 1; }
export TET_OPERATOR_PRIVATE_KEY
export TET_WORLD_ADDRESS="127.0.0.1:9251"
export POSTGRES_DATABASE="lyric_db"
exec ./venv_lyric/bin/python3 -u -m core.integration.world_inhabitant
