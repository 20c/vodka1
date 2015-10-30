"""
Holds the session class for user authentication and session specific data
storage
"""
################################################################################
################################################################################

import os 
import time
import datetime
import traceback
import logging, logging.handlers
import traceback
import re
import tmplbridge
import random
import weakref
import prefs
import uuid
import task
import simplejson as json
import types

import twentyc.tmpl as tmpl_engine

from twentyc.tools.thread import RunInThread
import twentyc.vodka.tools.session as vt_session

from rpc import RPC_JSON_KEYS
from wsgi import webapp
import constants

version = constants.version

AUTH_IDLE = 0
AUTH_PROCESSING = 1
AUTH_FINISHED = 2

AUTH_STATUS_XL = [
  "IDLE",
  "PROCESSING",
  "FINISHED"
]

AUTH_FINALIZE = []
AUTH_CLEAR_FINALIZE = []

TASK_CAPACITY = {

}

################################################################################

class AuthInProgressException(Exception):
  pass

class LoginInvalidException(Exception):
  pass

class LoginPermsException(Exception):

  def error_info(self):
    return {
      "log_msg" : "Login denied due to missing permissions: %s" % str(self),
      "user_msg" : constants.ERR_LOGIN_PERMS
    }

################################################################################
# VodkaApp session

class Session(object):

  """
  User session object
  """

  ##############################################################################

  def __init__(self, app, fromRequest, web_ses_id):
    
    """
    Initialize the session object

    app should be a reference to a VodkaApp instance
    fromRequest should be a reference to _environ.get("_request")
    """

    self.fromRequest = fromRequest

    #reference to the VodkaApp instance
    self.app = weakref.proxy(app)

    #static file url
    self.staticFileUrl = self.app.config.get("server", {}).get("static_file_url","/")

    self.staticFileUrl = os.path.join(
      self.staticFileUrl,
      version
    )

    self.pref_manager = None

    self.tmpl_engines = {}
   
    #path to the currently selected brand directory
    self.brand_path = ""

    #the selected brand
    self.brand = self.pick_brand(fromRequest)

    #static file url (brands)
    self.staticFileUrlBrand = self.staticFileUrl + "/brands/"+self.brand.get("name")

    #the selected locale
    self.locale = self.brand["locale"]
    self.lang = self.locale.lang

    #the selected theme
    self.theme = self.pick_theme(fromRequest)

    #error messages that can be displayed in-page or added to json output
    self.messages = []
    self.errors = []

    #if set, the specified theme will be used instead of the picked one
    self.override_theme = False
    
    #if set, the simple theme will be forced no matter what
    self.fixed_theme_forced = False

    #will hold module perms for the authenticated session as it is stored 
    #in couchbase 
    self.module_perms = {} 
    self.module_perms_structure = {}

    # a unique id identifying this session
    self.client_id = ""
    self.auth_id = None
    self.auth_status = None
    self.auth_data = None
    
    #session id for the web sessions
    self.web_ses_id = web_ses_id

    #user id that was returned by successful login
    self.user_id = 0

    #user name that was returned by successful login
    self.user = None

    self.sounds = {}

    self.env = None
    
    #user agent
    self.ua = fromRequest.get('user_agent').lower();

    #store imported prefs for later confirmation
    self.imported_prefs = None

    #specifies which preference document keys the user can create / write to
    self.pref_document_access = []

    #holds remote code execution requirements
    self.rce = {}

    #holds current tasks running for this session
    self.tasks = []

    #holds update index data for rpc/update
    self.update_index_map = {}
    self.update_index_rev = {}
    self.update_index_dropped = {}

  ##############################################################################

  def rce_require(self, name, code, grace=10, limit=5):
    
    """
    Remote code execution required.
    
    This will execute a piece of javascript code on the user's client (browser)
    
    When a remote code execution is sent to the client it is expecting to be
    satisified via rce_satisfied(). If that fails to happen within the grace period
    and request limit the session will be logged out.

    name <str> unqiue name for the rce to identify it
    code <str> valid javascript code to execute
    grace <int> grace period between execution requests (seconds)
    limit <int> if after n requests rce has not been satisified the session will
    be logged out
    """

    try:

      if self.rce.has_key(name) or not code:
        return

      id = uuid.uuid4()

      self.rce[name] = {
        "id" : id,
        "code" : code,
        "time" : 0,
        "limit" : limit,
        "grace" : grace
      }

    except:
      raise
    
    

  ##############################################################################

  def rce_satisfy(self, name, id):
    
    try:
      
      if self.rce.has_key(name):
        if str(self.rce.get(name).get("id")) == id:
          del self.rce[name]

    except:
      raise


  ##############################################################################

  def verify_csrf(self, request):
    a = request.get('query', {});
    csrf_token_a = a.get('csrfmiddlewaretoken');
    csrf_token_b = webapp.get_cookie(request, "csrftoken")
    if csrf_token_a != csrf_token_b or not csrf_token_b:
      return False

    return True

  ##############################################################################
  # pick brand depending on host name

  def pick_brand(self, request, f_brand=None):

    """
    Cycle to brand map in config and see if hostname matches
    any of the url

    Pick brand according to hostname match

    On no match pick default

    if f_brand is set always use brand that matches f_brand(str) by
    name
    """

    host = request.get("host")
    s_brand = None

    #print "checking host " + host + " for brand..."
    for brand, mask in self.app._brand_map.items():
      if mask.match(host):
        #print "got brand " + brand
        s_brand = self.app.brand[brand]
      #else:
        #print "no brand match " + brand + " " + str(mask)

    if f_brand:
      if self.app.brand.get(f_brand):
        s_brand = self.app.brand.get(f_brand)
    
    if not s_brand:
      s_brand = self.app.brand["default"]
    
    dir = s_brand.get("dir")


    request["session"].data["url_map"] = [
      ("/css", "%s/htdocs/css" % dir, "%s/htdocs/css" % self.app.brand["default"].get("dir")),
      ("/js", "%s/htdocs/js" % dir, "%s/htdocs/js" % self.app.brand["default"].get("dir")),
      ("/favicon.ico", "%s/htdocs/favicon.ico" % dir),
      ("favicon.ico", "%s/htdocs/favicon.ico" % dir)
    ]

    self.brand = s_brand
    self.staticFileUrlBrand = self.staticFileUrl + "/brands/"+self.brand.get("name")

    self.brand_path = dir 
    return s_brand

    
  
  ##############################################################################
  # pick default theme depending on user agent

  def pick_theme(self, request):
    
    """
    Select theme by useragent
    """
    
    ua = request.get("user_agent")
    for name, regex in self.app._theme_map.items():
      if regex.match(ua):
        return name

    return self.app.config.get("app",{}).get("theme.default", "default") 


  ##############################################################################

  def uses_chrome(self):
    
    """
    Return True if the useragent indicates that google chrome is being used
    """

    if self.ua.find("chrome") != -1:
      return True
    else:
      return False

  ##############################################################################
  # check the user agent string to figure of if it's safari

  def uses_safari(self):

    """
    Return True if the useragent indicates that safari is being used
    """

    if self.ua.find("safari") != -1:
      return True
    else:
      return False


  ##############################################################################
  # update session variables

  def update(self, **kwargs):
    
    """
    Update session variables

    possible keyword arguments:

    theme (str)
    brand (str)
    locale (locale object)
    user (str), username
    """

    if "theme" in kwargs:
      if kwargs.get("theme") == "default" and not self.uses_chrome() and not self.uses_safari():
        self.theme = "mobile"
        self.fixed_theme_forced = True
      else:
        self.fixed_theme_forced = False 
        self.theme = kwargs["theme"]

    if "brand" in kwargs:
      self.brand = kwargs["brand"]
    
    if "locale" in kwargs:
      self.locale = kwargs["locale"]
      self.lang = self.locale.lang

    if "user" in kwargs:
      self.user = kwargs["user"]

  ##############################################################################
      
  def update_sesmap(self):
    self.app.update_sesmap({ self.web_ses_id : self.auth_id or None })
    
  ##############################################################################

  def get_client(self, for_duration=10):
    
    """
    Get the first free VodkaClient instance from the app's client pool
    """
    
    client = self.app.client_pool.get_client(for_duration) 
    i = 0
    while not client:
      client = self.app.client_pool.get_client(for_duration)
      time.sleep(0.1)
      i+=1
      if i >= 1000:
        raise Exception("No inactive clients")
    return client

  ##############################################################################

  def free_client(self, client):

    """
    respawn an unused / finished cliend gotten via get_client()
    """

    self.app.client_pool.respawn(client)

  ##############################################################################

  def is_authed(self):
    
    """
    Return True if session is authenticated, False if not
    """
    
    return self.is_connected()

  ##############################################################################
  # check if session is connected (has auth_id)

  def is_connected(self):

    """
    Return True if session's auth_id property is set, False if not
    """
    if self.auth_id:
      return True
    return False


  ##############################################################################

  def get_bridge(self, request=None, ignoreExpiry=False):

    """
    Return TmplBridge object for the current request
    """

    if not request:
      request = self.fromRequest

    if not request.get("bridge"):
      request["bridge"] = tmplbridge.TmplBridge(self, request, ignoreExpiry)

    return request.get("bridge")

  ##############################################################################
  # append an error message

  def error(self, error, toSession=False):

    """
    Append error(str) to self.errors
    """

    self.errors.append(error)

  ##############################################################################
  # get all error messages and clear error message stack

  def get_errors(self):
    
    """
    Return list containing errors in self.errors
    Empty self.errors
    """
    
    e = list(self.errors)
    self.errors = []
    return e


  ##############################################################################

  def auth_working(self):
    if self.auth_status == AUTH_PROCESSING:
      return True
    else:
      return False

      
  ##############################################################################

  def auth_process(self, *args, **kwargs):
    return 1

  ##############################################################################

  def auth_success(self, res):
    self.auth_data['result'] = res
    self.auth_id = res
    self.auth_finalize()
    self.auth_status = AUTH_FINISHED
    self.auth_data = None 
    self.reload_20c_module_perms()

  ##############################################################################

  def auth_error(self, error):
    self.error(error)
    self.auth_cancel()
    webapp.log.error(traceback.format_exc())

  ##############################################################################

  def auth_cancel(self):
    self.auth_status = AUTH_IDLE
    self.auth_data = None
    self.auth_id = None

  ##############################################################################

  def auth_validate(self):
    if self.auth_working():
      to = self.auth_data.get("timeout", 0)
      if to:
        start_t = self.auth_data.get("start_t")
        now = time.time()
        if now - start_t > to:
          self.error("Authentication timed out, please try again")
          self.auth_cancel()
          return False
      return True
    return False

  ##############################################################################

  def auth_start(self, **kwargs):
    if not self.auth_working():
      self.auth_status = AUTH_PROCESSING
      self.auth_data = kwargs
      self.auth_data.update(start_t=time.time())
      t = RunInThread(self.auth_process)
      t.error_handler = self.auth_error
      t.result_handler = self.auth_success
      t.start(**kwargs)
    else:
      raise AuthInProgressException()

  ##############################################################################

  def auth_finalize(self):
    for fn in AUTH_FINALIZE:
      try:
        fn(self, self.auth_data) 
      except Exception, inst:
        self.auth_cancel()
        webapp.log.error(traceback.format_exc())
        raise

  ##############################################################################

  def auth_clear_process(self):
    pass

  ##############################################################################

  def auth_clear(self):
    t = RunInThread(self.auth_clear_process)
    t.start()

    try:
      for fn in AUTH_CLEAR_FINALIZE:
        fn(self)
    except Exception, inst:
      webapp.log.error(traceback.format_exc())
    finally:
      self.auth_id = None

  ##############################################################################

  def tmpl(self, name, namespace=None, request=None, tmpl_type="cheetah", theme=None, variables={}, **kwargs):
    
    """
    load a template return it's rendered response

    current supported templated tmpl_types are: "cheetah"

    Templates can come from modules, the vodka barebone or brands
    """

    if not theme:
      theme = self.theme

    #print "TMPL: %s" % namespace
   
    if theme and namespace:
      namespace = "%s.%s" % (namespace, theme)
   
    tmpl_code = None
    tmpl_path = None

    self.deny_frame(request)


    #if namespace is not defined, check barebone vodka templates
    if not namespace:
      tmpl_path = os.path.join("tmpl")
      if not os.path.exists(tmpl_path):
        raise Exception("Template not found: %s" % tmpl_path)
    
    else:

      # first  check in the brand location
      if self.brand and os.path.exists(os.path.join(self.brand.get("dir"), "tmpl", namespace, name)):
        tmpl_path=os.path.join(
          self.brand.get("dir"), "tmpl", namespace
        )

      # then check in the module template cache
      elif self.app.templates.has_key("%s.%s" % (namespace, name)):
        tmpl_code = self.app.templates.get("%s.%s" % (namespace, name))
     
    if type(tmpl_code) == list:
      tmpl_path = os.path.dirname(tmpl_code[0])
      tmpl_code = None

    tmpl = None

    variables.update({
      "brand_path" : self.brand_path,
      "app_version" : constants.version,
      "request" : self.get_bridge(request),
      "_" : self.locale._,
      "sf" : self.staticFileUrl,
      "sfb":  self.staticFileUrlBrand
    })

    #print "variables: %s" % variables

    if not variables.has_key("headers"):
      variables["headers"] = []

    if tmpl_type == "cheetah":
      engine = tmpl_engine.engine.CheetahEngine(tmpl_dir=tmpl_path)
    elif tmpl_type == "jinja2":
      engine = tmpl_engine.engine.Jinja2Engine(tmpl_dir=tmpl_path)
    elif tmpl_type == "django":
      engine = tmpl_engine.engine.DjangoEngine(tmpl_dir=tmpl_path)
    else:
      raise Exception("Unknown templating engine: %s" % tmpl_type)

    if tmpl_code:
      return engine._render_str_to_str(tmpl_code, env=variables)
    elif tmpl_path:
      return engine._render(name, env=variables)
    else:
      # template not found
      raise Exception("Template not found: %s, %s" % (name, namespace))
    
  #############################################################################
  # set x-frame-options to deny loading this request in a frame. One reason
  # to do this is to prevent clickjacking
  
  def deny_frame(self, request):
    headers = request.get("headers")
    headers.extend([
      ("x-frame-options", "DENY"),
    ])
  
  ##############################################################################

  def reload_20c_module_perms(self):
    
    """
    Reload the module perms for this session
    """

    if self.app.module_manager:
      self.module_perms = self.app.module_manager.perms(self.auth_id)
      self.module_perms_structure = vt_session.perms_structure(self.module_perms)

    for namespace, level in self.app.grant_permissions.items():
      if self.check_20c_module(namespace) & level:
        continue

      if self.module_perms.has_key(namespace):
        self.module_perms[namespace] = self.module_perms.get(namespace) | level
      else:
        self.module_perms[namespace] = level

    self.module_perms["twentyc-billing.%s.response"%self.client_id] = constants.ACCESS_READ

  ##############################################################################

  def module_control(self,app_doc):
    if self.pref_manager:
      return self.pref_manager.get(app_doc).get("module_control", {});
    else:
      return {}

  ##############################################################################

  def available_20c_modules(self, mobile=False):
    
    """
    Return a list of modules that the session has access to
    """
    
    r = [];
    
    
    if mobile:
      app_doc = "mobile_app"
    else:
      app_doc = "mobile"

    module_control = self.module_control(app_doc)

    for i in self.app.module_js_load_order:
      mod = self.app.module_status.get(i,{})
      if mobile and not mod.get("mobile"):
        continue;
      
      if not mod.get("status"):
        status = 0
      else:
        status = int(module_control.get(i,1))

      if self.check_20c_module(i):
        r.append({ 
          "name" : i, 
          "version" : mod.get("version"),
          "status" : status
        })
     
    return r

  ##############################################################################

  def check_20c_module(self, name, ambiguous=False):
    
    """
    Check if session has access to the specified 20c module, return perms
    """

    if self.app.module_status.has_key(name):
      if self.app.module_status.get(name,{}).get("access_level",0) == 0:
        return 3

    if self.app.grant_permissions.has_key(name):
      return self.app.grant_permissions.get(name)

    if re.match("^__U\.%s\..+" % self.client_id, name):
      return 0x01|0x02|0x04

    if re.match("^__vodka-task-result\..+", name):
      task_id = name.split(".")[1]
      if task_id in self.tasks:
        return 0x01
      else:
        return 0

    if self.app.module_manager:
      return self.app.module_manager.perms_check(self.module_perms, name, ambiguous=ambiguous)

  ##############################################################################

  def reload_20c_module(self, name, version):
    """
    Send remote code execution to client to reload the specified module

    name <str> name of the module to reload
    """

    self.rce_require(
      "reload.%s" % name,
      "\n".join([
        "TwentyC.Modules.Load('%s', '%s');" % (name,version)
      ])
    )
 

  ##############################################################################

  def unload_20c_module(self, name):
    
    """
    Send remote code execution to client to unload the specified module

    name <str> name of the module to unload 
    """

    #find all modules that depend on this module.

    modules = self.app.update_modules()
    for mod_name,mod_status in modules.items():
      if name in mod_status.get("dependencies",[]):
        self.unload_20c_module(mod_name)

    self.rce_require(
      "unload.%s" % name,
      self.app.unload_tools_code+"\n"+
      "TwentyC.Modules.Unload('%s');\n" % name+
      (self.app.module_javascript_component(name, comp="unload.js") or "")
    )


  ##############################################################################

  def task_run(self, moduleName, taskName, params={}, target="download", filename=None, limitResult=0, source="session"):
    if self.check_20c_module(moduleName):
      
      taskType ="%s.%s" % (moduleName, taskName)

      # make sure session is not at task capacity
      maxCap = TASK_CAPACITY.get(taskType, 1)
      totCap = self.app.taskSessionCap

      wSame, fSame = self.task_status(taskType)
      wTotal, fTotal = self.task_status()

      if wSame >= maxCap:
        raise Exception("Please wait for the current '%s' task(s) to finish" % taskType)

      if wTotal >= totCap:
        raise Exception("Please wait for one of your other background tasks to finish")

      
      id_prefix = self.client_id[:6]
      self.app.log.info("Session %s... starting task: %s.%s %s" % (
        id_prefix,
        moduleName,
        taskName,
        params
      ))
      id, p = self.app.task_run(
        moduleName, 
        taskName, 
        id=self.client_id[:6], 
        ses=self, 
        target=target, 
        params=params,
        filename=filename,
        limitResult=limitResult,
        source=source
      )
      self.tasks.append(id)
      return id
 
  ##############################################################################

  def task_cancel(self, id):
    if id not in self.tasks:
      raise Exception("Session doesn't own a task with that id")

    info = self.app.task_info(id)
    info.update(end_t=time.time(), status=task.FINISHED, progress="Canceled", retrieved=2)
    self.app.task_terminate(id)

  ##############################################################################

  def task_status(self, type=None):
    working = 0
    finished = 0
    
    for id in self.tasks:
      t = self.app.tasks.get(id)
      if not t or (type and t.get("info",{}).get("type") != type):
        continue
      status = t.get("info",{}).get("status")

      if status == task.FINISHED:
        finished += 1
      else:
        working += 1

    return (working, finished)

  ##############################################################################

  def update_index(self, name, index, rev=None):

    if type(index) == types.NoneType:
      return

    prev = self.update_index_map.get(name, type(index)())

    if type(prev) == list:
      diff = list(set(prev) - set(index))
      rv = self.update_index_dropped[name] = list(set(diff + self.update_index_dropped.get(name,[])))
      self.update_index_map[name] = index
      crev_a, crev_b = self.update_index_rev.get(name, (0,0))

      if rev > crev_a:
        self.update_index_dropped[name] = []
        crev_a = rev
      if rev == crev_b and rv:
        if not self.update_index_rev.has_key(name):
          crev_a = 0
          crev_b = 1
        else:
          crev_b += 1

      self.update_index_rev[name] = (crev_a, crev_b)

      return rv

    elif type(prev) == dict:
      dropped = {}
      updated = {}
      for k,v in index.items():
        if prev.get(k) != v:
          updated[k] = v

      for k,v in prev.items():
        if not index.has_key(k):
          dropped[k] = v
      diff = (updated, dropped)
      return diff


################################################################################
################################################################################

