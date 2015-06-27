import webapp
import time
import traceback
import json
import re

from webapp import HTTPCreated

def get_bool(key, **kwargs):
  return kwargs.has_key(key)

class RestException(Exception):
  
  def __init__(self, msg, code=500):
    Exception.__init__(self, msg)
    self.code = code 

class RestAPI:
  
  ErrorTypes = {
    "101" : "Unknown Type",
    "404" : "Object not found",
    "103" : "Missing Arguments",
    "104" : "Usage",
    "500" : "Internal Error",
    "401" : "Authentication Error"
  }

  def __init__(self, app, data_objects={}, obj_types={}):
    self.main_app = app
    self.config = app.config.get("rest", {})
    self.DEBUG = (self.config.get("debug") == "yes")
    self.DataObjects = data_objects
    self.ObjectTypes = obj_types;

    if self.config.get("url_regexp"):
      self.url_regexp = re.compile(self.config.get("url_regexp"))
    else:
      self.url_regexp = None

  def error(self, request, msg, code=500):
    if code >= 400:
      request["status"] = code
    else:
      request["status"] = 500
    return {
      "meta" : {
        "error_type" : code,
        "error" : "%s: %s" % (self.ErrorTypes.get(str(code),"Error"), msg)
      }
    }

  def get_session(self, req):
    return self.main_app.get_session(req)

  def request_info(self, **kwargs):
    return self.main_app.request_info(**kwargs)

  def auth(self, ses, username, password):
    return 1

  def urlargs(self, args, **kwargs):
    
    if self.url_regexp == None:
      if len(args) > 2 or len(args) < 1:
        raise RestException('/<obj_type>/<id>',code=103)
    
      obj_type = args[0]
      if not obj_type.lower() in self.DataObjects.keys():
        raise RestException(obj_type, code=101)
          
      try:
        id = args[1]
      except:
        id = kwargs.get('id')

      return (obj_type, id)
    else:
      if len(args) != 1:
        raise RestException('/%s' % self.config.get("url_regexp_help"),code=103)
        
      result = self.url_regexp.match(args[0])
      try:
        obj_type = result.group(1)
      except Exception, inst:
        obj_type = args[0]

      try:
        id = int(result.group(2)) 
      except Exception, inst:
        id = 0

      return (obj_type, id)
  

  @webapp.json_response
  def __call__(self, *args, **kwargs):
    try:
      t = time.time()
      req = self.request_info(**kwargs)
      ses = self.get_session(req)
      environ = kwargs.get("__environ")

      if self.DEBUG:
        print environ

        print "METHOD:%s" % req.get("method")
        print "GET_DATA:%s" % req.get("get_data").keys()
        print "POST_DATA:%s" % req.get("post_data").keys()
        print "DATA:%s" % kwargs.keys()
  
      auth = environ.get("HTTP_AUTHORIZATION")
      if not auth:
        auth = ["guest", "guest"]
      else:
        meth, auth = auth.split(" ")
        if meth == "Basic":
          auth = auth.decode('base64').split(":")
  
      try:
        auth_id = self.auth(ses, *auth)
      except:
        return self.error(req,"Authentication Failed", code=401)
  
      if req.get("method") == "GET":
        
        try:
          obj_type, id = self.urlargs(args , **kwargs)
        except RestException, inst:
          return self.error(req, str(inst), code=inst.code)

        if id:
          return self.rest_get_by_id(req, obj_type, id, deep=get_bool("deep", **kwargs))
        else:
          return self.rest_get_list(req, obj_type, skip=int(kwargs.get("skip",0)), limit=int(kwargs.get("limit",500)))
  
      elif req.get("method") == "POST":
  
        if not args:
          return {}
  
        try:
          obj_type = args[0]
          if len(args) > 1:
            raise Exception("Invalid API")
        except Exception, inst:
          return self.error(req,"/api/<obj_type>", code=104)

        param = req.get("post_data")
        
        if self.DEBUG:
          print "Creating %s: %s"  % (obj_type, param)
  
        try:
          if not param:
            raise Exception("",code=103);
          id = self.rest_create(req, obj_type, param)
          url = "/api/%s/%s" % (obj_type, id)
          raise HTTPCreated(url, json.dumps({"meta":{"url":url}}))
        except webapp.HTTPCreated:
          raise
        except Exception, inst:
          return self.error(req,str(inst))
  
      elif req.get("method") == "PUT":
  
        if not args:
          return {}
  
        try:
          obj_type, id = self.urlargs(args, **kwargs)
        except RestException, inst:
          return self.error(req, str(inst), code=inst.code)

        param = req.get("post_data")
       
        if self.DEBUG:
          print "Updating %s: %s"  % (obj_type, param)
  
        try:
          if not param:
            raise Exception("",code=103);
          
          self.rest_update(req, obj_type, id, param)
          url = "/api/%s/%s" % (obj_type, id)
          return {"meta":{"url":url}}
        except Exception, inst:
          return self.error(req,str(inst))
  
      elif req.get("method") == "DELETE":

        if self.DEBUG:
          print "DELETE %s" % str(args)
        
        try:
          obj_type, id = self.urlargs(args, **kwargs)
        except RestException, inst:
          return self.error(req, str(inst), code=inst.code)
  
        try:
          return self.rest_delete(req, obj_type, id)
          req["status"] = 204
          return {}
        except Exception, inst:
          return self.error(req,str(inst))

    except webapp.HTTPCreated:
      raise
    except Exception, inst:
      print traceback.format_exc()
      return self.error(req,str(inst))
  
  #############################################################################

  def rest_get_id(self, req, obj_type, id):
    pass

  def rest_get_list(self, req, obj_type, limit=None, skip=0):
    pass

  def rest_create(self, req, obj_type, param):
    pass

  def rest_update(self, req, obj_type, id, param):
    pass

  def rest_delete(self, obj_type, id):
    pass
