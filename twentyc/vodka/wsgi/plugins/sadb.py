from webapp import Plugin
from sqlalchemy import *
from sqlalchemy.orm import *

class Sadb(Plugin):

  db_engine = None
  url = None
  
  def __init__(self, id='db'):
    self.id = id
  
  def start(self):
    print "starting sadb plugin (%s)" % str(self.id)
    dbconf = self.config.get(self.id, {})
    self.url = dbconf.get('url')
    self.pool_size = int(dbconf.get('pool_size', 30))
    self.pool_recycle = int(dbconf.get('pool_recycle', 3600))

    if self.url:
      self.db_engine = create_engine(self.url, pool_size=self.pool_size, pool_recycle=self.pool_recycle)
      self.db = create_session(self.db_engine)
      self.meta = MetaData()

  def stop(self):
    print "stopping sadb plugin (%s)" % str(self.id)
    self.db_engine = None
    self.url = None
