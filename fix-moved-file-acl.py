#!/usr/bin/python3
import argparse
import logging
import os
import pyinotify
import re
import subprocess
import sys


class EventHandler(pyinotify.ProcessEvent):

	def __init__(self, exclude_regexes=None, **kwargs):
		super().__init__(**kwargs)
		self.logger = logging.getLogger("fix-acl")
		if exclude_regexes:
			self.exclude_regexes = []

			self.logger.info("compiling exclude regexes")
			for regex in exclude_regexes:
				self.logger.debug("compiling regex «%s»", regex)
				self.exclude_regexes.append(re.compile(regex))

	def reset_acl_for_file(self, event):
		self.logger.info("resetting permissions for file «%s» moved in «%s»", event.name, event.path)
		getfacl_process = subprocess.Popen(["getfacl", "-p", event.path], stdout=subprocess.PIPE, shell=False)
		(stdout, stderr) = getfacl_process.communicate()

		acl_output = b""
		for line in stdout.splitlines():
			if line.startswith(b"default:"):
				continue
			acl_output += line + b'\n'

		args = ["setfacl", "--set-file=/dev/stdin", event.pathname]
		setfacl_process = subprocess.Popen(
			["setfacl", "--set-file=/dev/stdin", event.pathname],
			stdin=subprocess.PIPE,
			shell=False,
		)
		setfacl_process.communicate(input=acl_output)

	def reset_acl_for_directory(self, event):
		self.logger.info("resetting permissions for directory «%s» moved in «%s»", event.name, event.path)
		getfacl_process = subprocess.Popen(["getfacl", "-p", event.path], stdout=subprocess.PIPE, shell=False)
		(stdout, stderr) = getfacl_process.communicate()
		setfacl_process = subprocess.Popen(
			["setfacl", "--set-file=/dev/stdin", event.pathname],
			stdin=subprocess.PIPE,
			shell=False,
		)
		setfacl_process.communicate(input=stdout)

	# noinspection PyPep8Naming
	def process_IN_MOVED_TO(self, event):
		for regex in self.exclude_regexes:
			if regex.search(event.pathname):
				self.logger.debug("path «%s» matches exclude regex «%s»", event.pathname, regex.pattern)
				return

		if event.dir is True:
			self.reset_acl_for_directory(event)
		else:
			self.reset_acl_for_file(event)


def parse_args():
	parser = argparse.ArgumentParser(description="Fix ACL on moved files.")
	parser.add_argument(
		"path_to_fix", metavar="PATH", type=str, nargs="+",
		help="paths to fix ACL for"
	)
	parser.add_argument(
		"-x", "--exclude-regex", metavar="REGEX", type=str, action="append",
		help="paths to exclude from automatic ACL fixing"
	)
	parser.add_argument(
		"-v", "--verbose", action="count", default=0,
		help="verbosity level, can be repeated twice"
	)
	return parser.parse_args()


def main():
	os.chdir("/")
	args = parse_args()

	if args.verbose == 1:
		level = logging.INFO
	elif args.verbose >= 2:
		level = logging.DEBUG
	else:
		level = logging.WARNING

	logging.basicConfig(level=level)
	logger = logging.getLogger("fix-acl")
	logger.setLevel(level)
	watch_manager = pyinotify.WatchManager()
	event_mask = pyinotify.IN_MOVED_TO
	handler = EventHandler(exclude_regexes=args.exclude_regex)
	notifier = pyinotify.Notifier(watch_manager, handler)
	logger.info("adding watches...")
	print(args)
	for path in args.path_to_fix:
		logger.debug("adding watch for «%s»", path)
		watch_manager.add_watch(path, event_mask, rec=True)
		logger.debug("watch for «%s» added", path)
	logger.info("ACL watcher is ready")
	notifier.loop()


if __name__ == "__main__":
	if len(sys.argv) < 2:
		sys.stderr.write("Usage: %s PATH_TO_MONITOR [PATH_TO_MONITOR..]\n" % os.path.basename(sys.argv[0]))
		sys.exit(2)

	try:
		main()
	except KeyboardInterrupt:
		sys.exit(0)
