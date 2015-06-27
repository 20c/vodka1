import traceback
import simplejson as json
import optparse
import uuid
import os
import sys
import time
from twentyc.tools.syslogfix import UTFFixedSysLogHandler
try:
  import twentyc.xbahn.xbahn as xbahn
except ImportError:
  print "Warning: xbahn module not installed, task system deactivated."

import twentyc.vodka.tools.module_manager as module_manager
import twentyc.database
from wsgi import webapp
webapp.serverStatus=0
import logging
import signal

STARTED=1
SENDING=2
FINISHED=3

MIME_JSON = "application/json"
MIME_CSV = "text/csv"

OUT_XBAHN = 1
OUT_CONSOLE = 2

tasks = {}

###############################################################################

class MissingConfigException(Exception):
  
  def __init__(self, group, name, msg, **kwargs):
    Exception.__init__(
      "Missing config for [%s] %s: %s" % (
        group,
        name,
        msg
      )
    )

###############################################################################

def register_task(full_task_name, taskClass):
  tasks[full_task_name] = taskClass

###############################################################################

class VodkaTask(object):
  
  def __init__(self, moduleName, taskName, vodkaId, id, config, log, limit=0, out="xbahn", options={}, module_manager=None):
    self.moduleName = moduleName 
    self.taskName = taskName
    self.config = config
    self.options = options
    self.id = id
    self.vodkaId = vodkaId
    self.log = log
    self.mime = MIME_JSON
    self.limit = limit
    self.empty_result_message = "Empty result"
    self.module_manager = module_manager

    if out == "console": 
      self.out = OUT_CONSOLE
    else:
      self.out = OUT_XBAHN

    log.info("Task initiating... sending output to %s" % out)

    # set up xbahn
    xbahn_config = self.config.get("xbahn")
    self.xbahn = xbahn.xBahnThread(
      xbahn_config.get("host"),
      xbahn_config.get("port"),
      xbahn_config.get("exchange"),
      self,
      None,
      username=xbahn_config.get("username"),
      password=xbahn_config.get("password"),
      queue_name="vodka-task:%s"%self.id,
      queue_capacity=50,
      interval=1,
      log=self.log
    )

    self.xbahn_listener = self.xbahn.listen(
      self.xbahn_subject("ctrl")
    )
    self.xbahn_listener.callbacks.append(self.ctrl)

    self.xbahn_listener_g = self.xbahn.listen(
      self.xbahn_subject("ctrl" , taskid="_ALL_")
    )
    self.xbahn_listener_g.callbacks.append(self.ctrl)


    self.info = {}

    T = self

    sigs = [
      signal.SIGABRT,
      signal.SIGINT,
      signal.SIGHUP,
      signal.SIGQUIT,
      signal.SIGSEGV,
      signal.SIGTSTP,
      signal.SIGTERM
    ]

    def sighandler(a,b):
      T.interrupt("signal")

    for i in sigs:
      signal.signal(i, sighandler)

  #############################################################################

  def require_config(self, group, name, reason): 
    try:
      assert(self.config.get(group).get(name))
    except:
      raise MissingConfigException(group, name, reason)

  #############################################################################

  def db_from_config(self, configName, dbName=None):
    if not dbName:
      dbName = configName
    return twentyc.database.ClientFromConfig(
      self.config.get("server", {}).get("couch_engine", "couchdb"),
      self.config.get(configName),
      dbName,
      logger=self.log
    )

  #############################################################################

  def ctrl(self, msg, body):
    try:

      cmd = body.get("cmd")
     
      if cmd == "stop":
        self.interrupt(body.get("reason", "vodka ctrl"))

    except Exception, inst:
      self.log.error(traceback.format_exc())

    
  #############################################################################

  def start(self):
    try:
      
      self.xbahn.start()
      
      # set initial state of the task
      self.update(
        mime=self.mime,
        type="%s.%s" % (self.moduleName, self.taskName),
        start_t=time.time(),
        id=self.id,
        status=STARTED
      )

      self.run()
      self.end()
    except Exception, inst:
      self.log.error(traceback.format_exc())
      self.interrupt(str(inst))
    finally:
      self.xbahn.stop()

  #############################################################################

  def run(self):
    pass

  #############################################################################

  def end(self):
    time.sleep(0.5)

    if self.info.get("error"):
      progress = "Errored"
    else:
      progress = "Finished" 

    self.update(
      status=FINISHED,
      progress=progress,
      end_t=time.time()
    )
    
  #############################################################################

  def interrupt(self, reason):
    try:
      self.update(error=reason)
    finally:
      self.xbahn.stop()
      self.end()
      os._exit(1)
      

  #############################################################################

  def update(self, **kwargs):
    if not self.info:
      self.info = kwargs
    else:
      self.info.update(kwargs)
    self.xbahn.send(None, self.xbahn_subject("update"), self.info, sync=True)

  #############################################################################

  def progress(self, msg):
    self.log.debug("Progress: %s" % msg)
    self.update(progress=msg)

  #############################################################################

  def result(self, result, size=0, total=0):
    if self.info.get("status") != SENDING:
      if not size:
        size = len(result)
      self.update(status=SENDING, progress="Sending: %d/%d" % (size,total))
      time.sleep(1.5)
   
    if self.out == OUT_XBAHN:
      self.xbahn.send(None, self.xbahn_subject("result"), result, sync=True)
    else:
      print "\n".join(result)

  #############################################################################

  def result_chunked(self, result, n=1000):
    i = 0

    if type(result) == dict:
      result = json.dumps(result, indent=" ").split("\n")
      if self.limit:
        result = result[:self.limit]
    elif type(result) in [str, unicode]:
      result = result.split("\n")
      if self.limit:
        result = result[:self.limit]
    elif type(result) == list and len(result) and type(result[0]) == dict:
      result = [json.dumps(r)+"," for r in result]
      if self.limit:
        result = result[:self.limit]
      result[-1] = result[-1].rstrip(",")
      result.insert(0, '{ "__result" : [')
      result.append(']}');

    if not result:
      return self.progress(self.empty_result_message)

    l = len(result)

    s = 0
    while i < l and self.info.get("status") != FINISHED:
      if i+n > l:
        n = l - i
      self.result(result[i:i+n], size=i+n, total=l)
      i+=n
      s+=1
      if s == 100 and self.out == OUT_XBAHN:
        self.update(progress="Sending: %d/%d" % (i,l))
        s = 0
        time.sleep(0.5)

    self.update(progress="Sending: %d/%d" % (l,l))

  #############################################################################

  def xbahn_subject(self, cmd, taskid=None):
    if cmd=="result":
      cmd="update"
    return "__vodka-task-%s.%s.%s" % (cmd, self.vodkaId, taskid or self.id)

  #############################################################################
  #############################################################################



###############################################################################

if __name__ == "__main__":

  parser = optparse.OptionParser()
  parser.add_option("-c", "--config", dest="configfile", default="$VODKA_HOME/etc/$VODKA_CONFIG", help="path to a vodka config file with couchbase bucket information")
  parser.add_option("-p", "--param", dest="param", default="{}", help="paramaters to pass to the task in JSON")
  parser.add_option("-l", "--limit", dest="limit", default=0, type="int", help="limit the result sent by the task to n rows")
  parser.add_option("-o", "--out", dest="out", default="xbahn", help="send output here, can be 'xbahn' or 'console' - defaults to 'xbahn'")
  parser.add_option("-v", "--verbose", dest="verbose", action="store_true", help="log will be sent to stdout")

  options, args = parser.parse_args()

  # make sure arguments contain module name, task name and unique task id
  if len(args) < 3:
    raise Exception("Task started with invalid arguments, need module name, task name and vodka id")

  moduleName = args[0]
  taskName = args[1]
  vodkaId = args[2]
  try:
    id = args[3]
  except:
    id = str(uuid.uuid4())

  if id.find(".") > -1:
    id = id.replace(".","-")

  # load vodka config
  configfile = os.path.expandvars(options.configfile)
  config = webapp.dict_conf(configfile)

  # set up logging
  logformat = "VodkaTask %s.%s.%s.%s: %s" % (
    moduleName,
    taskName,
    vodkaId,
    id,
    "%(message)s"
  )

  if int(config.get("server",{}).get("syslog",0)):
    syslog_address = config.get("server", {}).get("syslog_address", "/dev/log")
    syslog_facility = config.get("server", {}).get("syslog_facility", "LOG_LOCAL0")
    hdl = UTFFixedSysLogHandler(address=syslog_address, facility=getattr(logging.handlers.SysLogHandler, syslog_facility))
    hdl.setFormatter(logging.Formatter(logformat))
  else:
    hdl = logging.FileHandler("error.log")
    hdl.setFormatter(logging.Formatter(logformat))

  webapp.log.addHandler(hdl)

  # setup logging to stdout
  if options.verbose:
    hdl = logging.StreamHandler(sys.stdout)
    hdl.setFormatter(logging.Formatter(logformat))
    webapp.log.addHandler(hdl)

  # module manager instance so we can load the task module
  mm = module_manager.ModuleManager()
  mm.set_database(twentyc.database.ClientFromConfig("couchdb", config.get("couchdb"), "modules", logger=webapp.log))

  # import module from couchdb
  mods = mm.module_import(*mm.module_token(moduleName))
  taskClass = None
  for comp, mod in mods.items():
   if hasattr(mod, "vodka_tasks"):
     for name, ctor in mod.vodka_tasks.items():
       if name == taskName:
         taskClass = ctor
         break

  # instantiate class if it exists, if not bail
  if taskClass:
    try:
      task = taskClass(
        moduleName,
        taskName,
        vodkaId,
        id,
        config,
        webapp.log,
        limit=options.limit,
        out=options.out,
        options=json.loads(options.param),
        module_manager=mm
      )
      task.start()
    except Exception, inst:
      webapp.log.error("Could not construct task class %s.%s" % (moduleName, taskName))
      webapp.log.error(traceback.format_exc())
      raise
  else:
    webapp.log.error("Could not run task %s.%s - because it was never registered" % (moduleName, taskName))
    raise Exception("Unknown task")
