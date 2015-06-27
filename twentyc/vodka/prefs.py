"""
Functions and classes to handle loading, changing and saving of user prefs 
stored in a couchbase database
"""

import constants
import traceback
import threading
import base64
import re
import validator
import copy
import simplejson as json

MAX_KEY_LENGTH = 255

# store valid document types
documents = [
  "app",
  "mobile_app",
  "layout",
  "color_theme",
  "setups",
  "sounds"
]

# modules can use this dict to add their own document types
documents_from_modules = {}

# define expected storage types of a doctype (eg. single or multiple instance)
document_storage = {
  "app" : "single",
  "mobile_app" : "single",
  "layout" : "multi",
  "color_theme" : "multi",
  "setups" : "single",
  "sounds" : "single"
}

document_limits = {
}

###############################################################################
# Functions

###############################################################################

class ValidationException(Exception):
  trigger = ""
  traceback = ""

###############################################################################

class DoctypeLimitException(Exception):
  def __init__(self, doctype, limit):
    Exception.__init__(self, constants.ERR_DOCTYPE_LIMIT % (doctype, limit))

###############################################################################

class PrefManager(object):

  #############################################################################

  def __init__(self, ses):
    
    """
    Initialize the PrefManager instance with a session.
    
    Args
    
    ses <Session> Session instance
    """

    try: 
      
      # set this to true if you want to see whats happening
      self.verbose = False 

      self.ses = ses
      
      # reference to vodka app config
      self.config = ses.app.config
      
      # cache config documents
      self.cache = {}

      # thread locks
      self.lockSet = threading.RLock()

      # for validating pref documents
      self.validator = validator.Validator()

      self.dbg("loaded for session %d" % ses.id)
    except:
      raise


  ############################################################################
  
  def dbg(self, msg):
    if self.verbose:
      print "PrefManager: %s" % msg

  ############################################################################

  def error(self, msg):
    raise Exception("PrefManager: %s" % msg)

  ############################################################################

  def prefix(self):
    
    """
    Returns storage key prefix for this PrefManager instance / session combo
    """

    if self.ses and self.ses.is_authed():

      try:
         
        prefix = self.ses.app.couch_config.get("prefix_prefs")
        if not prefix:
          self.error("Missing %s config: prefix_prefs" % self.ses.app.couch_engine)
        prefix = prefix % self.ses.user_id
        return prefix

      except:
        raise
     
    else:

      return None 

  ############################################################################

  def update(self, config):
    
    """
    update multiple document types via a dict structure. Keys at the root
    level should be valid document identifiers eg. "app" or "layout"

    Keys at the second level will be updated in the targeted document. Note
    that a key not existing at the second level will not remove it from the
    document, but anything past and including the third level will be treated
    as absolute.

    example:

    {
      #update the app document
      "app": {
        
        # overwrite these values in the "app" document namespace
        "update_speed" : 1, # will get overwritten

        # will also get overwritten completely as is, the previous
        # state of this config key will be gone, so make sure that in this 
        # example the brackets list is holding all brackets that you want
        # to store.
        "brackets" : [
          ...
        ]
      }
    }
    """
    
    for doc_name, doc in config.items():
      
      #load the current document
      current = self.get(doc_name)
      
      #validate the new incoming data 
      validate_name = doc_name.split(".")[0]

      self.validator.validate(doc, validate_name)

      #update the current document
      current.update(doc)
      self.set(doc_name, current, validate=False)

  ############################################################################

  def update_by_key_list(self, items):

    """
    update config documents using a list of serialized keys. 

    Args

    items <dict> dict of serialized keys with values. 
    
      example

        {
          "app->update_speed" : 1,
          "app->context_menus" : 1,
          "app->some.nested.value" : 1,
          "sound->volume" : 100
        }
    """

    documents = []

    for key,value in items.items():
      
      keys = key.split("->")
      base_name = keys[0]
      keys = keys[1].split(".")

      if not base_name in documents:
        documents.append(base_name)
      
      doc = self.get(base_name)
      if len(keys) > 1:
        for token in keys[0:-1]:
          if not doc.has_key(token) or type(doc.get(token)) != dict:
            doc[token] = {}
          doc = doc.get(token)
      doc[keys[-1]] = value 

    for doc_name in documents:
      doc = self.get(doc_name)
      self.set(doc_name, doc)
        
      
  ############################################################################

  def clean_key(self, key):
    
    if len(key) > MAX_KEY_LENGTH:
      raise ValidationException(constants.ERR_KEY_LENGTH % ("key", MAX_KEY_LENGTH))

    m = re.findall("[^a-zA-Z0-9_\-\. #+*]", key)
    if m:
      a = []
      for k in m:
        if k not in a:
          a.append(k)

      raise ValidationException(constants.ERR_KEY_INVALID_CHARACTER % ("key", str(a)))
     

  ############################################################################

  def delete(self, key):
    """
    Delete the couchbase document at the specific key

    key <string> id key of the config object in the couchbase database. appropriate
    prefix will automatically be prepended, so you only need to provide the base 
    key, eg. "quoteboard" to get the quoteboard config
    """
    client = None

    try:
      if not self.ses.is_authed():
        return 

      self.clean_key(key)

      if self.cache.has_key(key):
        del self.cache[key]

      full_key = "%s.%s" % (self.prefix(), key)

      client = self.ses.get_client()
      self.dbg("Deleting: %s" % full_key)
      client.db_prefs.unset(full_key)

      self.document_unpin(key.split(".")[0], key)
      
      # apply post processor for document type if it exists
      doctype = key.split(".")[0]
      ondel = "on_delete_%s" % doctype
      if hasattr(self, ondel):
        ondel = getattr(self, ondel)
        ondel(key)

    except:
      raise
    finally:
      if client:
        self.ses.free_client(client)


  ############################################################################

  def document_check_limits(self, doctype, key):

    """
    Check if there is room for the proposed doctype creation.

    If the document key already exists do nothing.

    If the document key does not exist and the limit for the specified
    doctype is reached raise a DoctypeLimitException

    Args:

    doctype <string> valid known doctype eg. "layout"

    key <string> doc key string eg. "layout.MyNewLayout"


    Returns:

    True if its ok to add another document for this doctype
    """

    if doctype == "sys":
      return True

    limit = document_limits.get(doctype, None)
    if type(limit) != int:
      limit = 1

    sysconfig = self.get("sys")
    documents = sysconfig.get("documents",{})
    tracker = documents.get(doctype,[])

    if(key in tracker):
      return True

    if(len(tracker) >= limit):
      raise DoctypeLimitException(doctype, limit)
    else:
       return True

  ############################################################################
    
  def document_pin(self, doctype, key):
    if doctype == "sys" or key == doctype:
      return True

    sysconfig = self.get("sys")
    documents = sysconfig.get("documents",{})
    tracker = documents.get(doctype,[])

    if(key in tracker):
      return True
    
    tracker.append(key)

    documents[doctype] = tracker
    sysconfig["documents"] = documents
    self.set("sys", sysconfig)

  ############################################################################
  
  def document_unpin(self, doctype, key):
    if doctype == "sys" or key==doctype:
      return True

    sysconfig = self.get("sys")
    documents = sysconfig.get("documents",{})
    tracker = documents.get(doctype,[])

    if(key not in tracker):
      return True
    
    tracker.remove(key)
    documents[doctype] = tracker
    sysconfig["documents"] = documents
    self.set("sys", sysconfig)


  ############################################################################

  def set(self, key, data, validate=True, **kwargs):
    
    """
    save a data object at the specified key

    Args
    
    key <string> id key of the config object in the couchbase database. appropriate
    prefix will automatically be prepended, so you only need to provide the base 
    key, eg. "quoteboard" to get the quoteboard config

    data <dict> config document to be saved
    
    type <string> config documen type eg "layout", "base" etc.
    """

    self.lockSet.acquire()
    client = None

    if not self.ses or not self.ses.is_authed():
      return

    try:


      self.clean_key(key)
      
      if type(data) != dict:
        self.error("Tried to pass non-dict object as data to set()")
      
      tokens = key.split(".")
      doctype = tokens[0]

      # check limits
      if len(tokens) > 1:
        if document_storage.get(doctype, "single") != "multi":
          raise ValidationException("'%s' cannot store nested keys" % doctype)
        self.document_check_limits(doctype, key)

      if validate:
        self.validator.validate(data, doctype)
      
      # apply preparation processor for document type if it exists
      prepare = "prepare_%s" % doctype
      if hasattr(self, prepare):
        prepare = getattr(self, prepare)
        prepare(key, data, tokens)

      client = self.ses.get_client()
      full_key = "%s.%s" % (self.prefix(), key)
      data["%suser_id" % client.db_prefs.meta_prefix] = self.ses.user_id
      data["%stype" % client.db_prefs.meta_prefix] = doctype 
      #self.dbg("Setting %s: %s" % (full_key, data.keys()))

      if data.has_key("_rev"):
        del data["_rev"]

      client.db_prefs.set(full_key, data, retry=2)

      # update limits
      self.document_pin(doctype, key)

      # apply post processor for document type if it exists
      onset = "on_set_%s" % doctype
      if hasattr(self, onset):
        onset = getattr(self, onset)
        onset(key, data, tokens, **kwargs)

      self.cache[key] = data

    except:
      raise
    finally:
      self.lockSet.release()
      if client:
        self.ses.free_client(client)

  ############################################################################
  
  def get(self, key, load=False):

    """
    get a config object by it's key. will look in cache first, if it doesnt
    exist calls self.load
    
    Args

    key <string> id key of the config object in the couchbase database. appropriate
    prefix will automatically be prepended, so you only need to provide the base 
    key, eg. "quoteboard" to get the quoteboard config
 
    Keyword Args

    load <boolean> if true will always call self.load even if object is already
    cached
    """

    if not self.ses or not self.ses.is_authed():
      raise Exception("Trying to use pref manager with a non auth'd session")

    try:
      self.clean_key(key)
      if not self.cache.has_key(key) or load:
        return self.load(key)
      else:
        return self.cache.get(key, {})
      
    except:
      raise

  ############################################################################

  def load(self, key):
    
    """
    load and cache a config object by it's key. cached objects will be stored
    in self.cache
    
    Args

    key <string> id key of the config object in the couchbase database. appropriate
    prefix will automatically be prepended, so you only need to provide the base 
    key, eg. "quoteboard" to get the quoteboard config
    """
    
    client = None

    if not self.ses:
      return

    try:

      self.clean_key(key)
      
      #get a free client with a couchbase connection

      client = self.ses.get_client()

      #attempt to load object from the couchbase server
      
      full_key = "%s.%s" % (self.prefix(), key)
      self.dbg("Loading document: %s" % full_key)
      obj = client.db_prefs.get(full_key)

      if full_key:
        if not obj:
          obj = {}
        self.cache[key] = obj

      return obj

    except:
      raise
    finally:
      if client:
        self.ses.free_client(client)


  ############################################################################

  def import_prefs(self, data):
    """
    Imports preferences from a json string

    Args:

    data <string|dict> valid json string/dictionary holding pref documents indexed by
    document name 
    """
    try:
      
      if type(data) in [unicode,str]:
        config = json.loads(data)
      elif type(data) == dict:
        config = data
      else:
        raise Exception("Invalid import format")

      self.validator.validate_shared_data(config)
      app_config = None

      for key, value in config.items():
        if key.split(".")[0] == "layout":
          if not app_config:
            app_config = self.get("app")
            if app_config.get("default_layout","") in ["__dflt",""]:
              #print "Backing up user's current default layout."
              layout = self.layout_load_default()
              layout["name"] = "Default Layout"
              self.set("layout.Default Layout", layout)

      self.update(config)
      return config.keys()
    except:
      raise

  ############################################################################

  def export_prefs(self, targets):
    """
    Creates JSON data of targeted preferences for export.

    Args:

    targets <list> list of targets. Each target can be another list holding
    keys.

    Example:

    export_prefs([
      ["app", "brackets"],
      ["color_theme.my theme"]
    ])

    Export will be validated against validator specs for each specific
    target so if a target does not end up in the returned data object it 
    probably means the export validator threw it out and needs to be adjusted
    """

    try:

      data = {}
      
      for target in targets:
        prefs = None
        store = data
        i = 0
        for key in target:
          
          # if prefs object is empty, load the targeted prefs document
          # which should always reside in the first target key

          if not prefs:
            prefs = self.get(key)
          else:
            prefs = prefs.get(key)

          
          if i < len(target)-1:
            if not store.has_key(key):
              store[key] = {}
            store = store[key]

          i += 1

        if type(prefs) != None:
          store[target[-1]] = copy.deepcopy(prefs)

      # validate for export
      self.validator.validate_shared_data(data)

      if data: 
        return data
      else:
        return {}
        
    except:
      raise


  ############################################################################

  def layout_rename(self, layout, name):
    """
    Rename a layout
    
    Args

    layout <string> current layout name
    name <string> new layout name
    """
    if not name:
      raise Exception("No new name specified")

    if not layout:
      raise Exception("No layout specified")

    layout_data = self.get("layout.%s" % layout)
    if not layout_data:
      raise Exception("Could not load layout '%s' for rename" % layout)

    default = self.get("app",{}).get("default_layout")

    # save under new name
    self.set("layout.%s" % name, layout_data, replace=layout)
    
    # remove old layout
    self.delete("layout.%s" % layout)

    if default == layout:
      self.layout_set_default(name)

    return name



  ############################################################################

  def layout_load(self, name):
    """
    Return the config document for the layout with the specified name. Layout
    names cannot contain '.' character, so they will be stripped
    """

    if not name:
      return {}

    name = self.validate_layout_name(name)

    return self.get("layout.%s" % name)


  ############################################################################

  def layout_load_default(self):
    """
    Return the config document for this user's default layout
    """

    return self.layout_load(self.get("app").get("default_layout"))


  ############################################################################

  def layout_set_default(self, name):
    """
    Make the layout with name <name> the default layout for the user
    """

    if not name:
      return
    
    layout_config = self.get("layout.%s" % name)

    if not layout_config:
      raise Exception("Could not make layout '%s' the default layout, loading of layout failed." % name)

    self.update({ "app" : {
      "default_layout" : name
    }})

  ############################################################################

  def validate_layout_name(self, name):
    """
    Validate a config document key name and return it.
    """
    if not name:
      raise ValidationException(constants.ERR_LAYOUT_NAME_MISSING)
    return name.replace(".","-");

  ############################################################################

  def add_custom_sound(self, soundName, file):
    """
    Add a custom sound

    Args

    soundName <string>  sound name as it is define in vodka.conf

    file <data> sound file data
    """

    if not soundName:
      raise ValidationException(constants.ERR_VALUE_EMPTY%"name")

    changes = {}
    changes[soundName] = base64.b64encode(file)
    self.update({ "sounds" : changes})

    custom_sounds = self.get("app").get("custom_sounds",[]) or []
    if soundName not in custom_sounds:
      custom_sounds.append(soundName)
      self.update({ "app" : { "custom_sounds" : custom_sounds }})


  ############################################################################

  def prepare_layout(self, key, data, key_tokens):
    try:
      name = ".".join(key_tokens[1:])
      data["name"] = name
      data["id"] = name
    except:
      raise

  ############################################################################

  def on_set_layout(self, key, data, key_tokens, **kwargs):
    """
    Gets alled after a document type of type "layout" has been saved via
    set()

    Makes sure the layout name is added to app.layouts in the user's app
    preferences
    """

    try:

      name = ".".join(key_tokens[1:])
      app_config = self.get("app")

      self.load("layout.%s" % name)

      # make default if needed
      if app_config.get("default_layout") in [None, "", "__dflt"]:
        self.layout_set_default(name)
    
      if name != "__dflt" and "__dflt" in app_config.get("layouts",[]):
        self.delete("layout.__dflt")
    
      # add to layout list
      layouts = app_config.get("layouts")
      layout_tabs = app_config.get("layout_tabs", [])
      if not layouts or type(layouts) != list:
        layouts = []

      if not name in layouts:
        layouts.append(name)
        if not name in layout_tabs:
          rpl = kwargs.get("replace")
          if rpl and rpl in layout_tabs:
            layout_tabs[layout_tabs.index(rpl)] = name
          else:
            layout_tabs.append(name)

      self.update({
        "app" : {
           "layouts" : layouts,
           "layout_tabs" : layout_tabs
        }
      })

    except:
      raise

  ############################################################################

  def on_delete_layout(self, key):

    """
    Gets called after document of type layout has been deleted

    Makes sure the layour name is removed from app.layouts in the user's
    app preferences, and - if necessary - assigns a new default layout for
    the user
    """
    
    try:
      name = ".".join(key.split(".")[1:])

    
      app_config = self.get("app")

      # remove layout from layout list

      if name in app_config.get("layouts", []):
        app_config["layouts"].remove(name)

      if name in app_config.get("layout_tabs", []):
        app_config["layout_tabs"].remove(name)

      # if layout was default layout, make a different layout the default layout

      if app_config["default_layout"] == name:
        if(len(app_config.get("layouts",[]))):
          app_config["default_layout"] = app_config.get("layouts")[0]
        else:
          app_config["default_layout"] = ""

      # save app config

      self.set("app", app_config)

      # return new default layout

      return app_config["default_layout"]
    except:
      raise

  ############################################################################

  def on_delete_color_theme(self, key):
    """
    Gets called after document of type color theme has been deleted

    Makes sure the color theme name is removed from app.color_themes in the
    user's app preferences
    """

    try:
      name = ".".join(key.split(".")[1:])
      app_config = self.get("app")

      if name in app_config.get("color_themes", []):
        app_config["color_themes"].remove(name)

      self.set("app", app_config)
    except:
      raise

  ############################################################################

  def on_set_color_theme(self, key, data, key_tokens):
    
    """
    Gets called after a document of type color theme has been saved

    Makes sure the color theme name is added to app.color_themes in the user's
    app preferences.
    """

    try:
      
      name = ".".join(key_tokens[1:])

      app_config = self.get("app")
      color_themes = app_config.get("color_themes", [])
      
      if name not in color_themes:
        color_themes.append(name)
        self.update({
          "app" : {
            "color_themes" : color_themes
          }
        })


    except:
      raise


