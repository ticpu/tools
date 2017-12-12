/*
 * Tool to use in keyboard shortcut to set the volume of either a default sink
 * or the headset you have plugged in without having to switch the default
 * sink each time.
 *
 * Make sure to apt install libpulse-dev to compile.
 *
 * Debug with:
 *   gcc -Wall -g -o volume-logitech volume-logitech.c -lpulse -lsystemd -DSYSLOG
 *
 * Compile with:
 *   gcc -O3 -o volume-logitech volume-logitech.c -lpulse -lsystemd
 *
 */
#include <pulse/pulseaudio.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#ifdef SYSLOG
#include <syslog.h>
#else
#define syslog(fmt, args...) \
do { } while (0)
#endif
#include <systemd/sd-daemon.h>

#define PROG "logitech-volume-daemon"
#define VOLUME_INCREMENT 200
#define VOLUME_UP 0x01
#define VOLUME_DOWN 0x02
#define SINK_NAME_HEADSET "Logitech_G933"

static pthread_mutex_t volume_set_mutex = PTHREAD_MUTEX_INITIALIZER;

void set_volume_cb(pa_context *c, int success, void *userdata)
{
	pa_volume_t *new_volume = userdata;

	if (success && new_volume)
	{
		syslog(LOG_INFO, "Volume set at %u.", *new_volume);
		sd_notifyf(0, "STATUS=Volume at %u.", *new_volume);
	}
	else
	{
		syslog(LOG_ERR, "Failed to set volume.");
		sd_notify(0, "STATUS=Failed to set volume.");
	}

	pthread_mutex_unlock(&volume_set_mutex);
}

void set_volume(pa_context *c, uint32_t sink_index, pa_cvolume *volume, uint32_t increment, uint8_t direction)
{
	pa_operation *op;
	static pa_volume_t current_volume;
	int8_t multiplicator;

	switch (direction) {
	case VOLUME_UP:
		multiplicator = 1;
		break;
	case VOLUME_DOWN:
		multiplicator = -1;
		break;
	default:
		syslog(LOG_CRIT, "Invalid volume direction %u.", direction);
		abort();
	}

	current_volume = pa_cvolume_max(volume);
	syslog(LOG_DEBUG, "Current volume at %u.", current_volume);
	current_volume = current_volume + (increment * multiplicator);
	pa_cvolume_set(volume, volume->channels, current_volume);
	op = pa_context_set_sink_volume_by_index(
		c, sink_index, volume, set_volume_cb, &current_volume);
	pa_operation_unref(op);
}

void sink_list_cb(pa_context *c, const pa_sink_info *i, int eol, void *userdata)
{
	pa_cvolume sink_headset_volume;

	if (eol)
		return;

	if (strstr(i->name, SINK_NAME_HEADSET))
	{
		syslog(LOG_DEBUG, "found headset: #%u %s", i->index, i->name);
		sink_headset_volume = i->volume;
		set_volume(c, i->index, &sink_headset_volume, VOLUME_INCREMENT, *(uint8_t*)userdata);
	}
	else
		syslog(LOG_DEBUG, "sink #%u: %s", i->index, i->name);
}

void connected_cb(pa_context *c, void *userdata)
{
	pa_context_state_t cs;

	cs = pa_context_get_state(c);

	if (cs == PA_CONTEXT_READY)
	{
		syslog(LOG_INFO, "Connected to pulseaudio.");
	}
	else if (cs == PA_CONTEXT_FAILED || cs == PA_CONTEXT_TERMINATED)
	{
		syslog(LOG_CRIT, "Failed to connect to pulseaudio, bailing out.");
		exit(EXIT_FAILURE);
	}
	else
		syslog(LOG_INFO, "Connecting...");
}

int start_daemon(const char *hidraw_path)
{
	pa_context *c;
	pa_threaded_mainloop *m;
	pa_operation *op;
	pa_operation_state_t opstate;
	FILE *hidraw;
	char packet[8];
	size_t packet_size;
	uint8_t direction;

	hidraw = fopen(hidraw_path, "rb");
	if (!hidraw) {
		syslog(LOG_CRIT, "Unable to open %s: %m.", hidraw_path);
		return EXIT_FAILURE;		
	}

	pthread_mutex_init(&volume_set_mutex, NULL);
	m = pa_threaded_mainloop_new();
	c = pa_context_new(pa_threaded_mainloop_get_api(m), PROG);
	pa_context_set_state_callback(c, connected_cb, NULL);
	pa_context_connect(c, NULL, 0, NULL);
	pa_threaded_mainloop_start(m);

	sd_notify(0, "READY=1");
	
	while (1)
	{

		/* Get the action */
		do packet_size = fread(packet, 5, 1, hidraw);
		while (!feof(hidraw) && packet[1] == 0x00);

		/* Stream had ended */
		if (feof(hidraw) || packet_size == 0)
			break;

		/* Getting direction */
		direction = packet[1];

		/* Ask PulseAudio to find card and adjust volume. */
		pthread_mutex_lock(&volume_set_mutex);
		pa_threaded_mainloop_lock(m);
		op = pa_context_get_sink_info_list(c, sink_list_cb, &direction);
		pa_threaded_mainloop_unlock(m);

		/* See how it went */
		pthread_mutex_lock(&volume_set_mutex);
		pa_threaded_mainloop_lock(m);
		pthread_mutex_unlock(&volume_set_mutex);
		opstate = pa_operation_get_state(op);
		pa_operation_unref(op);
		pa_threaded_mainloop_unlock(m);

		/* Report it */
		if (opstate == PA_OPERATION_DONE)
			syslog(LOG_DEBUG, "Operation completed.");
		else
			syslog(LOG_ERR, "Operation failed.");

	}

	if (hidraw)
	{
		fclose(hidraw);
		hidraw = NULL;
	}

	pa_context_unref(c);
	pa_threaded_mainloop_stop(m);
	pa_threaded_mainloop_free(m);
	pthread_mutex_destroy(&volume_set_mutex);


	return 0;
}

int main(int argc, char *argv[])
{
#ifdef SYSLOG
	openlog(PROG, LOG_PERROR, LOG_USER);
#endif

	int ret;

	if (argc != 2) {
		fprintf(stderr, "Usage: %s /dev/hidrawN\n", argv[0]);
		return 2;
	} else if (strstr(argv[1], "/dev/")) {
		ret = start_daemon(argv[1]);
	} else {
		fprintf(stderr, "This doesn't look like a valid device.\n");
		return 1;
	}

#ifdef SYSLOG
	closelog();
#endif

	return ret;
}
