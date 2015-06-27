from wsgi import webapp
import gevent
from gevent.pywsgi import WSGIServer

application = webapp.get_application()
serverConf = application.config.get("server")

def gevent_start_server():
  address = serverConf.get("interface", "0.0.0.0")
  port = int(serverConf.get("port", 7009))
  ssl_cert = serverConf.get("ssl_certificate")
  ssl_key = serverConf.get("ssl_private_key")
  if int(serverConf.get("access_log",1)):
    log = "default"
  else:
    log = None

  print "ssl: %s, %s" % (ssl_key, ssl_cert)

  WSGIServer((address,port), application, log=log, keyfile=ssl_key, certfile=ssl_cert).serve_forever()
