#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# auto_bcachefs_snapshots.py manages BcacheFS snapshots, automatically purging
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


BCACHEFS = "bcachefs"
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


class SnapshotError(Exception):
	pass


def process_call(subprocess_args, do_action):
	"""Run a command and return its exit status."""
	if not do_action:
		print(" ".join(subprocess_args))
		return 0

	process = subprocess.Popen(
		subprocess_args,
		stdin=None,
		stdout=sys.stderr,
		stderr=sys.stderr,
		shell=False
	)
	return process.wait()


def checked_call(subprocess_args, do_action):
	returncode = process_call(subprocess_args, do_action)
	if returncode != 0:
		raise SnapshotError("%s exited %d" % (" ".join(subprocess_args), returncode))


def free_space_check(path, minimum_free_space):
	"""
	@param path: Path to check free space.
	@param minimum_free_space: Byte count, SI-suffixed size (100G) or percentage of the
		filesystem (10%). Empty or None means no constraint.
	@return: True if minimum_free_space is available, else False.
	@rtype: bool
	"""
	if not minimum_free_space:
		return True

	statvfs = os.statvfs(path)
	free_space = statvfs.f_frsize * statvfs.f_bavail

	if minimum_free_space.endswith("%"):
		total = statvfs.f_frsize * statvfs.f_blocks
		minimum_free_space_bytes = total * float(minimum_free_space[:-1]) / 100
	elif minimum_free_space[-1] in _si_prefix:
		minimum_free_space_bytes = float(minimum_free_space[:-1]) * _si_prefix[minimum_free_space[-1]]
	else:
		minimum_free_space_bytes = float(minimum_free_space)

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
		self.latest_snapshot = options.latest_snapshot
		self.path = os.path.abspath(path)
		self.snapshot_name_format = options.snapshot_prefix + options.time_format
		self.snapshot_dir = os.path.abspath(os.path.join(path, options.snapshot_dir))

	def list_archives(self):
		for snapshot in os.listdir(self.snapshot_dir):
			if not snapshot.startswith(self.options.snapshot_prefix):
				continue
			try:
				yield Archive(self.snapshot_dir, snapshot, self.snapshot_name_format)
			except ValueError:
				# Siblings share the prefix without carrying a timestamp, `<name>-latest` first
				# among them, and are not archives.
				continue

	def prune_backups(self):
		"""Prune repository archives according to specified rules"""
		if not any((self.options.secondly, self.options.minutely, self.options.hourly, self.options.daily,
					self.options.weekly, self.options.monthly, self.options.yearly, self.options.within)):
			sys.stderr.write("Not cleaning backups since we have not received any cleaning options.\n")
			return 0

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

		# One snapshot that refuses to go must not stop the rest from being reclaimed.
		failed = 0
		for snapshot in to_delete:
			try:
				self.snapshot_delete(snapshot.path)
			except SnapshotError as e:
				sys.stderr.write("%s\n" % e)
				failed += 1
		return failed

	def _bcachefs_snapshot_create(self, snapshot):
		return checked_call([
			BCACHEFS, "subvolume", "snapshot", "-r",
			self.path,
			os.path.abspath(snapshot),
		], self.do_action)

	def snapshot_create(self, snapshot=None):
		if snapshot is None:
			# Names are read back with strptime as UTC; generating them in local time would
			# shift every retention decision by the offset.
			stamp = datetime.now(timezone.utc).strftime(self.snapshot_name_format)
			snapshot = os.path.join(self.snapshot_dir, stamp)

		# Two runs inside one time-format tick want the same name. The archive is already
		# there, so pruning should still proceed rather than the run dying on EEXIST.
		if self.do_action and os.path.exists(snapshot):
			sys.stderr.write("%s already exists, keeping it\n" % snapshot)
			return

		if self.options.snapshot_create_command:
			checked_call(
				shlex.split(self.options.snapshot_create_command.format(source=self.path, destination=snapshot)),
				self.do_action,
			)
		else:
			self._bcachefs_snapshot_create(snapshot)

	def _bcachefs_snapshot_delete(self, snapshot):
		return checked_call([
			BCACHEFS, "subvolume", "delete",
			os.path.abspath(snapshot)
		], self.do_action)

	def snapshot_delete(self, snapshot):
		if self.options.snapshot_delete_command:
			checked_call(shlex.split(self.options.snapshot_delete_command.format(snapshot=snapshot)), self.do_action)
		else:
			self._bcachefs_snapshot_delete(snapshot)

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
		"-d", "--days", dest="days", type="int",
		default=None, metavar="DAYS",
		help="Keep all archives within this number of days. Same setting as --keep-within.",
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
		help="Echo all active BcacheFS commands issued without execution.",
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
		help="Discard stdout. Errors still go to stderr.",
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

	if options.days is not None:
		if options.within is not None:
			parser.error("-d/--days and --keep-within set the same thing, pass only one.")
		options.within = options.days * 24

	return options, args


def main():
	options, args = parse_options()

	if options.quiet:
		sys.stdout.close()
		sys.stdout = open(os.devnull, 'w')

	volume = Volume(args[0], options)

	# Pruning past this point would delete history without anything replacing it, so a failed
	# snapshot ends the run. A source that is a plain directory rather than a subvolume fails
	# here, every time, instead of quietly aging out every archive it already had.
	try:
		volume.snapshot_create()

		if options.do_action:
			os.utime(volume.path, None)

		if options.latest_snapshot:
			volume.snapshot_update_latest()
	except SnapshotError as e:
		sys.stderr.write("%s: %s\nrefusing to prune\n" % (volume.path, e))
		return 1

	if not free_space_check(volume.snapshot_dir, options.free_space):
		return 0

	return 1 if volume.prune_backups() else 0


if __name__ == "__main__":
	sys.exit(main())
