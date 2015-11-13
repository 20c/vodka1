# django <-> vodka synergy

"""
Xbahn replication receiver to replicate django-namespace-perms data to valid
vodka perms using the vodkatools module manager
"""

import twentyc.xbahn.couchdb.replication as replication
import twentyc.vodka.tools.module_manager as modman
import twentyc.database as database
from twentyc.tools.thread import RunInThread
import time

class NamespacePermsReceiver(replication.Receiver):
  def __init__(self, xbahn_connection, couchdb_client, config, namespace, batch_limit=1000, batch=True):
    replication.Receiver.__init__(self, xbahn_connection, couchdb_client, config, namespace, batch_limit=batch_limit, batch=batch)
    self.module_manager = modman.ModuleManager()

    self.user_couchdb = database.ClientFromConfig(
      "couchdb",
      self.config.get("vodka_modules"),
      "vodka_modules"
    )

    self.module_manager.set_database(self.user_couchdb)
    self.module_manager.set_xbahn(self.xbahn.get("main"))
    self.module_manager.disable_perms_log = True

  def handle_save_GroupPermission(self, docname, id, doc):
    print docname, doc
    self.module_manager.pgroup_perms_set(
      doc.get("group").get("name"),
      doc.get("namespace"),
      doc.get("permissions"),
      force=True,
      source="xbahn replication",
      reason="xbahn replication"
    )

  def handle_delete_GroupPermission(self, docname, ids, docs):
    for id, doc in docs.items():
      self.module_manager.pgroup_perms_set(
        doc.get("group").get("name"),
        doc.get("namespace"),
        -1,
        force=True,
        source="xbahn replication",
        reason="xbahn replication"
      )

  def handle_save_UserPermission(self, docname, id, doc):
    self.module_manager.perms_set(
      doc.get("user"),
      doc.get("namespace"),
      doc.get("permissions"),
      force=True,
      source="xbahn replication",
      reason="xbahn replication"
    )

  def handle_delete_UserPermission(self, docname, ids, docs):
    for id, doc in docs.items():
      self.module_manager.perms_set(
        doc.get("user"),
        doc.get("namespace"),
        -1,
        force=True,
        source="xbahn replication",
        reason="xbahn replication"
      )

  def handle_save_User_groups(self, docname, id, doc):
    t = time.time()
    self.module_manager.pgroup_grant(
      doc.get("group").get("name"),
      doc.get("user"),
      source="xbahn replication",
      reason="xbahn replication"
    )
    t2 = time.time()
    print "Assign group: %s %s %.5f" % (doc.get("group").get("name"), doc.get("user"), (t2-t))

  def handle_delete_User_groups(self, docname, ids, docs):
    for id, doc in docs.items():
      t = time.time()
      self.module_manager.pgroup_revoke(
        doc.get("group").get("name"),
        doc.get("user"),
        source="xbahn replication",
        reason="xbahn replication",
      )
      t2 = time.time()
      print "Revoking group: %s %s %.5f" % (doc.get("group").get("name"), doc.get("user"), (t2-t))


###############################################################################
