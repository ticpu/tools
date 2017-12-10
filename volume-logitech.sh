#!/bin/sh

LIST=`/usr/bin/pactl list short`
INCREMENT=5
SINK=alsa_output.pci-0000_00_1f.3.analog-stereo

if [ "$LIST" != "${LIST#*Logitech_G933*}" ]
then
	INCREMENT=1
	SINK=alsa_output.usb-Logitech_Logitech_G933_Gaming_Wireless_Headset-00.analog-stereo
fi

case $1 in
	up) exec /usr/bin/pactl set-sink-volume $SINK +${INCREMENT}%;;
	down) exec /usr/bin/pactl set-sink-volume $SINK -${INCREMENT}%;;
esac
