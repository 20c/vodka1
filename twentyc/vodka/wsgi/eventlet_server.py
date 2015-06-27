from wsgi import webapp

import eventlet
from eventlet import wsgi

application = webapp.get_application()
serverConf = application.config.get("server")

def eventlet_start_server():
  address = serverConf.get("interface", "0.0.0.0")
  port = int(serverConf.get("port", 7009))
  ssl_cert = serverConf.get("ssl_certificate")
  ssl_key = serverConf.get("ssl_private_key")
  if int(serverConf.get("access_log",1)):
    log = "default"
  else:
    log = None

  
  if not ssl_key or not ssl_cert:
    wsgi.server(
      eventlet.listen((address,port)), 
      application
    )
  else:
    print "ssl: %s, %s" % (ssl_key, ssl_cert)
    wsgi.server(
      eventlet.wrap_ssl(
        eventlet.listen((address, port)),
        certfile=ssl_cert,
        keyfile=ssl_key,
        server_side = True
      ),
      application
    )
