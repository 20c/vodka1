# specify where to read the config file from
import os, os.path
config_dir = os.path.expandvars("$VODKA_HOME/etc")
path = os.path.join(config_dir, os.getenv('VODKA_CONFIGFILE', 'vodka.conf'))

if not os.path.exists(path):
  path = os.path.join(".","etc","vodka.conf")

  if not os.path.exists(path):
    raise Exception("No vodka config found")
