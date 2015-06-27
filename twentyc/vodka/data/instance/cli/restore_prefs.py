"""
Migrate all vodka data from couchbase to couchdb and vice versa
"""

import twentyc.tools.cli as cli
import twentyc.database
import optparse
import subprocess
import os
import ConfigParser
import time
import sys
import json

if __name__ == "__main__":

  parser = optparse.OptionParser()

  parser.add_option("-c", "--config", dest="configfile", default="$VODKA_HOME/etc/$VODKA_CONFIG", help="path to a vodka config file with couchbase bucket information. Defaults to $VODKA_HOME/etc/$VODKA_CONFIG")

  # parse options
  (options, args) = parser.parse_args()

  # read config file from specified path
  configfile = os.path.expandvars(options.configfile)

  config = ConfigParser.RawConfigParser()
  config.read(configfile)
  print "Read config from file: %s" % configfile
 
  db_type = "couchdb" 
  if not db_type:
    raise Exception("Missing argument for database selection, specify either couchdb or couchbase. Alternatively you can also specify a default for this in the config file. Section [server], config property 'couch_engine'.")

  if db_type == "couchbase":

    couchbase_config = config.items("couchbase")

    if not couchbase_config:
      raise Exception("Missing couchbase config in specified config file")

    db_prefs = twentyc.database.ClientFromConfig(
      "couchbase", couchbase_config, "prefs"
    )

    print "Couchbase connected."

  elif db_type == "couchdb":
  
    couchdb_config = config.items("couchdb")
    if not couchdb_config:
      raise Exception("Missing couchdb config in specified config file")
  

    db_prefs = twentyc.database.ClientFromConfig(
      "couchdb", couchdb_config, "prefs"
    )

    print "CouchDB connected."

  else:
    raise Exception("Invalid database type. Supported types: couchdb, couchbase")

  #docstr = "%s%s" %  (couchdb_config.get("prefix_prefs"), args[1])

  #data = db_prefs.db.revisions(docstr)

  #print json.dumps(data, indent=2)

  if args[0] == "list":
    
    for id in db_prefs.db:
      doc = db_prefs.get(id)
      if doc.get(":user_id") == int(args[1]):
        print id
  elif args[0] == "revisions":
    for id in db_prefs.db.revisions(args[1]):
      print json.dumps(dict(id), indent=2)

  elif args[0] == "restore":

    old = db_prefs.db.get(args[1], rev=args[2])
    del old["_rev"]
    db_prefs.set(old["_id"], dict(old))

    print "Restored %s to %s" % (old.get("_id"), args[2])

