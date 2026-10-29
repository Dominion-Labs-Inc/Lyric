#!/bin/sh
# LYRIC ITSELF, ATTACHED TO ITS WORLD: the Lyric that takes people's turns.
#
# `world_inhabitant.sh` attaches the appraisal authority alone, with no Lyric behind it: it answers a person's
# reward allowance and nothing else, and leaves a person's turn, what their device hears and what it reports
# waiting in the world for the Lyric that can take them. This starts that Lyric.
#
# What reaches it through the gate: each message typed in Chat on the web platform or the phone (one turn of
# that person's own conversation, answered at Lyric's front door), what their device hears while Listening or
# voice mode is on, and what their device reports of itself.
#
# The world's address is given HERE and never defaulted in Lyric's code: a Lyric started for teaching or an
# experiment must not attach to the live world and take real people's turns.
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
export PYTHONPATH="$PWD"
exec ./venv_lyric/bin/python3 -u -m core.main
