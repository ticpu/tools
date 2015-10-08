#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# testshell.py allows to create a shell in a running program to modify
# its internals.
#
# Usage:
# testshell.start_shell(bind_ip, port, globals())
#
# Copyright (C) 2015 Jérôme Poulin <jeromepoulin@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
from socketserver import BaseRequestHandler, ThreadingMixIn, UDPServer
import threading


class ShellServer(ThreadingMixIn, UDPServer):
	pass


class ShellHandler(BaseRequestHandler):
	client_globals = None
	clients_locals = dict()

	def handle(self):
		# data = str(self.request.recv(1024), 'utf8')
		# self.request.sendall(bytes(repr(ret), 'utf8'))
		data, socket = self.request
		client_name = repr(self.client_address)

		if client_name in ShellHandler.clients_locals:
			c_threads, c_locals = ShellHandler.clients_locals[client_name]

			if data.strip() == b'.':
				del ShellHandler.clients_locals[client_name]
				socket.sendto(b"<RESET COMPLETE>", self.client_address)
		else:
			c_threads, c_locals = set(), dict()
			ShellHandler.clients_locals[client_name] = (c_threads, c_locals)

		c_threads.add(threading.current_thread())
		if len(data.strip()) > 0:

			c_globals = ShellHandler.client_globals
			c_locals.update(locals())

			args = (str(data, 'utf8'), globals(), c_locals)
			try:
				try:
					ret = eval(*args)
				except SyntaxError:
					exec(*args)
					ret = "OK"
			except Exception as e:
				ret = repr(e)

			if type(ret) != str:
				ret = "%s %s" % (type(ret), repr(ret))

			socket.sendto(bytes(ret, 'utf8'), self.client_address)

		running = 0
		job = "\nCurrently running threads:\n"
		for t in c_threads.copy():
			if t.is_alive():
				job += repr(t) + "\n"
				running += 1
			else:
				c_threads.discard(t)

		if running > 2:
			socket.sendto(bytes(job, 'utf8'), self.client_address)

		socket.sendto(b"\n>>> ", self.client_address)


def start_shell(address, port, imported_globals=None):
	ShellHandler.client_globals = imported_globals
	server = ShellServer((address, port), ShellHandler)
	server_thread = threading.Thread(target=server.serve_forever)
	server_thread.daemon = True
	server_thread.start()
	server.server_thread = server_thread
	return server

if __name__ == "__main__":
	server = start_shell('', 12123)
	ip, port = server.server_address
	server_thread = server.server_thread
	print("Server loop running in thread:", server_thread.name)
