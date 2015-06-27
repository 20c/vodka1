"""
Migrate all vodka data from couchbase to couchdb and vice versa
"""

import twentyc.database
import optparse
import os
import ConfigParser
import sys
import requests
import json
import re

if __name__ == "__main__":

  parser = optparse.OptionParser()

  parser.add_option("-c", "--config", dest="configfile", default="$VODKA_HOME/etc/$VODKA_CONFIG", help="path to a vodka config file with couchbase bucket information. Defaults to $VODKA_HOME/etc/$VODKA_CONFIG")
  parser.add_option("-p", "--path", dest="design_path", default="../design", help="Path to vodka design directory")

  # parse options
  (options, args) = parser.parse_args()

  # read config file from specified path
  configfile = os.path.expandvars(options.configfile)

  config = ConfigParser.RawConfigParser()
  config.read(configfile)
  print "Read config from file: %s" % configfile
 

  couchbase_config = dict(config.items("couchbase"))
  couchdb_config = dict(config.items("couchdb"))

  if not couchbase_config:
    raise Exception("Missing couchbase config in specified config file")

  if not couchdb_config:
    raise Exception("Missing couchdb config in specified config file")

  design_path = os.path.join(options.design_path, "couchbase_view_all.ddoc")

  if not os.path.exists(design_path):
    print "Could not find required couchbase design file at %s" % design_path
    print "If you are running this script from outside the the vodka/cli directory make sure to specify the design directory location via --path"
    sys.exit()

  couchbase_modules = twentyc.database.ClientFromConfig(
    "couchbase", couchbase_config, "modules"
  )
  couchbase_prefs = twentyc.database.ClientFromConfig(
    "couchbase", couchbase_config, "prefs"
  )

  print "Couchbase connected."

  couchdb_modules = twentyc.database.ClientFromConfig(
    "couchdb", couchdb_config, "modules"
  )
  couchdb_prefs = twentyc.database.ClientFromConfig(
    "couchdb", couchdb_config, "prefs"
  )

  print "CouchDB connected."


  print "Preparing couchbase views"

  #create_couchbase_views(couchbase_config)

  view_f = open(design_path)
  view_d = json.loads(view_f.read())
  view_f.close()

  r = requests.request(
    "PUT",
    "http://%s:8092/%s/_design/vodka" % (
      couchbase_config.get("host").split(":")[0],
      couchbase_config.get("bucket_modules").split(":")[0]
    ),
    auth=tuple(couchbase_config.get("bucket_modules").split(":")),
    data=json.dumps(view_d),
    headers={"content-type" : "application/json"}
  )

  resp = json.loads(r.text)
  if resp.get("ok") != True:
    raise Exception("could not create necessary couchbase view in modules bucket: %s" % r.text)

  r = requests.request(
    "PUT",
    "http://%s:8092/%s/_design/vodka" % (
      couchbase_config.get("host").split(":")[0],
      couchbase_config.get("bucket_prefs").split(":")[0]
    ),
    auth=tuple(couchbase_config.get("bucket_prefs").split(":")),
    data=json.dumps(view_d),
    headers={"content-type" : "application/json"}
  )

  resp = json.loads(r.text)
  if resp.get("ok") != True:
    raise Exception("could not create necessary couchbase view in prefs bucket: %s" % r.text)

  rows = couchbase_modules.view("vodka","all",stale=False)
  num_modules = len(rows)

  for row in rows:
    doc = couchbase_modules.get(row.get("id"))
    if type(doc) != dict or row.get("id")[0] == "_":
      continue
    print "(Modules) Copying %s" % row.get("id")
    couchdb_modules.set(row.get("id"), doc)

  rows = couchbase_prefs.view("vodka","all",stale=False)
  num_prefs = len(rows)

  prefix_old = couchbase_config.get("prefix_prefs")
  prefix_new = couchdb_config.get("prefix_prefs")

  for row in rows:
    doc = couchbase_prefs.get(row.get("id"))

    if type(doc) != dict or row.get("id")[0] == "_":
      continue
    
    for key, value in doc.items():
      if key == "__user_id":
        doc[":user_id"] = value
        del doc[key]
      elif key == "__type":
        doc[":type"] = value
        del doc[key]

    id = row.get("id")
    if not re.match("%s.*" % (prefix_old % doc.get(":user_id",0)),id):
      continue

    id = re.sub(
      "^%s"%(prefix_old % doc.get(":user_id",0)),
      prefix_new % doc.get(":user_id",0),
      id
    )

    print "(Prefs) Copying %s to %s" % (row.get("id"), id)

    couchdb_prefs.set(id, doc)

  print "Done!"
