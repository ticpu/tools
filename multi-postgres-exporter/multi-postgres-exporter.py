#!/usr/bin/python3
import argparse
import logging
import os
import socket
import subprocess
import sys
import time
from typing import Optional

import requests
from flask import Flask, stream_with_context, Response
from prometheus_client.parser import text_string_to_metric_families

app = Flask(__name__)
log = logging.getLogger("multi-postgres-exporter")
_CLUSTERS = None


def extract_prometheus_postgres_metrics(outputs):
	metric_dict = {}

	for output in outputs:
		if output is None:
			continue

		cluster = None

		for metric_family in text_string_to_metric_families(output):
			if metric_family.name.startswith("pg_") and metric_family.type != "unknown":
				if metric_family.name not in metric_dict:
					metric_dict[metric_family.name] = metric_family
				else:
					metric_dict[metric_family.name].samples += metric_family.samples
				if cluster is None and len(metric_family.samples) > 0:
					labels = metric_family.samples[0].labels
					if "server" in labels:
						cluster = labels["server"]

		if cluster is None:
			raise ValueError("No server defined in metrics.")

		for metric_family in metric_dict.values():
			for sample in metric_family.samples:
				if "server" not in sample.labels:
					sample.labels["server"] = cluster

	return metric_dict.values()


def generate_prometheus_output_from_extracted_metrics(metrics: iter):
	for metric_family in metrics:
		yield "# HELP %s %s\n" % (metric_family.name, metric_family.documentation.replace('\n', '\\n'))
		yield "# TYPE %s %s\n" % (metric_family.name, metric_family.type)
		for sample in metric_family.samples:
			yield "%s{%s} %s\n" % (
				sample.name,
				",".join(['%s="%s"' % (k, v) for k, v in sample.labels.items()]),
				sample.value,
			)


class PostgresCluster(object):
	@classmethod
	def get_all_clusters(cls, sockets_path: str, exporter_binary, exporter_args, exporter_bind_address):
		for top_dir, _, filenames in os.walk(sockets_path):
			for filename in filenames:
				if filename.startswith('.s.PGSQL.') and not filename.endswith('.lock'):
					yield cls(top_dir, filename, exporter_binary, exporter_args, exporter_bind_address)

	def _spawn_new_exporter_process(self):
		uri = f"postgres@:{self.port}/postgres?host={self.unix_socket}"
		env = os.environ.copy()
		env["DATA_SOURCE_URI"] = uri
		args = [
			f"--web.listen-address={self.exporter_bind_address}:{self.exporter_port}",
			"--auto-discover-databases",
		]
		log.info("launching a new exporter instance for [%s] command line [%s] ", uri, self.exporter_args + args)
		process = subprocess.Popen(
			[self.exporter_binary] + self.exporter_args + args,
			executable=self.exporter_binary,
			shell=False,
			env=env,
			stdin=subprocess.DEVNULL,
		)
		return process

	def run_postgres_exporter(self) -> subprocess.Popen:
		if self._freeswitch_exporter is None or \
				(isinstance(self._freeswitch_exporter, subprocess.Popen) and
					self._freeswitch_exporter.returncode is not None):
			self._freeswitch_exporter = self._spawn_new_exporter_process()
		return self._freeswitch_exporter

	@staticmethod
	def _get_exporter_port(exporter_bind_address) -> int:
		exporter_socket = socket.socket()
		exporter_socket.bind((exporter_bind_address, 0))
		port = int(exporter_socket.getsockname()[1])
		exporter_socket.close()
		return port

	def get_prometheus_metrics(self) -> Optional[str]:
		self.run_postgres_exporter()
		# noinspection HttpUrlsUsage
		url = f"http://{self.exporter_bind_address}:{self.exporter_port}/metrics"

		try:
			data = requests.get(url)
		except requests.exceptions.ConnectionError:
			log.error("couldn't connect to %s", url)
			if self._freeswitch_exporter is not None:
				logging.info("killing exporter instance, return code was %s", self._freeswitch_exporter.returncode)
				self._freeswitch_exporter.kill()
				self.run_postgres_exporter()
		else:
			return data.text

	def __init__(
			self, directory: str, filename: str,
			exporter_binary: str, exporter_args: list, exporter_bind_address: str):
		self.unix_socket = os.path.abspath(directory)
		self.port = int(filename.rsplit('.', 1)[1])
		self.exporter_bind_address = exporter_bind_address
		self.exporter_binary = exporter_binary
		self.exporter_args = exporter_args
		self.exporter_port = self._get_exporter_port(exporter_bind_address)
		self._freeswitch_exporter = None

	def __repr__(self):
		return "<%s host=%s port=%d>" % (self.__class__.__name__, self.unix_socket, self.port)


@app.route("/metrics")
def get_all_clusters_metrics():
	assert isinstance(_CLUSTERS, list) and len(_CLUSTERS) > 0
	metrics = extract_prometheus_postgres_metrics((x.get_prometheus_metrics() for x in _CLUSTERS))
	output_generator = generate_prometheus_output_from_extracted_metrics(metrics)
	return Response(stream_with_context(output_generator), content_type='text/plain; charset="UTF-8"')


def main():
	global _CLUSTERS
	parser = argparse.ArgumentParser()
	parser.add_argument('--exporter-path', default="postgres_exporter", help="Path or name for postgres_exporter")
	parser.add_argument('--socket-path', default="/run/postgresql", help="Path to PostgresSQL sockets")
	parser.add_argument(
		'--exporter-bind-address',
		default="127.1.1.1",
		help="Address to bind the exporter's internal socket to.",
	)
	args, unparsed = parser.parse_known_args()
	_CLUSTERS = list(
		PostgresCluster.get_all_clusters(
			args.socket_path,
			args.exporter_path,
			unparsed,
			args.exporter_bind_address
		)
	)

	if len(_CLUSTERS) < 1:
		log.fatal("no cluster defined, exiting")
		sys.exit(6)

	for cluster in _CLUSTERS:
		cluster.run_postgres_exporter()

	time.sleep(2)

	if not sys.flags.inspect:
		app.run(host="0.0.0.0", port=8089)


if __name__ == "__main__":
	logging.basicConfig(level=logging.WARNING)
	log.setLevel(logging.DEBUG)
	main()
