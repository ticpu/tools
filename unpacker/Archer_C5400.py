#!/usr/bin/python3
import sys
import subprocess
import zlib

p = subprocess.Popen(
	[ 'openssl', 'aes-256-cbc', '-d', '-K', '2EB38F7EC41D4B8E1422805BCD5F740BC3B95BE163E39D67579EB344427F7836', '-iv', '360028C9064242F81074F4C127D299F6' ],
	stdout=subprocess.PIPE,
	shell=False,
)
stdout, stderr = p.communicate()
sys.stdout.buffer.write(zlib.decompress(stdout))
