"""
WSGI Middleware for python webservers
"""
import types
import string
import weakref
import sys
import gc
import cgi
import os
from ConfigParser import ConfigParser
import urlparse
import re
import mimetypes
import time
import threading
import traceback
import datetime
from Cookie import SimpleCookie
import uuid
from rfc822 import formatdate
from BaseHTTPServer import BaseHTTPRequestHandler
import logging
from gzip import GzipFile
import StringIO
import websocket
import json
from twentyc.tools.config import dict_conf

WSGI_PROFILING = False 

HTTPresponses = BaseHTTPRequestHandler.responses

url_map = []
app_map = {}
sessionCache = {}

__DBG = False 

def urlarg_list(args, key):
  v = args.get(key)
  if type(v) != list:
    v = [v]
  return v

def post_parser_json(data):
  return json.loads(data)

POST_PARSER = {
  "application/json" : post_parser_json
}

def dbg_print(msg):
  """
  Prints a message to stdout if __DBG is True
  """
  if __DBG:
    print msg

def verify_referer(request):
  """
  Verify that referer matches host
  """
  referer = request.get("referer") or ""
  host = request.get("host")
  protocol = request.get("protocol")
  expect_prefix = protocol.lower()+'://' + host.lower() + '/'

  if not referer or not referer.lower().startswith(expect_prefix):
    log.debug("Referer Mismatch: EXPECTED REFERER: %s, PATH: %s, REFERER: %s, REMOTE_ADDR: %s" % (
      expect_prefix,
      request.get("path"),
      referer.lower(),
      request.get("remote_addr")
    ))
    raise HTTPError(403)

def error_handler(code, message, traceback, env, config):
  """
  Handle HTTP errors, overwrite this function to display custom error pages
  for 404 errors (and other error codes)

  Should return content response such as html code.
  """
  if code not in [401]:
    log.debug("\n%s"%traceback)
  return "%s %s<br />%s<br /><pre>%s</pre>" % (str(code), message, env.get("PATH_INFO",""), traceback)

def error_handler_json(code, message, traceback, env, config):
  if code not in [401]:
    log.debug("\n%s"%traceback)
  return json.json.dumps({"meta":{"error":message,"error_type":code}})

ERROR_HANDLERS = {
  "application/json" : error_handler_json
}

def set_header(request, name, value): 

  headers = request.get("headers")
  i = 0
  for n, v in headers:
    if n == name:
      headers[i] = (name, str(value))
      return
    i += 1

  headers.append((name, str(value)))

def on_session_expire(self):
  """
  This gets called when a session expires and will be a method of the
  affected session object, overwrite if needed
  """
  return

def session_validate(self, now_s):
  """
  This gets called during session clean up loop, it will be passed
  a session object, if it returns False, the session object will
  be deleted. Overwrite if needed
  """
  return True

def format_path(path, request):
  """
  Apply formatting to the requested path, overwrite if needed. Should return
  formatted path string
  """
  return path

def register_app(app, id, mount_to):
  """
  Register an application and mount it to the url_map. id should be a unique 
  id for the app. mount_to should be the mount location, set it to "" to mount
  the app as the root app at /.

  Returns the registered app
  """
  app_map[id] = app
  url_map.append([mount_to, app])
  return app

def get_app_instance(id):
  """
  returns the application that was registered with the specified id
  """
  return app_map.get(id, None)

def prepare_request(self, request, environ):
  """
  dummy function
  """
  return


class own(object):
  def __init__(self, owner_id):
    self.owner_id = owner_id
  def __call__(self, fn):
    if hasattr(fn, "owner_id") and fn.owner_id != self.owner_id:
      raise Exception("Two different modules are overriding the same method: %s, (%s, %s)" % (fn, fn.owner_id, self.owner-id))
    fn.owner_id = self.owner_id
    return fn

def json_response(fn):
  def _fn(self, *args, **kwargs):
    req = self.request_info(**kwargs)
    ses = self.get_session(req)
    headers = req.get("headers")
    headers.extend([("content-type", "text/json")])

    rv = fn(self, *args, **kwargs)
    t = time.time()
    rv = json.json.dumps(rv)
    t2 = time.time()
    print "Json Parse: %.2f" % (t2-t)
    return rv
  return _fn

def expose(fn):
  """
  Decorator function that exposes methods of a web application to
  the web server.

  Use infront of functions that you wish to expose 
  """
  if fn:
    fn.exposed = True
  return fn

def get_cookie(req, name, default=None, returnCookie=False):
  v = req.get("cookies_in", {}).get(name)
  if v:
    if not returnCookie:
      return v.value
    else:
      return v
  return default

def valid_wsgi_response(obj):
  t = type(obj)
  if t == unicode:
    return [str(obj)]
  elif isinstance(obj, list):
    return obj
  elif isinstance(obj, types.GeneratorType):
    return obj
  elif isinstance(obj, file):
    return obj
  else:
    return [str(obj)]

def clear_kwargs(kwargs):
  try:
    del kwargs["__request"]
    del kwargs["__environ"]
  except:
    pass
  return kwargs

log = logging.getLogger("Vodka WSGI WebApp")
log.setLevel(logging.DEBUG)

def setup_logging(logformat, config):
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


configs = {}

commandQueue = {
  "expireAllSessions" : False
}


def command(cmd, b = True):
  """
  Execute a wsgi command, such as expireAllSessions

  command('expireAllSessions')
  """
  if commandQueue.has_key(cmd):
    commandQueue[cmd] = b


shutdown_handlers = []

def shutdown_handler():
  log.debug("VODKA SHUTTING DOWN")
  stop_plugins()
  for func in shutdown_handlers:
    func()

  for handler in websocket.handlers:
    print "Stopping websocket handler %s:%s" % (handler.host, handler.port)
    handler.stop()

def redirect(environ, location):
  """
  Redirect Wrapper to create a redirect response, environ should be
  the environ object provided by the wsgi request. location should be 
  the location of the redirect.
  """
  
  environ["request"]["headers"].append(
    ("Location", str(location))
  )
  environ["request"]["status"] = 302
  environ["request"]["done"] = True
  return ""

plugins = []

def add_plugin(Plugin, start=False):
  
  """
  add a plugin to be started and stopped with the server process
  """
  
  plugins.append(Plugin)

  if start:
    Plugin.start()
    Plugin._started = True

  return Plugin

def start_plugins(config):
  
  """
  starts all the plugins that have been added with the add_plugin 
  function. You should not need to call it. This will be called
  when the server process is started
  """
  
  for plugin in plugins:
    if not plugin._started:
      plugin.config = config
      plugin.start()
      plugin._started = True

def stop_plugins():
  
  """
  stops all the plugins that have been added with the add_plugin
  function. You should not need to call it. This will be called
  when the server process is stopped.
  """

  for plugin in plugins:
    if plugin._started:
      plugin.stop()
      plugin._started = False



#####################################################################################
# This is the Base Web App, all your web applications should extend this
#####################################################################################

class BaseApp:
  
  """
  Base Web Application. All Your Web Applications should extend from this
  class
  """

  # these are the standard headers sent with every request

  headers = [
    ("Pragma", "no-cache"),
    ("Cache-Control", "no-cache")
  ]

  def handle_request(self, request, environ):
    """
    Called on the beginning of each request
    """
    pass

  def cleanup_request(self, request, environ):
    """
    Called on the end of each request
    """
    pass

  def request_info(self, **kwargs):
    return kwargs.get("__request")

 
  def dispatch(self, environ, request, path, query):

    """
    Dispatches a request to an exposed function of the web application or
    one of it's members
    """

    self.handle_request(request, environ)
    
    if not path or not path[0]:
      path = ['index']
    
    if hasattr(self, path[0]):
      fnc = getattr(self, path[0])
        
      if not fnc or not hasattr(fnc, 'exposed') or not fnc.exposed:
        dbg_print("%s not exposed" % str(fnc))
        raise HTTPError(404)

      path.pop(0)
      if hasattr(fnc, 'dispatch'):
        environ["dispatch_to"] = fnc
        setattr(fnc, 'cleanup_request', self.cleanup_request)
        return fnc.dispatch(environ, request, path, query)
      else:
        # send default headers
        request.get("headers", []).extend(self.headers)
        return fnc(__environ=environ, __request=request, *path, **query)

    else:
      raise HTTPError(404)

####################################################################################
####################################################################################
####################################################################################

class HTTPError(Exception):
  
  """
  HTTPError Exception. Raise with error code as argument in case of
  HTTP Error
  """ 

  def __init__(self, value):
    self.value = value

  def __str__(self):
    return repr(self.value)

  def __int__(self):
    return int(self.value)

class HTTPRedirect(Exception):
  
  """
  HTTPRedirect Exception. Raise to send redirect response. location should
  be the argument of the Exception
  """

  def __init__(self, value):
    self.value = value

  def __str__(self):
    return str(self.value)

class HTTPCreated(Exception):
  
  """
  HTTPAccept Exception. Raise when you want to send a 201 Status with Location
  """

  def __init__(self, location, content=""):
    self.value = location
    self.content = content

  def __str__(self):
    return str(self.value)

class BaseHandler(object):

  profile = False
  config = None

  def set_profiling(self):
    self.profile = WSGI_PROFILING

  def start_profile(self, force=False):
    
    """
    If self.profile is true, return a timestamp float of current time
    else return 0
    """

    if self.profile or force:
      return time.time()
    else:
      return 0

  def end_profile(self, handlerName, environ, t, force=False):
    
    """
    if self.profile is true, store profile for this handler in environ["request"]
    """

    if self.profile or force:
      d = time.time()-t
      if d < 0.0001:
        d = 0.0000
      environ["request"]["profile"][handlerName] = d
      return d
    return 0

  def save_profile(self, environ):
    """
    save the profile data to webapp.profile
    """

    if self.profile:
      overview = profile.get("overview")
      r = environ.get("request", {})
      P = r.get("profile", {})
      P["total"] = time.time() - r.get("profile_start")
      path = r.get("path")
      query = r.get("query_string")

      if not overview.has_key(path):
        overview[path] = {
          "num" : 1,
          "time" : P
        }
      else:
        overview = overview.get(path)

        overview["num"] += 1
        for handler, t in P.items():
          if overview["time"].has_key(handler):
            overview["time"][handler] += t
          else:
            overview["time"][handler] = t

      recent = profile.get("recent")

      recent.insert(0, {
        "path" : path,
        "query" : query,
        "time" : P
      })

      if len(recent) > 15:
        recent = recent[0:15]

      profile["recent"] = recent

 

####################################################################################
# Initial Request Handler
####################################################################################

class RequestHandler(BaseHandler):
  
  """
  WSGI Middleware to handle the incoming request and set up the request
  object under enviro['request']
  """

  def __init__(self, configName):
    self.application = None
    self.config = {}
    
    # load config   
 
    dbg_print("Loading config: %s" % configName)

    self.config = dict_conf(configName)

    # setup url map from config

    url_map.extend(self.config.get("path",{}).items())
    dbg_print(str(url_map))

  def __call__(self, environ, start_response):

    #profiling time spent in this handler

    self.set_profiling()

    t = self.start_profile()

    #set various environment variables that could be useful

    environ["request"] = {
      "status" : 200,
      "now" : datetime.datetime.now(),
      "cookies_in" : SimpleCookie(environ.get('HTTP_COOKIE')),
      "cookies_out" : {},
      "host" : environ.get("HTTP_HOST", environ.get("host")),
      "user_agent" : environ.get("HTTP_USER_AGENT", ""),
      "protocol" : environ.get("wsgi.url_scheme"),
      "referer" : environ.get("HTTP_REFERER"),
      "uploads" : {},
      "headers" : []
    }
    
    if self.profile:
      environ["request"]["profile"] = {}
      environ["request"]["profile_start"] = t
  
    self.end_profile("request-handler", environ, t)


    return ""

     

####################################################################################
# Dispatch Handler
####################################################################################

class UploadSizeException(Exception):
  """
  This Exceptions gets raised if the uploaded file was bigger than the specified
  upload limit in the config
  """
  pass
 
class DispatchHandler(BaseHandler):

  """
  WSGI Middleware that dispatches the request to either the file system or
  the web application
  """

  def __init__(self, application):
    self.application = application
    self.config = application.config
    self.set_profiling()
    
  
  def __call__(self, environ, start_response):

    self.application(environ, start_response)

    t_p = self.start_profile()

    path = environ.get("PATH_INFO", "")
    query = environ.get("QUERY_STRING", "")
    query = urlparse.parse_qs(query, keep_blank_values = True)
    GET_DATA = {}
    POST_DATA = {}

    #prepare query dict
  
    for key, items in query.items():
      if len(items) < 2:
        query[key] = items[0]
        GET_DATA[key] = items[0]
    
    # handle post requests accordingly

    if environ.get("REQUEST_METHOD", "GET") in ["POST","PUT"]:
       
      input = environ.get("wsgi.input")
      try:
        input_r = input.read(int(environ.get("CONTENT_LENGTH",0)))
      except Exception, inst:
        log.error(traceback.format_exc())
        raise HTTPError(400)
 
      ctype = environ.get("CONTENT_TYPE","").lower()
      if ctype.find('application/x-www-form-urlencoded') != 0 and ctype and not POST_PARSER.get(ctype):
        raise HTTPError(400)

      if POST_PARSER.get(ctype):
        try:
          POST_DATA = POST_PARSER[ctype](input_r)
        except:
          log.error(traceback.format_exc())
          raise HTTPError(400)

        query.update(POST_DATA)
      else:
        post_query = {}
        post_env = environ.copy()
        post_env['QUERY_STRING'] = ''
         
        try:
          form = cgi.FieldStorage(
            fp=StringIO.StringIO(input_r),
            environ=post_env,
            keep_blank_values=True
          )
        except Exception, inst:
          log.error(traceback.format_exc())
          raise HTTPError(400)
  
        for field in form.keys():
          if type(form[field]) == list:
            post_query[field] = []
            for fld in form[field]:
              post_query[field].append(fld.value)
          else:
            if hasattr(form[field], 'filename'):
              environ["request"]["uploads"][field] = form[field]
            post_query[field] = form[field].value
        query.update(post_query)
        POST_DATA = post_query
        dbg_print("post_data: %s - %s" % (str(query), str(post_query)))
  
    conf = self.config.get("server", {})
    addr_loc = conf.get("remote_addr_var", "REMOTE_ADDR")

    environ["request"].update({
      "method" : environ.get("REQUEST_METHOD"),
      "path" : path,
      "host" : environ.get("HTTP_HOST", ""),
      "user_agent" : environ.get("HTTP_USER_AGENT", ""),
      "remote_addr" : environ.get(addr_loc, ""),
      "query_string" : environ.get("QUERY_STRING", ""),
      "query" : query,
      "get_data" : GET_DATA,
      "post_data" : POST_DATA
    })

    #handle file uploads
    
    contentType = environ.get("CONTENT_TYPE","")
   
    if(contentType and contentType.find("multipart/form-data") > -1):
    #if(environ.get("CONTENT_TYPE").find("multipart/form-data") > -1):
      #print "Handling file upload"
      #print "File Size: %s" % str(environ.get("CONTENT_LENGTH"))
      s = int(environ.get("CONTENT_LENGTH"))
     
      ms = int(conf.get("upload_max_size", 1000000))
      if ms < s:
        raise UploadSizeException("Uploaded file too big, maximum size %d allowed" % ms)

    #prepend request specific urlmap if it exists

    ext_url_map = environ.get("request").get("session").data.get("url_map")
    if ext_url_map:
      umap = list(ext_url_map)
      umap.extend(url_map)
    else:
      umap = url_map

    #print "URL MAP: %s, %s" % (environ.get("request").get("path"), ext_url_map)

    #dispatch request to either application or static path
    o_path = path

    for map in umap:
      dbg_print("%s : %s" % (map[0], path))
      if re.match(map[0], path):
        if type(map[1]) == str:
          path = path.replace(map[0], map[1])
          path = os.path.join(self.config.get("server",{}).get("root", ""), path)
          #print "ROOT: "+path
          
          #allow for app specific path formatting

          path = format_path(path, environ["request"])
          dbg_print("dispatching to path: %s" % path)
            
          if not os.path.exists(path):
            if len(map) > 2:
              path = o_path.replace(map[0], map[2])
              if not os.path.exists(path):
                raise HTTPError(404)
            else:
              raise HTTPError(404)

          dbg_print("path exists")

          environ["dispatch_to"] = path 

          mimetype = mimetypes.guess_type(path)[0]
          if not mimetype:
            mimetype = "text/html"
          
          environ["request"]["headers"].append(("Content-type", mimetype))
          file = open(path, "r")
          c = file.read()
          file.close()
          self.end_profile("dispatch-handler", environ, t_p)
          return c
        else:
          environ["request"]["headers"].append(("Content-type", "text/html"))
          path = path.split("/")
          path.pop(0)
          if map[0] is not "":
            e = len(map[0].split("/"))
            while e > 1:
              path.pop(0)
              e = e-1

          environ["dispatch_to"] = map[1] 
          if self.profile:
            self.end_profile("dispatch-handler-prep", environ, t_p)
            t_p = self.start_profile()
            rv = map[1].dispatch(environ, environ.get("request"), path, query)
            self.end_profile("dispatch-handler", environ, t_p)
            return rv
          else:
            return map[1].dispatch(environ, environ.get("request"), path, query)
      
    raise HTTPError(404)
    
####################################################################################
# This is the Error Handler
####################################################################################

class ErrorHandler(BaseHandler):
  
  """
  WSGI Middleware for error handling
  """

  def __init__(self, application):
    self.application = application
    self.config = application.config

  def __call__(self, environ, start_response):
    
    accept = environ.get("HTTP_ACCEPT")
    
    try:

      return self.application(environ, start_response)
      
    except HTTPError, inst:

      errorString = HTTPresponses.get(int(inst), ())[0]

      environ["request"].update({
        "status" : int(inst),
        "headers" : [],
        "done" : True
      })

      hdl  = ERROR_HANDLERS.get(accept, error_handler)
      return hdl(int(inst), errorString, traceback.format_exc(), environ, self.config.get("error", {}))

    except HTTPRedirect, location:
      
      environ["request"]["headers"].append(
        ("Location", str(location))
      )
      environ["request"]["status"] = 302
      environ["request"]["done"] = True
      
      return ""

    except HTTPCreated, location:
      
      environ["request"]["headers"].append(
        ("Location", str(location))
      )
      environ["request"]["status"] = 201
      environ["request"]["done"] = True
      
      return location.content

    except Exception, inst:

      errorString = HTTPresponses.get(500, ())[0]

      environ["request"].update({
        "status" : 500,
        "headers" : [],
        "done" : True
      })
      try: 
        hdl  = ERROR_HANDLERS.get(accept, error_handler)
        return hdl(500, errorString, traceback.format_exc(), environ, self.config.get("error", {}))
      except HTTPRedirect, location:
        return redirect(environ, str(location))




####################################################################################
# This is the HTTP Cache Header handler
####################################################################################

class HTTPCacheHandler(BaseHandler): 
  
  """
  WSGI Middleware for cache handling
  """

  def __init__(self, application):
    self.application = application
    self.config = application.config
    self.set_profiling()

  def __call__(self, environ, start_response):

    rv = self.application(environ, start_response)
    t_p = self.start_profile()

    request = environ.get("request", {})
    headers = request.get("headers", [])
    
    # if request is done skip execution of this module

    if request.get("done", False):
      return rv

    # see where the request was dispatched to, if value is a string it
    # was dispatched to a static file, if target is an object it
    # was dispatched to the application, application caching applies

    if environ.has_key("dispatch_to"):
      
      dispatch_to = environ.get("dispatch_to")

      if type(dispatch_to) == str:
        
        
        # set cache expiry by config (default value 3600) if
        # no cache config is set up for extension 

        m = re.search("\.([^\.]+)$", environ.get("PATH_INFO", ""))
        if m:
          extension = m.group(0)
        else:
          extension =  "html"
        
        dbg_print("Sending Cache headers for static file (%s)" % extension)
        
        cacheConfig = self.config.get("cache", {})

        if cacheConfig.has_key(extension):
          maxAge = int(cacheConfig.get(extension))
        else:
          maxAge = int(cacheConfig.get(".*", 3600))

        #print "Max Age: %d" % maxAge
         
        mtime = formatdate(os.path.getmtime(dispatch_to))
        cacheHeaders = [
          ("Pragma", "cache"),
          ("Cache-Control", "max-age=%d, must-revalidate" % maxAge)
        ]

        #dbg_print(str(environ))


        #check if file has been modified and send cache response
        #if possible

        if environ.get('HTTP_IF_MODIFIED_SINCE') == mtime:
          headers.extend(cacheHeaders)
          request["status"] = 304 
          self.end_profile("cache-handler", environ, t_p)
          return ""
        
        # send last modified time to browser
          
        headers.append(("Last-Modified", mtime))
    
    self.end_profile("cache-handler", environ, t_p)
    return rv


   

####################################################################################
# Session Handler
####################################################################################

class SessionObject():

  """
  Session object that will be stored in environ['request']['session']

  SessionObject.data is the dict in which the session data should be stored
  in

  SessionObject.forceExpire can be set to true to expire this session object
  the next time it is requested
  """
  
  def __init__(self, id, expires):
    dbg_print("New session with id %s to expire on %s" % (id, str(expires)))
    self.id = id
    self.data = {}
    self.expires = expires
    self.on_expire = on_session_expire
    self.forceExpire = False


class SessionManager(object):
    
  def __init__(self):
    self.cache = sessionCache
 
  def cleanup(self):
    dbg_print("cleaning up sessions")
    now = datetime.datetime.now()
    now_s = time.mktime(now.timetuple())
    cleanup = []
    if self.profile:
      profile["sessions"] = len(self.cache.keys())
    for sid, session in self.cache.items():
      if session.expires <= now or session.forceExpire:
        cleanup.append(sid)
      elif not session_validate(session, now_s):
        cleanup.append(sid)

    for sid in cleanup:
      self.del_session(sid)

  
  def del_session(self, sid):
    dbg_print("deleting session "+str(sid))
    session = self.load_session(sid)
    if session:
      session.on_expire(session)
      if self.cache.has_key(sid):
        del self.cache[sid]


  def del_all(self):
    dbg_print("deleting all sessions")
    for sid, session in self.cache.items():
      self.del_session(sid)

  def load_session(self, sid):
    #print str(self.cache.keys())
    if self.cache.has_key(sid): 
      return weakref.proxy(self.cache.get(sid))
    else:
      return None 
  
  def generate_id(self):
    id = str(uuid.uuid4())
    while self.cache.has_key(id):
      id = str(uuid.uuid4())
    return id


class SessionHandler(BaseHandler, SessionManager):
  
  """
  WSGI Middleware for session handling
  """

  cache = {}

  def __init__(self, application):
    global sessionCache
    self.application = application
    self.config = application.config
    self.sesconf = self.config.get("session", {})
    self.cache = sessionCache

  def __call__(self, environ, start_response):
    self.set_profiling()
    rv = self.application(environ, start_response)
    t_p = self.start_profile()
    request =  environ.get("request", {})
    headers = request.get("headers", [])

    sesconf = self.sesconf

    # if expireAllSessions command is set, expire all sessions

    if commandQueue.get("expireAllSessions", False):
      self.del_all() 
      command("expireAllSessions", False)
    
    self.end_profile("ses1", environ, t_p)
   
    # if request is done skip execution of this module

    if request.get("done", False):
      self.end_profile("session-handler", environ, t_p)
      return rv
    
    # timeout expired sessions
    
    # self.cleanup(request)

    expires = request["now"] + datetime.timedelta(seconds=int(sesconf.get("timeout", 60*60*24)))

    # load cookie

    cookie = SimpleCookie(environ.get('HTTP_COOKIE')) 
    cookie_name = sesconf.get("cookie_name", "SID")
    cookie_path = sesconf.get("cookie_path", "/")
    cookie_secure = sesconf.get("cookie_secure", "yes")

    cookie_support = len(cookie.keys())

    data = cookie.get(cookie_name, None)

    self.end_profile("ses2", environ, t_p)

    if data:
      
      cookie_support = "ok"
   
      #print "cookie data found, trying to load session %s" % str(data.value)
      
      # session id found in cookie, attempt to load session

      request["session"] = self.load_session(data.value)
      
      if request["session"]:
        request["session"].expires = expires
      cookie[cookie_name]["expires"] = expires.ctime() 
      cookie[cookie_name]['path'] = cookie_path
      
      if(cookie_secure == "yes"):
        cookie[cookie_name]['secure'] = True


    if (not data or not request["session"]) and cookie_support:
      sid = self.generate_id()
      
      #log.error(
      #  "Creating new session object for %s, %s, cookie status: %s, sessions: %s" % 
      #  (sid, str(request), str(data), self.cache.keys())
      #)

      # session id not foind in cookie, create new session and send cookie data
      
      self.cache[sid] = SessionObject(
        id = sid, expires = expires
      )
      if self.profile:
        profile["sessions"] += 1
      request["session"] = self.load_session(sid)
      request["created_session"] = sid 

      cookie[cookie_name] = sid
      cookie[cookie_name]["expires"] = expires.ctime() 
      cookie[cookie_name]['path'] = cookie_path
      if(cookie_secure == "yes"):
        cookie[cookie_name]['secure'] = True
      #print "Cookie set for %s" % str(sid)
    elif not cookie_support:
      request["session"] = SessionObject(id=self.generate_id(), expires=expires)
      cookie["cookie_ok"] = "ok"
      cookie["cookie_ok"]["path"] = "/"
      if(cookie_secure == "yes"):
        cookie["cookie_ok"]['secure'] = True
      request["cookies_out"]["cookie_ok"] = cookie
      #cookie["cookie_ok"]["expires"] = expires.ctime()
      #print "Cookie support not established yet, no session object stored"

    self.end_profile("ses3", environ, t_p)

    request["cookies_out"][cookie_name] = cookie
   
    #headers.append(('Set-Cookie', cookie[cookie_name].OutputString()))

    self.end_profile("session-handler", environ, t_p)

    for app_id, app in app_map.items():
      if hasattr(app, "prepare_request"):
        app.prepare_request(request, environ)

    return rv

   

####################################################################################
# Response Handler, sends response
####################################################################################

class ResponseHandler(BaseHandler):

  """
  WSGI Middleware that will send the response
  """

  def __init__(self, application):
    self.application = application
    self.config = application.config
    self.cookie_path = self.config.get("session",{}).get("cookie_path", "/")
    self.cookie_secure = self.config.get("session",{}).get("cookie_secure", True)

  def __call__(self, environ, start_response):

    self.set_profiling()
    t_total = self.start_profile();

    rv = self.application(environ, start_response)
    t_p = self.start_profile()
    request = environ.get("request", {})
    headers = request.get("headers")
    cookies = request.get("cookies_out")


    # set cookie headers

    if cookies:
      for key, value in cookies.items():
        if type(value) != SimpleCookie:
          cookie = SimpleCookie()
          cookie[key] = value
          cookie[key]["path"] = self.cookie_path 
          if self.cookie_secure == "yes":
            cookie[key]["secure"] = True
        else:
          cookie = value
        if cookie.has_key(key):
          headers.append(('Set-Cookie', cookie[key].OutputString()))

    if request.get("created_session"):
      log.debug(
        "NEW SESSION CREATED %s @ %s - %s... on path %s, HTTP_COOKIE: %s" % (
          request.get("user_agent"),
          request.get("remote_addr"),
          request.get("created_session")[:8],
          request.get("path"),
          environ.get("HTTP_COOKIE")
        )
      )
    #print "response handler: %s, %s" % (request.get("path"), headers)
    
    # send status and headers 
    
    status = int(request.get("status", 200))
    status = "%s %s" % (str(status), HTTPresponses.get(status, ('OK'))[0])

    headers = request.get("headers", [])
    
    if False and self.config.get("server", {}).get("gzip","no") == "yes":
      headers.append(("Content-Length", str(len(rv))))

    dbg_print("Sending %s : %s" % (request.get("status"), str(headers)))

    t_d = self.end_profile("total-response-time", environ, t_total)
    if t_d:
      headers.append(("Server-Overhead-Time", str(t_d)))

    headers.append(("Server-Time", "%.5f" % time.time()))

    start_response(status, headers)

    # if dispatch went to app , call cleanup_request

    if hasattr(environ.get("dispatch_to"), "cleanup_request"):
      environ["dispatch_to"].cleanup_request(request, environ)
      self.end_profile("response-handler", environ, t_p)
      self.save_profile(environ)
      return valid_wsgi_response(rv)
    

    self.end_profile("response-handler", environ, t_p)
    self.save_profile(environ)
    return valid_wsgi_response(rv)

    # send content

####################################################################################
# GzipHandler
####################################################################################

class GzipHandler(BaseHandler):
    
  """
  WSGI Middleware for GZIP Compression
  """
  
  def __init__(self, application, compresslevel=6):
    self.application = application
    self.config = application.config
    self.compresslevel = compresslevel
 
  def __call__(self, environ, start_response):
    self.set_profiling()
    accept_encoding_header = environ.get("HTTP_ACCEPT_ENCODING", "")
    
    if self.config.get("server",{}).get("gzip", "no") != "yes":
      return self.application(environ, start_response)

    if(not self.client_wants_gzip(accept_encoding_header)):
      return self.application(environ, start_response)

    data = "".join(self.application(environ, start_response))
    t_p = self.start_profile()
    req = environ.get("request")
    headers = req.get("headers")
    headers.append(("Content-Encoding", "gzip"))
    headers.append(("Vary", "Accept-Encoding"))
    
    if self.profile:
      rv = self.gzip_string(data, self.compresslevel)
      self.end_profile("gzip-handler", environ, t_p)
      return rv
    else:
      return self.gzip_string(data, self.compresslevel)

  ##############################################################################

  def gzip_string(self, string, compression_level):
    fake_file = StringIO.StringIO()
    gz_file = GzipFile(None, 'wb', compression_level, fileobj=fake_file)
    gz_file.write(string)
    gz_file.close()
    return fake_file.getvalue()

  ##############################################################################

  def parse_encoding_header(self, header):
    encodings = {'identity':1.0}
    for encoding in header.split(","):
        if(encoding.find(";") > -1):
            encoding, qvalue = encoding.split(";")
            encoding = encoding.strip()
            qvalue = qvalue.split('=', 1)[1]
            if(qvalue != ""):
                encodings[encoding] = float(qvalue)
            else:
                encodings[encoding] = 1
        else:
            encodings[encoding] = 1
    return encodings
 
  ##############################################################################

  def client_wants_gzip(self, accept_encoding_header):
    encodings = self.parse_encoding_header(accept_encoding_header)
 
    # Do the actual comparisons
    if('gzip' in encodings):
        return encodings['gzip'] >= encodings['identity']
 
    elif('*' in encodings):
        return encodings['*'] >= encodings['identity']
 
    else:
        return False

####################################################################################

configPath = "server.conf"

profile = {
  "overview" : {},
  "sessions" : 0,
  "recent" : []
}

SERVER_RUNNING = 1
SERVER_SHUTTING_DOWN = 2
serverStatus = SERVER_RUNNING


def clean_up_session():
  while True:
    dbg_print("cleaning up sessions")
    now = datetime.datetime.now()
    now_s = time.mktime(now.timetuple())
    cleanup = []
    for sid, session in sessionCache.items():
      if session.expires <= now or session.forceExpire:
        cleanup.append(sid)
      elif not session_validate(session, now_s):
        cleanup.append(sid)

    for sid in cleanup:
      del sessionCache[sid]
    #log.debug("Cleaned up sessions, %d left" % len(sessionCache.keys()))
    time.sleep(30)

ses_clean_up = threading.Thread(target=clean_up_session)
ses_clean_up.daemon = True
ses_clean_up.start()

def get_application(dummy=False):

  config = configPath

  """
  Get new wsgi application object using the specified config file
  """
  application = RequestHandler(config)
  application = SessionHandler(application)
  application = DispatchHandler(application)
  application = HTTPCacheHandler(application)
  application = ErrorHandler(application)
  application = GzipHandler(application)
  application = ResponseHandler(application)
  
  configs[config] = application.config

  return application

###############################################################################
# P L U G I N 
###############################################################################

class Plugin(object):

  """
  Base plugin object, all plugins should extend this object
  """

  config = {}
  _started = False

  #############################################################################

  def start(self):
    pass

  #############################################################################

  def stop(self):
    pass


class TestPlugin(Plugin):
  
  def start(self):
    print "Test plugin started ..."

  def stop(self):
    print "Test plugin stopped ..."
