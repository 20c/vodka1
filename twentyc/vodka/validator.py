###############################################################################
# Validate json structures according to customized validation specs

import simplejson as json
import constants
import re
import sys
import copy

# stores the different validators, indexed by id
validators = {}
import time

###############################################################################

def add_from_json(json_string):
  """
  add a validator using a json string
  """
  #validators.update(json.loads(json_string))

  # update

  vset = json.loads(json_string)

  for name, structure in vset.items():
    if validators.has_key(name) and type(validators[name]) == dict:
      if type(structure) == dict and structure.has_key("data"):
        validators[name]["data"].update(structure.get("data"))
      elif type(structure) == dict and re.match("__share__.+",name):
        validators[name].update(structure)
      else:
        validators[name] = copy.deepcopy(structure)
    else:
      validators[name] = copy.deepcopy(structure)

  # apply extensions

  for name, structure in validators.items():
    if type(structure) == dict and structure.has_key("extend"):
      extend = structure.get("extend")
      if type(extend) in [str, unicode]:
        extend = validators.get(extend)
        if extend and extend.has_key("data") and structure.has_key("data"):
          structure["data"].update(extend.get("data"))
          del structure["extend"]
        elif extend:
          structure.update(extend)
          del structure["extend"]
  

###############################################################################

def add_from_file(file_path):
  """
  add a validator from file
  """
  f = open(file_path, "r")
  json_string = f.read()
  f.close()
  add_from_json(json_string)
  #print "Loaded validators from file: %s" % file_path

###############################################################################

class ValidationException(Exception):
  pass

###############################################################################

class Validator(object):

  #############################################################################

  def __init__(self, verbose=False):
    self.validators = validators
    self.verbose = verbose

  #############################################################################

  def dbg(self, msg):
    if self.verbose:
      print "Validator: %s" % msg

  #############################################################################

  def validate(self, document, validator_name=None, **kwargs):
    """
    Validate the specified document (dict).
    """

    if type(document) != dict:
      raise ValidationException("Tried to pass non-dict target to validate()")
    
    v_doc = {}
    v_doc[validator_name] = document
    validator = self.validators.get(validator_name)

    if not validator:
      return
   
    data = validator.get("data", {})
    allow_unknown = validator.get("allow_unknown", False)
    
    self.validate_key(validator_name, document, validator, {}, validator_name)

  #############################################################################

  def purge(self, document, key, name):
    self.dbg("Removing %s:%s" % (key, name));
    del document[key]

  #############################################################################

  def validate_key(self, key, value, specs, document, name):
    val = None
    
    if type(key) in [str, unicode] and key[0] == '_':
      return self.purge(document, key, name)

    if type(specs) in [str, unicode]:
      if specs == "any":
        return
      key_type = specs
      minimum = None
      maximum = None
    elif type(specs) == dict:
      key_type = specs.get("type")
      name = specs.get("label", name)
      if key_type == "any":
        if type(value) in [str, unicode] and specs.get("string"):
          key_type = "string"
          specs = specs.get("string")
        elif type(value) == int and specs.get("int"):
          key_type = "int"
          specs = specs.get("int")
        elif type(value) == float and specs.get("float"):
          key_type = "float"
          specs = specs.get("float")
        elif type(value) == bool and specs.get("bool"):
          key_type = "bool"
          specs = specs.get("bool")
        elif type(value) == dict and specs.get("dict"):
          key_type = "dict"
          specs = specs.get("dict")
        elif type(value) == dict and specs.get("dict_list"):
          key_type = "dict_list"
          specs = specs.get("dict_list")
        else:
          self.purge(document,key,name)
          return
      
      minimum = specs.get("min", None)
      maximum = specs.get("max", None)

    else:
      raise ValidationException("Unknown data type for %s" % name)
    
    self.dbg("Validating %s (%s) to %s, specs type: %s, max: %s" % (
      name,
      key,
      key_type,
      type(specs),
      maximum
    ))

    
    # validate normal strings
    if key_type == "string":
      try:
        if type(value) in [dict,list]:
          raise Exception("We dont serialize lists or dicts")
        val = unicode(value)
      except:
        raise ValidationException(constants.ERR_VALUE_STR % name)
        
    # validate label strings
    elif key_type == "string_label":
      try:
        if type(value) in [dict,list]:
          raise Exception("We dont serialize lists or dicts")
 
        val = unicode(value)
      except:
        raise ValidationException(constants.ERR_VALUE_STR % name)

      if type(maximum) != int:
        maximum = 50
        
      #validate cleaness of label
      m = re.findall("[^a-zA-Z0-9_\-\.: #+*]", str(val))
      if m:
        a = []
        for k in m:
          if k not in a:
            a.append(k)
        raise ValidationException(constants.ERR_KEY_INVALID_CHARACTER % (name, unicode(a)))

    # validate ints
    elif key_type == "int":
      try:
        if value == None:
          value = 0
        val = int(value)
      except:
        raise ValidationException(constants.ERR_VALUE_INT % name)
   
    # validate ints (positive)
    elif key_type == "int_pos":
      try:
        if value == None:
          value = 0
        val = int(value)
        if type(minimum) != int:
          minimum = 0
      except:
        raise ValidationException(constants.ERR_VALUE_INT % name)



    # validate floats
    elif key_type == "float":
      try:
        if value == None:
          value = 0.0
        val = float(value)
      except:
        raise ValidationException(constants.ERR_VALUE_FLOAT % name)

    # validate booleans 
    elif key_type == "bool":
      try:
        if value == None:
          value = False
        val = bool(int(value))
      except:
        raise ValidationException(constants.ERR_VALUE_BOOL % name)

    # validate lists
    elif key_type == "list":
      if type(value) != list:
        raise ValidationException(constants.ERR_VALUE_LIST % name)
      
      l = 0
      if type(maximum) == int:
        l = len(value)
        if l > maximum:
          raise ValidationException(constants.ERR_LIST_LENGTH % (name,maximum))

      if type(minimum) == int:
        if not l:
          l = len(value)
        if l < minimum:
          raise ValidationException(constants.ERR_LIST_INCOMPLETE % (name,minimum))


      # get validator link if it exists
      link = specs.get("validator")
      if link: 
        link = link.format(__key=key, **document)
        self.dbg("loading linked validator for %s: %s" % (name, link))
        link = self.validators.get(link)
        if not link and specs.has_key("fallback_validator"):
          link = specs.get("fallback_validator")
          link = link.format(__key=key, **document)
          self.dbg("required validator wasnt found, trying fallback validator: %s" % (link))
          link = self.validators.get(link)
 
      i = 0
      for item in value:
        subspecs = specs.get("data")
        
        if not subspecs and link:
          subspecs = link

        if type(subspecs) == list:
          subspecs = subspecs[i]
        self.validate_key(i, item, subspecs, value, "%s[%d]" % (name,i))
        i += 1

    # validate dicts
    elif key_type == "dict":
      if type(value) != dict:
        raise ValidationException(constants.ERR_VALUE_DICT % name)

      # make sure required keys are there
      if type(specs) == dict:
        req = specs.get("require")
        if req == "all":
          req = specs.get("data", {}).keys()

        if type(req) == list:
          for req_key in req:
            if value.get(req_key,None) in [None,""]:
              raise ValidationException(constants.ERR_VALUE_EMPTY % "%s.%s" % (name, req_key))
    
        # get validator link if it exists
        link = specs.get("validator")
        if link: 
          link = link.format(__key=key, **document)
          self.dbg("loading linked validator for %s: %s" % (name, link))
          link = self.validators.get(link)
          if not link and specs.has_key("fallback_validator"):
            link = specs.get("fallback_validator")
            link = link.format(__key=key, **document)
            self.dbg("required validator wasnt found, trying fallback validator: %s" % (link))
            link = self.validators.get(link)
      
      # validate dict items
      for subkey, subvalue in value.items():
       
        if type(specs) == dict:
          subspecs = specs.get("data",{}).get(subkey)
          if not subspecs:
            subspecs = specs.get("data",{}).get("*")
          if not subspecs and link:
            subspecs = link.get("data",{}).get(subkey)
        else:
          subspecs = "any"

        if subspecs:
          self.validate_key(subkey, subvalue, subspecs, value, "%s.%s" % (name, subkey))
        else:
          if not specs.get("allow_unknown"):
            self.purge(value, subkey, name)
          continue

    # validate dict lists
    elif key_type == "dict_list":
      if type(value) != dict:
        raise ValidationException(constants.ERR_VALUE_DICT % name)
     
      keys = value.keys()

      if type(maximum) == int:
        if len(keys) > maximum:
          raise ValidationException(constants.ERR_LIST_LENGTH % (name, maximum))
      
      subspecs = specs.get("data")
      subspecs = {
        "type" : subspecs.get("type"),
        "max" : subspecs.get("max"),
        "min" : subspecs.get("min"),
        "validator" : subspecs.get("validator"),
        "string" : subspecs.get("string"),
        "int" : subspecs.get("int"),
        "float" : subspecs.get("float"),
        "dict" : subspecs.get("dict"),
        "dict_list" : subspecs.get("dict_list"),
        "bool" : subspecs.get("bool"),
        "require" : subspecs.get("require"),
        "data" : subspecs.get("data",{})
      }
      for subkey, subvalue in value.items():
        #print "Validate DICT LIST %s with subspecs %s" % (subkey,subspecs)
        self.validate_key(subkey, subvalue, subspecs, value, "%s.%s" % (name,subkey))


    # apply maximum - minimum limits on strings and numbers

    if type(val) == unicode:
      if type(maximum) == int:
        if len(val) > maximum:
          raise ValidationException(constants.ERR_KEY_LENGTH % (name, maximum))
      if type(minimum) == int:
        if len(val) < minimum:
          raise ValidationException(constants.ERR_KEY_LENGTH_SHORT % (name, minimum))
      document[key] = val
    elif type(val) in [int, float]:
      if type(maximum) == int and val > maximum:
        raise ValidationException(constants.ERR_VALUE_TOO_BIG % (name, maximum))
      if type(minimum) == int and val < minimum:
        raise ValidationException(constants.ERR_VALUE_TOO_SMALL % (name, minimum))
      document[key] = val
    elif type(val) == bool:
      document[key] = val
      

    return True
 

  #############################################################################

  def validate_shared_data(self, data):
    """
    Removes any keys from data <dict> that are not flagged for sharing.

    Sharing validators will be loaded for the root keys in the dict.

    Sharing validators should be flagged with a "__share__" prefix in the
    validation specs.

    Example:

    { "app" : ... , "color_theme.my theme" : ... } will look for validators
    named __share__app and __share__color_theme

    If no sharing validator is found for a key then that key and all the data
    it holds will be thrown out.
    """

    try:
      
      for key, document in data.items():
        doctype = key.split(".")[0]
        validator = self.validators.get("__share__%s" % doctype)
        
        # no validator is found for root key / doctype, throw out
        # the data and move on to the next key
        if not validator or re.match("^(__|:).*", key):
          self.purge(data, key, key);
          continue


        self.dbg("Validating Shared Data: %s" % doctype)
        self.remove_private_keys(document)
        if type(validator) == bool and validator:
          continue

        for subkey,  subdata in document.items():
          self.validate_shared_subdata(document, subkey, subdata, validator.get(subkey))

    except:
      raise

  #############################################################################

  def validate_shared_subdata(self, document, key, data, validator):
    try:


      if type(validator) in [str, unicode]:
        validator = validator.format(__key=key, **document)
        validator = self.validators.get(validator)
        self.dbg("%s" % validator)
      elif type(validator) == bool and validator:
        return

      if not validator:
        return self.purge(document, key, key)

      if type(data) == list:
        subkey = 0
        for subdata in data:
          self.validate_shared_subdata(data, subkey, subdata, validator)
          subkey += 1

      elif type(data) == dict:
        for subkey, subdata in data.items():
          self.validate_shared_subdata(data, subkey, subdata, validator.get(subkey))

      else:
        if not validator:
          self.purge(document, key, key)

    except:
      raise

  #############################################################################

  def remove_private_keys(self, document):
    for key, data in document.items():
      if re.match("^(__|:).*", key):
        self.purge(document, key, key)
      elif type(data) == dict:
        self.remove_private_keys(data)

  #############################################################################
  #############################################################################
  #############################################################################
  #############################################################################
  #############################################################################
  #############################################################################
  #############################################################################


