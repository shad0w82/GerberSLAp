# GerberSLAp: the app on http://<host>:8800, with its data folder in the volume /data.
#
# The image holds the program and nothing else: no .ctb file (the printer's template is installed in the volume, see docs/en/installation/requirements.md), no data, no tests.
# One container per volume. The app has no authentication: do not expose it to the Internet.
FROM python:3.14-slim

LABEL org.opencontainers.image.title="GerberSLAp" \
      org.opencontainers.image.description="Print files for exposing printed circuit boards with a resin printer" \
      org.opencontainers.image.licenses="AGPL-3.0-only"

# GERBERSLAP_HOST: inside a container the server listens on every interface (the address the host reaches it by is chosen when the port is published).
# GERBERSLAP_DATA: the data folder is the volume.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GERBERSLAP_HOST=0.0.0.0 \
    GERBERSLAP_DATA=/data

# an unprivileged user owns the data folder
RUN groupadd --system --gid 10001 gerberslap \
 && useradd --system --uid 10001 --gid gerberslap --no-create-home --shell /usr/sbin/nologin gerberslap \
 && mkdir /data \
 && chown gerberslap:gerberslap /data

WORKDIR /app

# the dependencies first: this layer is rebuilt only when requirements.txt changes
COPY requirements.txt ./
RUN pip install --root-user-action=ignore -r requirements.txt

# the program (the package, with the printers' photos and the reader and writer of their files) and the licence
COPY LICENSE ./
COPY gerberslap ./gerberslap

USER gerberslap
VOLUME /data
EXPOSE 8800

# the app answers on its own address, whatever name it is reached by from outside
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request as u; u.urlopen('http://127.0.0.1:%s/api/info' % os.environ.get('GERBERSLAP_PORT', '8800'), timeout=4)"]

# the options of the command go after the image name: docker run IMAGE --install-template ld002h /in/template.ctb
ENTRYPOINT ["python", "-m", "gerberslap.web"]
