#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# fdmanage.py is a program to manage file descriptors of running programs
# by using gdb to modify the running program.
#
# copyright (c) 2019 jérôme poulin <jeromepoulin@gmail.com>
#
# this program is free software: you can redistribute it and/or modify
# it under the terms of the gnu general public license as published by
# the free software foundation, either version 3 of the license, or
# (at your option) any later version.
#
# this program is distributed in the hope that it will be useful,
# but without any warranty; without even the implied warranty of
# merchantability or fitness for a particular purpose.  see the
# gnu general public license for more details.
#
# you should have received a copy of the gnu general public license
# along with this program.  if not, see <http://www.gnu.org/licenses/>.
import argparse
import logging
import os
import re
import subprocess
import sys

from subprocess import DEVNULL, PIPE


def get_memory_stats(cgroup):
	memory_stats = {}

	for line in open(os.path.join(cgroup, "memory.stat")).readlines():
		k, v = line.split(' ')
		memory_stats[k] = int(v)

	return memory_stats


def get_containers_data():
	docker_process = subprocess.Popen(
		["docker", "container", "ls", "--format", "{{.ID}} {{.Image}} {{.Names}}"],
		shell=False, stdin=DEVNULL, stdout=PIPE, encoding='utf8',
	)
	(docker_stdout, docker_stderr) = docker_process.communicate(timeout=5)
	containers = {}
	for line in docker_stdout.splitlines():
		container, image, pod = line.split(' ', 3)
		pod_data = pod.split("_")
		containers[container] = {
			'namespace': pod_data[3],
			'pod_id': pod_data[4],
			'pod_name': pod_data[2],
			'image': image,
		}
	return containers


def parse_args():
	parser = argparse.ArgumentParser(
		description="list pods with their current and maximum memory usage",
	)
	parser.add_argument(
		"-H", "--human-readable", default=False, action="store_true",
		help="show memory usage in powers of 1024 (e.g., 1023M)",
	)
	parser.add_argument(
		"-i", "--ignore-inactive-cache", default=False, action="store_true",
		help="substract inactive file cache from used memory (total_inactive_file)",
	)
	return parser.parse_args()


def main():
	if not os.path.isdir("/sys/fs/cgroup/memory/kubepods"):
		raise("Path /sys/fs/cgroup/memory/kubepods is not a directory.")

	try:
		containers = get_containers_data()
	except:
		logging.exception("Could not get Docker data.")
		containers = {}

	args = parse_args()
	cgroup_list = os.walk("/sys/fs/cgroup/memory/kubepods")
	for cgroup, _, _ in cgroup_list:
		cgroup_re = re.match(".+/(pod\w{8}-\w{4}-\w{4}-\w{4}-\w{12})/(\w{64})$", cgroup)
		if cgroup_re:
			pod_id, container_id = cgroup_re.groups()
			container_id = container_id[:12]
			memory_stats = get_memory_stats(cgroup)
			memory_used = int(open(os.path.join(cgroup, "memory.usage_in_bytes")).read().strip())
			if args.ignore_inactive_cache:
				memory_used -= memory_stats['total_inactive_file']
			memory_max = int(open(os.path.join(cgroup, "memory.max_usage_in_bytes")).read().strip())
			memory_limit = int(open(os.path.join(cgroup, "memory.limit_in_bytes")).read().strip())
			if memory_limit == 9223372036854771712:
				memory_limit_percent = "NA"
				memory_max_percent = "NA"
			else:
				memory_limit_percent = "%.2f%%" % (memory_used/memory_limit*100,)
				memory_max_percent = "%.2f%%" % (memory_max/memory_limit*100,)

			if container_id in containers:
				container_name = "{c[namespace]}/{c[pod_name]}/{c[image]}".format(c=containers[container_id])
			else:
				container_name = "%s/%s/NA" % (pod_id, container_id)

			if args.human_readable:
				numfmt = subprocess.Popen(["numfmt", "--to=iec"], shell=False, stdin=PIPE, stdout=PIPE, encoding='utf8')
				(numfmt_stdout, _) = numfmt.communicate(input="%s\n%s\n%s\n" % (memory_used, memory_limit, memory_max))
				memory_used, memory_limit, memory_max = numfmt_stdout.splitlines()

			print("%s %s/%s %s %s/%s %s" % (container_name, memory_used, memory_limit, memory_limit_percent, memory_max, memory_limit, memory_max_percent))


if __name__ == "__main__":
	main()
