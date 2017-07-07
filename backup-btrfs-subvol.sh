#!/bin/bash

set -e

BACKUPTO="/mnt/sg1vosrv08backup/vm"
BACKUPFROM="/mnt/vm"

sd () {
	[ -z $NOTIFY_SOCKET ] && return 0
	systemd-notifyw "$@"
}

get_last_snapshot () {
	ls -1dtr *-* | tail -n1
}

get_subvolume_ro () {
	btrfs property get "$1" ro | sed -e 's/ro=//'
}

sd "READY=1"

for D in snapshots
do
	sd "STATUS=Processing item '$D'..."
	echo "Processing item '$D'..." 1>&2
	cd $BACKUPTO/$D
	LAST_REMOTE_SNAPSHOT=`cd $BACKUPFROM/$D; ls -1dtr *-* | tail -n1`

	[ "$LAST_REMOTE_SNAPSHOT" == "`get_last_snapshot`" ] && [ "`get_subvolume_ro $BACKUPTO/$D/$LAST_REMOTE_SNAPSHOT`" == "true" ] && {
		echo "Last snapshot already up-to-date.";
		continue;
	}

	[ -d "$LAST_REMOTE_SNAPSHOT" ] && {
		echo "Deleting dangling snapshot '$LAST_REMOTE_SNAPSHOT'.";
		btrfs subvol del "$LAST_REMOTE_SNAPSHOT" || continue;
	}

	echo "btrfs send -p $BACKUPFROM/$D/`get_last_snapshot` $BACKUPFROM/$D/$LAST_REMOTE_SNAPSHOT | btrfs receive $BACKUPTO/$D/"
	btrfs send -p $BACKUPFROM/$D/`get_last_snapshot` $BACKUPFROM/$D/$LAST_REMOTE_SNAPSHOT | \
		pv -f -F "TIME %t RATE %r AVG %a DATA: %b
" -i 5 -L 40m | \
		btrfs receive $BACKUPTO/$D/

	find $BACKUPTO/$D -maxdepth 1 -ctime +14 -type d | head -n -5 | \
		xargs btrfs subvolume delete
done
