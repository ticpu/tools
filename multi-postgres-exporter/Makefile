#!/usr/bin/make -f

POSTGRES_EXPORTER_VERSION ?= 0.12.0-rc.0
POSTGRES_EXPORTER_FOLDER = postgres_exporter-$(POSTGRES_EXPORTER_VERSION).linux-amd64
DESTDIR ?= /usr/local

postgres_exporter_instance:
	wget -N https://github.com/prometheus-community/postgres_exporter/releases/download/v$(POSTGRES_EXPORTER_VERSION)/$(POSTGRES_EXPORTER_FOLDER).tar.gz
	tar --strip-components=1 -xzf $(POSTGRES_EXPORTER_FOLDER).tar.gz $(POSTGRES_EXPORTER_FOLDER)/postgres_exporter

install:
	install -D -m0755 postgres_exporter $(DESTDIR)/usr/bin/postgres-exporter-instance
	install -D -m0644 multi-postgres-exporter.default $(DESTDIR)/etc/default/multi-postgres-exporter
	install -D -m0755 -t $(DESTDIR)/usr/bin/ multi-postgres-exporter.py
	install -D -m0644 -t $(DESTDIR)/lib/systemd/system multi-postgres-exporter.service

all:
	postgres_exporter_instance
