/*
 * Tool to use in keyboard shortcut to set the volume of either a default sink
 * or the headset you have plugged in without having to switch the default
 * sink each time.
 *
 * Make sure to apt install libpulse-dev to compile.
 *
 * Debug with:
 *   gcc -Wall -g -o volume-logitech volume-logitech.c -lpulse -DSYSLOG
 *
 * Compile with:
 *   gcc -O3 -o volume-logitech volume-logitech.c -lpulse
 *
 */
#include <pulse/pulseaudio.h>
#include <stdio.h>
#include <string.h>
#ifdef SYSLOG
#include <syslog.h>
#else
#define syslog(fmt, args...) \
do { } while (0)
#endif

#define PROG "logitech-volume"
#define VOLUME_INCREMENT_DEFAULT 500
#define VOLUME_INCREMENT_HEADSET 100
#define SINK_NAME_DEFAULT "alsa_output.pci-0000_00_1f.3.analog-stereo"
#define SINK_NAME_HEADSET "Logitech_G933"

#define VOLUME_UP 1
#define VOLUME_DOWN -1

static pa_mainloop *m;
static int8_t volume_direction;

void set_volume_cb(pa_context *c, int success, void *userdata)
{
	if (success)
	{
		syslog(LOG_INFO, "Volume set at %u.", pa_cvolume_max((pa_cvolume*)userdata));
		pa_mainloop_quit(m, 0);
	}
	else
	{
		syslog(LOG_ERR, "Failed to set volume.");
		pa_mainloop_quit(m, 1);
	}
}

void set_volume(pa_context *c, uint32_t sink_index, pa_cvolume *volume, uint32_t increment)
{
	pa_operation *op;
	pa_volume_t current_volume = pa_cvolume_max(volume);

	syslog(LOG_DEBUG, "Current volume at %u.", current_volume);
	current_volume = current_volume + (increment * volume_direction);
	pa_cvolume_set(volume, volume->channels, current_volume);
	op = pa_context_set_sink_volume_by_index(
		c, sink_index, volume, set_volume_cb, volume);
	pa_operation_unref(op);
}

void sink_list_cb(pa_context *c, const pa_sink_info *i, int eol, void *userdata)
{
	static uint32_t sink_default;
	static uint32_t sink_headset;
	static pa_cvolume sink_default_volume;
	static pa_cvolume sink_headset_volume;
	static uint8_t done = 0;

	if (done)
		return;

	if (eol)
	{
		if (sink_default)
		{
			syslog(LOG_INFO, "Setting volume for default sink.");
			done = 1;
			set_volume(c, sink_default, &sink_default_volume, VOLUME_INCREMENT_DEFAULT);
		}
		else
		{
			syslog(LOG_INFO, "End of listing, quitting application.");
			pa_mainloop_quit(m, 1);
		}
	}
	else if (strstr(i->name, SINK_NAME_DEFAULT))
	{
		syslog(LOG_DEBUG, "found default: #%u %s", i->index, i->name);
		sink_default = i->index;
		sink_default_volume = i->volume;
	}
	else if (strstr(i->name, SINK_NAME_HEADSET))
	{
		syslog(LOG_DEBUG, "found headset: #%u %s", i->index, i->name);
		sink_headset = i->index;
		sink_headset_volume = i->volume;
	}
	else
		syslog(LOG_DEBUG, "sink #%u: %s", i->index, i->name);

	if (sink_headset)
	{
		syslog(LOG_INFO, "Setting volume for headset sink.");
		done = 1;
		set_volume(c, sink_headset, &sink_headset_volume, VOLUME_INCREMENT_HEADSET);
	}
}

void connected_cb(pa_context *c, void *userdata)
{
	pa_context_state_t cs;
	pa_operation *op;

	cs = pa_context_get_state(c);

	if (cs == PA_CONTEXT_READY)
	{
		syslog(LOG_INFO, "Connected to pulseaudio.");
		op = pa_context_get_sink_info_list(c, sink_list_cb, NULL);
		pa_operation_unref(op);
	}
	else if (cs == PA_CONTEXT_FAILED || cs == PA_CONTEXT_TERMINATED)
	{
		syslog(LOG_CRIT, "Failed to connect to pulseaudio, bailing out.");
		pa_mainloop_quit(m, 1);
	}
	else
		syslog(LOG_INFO, "Connecting...");
}

int main(int argc, char *argv[])
{
#ifdef SYSLOG
	openlog(PROG, LOG_PERROR, LOG_USER);
#endif

	pa_context *c;
	int retval;

	if (argc != 2) {
		fprintf(stderr, "Usage: %s up|down\n", argv[0]);
		return 2;
	} else if (strstr(argv[1], "up")) {
		volume_direction = VOLUME_UP;
	} else if (strstr(argv[1], "down")) {
		volume_direction = VOLUME_DOWN;
	} else {
		fprintf(stderr, "Volume direction must be 'up' or 'down'.\n");
		return 1;
	}

	m = pa_mainloop_new();
	c = pa_context_new(pa_mainloop_get_api(m), "logitech-volume");
	pa_context_set_state_callback(c, connected_cb, NULL);
	pa_context_connect(c, NULL, 0, NULL);
	pa_mainloop_run(m, &retval);
	pa_context_unref(c);
	pa_mainloop_free(m);

#ifdef SYSLOG
	closelog();
#endif

	return retval;
}
