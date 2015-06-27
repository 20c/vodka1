import config
import os
from twentyc.tools.constants import *
from version import version

################################################################################
# error messages 

ERR_LOGIN_FIELDS_BLANK = "Please fill out both the username and the password field"
ERR_INVALID_ENV = "Invalid environment"
ERR_LOGIN_INVALID = "Invalid username / password"
ERR_LOGIN_PERMS = "You do not have permissions to log in"
ERR_LOGOUT_INVALID_SESSION = "You were logged out because your session was no longer valid."
ERR_GENERIC = "Server Error"
ERR_LOGIN_TIMEOUT = "Login timed out"
ERR_AUTH = "Need to be logged in for this action"
ERR_MISSING_ARGUMENT = "Argument is missing: %s"
ERR_INVALID_METHOD = "Invalid request method"
ERR_LAYOUT_LOAD = "Could not load layout"
ERR_LAYOUT_SAVE = "Could not save layout"
ERR_INVALID_INPUT = "Invalid input for %s"

ERR_NOTHING_TO_EXPORT = "Nothing to export"

ERR_VALUE_EMPTY = "Empty value for '%s'"
ERR_VALUE_STR = "Value for '%s' needs to be string"
ERR_VALUE_INT = "Value for '%s' needs to be numeric (int)"
ERR_VALUE_BOOL = "Value for '%s' needs to be boolean"
ERR_VALUE_FLOAT = "Value for '%s' needs to be numeric (float)"
ERR_VALUE_DICT = "Value for '%s' needs to be object (dict)"
ERR_VALUE_LIST = "Value for '%s' needs to be object (list)"
ERR_VALUE_UNKNOWN = "'%s' is an unknown property and cannot be set"
ERR_VALUE_TOO_BIG = "'%s' is too big - max. value: %d"
ERR_VALUE_TOO_SMALL = "'%s' is too small - min. value: %d"

ERR_KEY_INVALID_CHARACTER = "Invalid character(s) in '%s': %s";
ERR_KEY_LENGTH = "'%s' length too long, max. %d characters";
ERR_KEY_LENGTH_SHORT = "'%s' length too short, min. %d characters";
ERR_LIST_LENGTH = "Too many '%s' (max. %d), delete some before you add more";
ERR_LIST_INCOMPLETE = "Incomplete '%s' data (min. %d items)";

ERR_DOCTYPE_LIMIT = "'%s' limit met (max. %d) - delete some before creating another";

ERR_PREFS_POST_TOO_LARGE = "Uploaded preferences data too big, aborting. %d bytes max.";


ERR_LAYOUT_NAME_MISSING = "No layout name specified"

################################################################################
# input validation flags

INPUT_IS_SET = 0x01
INPUT_IS_NUM = 0x02
