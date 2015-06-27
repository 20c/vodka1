"""
Generate API documentation files
"""

import optparse
import os
import ConfigParser
import sys
import json
import re
import subprocess
import shutil

from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import HtmlFormatter

f = open(os.path.join(os.path.dirname(__file__),"../","config/VERSION"))
version = f.read().strip()
f.close()

ignore_examples = ["add-module.txt", "styles.css"]

def cli(cmd):
  #print cmd
  #return
  subprocess.check_call(cmd.split(' '))

def examples_index_entry(source, destination, file, webpath, indent=0):
  rv = {
    "name" : re.sub("\.[^\.]+$","", re.sub("[-_]"," ", re.sub("__",": ",file))),
    "link" : "%s/%s.html" % (webpath, file),
    "indent" : indent
  }
  if not os.path.exists(destination):
    os.makedirs(destination)

  cli("markdown_py %s -f %s/%s.html" % (source, destination, file))

  filename = "%s/%s.html" % (destination, file)

  fp = open(filename, "r")
  data = fp.read()
  fp.close()

  #data = data.replace("\n"," ")

  code_sec = re.findall("<code>(.+?)</code>", data, re.DOTALL)
  code_lst = []

  for code in code_sec:
    h_code = code
    t = re.match("code:(html|python|javascript|text).*", code)
    if t:
      t = t.group(1)
      h_code = re.sub("^code:%s\n"%t, "", h_code)
      if t in ["html","text"]:
        code_lst.append([code, h_code])
        continue
    else:
      t = "javascript"

    h_code = h_code.replace("&lt;", "<").replace("&gt;",">")
      
    h_code= highlight(
      h_code,
      get_lexer_by_name(t),
      HtmlFormatter(encoding="utf-8", cssclass="colorful")
    )
    code_lst.append(["<pre><code>%s</code></pre>" % code, h_code])

  for r in code_lst:
    data = data.replace(r[0], r[1])
  data = '<head><link rel="stylesheet" href="../styles.css" /></head><body>%s</body>' % data
  #data = '<style type="text/css">pre { background-color: #d8e1e9; padding: 5px; font-weight:bold }</style>%s' % data

  fp = open(filename, "w")
  fp.write(data)
  fp.close()



  return rv
 

def examples_gen(source, destination, public=False):

  index = []
  dirs = []
  files = []

  for file in os.listdir(source):
    
    path = os.path.join(source, file)
    
    # dont generate example files that are in the ignore list
    if file in ignore_examples or re.match("^\..+$", file):
      continue

    if public and re.match(".+\.priv$", file):
      continue

    # generate example files for sub dirs
    if os.path.isdir(path):
      dirs.append([file, path])

  dirs = sorted(dirs, key=lambda i: i[0])
  
  for d in dirs:
    file = d[0]
    path = d[1]
    index.append(file)
    files = []
    for subfile in os.listdir(path):
      if re.match(".+\.swp$", subfile):
        continue
      if public and re.match(".+\.priv$", subfile):
        continue
 
      subpath = os.path.join(path, subfile)
      if not os.path.isdir(subpath):
        files.append([subfile, subpath])

    for n in sorted(files, key=lambda i: i[0]):
      index.append(examples_index_entry(n[1], os.path.join(destination, file), n[0], "%s" % file, indent=1))
    
 
  file_contents = ["<ul>"]

  for point in index:
    if type(point) in [str,unicode]:
      file_contents.append('<li style="font-weight: bold; font-size: 14px">%s</li>' % point.capitalize())
    else:
      file_contents.append('<li style="padding-left:%dpx"><a href="%s">%s</a></li>' % (point.get("indent",0)*15, point.get("link"), point.get("name")))

  file_contents.append("</ul>")

  file_contents = "\n".join(file_contents)


  file_contents = '<head><link rel="stylesheet" href="styles.css" /></head><body>%s</body>' % file_contents
  f = open(os.path.join(destination, "index.html"), "w")
  f.write(file_contents)
  f.close()

  cli("cp %s %s" % (
    os.path.join(source, "styles.css"),
    os.path.join(destination)
  ))
    

def apidocs_gen(source, destination):
  
  if not os.path.exists(destination):
    print "Creating directory: %s" % destination
    os.makedirs(destination)
  else:
    print "Directory already exists, cleaning up..."
    cli("rm %s/* -rf" % destination)

  cli(
    "yuidoc %s -o %s -c %s/yuidoc/yuidoc.json --project-version %s" % (
      source,
      destination,
      source,
      version
    )
  )


if __name__ == "__main__":

  parser = optparse.OptionParser()

  parser.add_option("-c", "--config", dest="configfile", default="$VODKA_HOME/etc/$VODKA_CONFIG", help="path to a vodka config file with couchbase bucket information. Defaults to $VODKA_HOME/etc/$VODKA_CONFIG")

  parser.add_option("-p", "--path", dest="path", help="Files will be generated at this location. Note that if an existing directory is provided all files currently in it will be removed.")

  parser.add_option("--public", dest="public", help="If this flag is set, examples marked as private will not be published to the specified path", action="store_true")

  # parse options
  (options, args) = parser.parse_args()

  if not options.path:
    print "Please specify a path for the API docs destination using the --path option"
    sys.exit()

  # read config file from specified path
  configfile = os.path.expandvars(options.configfile)
  path = os.path.expandvars(options.path)
  source = os.path.join(
    os.path.dirname(__file__), "../", "htdocs", "js"
  )

  examples_dest = os.path.join(path, "examples")
  if not os.path.isdir(examples_dest):
    os.makedirs(examples_dest)
  
  config = ConfigParser.RawConfigParser()
  config.read(configfile)
  print "Read config from file: %s" % configfile

  if config.has_section("apidocs"):
    sources = dict(config.items("apidocs"))
  else:
    sources = {}

  for name,source_path in sources.items():
    symlink_name = os.path.join(source, name)
    if os.path.exists(symlink_name):
      print "Could not create symlink for %s -> %s - destination already exists" % (source_path, symlink_name)
      continue

    cli("ln -s %s %s" % (source_path, symlink_name))
    #shutil.copy(source_path, os.path.join(source, name)))

  print "Generating api docs"

  apidocs_gen(
    source,
    path
  )

  print "Generating examples ..."

  #shutil.copy(os.path.join(os.path.dirname(__file__), "../", "docs", "examples.txt"), path)
  examples_gen(
    os.path.join(os.path.dirname(__file__), "../", "docs"),
    examples_dest,
    options.public
  )



  print "Removing source code in documentation"

  cli("rm %s/files -rf" % path)

  print "Cleaning up..."

  for name,source_path in sources.items():
    cli("rm %s -f" % (os.path.join(source, name)))

  print "Done!"
