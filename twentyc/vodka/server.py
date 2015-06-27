from twentyc.vodka.wsgi import webapp
import cProfile
from twentyc.vodka.vodka import *

if not int(webapp.configs.get(serverConfPath,{}).get("app", {}).get("extend_vodka",0)):
  cfg = webapp.configs.get(serverConfPath,{}).get("profiler",{})
  if cfg.get("enabled") == "yes":
    print "Profiler is enabled"
    b_path = cfg.get("output.path", os.path.join(
      os.path.dirname(__file__),
      "profile",
      "%s.profile" % ( "%s." + str(int(time.time())))
    ))
    p_path = b_path % 'vodka' 
    print "Main Profile will be saved to %s after application is terminated" % p_path
    print "WTSrv Profile will be stored as it happens"
    cProfile.runctx("init()", { "init" : init }, {}, p_path)
  else:
    init()
