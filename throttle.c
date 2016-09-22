/*
 * throttle.c allows to throttle a program by sending SIGSTOP/SIGCONT
 * at a specified interval, this program is meant to complement cpulimit
 * which can only limit program using CPU, a GPU program can't be limited.
 *
 * Compile using gcc -Wall -DSYSLOG -DSYSTEMD -o throttle throttle.c -lsystemd
 *
 * Example unit file:
 *
 * [Service]
 * Type=notify
 * WatchdogSec=15
 * ExecStart=/bin/sh -c "exec throttle -d 0.84 -s 100000 `pidof hungry_app`"
 *
 * Copyright (C) 2015 Jérôme Poulin <jeromepoulin@gmail.com>
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 *
 */
#include <signal.h>
#include <stdarg.h>
#include <stdlib.h>
#include <stdio.h>
#include <sys/types.h>
#include <fcntl.h>
#include <unistd.h>
#ifdef SYSLOG
#include <syslog.h>
#endif
#ifdef SYSTEMD
#include <systemd/sd-daemon.h>
#endif

pid_t pid = 0;
char quiet = 1;

void mlog(const char *format, ...)
{
	if (quiet)
		return;

	va_list ap;

	va_start(ap, format);
#ifdef SYSLOG
	vsyslog(LOG_DEBUG, format, ap);
#else
	vfprintf(stderr, format, ap);
#endif
	va_end(ap);
}

void end(int signum)
{
#ifdef SYSLOG
	syslog(LOG_INFO, "Sending last SIGCONT.");
#endif
#ifdef SYSTEMD
	sd_notify(0, "STOPPING=1\nSTATUS=Sending last SIGCONT.");
#endif
	mlog("Last SIGCONT.\n");
	kill(pid, SIGCONT);
	if (signum == SIGSEGV)
		exit(SIGSEGV);
	else
		exit(EXIT_SUCCESS);
}

int main(int argc, char **argv)
{
	long sleep_time_us = 10000;
	int opt;
	float duty_cycle = 0.5;
	long sleep_on = 0;
	long sleep_off = 0;
	char foreground = 0;
#ifdef SYSTEMD
	uint64_t watchdog_usec;
	uint32_t watchdog_counter;
	uint32_t watchdog_max;

	if (getenv("NOTIFY_SOCKET") != NULL)
		foreground = 1;

	watchdog_counter = sd_watchdog_enabled(0, &watchdog_usec);
	if (watchdog_counter <= 0)
		watchdog_usec = 0;
#endif

	while ((opt = getopt(argc, argv, "fvd:s:")) != -1) {
		switch (opt) {
		case 'f':
			foreground = 1;
			break;
		case 'v':
			quiet = 0;
			break;
		case 'd':
			duty_cycle = atof(optarg);
			break;
		case 's':
			sleep_time_us = atol(optarg);
			break;
		default:
			fprintf(stderr, "Usage: %s [-fv] [-d duty_cycle (float)] [-s sleep_time_µs] PID\n",
					argv[0]);
			exit(EXIT_FAILURE);
		}
	}

	if (optind >= argc) {
		fprintf(stderr, "Expected PID after arguments.\n");
		exit(EXIT_FAILURE);
	}

	pid = atoi(argv[optind]);

	mlog("PID: %d, Duty: %0.2f\n", pid, duty_cycle);
	signal(SIGINT, end);
	signal(SIGTERM, end);
	signal(SIGHUP, end);
	signal(SIGSEGV, end);

	sleep_on = sleep_time_us * duty_cycle;
	sleep_off = sleep_time_us - sleep_on;

#ifdef SYSTEMD
	if (watchdog_usec > 0) {
		watchdog_max = watchdog_usec / (sleep_on + sleep_off) / 2;
	} else {
		watchdog_max = 0;
	}
	watchdog_counter = 0;
	sd_notifyf(0, "READY=1\nSTATUS=Throttling process %d.", pid);
#endif

	if (foreground == 0) {
		close(0);
		open("/dev/null", 0);
		daemon(0, 1);
	}

#ifdef SYSLOG
	syslog(LOG_INFO, "Throttling process %d.", pid);
#endif

	for (;;) {
#ifdef SYSTEMD
		if (watchdog_max > 0) {
			watchdog_counter++;
			if (watchdog_counter > watchdog_max) {
				watchdog_counter = 0;
				sd_notify(0, "WATCHDOG=1");
			}
		}
#endif
		usleep(sleep_on);
		mlog("SIGSTOP\n");
		kill(pid, SIGSTOP);
		usleep(sleep_off);
		mlog("SIGCONT\n");
		kill(pid, SIGCONT);
	}

	exit(EXIT_SUCCESS);
}
