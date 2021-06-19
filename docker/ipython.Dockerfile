FROM socnet-app:latest
LABEL maintainer="Aksarin Mikhail <m.aksarin@gmail.com>"

USER root

RUN apk add libzmq --no-cache --update \
    && apk add --virtual .build-deps --no-cache --update \
    zeromq-dev && \
    pip3 install notebook && \
    apk del .build-deps


USER app

EXPOSE 8888/tcp

CMD ["ipython", "notebook", "--ip=0.0.0.0"]
