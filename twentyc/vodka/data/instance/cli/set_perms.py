# set user access permissions for vodka modules

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


vodkaPath = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(vodkaPath)

import config
config.vodkaBaseDir = vodkaPath

import xbahn

def bail(msg):
  print msg
  sys.exit()

def level_readable(level):
  rv = []
  if level & 0x01:
    rv.append("READ")
  if level & 0x02:
    rv.append("WRITE")
  if level & 0x04:
    rv.append("WRITE XBAHN")
  if level == -1:
    return "PURGED"
  if not level:
    return "DENIED"

  return ",".join(rv)


if __name__ == "__main__":

  parser = optparse.OptionParser()
  parser.add_option("-c", "--config", dest="configfile", default="$VODKA_HOME/etc/$VODKA_CONFIGFILE", help="path to a vodka config file with couchbase bucket information. Defaults to $VODKA_HOME/etc/$VODKA_CONFIGFILE")
  parser.add_option("-u", "--user-id", dest="user_id", help="permissions will get updated for the specified user (id)")
  parser.add_option("-m", "--modules", dest="modules", help="permission will get updated for these modules - separated by ,")
  parser.add_option("-l", "--level", dest="level", default="0", help="permissions will be updated to this level (r = read, w = write, p = deny / purge entry from database. You may chain these flags together, eg. rw or rwx")
  parser.add_option("--purge", dest="purge", action="store_true", help="Remove all permission entries for the specified user")
  parser.add_option("--check", dest="check_perms", action="store_true", help="List the user's permissions for the specified modules")
  parser.add_option("-f", "--force", dest="force", action="store_true", help="Action will be forced regardless of any concerns")
  parser.add_option("-p", "--pretend", dest="pretend", action="store_true")

  (options, args) = parser.parse_args()

  configfile = os.path.expandvars(options.configfile)

  config = ConfigParser.RawConfigParser()
  config.read(configfile)
  print "Read config from file: %s" % configfile
  
  man = module_manager.ModuleManager()
  couch_engine = dict(config.items("server")).get("couch_engine", "couchdb")
  couch_config = config.items(couch_engine)

  man.set_database(
    twentyc.database.ClientFromConfig(
      couch_engine, couch_config, "modules"
    )
  )

  if config.has_option("xbahn", "username") and config.has_option("xbahn", "password"):
    xbahn_user = config.get("xbahn", "username")
    xbahn_pass = config.get("xbahn", "password")
  else:
    xbahn_user = None
    xbahn_pass = None

  if config.has_section("xbahn") and config.get("xbahn", "host"):
    xb = xbahn.xBahn(
      config.get("xbahn", "host"),
      int(config.get("xbahn", "port")),
      config.get("xbahn", "exchange"),
      None,
      None,
      username = xbahn_user,
      password = xbahn_pass
    )
    man.xbahn = xb
  
  users = []
  user_id = 0

  if options.user_id:
    try:
      user_id = int(options.user_id)
      users.append((user_id, options.user_id))
    except ValueError:
      if orderhistory:
        user_id = orderhistory.get_user_id(options.user_id)
        if not user_id:
          pattern = options.user_id.split(":")
          user_pattern = pattern[0]

          m = re.search("\((\d+)-(\d+)\)", user_pattern)

          if m:

            min = int(m.group(1))
            max = int(m.group(2))
            base = m.group(0)

            while min <= max:
              user = user_pattern.replace(base, str(min))
              min += 1
              user_id = orderhistory.get_user_id(user)
              if not user_id:
                print "Could not resolve username '%s'" % user
                continue
              pattern[0] = str(user_id)
              users.append((int(user_id), user))
        
          else:
            bail("Could not resolve username '%s'" % options.user_id)

        else:
          users.append((user_id, options.user_id))
  
  modules = options.modules.split(",")
  level = options.level

  for user_id, inpt in users:
    if options.purge:
      print "Purging permissions for user %s" % user_id
      if not options.pretend:
        man.perms_purge(user_id)
      print "Done!"
      continue

    for m in modules:
      if not options.check_perms:
      
        int_level = 0

        if "r" in level: 
          int_level |= 0x01
        if "w" in level: 
          int_level |= 0x02
        if "x" in level:
          int_level |= 0x04
        if level == "p":
          int_level = -1

        print "Updating user %s(%d)'s perms for '%s' to '%s'" % (inpt, user_id, m, level_readable(int_level))
        if not options.pretend:
          man.perms_set(
            user_id,
            m,
            int_level,
            force=options.force,
            source="cli/set_perms.py"
          )
      else:
        level = man.perms_check(user_id, m)
        print "User %s(%d)'s perms for '%s' are '%s'" % (inpt, user_id, m, level_readable(level))
        print json.dumps(man.cb_client.get(man.perms_key(user_id)), indent=2)

  print "Done!"
 
