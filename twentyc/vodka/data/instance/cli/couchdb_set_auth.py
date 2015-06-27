import os
import ConfigParser
import subprocess
import optparse
import json
import sys
import twentyc.database
import twentyc.database.couchdb.client
import uuid
import hashlib
import requests


def create_security(host, db_name, security, admin_user, admin_password):
  print "Creating _security document for %s" % db_name
  req = requests.request("PUT", "http://%s/%s/_security" % (host, db_name), data=json.dumps(security), auth=(admin_user, admin_password))
  print req.text

def create_user(host, user, password, admin_user, admin_password):
  print "Creating user '%s'" % (user)

  _user = {
    "_id" : "org.couchdb.user:%s" % user,
    "type" : "user",
    "name" : user,
    "roles" : [],
    "password" : password
  }

  req = requests.request("POST", "http://%s/_users" % host, data=json.dumps(_user), headers={ "Content-Type" : "application/json" }, auth=(admin_user, admin_password))
  print req.text


if __name__ == "__main__":
  parser = optparse.OptionParser()
  parser.add_option("-c", "--config", dest="configfile", default="$VODKA_HOME/etc/$VODKA_CONFIGFILE", help="path to a vodka config file with couchbase bucket information. Defaults to $VODKA_HOME/etc/$VODKA_CONFIGFILE")

  (options, args) = parser.parse_args()

  configfile = os.path.expandvars(options.configfile)

  config = ConfigParser.RawConfigParser()
  config.read(configfile)
  print "Read config from file: %s" % configfile

  couch_engine = "couchdb"
  couch_config = dict(config.items(couch_engine))

  if not couch_config:
    raise Exception("Missing [couchdb] config section in specified config file")

  if not couch_config.get("user"):
    raise Exception("Missing 'user' config attribute in [couchdb]")

  if not couch_config.get("password"):
    raise Exception("Missing 'password' config attribute in [couchdb]")

  if not couch_config.get("admin_user"):
    raise Exception("Missing 'admin_user' config attribute in [couchdb]")

  if not couch_config.get("admin_password"):
    raise Exception("Missing 'admin_password' config attribute in [couchdb]")

  admin_user = couch_config.get("admin_user")
  admin_password = couch_config.get("admin_password")
  host = couch_config.get("host")

  # create the modules database if it doesnt exist yet
  cdb_client_modules = twentyc.database.couchdb.client.CouchDBClient(
    host,
    couch_config.get("db_modules"),
    auth="%s:%s" % (admin_user, admin_password)
  )

  # create the prefs database if it doesnt exist yet
  cdb_client_modules = twentyc.database.couchdb.client.CouchDBClient(
    host,
    couch_config.get("db_prefs"),
    auth="%s:%s" % (admin_user, admin_password)
  )

  _security = {
    "id" : "_security",
    "admins" : {
      "names" : [],
      "roles" : ["editor"]
    },
    "readers" : {
      "names" : [],
      "roles" : ["reader"]
    }
  }

  _security["admins"]["names"].append(couch_config.get("user"))

  create_security(host, couch_config.get("db_modules"), _security, admin_user, admin_password)
  create_security(host, couch_config.get("db_prefs"), _security, admin_user, admin_password)
  create_user(host, couch_config.get("user"), couch_config.get("password"), admin_user, admin_password)

  #print "%s : %s : %s" % (couch_config.get("password"), password_sha, salt)
