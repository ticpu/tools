#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# fdmanage.py is a program to manage file descriptors of running programs
# by using GDB to modify the running program.
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

from __future__ import unicode_literals

import fcntl
import optparse
import os
import select
import subprocess


class Gdb(object):
	def __init__(self, pid, verbose=False):
		pid = str(pid)

		# if verbose:
		# 	output = None
		# else:
		# 	output = open("/dev/null", "w")

		self.gdb = subprocess.Popen(
			["gdb", "-q", "-p", pid],
			stdin=subprocess.PIPE,
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
			close_fds=True,
		)
		self.pid = pid
		self.verbose = verbose
		fcntl.fcntl(
			self.gdb.stdout.fileno(),
			fcntl.F_SETFL,
			os.O_NONBLOCK,
		)

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc_val, exc_tb):
		del exc_type, exc_val, exc_tb

		self.send_command("detach")
		self.send_command("quit")
		self.gdb.stdin.close()
		self.gdb.wait()

		if self.verbose:
			print(self.gdb.stdout.read())
			print("\nProgram terminated.")

	def send_command(self, command):
		self.gdb.stdin.write(command.encode("utf8") + b"\n")
		self.gdb.stdin.flush()

	def send_command_expect(self, command):
		self.send_command(command)
		while True:
			try:
				data = self.gdb.stdout.readline().decode("utf8")
				if self.verbose:
					print(data)
				if " = " in data:
					return data.split("=", 1)[-1].strip()
			except IOError:
				ready = select.select([self.gdb.stdout], [], [], 5)
				if len(ready[0]) == 0:
					raise RuntimeError("GDB took too long to respond.")

	def close_fd(self, fd):
		self.send_command("call close(%d)" % int(fd))

	def dup2(self, old_fd, new_fd):
		self.send_command("call dup2(%d, %d)" % (int(old_fd), int(new_fd)))

	def open_file(self, path):
		fd = get_file_opened(self.pid, path)

		if not fd:
			fd_expected = self.send_command_expect('call open("%s", 66)' % path)
			fd = get_file_opened(self.pid, path)

			if fd != fd_expected:
				raise ValueError("Asked for FD #%d but received #%d." % (int(fd_expected), int(fd)))

		return fd


def get_file_opened(pid, path):
	for fd in os.listdir("/proc/%s/fd" % pid):
		fd_link = "/proc/%s/fd/%s" % (pid, fd)
		if os.path.islink(fd_link):
			fd_path = os.readlink(fd_link)
			if fd_path == path:
				return fd


def check_fd(parser, pid, fd):
	if not os.path.islink("/proc/%s/fd/%s" % (pid, fd)):
		parser.error("File descriptor %s does not exist for PID %s." % (fd, pid))


def parse_command():
	parser = optparse.OptionParser(
		usage="usage: %prog [options] [PID] [FD]\n"
		"Allows to close a file descriptor from a PID or swap it for another\n"
		"file. Default option is to close the file descriptor. Uses GDB."
	)

	parser.add_option(
		"-g", "--gdb-output",
		action="store_true", dest="gdb_verbose", default=False,
		help="Show GDB output.",
	)
	parser.add_option(
		"-c", "--copy", metavar="FD",
		action="store", dest="copy", default=None,
		help="Replace the file descriptor with a copy of one already open."
	)
	parser.add_option(
		"-r", "--replace", metavar="FILE",
		action="store", dest="replace", default=None,
		help="Replace the file descriptor with a new file."
	)
	parser.add_option(
		"-s", "--swap", metavar="FD", type="int",
		action="store", dest="swap", default=None,
		help="Exchange the file descriptor with one already open."
	)

	options, args = parser.parse_args()

	if len(args) != 2:
		parser.error("Need exactly 2 arguments.")

	pid = args[0]
	fd = args[1]

	if not os.path.isdir("/proc/%s" % pid):
		parser.error("Process %s does not exist." % pid)

	if (bool(options.copy) + bool(options.replace) + bool(options.swap)) > 1:
		parser.error("Options -c, -r and -s are mutually exclusive.")

	if options.replace:
		if not (os.access(options.replace, os.W_OK) or os.access(os.path.dirname(options.replace), os.W_OK)):
			parser.error("File used in -r is not writable.")

	if options.swap == fd or options.copy == fd:
		parser.error("Can not operate on the same FD twice.")

	for fd_to_check in (fd, options.copy, options.swap):
		if fd_to_check:
			check_fd(parser, pid, fd_to_check)

	return options, args


def main():
	options, args = parse_command()

	fd_to_replace = args[1]

	with Gdb(args[0], options.gdb_verbose) as gdb:
		if options.replace:
			fd = gdb.open_file(options.replace)
			gdb.dup2(fd, fd_to_replace)
			gdb.close_fd(fd)
		elif options.swap:
			fd = gdb.open_file("/dev/null")
			gdb.dup2(options.swap, fd)
			gdb.dup2(fd_to_replace, options.swap)
			gdb.dup2(fd, options.swap)
			gdb.close_fd(fd)
		elif options.copy:
			gdb.dup2(options.copy, fd_to_replace)
		else:
			gdb.close_fd(fd_to_replace)

if __name__ == "__main__":
	main()
