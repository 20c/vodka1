# import all vodka modules in a specified directory to a specified couchbase instance
# can take instuctions from a vodka_import.json file

import optparse
import twentyc.vodka.tools.module_manager as module_manager
import twentyc.database
import logging
import os
import ConfigParser
import json
import re
import sys
import subprocess
import commands
import mimetypes
import update_designs
import traceback

def import_template(man, namespace, mod, file, path, theme=None):
  if theme:
    file = "%s.%s" % (theme, file)

  print "Importing template component for module %s.%s: %s" % (
    namespace, mod, file
  ) 
  f = open(path, "r")

  man.module_add_component(
    namespace, mod, file, f.read(), "text/vodka-template"
  )
  f.close()

def import_datafile(man, namespace, mod, file, path, theme=None):
  if theme:
    file = "%s.%s" % (theme, file)

  print "Importing datafile component for module %s.%s: %s" % (
    namespace, mod, file
  ) 
  f = open(path, "r")

  man.module_add_component(
    namespace, mod, file, f.read(), "text/json"
  )
  f.close()



if __name__ == "__main__":

  parser = optparse.OptionParser()
  parser.add_option("-c", "--config", dest="configfile", default="$VODKA_HOME/etc/$VODKA_CONFIGFILE", help="path to a vodka config file with couchbase bucket information")
  parser.add_option("-m", "--modules", dest="modules", default=None, help="Comma separated list of module names. If specified only the targeted modules will be imported/updated")
  parser.add_option("-v", "--version", dest="version", default=None, help="Specify the import version of the modules. If not set config/VERSION in the source directory will be used.")
  parser.add_option("-p", "--path", dest="path", default=".", help="Path with vodka modules. If not specified cwd is used.")
  parser.add_option("-r", "--remove", dest="remove", action="store_true", help="Remove modules instead of importing")
  parser.add_option("--skip-designs", dest="skip_designs", action="store_true", help="Do not update couchbase designs")
  parser.add_option("--yuicompressor", dest="yui", help="path to yuicompressor directory. If specified javascript components will also be saved in a minified version")
  parser.add_option("--ignore", dest="ignore", help="list of comma separated modules that will be ignored", default="")

  (options, args) = parser.parse_args()

  configfile = os.path.expandvars(options.configfile)
  source_path = os.path.expandvars(options.path)

  if not source_path:
    raise Exception("No source directory specified, see --path.");

  instructions = os.path.join(source_path, "vodka_import.json");
  manual_version = options.version

  ignore = options.ignore.split(",")

  filters = options.modules
  if filters: 
    filters = filters.split(",")

  config = ConfigParser.RawConfigParser()
  config.read(configfile)
  print "Read config from file: %s" % configfile

  man = module_manager.ModuleManager()
  couch_engine = dict(config.items("server")).get("couch_engine", "couchdb")
  couch_config = dict(config.items(couch_engine))

  man.set_database(
    twentyc.database.ClientFromConfig(
      couch_engine, couch_config, "modules"
    )
  )

  print "Read instructions from file: %s" % instructions
  
  if not os.path.exists(instructions):
    raise Exception("No instructions file found at the specified path: %s" % (instructions))

  f = open(instructions, "r")
  instructions = json.loads(f.read())
  f.close()

  namespace = instructions.get("namespace")
  glob_deps = instructions.get("_dependencies",[])

  if not namespace:
    raise Exception("No namespace defined in %s" % instructions)

  if not options.remove:
    print "Importing modules from %s to namespace %s" % (options.path, namespace)
  
  if not manual_version:
    print "Using versioning from %s" % (os.path.join(options.path, "config/VERSION"))
    f = open(os.path.join(options.path,"config/VERSION"))
    manual_version = f.read().replace("\n","")
    f.close()

  if options.yui:
    yui_rv, yui_jar = commands.getstatusoutput("ls " + options.yui + "/build/yuicompressor-*.jar")
    if yui_rv:
      raise RuntimeError("yuicompressor jar not found (" + options.yui + ")")

  for mod in os.listdir(options.path):
   
    try:
      mod_instructions = instructions.get(mod, {})

      if mod in ignore:
        print "Ignoring %s" % mod
        continue

      namespace = mod_instructions.get("namespace", instructions.get("namespace"))

      dir = os.path.join(options.path,mod)

      mod = mod_instructions.get("name", mod)

      if os.path.isdir(dir):
        if filters and mod not in filters:
          continue

        if mod in ["config"] or mod[0] == '.' or mod[0] == "_":
          continue
        
        # load mod info
        mod_info = man.module_info(namespace, mod)
        access_level = mod_instructions.get("access_level", 0)
        title = mod_instructions.get("title", re.sub("[_-]", " ", mod)).capitalize()

        if mod_info:
          man.module_remove(namespace, mod)
          if options.remove or mod_instructions.get("remove"):
            print "Removed module %s" % man.module_key(namespace, mod)
            continue
 
        version = manual_version or "1.0.0.0"

        # create the module information in couchbase
        mod_info = man.module_create(
          namespace, 
          mod, 
          "20c", 
          version=version, 
          access_level=access_level, 
          title=title,
          mobile = mod_instructions.get("mobile", False),
          priority = mod_instructions.get("priority", 0)
        )

        dep = mod_instructions.get("dependencies",[])
        for gd in glob_deps:
          if gd not in dep and gd != "%s.%s" % (namespace, mod):
            dep.append(gd)

        for d in dep:
          print "Adding dependency for %s.%s: %s" % (namespace, mod, d)
          man.module_add_dependency(namespace, mod, d)
          
        print "Importing module %s.%s (v %s, al %d)" % (
          namespace, mod, version, access_level
        )

        # load media from directory
        media_path = os.path.join(dir, "media")
        if os.path.exists(media_path):
          for file in os.listdir(media_path):
            if file[0] == ".":
              continue

            media_file_path = os.path.join(media_path, file)
            mime = mimetypes.guess_type(media_file_path)

            print "Importing media component for module %s.%s: %s %s" % (
              namespace, mod, file, mime
            ) 
            f = open(media_file_path, "r")

            file = re.sub("^_min_\.", "", file)
            
            try: 
              man.module_add_component(
                namespace, mod, file, f.read(), mime
              )
	    except Exception, inst:
	      print "========================"
	      print "ERROR while importing '%s': %s" % (media_file_path, inst)
	      print "========================"
	    finally:
              f.close()

        # load templates from directory
        template_path = os.path.join(dir, "tmpl")
        if os.path.exists(template_path):
          for file in os.listdir(template_path):
            if file[0] == ".":
              continue

            template_file_path = os.path.join(template_path, file)
            if os.path.isdir(template_file_path):
              for t_file in os.listdir(template_file_path):
                if t_file[0] == ".":
                  continue
                import_template(man, namespace, mod, t_file, os.path.join(template_file_path, t_file), theme=file)
            else:
              import_template(man, namespace. mod, file, template_file_path)

        # load data from directory
        datafile_path = os.path.join(dir, "data")
        if os.path.exists(datafile_path):
          for file in os.listdir(datafile_path):
            if file[0] == ".":
              continue

            datafile_file_path = os.path.join(datafile_path, file)
            if os.path.isdir(datafile_file_path):
              for t_file in os.listdir(datafile_file_path):
                if t_file[0] == ".":
                  continue
                import_datafile(man, namespace, mod, t_file, os.path.join(datafile_file_path, t_file), theme=file)
            else:
              import_datafile(man, namespace, mod, file, datafile_file_path)


        # check if module has couchdb design docs that may need to be updated
        design_path = os.path.join(dir, "design")
        if os.path.exists(design_path) and not options.skip_designs:
          for file in os.listdir(design_path):
            if file[0] == ".":
              continue

            design_file_path = os.path.join(design_path, file)
            db_config =  mod_instructions.get("design", {}).get(file, {}).get("db_config")
            if not db_config:
              db_config = couch_config
            else:
              try:
                db_config = dict(config.items(db_config))
              except Exception, inst:
                print "Could not load config section '%s' required for '%s.%s', couchdb views will not be updated" % (db_config, namespace, mod)
                break

            update_designs.update_views(couch_engine, db_config, design_file_path)
 
        for file in os.listdir(dir):
          if re.match(".*\.py$", file):
            
            #print "Importing python component for module %s.%s (v %s): %s" % (
            #  namespace, mod, version, file
            #)
            f = open(os.path.join(dir,file), "r")#
            man.module_add_component(namespace, mod, file, f.read(), "text/python")
            #man.module_remove_component(namespace, mod, re.sub("\.py$","",file))
            f.close()

          elif re.match("prefs.json$", file):
            
            #print "Importing validator component for module %s.%s (v %s): %s" % (
            #  namespace, mod, version, file
            #)

            f = open(os.path.join(dir,file), "r")#
            man.module_add_component(namespace, mod, file, f.read(), "text/vodka-validator")
            #man.module_remove_component(namespace, mod, re.sub("\.py$","",file))
            f.close()

          elif re.match(".*\.js$", file) and not re.match("^_min_",file):
            #print "Importing javascript component for module %s.%s (v %s): %s" % (
            #  namespace, mod, version, file
            #)

            path = os.path.join(dir, file)
            minified_file = os.path.join(dir,"_min_.%s"%file)
            f = open(path, "r")
            contents = f.read()
            f.close()

            if options.yui:
              minified = ""
              cmd = "java -jar " + yui_jar
              dst = minified_file
              cmd = "%s %s -o %s" % (cmd, path, dst)
              subprocess.check_call(cmd.split(" "))
              f = open(dst, "r")
              minified = f.read()
              f.close()
              try:
                subprocess.check_call(["rm", dst])
              except Exception, inst:
                print "Warning: %s" % str(inst)
            elif os.path.exists(minified_file):
              #print "..Importing minified js from %s" % minified_file
              f = open(minified_file, "r")
              minified = f.read()
              f.close()
            else:
              minified = None
            
            man.module_add_component(namespace, mod, file, contents, "text/javascript",minified=minified)
            #man.module_remove_component(namespace, mod, re.sub("\.js$","",file))
    except Exception, inst:
      raise 
      #print "--------------------------------------------------------------------"
      #print "Error \"%s\" was raised when trying to import module %s" % (inst, mod)
      #print "--------------------------------------------------------------------"
      #print traceback.format_exc()
      #print "--------------------------------------------------------------------"

  # remove any modules staged for removal
  rm_mod_list = instructions.get("_deploy_remove", [])
  for rm_mod in rm_mod_list:
    if filters and rm_mod not in filters:
      continue
    print "Removing via _deploy_remove: %s.%s" % (namespace, rm_mod)
    man.module_remove(namespace, rm_mod)


  print "Done!"
