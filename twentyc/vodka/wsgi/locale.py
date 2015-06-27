
################################################################################
################################################################################

import sys
reload(sys)
sys.setdefaultencoding('utf-8')

import os

from datetime import datetime, timedelta
import time

import errno

import socket

import locale
import gettext
import babel

from babel.numbers import format_number, format_decimal, format_percent

import logging, logging.handlers

import csv

################################################################################
# locale information

class Locale:

  ##############################################################################

  def __init__(self, name, msgdir="msg"):
    self.name = name
    self.msgdir = msgdir

    ar = name.split("-")
    self.lang = ar[0]
    self.territory = None
    if len(ar) > 1:
      self.territory = ar[1]

    self._locale = babel.core.Locale(self.lang, self.territory)

    # no lazy init since these are loaded once per server start
    self.decimal = self._locale.number_symbols["decimal"]
    self.group = self._locale.number_symbols["group"]

    file = self.msgdir + "/" + self.name + ".csv"
    if os.path.exists(file):
      self.load_msg()

  ##############################################################################
  # dumps a dict of the language source file (muxed with english backing)

  def lang_src(self):
    # parse english file for defaults
    file = self.msgdir + "/en.csv"
    f = csv.DictReader(open(file), quotechar='"', delimiter=",", skipinitialspace=True)
    rv = {}

    for each in f:  
      line = {}
      msgid = each["MsgID"].strip()
      line["MsgID"] = msgid
      line["Comment"] = each["Comment"].strip()
      line["English"] = each["English"].strip()
      line["Translation"] = ""
      rv[line["MsgID"]] = line

    if self.lang == "en" and self.territory == None:
      for k, line in rv.items():
        line["Translation"] = line["English"]
    else:
      file = self.msgdir + "/" + self.name + ".csv"
      f = csv.DictReader(open(file), quotechar='"', delimiter=",", skipinitialspace=True)

      for each in f:   
        msgid = each["MsgID"].strip()
        # only use if english has it
        if msgid in rv and each["Translation"]:
          rv[msgid]["Translation"] = each["Translation"].strip()

    return rv

  ##############################################################################

  def __parse_msg(self, file, col):
    rv = {}
    f = csv.DictReader(open(file), quotechar='"', delimiter=",", skipinitialspace=True)

    for each in f:
      # use col if it exists, or fall back to english
      if col in each and each[col]:
        val = each[col].strip()
        if len(val) != 0:
          rv[each["MsgID"]] = val

    return rv

  ##############################################################################

  def load_msg(self):
    # parse english file for defaults
    en = self.__parse_msg(self.msgdir + "/en.csv", "English")

    if self.lang == "en" and self.territory == None:
      self.msgflat = en
    else:
      file = self.msgdir + "/" + self.name + ".csv"
      m = self.__parse_msg(file, "Translation")
      # mux english behind translation
      for k,v in en.items():
        if k not in m:
          m[k] = v
      self.msgflat = m

  ##############################################################################

  def htmlescape(self):
    import xml.sax.saxutils as saxutils
    for k,v in self.msgflat.items():
      self.msgflat[k] = saxutils.escape(v)

  ##############################################################################

  def _(self, msgid):
    return self.msgflat[msgid]

  ##############################################################################

  def fmt_number(self, n, prec):
    prec = int(prec)
    fmt = "#0"
    if prec:
      z = "0"
      z = z.rjust(prec, "0")
      fmt = fmt + "." + z
    #print "FMT prec " + str(prec) + " fmt " + fmt
    return format_decimal(n, format=fmt, locale=self._locale)

################################################################################
################################################################################

