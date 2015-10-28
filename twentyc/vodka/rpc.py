
###############################################################################
###############################################################################

import time
import datetime

# we use this for an other json encoding / decoding
import simplejson as njson

import logging, logging.handlers
import traceback
import re
import prefs
import mimetypes
import random
import os
import task as vodkatask
from threading import Thread

from constants import *
from validator import ValidationException

from wsgi import webapp, json

def user_friendly_error(msg):
  return msg

def parse_update_specs(specs):
  if specs[0] == "{":
    try:
      return njson.loads(specs)
    except:
      return {}
  elif specs.find(':') > -1:
    return specs.split(':')
  elif specs.find('.') > -1:
    return specs.split('.')
  else:
    try:
      return int(specs)
    except ValueError:
      return specs

def generate_update_section(name, id, data, ses, bridge, xbahn=False, index=[]):
  
  section = {"name": name, "data": data}

  if not xbahn:
    if bridge and hasattr(bridge, "%s_index" % name):
      fn_idx = getattr(bridge, "%s_index" % name)
      if callable(fn_idx) and fn_idx.exposed:
        if type(id) == dict and id.has_key("index_rev"):
          section["dropped"] = ses.update_index(name, fn_idx(), rev=int(id.get("index_rev",0)))
        else:
          section["dropped"] = ses.update_index(name, fn_idx(), rev=None)

        section["index_rev"] = int(ses.update_index_rev.get(name,(0,0))[1])
  elif xbahn and type(id) == dict and id.has_key("index_key"):
    index_key = id.get("index_key")
    if id.has_key("index_rev"):
      section["dropped"] = ses.update_index(name, index, rev=int(id.get("index_rev",0)))
    else:
      section["dropped"] = ses.update_index(name, index, rev=None)

    section["index_rev"] = int(ses.update_index_rev.get(name,(0,0))[1])

  if id:
    section["id"] = id

  if not xbahn and type(id) == dict:
    if id.get("select") and data and type(data) == list:
      sel = id.get("select").split(":")
      _data = []
      if sel[0] == "from":
        m = float(sel[2])
        k = sel[1]
        if type(data[0]) == dict:
          for row in data:
            if row.get(k) > m:
              _data.append(row)
        else:
          for row in data:
            if hasattr(row, k) and getattr(row, k) > m:
              _data.append(row)
      section["data"] = _data

  return section



###############################################################################
# json field map for the various keys, translate key name to int value and
# vice versa

RPC_JSON_KEYS = {
}


def dd_list(o, idx="id", value="name"):
  r = {}
  if type(o) == dict:
    for k,i in o.items():
      r[i.get(idx)] = i.get(value)
  else:
    for i in o:
      r[getattr(i, idx)] = getattr(i, value)
  return r


class RpcUpdateEncoder(json.Encoder):

  """
  Extends json.Encoder and adds the functionality to numerically encode
  keys according to RPC_JSON_KEYS in order to shrink json result size
  """

  def default(self, c):
     c = dict(json.Encoder.default(self, c));
     for i in c:
       if RPC_JSON_KEYS.has_key(i):
         c[RPC_JSON_KEYS.get(i)] = c[i];
         del c[i]
     return c


###############################################################################
# VodkaApp RPC Module
#

RPC_OUTPUT_JSON = 1
RPC_OUTPUT_STATIC = 2

DEBUG = False 

class RPC(webapp.BaseApp):

  """
  RPC Request object
  """

  #############################################################################
  # startup INIT

  def __init__(self, outputType, vodka):
    
    """
    outputType can be RPC_OUTPUT_JSON or RPC_OUTPUT_STATIC
    vodka should be a reference to a VodkaApp instance
    """

    # output: json

    self.outputType = outputType 
    self.vodka = vodka

  #############################################################################

  def get_session(self, request):
    
    """
    Return session object from request
    """
    
    return self.vodka.get_session(request)
  
  #############################################################################
  # Get new JSON result object, containing timestamp with current time

  def json_result(self, bridge, withSessionMessages=False):
    
    """
    Return json result dict containing error, alert and time keys
    
    bridge should be a reference to a TmplBridge object
    """
    
    
    dt = bridge.now
    
    if withSessionMessages:
      alert = bridge.ses.messages
      bridge.ses.messages = []
    else:
      alert = []

    return {
      "error" : [],
      "alert" : alert,
      "time" : { "sec" : int(dt.strftime("%s")), "usec": dt.microsecond }
    }


  #############################################################################
  # Return output according to outputType

  def output(self, bridge, rv=None, redirect=None, compress=False):

    """
    Return output according to self.outputType

    if output type is RPC_OUTPUT_JSON return a json encoded string of
    rv

    if output type is RPC_OUTPUT_STATIC append any messages in
    rv["error"] or rv["alert"] to bridge.ses.errors and redirect
    to the specified redirect location
    """

    if self.outputType == RPC_OUTPUT_JSON and rv:
      
      if rv.has_key('traceback'):
        webapp.log.debug(str(rv['traceback']))

      #t_now = int(time.time()*1000)
      #t_then = (rv["time"].get("sec")*1000) + (rv["time"].get("usec") / 1000)

      #t_diff = t_now - t_then
      #rv["server_overhead"] = t_diff
      #rv["time"]["response"] = t_now

      # no cacheing for IE

      bridge.request.get("headers").append(
        ("Cache-Control", "no-store, no-cache, must-revalidate")
      )

      compress = bridge.ses.app.config.get("app",{}).get("compress_json", "off")
      if compress == "on":
        compress = True
      else:
        compress = False

      def dflt_serialize(o):
        return "ERR Serialization"
      
      #t1 = time.time()
      if compress:
        data = RpcUpdateEncoder(separators=(",",":"), encoding="latin1").encode(rv)
      else:
        data = json.Encoder(separators=(",",":"), encoding="latin1").encode(rv)
      #t2 = time.time()
      #print "JSON ENCODE TOOK %.5f" % (t2-t1)

      bridge.request.get("headers").append(
        ("Content-Length", "%s" % len(data))
      )

      return data
    elif self.outputType == RPC_OUTPUT_STATIC and redirect:
      for error in rv['alert']:
        bridge.error(error)
      raise webapp.HTTPRedirect(redirect)

  #############################################################################

  def handle_error_response(self, rv, error):
    """
    Append error response properties to respone result <rv>
    
    Args:

    rv <dict> response object gotten by self.json_result()
    error <Exception>
    """

    rv["alert"].append(user_friendly_error(error))
    if type(error) != ValidationException: 
      rv["traceback"] = traceback.format_exc()
    rv["error"].append(error)

  #############################################################################
  
  def controls(self, request):
    """
    Return session, bridge, json response object and request for the specified request
    in a tuple
    """

    ses = self.get_session(request)
    bridge = ses.get_bridge(request=request)
    rv = self.json_result(bridge)

    return (ses, bridge, rv, request)

  #############################################################################
  
  def require_content_length(self, ses, environ, config_name, err):
    l = int(environ.get("CONTENT_LENGTH",0))
    max = int(ses.app.config.get("server",{}).get(config_name, 1048576))
    #print "Checking CONTENT LENGTH: %d vs %d" % (l, max)
    if l > max:
      raise Exception(err % max)

  #############################################################################
  # Check if the session is logged in if not raise a 401

  def require_auth(self, request):
    """
    Check if the session is logged in, and if not raise a 401
    """

    ses = self.get_session(request)
    if not ses.is_authed(): 
      raise webapp.HTTPError(401)

  #############################################################################
  # Check if the user session has access to a module and if it doesnt
  # raise a 401 web error
  
  def require_module_perms(self, ses, module, perms):
    if not ses.check_20c_module(module) & perms:
      raise webapp.HTTPError(401)

  #############################################################################
  # Check if request is valid (POST and user logged in)

  def validate_request(self, request, require_auth=True):
    
    """
    Check if request is valid (request method and session is authenticated)

    If not valid raise webapp.HTTPError(401)
    """

    # make sure request is post

    if not request.get("method") == 'POST':
      raise webapp.HTTPError(401)

    ses = self.get_session(request)

    # verify csrf token

    if not ses.verify_csrf(request):
      raise Exception("CSRF attempt?");

    # verify referer

    webapp.verify_referer(request);

    # make sure user is connected
    
    if require_auth and not ses.is_authed():
      raise webapp.HTTPError(401)

  #############################################################################
  # expire session

  @webapp.expose
  def expire_session(self, **kwargs):

    """
    Expire the session linked to the http request
    """

    req = kwargs.get("__request") 
    ses = self.get_session(req)
    ses.forceExpire = True

  #############################################################################
  # make sure session is fulled loaded (account perms)
  
  def session_valid(self, b, request):

    """
    """

    ses = self.get_session(request)
    bridge = ses.get_bridge(request, b)
    return True

  #############################################################################
  # Return JSON data for update request 

  @webapp.expose
  def update(self, **kwargs):
    
    """
    Render json for the global update request

    possible keyword arguments: any tmplbridge function name 

    e.g rpc_json/update?accounts&instruments
    """

    req = kwargs.get("__request")
    ses = self.get_session(req)

    # make sure user is logged in
    # if not self.vodka.is_connected():
    
    if not ses.is_authed():
      raise webapp.HTTPError(401)
    
    # get bridge object and make sure expiry time is NOT updated
      
    bridge = ses.get_bridge(req, True)
    rv = self.json_result(bridge, withSessionMessages=True)

    isExplicit = kwargs.has_key("__exp")
    isMain = int(kwargs.get("__main",1))
    fullUpdate = kwargs.has_key("__full")

    #if bridge.zw.client.status != 2:
    #  ses.forceExpire = True
    #  raise webapp.HTTPError(401)
    
    try:
     
      ##webapp.clear_kwargs(kwargs)

      self.session_valid(True, req)
      del kwargs["__environ"]
      del kwargs["__request"]
 
      rv["update"] = []

      t = rv["time"]["sec"]
      
      try:
        for k,v in kwargs.items():
          
          section = None 

          ok = k

          if bridge.rpc_alias(k):
            k = bridge.rpc_alias(k)

          if hasattr(bridge, k):
            func = getattr(bridge, k)
        
            if not callable(func):
              continue

            if not hasattr(func, "exposed"):
              continue

            #print "calling update: %s" % k
        
            if v:
              if not hasattr(v, '__iter__'):
                v = parse_update_specs(v)
               
                section = generate_update_section(ok, v, func(v), ses, bridge)

              else:
                for n in v:
                  n = parse_update_specs(n)
                  rv["update"].append(generate_update_section(ok, n, func(n), ses, bridge))
            else:
              section = generate_update_section(ok, None, func(), ses, bridge)
          
          elif ses.app.xbahn:
            
            # retrieve data from xbahn

            if not ses.check_20c_module(k, ambiguous=True):
              continue

            prepFncName = "prepare_%s_for_update" % (k)

            if v:
              if not hasattr(v, '__iter__'):

                v = parse_update_specs(v)
                data,index = ses.app.xbahn.update(k,ses=ses,prepare=prepFncName,id=v,time=t)
                section = generate_update_section(
                  k,
                  v,
                  data,
                  ses,
                  bridge,
                  xbahn=True,
                  index=index
                )

              else:
                for n in v:
                  n = parse_update_specs(n)

                  data,index = ses.app.xbahn.update(k,ses=ses,prepare=prepFncName,id=n,time=t)
                  rv["update"].append(
                    generate_update_section(
                      k,
                      n,
                      data,
                      ses,
                      bridge,
                      xbahn=True,
                      index=index
                    )
                  )

            else:
              data,index = ses.app.xbahn.update(k, ses=ses, prepare=prepFncName, time=t)
              section = generate_update_section(
                k,
                None,
                data,
                ses,
                bridge,
                xbahn=True,
                index=index
              )

          if section:
            rv["update"].append(section)
        
      except Exception, inst:
        rv["update"].append({
          "name" : k,
          "data" : {},
          "error": str(inst)
        })
        if not ses.app.is_production:
          ses.app.log.error(traceback.format_exc())


    except Exception, inst:
      if DEBUG:
        rv["traceback"] = traceback.format_exc()
        rv["error"].append(inst)
      else:
        raise

    # attach any remote code execution requirements 
    rv["rce"] = []
    for rce_name, rce_data in ses.rce.items():
      if t - rce_data.get("time",0) < rce_data.get("grace"):
        continue
      rv["rce"].append(rce_name)
      rce_data["time"] = t
      rce_data["limit"] -= 1

      if rce_data["limit"] <= 0:
        del ses.rce[rce_name]

    #if random.randint(1,10) > 2:
    #  print "Canceling update ..."
    #  rv["update"] = []
    #else:
    #  print "NOT CANCELING UPDATE"
      
    return self.output(bridge, rv, False, False)


  #############################################################################
  
  @webapp.expose
  def layout_list(self, **kwargs):

    """
    Send a list of all layout names for this user, stored in json result under
    key "layouts"
    """

    req = kwargs.get("__request")
    ses = self.get_session(req)
    bridge = ses.get_bridge(req)
    rv = self.json_result(bridge)

    if not ses.is_authed():
      raise webapp.HTTPError(401)

    try:
      rv["layouts"] = ses.pref_manager.get("app").get("layouts",[])
    except Exception, inst:
      rv["error"].append(inst)
      rv["traceback"] = traceback.format_exc()
      rv["alert"].append(str(inst))

    return self.output(bridge, rv)
 


  #############################################################################
  # load layout

  @webapp.expose
  def layout(self, id=0, **kwargs):
    
    """
    Generate json for the layout with the specified id (int)
    """

    req = kwargs.get("__request")
    ses = self.get_session(req)

    if not ses.is_authed():
      raise webapp.HTTPError(401)
    
    bridge = ses.get_bridge(req)
    rv = self.json_result(bridge)

    try:
      pass

    except Exception, inst:
      rv["error"].append(inst)
      rv["traceback"] = traceback.format_exc()
      rv["alert"].append(str(inst))
      #rv["alert"].append(ERR_LAYOUT_LOAD)

    return self.output(bridge, rv)


  #############################################################################

  @webapp.expose
  def prefs(self, **kwargs):
    
    """
    Return the specified prefs object for the user

    Args:

    key <string> should be an existing config document name eg. "app"
    """

    ses, bridge, rv, req = self.controls(kwargs.get("__request"))

    if not ses.is_authed(): 
      rv["prefs"] = {}
      return self.output(bridge, rv)

    self.require_auth(req)

    try:

      key = kwargs.get("key")
      
      doctype = key.split(".")[0]

      if doctype not in ses.pref_document_access:
        rv["prefs"] = {}
      else:
        rv["prefs"] = ses.pref_manager.get(key)
      
    except Exception, inst:
      self.handle_error_response(rv, inst)

    return self.output(bridge, rv)


  #############################################################################

  @webapp.expose
  def prefs_selective(self, **kwargs):
    
    """
    Return specific properties for the specified prefs object for the user

    Args:

    key <string> should be an existing config document name eg. "app"

    properties <string> list of properties to retrieve - delimited by ,

    JSON specs:

    { prefs : { <property_name> : <property_value>, ... }}
    """

    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    self.require_auth(req)

    try:

      key = kwargs.get("key")
      props = kwargs.get("properties","").split(",")

      doctype = key.split(".")[0]

      if doctype not in ses.pref_document_access:
        rv["prefs"] = {}
      else:
        obj = ses.pref_manager.get(key)
        r = {}

        for prop in props:
          r[prop] = obj.get(prop)

        rv["prefs"] = r
      
    except Exception, inst:
      self.handle_error_response(rv, inst)

    return self.output(bridge, rv)



  #############################################################################

  @webapp.expose
  def import_prefs_apply(self, **kwargs):
    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    self.validate_request(req)

    try:
      
      if not ses.imported_prefs:
        return

      prefs = ses.imported_prefs
      ses.imported_prefs = None
      rv["documents"] = ses.pref_manager.import_prefs(prefs)

    except Exception, inst:
      self.handle_error_response(rv, inst)
    
    return self.output(bridge, rv, '/')
 
  #############################################################################

  @webapp.expose
  def import_prefs(self, **kwargs):
    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    self.validate_request(req)

    try:
      self.require_content_length(ses, kwargs.get("__environ"), "post_limit_prefs", ERR_PREFS_POST_TOO_LARGE)
      file = kwargs.get("file")

      try:
        ses.imported_prefs = json.json.loads(file)
      except Exception, inst:
        ses.app.log.debug("PREFS IMPORT JSON ERROR: %s" % str(inst))
        raise Exception("Needs to be valid JSON format");

      ses.pref_manager.validator.validate_shared_data(ses.imported_prefs)

      import_list = []

      for key,data in ses.imported_prefs.items():
        import_list.append(key)
        if type(data) == dict:
          for subkey in data.keys():
            import_list.append("... %s" % (subkey))
        
      rv["import"] = import_list

    except Exception, inst:
      self.handle_error_response(rv, inst)
    
    return self.output(bridge, rv, '/')
 
 

  #############################################################################

  @webapp.expose
  def export_prefs(self, **kwargs):

    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    self.require_auth(req)

    try:

      targets = json.json.loads(kwargs.get("targets",{}))
      targets = targets.get("targets",[])

      if targets:
        exp_data = ses.pref_manager.export_prefs(targets)
        exp_keys = exp_data.keys()
        print "Export keys: %s" % exp_keys
        if len(exp_keys) > 1:
          filename = "preferences.json"
        else:
          filename = "%s.json" % exp_keys[0]

        if exp_data:
          rv = exp_data
          headers = req.get("headers")
          headers.extend([
            ("content-type", "text/json"),
            ("content-disposition", "attachment; filename=%s" % filename)
          ])
        else:
          raise Exception(ERR_NOTHING_TO_EXPORT)

      
    except Exception, inst:
      self.handle_error_response(rv, inst)
    
    return self.output(bridge, rv, '/')
 

  #############################################################################

  @webapp.expose 
  def save_app_prefs(self, **kwargs):
    
    """
    Save app preferences
    """

    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    self.validate_request(req)

    try:
      
      self.require_content_length(ses, kwargs.get("__environ"), "post_limit_prefs", ERR_PREFS_POST_TOO_LARGE)

      config = kwargs.get("config")

      if not config:
        return

      config = json.json.loads(config)

      ses.pref_manager.update({
        "app" : config
      })

    except Exception, inst:
      self.handle_error_response(rv, inst)
    
    return self.output(bridge, rv, '/')
 
 
  #############################################################################

  @webapp.expose 
  def save_module_prefs(self, **kwargs):
    
    """
    Save module preferences

    Args

    config <dict> data to save
    module <string> module name (config document name)
    """

    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    self.validate_request(req)

    try:

      config = kwargs.get("config")
      name = kwargs.get("module");

      if not config or not name:
        return
      
      self.require_content_length(ses, kwargs.get("__environ"), "post_limit_prefs", ERR_PREFS_POST_TOO_LARGE)

      doctype = name.split(".")[0]

      # make sure module is a valid document type
      if doctype not in ses.pref_document_access:
        raise prefs.ValidationException(ERR_INVALID_PREFS_DOC % doctype)

      config = json.json.loads(config)

      data = {}
      data[name] = config

      ses.pref_manager.update(data)

    except Exception, inst:
      self.handle_error_response(rv, inst)
    
    return self.output(bridge, rv, '/')
 
 
  #############################################################################

  @webapp.expose 
  def delete_module_prefs(self, **kwargs):
    
    """
    Save module preferences

    Args

    name <string> full config document name to delete. eg. "color_theme.my theme"
    """

    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    self.validate_request(req)

    try:

      name = kwargs.get("name");

      if not name:
        return

      doctype = name.split(".")[0]

      if doctype in ["app","sys"]:
        raise prefs.ValidationException(ERR_INVALID_PREFS_DOC % doctype)
      
      # make sure module is a valid document type
      if doctype not in ses.pref_document_access:
        raise prefs.ValidationException(ERR_INVALID_PREFS_DOC % doctype)

      ses.pref_manager.delete(name)

    except Exception, inst:
      self.handle_error_response(rv, inst)
    
    return self.output(bridge, rv, '/')
 
 
  #############################################################################

  @webapp.expose
  def layout_make_default(self, **kwargs):
    
    """
    Make the layout with the specified name the default layout for the user

    Args

    name <string> layout name
    """
    
    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    self.require_auth(req)

    try:

      name = kwargs.get("name")
      ses.pref_manager.layout_set_default(name)
      
    except Exception, inst:
      self.handle_error_response(rv, inst)

    return self.output(bridge, rv)


  #############################################################################

  @webapp.expose
  def layout_rename(self, **kwargs):
    
    """
    Rename a layout
    
    Args

    layout <string> current layout name
    name <string> new layout name
    """


    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    self.validate_request(req)

    try:

      name = kwargs.get("name")
      layout = kwargs.get("layout")

      rv["layout_rename"] = ses.pref_manager.layout_rename(layout, name)
      
    except Exception, inst:
      self.handle_error_response(rv, inst)

    return self.output(bridge, rv)


  
  #############################################################################

  @webapp.expose
  def layout_save(self, **kwargs):

    """
    Save a layout

    Required keyword arguments:

    config <string> jsonified layout config object.

    valid format:

    {
      "my layout" : {
        "windows" : { .. },
        "panes" : [...],
      },
      ...
    }
    """

    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    self.validate_request(req)

    try:
      config = kwargs.get("config")
      
      self.require_content_length(ses, kwargs.get("__environ"), "post_limit_prefs", ERR_PREFS_POST_TOO_LARGE)

      config = json.json.loads(config)
      app_config = ses.pref_manager.get("app")

      for layout_name, layout_config in config.items():
        ses.pref_manager.set("layout.%s" % layout_name, layout_config)
    except Exception, inst:
      self.handle_error_response(rv, inst)

    return self.output(bridge, rv, "/")

  #############################################################################

  @webapp.expose
  def layout_delete(self, **kwargs):
    
    """
    Delete layout matching name (str)
    """
    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    self.validate_request(req)

    try:
      name = kwargs.get("name")
      ses.pref_manager.delete("layout.%s" % name)
      rv["default_layout"] = ses.pref_manager.get("app").get("default_layout")
    except Exception, inst:
      self.handle_error_response(rv, inst)
   
    return self.output(bridge, rv, "/")

  #############################################################################

  @webapp.expose
  def module_status(self, **kwargs):
    """
    Return a json struct of loaded modules and their versions.
    """
    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    self.require_auth(req)

    try:
      rv["modules"] = ses.app.update_modules()  
    except Exception, inst:
      self.handle_error_response(rv, inst)

    return self.output(bridge, rv, "/")

  #############################################################################

  @webapp.expose
  def upload_custom_sound(self, **kwargs):
    
    """
    Upload a sound and save it to config

    Keyword Arguments:

    file (file upload)
    sound_name (str, the sound name that should use the new file)
    """
    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    self.validate_request(req)

    try:
      file = kwargs.get("file")

      if not file:
        raise Exception("No file selected for upload")

      fileType = mimetypes.guess_type(kwargs.get("__environ").get("request").get("uploads").get("file").filename)

      if fileType[0] != "audio/mpeg":
        raise Exception("The uploaded file type is not supported")
      else:
        soundName = kwargs.get('sound_name')
  
        if soundName not in ses.app.config.get("sounds",{}).keys():
          raise Exception("Invalid sound file name: %s" % soundName)
        else:
          ses.pref_manager.add_custom_sound(soundName, file)

    except Exception, inst:
      self.handle_error_response(rv, inst)
   
    return self.output(bridge, rv, "/")
  
  #############################################################################
  # remove a custom sound from config

  @webapp.expose
  def restore_default_sound(self, **kwargs):
    
    """
    Restore default sound for sound name (str)

    eg. /rpc_json?restore_default_sound?sound_name=order_fill
    """
    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    self.validate_request(req)

    try:
      soundName = kwargs.get('sound_name')
      if soundName not in ses.app.config.get("sounds",{}).keys():
        raise Exception("Invalid sound file name: %s" % soundName)
      else:
        sounds = ses.pref_manager.get("sounds")

        # remove sound
        if sounds.has_key(soundName):
          del sounds[soundName]
          ses.pref_manager.set("sounds", sounds)

        # remove custom sounds tracker from app prefs

        custom_sounds = ses.pref_manager.get("app").get("custom_sounds",[]) or []
        if soundName in custom_sounds:
          custom_sounds.remove(soundName)

        ses.pref_manager.update({
          "app" : {
            "custom_sounds": custom_sounds or []
          }
        });

    except Exception, inst:
      self.handle_error_response(rv, inst)
   
    return self.output(bridge, rv, "/")

  #############################################################################

  @webapp.expose
  def module_listing(self, **kwargs):
    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    self.validate_request(req, require_auth=False);
    try:
      for_mobile = kwargs.get("mobile")
      rv["modules"] = ses.available_20c_modules(mobile=for_mobile)
    except Exception, inst:
      self.handle_error_response(rv, inst)

    return self.output(bridge, rv, "/")
    
  #############################################################################

  @webapp.expose
  def unload_module_test(self, **kwargs):
    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    try:
      ses.unload_20c_module(kwargs.get("name"))
    except Exception, inst:
      self.handle_error_response(rv, inst)

    return self.output(bridge, rv, "/")


  #############################################################################

  @webapp.expose
  def rce_satisfy(self, **kwargs):
    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    self.validate_request(req);
    try:
      ses.rce_satisfy(kwargs.get("name"), kwargs.get("id"))
    except Exception, inst:
      self.handle_error_response(rv, inst)
    return self.output(bridge, rv, "/")

  #############################################################################

  @webapp.expose
  def module_perms(self, **kwargs):
    
    """
    Sends a dict of the user's current module permissions
    """

    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    self.validate_request(req, require_auth=False)

    try:
      rv["module_perms"] = ses.module_perms
    except Exception, inst:
      self.handle_error_response(rv, inst)

    return self.output(bridge, rv, "/")

  #############################################################################
  
  @webapp.expose
  def reload_module_perms(self, **kwargs):
    
    """
    Reloads the module permissions for this users session
    """

    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    self.validate_request(req);
    try:
      ses.reload_20c_module_perms()
    except Exception, inst:
      self.handle_error_response(rv, inst)

    return self.output(bridge, rv, "/")

  #############################################################################
  
  @webapp.expose
  def task_result(self, **kwargs):
    
    """
    Fetch/download task result
    """

    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    self.require_auth(req);
    try:
      
      id = kwargs.get("id")
      if id not in ses.tasks:
        raise Exception("You don't own a task with that id: %s" % id)

      info = ses.app.task_info(id)

      webapp.set_header(req, "Content-type", info.get("mime"))
      if info.get("target") == "download":
        webapp.set_header(req, "Content-disposition", "attachment; filename=%s" % info.get("filename", id))

      if info.get("length"):
        webapp.set_header(req, "Content-length", str(info.get("length")))

      ses.app.info(req.get("headers"))

      info["retrieved"] = 1
      
      def gen():
        while ses.app.tasks.get(id):
          
          if info.get("error") or info.get("retrieved") >= 2:
            yield ""
            break

          result = ses.app.tasks[id].get("result", [])
          l = len(result)
          if l:
            rows = "\n".join(result[:l])
            if type(rows) == unicode:
              rows = str(rows)

            del result[:l]
            yield rows
          elif info.get("status") != vodkatask.FINISHED:
            time.sleep(0.5)
          else:
            info["retrieved"] = 2
            break
      
      return gen()
  
    except Exception, inst:
      ses.app.log.error(traceback.format_exc())

  #############################################################################
  
  @webapp.expose
  def task_cancel(self, **kwargs):
    
    """
    Cancel the specified task
    """

    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    self.validate_request(req);
    try:
      
      id = kwargs.get("id")
      if id not in ses.tasks:
        raise Exception("You don't own a task with that id: %s" % id)

      ses.task_cancel(id)

    except Exception, inst:
      self.handle_error_response(rv, inst)

    return self.output(bridge, rv, "/")

  #############################################################################

  @webapp.expose
  def info(self, **kwargs):
    """
    Return some information about the vodka instance
    """

    ses, bridge, rv, req = self.controls(kwargs.get("__request"))

    try:
      
      if ses.app.xbahn and ses.app.xbahn.status == 2:
        xbahn = "ok"
      else:
        xbahn = "disconnected"

      rv["info"] = {
        "xbahn" : xbahn,
        "db_engine" : ses.app.couch_engine,
        "modules_loaded" : len(ses.app.module_status.keys()),
        "version" : version 
      }
    except Exception,inst:
      self.handle_error_response(rv, inst)

    return self.output(bridge, rv, "/")

