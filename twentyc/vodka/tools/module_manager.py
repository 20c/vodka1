# Module Manager
# Allowes syncing vodka modules from and to a couchbase instance

import twentyc.database
import sys
import imp
import re
import simplejson as json
import base64
import uuid
import threading
import copy

import twentyc.vodka.tools.session as session

import time

# holds all javascript component names that are not part of the module
# javascript main

javascript_parts = [
  "unload.js"
]

# holds all python modules imported from couchbase via 
# ModuleManager.module_import

imported_modules = {}

class InvalidModuleException(Exception):
  pass

class InvalidLevelException(Exception):
  pass

class PrivateNamespaceException(Exception):
  pass


class ModuleManager(object):

  #############################################################################
  
  def __init__(self, logger=None, verbose=True, use_cache=False):
    
    """
    Keyword arguments

    logger <logger> python logger instance to log debug and info messages
    """
    
    self.verbose = verbose
    self.log = logger
    self.xbahn = None
    self.lock = threading.RLock();
    self.disable_perms_log = False
    self.use_cache = use_cache
    self.cache = {}

  #############################################################################

  def namespace_match(self, items, prefix):
    
    """
    Returns whether the prefix namespace is matched by any str in items

    items <list> list of strings
    prefix <str> namespace prefix to check

    example

    namespace_match(["foo","bar"], "bar.test") return True because of match
    namespace_match(["foo.test","bar"], "foo.test") return True because of match
    namespace_match(["foo","bar"], "test") return False because of no match
    """

    token = prefix.split(".")

    i = 1
    l = len(token)
    r = 0

    while i <= l:
      k = ".".join(token[:i])
      if k in items:
        return True
      i += 1

    return False
 
  #############################################################################

  def set_database(self, client):
    """
    Pass a twentyc couch-engine client here.

    Example

    set_database(
      twentyc.database.Client(
        engine="couchbase", host="1.2.3.4:1234", auth="bucket_name:password"
      )
    )
    """
    self.cb_client = client
    self.meta_prefix = client.meta_prefix
    
  #############################################################################

  def set_couchbase(self, host, auth):
    
    """
    DEPRECATED, use set_database
    Setup couchbase client for this module manager instance using host and auth information

    Args

    host <string> hostname (can include port separated by :)
    auth <string> bucket auth (bucket_name:bucket_password)
    """

    self.set_database(
      twentyc.database.Client(
        engine="couchbase",
        host=host,
        auth=auth,
        logger=self.log
      )
    )

  #############################################################################
    
  def set_couchbase_from_client(self, client):
    
    """
    DEPRECATED, use set_database
    Set couchbase client for this module manager using an existing twentyc couchbase client instance

    Args

    client <twentyc.couchbase.CouchbaseClient>
    """
    
    self.cb_client = client

  #############################################################################

  def now(self):
    return time.time()

  #############################################################################

  def dbg(self, msg):
    msg = "Vodka Module Manager: %s" % msg
    if self.log:
      self.log.debug(msg)
    if self.verbose:
      print msg

  #############################################################################

  def module_import(self, namespace, name):
    try:
      key = self.module_key(namespace, name)
      info = self.module_info(namespace, name)
      modules = {}
      if info:
        if len(info["python"]) > 0:
          
          if not imported_modules.has_key(namespace):
            imported_modules[namespace] = {}

          imported_modules[namespace][name] = {}
          
          for comp in info["python"]:
            k = "%s_%s" % (key, comp)
            k = re.sub("[^a-zA-Z0-9_]","_",k)
            #self.dbg("Importing python module component: %s.%s.%s" % (
            #  namespace, name, comp
            #))
            mod = imp.new_module(k)
            data = self.module_component(namespace, name, comp)
            code = data.get("contents")
            if code:
              exec code in mod.__dict__
            modules[comp] = mod
            sys.modules[k] = mod
            imported_modules[namespace][name][comp] = mod
      return modules
    except:
      raise

  #############################################################################

  def module_javascript(self, namespace, name, minified=False):
    try:
      info = self.module_info(namespace, name)
      code = "";
      for comp_name in info.get("javascript"):
        
        if comp_name in javascript_parts:
          continue

        comp = self.module_component(namespace, name, comp_name)
        
        if minified and comp.get("minified"):
          key = "minified"
        else:
          key = "contents"

        code += "\n%s" % comp.get(key)
      return code
        
    except:
      raise

  #############################################################################

  def module_validator_code(self, namespace, name):
    try:
      info = self.module_info(namespace, name)
      code = "";
      for comp_name in info.get("validator"):
        comp = self.module_component(namespace, name, comp_name)
        code += "\n%s" % comp.get("contents","")
      return code
        
    except:
      raise

  #############################################################################

  def module_templates(self, namespace, name):
    try:
      info = self.module_info(namespace, name)
      code = "";
      rv = {} 
      for comp_name in info.get("template"):
        rv["%s.%s.%s" % (namespace, name, comp_name)] = self.module_component(namespace, name, comp_name).get("contents")
      return rv 
        
    except:
      raise


  #############################################################################

  def module_key(self, namespace, name):
    try:
      return "%s.%s" % (namespace, name)
    except:
      raise


  #############################################################################

  def module_token(self, module_key):
    try:
      a = module_key.split(".")
      return (
        a[0],
        ".".join(a[1:])
      )
    except:
      raise

  #############################################################################

  def module_create(self, namespace, name, owner, version="1.0.0", access_level=0, title=None, status=1, mobile=False, priority=0):
    try:
      mod = self.module_info(namespace, name)
      if mod:
        return

      if not title:
        title = re.sub("[_-]", " ", name).capitalize()

      mod = {
        "type" : "vodka_module",
        "version" : version,
        "javascript" : [],
        "template" : [],
        "python" : [],
        "validator" : [],
        "media" : [],
        "dependencies" : [],
        "namespace" : namespace,
        "name" : name,
        "title" : title,
        "status" : status,
        "mobile" : mobile,
        "owner" : owner,
        "priority" : priority,
        "access_level" : access_level,
        "modified" : self.now()
      }

      key = self.module_key(namespace, name)

      self.cb_client.set(key, mod)

      return mod
      
    except:
      raise

  #############################################################################

  def module_index(self):
    try:
      
      result = self.cb_client.view("vodka", "module_index", descending=True)
      modules = {}
      for row in result: 
        mod = row.get("value")
        modules["%s.%s" % (mod.get("namespace"), mod.get("name"))] = mod

      return {
        "modules" : modules 
      };
    except:
      raise

  #############################################################################
  
  def module_info(self, namespace, name):
    try:
      key = self.module_key(namespace, name)
      mod = self.cb_client.get(key)
      return mod
    except:
      raise

  #############################################################################

  def module_update_info(self, namespace, name, info):
    try:
      key = self.module_key(namespace, name)
      mod = self.module_info(namespace, name)

      if not mod:
        raise Exception("Trying to update non existant module info %s" % key)

      mod.update(info)
      mod["modified"] = self.now()
      self.cb_client.set(key, mod)

    except:
      raise

  #############################################################################

  def module_add_component(self, namespace, name, component_name, contents, mime, minified=""):
    try:
      
      index = self.module_info(namespace, name)
      
      if mime == "text/javascript":
        list_name = "javascript"
      elif mime == "text/python":
        list_name = "python"
      elif mime == "text/vodka-validator":
        list_name = "validator"
      elif mime == "text/vodka-template":
        list_name = "template"
      elif mime == "text/json":
        list_name = "data"
      else:
        list_name = "media"
        contents = base64.b64encode(contents)

      if not index.has_key(list_name):
        index[list_name] = []

      if component_name not in index[list_name]:
        index[list_name].append(component_name)
 
      self.module_update_info(namespace, name, index)

      self.cb_client.set(
        "%s.%s" % (self.module_key(namespace, name), component_name),
        {
          "module" : self.module_key(namespace, name),
          "name" : component_name,
          "owner" : index.get("owner"),
          "type" : "vodka_module_component",
          "component_type" : list_name,
          "mime" : mime,
          "contents" : contents,
          "minified" : minified
        }
      )

    except:
      raise

  #############################################################################

  def module_remove_component(self, namespace, name, component_name):
    try:
      
      key = "%s.%s" % (self.module_key(namespace, name), component_name)

      component = self.cb_client.get(key)
      mod = self.module_info(namespace, name)
     
      if component: 
        if component.get("mime") == "text/javascript":
          mod["javascript"].remove(component_name)
        elif component.get("mime") == "text/python":
          mod["python"].remove(component_name)
        elif component.get("mime") == "text/vodka-validator":
          mod["validator"].remove(component_name)
        elif component.get("mime") == "text/vodka-template":
          mod["template"].remove(component_name)
        elif component.get("mime") == "text/json":
          mod["data"].remove(component_name)
        else:
          mod["media"].remove(component_name)

        self.cb_client.unset(key)

        self.module_update_info(namespace, name, mod)

    except:
      raise


  #############################################################################

  def module_remove(self, namespace, name):
    try:
      
      key = self.module_key(namespace, name)
      mod = self.cb_client.get(key)

      if mod:
        self.cb_client.unset(key)
        for comp in mod.get("javascript"):
          self.cb_client.unset("%s.%s" % (key, comp))
        for comp in mod.get("python"):
          self.cb_client.unset("%s.%s" % (key, comp))
        for comp in mod.get("media"):
          self.cb_client.unset("%s.%s" % (key, comp))
        for comp in mod.get("validator",[]):
          self.cb_client.unset("%s.%s" % (key, comp))
        for comp in mod.get("template", []):
          self.cb_client.unset("%s.%s" % (key, comp))

    except:
      raise

  #############################################################################
  
  def module_component(self, namespace, name, component_name):
    try:
      key = "%s.%s" % (self.module_key(namespace, name), component_name)
      component = self.cb_client.get(key)
      return component
    except:
      raise

  #############################################################################

  def module_media_content(self, namespace, name, component_name):
    try:
      mod = self.module_component(namespace, name, component_name)
      return base64.b64decode(mod.get("contents",""))
    except:
      raise

  #############################################################################

  def module_add_dependency(self, namespace, name, dependency):
    try:
      
      info = self.module_info(namespace, name)

      dep = info.get("dependencies",[])
      if not dependency in dep:
        dep.append(dependency)
        info["dependencies"] = dep
        self.module_update_info(namespace, name, info)

    except:
      raise

  #############################################################################

  def module_is_valid(self, name, exact=True):

    """
    Check if a module name is valid (eg. a module with that name or prefix
    exists)

    Args:

    name <string> full or partial module name. In this case partial means partial
                 to the prefix so if the exact module name is "twentyc.some.module"
                 then valid partial names are "twentyc" and "twentyc.some"

    exact <bool> if true only return true if a module with the exact name match
                 exists. If false return true on the first prefix matching the
                 name. eg. a module named "twentyc.chart" would validate a check
                 for name "twentyc" if the "exact" argument is false.
    """

    try:

      index = self.module_index().get("modules")
      name = name.lower()
      i = 1

      exact_exists = index.has_key(name)

      if exact or exact_exists:
        return exact_exists

      name = "%s." % name
      
      for module in index.keys():
        if module.find(name) == 0:
          return True
          
      return False

    except:
      raise

 
  #############################################################################

  def xbahn_set(self, xbahn):
    
    """
    Allows linking an xbahn object to the module manager instance. If linked
    updates to user perms will be broadcast to the xbahn amq exchange.
    """

    self.xbahn = xbahn
    module_reload = self.xbahn.listen("__vodka.control.reload_modules_for_client")
    if module_reload:
      module_reload.callbacks.append(self.xbahn_perms_reload)

  def set_xbahn(self, xbahn):
    self.xbahn_set(xbahn)

  #############################################################################

  def xbahn_perms_reload(self, msg, data):
    user_id = data.get("user_id")
    self.perms(user_id, update_cache=True)

  #############################################################################

  def user_data(self, user_id):
    return self.cb_client.get(self.perms_key(user_id)) or {
      "type" : "module_perms",
      "user_id" : user_id,
      "perms" : {},
      "groups" : []
    }

  #############################################################################

  def perms_key(self, user_id):

    """
    Return the key name of a user's permission storage
    """

    return "U%s.perms" % user_id

  #############################################################################

  def pgroup_key(sellf, name):
    
    """
    Return the key name of the specified permission group
    """

    return "permgroup.%s" % name

  #############################################################################

  def perms(self, user_id, details=False, update_cache=False):
    
    """
    Return the perms dict for the specified user id
    """

    key = self.perms_key(user_id)

    if not details:
      cache_key = key
    else:
      cache_key = "%s-D" % key

    if self.use_cache and not update_cache and self.cache.has_key(cache_key):
      #print "returning perms from cache %s -> %s" % (key, cache_key)
      return self.cache.get(cache_key)

    data = self.cb_client.get(key) or {}
    perms = {}
   
    # apply perms from user groups
    for group in data.get("groups",[]):
      group_data = self.pgroup(group)
      for namespace, lvl in group_data.get("perms", {}).items():
        perms[namespace] = lvl
        
      if details:
        perms_d = {}
        for namespace, lvl in perms.items():
          perms_d[namespace] = { 
            "user_id" : user_id, 
            "level" : lvl, 
            "sources" : ["group"] 
          }
  

    # apply user perms
    for namespace, lvl in data.get("perms", {}).items():
      diff = lvl & ~perms.get(namespace, 0)
      if diff and perms.has_key(namespace) and lvl:
        # extend perms to namespace
        perms[namespace] ^= diff
      elif not perms.has_key(namespace) or not lvl:
        # add perms to namespace
        perms[namespace] = lvl
 
      if details:
        if not perms_d.has_key(namespace):
          perms_d[namespace] = { 
            "user_id" : user_id, 
            "level" : perms[namespace], 
            "sources" : ["user"] 
          }
        else:
          perms_d[namespace]["level"] = perms[namespace]
          if "user" not in perms_d[namespace]["sources"]:
            perms_d[namespace]["sources"].append("user")


    if not details:
      if self.use_cache:
        #print "updating perms to cache %s -> %s: %s" % (key, cache_key, perms)
        self.cache[cache_key] = perms
      return perms
    else:
      if self.use_cache:
        #print "updating perms to cache %s -> %s: %s" % (key, cache_key, perms_d)
        self.cache[cache_key] = perms_d
      return perms_d

  #############################################################################
  
  def pgroup(self, name):
    
    """
    Return the data object for a permission group
    """

    key = self.pgroup_key(name)
    data = self.cb_client.get(key) or {
      "name" : name,
      "perms" : {},
      "type" : "permission_group"
    }

    return data

  #############################################################################

  def pgroup_list(self, id=False):
    
    """
    Return a list of all permission groups
    """

    rv = []

    for row in self.cb_client.view("vodka", "permission_groups"):
      if not id:
        rv.append(row.get("key"))
      else:
        rv.append(row.get("id"))

    return rv

  #############################################################################

  def perms_log_view(self, user_id, limit=None):
    """
    Retrieve permission log entries for the specified user

    user_id <int>
    limit <int> result limit - can be None to specify no limit
    """

    try:
      result = self.cb_client.view(
        "vodka", 
        "permission_log", 
        startkey=[user_id,{}],
        endkey=[user_id],
        descending=True,
        limit=limit
      )

      docs = []
      for row in result:
        docs.append(row.get("value"))
      return docs
        
    except:
      raise

  #############################################################################

  def perms_log_change(self, user_id, prefix, level, source="", reason="", extra={}):

    """
    Log permission changes

    user_id <int> 
    prefix <string> module name space or whole module name 
    level <int>
    source <string> source of the change eg. "appstore purchase" or "user <user_id>"
    reason <string> reason for change eg. "subscription end"
    """

    try:
      if self.disable_perms_log:
        return
      
      key = "permission-changes:%d-%s" % (user_id, uuid.uuid4())

      self.cb_client.set(
        key,
        {
          "time" : time.time(),
          "type" : "permission_change_log",
          "user_id" : user_id,
          "source" : source or "unknown",
          "level" : level,
          "module_namespace" : prefix,
          "extra" : extra or {},
          "reason" : reason or "unknown"
        }
      )

    except:
      raise

  #############################################################################

  def perms_set(self, user_id, prefix, level, force=False, source="", reason="", xbahn_sync=True, extra={}):
    
    """
    Set a user's access permissions for a module prefix

    level flags

    0x01 read
    0x02 write
    0x04 write xbahn stream

    if you pass -1 to level the entry will be removed

    if you pass 0 to level it will deny any access to the module

    Args:

    user_id <int> user id
    prefix <string> module name space or whole module name 
    level <int> see above
    force <bool> if true set perms to the specified modules forcably 
    """

    try:

      if type(level) != int:
        raise Exception("Tried to set invalid permission level for user '%s' on module '%s': %s" %(
          user_id, prefix, level
        ))

      if type(user_id) != int:
        raise Exception("user_id needs to be of type: int")

      if type(prefix) not in [str, unicode]:
        raise Exceptipn("prefix needs to be of type: str or unicode")
      
      if level > -1 and prefix[0] == "_":
        raise Exception("'%s' is a private subject and cannot be provisioned on a per user basis." % prefix)

      user_data = self.user_data(user_id)
      perms = user_data.get("perms")
      old_perms = copy.copy(perms)

      if level == -1 and perms.has_key(prefix):
        del perms[prefix]
      elif level > -1:

        is_valid = self.module_is_valid(prefix, exact=False)

        if is_valid or force:
          perms[prefix] = level
        else:
          raise InvalidModuleException("Invalid module. Name or prefix doesn't exist: %s" % prefix)

      user_data["user_id"] = user_id

      self.cb_client.set(self.perms_key(user_id),user_data)

      self.perms_log_change(
        user_id,
        prefix,
        level,
        source=source,
        reason=reason,
        extra=extra or {}
      )

      # if xbahn property is set, broadcast the permission updates
      # to the xbahn amq exchange
      
      modifies, removed = self.perms_diff(old_perms, perms)

      if xbahn_sync:
        # passing {} here causes a full sync on the vodka side
        self.xbahn_notify_module_reload(user_id, {})
      if self.use_cache:
        self.perms(user_id, update_cache=True)

      return (modifies, removed)

    except:
      raise

  #############################################################################

  def perms_check(self, user_id, prefix, ambiguous=False):
    
    """
    Return the user's perms for the specified prefix

    user_id <int|dict> can either be user id or a dict of perms gotten via self.perms()

    prefix <string> namespace to check for perms

    ambiguous <bool=False> if True reverse wildcard matching is active and a perm check for a.b.* will
    be matched by the user having perms to a.b.c or a.b.d - only use this if you know what 
    you are doing.
    """

    try:
     
      if type(user_id) == dict:
        perms = user_id
      else:
        perms = self.perms(user_id)

      return session.perms_check(perms, prefix, ambiguous=ambiguous)

    except:
      raise

  #############################################################################

  def perms_purge(self, user_id, source="", reason = "", xbahn_sync=True):
    
    """
    Remove all permission entries for the specified user_id
    """

    try:
      
      key = self.perms_key(user_id)
      data = self.cb_client.get(key)
      perm_keys = data.get("perms", {}).keys()
      if data:
        data["perms"] = {}
      self.cb_client.set(key, data)

      for prefix in perm_keys: 
        self.perms_log_change(
          user_id,
          prefix,
          -1,
          source = source,
          reason = reason
        )

      # if xbahn property is set, broadcast the permission updates
      # to the xbahn amq exchange

      if self.xbahn:
       
        r = {}
        for key in perm_keys: 
          r[key] = None

        if xbahn_sync:
          self.xbahn_notify_module_reload(user_id, {})

      if self.use_cache:
        self.perms(user_id, update_cache=True)

    except:
      raise

  #############################################################################

  def pgroup_grant(self, group_name, user_id, source="", reason="", xbahn_sync=True):
    try:

      user = self.user_data(user_id)
      
      # user already member of that group
      if group_name in user.get("groups",[]):
        return

      pgroup = self.pgroup(group_name).get("perms",{})
      
      # get the perms that would be modified by that group (relative to the
      # users current perms)
      modifies, removed = self.perms_diff(
        self.perms(user_id), pgroup
      )

      if not user.has_key("groups"):
        user["groups"] = [group_name]
      else:
        user["groups"].append(group_name)

      user["user_id"] = user_id
      
      # log change
      self.perms_log_change(
        user_id,
        "group:%s" % group_name,
        1,
        source = source,
        reason = reason
      )

      # save change
      self.cb_client.set(self.perms_key(user_id), user)

      reason_r = "group '%s' granted" % group_name
      if reason:
        reason_r = "%s: %s" % (reason_r, reason)

      for mod, level in modifies.items():
        self.perms_log_change(
          user_id,
          mod,
          level,
          source=source,
          reason=reason_r
        )
 
      # broadcast change to xbahn
      if xbahn_sync:
        self.xbahn_notify_module_reload(user_id, {})
      if self.use_cache:
        self.perms(user_id, update_cache=True)

      return (modifies, removed)

    except:
      raise
     
  #############################################################################

  def pgroup_revoke(self, group_name, user_id, source="", reason="", xbahn_sync=True):
    try:

      t1 = time.time()
      user = self.user_data(user_id)
      
      # user not a member of that group
      if group_name not in user.get("groups",[]):
        return

 
      pgroup = self.pgroup(group_name).get("perms")
      
      user["groups"].remove(group_name)
      user["user_id"] = user_id
      
      # log change
      self.perms_log_change(
        user_id,
        "group:%s" % group_name,
        0,
        source = source,
        reason = reason
      )

      # save change
      t2 = time.time()
      self.cb_client.set(self.perms_key(user_id), user)
      t3 = time.time()
      
      # get the perms that would be modified by that group (relative to the
      # users current perms)
      modifies, removed = self.perms_diff(
        pgroup, self.perms(user_id)
      )

      t4 = time.time()
      
      reason_r = "group '%s' revoked" % group_name
      if reason:
        reason_r = "%s: %s" % (reason_r, reason)

      for mod, level in removed.items():
        self.perms_log_change(
          user_id,
          mod,
          0,
          source=source,
          reason=reason_r
        )

      t5 = time.time()

      # broadcast change to xbahn
      if xbahn_sync:
        self.xbahn_notify_module_reload(user_id, {})
      if self.use_cache:
        self.perms(user_id, update_cache=True)

      t6 = time.time()

      print "revoke %.5f %.5f %.5f %.5f %.5f" % (
        (t2 - t1),
        (t3 - t2),
        (t4 - t3),
        (t5 - t4),
        (t6 - t5)
      )

      return (modifies, removed)

    except:
      raise

  #############################################################################

  def pgroup_perms_set(self, group_name, prefix, level, force=False, xbahn_sync=True, source="", reason=""):

    try:
      pgroup = self.pgroup(group_name) 
      perms = pgroup.get("perms")
      removed = {}
      modified = {}

      if type(level) != int:
        raise Exception("Tried to set invalid permission level for group '%s' on module '%s': %s" %(
          group_name, prefix, level
        ))

      if level > -1 and prefix[0] == "_":
        raise Exception("'%s' is a private subject and cannot be provisioned in a permission group." % prefix)

      if level == -1 and perms.has_key(prefix):
        del perms[prefix]
        removed[prefix] = 0
      elif level > -1:
        is_valid = self.module_is_valid(prefix, exact=False)

        if is_valid or force:
          perms[prefix] = level
          modified[prefix] = level
        else:
          raise InvalidModuleException("Invalid module. Name or prefix doesn't exist: %s" % prefix)
 
      self.cb_client.set(self.pgroup_key(group_name), pgroup)

      if xbahn_sync:
        self.pgroup_sync(group_name, modified, removed, source=source, reason=reason)
    except:
      raise

  #############################################################################

  def pgroup_update(self, group_name, perm_set, xbahn_sync=True, source="", reason=""):
    try:

      pgroup = self.pgroup(group_name)

      oldperms = pgroup.get("perms",{})
      
      for namespace, level in perm_set.items():
        if type(level) != int:
          raise InvalidLevelException("Tried to set invalid permission level for group '%s' on module '%s': %s" %(
            group_name, namespace, level
          ))

        if namespace[0] == "_":
          raise PrivateNamespaceException("'%s' is a private subject and cannot be provisioned in a permission group." % namespace)


      diff_reload, diff_unload = self.perms_diff(oldperms, perm_set)

      pgroup["perms"] = perm_set

      self.cb_client.set(self.pgroup_key(group_name), pgroup)

      if xbahn_sync:
        self.pgroup_sync(group_name, diff_reload, diff_unload, source=source, reason=reason)

      return (diff_reload, diff_unload)

    except:
      raise

  #############################################################################

  def pgroup_remove(self, group_name, source="", reason=""):

    try:
      users = self.pgroup_users(group_name)
      for user_id in users:
        self.pgroup_revoke(group_name, user_id, source=source, reason="group %s removed: %s" % (group_name, reason))
      self.cb_client.unset(self.pgroup_key(group_name))
    except:
      raise

  #############################################################################

  def pgroup_sync(self, group_name, reload, unload, source="", reason=""):
    
    if not self.xbahn:
      return

    pgroup = self.pgroup(group_name)

    reason_r="group '%s' updated - user's perms after change" % group_name
    if reason:
      reason_r="%s: %s" % (reason_r, reason)

    for user_id in self.pgroup_users(group_name):
      self.xbahn_notify_module_reload(user_id, {})
      
      perms = self.perms(user_id)

      for mod in unload:
        if not self.perms_check(perms, mod):
          self.perms_log_change(
            user_id,
            mod,
            0,
            source=source,
            reason=reason_r
          )

      for mod, level in reload.items():
        if not self.perms_check(perms, mod) != level:
          self.perms_log_change(
            user_id,
            mod,
            self.perms_check(perms, mod),
            source=source,
            reason=reason_r
          )
  
    self.xbahn_notify_pgroup_update(group_name)
   

  #############################################################################
  
  def pgroup_users(self, group_name):
    rv = []

    users = self.cb_client.view(
      "vodka", "users_by_pgroup", stale=False, key=group_name
    )
    for row in users:
      rv.append(row.get("value"))

    return rv
  
  #############################################################################
  #############################################################################
  #############################################################################

  def perms_diff(self, perms_a, perms_b):

    """
    Returns 2 dicts in a tuple

    First dict holds namespaces affected by permset b when applied over permset a
    Second dict hold namespaces that exist in a but not in b
    """
    
    rv = {} 
    rv_r = {} 

    for namespace, lvl in perms_b.items():

      diff = lvl & ~perms_a.get(namespace,0)

      if diff:
        rv[namespace] = perms_a.get(namespace, 0) ^ diff
      elif not perms_a.has_key(namespace):
        rv[namespace] = lvl

   
    for namespace, lvl in perms_a.items():

      if namespace not in perms_b:
        rv_r[namespace] = 0

    return (rv, rv_r)



  #############################################################################

  def xbahn_notify_module_reload(self, user_id, modules):
    if self.xbahn and user_id:
      self.xbahn.send(None, "__vodka.control.reload_modules_for_client", {
        "user_id" : user_id,
        "modules" : modules
      })

  #############################################################################
  
  def xbahn_notify_module_unload(self, user_id, modules):
    if self.xbahn and user_id and modules:
      self.xbahn.send(None, "__vodka.control.unload_modules_for_client" % user_id, {
        "user_id" : user_id,
        "modules" : modules
      })

  #############################################################################

  def xbahn_notify_pgroup_update(self, group_name):
    if self.xbahn and group_name:
      self.xbahn.send(None, "__vodka.ALL.permgroup_update", {
        "group" : group_name
      })

  #############################################################################
  #############################################################################
  #############################################################################
  #############################################################################


