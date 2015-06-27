
import simplejson as json

def loads(*args, **kwargs):
  return json.loads(*args, **kwargs)

def dumps(*args, **kwargs):
  return json.dumps(*args, **kwargs)

################################################################################

class Encoder(json.JSONEncoder):
  def default(self, c):
    if hasattr(c, '__class__'):
      if hasattr(c, '__getstate__'):
        return c.__getstate__()
      else:
        return c.__dict__

    # Handles generators and iterators
    if hasattr(c, '__iter__'):
      return [i for i in c]

    # Handles closures and functors
    if hasattr(c, '__call__'):
      return c()

    return json.JSONEncoder.default(self, c)

################################################################################
################################################################################

