
################################################################################
################################################################################

import ConfigParser
import weakref
from pprint import pformat
import urllib
import re
import constants
import session
from rpc import *
import logging, logging.handlers
from datetime import datetime, timedelta, tzinfo
import time
import errno
import socket
import locale
import gettext
import babel
from wsgi import webapp
import operator

gettext.bindtextdomain('vodka', '/path/to/my/language/directory')
gettext.textdomain('vodka')
_ = gettext.gettext

# read , write perm flags
PERMS = {
  "READ" : 0x01,
  "WRITE" : 0x02
}

def add_module(name, allow=False):
  # DEPERECATED
  return

################################################################################

rpc_alias = {}
def register_rpc_alias(rpc_name, function_name):
  rpc_alias[rpc_name] = function_name
  
################################################################################

class UTC(tzinfo):
  """
  Timezone object
  """
  def __init__(self, offset=0):
    tzinfo.__init__(self)
    self.offset = offset

  def dst(self, dt):
    return timedelta(0)

  def utcoffset(self, dt):
    #FIXME 
    return timedelta(hours=self.offset)

  def tzname(self, dt):
    return "UTC %s" % str(self.offset)


################################################################################

class TmplBridge:

  """
  Request bridge
  A new instance is created with each request
  """

  def __init__(self, ses, request, ignoreExpiry=False):
    
    """
    ses should be a reference to a vodka Session instance
    
    if ignoreExpiry is True the creation of this tmplbridge
    instance will not reset the session expiry timer
    """

    # reference to the http request object that this bridge belongs to
    self.request = request 

    # current time 
    self.now = datetime.now()

    # reference to the user session that this bridge belongs to
    self.ses = weakref.proxy(ses)

    # reference to the session's locale object
    self.locale = ses.locale

    # reference to the VodkaApp instance
    self.zw = ses.app
    self.app = ses.app

    # user session id
    self.auth_id = ses.auth_id

    if not ignoreExpiry:
      self.reset_expiry()

    self.check_expiry(int(ses.app.config['app'].get('expiry', 240)))
    
    #set up locale

    locale.setlocale(locale.LC_ALL, '')

  @property
  def errors(self):
    return self.ses.get_errors()

  ##############################################################################

  def rpc_alias(self, name):
    return rpc_alias.get(name)

  ##############################################################################

  def version(self):
    """
    Return app version (str)
    """

    return constants.version

  ##############################################################################

  def timestamp(self):
   
    """
    Return timestamp for self.now (sec.usec format)
    """

    dt = self.now
    return dt.strftime("%s")+'.'+str(dt.microsecond)

  ##############################################################################

  def user(self):
    
    """
    Return username
    """
    
    return self.ses.user

  ##############################################################################
  # check if the server is running production or dev env

  def is_production(self):

    """
    Return True if server is running in production environment
    Else return False
    """

    # default to production 
    env = self.zw.serverConfig.get("environment", "production")
    if env == "production":
      return True
    else:
      return False

  #############################################################################
  # append error to session error object

  def error(self, error):
    
    """
    Append error (str) message to session error object
    """
    
    self.ses.errors.append(error)
    return False
   
  ##############################################################################
  
  def round_float(self, n, places):
    return round(float(n) * pow(10, places)) / pow(10, places)

  ##############################################################################
  # set vodka_ts session variable to current timstamp

  def reset_expiry(self):
    
    """
    Reset session expiry time according to current time
    """
    
    self.request.get("session").data["vodka_ts"] = time.mktime(self.now.timetuple())
  
  ##############################################################################

  def check_expiry(self, n = 4):
    
    """
    Check if enough time has passed since the last reset_expiry call. If so
    force timeout and logout on the session
    """

    sd = self.request.get("session").data
    if not sd.get('vodka_ts') or not n:
      return 0

    #print "sd: %s" % str(sd)

    lastAction = sd['vodka_ts']
    
    now = time.mktime(self.now.timetuple())

    diff = now - lastAction
    
    #print "checking expiry %d minutes (%d)" % (n, diff)
    if diff >= (60*n):
      self.request["session"].forceExpire = True

    return diff

  ##############################################################################

  def prefs(self):
    
    """
    Return session prefs object
    """

    return self.ses.pref_manager

  ##############################################################################

  def get_themes(self):
    
    """
    Return dict of themes
    """
    
    return self.zw.config.get("themes", {
      "default" : "Enhanced",
      "fixed" : "Simple", 
      "iphone" : "IPhone",
    }).items()
    

  ##############################################################################

  def get_langs(self):
    
    """
    Return dict of languages
    """
    
    return self.zw.config.get('lang', {'en-US':1}).items()

  ##############################################################################

  def csrf_token(self):
    return webapp.get_cookie(self.request, "csrftoken", "")

  ##############################################################################

  def selected_theme(self):
    
    """
    Return the currently selected theme in the cookie

    If no theme is selected in the cookie return the default theme for the
    session
    """
    
    return webapp.get_cookie(self.request, "theme", self.ses.theme)

  ##############################################################################

  def selected_lang(self):
    
    """
    Return the currently selected language in the cookie
    
    If no language is selected in the cookie return the default language
    for the session
    """
    
    return webapp.get_cookie(self.request, "lang", self.ses.locale.lang)

  ##############################################################################

  def selected_brand(self):
    
    """
    Return the session's brand
    """
    
    return self.ses.brand

  ##############################################################################

  def js_init_20c_modules(self):
    
    rv = []

    for name, mod in self.ses.app.modules.items():
      
      # skip modules that were loaded from couchbase but are currently
      # deactivated
      if hasattr(mod, "_module_from_couchbase"):
        if not self.ses.app.module_status.has_key(mod._module_from_couchbase):
          continue;

      if hasattr(mod, "js_init"):
        rv.append(mod.js_init(self.ses) or "")
    if rv:
      return "\n".join(rv)
    else:
      return ""

  ##############################################################################

  def include_20c_modules(self, mobile=False):
    
    """
    Cycle through modules and include their js libs if the session has access
    to it
    """
    
    r = [];
    ses = self.ses
    sfUrl = ses.staticFileUrl;

    modctrl = ses.module_control()
    modstat = ses.app.update_modules()

    for i in ses.app.module_js_load_order:
      
      mod = ses.app.module_status.get(i)
      
      # dont include modules that are deactivated
      if not mod or not mod.get("status"):
        continue
      
      # if were importing for mobile theme, check if module has a mobile component
      # before proceeding
      if mobile and not mod.get("mobile"):
        continue

      # check if module is disabled on the session level
      if modctrl.get(i) == False:
        continue

      # check if module dependencies are disabled in module manager or the
      # session level. And if they, dont load the module depending on them.
      deps = mod.get("dependencies", [])
      valid = True
      for d in deps:

        # is dependency disabled on session level?
        if modctrl.get(d) == False:
          valid = False
          break

        # is dependency disabled in module status?
        dep = modstat.get(d)
        if not dep or not dep.get("status"):
          valid = False
          break

      if not valid:
        continue

      if self.check_20c_module(i):
        r.append('<script id="mod:%s" type="text/javascript" src="/ui_component/%s/%s"></script>' % (
          i, i, mod.get("version")
        ))
     
    return "\n".join(r)


  ##############################################################################

  def check_20c_module(self, name):
    
    """
    Check if session has access to the specified 20c module, return perms
    """

    return self.ses.check_20c_module(name)

  #############################################################################

  def locations(self):
    """
    Return a list of valid hosts from brand location map
    """
    
    rv = []

    for loc in self.ses.brand.get("locations", []):
      rv.append(loc.split("="))

    return rv

  #############################################################################
  
  def json_string(self, obj):
    """
    Return json encoded string for <obj>
    """

    return json.json.dumps(obj)

  #############################################################################

  def js_bool(self, b):
    if b:
      return "true"
    else:
      return "false"

  #############################################################################

  def esc(self, txt):
    if txt:
      return txt.replace('"', '\\"').replace("'", "\\'")
    else:
      return ""

  #############################################################################

  def required_themes(self, layout):
    themes = []
    if layout.has_key("windows"):
      windows = layout.get("windows")
      for win in windows:
        if win.get("opt"):
          opt = win.get("opt")

          theme = opt.get("color_theme", opt.get("theme"))
          if theme and theme not in themes:
            themes.append(theme)
    return themes


  #############################################################################

  def loading_shim_get_template(self):
    """
    Dummy function
    """

    return None

  #############################################################################

  def module_media(self, namespace, fileName):
    return "/module_media/%s/%s/%s" % (
      namespace,
      self.ses.app.module_version(namespace),
      fileName
    )

  #############################################################################

  def module_js_path(self, namespace):
    return "/ui_component/%s/%s" % (
      namespace,
      self.ses.app.module_version(namespace)
    )

  #############################################################################

  def include_css_libs(self):
    rv = []
    for path in self.ses.app.lib_includes_css:
      rv.append('<link rel="stylesheet" type="text/css" href="%s/%s" />' % (
        self.ses.staticFileUrl,
        path
      ))
    return '\n'.join(rv)

  #############################################################################

  def include_js_libs(self):
    rv = []
    for path in self.ses.app.lib_includes_js:
      rv.append('<script type="text/javascript" src="%s/%s"></script>' % (
        self.ses.staticFileUrl,
        path
      ))
    return '\n'.join(rv)


  #############################################################################

  def include(self, name, namespace=None, **kwargs):
    return self.ses.tmpl(name, namespace=namespace, request=self.request, **kwargs)

  #############################################################################

  def access_xl(self, v):
    return constants.access_xl(v)

  #############################################################################

  @webapp.expose
  def tasks(self):
    rv = {}
    for id in self.ses.tasks:
      task = self.ses.app.tasks.get(id)
      if not task:
        continue
      rv[id] = task.get("info")
    return rv
    
   
################################################################################
################################################################################
