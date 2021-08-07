#!/bin/ash

/bin/consul-template \
  -consul-addr=$CONSUL_HOST \
  -template "/etc/consul-templates/app.conf:/etc/nginx/conf.d/default.conf:/bin/ash -c 'nginx -s reload || true'"
