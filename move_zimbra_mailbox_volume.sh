#!/bin/bash
# -*- coding: utf-8 -*-
#
# move_zimbra_mailbox_volume.sh Allows moving a mailbox in Zimbra from
# one volume to another.
#
# Usage:
# move_zimbra_mailbox_volume.sh <account@domain.com> \
#   <source_path> <destination_path> <rsync_options>
#
# Copyright (C) 2019 Jérôme Poulin <jeromepoulin@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

set -e

[ -z $3 ] && {
	echo "Usage: $0 <account@domain.com> <source> <destination> <rsync options>" 1>&2
	exit 2
}

ACCOUNT="$1"; shift
SOURCE="`readlink -f $1`"; shift
DESTINATION="`readlink -f $1`"; shift
RSYNC_OPTIONS="$*"

err () {
	echo "$*" 1>&2
	exit 1
}

get_volume_id () {
	local path="$1"

	mysql -NB zimbra -e "select id from volume where path=\"${path}\";"
}

get_account_ids () {
	local account_email="$1"

	mysql -NB zimbra -e "select id,group_id from mailbox where comment=\"${account_email}\";"
}

get_file_list () {
	local group_id="$1"
	local mbox_id="$2"
	local source_id="$3"

	cat << EOF | mysql -NB mboxgroup${group_id}
	select concat((mailbox_id >> 12), '/', mailbox_id, '/msg/', (id % (1024*1024) >> 12), '/', id, '-', mod_content, '.msg') as file
		from mail_item where mailbox_id=${mbox_id} and locator=${source_id};
EOF
}

update_location () {
	local group_id="$1"
	local mbox_id="$2"
	local source_id="$3"
	local destination_id="$4"

	cat << EOF | mysql -NB mboxgroup${group_id}
	update mail_item set locator=${destination_id}
		where mailbox_id=${mbox_id} and locator=${source_id};
EOF
}

SOURCE_ID=`get_volume_id "$SOURCE"`
DESTINATION_ID=`get_volume_id "$DESTINATION"`
FILE_LIST=`mktemp /tmp/zimbra.XXXXXXX`
read GROUP_ID MBOX_ID <<< `get_account_ids ${ACCOUNT}`

[ $SOURCE_ID -gt 0 ] || err "Can't find source ID."
[ $DESTINATION_ID -gt 0 ] || err "Can't find source ID."
[ -d "$SOURCE" -a -r "$SOURCE" ] || err "Can't read source at $SOURCE"
[ -d "$DESTINATION" -a -w "$DESTINATION" ] || err "Can't write to destonation at $DESTINATION"

get_file_list $GROUP_ID $MBOX_ID $SOURCE_ID > $FILE_LIST
rsync $RSYNC_OPTIONS -rpt --files-from="$FILE_LIST" "${SOURCE}/" "${DESTINATION}/"
update_location $GROUP_ID $MBOX_ID $SOURCE_ID $DESTINATION_ID
sed -e "s|^|${SOURCE}/|" $FILE_LIST | xargs -r rm
