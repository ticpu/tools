#!/usr/bin/env python
# -*- coding: utf8 -*- 

import datetime
import optparse
import os
import subprocess
import sys

BTRFS = "btrfs"


def process_call(subprocess_args):
	if options.do_action:
		process = subprocess.Popen(
			subprocess_args,
			stdin=None,
			stdout=sys.stderr,
			stderr=sys.stderr,
			shell=False
		)
		process.wait()
	else:
		print(" ".join(subprocess_args))


parser = optparse.OptionParser("usage: %prog [options] source_subvolume")
parser.add_option(
	"-q", "--quiet", dest="quiet",
	action="store_true", default=False,
	help="Closes stdout and stderr.",
)
parser.add_option(
	"-n", "--no-action", dest="do_action",
	action="store_false", default=True,
	help="Echo all active BTRFS commands issued without execution.",
)
parser.add_option(
	"-d", "--days", dest="days", type="int",
	default=7, metavar="DAYS",
	help="Minimum number of days to keep snapshots before cleaning.",
)
parser.add_option(
	"-s", "--snapshot-dir", dest="snapshot_dir",
	default=".snapshots", metavar="SNAPDIR",
	help="Relative path of the snapshot directory. Relative to snapshot source.",
)
parser.add_option(
	"-p", "--snapshot-prefix", dest="snapshot_prefix",
	default="@GMT-", metavar="NAME",
	help="Prefix to the snapshot directory, used when selecting snapshot for automatic removal."
)
parser.add_option(
	"-l", "--latest", dest="latest_snapshot",
	default="", metavar="PATH",
	help="When not empty, delete and create a second snapshot at this PATH.",
)
parser.add_option(
	"-t", "--time-format", dest="time_format",
	default="@GMT-%Y.%m.%d-%H.%M.%S", metavar="TIMEFMT",
	help="Time format to append to snapshot prefix, uses date(1) compatible format.",
)
(options, args) = parser.parse_args()

if len(args) != 1:
	parser.error("The only non-option argument is the directory to snapshot.")

if options.quiet:
	sys.stdout.close()
	sys.stdout = open("/dev/null", 'w')
	sys.stderr.close()
	sys.stderr = open("/dev/null", 'w')

source_subvolume = args[0]

current_time = datetime.datetime.utcnow()
time_format = options.snapshot_prefix + options.time_format
formatted_time = current_time.strftime(time_format)

os.utime(source_subvolume, None)
process_call([
		BTRFS, "subvolume", "snapshot", "-r",
		os.path.abspath(source_subvolume),
		os.path.abspath(os.path.join(source_subvolume, options.snapshot_dir, formatted_time)),
])

if options.latest_snapshot:
	latest_path = os.path.abspath(os.path.join(source_subvolume, options.latest_snapshot))

	if os.path.isdir(latest_path):
		process_call([BTRFS, "subvolume", "delete", latest_path])

	process_call([
		BTRFS, "subvolume", "snapshot", "-r",
		os.path.abspath(source_subvolume),
		latest_path,
	])

snapshot_dir = os.path.abspath(os.path.join(source_subvolume, options.snapshot_dir))
for i in os.listdir(snapshot_dir):
	if i.startswith(options.snapshot_prefix):
		try:
			snapshot_time = datetime.datetime.strptime(i, time_format)
		except ValueError:
			continue
		if (current_time - snapshot_time).days > options.days:
			process_call([BTRFS, "subvolume", "delete", os.path.join(snapshot_dir, i)])
