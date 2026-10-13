#!/bin/sh
# The two timers in this directory, for a container that has no systemd: the
# pipeline once a month and the rotation check once a minute. Runs for ever;
# docker-compose.yml starts it as the `pipeline` service.
#
# The pipeline runs on the first start of each month after PIPELINE_HOUR
# (container time, so set TZ). Which month it last ran for is a file in the
# library, so a container that was down on the 1st catches up when it comes
# back, the way Persistent=true does for the timer.
set -u
cd "$(dirname "$0")/.."

STAMP=library/.pipeline-month
HOUR=${PIPELINE_HOUR:-4}
warned=

paired() {
    python -c 'import config, pathlib, sys
sys.exit(0 if pathlib.Path(config.TV_TOKEN_FILE).exists() else 1)'
}

while true; do
    month=$(date +%Y-%m)
    if [ "$(date +%H)" -ge "$HOUR" ] && [ "$(cat "$STAMP" 2>/dev/null)" != "$month" ]; then
        # Written before the run, not after. A failed run should be a line in
        # the log and a run by hand, not a 40 minute fetch retried every minute.
        mkdir -p library && echo "$month" > "$STAMP"
        echo "== pipeline for $month =="
        ./run_pipeline.sh \
            || echo "pipeline failed; when it is fixed: docker compose run --rm pipeline ./run_pipeline.sh"
    fi
    if paired; then
        warned=
        # --only-in-artmode is load bearing: see frame-art-rotate.service.
        python push_to_frame.py --rotate --only-in-artmode --min-interval 3 --quiet-if-offline
    elif [ -z "$warned" ]; then
        # Not a retry loop on purpose: every attempt to connect without a token
        # puts the allow prompt on the TV. Pairing is a thing a person does.
        echo "not paired with a TV; to pair: docker compose run --rm pipeline python push_to_frame.py --check"
        warned=1
    fi
    sleep 60
done
