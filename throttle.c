#include <signal.h>
#include <stdarg.h>
#include <stdlib.h>
#include <stdio.h>
#include <sys/types.h>
#include <unistd.h>

pid_t pid = 0;
char quiet = 1;

void mlog(const char *format, ...)
{
	if (quiet)
		return;

	va_list ap;

	va_start(ap, format);
	vfprintf(stderr, format, ap);
	va_end(ap);
}

void end(int signum)
{
	mlog("Last SIGCONT.\n");
	kill(pid, SIGCONT);
	exit(EXIT_SUCCESS);
}

int main(int argc, char **argv)
{
	long sleep_time_us = 10000;
	int opt;
	float duty_cycle = 0.5;
	long sleep_on = 0;
	long sleep_off = 0;

	while ((opt = getopt(argc, argv, "vd:s:")) != -1) {
		switch (opt) {
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
			fprintf(stderr, "Usage: %s [-d duty_cycle (float)] [-s sleep_time_µs] PID\n",
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

	sleep_on = sleep_time_us * duty_cycle;
	sleep_off = sleep_time_us - sleep_on;

	for (;;) {
		usleep(sleep_on);
		mlog("SIGSTOP\n");
		kill(pid, SIGSTOP);
		usleep(sleep_off);
		mlog("SIGCONT\n");
		kill(pid, SIGCONT);
	}

	exit(EXIT_SUCCESS);
}
