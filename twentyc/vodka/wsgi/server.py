import webapp
application = webapp.get_application(dummy=True)
serverConf = application.config.get("server")
serverType = serverConf.get("wsgiserver", "twisted")

if serverType == "twisted" or serverType == "twistd":
  from twisted_server import *
elif serverType == "uwsgi":
  from uwsgi_server import *
elif serverType == "gevent":
  from gevent_server import *
elif serverType == "eventlet":
  from eventlet_server import *
else:
  raise Exception("Unknown / Unsupported WSGI server type: %s" % serverType)

print "Using WSGI Server: %s" % serverType 


