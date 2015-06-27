from twentyc.tools.session import *
class UserSession(object):
  """
  Base 20c user session object.
  """
  
  def __init__(self, module_manager=None):
    self.auth_id = None
    self.client_id = None
    self.module_manager = module_manager
    self.module_perms = {}
    self.module_perms_structure = {}

  def set_auth(self, id):
    self.auth_id = id
    if self.module_manager:
      self.module_perms = self.module_manager.perms(id)
      self.module_perms_structure = perms_structure(self.module_perms)

  def clear_auth(self):
    self.auth_id = None
    self.module_perms = {}
    self.module_perms_structure = {}

  def check_20c_module_fast(self, name):
    if self.module_perms and not self.module_perms_structure:
      self.module_perms_structure = perms_structure(self.module_perms)
      
    if re.match("^__U\.%s\..+" % self.client_id, name):
      return 0x01|0x02|0x04

    rv =  perms_check_fast(self.module_perms_structure, name) 
    print "%s %s %s" % (name, rv, self.module_perms_structure)
    return rv

  def check_20c_module(self, name, ambiguous=False):

    """
    Check if session has access to the specified 20c module, return perms
    """

    if re.match("^__U\.%s\..+" % self.client_id, name):
      return 0x01|0x02|0x04

    return perms_check(self.module_perms, name, ambiguous=ambiguous)
