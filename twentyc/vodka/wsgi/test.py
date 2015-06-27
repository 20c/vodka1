"""
This is a test webapplication supposed to test various functionality and serve
as example code.

Check out the exposed functions, what they return will be the content of the 
response.
"""
import webapp
import imghdr
import os
import time
from ConfigParser import ConfigParser

# plugins need to be added before twisted_server is imported

from plugins import sadb

db = webapp.add_plugin(sadb.Sadb('db'))

# importing twisted_server allows us to run this file via the twistd
# web server
#
# twistd -ny test.py
#from twisted_server import *

from server import *

class SubTestApp(webapp.BaseApp):
  """
  This class will be a sub application of the main web application
  """
 
  @webapp.expose
  def details(self, **kwargs):
    """
    Return the contents of the environ object. 
    """
    return str(self.environ)

  @webapp.expose  
  def test(self, **kwargs):
    """
    Redirect to /base/test1.jpg
    """
    raise HTTPRedirect("/base/test1.jpg")

class TestApp(webapp.BaseApp):
  
  """
  This class will be the main web application
  """

  #here we are exposing the SubTestApp as a child of the this
  #application
  #
  #it will be accessable via /sub

  sub = SubTestApp()
  sub.exposed = True

  def __init__(self):
    self.config = webapp.dict_conf("server.conf")
    print str(self.config)

  
  @webapp.expose
  def fileupload(self, **kwargs):
    """
    Test file upload
    """
    if not kwargs.has_key('file'):
      r = "".join([
        '<form method="POST" action="/fileupload" enctype="multipart/form-data">',
        '<input type="file" name="file" />',
        '<input type="submit" value="Upload" />',
        '</form>'
      ])
      return r
    else:
      f = kwargs.get("file")
      ft = imghdr.what("", f)
      
      if ft != "jpeg":
        return "Only jpegs are allowed, "+str(ft)

      fout = open(os.path.join(serverConf.get("root"), "htdocs/test.jpg"), "wb")
      fout.write(f)
      fout.close()
      return '<a href="/base/test.jpg">Click</a>'

  @webapp.expose
  def dump(self, **kwargs):
    """
    Dump contents of the environ object
    """
    return str(kwargs.get('__environ'))

  @webapp.expose  
  def index(self, **kwargs):
    """
    Index page, / with no path components will be dispatched to this function
    """
    return '<html><head><link rel="stylesheet" href="/base/main.css" type="text/stylesheet" /></head><body>SCHNELL SCHNELL!!</body></html>'


  @webapp.expose  
  def post_test(self, **kwargs):
    """
    Test form submission
    """
    s = "%s<hr />%s %s" % ( 
      str(kwargs.keys()),
      '<form action="/post_test" method="post"><input type="text" name="firstname" /><input type="submit" value="OK" />',
      kwargs.get("firstname", "")
      )
    return s

  @webapp.expose  
  def cookie_test(self, **kwargs):
    """
    Test cookies and sessions
    """
    req = kwargs.get('__request')
    ses = req.get('session')

    if not ses.data.get("counter"):
      ses.data["counter"] = 1
    else:
      ses.data["counter"] += 1

    t = webapp.get_cookie(req, "tame")
    
    req["cookies_out"]["tame"] = str(time.time() )

    return "%s : %s" % (str(ses.data), str(t))


class SecondApp(webapp.BaseApp):
  """
  A second web application that will be mounted on a different
  location
  """
  @webapp.expose  
  def index(self, **kwargs):
    return "Second app responding!"

# here we are created and mounting our applications

Test = TestApp()
SApp = SecondApp()
webapp.url_map.append(["/second", SApp])
webapp.url_map.append(["", Test])

if serverConf.get('wsgiserver') == "gevent":
  gevent_start_server() 
