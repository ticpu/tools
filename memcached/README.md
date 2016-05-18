## Automatic memcache replication on service restart. ##
Make sure you are aware that memcached-tool dump command can lock your memcached instance for a while if it has a lot of records, this warning is displayed when running the memcached-tool.

1. Copy memcache-copy.sh and memcache-firewall.sh in `/usr/local/sbin/`
2. Copy memcached.service-override.conf in `/etc/systemd/system/memcached.service/override.conf`
3. Copy memcached.default in `/etc/default/memcached`
4. Edit /etc/default/memcached to modify the `REMOTE_HOST` var.
5. Make sure you can connect to the remote memcached instance.
6. Execute `systemctl daemon-reload`.
7. Restart memcached with `systemctl restart memcached` to test the setup.
8. Execute `/usr/share/memcached/scripts/memcached-tool 127.0.0.1:11211 dump` to confirm replication has been completed.
