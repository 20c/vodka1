from wsgi import webapp
import simplejson as json
import rpc
import constants
import time

from twentyc.xbahn.xbahn import *
import twentyc.xbahn.bridge as xbahn_bridge

class RPC(rpc.RPC):

  @webapp.expose
  def xbahn_request_data(self, **kwargs):

    if not xbahn_bridge:
      raise webapp.HTTPError(502)

    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    self.require_auth(req)

    if not ses.app.xbahn.session:
      raise webapp.HTTPError(404)
  
    try:

      targets = {} 
      
      for k,v in kwargs.items():
        if k[0] == "_":
          continue

        if type(v) != list:
          v = [v]

        fn = xbahn_bridge.ALIASES.get(k)
        for a in v:
          if k in xbahn_bridge.ALIASES:
            d = fn(int(a), ses.app)
            print "xbahn request data: %s" % d
            targets[k+":"+a] = d["storage"]
            xbahn_bridge.require_data(**d)

      rv["list_names"] = targets

    except Exception, inst:
      self.handle_error_response(rv, inst)

    return self.output(bridge, rv, "/")
 
  
  @webapp.expose
  def xbahn_retrieve(self, **kwargs):

    if not xbahn_bridge:
      raise webapp.HTTPError(502)


    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    self.require_auth(req)

    if not ses.app.xbahn.session:
      raise webapp.HTTPError(404)
  
    try:
      target = kwargs.get("target")
      opt = json.loads(kwargs.get("opt","{}"))

      print "OPT: %s %s" % (type(opt), str(opt))

      if not target:
        raise Exception("No xbahn target specified");

      if not ses.check_20c_module(target):
        raise Exception("No permission to read from: %s" % target)


      data = ses.app.xbahn.update(
        target,
        ses=ses,
        init_listen=False,
        id=opt
      )
      if opt.get("raw"):
        return data
      else:
        rv["data"] = data

    except Exception, inst:
      self.handle_error_response(rv, inst)

    return self.output(bridge, rv, "/")
 
  
  @webapp.expose
  def xbahn(self, **kwargs):

    if not xbahn_bridge:
      raise webapp.HTTPError(502)

    ses, bridge, rv, req = self.controls(kwargs.get("__request"))
    
    self.validate_request(req)

    if not ses.app.xbahn.session:
      raise webapp.HTTPError(404)
  
    try:
      cmd = kwargs.get("cmd")
      target = kwargs.get("target")

      for k in ses.app.config.get("xbahn_protect",{}).keys():
        if ses.app.module_manager.namespace_match(target.split("."), k):
          raise Exception("Invalid xbahn target")

      if not target:
        raise Exception("No xbahn target specified");

      if cmd:
        cmd = json.loads(cmd)
        cmd["target"] = target
        cmd["sid"] = ses.web_ses_id
        cmd["remote_address"] = req.get("remote_addr", "")
        cmd["user_id"] = ses.user_id 
        cmd["send_t"] = time.time()
        
        if not ses.check_20c_module(target) & constants.ACCESS_XBAHN_WRITE:
          raise Exception("No permission to write to: %s" % target)

        ses.app.xbahn.send(ses, target, cmd)

    except Exception, inst:
      self.handle_error_response(rv, inst)

    return self.output(bridge, rv, "/")
  
rpc.RPC = RPC
