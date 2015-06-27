import tornado.ioloop
import tornado.websocket
import uuid
import threading
import logging
import json

def setup_logging(logformat, config):
  if logging.getLogger("tornado").handlers:
    return

  log = logging.getLogger("tornado")

  from twentyc.syslogfix import UTFFixedSysLogHandler
  if int(config.get("server",{}).get("syslog",0)): 
    syslog_address = config.get("server", {}).get("syslog_address", "/dev/log") 
    syslog_facility = config.get("server", {}).get("syslog_facility", "LOG_LOCAL0") 
    hdl = UTFFixedSysLogHandler(address=syslog_address, facility=getattr(logging.handlers.SysLogHandler, syslog_facility)) 
    hdl.setFormatter(logging.Formatter(logformat)) 
  else: 
    hdl = logging.FileHandler("error.log") 
    hdl.setFormatter(logging.Formatter(logformat)) 
 
  log.addHandler(hdl) 

handlers = []

def setup_handler(host, port, paths, config, parent_app=None, subprocess=False):
  handler = WebSocketServer(
    host,
    port,
    paths,
    config,
    parent_app=parent_app
  )
  handlers.append(handler)
  handler.start()

class WebSocketHandler(tornado.websocket.WebSocketHandler):
  def __init__(self, application, request, **kwargs):
    tornado.websocket.WebSocketHandler.__init__(self, application, request, **kwargs)
    self.vodka_id = str(uuid.uuid4()) 
    self.vodka_app = self.application.vodka_app
    self.auth = False

  def open(self):
    print "Websocket %s opened" % self.vodka_id

class WebSocketJsonHandler(WebSocketHandler):
  def handle(self, instructions):
    pass

  def send(self, data):
    self.write_message(json.dumps(data))

  def on_message(self, message):
    print "Got message:%s" % message
    self.handle(json.loads(message))

class EchoHandler(WebSocketHandler): 
  def on_message(self, message):
    print "websocket %s received message: %s" % (self.vodka_id, message)

class WebSocketServer(threading.Thread):

  def __init__(self, host, port, paths, config, parent_app=None):
    threading.Thread.__init__(self)
    self.host = host
    self.port = port
    self.paths = paths
    self.config = config
    self.ssl_certfile = None
    self.ssl_keyfile = None
    self.parent_app = parent_app
    setup_logging("%(asctime)s - vodka websocket %(message)s", config)

  def run(self):
    
    self.application = tornado.web.Application(
      self.paths
    )
    
    self.application.vodka_app = self.parent_app
    self.application.vodka_server = self

    if self.ssl_certfile and self.ssl_keyfile:
      self.application.listen(self.port)
    else:
      print "Setup non-SSL websocket handler at %s:%s" % (self.host, self.port)
      self.application.listen(self.port)

    self.ioloop = tornado.ioloop.IOLoop.current()
    self.ioloop.make_current()
    self.ioloop.start()

  def stop(self):
    self.ioloop.stop()
