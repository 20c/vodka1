import twentyc.tools.cli as cli
import os
import socket
import inspect
import twentyc.vodka
import sys
import json
import re
try:
  import twentyc.xbahn.xbahn as xbahn
except ImportError:
  xbahn = None
  print "xBahn module not found in this python environment running without"

from twentyc.vodka.util import instance_id_from_config
from twentyc.vodka.tools import module_manager
from twentyc.database.base import ClientFromConfig as DBClient 

cli.DEBUG = True

def expose(fn):
  fn.xrh_exposed = True
  return fn

###############################################################################

class Bartender(cli.CLIEnv):
  def __init__(self):
    cli.CLIEnv.__init__(self, name="bartender")
    self.target = {}
    self.databases = {}

  def custom_options(self):
    cli.CLIEnv.custom_options(self)
    self.optparse.remove_option("-c")
    self.optparse.add_option("-c", "--config", dest="configfile", default="$VODKA_HOME/etc/$VODKA_CONFIGFILE", help="path to cli config file, defaults to $VODKA_HOME/etc/$VODKA_CONFIGFILE")
    self.optparse.add_option("--prefix", dest="prefix", default=os.getcwd(), help="Install location prefix")
    self.optparse.add_option("-m", "--modules", dest="modules", default="", help="Specify a comma separated list of module for filtering operations")

    self.optparse.add_option("--with-bootstrap", dest="with_bootstrap", action="store_true", help="Install bootstrap libs")
    self.optparse.add_option("--with-jquery", dest="with_jquery", action="store_true", help="Install jquery base lib")

  def database(self, name):
    if name not in self.databases:
      self.databases[name] = DBClient("couchdb", self.config.get("db_%s"%name, self.config.get("couchdb")), name)
    return self.databases[name]

  def module_manager(self): 
    if not hasattr(self, "module_manager_inst"):
      self.module_manager_inst = module_manager.ModuleManager();
      self.module_manager_inst.set_database(self.database("modules"))
    return self.module_manager_inst

  def need_config_file(self):
    if self.run_command in ['install']:
      return False
    else:
      return True

  def run(self):
    cli.CLIEnv.run(self)

    self.module_root = os.path.dirname(inspect.getfile(twentyc.vodka))
    self.module_data = os.path.join(self.module_root, "data")
    self.module_bare_instance = os.path.join(self.module_data, "instance")
    self.module_libs = os.path.join(self.module_data, "libs")

    cmd = self.run_command
     
    if not cmd:
      self.validate_config()
      self.connect_xbahn()
      self.do_ping(None)
      self.cmdloop()
    else:
      if cmd not in ["install", "help", "update", "config_template", "make_setenv_script"]:
        self.validate_config()
        if cmd not in ["setup", "install_modules", "install_module", "dump_config"]:
          self.connect_xbahn()
          self.do_ping(None)

      if hasattr(self, "do_%s"%cmd):
        fn = getattr(self, "do_%s"%cmd)
        if len(self.args) > 1:
          fn(" ".join(self.args[1:]))
        else:
          fn("")
        self.do_exit(True)
      else:
        try:
          raise cli.InvalidCommand(cmd)
        except Exception, inst:
          print inst
          self.do_exit(True)

  #############################################################################

  def validate_config(self):
    
    self.notify("Checking config for any obvious errors ...")

    self.check_config("server", "wsgiserver")
    
    root_set = self.check_config("server", "root")

    if root_set and self.config["server"]["root"] != self.vodka_home():
      self.warn("server: root path different to vodka home environtment. In most cases they should be identical")
      self.notify("server: root = '%s'" % self.config["server"]["root"])
      self.notify("$VODKA_HOME = '%s'" % self.vodka_home())

    self.check_config("server", "protocol")
    self.check_config("server", "couch_engine")
    self.check_config("couchdb", "host")
    self.check_config("couchdb", "user")
    self.check_config("couchdb", "password")
    self.check_config("couchdb", "db_modules")
    self.check_config("couchdb", "db_prefs")

    if self.run_command in ["setup", "install_module"]:
      self.check_config("couchdb", "admin_user")
      self.check_config("couchdb", "admin_password")
   
    if self.check_config("brand.default", "dir"):
      brand_dir = self.require_config("brand.default", "dir")
      if not os.path.exists(brand_dir):
        self.notify("Config error: Specified brand directory not found: %s" % brand_dir)
    self.check_config("brand.default", "title")
    self.check_config("brand.default", "lang")

    if self.config.has_key("xbahn"):
      self.check_config("xbahn", "host")
      self.check_config("xbahn", "port")
      self.check_config("xbahn", "exchange")
      self.check_config("xbahn", "queue_id")

    self.home_instance = "__vodka.%s" % instance_id_from_config(self.config.get("server",{}))

    if len(self.config_errors) > 0:
      self.notify("Fix these config errors and try again:")
      for error in self.config_errors:
        self.notify(error)
      sys.exit()

    self.notify("Config appears to be sane, proceeding.")

  #############################################################################

  def validate_config_module(self, inst):
     if inst.has_key("bartender"):
       if inst["bartender"].has_key("config"):
         for section, items in inst["bartender"]["config"].items():
           for item in items:
             self.check_config(section, item)

     if len(self.config_errors) > 0:
       self.notify("Fix these config errors and try again:")
       for error in self.config_errors:
         self.notify(error)
       self.notify("To see a config template for this module use the config_template command")
       sys.exit()

  #############################################################################

  def vodka_home(self):
    return os.path.expandvars("$VODKA_HOME")

  def cli_path(self):
    return os.path.join(self.vodka_home(), "cli")

  #############################################################################

  def print_line(self):
    print "==========================================================="

  #############################################################################

  def help_config_template(self):
    self.notify("Prints the config template for the module located at path. Add it to your vodka config before installing the module")
    self.notify("Usage: config_template <path>")
  
  #############################################################################

  def do_config_template(self, s):

    args = s.split(" ")
    if len(args) == 0:
      return self.notify("Usage: config_template <path>")

    path = os.path.join(args[0], "config.tmpl")

    if not os.path.exists(path):
      return self.notify("Could not locate config template for module: %s" % path)

    self.print_line()
    fp = open(path)
    print fp.read()
    fp.close()
    self.print_line()

  #############################################################################

  def help_install(self):
    print "Installs a bare vodka instance in the specified directory. If no directory is specified the current working directory is used."

  #############################################################################

  def do_install(self, s):

    if s == "":
      d = self.options.prefix
      if not os.path.exists(d):
        os.makedirs(d)
    else:
      d = s


    if os.path.exists(os.path.join(d, "server.py")):
      return self.notify("There already appears to be a vodka installation at '%s', use 'update' instead of 'install', or specify a diffrent path using the --prefix option" % d)

    if os.environ.has_key("VODKA_HOME"):
      self.notify("WARNING: VODKA_HOME environment variable already set to '%s'" % os.environ["VODKA_HOME"])

    self.print_line()
    
    self.notify("Installing bare vodka instance to '%s'" % d)

    self.copyfiles(self.module_bare_instance, d)
    
    if not os.path.exists(os.path.join(d, "modules")):
      os.mkdir(os.path.join(d, "modules"))
    
    self.print_line()
    self.require_env_var("VODKA_HOME", d)
    self.require_env_var("VODKA_CONFIGFILE", "vodka.conf")
    self.make_setenv_script()
    self.print_line()

    self.install_libs(d)

    self.notify("Installation complete. Edit the config file in '%s' and run setup command afterwards to finalize setup" % os.path.expandvars(self.options.configfile))


  def install_libs(self, path):
    if self.options.with_bootstrap:
      self.options.with_jquery = True
      self.copyfiles(os.path.join(self.module_libs, "bootstrap"), os.path.join(path, "htdocs", "libs", "bootstrap"))

    if self.options.with_jquery:
      self.copyfiles(os.path.join(self.module_libs, "jquery"), os.path.join(path, "htdocs", "libs", "jquery"))

  #############################################################################

  def help_update(self):
    print "Update vodka instance base files"

  #############################################################################

  def do_update(self, s):
    if s == "":
      d = self.options.prefix
    else:
      d = s

    if not os.path.exists(os.path.join(d, "server.py")):
      raise Exception("There doesnt appear to be a vodka installation at '%s', use 'install' instead of 'update'")

    self.print_line()
    
    self.notify("Update vodka base files in '%s'" % d)

    self.copyfiles(os.path.join(self.module_bare_instance, "server.py"), d)
    self.copyfiles(os.path.join(self.module_bare_instance, "cli"), os.path.join(d, "cli"))

    js_path = os.path.join(self.module_bare_instance, "htdocs", "js")
    for filename in os.listdir(js_path):
      if re.match("^twentyc\..+\.js$", filename):
        self.copyfiles(os.path.join(js_path, filename), os.path.join(d, "htdocs", "js"))

    if os.environ.has_key("VODKA_HOME"):
      self.make_runserver_script()

    self.install_libs(d)

    self.notify("Update complete.")


  #############################################################################

  def help_setup(self):
    print "Setup vodka requirements for the vodka instance specified in the bartended config. Bartender does NOT need to be attached to live vodka instance for this command."

  #############################################################################

  def do_setup(self, s):
    self.require_config("couchdb", "admin_user")
    self.require_config("couchdb", "admin_password")

    self.print_line()
    
    self.notify("Setting up couch db auth ...")

    self.run_shell("python %s --config=%s" % (
      os.path.join(self.cli_path(), "couchdb_set_auth.py"), 
      self.configfile)
    )

    self.make_runserver_script()

    self.print_line()

    self.notify("Setup completed. Install modules using the install_module or install_modules command.")
    
    self.notify("Run runserver.sh to start the vodka server")

    self.print_line()


  #############################################################################

  def make_setenv_script(self):

    if self.options.prefix != "":
      p = self.options.prefix
    else:
      p = self.vodka_home()

    path = os.path.join(p,"setenv.sh")
    
    tmpl = "\n".join([
      "#!/bin/bash",
      "export VODKA_HOME=%s" % os.path.abspath(p),
      "export VODKA_CONFIGFILE=vodka.conf"
    ])

    fp = open(path, "w")
    fp.write(tmpl)
    fp.close()
   
    os.chmod(path, 0755)


    self.notify(tmpl)
    self.print_line()
    self.notify("Created '%s' - run it to set the necessary environment variables"  % path)


  #############################################################################

  def make_runserver_script(self):

    port = int(self.config.get("server").get("port"))
    servertype = self.config.get("server").get("wsgiserver")

    fp = open(self.module_data+"/runserver-%s.sh.tmpl" % servertype) 
    tmpl = fp.read()
    fp.close()

    tmpl = tmpl % {"port" : port}
    
    path = os.path.join(self.vodka_home(),"runserver.sh")
    
    fp = open(path, "w")
    fp.write(tmpl)
    fp.close()
   
    os.chmod(path, 0755)

    self.notify("Created '%s' - run it to start the server" % path)
    
  #############################################################################
   
  def help_make_setenv_script(self):
    self.notify("Remakes the setenv.sh scripts in the vodka home directory. If your vodka env variables arent set yet make sure to pass --prefix to this command")

  #############################################################################

  def do_make_setenv_script(self, s):
    self.make_setenv_script()

  #############################################################################

  def help_install_module(self):
    self.notify("Install module located at path")
    self.notify("Usage: install_module <path>")

  #############################################################################

  def do_install_module(self, s):
    
    args = s.split(" ")
    if len(args) == 0:
      return self.notify("Usage: install_module <path>")

    path = args[0]

    if not os.path.exists(path):
      return self.notify("No module found at '%s'" % path)

    self.notify("Attempting to import modules from '%s'" % path)

    fp = open(os.path.join(path, "vodka_import.json"))
    instructions = json.load(fp);
    fp.close()

    self.validate_config_module(instructions)

    self.run_shell("python %s --path=%s" % (
      os.path.join(self.cli_path(), "import_modules.py"),
      path
    ))


  #############################################################################

  def help_install_modules(self):
    self.notify(os.path.expandvars("Install modules located in '$VODKA_HOME/etc/modules'"))
    self.notify("Usage: install_modules - install/update all modules")
    self.notify("Usage: install_modules <name> - install/update module with matching name")

  #############################################################################

  def do_install_modules(self, s):
    path = os.path.join(self.vodka_home(), "modules")

    if not os.path.exists(path):
      return self.notify("No modules found at '%s'" % path)
    
    c = 0
    for filename in os.listdir(path):
      if s != "" and s != filename:
        continue
      filename = os.path.join(path, filename)
      c+=1
      if os.path.isdir(filename):
        self.print_line()
        self.notify("Attempting to import modules from '%s'" % filename)

        fp = open(os.path.join(filename, "vodka_import.json"))
        instructions = json.load(fp);
        fp.close()

        self.validate_config_module(instructions)
        self.run_shell("python %s --path=%s" % (
          os.path.join(self.cli_path(), "import_modules.py"),
          filename
        ))

    if c == 0:
      return self.notify("No modules found at '%s'" % path)
    else:
      return self.notify("Installed %d modules" % c)

  #############################################################################

  def help_ping(self):
    print "Ping vodka instances and output a list of all vodka instances that responded"

  #############################################################################

  def do_ping(self, s):
    print "Pinging vodka home instance (%s)" % self.home_instance
    try:
      rv = self.xbahn_request_to_all(self.home_instance, { "cmd" : "request.ping" }, response_timeout=3)
    except xbahn.ResponseTimeoutException, inst:
      print "No vodka instances responded to xbahn ping. Make sure there is at least one running"
      return

    n =0 
    self.ping_list = rv 
    self.print_line()
    print "VODKA INSTANCES"
    self.print_line()
    for instance in rv:
      print "%d) ... %s (via %s)" % (n, instance.get("host"), instance.get("xbahn")) 
      n += 1
    self.print_line()

    if n > 1:
      print "Multiple vodka instances found. Type 'attach <n>' to attach to the corresponding vodka instance and make all requests go to it."
    else:
      print "Only one vodka instance found, attaching ..."
      self.do_attach([0])

  #############################################################################

  def help_attach(self):
    print "Attach to the vodka instance of the corresponding number (type 'ping' to retrieve a list of all available vodka instances. Once attached you may issue direct commands to the vodka instance, such as 'status'"

  #############################################################################

  def do_attach(self, n):

    n = n[0]
    try:
      i = self.ping_list[n]
      self.target = { 
        "instance" : i,
        "namespace" : "__vodka.%s" % i.get("id"),
        "xbahn" : self.xbahn_find_instance(i.get("xbahn"))
      }
      self.prompt = "vodka:%s -> " % i.get("host")
        
    except:
      raise
      print "Not a valid vodka instance, type ping to get a list"

  def do_status(self,n ):
    rv = self.target_request("request.status", response_timeout=3)
    print rv

  def help_status(self):
    print "Show current status of the vodka application"

  def profile_types(self):
    return ['requests', 'tasks']

  def do_profile(self, args):
    args = args.split(" ")
    if len(args) != 2:
      return self.help_profile()
    type = args[0]
    category = args[1] 

    rv = self.target_request("profile_json", type=type, response_timeout=20)

    data = rv.get(category)
    if data:
      self.print_table(data[0].keys(), data)
    else:
      print "No data for category: %s" % category

  def help_profile(self, type=None):
    print "Show vodka profile information"
    print "Usage: profile <type> <category>"
    print "Possible types: %s" % (self.profile_types())

  def do_toggle_profile(self, args):
    args = args.split(" ")
    if len(args) != 2:
      return self.help_toggle_profile()
    type = args[0]
    state = args[1]
    if state not in ['on','off']:
      return self.help_toggle_profile()
    rv = self.target_request("toggle_profile", type=type, state=state, response_timeout=20)
  
  def help_toggle_profile(self):
    print "Toggle vodka profiling on or off"
    print "Usage: toggle_profile <type> <on|off>"
    print "Possible types: %s" % (self.profile_types())

  def require_target(self):
    if not self.target:
      raise Exception("Attach to a vodka instance before running this command")

  def target_request(self, cmd, response_timeout=3,  **kwargs):
    self.require_target()
    xbahn = self.target.get("xbahn")
    namespace = self.target.get("namespace")
    return xbahn.request(namespace, { "cmd" : cmd, "kwargs" : kwargs })

  def can_exit(self):
    return True

  def do_exit(self, s):
    self.shutdown()
    return True
  
  def help_update_module_document(self):
    print "Update a module document (such as a media file) to vodka DB"
    print "Usage: update_module_document <mod_namespace>.<mod_name> <document_name> <file_path>"

  def do_update_module_document(self, args):
    args = args.split(" ")
    if len(args) != 3:
      return self.help_update_module_document()
    mod_man = self.module_manager() 
    ns,mn = args[0].split(".")
    dn = args[1]
    file_path = args[2]

    with open(file_path, "r") as f:
      comp = f.read()

    if comp:
      mod_man.module_remove_component(ns, mn, dn)
      mod_man.module_add_component(ns, mn, dn, comp, "text/json")
      print "Updated %s.%s.%s from %s" % (ns,mn,dn,file_path)
    else:
      print "File at '%s' was empty... nothing was done." % file_path
      
  def help_dump_config(self):
    print "Dumps the currently loaded config as json"
    print "Usage: dump_config <path>"

  def do_dump_config(self, args):
    with open(args, "w") as f:
      json.dump(self.config, f, indent=2)

  do_EOF = do_exit


