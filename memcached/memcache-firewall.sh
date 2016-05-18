#!/bin/sh -e

PORT=${REMOTE_CACHE##*:}
PORT=${PORT-11211}

/sbin/iptables -D INPUT ! -d 127.0.0.0/8 -p tcp --dport ${PORT} -j REJECT --reject-with tcp-reset || continue
echo "Firewalling port ${PORT}."
/sbin/iptables -I INPUT ! -d 127.0.0.0/8 -p tcp --dport ${PORT} -j REJECT --reject-with tcp-reset

exit 0
