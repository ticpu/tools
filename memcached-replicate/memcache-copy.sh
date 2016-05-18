#!/bin/sh -e

MEMCACHE_TOOL="${MEMCACHE_TOOL-/usr/share/memcached/scripts/memcached-tool}"
PORT=${REMOTE_CACHE##*:}
PORT=${PORT-11211}

echo -n "Waiting for memcache port ${PORT} to be ready."
for I in `seq 50`
do
	sleep 0.2
	echo -n "."
	nc -z 127.0.0.1 ${PORT} && { echo " OK"; break; }
done

echo "Copying cache from ${REMOTE_CACHE}."
$MEMCACHE_TOOL $REMOTE_CACHE dump | nc -q 1 -v 127.0.0.1 ${PORT}
echo "Removing firewall from port ${PORT}."
/sbin/iptables -D INPUT ! -d 127.0.0.0/8 -p tcp --dport ${PORT} -j REJECT --reject-with tcp-reset || continue
echo "Memcache ready."

exit 0
