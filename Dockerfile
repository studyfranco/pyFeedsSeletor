from debian:testing-slim

LABEL maintainer="studyfranco@gmail.com"

RUN set -x \
 && apt update \
 && DEBIAN_FRONTEND=noninteractive apt install -y python3 python3-feedparser python3-flask --no-install-recommends \
 && rm -rf /var/lib/apt/lists/* \
 && useradd -ms /bin/bash pyFeedsSeletor \
 && gosu nobody true \
 && mkdir -p /config/data \
 && chown -R pyFeedsSeletor:pyFeedsSeletor /config

COPY init.sh /
COPY --chown=pyFeedsSeletor:pyFeedsSeletor src/*.py run.sh /home/pyFeedsSeletor/
RUN chmod +x /init.sh \
 && chmod +x /home/pyFeedsSeletor/run.sh

WORKDIR /

ENV PGID="1000" \
    PUID="1000" \
    PORT="5050"

ENTRYPOINT [ "/init.sh" ]
