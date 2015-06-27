"""
Super xBahn connected to an AMQP broker listening for data to forward to the
vodka update request
"""
import types
import qpid.messaging as qmsg
import traceback
import re
import json
import time
import threading
import uuid
import socket

import signal


hostname = socket.gethostname()

ACCESS_READ = 0x01
ACCESS_WRITE = 0x02

###############################################################################
# G L O B A L S

on_initial_request = []
topic_instructions = {}

###############################################################################
# F U N C T I O N S

###############################################################################

def filter_data(data, **kwargs):
  
  """
  Filter a list of data rows

  Keyword arguments

  Filter these keys, only keeping matches. If value is a list perform an
  in() check, otherwise check for equal values.
  """
  
  rv = []
  for row in data:
    for key, value in kwargs.items():
      if type(value) != list:
        if row.get(key) == value:
          rv.append(row)
      else:
        if row.get(key) in value:
          rv.append(row)
  return rv


###############################################################################

class Topic(object):
  
  def __init__(self, name, session, topic_name, queue_name="vodka", receiver=False, sender=False, queue_capacity=50):
    self.config = {}
    self.callbacks = []
    self.sender = None
    self.receiver = None
    self.queue_capacity = queue_capacity or 50

    self.connect(
      name,
      session,
      topic_name,
      queue_name=queue_name,
      receiver=receiver,
      sender=sender
    )

  #############################################################################

  def connect_sender(self):
    if not self.sender:
      self.sender = self.session.sender(self.name)

  #############################################################################

  def connect_receiver(self):
    if not self.receiver:
      self.receiver = self.session.receiver(self.address % (self.name, self.id))
      self.receiver.capacity = self.queue_capacity

  #############################################################################

  def connect(self, name, session, topic_name, queue_name="vodka", receiver=False, sender=False):
    self.name = name
    self.topic_name = topic_name
    self.session = session
    self.queue_name = queue_name

    #address = name
    #self.id = "xbahn.%s.%s" % (queue_name, uuid.uuid4())
    self.id = "xbahn.%s:%s:%s" % (queue_name, hostname, name)
    self.address = "%s; { link : { name : '%s', x-declare : { auto-delete: true, exclusive : true }}}" 

    self.time = time.time()

    self.receiver = None
    self.sender = None

    if receiver:
      self.connect_receiver()
    if sender:
      self.connect_sender()

    for key, config in topic_instructions.items():
      if re.match(key, topic_name):
        self.config = config
        break

  #############################################################################

  def reconnect(self, session):
    self.connect(
      self.name,
      session,
      self.topic_name,
      queue_name=self.queue_name,
      receiver=self.receiver,
      sender=self.sender
    )

  #############################################################################

  def receive(self, acknowledge=False):
    
    if not self.receiver or not self.receiver.available():
      return None

    message = self.receiver.fetch(timeout=1)
    
    if acknowledge:
      self.session.acknowledge()
    return message 

  #############################################################################

  def send(self, msg):
    if not self.sender:
      self.connect_sender()
    self.sender.send(qmsg.Message(msg))

  #############################################################################

  def available(self):
    if not self.receiver:
      return 0

    return self.receiver.available();

  #############################################################################

  def inactive(self, t):
    d = self.config.get("keep_alive",0)
    if d and t - self.time > d:
      return True
    return False

  #############################################################################

  def close(self):
    if self.receiver:
      self.receiver.close();
    if self.sender:
      self.sender.close();
    
###############################################################################

class xBahn(object):

  """
  xBahn client for sending and receiving data via xbahn

  host <str> qpid host
  port <int> qpid port
  exhange <str> qpid topic exchange
  app <vodka app> put None to this if you are using xbahn outside of vodka
  storage_dict <dict> refrence to the dict you want xbahn to store data in
    if not supplied data will be stored in xbahn.storage
  explicit_errors <bool> if true exceptions will be raised on xbahn usage errors
  username <str> qpid user name
  password <str> qpid password 
  queue_name <str> token to insert into the names of queues that are created by this xbahn instance. This is useful for quickly finding them in qpid-config
  queues list
  queue_capacity <int> queue capacity for receiving - defaults to 50
  """
  
  def __init__(self, host, port, exchange, app, storage_dict, explicit_errors=False, username=None, password=None, queue_name="vodka", queue_capacity=50, interval=0.05, handle_signals=False):
    
    # data storage
    if type(storage_dict) == dict:
      self.storage = storage_dict
    else:
      self.storage = {}

    # topic tracker
    self.topics = {}
    
    # status
    # 0 = disconnected
    # 1 = connecting
    # 2 = connected

    self.status = 0

    self.host = host
    self.port = port
    self.username = username
    self.password = password
    self.broker = ""
    self.tmp = 0
    self.queue_name = queue_name
    self.limits = {}
    self.started = False
    self.stopping = False

    self.lockConnect = threading.RLock()

    self.queue_capacity = queue_capacity or 50
    self.interval = interval

    self.app = app
    self.session = None
    self.connection = None
    self.exchange = exchange
    self.explicit_errors = explicit_errors 

    self.connect(host, port, username=username, password=password)
    
    if handle_signals:
      self.handle_signals()


  def handle_signals(self):
    return
    
    xb = self
    sigs = [
      signal.SIGABRT,
      signal.SIGINT,
      signal.SIGHUP,
      signal.SIGQUIT,
      signal.SIGSEGV,
      signal.SIGTSTP,
      signal.SIGTERM
    ]

    def sighandler(a,b):
      xb.disconnect()

    for i in sigs:
      signal.signal(i, sighandler)

  def error(self, msg, error=None):
    if self.explicit_errors:
      if error:
        self.dbg(msg)
        raise error
      else:
        raise Exception(msg)
    else:
      self.dbg("Warning: %s" % msg)
      if error and self.app and hasattr(self.app, "log"):
        self.app.log.error(traceback.format_exc())

  def dbg(self, msg):
    if self.app and hasattr(self.app, "dbg"):
      self.app.dbg(msg)
    else:
      print msg

  #############################################################################

  def set_limits(self, limits):
    if not limits:
      return
    for key,limit in limits.items():
      self.limits[key] = int(limit)

  #############################################################################

  def connect(self, host, port, username=None, password=None):
    
    """
    connect to the specified qpid instance. Called automatically by 
    constructor

    host <str> qpid host
    port <int> qpid port
    username <str> qpid user
    password <str> qpid password
    """

    try:
      self.lockConnect.acquire()
      self.status = 1

      self.host = host
      self.port = port
      self.username = username
      self.password = password
      
      self.dbg("Connecting xBahn %s: %s" % (host, port))

      self.broker = ("%s:%s" % (host,port))
      self.connection = qmsg.Connection(
        self.broker, 
        username=username, 
        password=password
      )
    
      self.connection.open()
      self.session = self.connection.session()
      self.status = 2

      # reconnect existing topics

      for name, topic in self.topics.items():
        topic.reconnect(self.session)

    except Exception, inst:
      self.status = 0
      self.error(str(inst), error=inst)
      self.error("xbahn failed to connect with error: %s, %s" % (inst.__class__, inst), error=inst)
    finally:
      self.lockConnect.release()

  ##############################################################################

  def reconnect(self):
    """
    Reconnect qpid connection
    """

    try:
      if self.status == 0 and self.host:
        self.dbg("Reconnecting xbahn: %s:%s" % (self.host, self.port))
        self.connect(
          self.host,
          self.port,
          username=self.username, 
          password=self.password
        )
        return True
      return False
    except:
      raise


  ##############################################################################
  
  def disconnect(self):
    
    """
    Close all qpid connections
    """

    if self.connection and self.status == 2:
      self.status = 0
      self.lockConnect.acquire()
      #self.dbg("Closing xBahn connection %s" % self.broker)
      
      try:
        for name, topic in self.topics.items():
          try:
            topic.close()
          except:
            pass
        self.connection.close()
      except Exception, inst:
        self.error(str(inst), error=inst)
      finally:
        self.session = None
        self.connection = None
      self.lockConnect.release()

  ##############################################################################
  
  def listen(self, topic):
    
    """
    Set xbahn up to receive data from the specified topic

    topic <str> qpid topic subject

    Returns the Topic object
    """
    
    try:
      if not self.session:
        #self.error("xBahn tried to listen to a topic without an established connection (%s)" % self.broker)
        return
      if not self.topics.has_key(topic):

        self.topics[topic] = Topic(
          "%s/%s" % (self.exchange, topic), 
          self.session, 
          topic, 
          queue_name=self.queue_name,
          receiver=True,
          queue_capacity=self.queue_capacity
        )

        for key, fn in on_initial_request:
          m = re.match(key, topic)
          if m:
            fn(self, topic, m)

      self.topics[topic].connect_receiver()
      return self.topics.get(topic)
    except qmsg.exceptions.ConnectionError, inst:
      self.dbg(traceback.format_exc())
      self.disconnect()
    except qmsg.exceptions.SessionClosed, inst:
      self.dbg(traceback.format_exc())
      self.disconnect()
    except Exception, inst:
      self.error(str(inst))
      raise
      
  ##############################################################################

  def send(self, ses, topic, cmd):
    
    """
    Send data to the specified qpid topic subject

    ses <vodka session> if using xbahn outside of vodk, pass None to this
    topic <str> qpid topic subject
    cmd <dict|list> data to send
    """
    
    try:
      if not self.session:
        if not self.reconnect():
          return
      if not self.topics.has_key(topic):
        self.topics[topic] = Topic(
          "%s/%s" % (self.exchange, topic), 
          self.session, 
          topic,
          queue_name=self.queue_name,
          queue_capacity=self.queue_capacity,
          sender=True
        )

      if type(cmd) == list:
        cmd = { "_list" : cmd }

      self.topics[topic].connect_sender()
      self.topics[topic].send(json.dumps(cmd))
    except qmsg.exceptions.ConnectionError, inst:
      self.dbg(traceback.format_exc())
      self.disconnect()
    except qmsg.exceptions.SessionClosed, inst:
      self.dbg(traceback.format_exc())
      self.disconnect()
    except Exception, inst:
      self.error(str(inst))
      raise
 
  ##############################################################################

  def create_storage_space(self, path):
    s = self.storage
    for a in path:
      if not s.has_key(a):
        s[a] = {}
      s = s[a]
    return (s,a)

  ##############################################################################

  def get_data(self, path, ses, storage=None, data=None, pos=None):

    """
    Return stored data. Note that there is a more straight forward way to do
    this by using the update() function further below.

    path <str or list> path to data location. To retrieve data for a specific 
    topic subject just pass the subject here. * are supported

    ses <vodka app session> pass None if runnin xbahn outside of vodka

    OPTIONAL

    storage <dic> if supplied data will be retrieved from this dict. Otherwise
      self.storage will be used
    """

    if not storage:
      storage = self.storage

    if type(data) != dict:
      data = {}

    if type(path) in [str, unicode]:
      path = path.split(".")

    i = 0
    l = len(path)

    #print "Get data for %s : %s" % (path, pos)

    for a in path:
      i += 1
      if a == "*":
        path_sub = path[i:]
        for k in storage.keys():
          mod = "%s.%s" % (pos,k)
          if i == l:
            #print "Checking perms for key (final object): %s via wildmark" % (mod)
            if not ses or ses.check_20c_module(mod) & ACCESS_READ:
              data[k] = storage[k]
          else:
            data[k] = {}
            self.get_data(path_sub, ses, storage=storage[k], data=data[k], pos="%s.%s" % (pos,k))
        #print "Returning data: %s" % data
        return data

      if pos:
        pos = "%s.%s" % (pos,a)
      else:
        pos = a

      if not storage.has_key(a):
        return data

      storage = storage[a]
      
      if type(storage) == list:
        if not ses or ses.check_20c_module(pos):
          return storage
        else:
          return []

    #print "Preparing data for %s" % pos

    for k,v in storage.items():

      if path:
        mod = "%s.%s" %(pos,k)
      else:
        mod = pos
      
      #print "Checking perms for key (final object): %s" % (mod)

      if not ses or ses.check_20c_module("%s" % (mod)) & ACCESS_READ:
        data[k] = v
    return data


  ##############################################################################

  def store(self, key, data):
    path = key.split(".")
    
    if data.has_key("_list"):
      data = data.get("_list")

    if type(data) == dict:
      k = data.keys()
      if len(k) == 1 and k[0] == path[-1]:
        s,end = self.create_storage_space(path[:-1])
      else:
        s,end = self.create_storage_space(path)

      s.update(data)
      for k,value in data.items():
        if type(value) == types.NoneType or (value == None and type(value) == dict):
          del s[k];
    elif type(data) == list:
      s,end = self.create_storage_space(path[:-1])
      end = path[-1]
      if s.has_key(end) and type(s.get(end)) == list:
        s[end].extend(data)
      else:
        s[end] = data
      
       
      lkey_1 = ".".join(path)
      lkey_2 = ".".join(path[:-1])

      limit = int(self.limits.get(lkey_1, self.limits.get(lkey_2, 0)))
      l = len(s[end])
      if limit and l > limit:
        s[end] = s[end][l-limit:]


  ##############################################################################

  def receive(self):

    """
    Receive data for all xbahn topic listeners that have been setup via
    listen.

    It is suggested you run this at an interval in its own thread.

    Wont block if there are no messages to retrieve.
    """
    

    try:
      if not self.session:
        return
    
      t = time.time()
      str_types = [str, unicode]
      for name, topic in self.topics.items():

        # if no user has requested data for this topic in a while
        # close the topic
        if topic.inactive(t):
          print "Closing topic %s for inactivity, %s" % (name, topic.config)
          topic.close()
          del self.topics[name]
          continue

        while topic.available() > 0:
          msg = topic.receive()
          data = msg.content
        
          if type(data) == str:
            data = json.loads(data)
          if type(data) == unicode:
            data = json.loads(data)

          for callback in topic.callbacks:
            callback(msg, data)
       
          self.store(msg.subject, data)
          #print "Got data for %s: %s" % (msg.subject, data)

      self.session.acknowledge()
    except qmsg.exceptions.ConnectionError, inst:
      self.dbg(traceback.format_exc())
      self.disconnect()
    except qmsg.exceptions.SessionClosed, inst:
      self.dbg(traceback.format_exc())
      self.disconnect()

  ##############################################################################

  def update(self, topic, ses=None, prepare=None, **kwargs):

    """
    Retrieve data for the specified topic

    topic <str> qpid topic subject, listener will be created for the topic 
    if it doesnt exist yet.

    OPTIONAL

    ses <vodka user session> pass None if running xbahn outside of vodka

    prepare <str> pass a function name here. data will be passed to that 
    function before its being returned.
    """
    
    amq_subject = topic

    for existing, e_topic in self.topics.items():
      
      if not e_topic.receiver:
        continue

      if re.match("^%s$" % re.sub("\*", "[^\.]+", existing), topic):
        amq_subject = existing
        break

    if not self.topics.has_key(amq_subject):
      if ses and ses.check_20c_module(amq_subject):
        try:
          tpc =self.listen(amq_subject)
          if tpc:
            print "Xbahn listener set up for topic '%s/%s' via update" % (self.exchange, amq_subject)
        except Exception, inst:
          if self.app and hasattr(self.app, "log"):
            self.app.log.debug(str(inst))
            self.app.log.debug(traceback.format_exc())
      return {}


    path = topic.split(".")

    #data = self.storage.get(topic)
    
    data = self.get_data(path, ses)

    T = self.topics.get(amq_subject)
    T.time = kwargs.get("time")

    id = kwargs.get("id")

    if data:
      #if type(data) == dict:
      #  data = data.values()
      if type(data) not in [list,dict]:
        return []
      
      if prepare:
        fnc = globals().get(prepare)
        if callable(fnc):
          data = fnc(data, ses, **kwargs)

      if type(id) == list:
        
        filtered_data = []
        if type(data) == list:
          items = data
        else:
          items = data.values()

        if id[0] in ["from", "to"] and path[-1] == "*":
          merged_data = []
          for row in items:
            if type(row) == dict:
              for child in row.values():
                merged_data.append(child)
            elif type(row) == list:
               merged_data.extend(row)
          items = merged_data

        if id[0] == "from":
          max = float(id[2])
          for row in items:
            try:
              if hasattr(row, "get") and float(row.get(id[1],0)) > max:
                filtered_data.append(row)
            except:
              pass
          data = filtered_data
        elif id[0] == "to":
          min = float(id[2])
          for row in items:
            try:
              if hasattr(row, "get") and float(row.get(id[1],0))< min:
                filtered_data.append(row)
            except:
              pass
          data = filtered_data



      if T.config.get("discard_data"):
        print "Discarding data for %s" % topic
        j = topic.split(".")
        space,k = self.create_storage_space(j[:-1])
        del space[j[-1]]
    return data or []

  #############################################################################

  def run(self):
    if self.run_in_thread :
      print 'RUNNING STARTUP HANDLER'
      self.run_in_thread(self)
    
    print "RUN"
    if not self.started:
      self.started = True
      while not self.stopping:
        self.receive()
        time.sleep(self.interval)
      if self.stopping:
        self.disconnect()
      self.started = False
      self.stopping = False

  #############################################################################

  def stop(self):
    if self.started:
      self.stopping = True

class xBahnThread(xBahn, threading.Thread) :
  def __init__(self, *a, **kw) :
    threading.Thread.__init__(self)
    self.run_in_thread = None
    if 'run_in_thread' in kw :
      self.run_in_thread = kw['run_in_thread']
      del kw['run_in_thread']
    xBahn.__init__(self, *a, **kw)
