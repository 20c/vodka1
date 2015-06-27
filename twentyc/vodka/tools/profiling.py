"""
Profiling tools and utils for vodka
"""

###############################################################################
# Extend Pympler - memory profiling tool

from pympler import summary, muppy
from pympler.util import stringutils

def pympler_snapshot(rows=None, limit=15, sort="size", order="descending"):
  """Print the rows as a summary.

  Keyword arguments:
  limit -- the maximum number of elements to be listed
  sort  -- sort elements by 'size', 'type', or '#'
  order -- sort 'ascending' or 'descending'
  """
  
  if not rows:
    rows = summary.summarize(muppy.get_objects())

  localrows = []
  for row in rows:
      localrows.append(list(row))
  # input validation
  sortby = ['type', '#', 'size']
  if sort not in sortby:
      raise ValueError("invalid sort, should be one of" + str(sortby))
  orders = ['ascending', 'descending']
  if order not in orders:
      raise ValueError("invalid order, should be one of" + str(orders))
  # sort rows
  if sortby.index(sort) == 0:
      if order == "ascending":
          localrows.sort(key=lambda x: _repr(x[0]))
      elif order == "descending":
          localrows.sort(key=lambda x: _repr(x[0]), reverse=True)
  else:
      if order == "ascending":
          localrows.sort(key=lambda x: x[sortby.index(sort)])
      elif order == "descending":
          localrows.sort(key=lambda x: x[sortby.index(sort)], reverse=True)
  # limit rows
  localrows = localrows[0:limit]
  for row in localrows:
      row[2] = stringutils.pp(row[2])
  # print rows
  localrows.insert(0, ["types", "# objects", "total size"])
  return pympler_prepare(localrows)


def pympler_prepare(rows, header=False):
  """Print a list of lists as a pretty table.

  Keyword arguments:
  header -- if True the first row is treated as a table header

  inspired by http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/267662
  """
  border = "="
  # vertical delimiter
  vdelim = " | "
  # padding nr. of spaces are left around the longest element in the
  # column
  padding = 1
  # may be left,center,right
  justify = 'right'
  justify = {'left': str.ljust,
             'center': str.center,
             'right': str.rjust}[justify.lower()]
  # calculate column widths (longest item in each col
  # plus "padding" nr of spaces on both sides)
  cols = zip(*rows)
  colWidths = [max([len(str(item)) + 2 * padding for item in col])
               for col in cols]

  borderline = vdelim.join([w * border for w in colWidths]) 
  result = ""
  for row in rows:
    result += "%s\n" % (vdelim.join([justify(str(item), width)
                           for (item, width) in zip(row, colWidths)]))
    if header:
      result += "%s\n" % (borderline)
      header = False
 
  #result = []
  #for row in rows:
  #  result.append(tuple([str(item)
  #                       for (item, width) in zip(row, colWidths)]))
  return result

###############################################################################
