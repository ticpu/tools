#!/usr/bin/env python3
import argparse
import io
import re
import sys
import threading
import time
from collections import Counter
from queue import Queue
from typing import Iterator

QUERY = re.compile(rb"\s([0-9]+)\sQuery\s(.*)")


def clean_line(line: bytes):
	return line\
		.replace(b"  ", b" ")\
		.replace(b"\t", b" ")\
		.replace(b"\r", b"")\
		.strip()


def get_query_line(line: bytes):
	result = QUERY.findall(line)

	if len(result) == 1:
		return b"%s %s" % (result[0][0].strip(), clean_line(result[0][1]))


def get_log_lines(in_file: io.BytesIO) -> Iterator[bytes]:
	do_print = False
	cleaned_line = str()

	for line in in_file:
		if line.startswith(b"\t\t"):
			if do_print:
				do_print = False
				yield b"%s\n" % (cleaned_line,)

			cleaned_line = get_query_line(line)

			if cleaned_line is not None:
				do_print = True
		elif do_print:
			cleaned_line += b" %s" % (clean_line(line),)


def clean_table_name(table_name: bytes) -> bytes:
	return table_name.strip().strip(b"`")


def cmd_print_queries(args):
	for f in args.files:
		lines = get_log_lines(f)

		for line in lines:
			sys.stdout.buffer.write(line)


def print_progress(current_file: Queue, total_files: int):
	current_file_no = 0

	while True:
		item = current_file.get()
		current_file_no += 1

		if item is None:
			break

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


def get_verb_tables_and_joins(args) -> Iterator[bytes]:
	verb_regex = re.compile(rb"\W([A-Z]+)\W")
	table_regex = re.compile(rb"\s+FROM\s+([^ (]+)\W")
	join_regex = re.compile(rb"\s+JOIN\s+([^ (]+)\W")
	current_file = Queue()
	progress_thread = None
	joins = set()

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
			f.seek(0, io.SEEK_END)
			current_file.put((f, f.tell()))
			f.seek(0, io.SEEK_SET)

		lines = get_log_lines(f)

		for line in lines:
			table_match = table_regex.findall(line)

			if len(table_match) == 0:
				continue

			query_table_name = ""
			out = b""

			for i, table_name in enumerate(table_match):
				if i == 0:
					if args.verb:
						verb_match = next(verb_regex.finditer(line))
						out += verb_match.group(1) + b" "
					query_table_name = clean_table_name(table_name)
					out += query_table_name
				elif args.joins:
					joins.add(clean_table_name(table_name))
				else:
					break

			if args.joins:
				join_match = join_regex.findall(line)

				for join in join_match:
					joins.add(clean_table_name(join))

			if joins:
				joins.discard(query_table_name)
				out += b" " + b" ".join(sorted(joins))
				joins.clear()

			yield out

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
