from module_manager import *
import os
import mimetypes
import time
import traceback
import base64
import threading
import twentyc.tools.CryptoUtil as cu

###############################################################################

APPSTORE_STATUS_PENDING = 0
APPSTORE_STATUS_APPROVED = 1
APPSTORE_STATUS_HIDDEN = 2

APPSTORE_LISTING_KEY = ":appstore-listing:%s"
APPSTORE_COMPONENT_KEY = ":appstore-component:%s.%s" 
APPSTORE_COMPANY_INFO_KEY = ":appstore-company:%s"
APPSTORE_CATEGORIES_KEY = ":appstore-categories:%s.%s"
APPSTORE_FILTERS_KEY = ":appstore-filters:%s"

###############################################################################

class AppAlreadyProvisioned(Exception):
  pass

class TrialAlreadyStarted(Exception):
  pass

class TrialEnded(Exception):
  pass

###############################################################################

class Appstore(ModuleManager):

  _started = False
  
  billing_pubkey = None,

  # category and filter refresh time
  cf_refresh = 10

  # trial duration time in seconds
  trial_t = 1800 

  # trial limit time (time between trials) in seconds
  trial_limit_t = 60*60*24*14

  # indicates whether the check trials timer is on or off
  started = 0

  #############################################################################

  def dbg(self, msg, verbose=True):
    msg = "Appstore: %s" % msg
    if self.log:
      self.log.debug(msg)
    if self.verbose and verbose:
      print msg

  #############################################################################

  def error(self, msg):
    raise Exception("Appstore: %s" % msg)

  #############################################################################
  
  def appstore_index(self):
    
    """
    Return index of all appstore listings
    """
    
    try:
      apps = self.cb_client.view("appstore", "index")
      rv = {}
      for row in apps:
        app = row.get("value")
        rv[app.get("name")] = app
      return rv
    except:
      raise

  #############################################################################

  def appstore_app_listing(self, app_name):
    
    """
    Return info for specified app listing

    app_name <str> name of the listing
    """
    
    try:
      return self.cb_client.get(APPSTORE_LISTING_KEY % app_name)
    except:
      raise

  #############################################################################

  def appstore_listing_save(self, app_listing):
    try:
      app_name = app_listing.get("name")
      self.cb_client.set(APPSTORE_LISTING_KEY % app_name, app_listing)
    except:
      raise


  #############################################################################

  def appstore_add_listing(self, app_name, modules, title="", owner="", tags=[], price=0.0, subscription=0, description=""):

    """
    Createa new app listing

    app_name <str> name of the listing - will error if anotherl isting with the same name already exists
    modules <dict> dict of modules and perms provisioned by this app. Keys should be the module names and
      values should be the permissions
    title <str> user friendly title of the listing
    owner <str> company name/id (as it is used to store to company info)
    tags <list> list of tags relevant to the listing
    price <float> 
    subscription <int> if > 0 indicates a subscription with a due time every n days
    description <str> short description of the listing
    """
    
    try:
      self.lock.acquire()
      app_listing = self.appstore_app_listing(app_name)

      # check if listing already has entry for module

      if not app_listing:
        
        tags.extend([
          app_name, 
          title,
          owner
        ])

        tags = [ x.lower() for x in tags ]

        app_listing = {
          "type" : "appstore_listing",
          "name" : app_name,
          "title" : title,
          "owner" : owner,
          "app_name" : app_name,
          "modules" : modules,
          "tags" : tags,
          "media" : [],
          "status" : APPSTORE_STATUS_PENDING,
          "description" : description,
          "price" : price,
          "subscription" : subscription
        }
        self.appstore_listing_save(app_listing)

        # create / update pgroup entry for app
        self.pgroup_update(
          "app:%s" % app_name,
          modules,
          source="appstore",
          reason="listing creation: %s" % app_name
        )

        return app_listing
      else:
        self.error("A listing for the name '%s' already exists" % app_name)

    except:
      raise
    finally:
      self.lock.release()

  #############################################################################

  def appstore_remove_listing(self, app_name, remove_provisioning=False, reason=None):

    """
    Remove a listing

    app_name <str> name of the listing 
    remove_provisioning <bool> if True remove app and provisioning from
      all users who have purchased this app
    """
    
    try:
      self.lock.acquire()

      app_listing = self.appstore_app_listing(app_name)
      if app_listing:

        # remove provisioning to that app
        if remove_provisioning:
          used_by = self.appstore_app_is_used_by(app_name)
          for user_id in used_by:
            self.appstore_remove_app_from_user(user_id["value"], app_name, reason=reason)
        
        # remove app listing and the listing's components
        for comp in app_listing.get("media",[]):
          self.cb_client.unset(APPSTORE_COMPONENT_KEY % (app_name, comp))

        self.cb_client.unset(APPSTORE_LISTING_KEY % app_name)

        # remove app's permgroup
        self.pgroup_remove("app:%s" % app_name, source="appstore", reason="listing removed: %s" % app_name)
  
        return True
      return False
    except:
      raise
    finally:
      self.lock.release()

  #############################################################################

  def appstore_change_listing_status(self, app_name, status):
    
    """
    Change the status of a listing 

    app_name <str> name of the listing
    status <int> new listing status
    """
    
    try:
      self.lock.acquire()
      if status not in [
        APPSTORE_STATUS_PENDING,
        APPSTORE_STATUS_APPROVED,
        APPSTORE_STATUS_HIDDEN
      ]:
        self.error("Invalid listing status: %s" % status)
      
      app_listing = self.appstore_app_listing(app_name)

      if not app_listing:
        self.error("Cannot change status of listing, as listing does not exist: %s" % app_name)


      app_listing["status"] = status
      self.appstore_listing_save(app_listing)

    except:
      raise
    finally:
      self.lock.release()
  
  #############################################################################

  def appstore_listing_add_component(self, name, component_name, contents, mime, minified=""):
    
    """
    Add a media component to a listing

    name <str> listing name
    component_name <str> unique component name (think filename)
    contents <str> will be base64 encoded
    mime <tuple> mimetype as returned by mimetypes.guesstype
    """
    
    try:
      
      app_listing = self.appstore_app_listing(name)
      list_name = "media"
      contents = base64.b64encode(contents)

      if not app_listing.has_key(list_name):
        app_listing[list_name] = []

      if component_name not in app_listing[list_name]:
        app_listing[list_name].append(component_name)
 
      self.appstore_change_listing(name, app_listing)

      self.cb_client.set(
        APPSTORE_COMPONENT_KEY % (name, component_name),
        {
          "listing" : name,
          "name" : component_name,
          "owner" : app_listing.get("owner"),
          "type" : "vodka_appstore_listing_component",
          "component_type" : list_name,
          "mime" : mime,
          "contents" : contents
        }
      )

    except:
      raise

  #############################################################################

  def appstore_listing_remove_component(self, name, component_name):
    
    """
    Remove media component from listing

    name <str> listing name
    component_name <str> name of the component to be removed
    """

    try:
      
      key = APPSTORE_COMPONENT_KEY % (name, component_name)
      component = self.cb_client.get(key)
      app_listing = self.appstore_app_listing(name)
     
      if component:
        app_listing["media"].remove(component_name)
        self.cb_client.unset(key)
        self.appstore_change_listing(name, app_listing)

    except:
      raise


  #############################################################################
  
  def appstore_listing_component(self, name, component_name):
    
    """
    Return the contents of a media component.

    Note that this will not base64 decode the contents

    name <str> listing name
    component_name <str> name of the component
    """
    
    try:
      key = APPSTORE_COMPONENT_KEY % (name, component_name)
      component = self.cb_client.get(key)
      return component
    except:
      raise


  #############################################################################

  def appstore_listing_module_fields(self, app_name):
    """
    Returns version of the first module in the app's module list
    Returns modified date of the most recently modified module in the app's
      module list
    Returns mod_status 1 if all modules in the app's module list have been
      approved, 0 if any of them hasn't
    """

    try:
      version = None
      modified = 0
      mod_status = 1

      app_listing = self.appstore_app_listing(app_name)

      if not app_listing:
        return ("",0)

      for mod_name, perms in app_listing.get("modules").items():
        mod_info = self.appstore_module_info(mod_name)

        if mod_info:
          if not version:
            version = mod_info.get("version")
          modified = max(modified, mod_info.get("modified"))

          if not mod_status:
            mod_status = 0

        return (version, modified, mod_status)

    except:
      raise

  #############################################################################

  def appstore_add_provisioning_to_user(self,user_id,listing_name, reason, transaction_id=0, xbahn_sync=True):
    """
    Set provisioning for all modules specified in an app listing on
    the specified user.

    listing_name <str> name of the appstore listing
    user_id <int> user id 
    reason <str> reason for provisioning change, eg. "subscription start"
    """

    try:
      
      app_listing = self.appstore_app_listing(listing_name)

      if not app_listing:
        raise Exception("Cannot find listing: %s", listing_name)

      user_perms = self.perms(user_id)
      mods_changed = {}
      
      self.pgroup_grant("app:%s" % listing_name, user_id, source="appstore", reason="listing '%s': %s" % (listing_name, reason), xbahn_sync=xbahn_sync)

      return mods_changed

    except: 
      raise

  #############################################################################

  def appstore_remove_provisioning_from_user(self, user_id, listing_name, reason="", xbahn_sync=True):
    """
    Unset provisioning for all modules specified in an app listing on
    the specified user.

    listing_name <str> name of the appstore listing
    user_id <int> user id 
    reason <str> reason for provisioning change, eg. "subscription end"
    """

    try:
      
      app_listing = self.appstore_app_listing(listing_name)

      if app_listing:
        self.pgroup_revoke("app:%s" % listing_name, user_id, source="appstore", reason="listing '%s': %s" % (listing_name, reason), xbahn_sync=xbahn_sync)
      return {}
      
    except:
      raise

  #############################################################################

  def appstore_user_info_key(self, user_id):

    """
    Return the key with which appstore user info documents are stored

    user_id <int> 
    """

    try:
      return "U%s.appstore_user_info" % user_id
    except:
      raise

  #############################################################################

  def appstore_app_is_used_by(self, listing_name):
    
    """
    Return a list of user ids that currently possess the specified app (listing_name)

    listing_name <str> app listing name
    """

    try:
      return self.cb_client.view("appstore", "user_active_apps", key=listing_name, stale=False)
    except:
      raise

  #############################################################################

  def appstore_all_active_trials(self):
    
    """
    Returns a list of app names and user ids of all active trials
    """

    try:
      r = self.cb_client.view("appstore", "user_active_trials", stale=False)
      rv = {}
      for row in r:
        
        user_id = row.get("value")
        app_name = row.get("key")

        if not rv.has_key(user_id):
          rv[user_id] = []
        
        rv[user_id].append(app_name)
      return rv
    except:
      raise

  #############################################################################
  
  def appstore_user_has_provisioning(self, user_id, app_name):

   """
   Check if a user already has provision to all the modules linked to
   an application (not necessarily provisioned by the application in question)

   user_id <int>
   app_name <str> name of the app listing
   """

   try:
     
     app_listing = self.appstore_app_listing(app_name)

     if not app_listing:
       raise Exception("Listing does not exist: %s" % app_name)

     for mod, perms in app_listing.get("modules", {}).items():
       if not self.perms_check(user_id, mod) & perms:
         return False

     return True
   except:
     raise

  #############################################################################

  def appstore_user_info(self, user_id):

    """
    Return appstore user info for the specified user id

    User info contains user specific appstore information such as
    purchased applications and demo tracking

    user_id <int> 
    """

    try:
      
      k = self.appstore_user_info_key(user_id)
      info = self.cb_client.get(k) or {
        "type" : "appstore_user_info",
        "user_id" : user_id,
        "trials" : {},
        "active_apps" : {}
      }
      return info

    except:
      raise

  #############################################################################

  def appstore_save_user_info(self, user_id, info):
    
    """
    Update user info for the sepcified user_id

    user_id <int>
    info <dict> dict with updated keys
    """
    
    try:
      self.cb_client.set(
        self.appstore_user_info_key(user_id),
        info
      )
    except:
      raise
  
  #############################################################################

  def appstore_add_app_to_user(self, user_id, listing_name, reason="", xbahn=True, transaction_id=0):

    """
    Add app to user. This is what we want to call when a payment has gone
    through. It takes care about provisioning access to the app's modules to the
    user amongst other stuff.

    user_id <int>
    listing_name <str> app listing name
    reason <str> reason for adding eg. "app purchase"
    xbahn <bool> if true and xbahn property is set on appstore, broadcast module
      reload notify
    transaction_id <str|int> payment transaction id, if any
    """

    try:
      self.lock.acquire()

      self.dbg("Adding app to user %s: %s" % (user_id, listing_name))
      self.appstore_end_trial_for_user(user_id, listing_name, xbahn=False)
      mods_changed = self.appstore_add_provisioning_to_user(user_id, listing_name, reason=reason, transaction_id=transaction_id)

      info = self.appstore_user_info(user_id)

      app_listing = self.appstore_app_listing(listing_name)

      info["active_apps"][listing_name] = {
        "purchase_price" : app_listing.get("price"),
        "transaction_id" : transaction_id,
        "subscription" : app_listing.get("subscription"),
        "subscription_end" : 0,
        "purchase_t" : time.time() 
      }
      self.appstore_save_user_info(user_id, info)

      return {
        "user_id" : user_id,
        "modules" : mods_changed
      }

    except:
      raise
    finally:
      self.lock.release()

  #############################################################################

  def appstore_remove_app_from_user(self, user_id, listing_name, reason="", xbahn=True):
    
    """
    Remove app from user (this function is what we want to call when a subscription
    to an app is ended, or when the app listing is removed completely from the
    app store.

    It will undo all the provisioning a user has to the app's modules

    user_id <int>
    listing_name <str> app listing name
    reason <str> reason for removal, eg. "subscription end"
    xbahn <bool> if true and xbahn property is set on appstore, broadcast module
      unload notify
    """
    
    try:
      self.lock.acquire()

      info = self.appstore_user_info(user_id)

      if not info["active_apps"].has_key(listing_name): 
        return

      self.dbg("Removing app from user %s: %s" % (user_id, listing_name))

      del info["active_apps"][listing_name]

      self.appstore_save_user_info(user_id, info)

      mods_removed = self.appstore_remove_provisioning_from_user(user_id, listing_name, reason=reason)

      mods_reset = self.appstore_sync_provisioning(user_id, info=info, reason="Listing '%s' removed" % listing_name)

      for k in mods_reset.keys():
        if mods_removed.has_key(k):
          del mods_removed[k]

      if xbahn:
        self.xbahn_notify_module_unload(user_id, mods_removed)
      
      return {
        "user_id" : user_id,
        "modules" : mods_removed
      }

    except:
      raise
    finally:
      self.lock.release()

  #############################################################################

  def appstore_cancel_subscription(self, user_id, listing_name, active_until=0, reason="", info={}):
    
    try:
      self.lock.acquire()

      info = self.appstore_user_info(user_id)

      sub_info = info["active_apps"].get(listing_name)

      if not sub_info:
        raise Exception("User has no subscription to '%s'" % listing_name)

      if sub_info.get("subscription_end"):
        return

      sub_info["subscription_end"] = active_until or time.time()
      sub_info["subscription_end_reason"] = reason

      self.appstore_save_user_info(user_id, info)

    except:
      raise
    finally:
      self.lock.release()

  #############################################################################

  def appstore_sync_provisioning(self, user_id, reason="", info={}):
    
    """
    Sync provisioning for user

    user_id <int> 
    info <dict> userinfo (if not supplied will be fetched autmatically using user id)
    """

    try:

      mods_reset = {}

      if not info:
        info = self.appstore_user_info(user_id)

      for name in info["active_apps"].keys():
        mods_reset.update(
          self.appstore_add_provisioning_to_user(user_id, name, reason="sync provisioning: %s - access regained via %s" % (reason, name))
        )

      for name in self.appstore_active_trials(info):
        mods_reset.update(
          self.appstore_add_provisioning_to_user(user_id, name, reason="sync provisioning (trial): %s - acess regained via TRIAL %s" % (reason, name))
        )

      return mods_reset


    except:
      raise

  #############################################################################

  def appstore_active_trials(self, user_id):
    
    """
    Return a list of currently active trials for the specified user

    user_id <int|dict> can be user id or userinfo dict
    """

    try:
       
      if type(user_id) == dict:
        info = user_id
      else:
        info = self.appstore_user_info(user_id)

      trials = info.get("trials", {})
      
      rv = []
      for app_name, trial in trials.items():
        if trial.get("status") == 0:
          rv.append(app_name)
      return rv

    except:
      raise

  #############################################################################

  def appstore_trial_status(self, user_id, app_name, t=0):

    """
    Check the trial status for the specified user and app

    user_id <str|dict>  can either be user id or a userinfo dict as returned
      by self.appstore_user_info

    app_name <str> listing name

    t <int> optional timestamp as returned by time.time() if omited time.time()
      will be called

    Returns:

      0 - no trial
      >0 - active or used up trial, the remaining seconds until another trial can be started
    """

    try:
      
      if type(user_id) != dict:
        info = self.appstore_user_info(user_id)
      else:
        info = user_id

      trial = info.get("trials", {}).get(app_name)

      if not trial:
        return (0,0,0)

      if not t:
        t = time.time()

      a = t - trial.get("end_t")
      d = self.trial_limit_t - a
      b = (trial.get("end_t") - trial.get("start_t")) - (t - trial.get("start_t"))

      if d > 0:
        return (trial.get("status"), d, b)
      else:
        return (trial.get("status"), 0, 0)

    except:
      raise

  #############################################################################

  def appstore_add_trial_to_user(self, user_id, app_name, xbahn=True):

    """
    Add a trial for an app to the specified user. Trials grant provisioning
      to the app's modules for a limited amount of time

    user_id <int> 
    app_name <str> name of the listing
    """

    try:
      self.lock.acquire()
      
      # make sure user doesnt have provisioning to app before proceeding

      if self.appstore_user_has_provisioning(user_id, app_name):
        raise AppAlreadyProvisioned([user_id, app_name])

      user_info = self.appstore_user_info(user_id)

      trials = user_info.get("trials", {})

      t = time.time()

      if trials.has_key(app_name):
        if trials.get(app_name).get("status") == 0:
          raise TrialAlreadyStarted([user_id, app_name])
        else:
          trial = trials.get(app_name)
          a = t - trial.get("end_t")
          d = self.trial_limit_t - a;
          if d > 0:
            raise TrialEnded([user_id, app_name, d])

      trials[app_name] = {
        "start_t" : t,
        "end_t" : t + self.trial_t,
        "status" : 0
      }
      user_info["trials"] = trials
      self.appstore_save_user_info(user_id, user_info)

      mods_changed = self.appstore_add_provisioning_to_user(user_id, app_name, reason="trial started: %s" % app_name)
      if xbahn:
        self.xbahn_notify_module_reload(user_id, mods_changed)

      return {
        "user_id" : user_id,
        "modules" : mods_changed
      }


    except:
      raise
    finally:
      self.lock.release()

  #############################################################################

  def appstore_end_trial_for_user(self, user_id, app_name, xbahn=True):
    
    """
    End app trial for specified user

    user_id <int>
    app_name <str> name of the listing
    """

    try:
      self.lock.acquire()
      
      user_info = self.appstore_user_info(user_id)
      trials = user_info.get("trials", {})

      if not trials.get(app_name):
        return

      trial = trials.get(app_name)

      if trial.get("status"):
        return

      trials[app_name]["status"] = 1
      trials[app_name]["end_t"] = time.time()
      self.appstore_save_user_info(user_id, user_info)

      mods_removed = self.appstore_remove_provisioning_from_user(user_id, app_name, reason="trial ended: %s" % app_name)
      mods_reset = self.appstore_sync_provisioning(user_id, info=user_info, reason="trial ended: %s" % app_name)

      for k in mods_reset.keys():
        if mods_removed.has_key(k):
          del mods_removed[k]
      
      if xbahn:
        self.xbahn_notify_module_unload(user_id, mods_removed)
        self.xbahn_notify_appstore_trial_ended(user_id, app_name)

      return {
        "user_id" : user_id,
        "modules" : mods_removed
      }

    except:
      raise
    finally:
      self.lock.release()

  #############################################################################
  
  def appstore_module_info(self, mod_name):
    return self.module_info(*self.module_token(mod_name))

  #############################################################################

  def appstore_change_listing(self, app_name, info, xbahn=True):
    
    """
    Update an app listing

    app_name <str> name of the listing
    info <dict> dict holding updated fields
    """

    try:
      self.lock.acquire()

      app_listing = self.appstore_app_listing(app_name)
      mchanged = False
      
      # check if listing already has entry for module

      if not app_listing:
        raise Exception("Cannot change listing, as appstore listing for this module does not exist: '%s'" % mod_name)

      if info.has_key("tags"):
        info["tags"] = [ x.lower() for x in info["tags"] ]

      if info.has_key("modules"):
        # modules has been set, check if modules differ from old listing
        # if they do, provisioning needs to be reset for all users that
        # have acess to this app
        lmo = app_listing.get("modules", {})
        lmn = info.get("modules", {})

        if len(lmo.keys()) != len(lmn.keys()):
          mchanged = True
        else:
          for mod in lmo.keys():
            if mod not in lmn.keys():
              mchanged = True
              break
      
      # if modules changed: remove provisioning to old modules

      # update listing

      app_listing.update(info)
      app_listing["status"] = APPSTORE_STATUS_PENDING
      self.appstore_listing_save(app_listing)
      
      # if modules changed: add provisioning to new modules

      if mchanged:
        self.pgroup_update(
          "app:%s" % app_name,
          info.get("modules"),
          source="appstore",
          reason="listing '%s' updated" % (app_name)
        )
 

    except:
      raise
    finally:
      self.lock.release()

  #############################################################################

  def appstore_company_info_key(self, name):
    """
    Return the key used to store company info

    name <str> company name
    """
    try:
      return APPSTORE_COMPANY_INFO_KEY % name
    except:
      raise

  #############################################################################

  def appstore_company_info(self, name):
    """
    Return company info document for the specified company

    name <str> company name
    """
    try:
      
      return self.cb_client.get(
        self.appstore_company_info_key(name)
      ) 

    except:
      raise

  #############################################################################

  def appstore_add_company(self, name, description, web, tags, address, phone, email):
    
    """
    add company info

    name <str> user friendly company name
    description <str> short description of the company
    web <str> website address of the company
    tags <list> list of tags for search and filtering
    """

    try:

      info = self.appstore_company_info(name)
      
      if not info:
        self.dbg("Adding company: %s" % name)

        info = {
          "name" : name,
          "description" : description,
          "web" : web,
          "address" : address,
          "phone" : phone,
          "email" : email,
          "tags" : tags
        }

        self.cb_client.set(
          self.appstore_company_info_key(name),
          info
        )

    except Exception, inst:
      raise

  #############################################################################

  def appstore_remove_company(self, name):
    
    """
    Remove company info for the company with the specified name
    name <str> company name
    """

    try:

      info = self.appstore_company_info(name)

      if info:
        self.dbg("Removing company: %s" % name)

        self.cb_client.unset(
          self.appstore_company_info_key(name)
        )

    except:
      raise

  #############################################################################

  def appstore_filters(self, brand="default", t=0):
    try:

      data = self.cb_client.get(APPSTORE_FILTERS_KEY % (brand))
      if not data:
        data = self.cb_client.get(
          APPSTORE_FILTERS_KEY % ("default")
        )
      return data or {}

    except:
      raise

  #############################################################################

  def appstore_filters_set(self, data, brand="default"):

    try:
      self.lock.acquire()
      self.cb_client.set(APPSTORE_FILTERS_KEY % (brand), data)
    except:
      raise
    finally:
      self.lock.release()


  #############################################################################

  def appstore_categories(self, lang="en", brand="default", t=0):
    try:

      data = self.cb_client.get(APPSTORE_CATEGORIES_KEY % (brand,lang))
      if not data:
        data = self.cb_client.get(
          APPSTORE_CATEGORIES_KEY % ("default", lang)
        )
        if not data:
          data = self.cb_client.get(
            APPSTORE_CATEGORIES_KEY % ("default", "en")
          )

      return data or {}

    except:
      raise

  #############################################################################

  def appstore_categories_set(self, data, lang="en", brand="default"):

    try:
      self.lock.acquire()
      self.cb_client.set(APPSTORE_CATEGORIES_KEY % (brand,lang), data)
    except:
      raise
    finally:
      self.lock.release()

  #############################################################################

  def run(self):
    if not self._started:
      self.start_process()
      self._started = True


  #############################################################################

  def stop(self):
    self.stop_process()
    self._started = False
  
  #############################################################################

  def start_process(self):
    
    try:

      if self.started:
        return

      self.started = 1
      t = threading.Thread(
        target = self.process
      )
      t.start()

    except:
      raise

  #############################################################################

  def stop_process(self):
    try:
      self.started = 0
    except:
      raise

  #############################################################################

  def process(self):

    store = self
    while self.started:
      try:
        
        # HANDLE TRIALS

        active_trials = store.appstore_all_active_trials()
        t = time.time()

        #print "Appstore: checking for active trials"

        for user_id, apps in active_trials.items():

          #print "Appstore: Found active trials for %s -> %s" % (user_id, apps)

          info = store.appstore_user_info(user_id)
 
          for app_name in apps:
            trial = info.get("trials",{}).get(app_name)
  
            if trial.get("status"):
              continue

            if store.appstore_trial_status(info, app_name, t=t)[2] <= 0:
              self.dbg("Trial for %s has run out" % (app_name))
              store.appstore_end_trial_for_user(user_id, app_name)

        # HANDLE ENDING SUBSCRIPTIONS

        ending_subs = self.cb_client.view("appstore", "user_ending_subs", stale=False)
        for row in ending_subs:
          data = row.get("value")
          sub_end = data.get("t")
          if sub_end <= t:
            self.dbg("Subscription '%s' ran out for '%s'" % (data.get("a"), data.get("u")))
            self.appstore_remove_app_from_user(data.get("u"), data.get("a"), reason="subscription was not renewed.")


      except Exception,inst:
        self.dbg("Error while checking for active trials (see log for details): %s"%str(inst))
        self.dbg(traceback.format_exc(), verbose=False)
      finally:
        time.sleep(1)


  #############################################################################

  def xbahn_notify_appstore_trial_ended(self, user_id, app_name):
    app_listing = self.appstore_app_listing(app_name)
    self.xbahn_notify_user(
      user_id,
      {
        "type" : "appstore_trial_ended",
        "app_name" : app_listing.get("title")
      }
    )

  #############################################################################

  def xbahn_notify_user(self, user_id, message):
    if self.xbahn:
      data = {
        "user_id" : user_id
      }
      data[str(uuid.uuid4())] = message
      self.xbahn.send(
        None,
        "__U.%s.notify" % user_id,
        data
      )

  #############################################################################

  def billing_load_pubkey(self, path):
    self.billing_pubkey = cu.BillingCrypto.load_rsa_key(None, filepath=path)


  #############################################################################

  def appstore_import_companies(self, path):
    print "Importing company information"

    f = open(path,"r")
    companies = json.load(f)
    f.close()

    for name, info in companies.items():
      self.appstore_remove_company(name)
      self.appstore_add_company(**info)

  #############################################################################
  
  def appstore_import_listings(self, path, om=False):

    f = open(os.path.join(path),"r")
    listings = json.load(f)
    f.close()

    for name, info in listings.get("listings", {}).items():
      if not om:
        print "Importing listing: %s" % name
      else:
        print "Importing listing media only: %s" % name

      approve = True

      if not om:
        app_listing = self.appstore_app_listing(name)

        if app_listing:
          self.appstore_change_listing(name, info)
        else:
          self.appstore_add_listing(
            name,
            **info
          )

      # import media
      media_path = os.path.join(os.path.dirname(path), name)
        
      if os.path.exists(media_path):
       
        print "removing old media components for %s" % name
        for comp in info.get("media", []):
          self.appstore_listing_remove_component(name, comp)

        for file in os.listdir(media_path):
          if file[0] == ".":
            continue

          media_file_path = os.path.join(media_path, file)
          mime = mimetypes.guess_type(media_file_path)

          print "Importing media component for listing  %s: %s %s" % (
            name, file, mime
          ) 
          f = open(media_file_path, "r")
          self.appstore_listing_add_component(
            name, file, f.read(), mime
          )
          f.close()

      self.appstore_change_listing_status(name, 1)
 

  #############################################################################

  def appstore_import_categories(self, path):

    try:
      f = open(path,"r")
      categories = json.load(f)
      f.close()

      for brand, lang_dict in categories.items():
        for lang, data in lang_dict.items():
          self.appstore_categories_set(data, lang, brand)
    except:
      raise

  #############################################################################

  def appstore_import_filters(self, path):

    try:
      f = open(path,"r")
      filters = json.load(f)
      f.close()

      for brand, data in filters.items():
        self.appstore_filters_set(data, brand=brand)
    except:
      raise

