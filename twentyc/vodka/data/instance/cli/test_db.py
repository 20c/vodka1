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
 
  if len(args) == 0:
    db_type = dict(config.items("server")).get("couch_engine", "couchdb")
    if not db_type:
      raise Exception("Missing argument for database selection, specify either couchdb or couchbase. Alternatively you can also specify a default for this in the config file. Section [server], config property 'couch_engine'.")
  else:
    db_type = args[0]

  if db_type == "couchbase":

    couchbase_config = config.items("couchbase")

    if not couchbase_config:
      raise Exception("Missing couchbase config in specified config file")

    db_modules = twentyc.database.ClientFromConfig(
      "couchbase", couchbase_config, "modules"
    )
    db_prefs = twentyc.database.ClientFromConfig(
      "couchbase", couchbase_config, "prefs"
    )

    print "Couchbase connected."

  elif db_type == "couchdb":
  
    couchdb_config = config.items("couchdb")
    if not couchdb_config:
      raise Exception("Missing couchdb config in specified config file")
  

    db_modules = twentyc.database.ClientFromConfig(
      "couchdb", couchdb_config, "modules"
    )
    db_prefs = twentyc.database.ClientFromConfig(
      "couchdb", couchdb_config, "prefs"
    )

    print "CouchDB connected."

  else:
    raise Exception("Invalid database type. Supported types: couchdb, couchbase")

  failed = 0
  succeeded = 0
  tests = 0

  ######

  perf = 0.0

  try:
    t1 = time.time()
    obj = db_modules.get("doesntexist")
    t2 = time.time()
    diff = t2 - t1
    perf += diff
    print "Tested document get (non-existant): OK! (in %.5fsec)" % (diff)
  except:
    print "Tested document get (non-existant): FAILED!"
    raise
 
  ######

  try:
    t1 = time.time()
    db_modules.set("test_db:test-object", { "hello" : "world"} )
    t2 = time.time()
    diff = t2 - t1
    perf += diff

    if diff > 0.008 and db_type == "couchdb":
      print "Tested document set: SLOW! is nodelay set up on couchdb server? (in %.5fsec)" % (diff)
    else:
      print "Tested document set: OK! (in %.5fsec)" % (diff)
  except:
    print "Tested document set: FAILED!"

  
  ######

  try:
    t1 = time.time()
    obj = db_modules.get("test_db:test-object")
    t2 = time.time()
    diff = t2 - t1
    perf += diff
    print "Tested document get: OK! (in %.5fsec)" % (diff)
  except:
    print "Tested document get: FAILED!" % (diff)
    raise

  
  ######
 
  try:
    t1 = time.time()
    db_modules.unset("test_db:test-object")
    t2 = time.time()
    diff = t2 - t1
    perf += diff
    print "Tested document delete: OK! (in %.5fsec)" % (diff)
  except:
    print "Tested document delete: FAILED!"
    raise

  ######

  print "Total time %.5f" % (perf)
  print "Done!"
