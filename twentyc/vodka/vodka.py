#!/pyenv/2.6/bin
import imp
import cProfile
import os
import config
from wsgi import webapp, locale
from util import instance_id_from_config

serverConfPath = config.path
webapp.configPath = serverConfPath
vodkaPath = os.path.abspath(os.path.join(os.path.dirname(__file__)))

import weakref

from pprint import pformat
from Cookie import SimpleCookie

import new
import md5
import signal
import base64
import ConfigParser
import urllib
import re
import twentyc.database
import twentyc.vodka.tools.module_manager
import tmplbridge
import session
import task as vodkatask
import traceback
import random
import logging, logging.handlers
import time
import smtplib
import errno
import socket
import operator
from constants import *
import sys
import types
import simplejson as jsonlib
import threading
import copy
from threading import Thread
from twentyc.tools.syslogfix import UTFFixedSysLogHandler
import random
import inspect
import validator

from wsgi.server import *

try:
  import xbahn
except ImportError:
  print "Warning, xbahn module not installed, no xbahn support"
  xbahn = None

import subprocess
import bartender
import twentyc.database.tools

if xbahn:
  # set up xbahn topic config
  xbahn.topic_instructions["^__U\..+\.notify$"] = {
    "discard_data" : True
  }

# remove unretrieved task results after n seconds
TASK_CLEANUP_MARGIN = 60

# remove unfinished task after n seconds
TASK_TIMEOUT_MARGIN = 600

# remove unfinished task if it has stopped sending for n seconds
TASK_SILENCE_MARGIN = 60

# mac concurrent tasks per session
TASK_SESSION_CAP = 3

# import this to make this file runable with twistd
#from wsgi.uwsgi_server import *

##############################################################################
# Functions
###############################################################################
# Turn list of objects into a key => value dict

#def map(d, keyName='id', valueName='name', setNone=False):
#  r = {}
#  for k,v in d.items():
#    r.setdefault(getattr(v, keyName), getattr(v, valueName))
#  if setNone == True:
#    r.setdefault('0', 'None')
#  return r

def dbg(msg):
  print "Vodka: %s" % msg

def dict_equal(a, b):
  for k,v in b.items():
    if a.get(k) != v:
      return False
  return True

def obj_equal(a, b):
  
  if not a and b:
    return False
  elif not b and a:
    return False

  return dict_equal(a.__dict__, b.__dict__)

#############################################################################
# check if app environment is production

def is_production():
  env = serverConf.get("environment", "production")
  if env == "production":
    return True
  else:
    return False

def row2dict(row):
  d = {}
  for columnName in row.keys():
    d[columnName] = getattr(row, columnName)
    if hasattr(d[columnName], "strftime"):
      d[columnName] = int(d[columnName].strftime("%s"))
  return d

################################################################################
# load error page

errorPage = None

################################################################################
# error handler function

def error_handler(code, message, traceback, env, config):
  
  """
  error handler function that will take care of displaying 
  http error pages (404, 500 etc.) 

  if server env is set to production error pages will now show
  a traceback
  """
  
  try:
    raise
  except webapp.UploadSizeException:
    ses = env.get("request").get("session").data.get("client_session")
    ses.error("Uploaded file too big", True)
  except:
    pass

  if code in [404]:
    message += ": %s" % env.get("PATH_INFO", "")
  
  if code not in [401]:
    webapp.log.debug("(%d) %s\n%s" % (code, message, traceback))
  
  if is_production():
    traceback = ''

  if code in [503]:
   
    f = open("htdocs/503/index.html", "r");
    html = f.read()
    f.close()

    return html % {
      "errormsg" : serverConf.get("503_error_msg", "Out of Service"),
      "errormsg_apology" : serverConf.get("503_error_apology", "We apologize for any inconvenience. Please check back soon!")
    }

  else:
    global errorPage
 
    if not errorPage:
      f = open('htdocs/error.html', 'r')
      errorPage = f.read()
      f.close()

    return errorPage % {
      "status" : str(code), "message" : message, "traceback": traceback
    } 

webapp.error_handler = error_handler

###############################################################################

def format_path(path, request):
  
  """
  format a path to handle correct brand selection
  """
  
  ses = request["session"].data.get("client_session")
  
  if ses:
    brand = ses.brand
    #print "Using brand %s" % (str(brand))
    path = path.replace("__BRAND__", brand.get("dir"))

  return path
webapp.format_path = format_path

mcfg = webapp.dict_conf(serverConfPath).get("modules")

# defines the order in which modules should be loaded on the client
module_js_load_order =[]

# defines the order in which modules should be loaded on the server
module_py_load_order = []

# holds the python components loaded from vodka modules (as python modules)
# indexed by modulname and component name
module_py_components = {}


from rpc import *
from datetime import datetime, timedelta

###############################################################################
# load pref validators from disk

validators_path = os.path.join(os.path.dirname(inspect.getfile(twentyc.vodka)), "data", "validators")

if os.path.exists(validators_path):
  for validator_file in os.listdir(validators_path):
    if re.match("^.+\.json$", validator_file):
      validator.add_from_file(os.path.join(validators_path,validator_file))

###############################################################################
# Classes
###############################################################################

class VodkaAppThread(Thread):
  
  """
  Extends threading.Thread
  
  Example:

  t = VodkaAppThread(my_func)
  t.start("some text")
  will call my_func("some text") in it's own thread
  """
  
  def __init__(self, callback):
    
    """
    Init and set callback function, the callback function
    will be executed on run()
    """
    
    Thread.__init__(self)
    self.callback = callback

  def run(self):
    self.callback(*self.runArgs)
    del self.callback
    del self.runArgs

  def start(self, *args):
    
    """
    Set the arguments for the callback function and start the
    thread
    """

    self.runArgs = args
    Thread.start(self)

###############################################################################
# VodkaApp
###############################################################################

class VodkaApp(webapp.BaseApp):

  """
  The main vodka application

  Also handles page rendering
  """

  #############################################################################
  # Initialize object

  def __init__(self, clientClass=None):
    
    """
    Initialize the App

    clientClass can be set if you want client pool to spawn an object
    different to VodkaClient
    """

    self.config = webapp.dict_conf(serverConfPath)
    self._Client = clientClass or VodkaClient

    self.is_production = is_production()

    self.session_map = {}

    self.templates = {}

    self.id = instance_id_from_config(self.config.get("server",{}))
    #self.id = self.config.get("server",{}).get("vodka_id",
    #  str(md5.new("%s-%s" % (socket.gethostname(), uwsgi.opt.get("socket"))).hexdigest())[:8]
    #)

    if self.config.get("profiler",{}).get("wsgi") == "yes":
      self.toggle_profile_requests(state="on")

    # status

    self.http_requests = 0
    self.http_requests_prev = 0
    self.http_requests_total = 0
    self.http_request_time = 0

    self.app_status = 0

    # load app config

    self.serverConfig = serverConf
    self.pathRoot = self.config.get("server",{}).get("root", "/")

    self.locationConfig = self.config.get("locations", {
      "js" : "base/js",
      "css" : "base/css",
      "libs" : "base/libs"
    })

    self.statusKey = self.config.get("app", {}).get("status_key", None)

    # set up version based dispatch
    
    pathCfg = self.config.get("path", {})
    for path, dest in pathCfg.items():
      webapp.url_map.append(["/%s%s" % (version, path), dest])

    self.debugging = (self.config.get("app", {}).get("debugging", "no") == "yes")

    # set up profiling

    profile_conf = self.config.get("profiler", {})
    if profile_conf.get("enabled") == "yes":
      self.profiling = True
      self.profiling_path = profile_conf.get(
        "output.path", 
        os.path.join(
          os.path.dirname(__file__),
          "profile",
          "%s.profile" % ("%s."+str(int(time.time())))
        )
      )
    else:
      self.profiling = False
      self.profiling_path = None

    if profile_conf.get("wsgi") == "yes":
      self.profiling_wsgi = True
    else:
      self.profiling_wsgi = False
    
    # set up logging

    log = webapp.log
    if is_production() or int(self.config.get("server",{}).get("syslog",0)):
      
      syslog_address = self.config.get("server", {}).get("syslog_address", "/dev/log")
      syslog_facility = self.config.get("server", {}).get("syslog_facility", "LOG_LOCAL0")

      print "Using syslog to log error messages (address:%s) (facility:%s)" % (syslog_address, syslog_facility)
      
      hdl = UTFFixedSysLogHandler(address=syslog_address, facility=getattr(logging.handlers.SysLogHandler, syslog_facility))
      hdl.setFormatter(logging.Formatter(" Vodka %(message)s"))
    else:
      hdl = logging.FileHandler("error.log")
      hdl.setFormatter(logging.Formatter("%(asctime)s - vodka %(message)s"))
    
    log.addHandler(hdl)
    self.log = log

    try:
      
      # load grant permissions list from config
      
      self.grant_permissions = self.config.get("grant_permissions", {})
      for name, perms in self.grant_permissions.items():
        t = perms
        p = 0
        if "r" in t:
          p |= 0x01
        if "w" in t:
          p |= 0x02
        if "x" in t:
          p |= 0x04
        self.grant_permissions[name] = p
        self.info("GRANTING EVERYONE PERMISSION to %s at level %d" % (name, p))
    
      # load brand and theme map from dispatch

      self.load_dispatch()
    
      # connect database client
      self.couch_engine = serverConf.get("couch_engine", "couchdb")
      self.couch_config = self.config.get(self.couch_engine)

      self.info("Using database: %s" % self.couch_engine)
     
      if not self.couch_config:
        raise Exception("Attempted to use couch-engine: %s for preferences, but found no config section for it" % couch_engine)

      design_path = os.path.join(os.path.dirname(inspect.getfile(twentyc.vodka)), "data", "design")
      self.info("Making sure designs are up to date, reading from %s ..." % design_path)

      for design_file in os.listdir(design_path):
        twentyc.database.tools.update_views(
          self.couch_engine, 
          self.couch_config, 
          os.path.join(design_path, design_file)
        )
 
      self.db_prefs = twentyc.database.ClientFromConfig(
        self.couch_engine, 
        self.couch_config, 
        "prefs",
        logger=self.log
      )

      pref_limits = self.config.get("pref_limits", {})
      if not pref_limits.has_key("color_theme"):
        raise Exception("Missing pref limit for color themes, add in section [pref_limits], color_theme : n")
      if not pref_limits.has_key("layout"):
        raise Exception("Missing pref limit for layout, add in section [pref_limits], layout : n")


      for doctype, limit in pref_limits.items():
        prefs.document_limits[doctype] = int(limit)

      # connect vodka module manager
      self.module_manager = twentyc.vodka.tools.module_manager.ModuleManager(
        logger=self.log
      )
      self.db_modules = twentyc.database.ClientFromConfig(
        self.couch_engine,
        self.couch_config,
        "modules",
        logger=self.log
      )
      self.module_manager.set_database(self.db_modules)


      # stores module data for easy access,
      # version, status, mobile, dependencies and whether the
      # were loaded from disk or database
      
      self.module_status = {}
      self.module_status_time = 0 
      self.module_js_load_order = module_js_load_order
      self.module_py_load_order = module_py_load_order
      
      # load modules from disk
      self.load_modules_from_disk()
      
      # load modules from database.
      self.load_modules()
      self.update_modules()

      if self.config.get("module_load_order"):
        load_order = self.config.get("module_load_order",{})
        self.module_js_load_order = sorted(self.module_js_load_order, key=lambda obj:load_order.get(obj, "99"))

      # load unload tools js and store it
      f = open("htdocs/js/twentyc.unloadtools.js", "r")
      self.unload_tools_code = f.read()
      f.close()


      # extend from modules if needed
      self.modules = module_py_components
      if module_py_components:
        for name in module_py_load_order:
          mod = module_py_components.get(name)
          if hasattr(mod, 'extend_vodka'):
            self.info("%s is extending application" % name)
            mod.extend_vodka(self, VodkaApp);

      # bind rpc

      from rpc import RPC
      self.rpc_json = RPC(RPC_OUTPUT_JSON, self)
      self.rpc_json.exposed = True

      self.rpc_static = RPC(RPC_OUTPUT_STATIC, self)
      self.rpc_static.exposed = True

      # connect xbahn 

      self.storage = {} 

      self.xbahn = None
      if xbahn:
        xbahn_connect = VodkaAppThread(self.connect_xbahn)
        xbahn_connect.start()

      # connect client pool
 
      self.client_pool = ClientPool(
        int(self.config.get("app", {}).get("client_pool.size", 20)),
        self
      )

      # tasks will be stored here

      self.tasks = {}

      self.taskCleanupMargin = int(self.config.get("tasks", {}).get("cleanup_margin", TASK_CLEANUP_MARGIN))
      self.taskTimeoutMargin = int(self.config.get("tasks", {}).get("timeout_margin", TASK_TIMEOUT_MARGIN))
      self.taskSilenceMargin = int(self.config.get("tasks", {}).get("silence_margin", TASK_SILENCE_MARGIN))
      self.taskSessionCap = int(self.config.get("tasks", {}).get("session_cap", TASK_SESSION_CAP))

      task_cleanup = VodkaAppThread(self.task_cleanup_worker)
      task_cleanup.start()

      self.lib_includes_js = self.config.get("includes",{}).get("js","")
      if self.lib_includes_js:
        self.lib_includes_js = self.lib_includes_js.split(",")
      else:
        self.lib_includes_js = []

      # make sure core lib is always loaded (it's tiny)
      if "base/js/twentyc.core.js" not in self.lib_includes_js:
        self.lib_includes_js.insert(0, os.path.join(self.locationConfig.get("js"), "twentyc.core.js"))
      
      self.lib_includes_css = self.config.get("includes",{}).get("css","")
      if self.lib_includes_css:
        self.lib_includes_css = self.lib_includes_css.split(",")
 
      self.info("%d templates initialized" % (len(self.templates.keys())))
 
      self.info("Running on vodka %s (instance id: %s from %s)" % (version, self.id, socket.gethostname()))

      self.start()


    except Exception, inst:
      self.log.debug(str(inst)+"\n"+traceback.format_exc())
      raise

  #############################################################################

  def start(self):
    self.app_status = 1
    
    t_run = VodkaAppThread(self.run)
    t_run.start()

  #############################################################################

  def run(self):
    while self.app_status == 1:
      self.update_modules();
      time.sleep(1)
    
  #############################################################################

  def stop(self):
    self.app_status = 10
    self.logout_all_sessions()
    self.tasks_terminate()
    if self.xbahn: 
      self.xbahn.stop()

  #############################################################################

  def connect_db(self, id):
    setattr(self, "%s_db" % id, twentyc.database.ClientFromConfig(
      self.couch_engine,
      self.config.get(id),
      id,
      logger=self.log
    ))
 
  #############################################################################

  def connect_xbahn(self):
    xbahn_config = self.config.get("xbahn")
    if xbahn_config and xbahn:
      self.xbahn = xbahn.xBahnThread(
        xbahn_config.get("host"), 
        xbahn_config.get("port"), 
        xbahn_config.get("exchange"), 
        self,
        self.storage,
        username = xbahn_config.get("username"),
        password = xbahn_config.get("password"),
        queue_name = xbahn_config.get("queue_id","vodka"),
        queue_capacity = int(xbahn_config.get("queue_capacity", 50)),
        log=self.log
      )
      self.xbahn.start()
      self.module_manager.xbahn_set(self.xbahn)

      self.xbahn.set_limits(self.config.get("xbahn_limits",{}))

      self.xbahn.listen("__U.*.notify")
      
      # set up required topics
      tpc_vodka_ctrl = self.xbahn.listen("__vodka.control.*")
      if tpc_vodka_ctrl:
        tpc_vodka_ctrl.callbacks.append(self.vodka_control_handler)

      tpc_vodka_xb_req = self.xbahn.listen("__vodka.%s.request" % self.id)
      if tpc_vodka_xb_req:
        tpc_vodka_xb_req.callbacks.append(self.vodka_xbahn_request_handler)

      tpc_vodka_xb_req = self.xbahn.listen("__vodka.ALL.request")
      if tpc_vodka_xb_req:
        tpc_vodka_xb_req.callbacks.append(self.vodka_xbahn_request_handler)

 
      tpc_task_info = self.xbahn.listen("__vodka-task-update.%s.*" % self.id)
      tpc_task_info.config.update(
        {
          "storage_handler" : self.task_update_receiver
        }
      )
     
      self.info("Cleaning up any previous tasks that may still be lingering around")

      self.xbahn.send(None, "__vodka-task-ctrl.%s._ALL_" % self.id, {
        "cmd" : "stop"
      })
 
      # see if any of the loaded mods need to init something
      # on xbahn

      if module_py_components:
        for name in module_py_load_order:
          mod = module_py_components.get(name)
          if hasattr(mod, 'xbahn_init'):
            self.info("%s is hooking into xbahn" % name)
            mod.xbahn_init(self, self.xbahn);

    else:
      self.xbahn = None

  #############################################################################

  def vodka_xbahn_request_handler(self, msg, data):
    
    cmd = data.get("cmd")

    print "Got XBAHN request: %s" % data
    
    try:
      if cmd == "request.ping":
        self.xbahn.respond(msg, 
          { 
            "result" : {
              "id" : self.id, 
              "pid" : os.getpid(),
              "host" : uwsgi.opt.get("socket"),
              "xbahn" : self.xbahn.conn_str
            }
          }
        )
      elif cmd == "request.status":
        self.xbahn.respond(msg, { 
          "result" : self.status_json()
        })
      else:
        kwargs = data.get('kwargs',{})
        type = kwargs.get('type')
        if type:
          cmd = "%s_%s" % (cmd, type)
        if not hasattr(self, cmd):
          raise Exception("Unknown command: %s" % cmd)
        fn = getattr(self, cmd)
        if not fn.xrh_exposed:
          raise Exception("Command %s is not exposed to the xbahn request handler")
        rdata = { "result" : fn(**kwargs) }
        self.xbahn.respond(msg, rdata);
    except Exception, inst:
      self.xbahn.respond(msg, { "status" : "ERR", "alert" : "Vodka Threw Exception(%s): %s" % (inst.__class__.__name__, str(inst))})
      webapp.log.error(traceback.format_exc())

  #############################################################################

  def vodka_control_handler(self, msg, data):
    if msg.subject == "__vodka.control.require_session_map":
      
      # something requires a full update of the session mapping

      self.xbahn.send(
        None, "__vodka.update.session_map", self.session_map
      )

    elif msg.subject == "__vodka.control.reload_modules_for_client":
      self.client_reload_modules(
        data.get("user_id"),
        data.get("modules")
      )

    elif msg.subject == "__vodka.control.unload_modules_for_client":
      self.client_unoad_modules(
        data.get("user_id"),
        data.get("modules")
      )



  #############################################################################

  def client_reload_modules(self, user_id, modules):
    sessions = self.sessions_by_user_id(user_id)

    for ses in sessions:
      if modules:
        old_perms = ses.module_perms
        ses.reload_20c_module_perms()
        for mod, perms in modules.items():
          if ses.check_20c_module(mod) and not self.module_manager.perms_check(old_perms, mod):
            self.log.info("User %s gained access to module %s" % (user_id, mod))
            ses.rce_require(
              "reload.%s" % mod,
              "\n".join([
                "TwentyC.Modules.Load('%s', '%s');" % (mod, self.module_version(mod))
              ])
            )

      else:
        old_perms = ses.module_perms
        ses.reload_20c_module_perms()
        
        modules = self.update_modules()

        for mod, info in modules.items():
          if info.get("access_level", 0) == 0:
            continue
          if not self.module_manager.perms_check(old_perms, mod):
            if ses.check_20c_module(mod):
              self.log.info("User %s gained access to module %s" % (user_id, mod))
              ses.reload_20c_module(mod, self.module_version(mod))
          elif not ses.check_20c_module(mod):
            self.log.info("User %s lost access to module %s" % (user_id, mod))
            ses.unload_20c_module(mod)

      ses.rce_require("reload_perms_to_client", "TwentyC.Modules.LoadModulePerms();")
            
  #############################################################################

  def client_unload_modules(self, user_id, modules):
    sessions = self.sessions_by_user_id(user_id)
    
    for ses in sessions:
      ses.reload_20c_module_perms()
      for mod, perms in modules.items():
        if not ses.check_20c_module(mod):
          self.log.info("User %s lost access to module %s" % (user_id, mod))
          ses.unload_20c_module(mod)

      ses.rce_require("reload_perms_to_client", "TwentyC.Modules.LoadModulePerms();")

  #############################################################################

  def sessions_by_user_id(self, user_id):
    try:
      rv = []
      for sid, ses in webapp.sessionCache.items():
        cl_ses = ses.data.get("client_session")
        if cl_ses and cl_ses.auth_id == user_id: 
          rv.append(cl_ses)
      return rv
    except Exception, inst:
      self.log_error(inst)
    

  #############################################################################

  def log_error(err):
    self.log.error(str(err))
    self.log.error(traceback.format_exc())

  #############################################################################

  def dbg(self, msg):
    msg = "Vodka: %s" % msg
    print msg
    self.log.debug(msg)

  #############################################################################

  def info(self, msg):
    msg = "Vodka: %s" % msg
    print msg
    self.log.info(msg)

  #############################################################################

  def module_version(self, name):
    #if not is_production():
    #  return time.time()
    return self.update_modules().get(name, {}).get("version", version)

  #############################################################################

  def list_modules(self):
    return self.module_js_load_order

  #############################################################################

  def modules_at_path(self, dir):
    """
    returns a list of valid vodka modules that exist at path"
    """

    rv = {}
    for mod in os.listdir(dir):
      if mod[0] in [".","_"] or mod in ["config"]:
        continue
      path = os.path.join(dir,mod)
      if not os.path.isdir(path):
        continue
      rv[mod] = path

    return rv


  #############################################################################

  def is_module_loaded(self, modid):
    """
    Returns whether the specified module has been loaded from any source
    """

    return self.module_status.get(modid,{}).get("source")

  #############################################################################

  def load_modules_from_disk(self):
    
    # see what directories to scan for modules
    dirs = self.config.get("module_directories", {})

    all_instructions = {}

    # preload module instructions for all module sources specified in the config
    for name, dir in dirs.items():
      
      # read module instructions 
      instructions_path = os.path.join(dir, "vodka_import.json")
      if not os.path.exists(dir):
        self.info("Specified module directory for '%s': %s DOES NOT EXIT" %(name,dir))
        continue

      if not os.path.exists(instructions_path):
        self.info("No module instructions found for %s, skipping" % dir)
        continue
        
      f = open(instructions_path, "r")
      instructions = jsonlib.loads(f.read())
      f.close()

      # make sure a module name space is defined in the instructions
      namespace = instructions.get("namespace")
      if not namespace:
        self.info("No module namespace defined in %s, skipping" % instructions_path)
        continue

      all_instructions[name] = instructions

      for mod, path in self.modules_at_path(dir).items():
        self.module_status["%s.%s" % (namespace, mod)] = {
          "path" : path
        }

    self.disk_module_instructions = all_instructions


    # load modules from all directory sources specified in the config
    for name, dir in dirs.items():
   
      # only proceed if there are module instructions in the directory
      instructions = all_instructions.get(name)
      if not instructions:
        continue

      namespace = instructions.get("namespace")

      # require global module dependencies specified in the instructions
      # if any
      
      if instructions.get("_dependencies"):
        for dep in instructions.get("_dependencies"):
          self.load_module_dependency(dep, "%s modules" % namespace)

      # cycle through directories in the source location, and load
      # any valid vodka module we find
      for mod, path in self.modules_at_path(dir).items():
        mod_id = "%s.%s" % (namespace, mod)
        # load the module from the disk
        if os.path.isdir(path):
          self.load_module_from_disk(mod_id, path, instructions)


  #############################################################################

  def load_module_dependency(self, mod_id, reason=""):
    # if module is already loaded from elsewhere, bail
    if self.is_module_loaded(mod_id):
      return
 
    path = self.module_status.get(mod_id, {}).get("path")
    if path:
      # module is loaded from disk
      if not self.is_module_loaded(mod_id):
        self.info("Loading dependency from disk: %s from %s for %s" % (mod_id, path, reason))
        self.load_module_from_disk(
          mod_id, 
          path, 
          self.disk_module_instructions.get(mod_id.split(".")[0])
        )
    else:
      # module is loaded from database
      rv = self.load_module(mod_id)
      if not rv:
        raise Exception("Could NOT load module dependency: %s for %s" % (mod_id, reason))
      else:
        self.info("Loading dependency from couchdb: %s for %s" % (mod_id, reason))

  #############################################################################

  def load_module_from_disk(self, mod_id, path, instructions):

    """
    Load the specified module from disk
    """

    # if module is already loaded from elsewhere, bail
    if self.is_module_loaded(mod_id):
      return
   
    a = mod_id.split(".")
    namespace = a[0]
    mod = ".".join(a[1:])
    
    # get loading instructions for module
    mod_instructions = instructions.get(mod, {})

    # dependencies of this module
    dep = mod_instructions.get("dependencies",[])

    # dont load the module if its disabled via config
    if mcfg.get(mod_id) == "disabled" or mcfg.get(namespace) == "disabled":
      return
 
    # load dependency modules
    if dep:
      for d in dep:
        self.load_module_dependency(d, mod_id)

    js = ""
    namespace = mod_id.split(".")[0]
    has_js = False
    if os.path.isdir(path):
      self.info("Loading module from directory: %s, %s" % (mod_id,path))

      # add module to module status
      self.module_status[mod_id] = {
        "version" : instructions.get("version", version),
        "access_level" : int(mod_instructions.get("access_level", 0)),
        "dependencies" : dep,
        "status" : 1,
        "source" : "disk",
        "path" : path,
        "mobile" : mod_instructions.get("mobile",False)
      }

      # load preferences validators for this module
      if os.path.exists(os.path.join(path, "prefs.json")): 
        validator.add_from_file(os.path.join(path,"prefs.json"))

      # load template components of this module
      if os.path.exists(os.path.join(path, "tmpl")):
        tmpl_path = os.path.join(path, "tmpl")
        for file in os.listdir(tmpl_path):  
          
          if file[0] == ".":
            continue

          tmpl_file_path = os.path.join(tmpl_path, file)
          
          if os.path.isdir(tmpl_file_path):
            # themed template
            for t_file in os.listdir(tmpl_file_path):
              
              if t_file[0] == ".":
                continue
              self.templates["%s.%s.%s" % (mod_id,file,t_file)] = [os.path.join(tmpl_file_path, t_file), "r"]
          else: 
            # themeless template
            self.templates["%s.%s" % (mod_id, file)] = [tmpl_file_path, "r"]

      
      # load python components of this module
      for file in os.listdir(path):
        if re.match(".*\.py$", file) and file not in ["__init__.py"]:
          mod_path = os.path.join(path, file)
          f = open(mod_path, "r")
          code = f.read()
          f.close()
          
          mod_sysid = re.sub("[^a-zA-Z0-9_]","_",mod_id)
          pymod = imp.new_module(mod_sysid)
          sys.modules[mod_sysid] = pymod

          exec code in pymod.__dict__
          module_py_components[mod_id] = pymod
          module_py_load_order.append(mod_id)
        elif re.match(".*\.js$", file) and not re.match("^_min_\.", file) and not file in twentyc.vodka.tools.module_manager.javascript_parts:
          self.module_status[mod_id]["path_js"] = os.path.join(path, file)
          has_js = True

      if has_js:
        module_js_load_order.append(mod_id)

  #############################################################################

  def load_modules(self):
   
    """
    Load modules using the vodka module manager connected to a database
    (database, couchdb)
    """
    

    t1 = time.time()
    if self.module_manager:
      man = self.module_manager
      try:
        modules = man.module_index().get("modules")
      except Exception,inst:
        self.info("!!!!!!! Did you forget to run cli/update_design.py after your last vodka update?")
        raise

      for name, data in modules.items():
        if mcfg.get(name) != "disabled":
          self.load_module(name)
    print "Modules loaded from database in %.5f" % (time.time() - t1)

  #############################################################################

  def load_module(self, name):
    
    """
    load the specified vodka module using the module manager
    """

    if not self.module_manager:
      return

    mod_id = name
    man = self.module_manager
    a = name.split(".")
    namespace = a[0]
    mod_name = ".".join(a[1:])
     
    # if module namespace is disabled in config, bail
    if mcfg.get(namespace) == "disabled" or mcfg.get(mod_id) == "disabled":
      return

    info = man.module_info(namespace, mod_name)

    if info:
          
      # if module has already been loaded from disk, give priority to that
      # and skip this.

      if self.is_module_loaded(name):
        return True

      # if module has dependencies, load those first - assuming they havent been loaded yet

      if info.get("dependencies"):
        for dependency in info.get("dependencies"):
          self.load_module_dependency(dependency, name)
#          if not self.is_module_loaded(dependency):
#            print "Dependency for %s: %s" % (name, dependency)
#            self.load_module(dependency)

      self.info("Loading module from %s: %s" % (self.couch_engine, name))

      # make entry in module_status

      self.module_status[mod_id] = {
        "version" : info.get("version"),
        "access_level" : int(info.get("access_level", 0)),
        "dependencies" : info.get("dependencies", []),
        "source" : "manager",
        "status" : info.get("status"),
        "path" : None,
        "mobile" : info.get("mobile", False)
      }


      # module info is loaded, import any module components of it
      imports = man.module_import(namespace, mod_name)
      for comp_name,mod in imports.items():
        mod._module_from_database = name
        module_py_components["%s.%s"%(name, comp_name)] = mod
        module_py_load_order.append("%s.%s"%(name, comp_name))

      # load templates
      self.templates.update(man.module_templates(namespace, mod_name))
          
      # load validator json for this module
      validator_code = man.module_validator_code(namespace, mod_name)
      if validator_code:
        validator.add_from_json(validator_code)

      module_js_load_order.append(mod_id)

      return True


    else:
      self.info("No valid module data found for %s, skipping" % name)
      return False



  
  #############################################################################
  # load brands from dipatch.conf

  def load_dispatch(self):
    
    """
    load dispatch config (brands, locale etc) so they can later
    be picked by the sessions
    """
    
    # load dispatch config

    config = self.config

    self.brand = {}
    self._brand_map = {}
    self._locale = {}
    self._theme_map = {}

    # load default brand
    self.brand["default"] = dict(config.get("brand.default"))
    self.brand["default"]["locale"] = self.get_locale(self.brand["default"]["lang"])
    self.brand["default"]["name"] = "default"

    def init_brand(brand):
      section = "brand." + brand
      bd = dict(self.brand["default"])

      if config.has_key(section):
        print "loading " + section
        for k,v in config.get(section).items():
          bd[k] = v
        bd["locations"] = config.get(section).get("locations","")
        if bd["locations"]:
          bd["locations"] = bd["locations"].split(",")

      if not os.path.isdir(bd["dir"]):
        raise Exception("Brand directory not found: %s (absolute path required)" % bd["dir"])

      bd["name"] = brand
      bd["locale"] = self.get_locale(bd["lang"])

      webapp.url_map.append(
        ("/%s-favicon.ico" % brand, "%s/htdocs/favicon.ico" % bd["dir"]),
      )
      webapp.url_map.append(
        ("/%s/brands/%s" % (version, brand), "%s/htdocs" % bd["dir"], "%s/htdocs" % self.brand["default"].get("dir"))
      )

      return bd

    init_brand("default")

    for brand,regex in config.get("brand_map").items():
      self._brand_map[brand] = re.compile(regex)
      self.brand[brand] = init_brand(brand)

    #for k,v in self.brand.items():
    #  print "FF " + k + " : " + str(v)

    for name, regex in config.get("theme_map").items():
      self._theme_map[name] = re.compile(regex)


  #############################################################################

  def prepare_request(self, request, environ):
    
    """
    prepare request
    unline handle request this is fired before path dipatch
    """
    ses = self.get_session(request)


  #############################################################################
  # handle request

  def handle_request(self, request, environ):
    
    """
    handle incoming http request
    sets the request property of the user's session
    """

    ses = self.get_session(request)

    csrf = webapp.get_cookie(request, "csrftoken");

    if not csrf:
      secure = (self.config.get("session").get("cookie_secure", "no") == "yes")
      csrfCookie = SimpleCookie()
      csrfCookie['csrftoken'] = str(webapp.uuid.uuid4()).replace('-', '')
      csrfCookie['csrftoken']['path'] = "/"
      if secure:
        csrfCookie['csrftoken']['secure'] = True
      request['cookies_out']["csrftoken"] = csrfCookie;

    self.http_requests += 1
    self.http_requests_total += 1

  ############################################################################
  # clean up request

  def cleanup_request(self, request, environ):
    return

  #############################################################################
  # get session object

  def get_session(self, request):

    """
    Return the session object for the user the request
    """
    sesContainer = request.get("session")
    #print "Using session " + str(sesContainer.id)
    if not sesContainer.data.has_key("client_session"):
      sesContainer.data["client_session"] = session.Session(self, request, sesContainer.id)
    return weakref.proxy(sesContainer.data.get("client_session"))


  ##############################################################################

  def template_response(self, name, **kwargs):
    req = kwargs.get("__request")
    ses = self.get_session(req)
    return ses.tmpl(name, request=req, **kwargs)

  ##############################################################################

  def extend(self, name, method):
    setattr(self, name, new.instancemethod(method, self, VodkaApp))
  
  ##############################################################################
  
  def get_locale(self, lang):
    # ref locale objects
    if lang not in self._locale:
      self._locale[lang] = locale.Locale(lang)
      self._locale[lang].htmlescape()
    return self._locale[lang]
  
  ##############################################################################

  def authed_session(self, request):
    
    """
    check if the request holds an authenticated session object

    Return session object on success else
    raise a HTTPRedirect to the login page
    """
    
    ses = self.get_session(request)
    if ses.is_authed():
      return ses

  ##############################################################################

  def update_modules(self):
    now = time.time()
    if not self.module_status_time or now-self.module_status_time > 10:
      self.module_status_time = now
      s = self.module_manager.module_index()

      # module manager returned empty module list, bail
      # before bailing unload all old modules that had been
      # loaded from manager before
      if not s:
        for i, mod in self.module_status.items():
          if mod.get("source") == "manager":
            del self.module_status[i]
        return self.module_status

      for k, mod in s.get("modules").items():

        if self.is_module_loaded(k):

          old = self.module_status.get(k)
          
          # check if module is loaded from disk already, if it is, bail

          if old.get("source") == "disk":
            continue

          
          # mod has already been loaded into vodka, but a new version is available
          
          if old.get("version") != mod.get("version") or old.get("status") != mod.get("status"):
            self.info("Mod version or status change for '%s' : %s" % (k, mod.get("version")))

            modstat = { 
              "version" : mod.get("version"),
              "mobile" : mod.get("mobile", 0),
              "status" : mod.get("status"),
              "dependencies" : mod.get("dependencies", []),
              "source" : "manager",
              "access_level" : mod.get("access_level", 0),
              "path" : None
            }
 

            # load validator json for this module
            validator_code = self.module_manager.module_validator_code(mod.get("namespace"), mod.get("name"))
            if validator_code:
              validator.add_from_json(validator_code)

            self.module_status[k] = modstat

            # reload templates
            self.templates.update(self.module_manager.module_templates(mod.get("namespace"), mod.get("name")))


        else:
          # mod has not beenm loaded into vodka yet, load it.
      
          # if module namespace is disabled in config, bail
          if mcfg.get(mod.get("namespace")) == "disabled":
            continue

          # if module is disabled
          if mcfg.get(k) == "disabled":
            continue

          # if module not approved yet
          if not mod.get("status"):
            continue

          self.info("New vodka mod discovered: %s, loading ..." % k)
          self.load_module(k)

      # finally find any modules that have been removed
    
      for k, mod in self.module_status.items():
        if not mod.get("source") == "manager":
          continue
        if not s.get("modules").get(k):
          self.info("Module %s has been removed from database, unloading" % k)
          del self.module_status[k]

    return self.module_status

  #############################################################################

  def clear_headers(self, request, keys):
    headers = request.get("headers")
    i = 0
    l = len(headers)

    while i < l:
      header = headers[i][0]
      if header.lower() in keys:
        headers.remove(headers[i])
        i = 0
        l = len(headers)
        continue
      i += 1


  #############################################################################

  @webapp.expose
  def module_media(self, mod_name, version, file, **kwargs):
    req = kwargs.get("__request")
    environ = kwargs.get("__environ")

    ses = self.get_session(req)
    
    if not self.module_manager:
      return ""

    man = self.module_manager

    if not re.match("^appstore.", file):
      if not ses.check_20c_module(mod_name) & ACCESS_READ:
        return "";

    if not self.is_module_loaded(mod_name):
      raise webapp.HTTPError(404)

    full_name = mod_name
    mod_name = mod_name.split(".")
    namespace = mod_name[0]
    name = ".".join(mod_name[1:])

    info = man.module_info(namespace, name)
    modstat = self.module_status.get(full_name)

    maxAge = 36000
    fromDisk = False
 
    if not info or modstat.get("path_js"):
      path = modstat.get("path_js")
      path = os.path.dirname(path)
      path = os.path.join(path, "media", file);
      print "Checking path: %s" % path
      if path and os.path.exists(path):
        self.clear_headers(req, ["pragma","cache-control","content-type"])
        mtime = webapp.formatdate(os.path.getmtime(path))
        fromDisk = True
      else:
        raise webapp.HTTPError(404)
    else:
      self.clear_headers(req, ["pragma","cache-control","content-type"])
      mtime = webapp.formatdate(info.get("modified"))
 
    headers = req.get("headers")
    cacheHeaders = [
      ("Pragma", "cache"),
      ("Cache-Control", "max-age=%d, must-revalidate" % maxAge)
    ]

    #check if file has been modified and send cache response
    #if possible

    if environ.get('HTTP_IF_MODIFIED_SINCE') == mtime:
      headers.extend(cacheHeaders)
      req["status"] = 304 
      return ""

    headers.append(("Last-Modified", mtime))
    mime = "text/plain"

    if not fromDisk:
      contents = man.module_media_content(namespace,name, file);
      comp = man.module_component(namespace,name, file)
      mime = str(comp.get("mime")[0])
    elif path:
      f = open(path, "r")
      contents = f.read()
      f.close()
      mime = mimetypes.guess_type(path)[0]

    headers.extend([
      ("content-type", mime)
    ])


    return contents


  #############################################################################

  def module_javascript_component(self, mod_name, comp="unload.js"):

    """
    Return a module's javascript component that isnt part of the 
    module main javascript, such as the module unload script
    """
    
    if not self.is_module_loaded(mod_name):
      return

    modstat = self.module_status.get(mod_name)
    
    if modstat.get("path_js"):
      # from disk

      path = os.path.join(
        os.path.dirname(modstat.get("path_js")),
        comp
      )

      if not os.path.exists(path):
        return ""
      f = open(path, "r")
      code = f.read()
      f.close()
      return code

    else:
      # from cb
      man = self.module_manager
      namespace, name = man.module_token(mod_name)

      minified = self.config.get("modules",{}).get("minified")
      if (is_production() and minified != "no") or minified == "yes":
        minified = True
      else:
        minified = False

      scr = man.module_component(namespace, name, comp)
      if scr:
        if minified:
          return scr.get("minified")
        else:
          return scr.get("contents")

    return ""

  #############################################################################
  # return code for remote code execution
  # this data wont be cached ever
  # RCE is currently primarily used to unload modules on the client side
  # after the client no longer has access to them (perms revoked)

  @webapp.expose
  def rce(self, rce_name, **kwargs):
    
    req = kwargs.get("__request")
    environ = kwargs.get("__environ")

    ses = self.get_session(req)

    # make sure RCE actually exists on session before proceeding
    if not ses.rce.has_key(rce_name):
      return
    
    rce = ses.rce.get(rce_name)

    # prepare code
    code = "\n".join([
      "(function(){",
      "TwentyC.IO.Send(TwentyC.rpcUrl+'/rce_satisfy', {name : '%s', id:'%s'},0,0,0,'POST');" % (rce_name, rce.get("id")),
      rce.get("code"),
      "})();"
    ])
    
    headers = req.get("headers")
    headers.extend([
      ("content-type", "text/javascript")
    ])



    # send code
    return code


  #############################################################################
  # load module javascript
  
  @webapp.expose
  def ui_component(self, mod_name, version, **kwargs):
    
    req = kwargs.get("__request")
    environ = kwargs.get("__environ")

    ses = self.get_session(req)
    
    if not self.module_manager:
      return ""

    if not self.is_module_loaded(mod_name):
      raise webapp.HTTPError(404)

    man = self.module_manager
    if not ses.check_20c_module(mod_name) & ACCESS_READ:
      raise webapp.HTTPError(401)
    
    full_mod_name = mod_name
    mod_name = mod_name.split(".")
    namespace = mod_name[0]

    name = ".".join(mod_name[1:])
    info = man.module_info(namespace, name)
    modstat = self.module_status.get(full_mod_name)

    maxAge = 36000
    path = None

    minified = self.config.get("modules",{}).get("minified")
    if (is_production() and minified != "no") or minified == "yes":
      minified = True
    else:
      minified = False

    fromDisk = False

    if info and info.get("status") == 0:
      return "// Module is currently deactivated"
 
    if not info or modstat.get("path_js"): 
      path = modstat.get("path_js")
      if minified:
        bname = os.path.basename(path)
        dname = os.path.dirname(path)
        path = os.path.join(dname, "_min_.%s" % bname)
      if path and os.path.exists(path):
        self.clear_headers(req, ["pragma","cache-control","content-type"])
        mtime = webapp.formatdate(os.path.getmtime(path))
        fromDisk = True
      else:
        raise webapp.HTTPError(404)
    else:
      self.clear_headers(req, ["pragma","cache-control","content-type"])
      mtime = webapp.formatdate(info.get("modified"))
 
    headers = req.get("headers")
    headers.extend([
      ("content-type", "text/javascript")
    ])

    cacheHeaders = [
      ("Pragma", "cache"),
      ("Cache-Control", "max-age=%d, must-revalidate" % maxAge)
    ]

    #check if file has been modified and send cache response
    #if possible

    if environ.get('HTTP_IF_MODIFIED_SINCE') == mtime:
      headers.extend(cacheHeaders)
      req["status"] = 304 
      return ""

    headers.append(("Last-Modified", mtime))

    code = "(function() {\n"
    code += "var __MODULE_VERSION='%s';\n" % self.module_version(full_mod_name)
    code += "var __MODULE_NAME='%s';\n" % full_mod_name
   
    if not fromDisk:
      code += man.module_javascript(namespace,name,minified=minified)
    elif path:
      f = open(path, "r")
      code += f.read()
      f.close()
 
    code += "\nTwentyC.Modules.loaded['%s.%s'] = { version : '%s' };" % (namespace,name,version)
    code += "\n})()"

    return code

  #############################################################################
  # path: /dbg_refcount

  @webapp.expose
  def dbg_refcounts(self, **kwargs):
    
    """
    return serialized representation of objects and their refcounts
    """
   
    req = kwargs.get("__request");
    if self.statusKey not in kwargs:
      raise webapp.HTTPError(404)

    if not "ses" in kwargs: 
      d = {}
      sys.modules
      # collect all classes
      for m in sys.modules.values():
          for sym in dir(m):
              o = getattr (m, sym)
              if type(o) is types.ClassType:
                  d[o] = sys.getrefcount (o)
      # sort by refcount
      pairs = map (lambda x: (x[1],x[0]), d.items())
      pairs.sort()
      pairs.reverse()
      return str(pairs)
    else:
      import gc
      ses = webapp.sessionCache[kwargs.get("__request").get("session").id];
      r = "Reference count for this session object: %d\n\n" % sys.getrefcount(ses)
      r += self.dbg_refs(ses, [], max=int(kwargs.get("max",1)), show_frame=kwargs.get("show_frame"))
      gc.collect()
      return r
        
  def dbg_refs(self, obj, n, max=3, show_frame=None):
    import gc
    r = ""
    i = 0

    if len(n) > max: 
      return ""
    
    refs = gc.get_referrers(obj)

    for ref in refs:
      if i > 5:
        break
      if ref == obj:
        continue
      if str(type(ref)) == "<type 'frame'>" and not show_frame:
        continue
      i+=1
      r += "".center(len(n),"\t")+"%s\n" % (type(ref))
      n.append(1)
      r += self.dbg_refs(ref, n, max)
      n.pop()

    return r


  ##############################################################################
  # play custom uploaded sound

  @webapp.expose
  def playsound(self, **kwargs):

    """
    Send a soundfile response
    """

    req = kwargs.get("__request")
    ses = self.authed_session(req)

    sound = kwargs.get('sound')
    if sound:
      customSounds = ses.pref_manager.get("sounds")
      if customSounds.get(sound):
        headers = req.get("headers")
        headers.extend([
          ("content-type", "audio/mpeg")
        ])
        return base64.b64decode(customSounds.get(sound))
      else:
        sounds = ses.app.config.get("sounds",{})
        if sounds.get(sound):
          raise webapp.HTTPRedirect("/base/sound/"+sounds.get(sound).strip("'"))
        else:
          raise Exception("Invalid sound id")
    else:
      raise Exception("No Sound Specified")

  #############################################################################

  @webapp.expose
  def index(self, **kwargs):
    ses = self.get_session(kwargs.get("__request"))
    return ses.tmpl("index.tmpl", request=kwargs.get("__request"))

  #############################################################################

  def status_json(self):
    return { 
      "app_status" : self.app_status,
      "status" : "OK"
    }

  #############################################################################

  @bartender.expose
  def toggle_profile_requests(self, **kwargs):
    if kwargs.get("state") == "on":
      self.profiling_wsgi = True
    else:
      self.profiling_wsgi = False
    application.profile = self.profiling_wsgi
    webapp.WSGI_PROFILING = self.profiling_wsgi
    return { "state" : self.profiling_wsgi }

  #############################################################################

  @bartender.expose
  def profile_json_requests(self, **kwargs):
    rv = {}
    if self.profiling_wsgi:
      
      rv = { "overview" : [], "recent" : []}

      #overview
      overview = rv["overview"]
      lst = webapp.profile.get("overview").items()
      lst = sorted(lst, key=lambda p: p[1].get("num"), reverse=True)
      for path, profile in lst:
        data = {"num" : profile.get("num"), "path":path}
        data.update(profile.get("time"))
        overview.append(data)

      #recent requests
      lst = webapp.profile.get("recent")
      recent = rv["recent"]
      for entry in lst:
        times = entry.get("time")
        times['path'] = entry.get("path")
        recent.append(times)
    else:
      
      rv["alert"] = "Request profiling is not turned on"

    return rv

  #############################################################################

  @webapp.expose
  def status(self, **kwargs):
    req = kwargs.get("__request");
    if self.statusKey not in kwargs:
      raise webapp.HTTPError(404)

    status = "OK"


    show_profile = kwargs.has_key("profile")
    show_debugging = kwargs.has_key("debug")
    show_tasks = kwargs.has_key("tasks")

    # General information about user requests

    n = 0
    r = "%s\n<pre>%d user requests/sec\n%s user requests (total)\n\n" % (
      status,
      self.http_requests_prev,
      self.http_requests_total
    )

    # Debugging information
    if show_debugging:
      r += "\n\nClient Pool Size: BUSY: %d, IDLE: %d" % (len(self.client_pool.busy), len(self.client_pool.pool))

      if self.debugging:
        r += "\nBusy clients requested by:"
        for client in self.client_pool.busy:
          r += "\n%s: %s" % (client.id, client.requested_by)

    # WSGI Request profiling

    if self.profiling_wsgi and show_profile:
      r += "\n\nWeb Sessions: %d" % len(webapp.sessionCache.keys()) 
      r += "\n\nTotal Time spent on http requests\n"
      r += "<table style=\"width:100%; text-align:left;\">"
      lst = webapp.profile.get("overview").items()
      lst = sorted(lst, key=lambda p: p[1].get("num"), reverse=True)
      headers = False
      for path, profile in lst:
        if not headers:
          headers = profile.get("time").keys() 
          r += "<tr><th>Path</th><th>Num</th></td>"
          for handler in headers:
            r+= "<th>%s</th>" % handler
          r += "</tr>"
          
        r += "<tr><td>%s</td><td>%d</td>" % (path, profile.get("num"))
        for handler in headers:
          r += "<td>%f</td>" % (profile.get("time").get(handler, 0.0))
        r += "</tr>"
      r += "</table>"

      r += "\n\nMost recent requests\n"
      r += "<table style=\"width:100%; text-align:left;\">"
      lst = webapp.profile.get("recent")
      headers = False
      for entry in lst:
        path = entry.get("path"),
        times = entry.get("time")

        if not headers:
          headers = times.keys() 
          r += "<tr><th>Path</th></td>"
          for handler in headers:
            r+= "<th>%s</th>" % handler
          r += "</tr>"
          
        r += "<tr><td>%s</td>" % (path)
        for handler in headers:
          r += "<td>%f</td>" % (times.get(handler, 0.0))
        r += "</tr>"
      r += "</table>"


      r += str(webapp.profile.get("longest"))

    # Task list
    if show_tasks:
      r += "\n\nTasks"
      for id, task in self.tasks.items():
        r += "\nID: %s OWN: %s PS: %s INFO: %s R: %s CMD: %s %s %s" % (
          id, 
          task.get("owner"),
          task.get("process").poll(), 
          task.get("info"),
          str(type(task.get("result"))).replace("<","").replace(">",""),
          task.get("module"),
          task.get("task"),
          task.get("params")
        )

    r += "</pre>"

    return r

  #############################################################################

  def update_sesmap(self, data):
    
    if not hasattr(self, "lockSesmap"):
      self.lockSesmap = threading.Lock()

    self.lockSesmap.acquire()
    try:
      self.log.debug("Updating session map (cache)")
      self.session_map.update(data)
      
      for sid, status in data.items():
        if not status:
          del self.session_map[sid]

      if self.xbahn:
        self.log.debug("Updating session map (xbahn)")
        self.xbahn.send(None, "__vodka.update.session_map", data)
        self.log.debug("Update session map (xbahn) COMPLETED")

    finally:
      self.lockSesmap.release()
    

  #############################################################################

  def logout_all_sessions(self):
    pass
  
  #############################################################################

  def task_update_receiver(self, xb, msg, data):
    if type(data) == dict:
      self.task_info_receiver(xb, msg, data)
    else:
      self.task_result_receiver(xb, msg, data)

  #############################################################################

  def task_info_receiver(self, xb, msg, data):
    id = msg.subject.split(".")[-1]
    #self.log.debug("Received task info %s: %s" % (id, data))
    if self.tasks.has_key(id):
      info = self.tasks[id].get("info",{})
      if info.get("owner") and info.get("owner") not in webapp.sessionCache.keys():
        webapp.log.info("Ignoring task info since the owning user session is no longer a round")
        return self.task_cleanup(id)
      else:
        self.tasks[id]["info"].update(data)
        self.tasks[id]["info"].update(update_t=time.time())
        if self.tasks[id]["info"].get("status") == vodkatask.FINISHED:
          if self.tasks[id].get("callback"):
            d = VodkaAppThread(self.tasks[id]["callback"])
            d.start(self.task_result(id), self, id)


  #############################################################################

  def task_result_receiver(self, xb, msg, data):
    id = msg.subject.split(".")[-1]
    if self.tasks.has_key(id):
      task = self.tasks.get(id)
      task["info"].update(update_t=time.time())
      #self.log.debug("got task result data: %s" % msg.subject)
      if not task.get("result"):
        task["result"] = data
      else:
        existing = task.get("result")
        if type(data) == list and type(existing) == list:
          existing.extend(data)
        else:
          existing.update(data)
    
  #############################################################################

  def task_info(self, id):
    return self.tasks.get(id, {}).get("info")

  #############################################################################

  def task_result(self, id):
    data = self.tasks.get(id, {}).get("result")
    if data:
      del self.tasks[id]["result"]
    return data

  #############################################################################

  def task_cleanup_worker(self):
    while webapp.serverStatus != webapp.SERVER_SHUTTING_DOWN:
      t = time.time()
      cleanup = []
      for id, task in self.tasks.items():
        info = task.get("info",{})
        if info.get("status") == vodkatask.FINISHED:
          if not task.get("result") and t-info.get("end_t",0) > 60:
            self.log.debug("Removing task %s because it is finished and its result has been retrieved" % id)
            cleanup.append(id)
          elif t-info.get("end_t", t) > self.taskCleanupMargin:
            self.log.debug("Removing task %s because it is finished and result has not been requested in time (%d seconds)" % (id, self.taskCleanupMargin))
            cleanup.append(id)
        elif t-info.get("start_t", 0) > self.taskTimeoutMargin:
          self.log.debug("Removing task %s because it did not finish before timeout margin was up (%d seconds)" % (id, self.taskTimeoutMargin))
          self.task_terminate(id)
          info.update(zombie=True, end_t=t, status=vodkatask.FINISHED, error="Terminated: task timed out")
        elif t-info.get("update_t", 0) > self.taskSilenceMargin:
          self.log.debug("Removing task %s because it was silent for too long (> %d seconds)" % (id, self.taskSilenceMargin))
          self.task_terminate(id)
          info.update(zombie=True, end_t=t, status=vodkatask.FINISHED, error="Terminated: task unresponsive")

      for id in cleanup:
        self.task_cleanup(id)

      time.sleep(1)

  #############################################################################

  def task_cleanup(self, id):
    task = self.tasks.get(id)
    if not task:
      return
    info = task.get("info")
    if info:
      if task.get("owner"):
        ses = webapp.sessionCache.get(task.get("owner")).data.get("client_session")
        ses.tasks.remove(id)

    try:
      del self.tasks[id]
    except:
      pass

  #############################################################################

  def tasks_terminate(self):
    tasks = self.tasks.items()
    self.info("Terminating tasks %s" % tasks)
    for id, task in tasks:
      self.task_terminate(id)

  #############################################################################

  def task_terminate(self, id):
    if self.tasks.has_key(id):
      task = self.tasks[id]
      self.info("Terminating task %s" % id)
      try:
        proc = task.get("process")
        if proc and proc.pid:
          os.kill(int(proc.pid), signal.SIGTERM)
          if not proc.poll():
            os.kill(int(proc.pid), signal.SIGKILL)
      except Exception, inst:
        self.log.error(traceback.format_exc())
      

  #############################################################################

  def task_run(self, moduleName, taskName, id="task", params={}, target="download", filename=None, ses=None, limitResult=0, source="unknown", callback=None):

    id = "%s-%s" % (id, str(webapp.uuid.uuid4()))
    params = jsonlib.dumps(params)
    cmd = [
      "python",
      os.path.join(vodkaPath, "task.py"),
      moduleName,
      taskName,
      self.id,
      id,
      "--config",
      serverConfPath,
      "--param",
      params
    ]

    if limitResult:
      cmd.extend(["--limit", str(limitResult)])

    
    p = subprocess.Popen(cmd, close_fds=True)

    if ses:
      owner = ses.client_id
    else:
      owner = None

    print "%s runtask:%s" % (p.pid, cmd)
    self.tasks[id] = {
      "owner" : owner,
      "process" : p,
      "callback" : callback,
      "module" : moduleName,
      "task" : taskName,
      "params" : params,
      "info" : {
        "id" : id,
        "source" : source,
        "start_t" : time.time(),
        "update_t" : time.time(),
        "filename" : filename,
        "target" : target
      }
    }
    print "%s" % self.tasks.keys()
    

    return (id, p)


###############################################################################
# ClientPool
###############################################################################

class ClientPool:
  
  """
  ClientPool holds a pool of VodkaClients which each can hold connections to databases
  and so forth.

  Makes client usage thread-safe
  """

  idx = 0

  def __init__(self, size, app, idstr="pooled_%d"):
    
    """
    Initialize ClientPool

    size should be the amount of initial connections in the pool, needs
    to be >= 1

    app needs to be a reference to the VodkaApp Instance

    idstr will be the prefix for the client id
    """
    
    if size < 1:
      raise Exception("Client Pool size needs to be at least 1")

    i = 0
    self.busy = []
    self.pool = []
    self.app = app
    self.base_size = size

    while i <= size:
      self.pool.append(self.app._Client(
        idstr % i,
        pool = self,
        app = self.app
      ))
      i += 1

    self.idx = i


  #############################################################################

  def get_client(self, for_duration=10):

    """
    Return the first client in the pool that is currently not in use.
    Also respawn any clients that have timed out

    for_duration <int> 10 - claim the client for n seconds, if it is not returned
    within the alloted time it will be timed out and respawned
    """

    t = time.time()
    r = None

    self.respawn_timed_out(t)

    
    if self.pool:
      i = 0
      for r in self.pool:
        if r.status == 2 and r.client:
          self.pool.pop(i)
          break

          r.connect()
        #r = self.pool.pop() 
        r = None
        i += 1

    # no connected client could be obtained, create a new
    # client object and connect it
    if not r:
      r = self.app._Client(
        "pooled_%d" % self.idx,
        pool = self,
        app = self.app,
      )
      self.idx += 1

    # if debugging is on find out what requested the client and log it
    if self.app.debugging:
      r.requested_by = []
      for row in inspect.stack():
        r.requested_by.append((row[3], row[2]))
      self.app.log.debug("Client '%s' requested by %s" % (r.id, r.requested_by))

    self.busy.append(r)
    r.last_request = []

    r.for_duration = t
    r.time = t
    return r
  
  ############################################################################
  # cycle through busy clients and find those that are older than
  # 1 minute, meaning they have timed out, never been used

  def respawn_timed_out(self, t):
    for client in self.busy:
      if t - client.time > client.for_duration:
        if webapp.log:
          if not client.last_request or client.last_request[0] != "login":
            webapp.log.debug("%s: %s has TIMED OUT, attempting to remove/respawn" % (
              client.id,
              client.last_request
            ))
          elif client.last_request and client.last_request[0] == "login":
            webapp.log.debug("%s: %s has TIMED OUT, attempting to remove/respawn" % (
              client.id,
              client.last_request[0]
            ))
            
        try:
          client.disconnect()
          self.busy.remove(client)
          
          if client.client and client.client.transport.isOpen():
            client.client.transport.close()

          client.connect()

          if self.app.debugging:
            client.requested_by = None
 
          self.pool.append(client)

          if webapp.log:
            webapp.log.debug("%s respawned after timeout" % client.id)
        except Exception, inst:
          webapp.log.error("Client Pool Cleanup Error: "+traceback.format_exc())

  #############################################################################
  # respawn client

  def respawn(self, client):
    
    """
    Respawn client, remove client from busy list
    """
    
    try:
      self.busy.remove(client)
    except:
      pass
    if not client in self.pool:
      
      busy = len(self.busy)
      pool = len(self.pool)

      if not busy and pool > self.base_size:
        client.disconnect()
        webapp.log.debug("retired: %s (%d free, %d busy)" % (client.id, pool, busy))
      else:
        if self.app.debugging:
          client.requested_by = None
        self.pool.append(client)
        if webapp.log:
          webapp.log.debug("respawned: %s (%d free, %d busy)" % (client.id, pool, busy))

  #############################################################################
  # reconnect all clients

  def reconnect(self):
    
    """
    Reconnect all clients in the pool,
    and remove all clients from the busy list
    """
    
    self.pool.extend(self.busy)
    self.busy = []
    for client in self.pool:
      client.connect()
  
  #############################################################################
  # disconnect all

  def disconnect(self):
    
    """
    Disconnect all clients in the pool and clear busy list
    """

    self.pool.extend(self.busy)
    self.busy = []
    for client in self.pool:
      client.disconnect()
    self.pool = []

###############################################################################
# VodkaClient
###############################################################################

class VodkaClient(object):
  
  """
  Vodka client base class
  """

  def __init__(self, id="VodkaClient", pool=None, app=None, timeout=None):
    
    self.config = webapp.configs.get(serverConfPath,{})
    self.id = id
    self.busy = False
    self.timeout = timeout
    self.time = 0
    self.for_duration = 10
    self.status = 0
    self.isMain = False
    self.children = None
    self.db_prefs = None
    self.db_modules = None
    self.pool = pool
    self.app = app
    self.ses_id = ""
    self.lockBusy = threading.RLock()
    self.last_request = []
    
    if module_py_components:
      for name in module_py_load_order:
        mod = module_py_components.get(name)
        if hasattr(mod, 'extend_client'):
          mod.extend_client(self, VodkaClient);

    if app:
      self.db_prefs = app.db_prefs

  def connect(self, *args, **kwargs):
    pass

  def disconnect(self, *args, **kwargs):
    pass


###############################################################################
# Spawn and mount vodka application on root path

def vodka_shutdown():
  app = webapp.app_map["vodka"]
  app.stop()
  webapp.serverStatus = webapp.SERVER_SHUTTING_DOWN

def init():
  App = webapp.register_app(VodkaApp(), "vodka", "")
  webapp.start_plugins(App.config)
  webapp.shutdown_handlers.append(vodka_shutdown)
  
  if serverConf.get("wsgiserver") == "gevent":
    gevent_start_server()
  if serverConf.get("wsgiserver") == "eventlet":
    eventlet_start_server()

