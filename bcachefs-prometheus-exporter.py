import time
import argparse
import os
import re
from prometheus_client import start_http_server, Gauge
import psutil

class BcacheFSCollector:
    def __init__(self, uuid):
        self.uuid = uuid
        self.base_path = f"/sys/fs/bcachefs/{self.uuid}"
        self.metrics = {}
        self.io_counters = {}

    def initialize_metrics(self):
        labels = self.get_device_labels()
        bucket_types = ['free', 'sb', 'journal', 'btree', 'user', 'cached', 'parity', 'stripe', 'need_gc_gens', 'need_discard', 'unstriped', 'capacity']

        for bucket_type in bucket_types:
            self.metrics[bucket_type] = Gauge(f'bcachefs_{bucket_type}_buckets', f'Number of {bucket_type} buckets', ['device'])

        self.metrics['io_read_bytes'] = Gauge('bcachefs_io_read_bytes', 'Bytes read from device', ['device'])
        self.metrics['io_write_bytes'] = Gauge('bcachefs_io_write_bytes', 'Bytes written to device', ['device'])

        # Initialize btree metrics
        accounting_file = f"{self.base_path}/internal/accounting"
        if os.path.exists(accounting_file):
            with open(accounting_file, 'r') as f:
                for line in f:
                    match = re.match(r'^btree btree=(\w+): (\d+)$', line)
                    if match and match.group(1) != '(unknown)':
                        metric_name = f'bcachefs_accounting_btree_{match.group(1)}'
                        self.metrics[metric_name] = Gauge(metric_name, f'Btree size for {match.group(1)}')

    def get_device_labels(self):
        labels = {}
        for dev_dir in os.listdir(self.base_path):
            if dev_dir.startswith('dev-'):
                with open(f"{self.base_path}/{dev_dir}/label", 'r') as f:
                    label = f.read().strip()
                labels[dev_dir] = label
        return labels

    def get_block_devices(self):
        block_devices = {}
        for dev_dir in os.listdir(self.base_path):
            if dev_dir.startswith('dev-'):
                block_device = os.path.basename(os.readlink(f"{self.base_path}/{dev_dir}/block"))
                block_devices[dev_dir] = block_device
        return block_devices

    def collect_metrics(self):
        labels = self.get_device_labels()
        block_devices = self.get_block_devices()

        for dev_dir, label in labels.items():
            alloc_debug_path = f"{self.base_path}/{dev_dir}/alloc_debug"
            with open(alloc_debug_path, 'r') as f:
                lines = f.readlines()
                for line in lines:
                    parts = line.split()
                    if len(parts) >= 2 and parts[0] in self.metrics:
                        self.metrics[parts[0]].labels(device=label).set(int(parts[1]))

            # Collect I/O statistics
            block_device = block_devices[dev_dir]
            io_counter = psutil.disk_io_counters(perdisk=True).get(block_device)
            if io_counter:
                if dev_dir in self.io_counters:
                    prev_counter = self.io_counters[dev_dir]
                    read_bytes = io_counter.read_bytes - prev_counter.read_bytes
                    write_bytes = io_counter.write_bytes - prev_counter.write_bytes
                    self.metrics['io_read_bytes'].labels(device=label).set(read_bytes)
                    self.metrics['io_write_bytes'].labels(device=label).set(write_bytes)
                self.io_counters[dev_dir] = io_counter

        # Collect btree metrics
        accounting_file = f"{self.base_path}/internal/accounting"
        if os.path.exists(accounting_file):
            with open(accounting_file, 'r') as f:
                for line in f:
                    match = re.match(r'^btree btree=(\w+): (\d+)$', line)
                    if match and match.group(1) != '(unknown)':
                        metric_name = f'bcachefs_accounting_btree_{match.group(1)}'
                        self.metrics[metric_name].set(int(match.group(2)))

def main():
    parser = argparse.ArgumentParser(description='BcacheFS Prometheus Exporter')
    parser.add_argument('uuid', help='UUID of the BcacheFS filesystem')
    parser.add_argument('--port', type=int, default=8000, help='Port to expose metrics on')
    args = parser.parse_args()

    collector = BcacheFSCollector(args.uuid)
    collector.initialize_metrics()

    start_http_server(args.port)
    print(f"Serving metrics on :{args.port}")

    while True:
        collector.collect_metrics()
        time.sleep(1)

if __name__ == '__main__':
    main()
