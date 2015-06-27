from twentyc.database.tools import *
if __name__ == "__main__":

  parser = optparse.OptionParser()

  parser.add_option("-c", "--config", dest="configfile", default="$VODKA_HOME/etc/$VODKA_CONFIG", help="path to a vodka config file with couchbase bucket information. Defaults to $VODKA_HOME/etc/$VODKA_CONFIG")

  parser.add_option("-p", "--path", dest="path", default="../design", help="path to the location of design documents")
  # parse options
  (options, args) = parser.parse_args()

  # read config file from specified path
  configfile = os.path.expandvars(options.configfile)
  path = os.path.expandvars(options.path)

  config = ConfigParser.RawConfigParser()
  config.read(configfile)
  print "Read config from file: %s" % configfile

  couch_engine = dict(config.items("server")).get("couch_engine", "couchdb")
  couch_config = dict(config.items(couch_engine))

  for file in os.listdir(path):
    update_views(couch_engine, couch_config, os.path.join(path, file))
