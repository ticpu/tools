#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# mysql-general-log-parser parses queries and puts them on one line or shows
# what table are used to in queries/verbs.
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
import argparse
import io
import re
import sys
import threading
import time
from collections import Counter
from queue import Queue
from typing import Iterator, Optional, List, Tuple

QUERY = re.compile(rb"([0-9]+)\sQuery\s(.*)")
NEW_QUERY = re.compile(rb"^(\t\t|[0-9]{6} [0-9]{2}:[0-9]{2}:[0-9]{2}\t)")
TABLE_REGEX = re.compile(rb"\s+FROM\s+([^ (]+)\W")
VERB_REGEX = re.compile(rb"^([A-Z]+)\W")
JOIN_REGEX = re.compile(rb"\s+JOIN\s+([^ (]+)\W")


def clean_line(line: bytes) -> bytes:
	return line\
		.strip()\
		.replace(b"  ", b" ")\
		.replace(b"\t", b" ")\
		.replace(b"\r", b"")


def get_query_line(line: bytes) -> Optional[Tuple[bytes, bytes]]:
	if line.find(b"Query", 8, 16) == -1:
		return

	result = QUERY.findall(line)

	if len(result) == 1:
		return result[0][0].strip(), result[0][1]


def get_log_lines(in_file: io.BytesIO) -> Iterator[List[bytes]]:
	do_print = False
	full_query_line = []

	for line in in_file:
		match = NEW_QUERY.match(line)
		if match:
			if do_print:
				do_print = False
				yield full_query_line

			query_line = get_query_line(line[match.end():])

			if query_line is not None:
				do_print = True
				full_query_line = list(query_line)
		elif do_print:
			full_query_line.append(line)


def clean_table_name(table_name: bytes) -> bytes:
	return table_name.strip().strip(b"`")


def cmd_print_queries(args):
	for f in args.files:
		lines = get_log_lines(f)

		for full_query_line in lines:
			sys.stdout.buffer.write(b" ".join(map(clean_line, full_query_line)) + b"\n")


def print_progress(current_file: Queue, total_files: int):
	current_file_no = 0

	for item in iter(current_file.get, None):
		current_file_no += 1
		f, full_size = item
		old_progress = 0

		while not f.closed:
			time.sleep(0.02)
			progress = f.tell() * 100 / full_size

			if old_progress != progress:
				old_progress = progress
				sys.stderr.write("\r(%d/%d) %0.2f%%" % (current_file_no, total_files, progress))
				if progress == 100:
					break

	sys.stderr.write("\r            \r")


def _init_multiprocessing(args):
	get_verb_tables_and_joins_from_line.add_join = args.joins
	get_verb_tables_and_joins_from_line.add_verb = args.verb


def get_verb_tables_and_joins_from_line(full_query_line: List[bytes]):
	try:
		line = b" ".join(map(clean_line, full_query_line[1:]))
		table_match = TABLE_REGEX.finditer(line)
		first_table = next(table_match)
	except StopIteration:
		return

	add_join = get_verb_tables_and_joins_from_line.add_join
	add_verb = get_verb_tables_and_joins_from_line.add_verb
	joins = set()
	query_table_name = ""
	out = []

	if add_verb:
		verb_match = next(VERB_REGEX.finditer(line))
		out.append(verb_match.group(1))
		if out[-1] == "SET":
			raise AssertionError("Error parsing log file, SET detected as verb. Query: %s" % full_query_line)

	out.append(clean_table_name(first_table.group(1)))

	if add_join:
		joins.update((clean_table_name(x.group(1)) for x in table_match))

	if add_join:
		join_match = JOIN_REGEX.findall(line)
		joins.update(map(clean_table_name, join_match))
		joins.discard(query_table_name)
		out.extend(joins)

	return b" ".join(out)


def get_verb_tables_and_joins(args) -> Iterator[bytes]:
	current_file = Queue()
	progress_thread = None

	if args.progress and args.files[0] != sys.stdin:
		progress_thread = threading.Thread(
			name="progress",
			target=print_progress,
			args=(current_file, len(args.files)),
			daemon=True,
		)
		progress_thread.start()

	for f in args.files:
		if progress_thread:
			try:
				f.seek(0, io.SEEK_END)
				current_file.put((f, f.tell()))
				f.seek(0, io.SEEK_SET)
			except io.UnsupportedOperation:
				current_file.put(None)

		full_query_line = get_log_lines(f)

		if args.single_process:
			_init_multiprocessing(args)
			lines_iter = map(get_verb_tables_and_joins_from_line, full_query_line)
			yield from filter(None, lines_iter)
		else:
			import multiprocessing
			p = multiprocessing.Pool(initializer=_init_multiprocessing, initargs=(args,))
			lines_iter = p.imap_unordered(
				get_verb_tables_and_joins_from_line,
				iterable=full_query_line,
				chunksize=args.chunk_size,
			)
			yield from filter(None, lines_iter)
			p.close()

	if progress_thread:
		current_file.put(None)
		progress_thread.join()


def cmd_print_tables(args):
	data = get_verb_tables_and_joins(args)

	if args.count:
		counts = Counter(data)

		for k, v in counts.items():
			print("%s\t%s" % (v, k.decode('utf8')))

	else:
		for line in data:
			sys.stdout.buffer.write(line + b"\n")


def command_line_parser():
	parser = argparse.ArgumentParser(description="MySQL general log parser")
	subparser = parser.add_subparsers()
	parser_queries = subparser.add_parser("queries", help="print queries line-by-line")
	parser_queries.add_argument("files", nargs="*", help="file(s) to parse or stdin")
	parser_queries.set_defaults(func=cmd_print_queries)
	parser_tables = subparser.add_parser("tables", help="print tables from queries")
	parser_tables.add_argument("-c", "--count", action="store_true",
		help="includes ordered tables from joins on same line")
	parser_tables.add_argument("-j", "--joins", action="store_true",
		help="includes ordered tables from joins on same line")
	parser_tables.add_argument("-v", "--verb", action="store_true",
		help="includes the SQL verb at the start of the line")
	parser_tables.add_argument("files", nargs="*", help="file(s) to parse or stdin")
	parser_tables.set_defaults(func=cmd_print_tables)
	parser.add_argument("-1", "--single-process", action="store_true", help="disable multiprocessing")
	parser.add_argument("-l", "--chunk-size", type=int, default=90000, help="number of lines per processes (advanced)")
	parser.add_argument("-p", "--progress", action="store_true", help="shows progress for some operations")
	args = parser.parse_args()

	if len(sys.argv) < 2:
		parser.print_help()
		sys.exit(2)

	if "files" in args and len(args.files) > 0:
		open_files = []

		for f in args.files:
			assert isinstance(f, str)
			opened = open(f, 'rb')
			open_files.append(opened)

		args.files.clear()
		args.files.extend(open_files)
	else:
		args.files = [sys.stdin.buffer]

	return args


def main():
	args = command_line_parser()
	args.func(args)


if __name__ == "__main__":

	try:
		main()
	except (BrokenPipeError, KeyboardInterrupt):
		sys.exit(0)
