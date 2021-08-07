ARG CONSUL_TEMPLATE_VERSION=0.26.0
ARG NGINX_VER=1.21.1-alpine

FROM hashicorp/consul-template:${CONSUL_TEMPLATE_VERSION} as consul-template

FROM nginx:${NGINX_VER} as entrykit

ARG ENTRYKIT_VERSION=0.4.0

ADD https://github.com/progrium/entrykit/releases/download/v${ENTRYKIT_VERSION}/entrykit_${ENTRYKIT_VERSION}_Linux_x86_64.tgz /tmp/
RUN cd /tmp && \
  tar -xvzf entrykit_${ENTRYKIT_VERSION}_Linux_x86_64.tgz && \
  rm entrykit_${ENTRYKIT_VERSION}_Linux_x86_64.tgz && \
  mv entrykit /bin/entrykit && \
  chmod +x /bin/entrykit && \
  entrykit --symlink

# Creating symlink /bin/entrykit ...
# Creating symlink /bin/codep ...
# Creating symlink /bin/prehook ...
# Creating symlink /bin/render ...
# Creating symlink /bin/switch ...

FROM nginx:${NGINX_VER}


COPY --from=consul-template /bin/consul-template /bin/consul-template
COPY --from=entrykit /bin/entrykit /bin/codep

ENV CONSUL_HOST consul

ADD  "ng.sh" "ct.sh" /
ADD ./nginx.conf /etc/consul-templates/app.conf

CMD [ "/bin/codep", "/ct.sh", "/ng.sh" ]
