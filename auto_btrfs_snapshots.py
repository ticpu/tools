#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# auto_btrfs_snapshots.py manages BTRFS snapshots, automatically purging
# them after a programmable number of days.
#
# Copyright (C) 2015 Jérôme Poulin <jeromepoulin@gmail.com>
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

from datetime import datetime, timezone, timedelta
from operator import attrgetter
import optparse
import os
import shlex
import subprocess
import sys
import time


BTRFS = "btrfs"
_si_prefix = {
	'k': 1e3,  # kilo
	'M': 1e6,  # mega
	'G': 1e9,  # giga
	'T': 1e12,  # tera
	'P': 1e15,  # peta
	'E': 1e18,  # exa
	'Z': 1e21,  # zetta
	'Y': 1e24,  # yotta
}


def to_localtime(ts):
	"""Convert datetime object from UTC to local time zone"""
	return datetime(*time.localtime((ts - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds())[:6])


def prune_within(archives, hours):
	target = datetime.now(timezone.utc) - timedelta(seconds=hours * 3600)
	return [a for a in archives if a.ts > target]


def prune_split(archives, pattern, n, skip=None):
	if skip is None:
		skip = []
	last = None
	keep = []
	if n == 0:
		return keep

	for a in sorted(archives, key=attrgetter('ts'), reverse=True):
		period = to_localtime(a.ts).strftime(pattern)
		if period != last:
			last = period
			if a not in skip:
				keep.append(a)
				if len(keep) == n:
					break
	return keep


def process_call(subprocess_args, do_action):
	if do_action:
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


def free_space_check(path, minimum_free_space):
	"""
	@param path: Path to check free space.
	@param minimum_free_space: Minimum free space in bytes, SI unit or percent.
	@return: True if minimum_free_space is available, else False.
	@rtype: bool
	"""
	statvfs = os.statvfs(path)
	free_space = statvfs.f_frsize * statvfs.f_bavail
	minimum_free_space_bytes = 0

	if minimum_free_space:
		try:
			minimum_free_space_bytes = int(minimum_free_space)
		except ValueError:
			if minimum_free_space.endswith("%"):
				pass
			elif minimum_free_space[-1] in _si_prefix:
				pass
	else:
		return True

	return free_space > minimum_free_space_bytes


class Archive(object):
	def __init__(self, path, name, time_format):
		self.path = os.path.abspath(os.path.join(path, name))
		self.name = name
		ts = datetime.strptime(name, time_format)
		self.ts = ts.replace(tzinfo=timezone.utc)


class Volume(object):
	def __init__(self, path, options):
		self.options = options
		self.show_snapshot_kept = options.snapshot_kept
		self.do_action = options.do_action
		self.do_create = options.do_create
		self.latest_snapshot = options.latest_snapshot
		self.path = os.path.abspath(path)
		self.snapshot_name_format = options.snapshot_prefix + options.time_format
		self.snapshot_dir = os.path.abspath(os.path.join(path, options.snapshot_dir))

	def list_archives(self):
		for snapshot in os.listdir(self.snapshot_dir):
			if snapshot.startswith(self.options.snapshot_prefix):
				yield Archive(self.snapshot_dir, snapshot, self.snapshot_name_format)

	def prune_backups(self):
		"""Prune repository archives according to specified rules"""
		if not any((self.options.secondly, self.options.minutely, self.options.hourly, self.options.daily,
					self.options.weekly, self.options.monthly, self.options.yearly, self.options.within)):
			if not self.options.quiet:
				sys.stderr.write("Not cleaning backups since we have not received any cleaning options.\n")
				return

		archives = list(self.list_archives())

		keep = []
		if self.options.within:
			keep += prune_within(archives, self.options.within)
		if self.options.secondly:
			keep += prune_split(archives, '%Y-%m-%d %H:%M:%S', self.options.secondly, keep)
		if self.options.minutely:
			keep += prune_split(archives, '%Y-%m-%d %H:%M', self.options.minutely, keep)
		if self.options.hourly:
			keep += prune_split(archives, '%Y-%m-%d %H', self.options.hourly, keep)
		if self.options.daily:
			keep += prune_split(archives, '%Y-%m-%d', self.options.daily, keep)
		if self.options.weekly:
			keep += prune_split(archives, '%G-%V', self.options.weekly, keep)
		if self.options.monthly:
			keep += prune_split(archives, '%Y-%m', self.options.monthly, keep)
		if self.options.yearly:
			keep += prune_split(archives, '%Y', self.options.yearly, keep)

		to_delete = set(archives) - set(keep)

		if self.show_snapshot_kept:
			for snapshot in keep:
				print("Keep: " + snapshot.name)

		for snapshot in to_delete:
			self.snapshot_delete(snapshot.path)

	def _btrfs_snapshot_create(self, snapshot):
		if self.do_create:
			return process_call([
				BTRFS, "subvolume", "snapshot", "-r",
				self.path,
				os.path.abspath(snapshot),
			], self.do_action)

	def snapshot_create(self, snapshot=None):
		if snapshot is None:
			snapshot = os.path.join(self.snapshot_dir, datetime.now().strftime(self.snapshot_name_format))

		if self.options.snapshot_create_command:
			process_call(
				shlex.split(self.options.snapshot_create_command.format(source=self.path, destination=snapshot)),
				self.do_action,
			)
		else:
			self._btrfs_snapshot_create(snapshot)

	def _btrfs_snapshot_delete(self, snapshot):
		return process_call([
			BTRFS, "subvolume", "delete",
			os.path.abspath(snapshot)
		], self.do_action)

	def snapshot_delete(self, snapshot):
		if self.options.snapshot_delete_command:
			process_call(shlex.split(self.options.snapshot_delete_command.format(snapshot=snapshot)), self.do_action)
		else:
			self._btrfs_snapshot_delete(snapshot)

	def snapshot_update_latest(self):
		latest_path = os.path.abspath(os.path.join(self.path, self.latest_snapshot))

		if os.path.isdir(latest_path):
			self.snapshot_delete(latest_path)

		self.snapshot_create(os.path.join(self.path, latest_path))


def parse_options():
	parser = optparse.OptionParser("usage: %prog [options] source_subvolume")
	parser.add_option(
		"--keep-within", dest="within", type="int",
		default=None, metavar="HOURS",
		help="Keep all archives within this number of hours.",
	)
	parser.add_option(
		"--keep-last", dest="secondly", type="int",
		default=None, metavar="LAST",
		help="Minimum number of archives to keep.",
	)
	parser.add_option(
		"--keep-minutely", dest="minutely", type="int",
		default=None, metavar="MINUTELY",
		help="Number of minutely archives to keep.",
	)
	parser.add_option(
		"--keep-hourly", dest="hourly", type="int",
		default=None, metavar="HOURLY",
		help="Number of hourly archives to keep.",
	)
	parser.add_option(
		"--keep-daily", dest="daily", type="int",
		default=None, metavar="DAILY",
		help="Number of daily archives to keep.",
	)
	parser.add_option(
		"--keep-weekly", dest="weekly", type="int",
		default=None, metavar="WEEKLY",
		help="Number of hourly archives to keep.",
	)
	parser.add_option(
		"--keep-monthly", dest="monthly", type="int",
		default=None, metavar="MONTHLY",
		help="Number of monthly archives to keep.",
	)
	parser.add_option(
		"--keep-yearly", dest="yearly", type="int",
		default=None, metavar="YEARLY",
		help="Number of yearly archives to keep.",
	)
	parser.add_option(
		"-f", "--free-space", dest="free_space", type="str",
		default=None, metavar="NUM",
		help="Minimum free space before starting to clean snapshots. "
			 "Free space can be specified using either a percentage or a number "
			 "followed by an SI unit. See man 7 units for reference.",
	)
	parser.add_option(
		"-l", "--latest", dest="latest_snapshot",
		default="", metavar="PATH",
		help="When not empty, delete and create a second snapshot at this PATH.",
	)
	parser.add_option(
		"-n", "--no-action", dest="do_action",
		action="store_false", default=True,
		help="Echo all active BTRFS commands issued without execution.",
	)
	parser.add_option(
		"--no-create", dest="do_create",
		action="store_false", default=True,
		help="Echo all active BTRFS commands issued without execution.",
	)
	parser.add_option(
		"-k", "--snapshot-kept", dest="snapshot_kept",
		action="store_true", default=False,
		help="Echo all snapshot kept and not deleted.",
	)
	parser.add_option(
		"-p", "--snapshot-prefix", dest="snapshot_prefix",
		default="@GMT-", metavar="NAME",
		help="Prefix to the snapshot directory, used when selecting snapshot for automatic removal."
	)
	parser.add_option(
		"-q", "--quiet", dest="quiet",
		action="store_true", default=False,
		help="Closes stdout and stderr.",
	)
	parser.add_option(
		"-s", "--snapshot-dir", dest="snapshot_dir",
		default=".snapshots", metavar="SNAPDIR",
		help="Relative path of the snapshot directory. Relative to snapshot source.",
	)
	parser.add_option(
		"-t", "--time-format", dest="time_format",
		default="%Y.%m.%d-%H.%M.%S", metavar="TIMEFMT",
		help="Time format to append to snapshot prefix, uses date(1) compatible format.",
	)
	parser.add_option(
		"--snapshot-create-command", dest="snapshot_create_command",
		default=None, metavar="COMMAND",
		help="Snapshot create command, use {source} and {destination} to specify how to create the snapshot.",
	)
	parser.add_option(
		"--snapshot-delete-command", dest="snapshot_delete_command",
		default=None, metavar="COMMAND",
		help="Snapshot delete command, use {snapshot} to specify how to delete the snapshot.",
	)
	options, args = parser.parse_args()

	if len(args) != 1:
		parser.error("The only non-option argument is the directory to snapshot.")

	return options, args


def main():
	options, args = parse_options()

	if options.quiet:
		sys.stdout.close()
		sys.stdout = open("/dev/null", 'w')
		sys.stderr.close()
		sys.stderr = open("/dev/null", 'w')

	volume = Volume(args[0], options)
	volume.snapshot_create()

	if options.do_action:
		os.utime(volume.path, None)

	if options.latest_snapshot:
		volume.snapshot_update_latest()

	if options.free_space is None or (options.free_space and free_space_check(volume.snapshot_dir, options.free_space)):
		volume.prune_backups()


if __name__ == "__main__":
	main()
