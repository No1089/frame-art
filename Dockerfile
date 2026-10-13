# One image for both halves: the web gallery (the default command) and the
# pipeline with its timers (deploy/scheduler.sh). The layout inside is the one
# the systemd units and run_pipeline.sh already assume, a checkout with a
# .venv in it, so nothing in the scripts knows it is in a container.

FROM python:3.13-slim AS deps
# git is only here to install the pinned samsungtvws fork; it stays in this stage.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN python -m venv /app/.venv \
 && /app/.venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

FROM python:3.13-slim
# DejaVu Serif is the first font config.py finds on Linux; without it labels
# fall back to a bitmap face. ffmpeg is a few hundred megabytes and only the
# video render needs it, so it is opt-in: --build-arg FFMPEG=1.
ARG FFMPEG=0
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core \
      $([ "$FFMPEG" = 1 ] && echo ffmpeg) \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=deps /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH
COPY config.py fetch_art.py prepare_images.py push_to_frame.py frame_control.py \
     export_stills.py make_slideshow.py run_pipeline.sh ./
COPY web ./web
COPY deploy/scheduler.sh ./deploy/
# The library is the volume, and the pairing token lives in it too, so a
# recreated container is still paired. tv-token.txt and uploaded.json are the
# two files the README says to back up; this keeps them in one place.
RUN ln -s library/tv-token.txt tv-token.txt
VOLUME /app/library
EXPOSE 5000
CMD ["python", "web/app.py"]
