import socket

###############################################################################

def instance_id_from_config(config):
  return config.get("vodka_id", "%s:%s" % (socket.gethostname(), config.get("port")))
