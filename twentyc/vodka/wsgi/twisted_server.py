"""
Import this file in your webapplication's source to run it via
twisted.web 
Example:

	Your webapplication is defined in myapp.py
	In myapp.py import twisted_server.py
	Then run it via: twistd -ny myapp.py
"""

from ConfigParser import ConfigParser
from twisted.web import server
from twisted.web.wsgi import WSGIResource
from twisted.python.threadpool import ThreadPool
from twisted.internet import reactor, ssl, threads
from twisted.application import service, strports

import webapp

application = webapp.get_application()

serverConf = application.config.get("server")

# Create and start a thread pool,
wsgiThreadPool = ThreadPool()
wsgiThreadPool.start()

# ensuring that it will be stopped when the reactor shuts down
reactor.addSystemEventTrigger('after', 'shutdown', wsgiThreadPool.stop)
reactor.addSystemEventTrigger('after', 'shutdown', webapp.stop_plugins)

# Create the WSGI resource
wsgiAppAsResource = WSGIResource(reactor, wsgiThreadPool, application)

# Hooks for twistd

privkey = serverConf.get("ssl_private_key")
cert = serverConf.get("ssl_certificate")
port = serverConf.get("port")
protocol = serverConf.get("protocol")
interface = serverConf.get("interface","0.0.0.0")

if protocol == "ssl": 
  svcName = "%s:%s:privateKey=%s:certKey=%s:interface=%s" % (protocol, port, privkey, cert, interface)
else:
  svcName = "%s:%s:interface=%s" % (protocol, port, interface)

webapp.start_plugins(application.config)

application = service.Application('Twisted.web.wsgi Web Server')
server = strports.service(svcName, server.Site(wsgiAppAsResource))
server.setServiceParent(application)

