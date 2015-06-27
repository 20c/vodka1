
# vodka

vodka is a real time python web service daemon

### License

Copyright 2015 20C, LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this softare except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

### Configuration

#### install new vodka instance
bartender install --prefix=/path/to/new/vodka-instance

#### sets VODKA_HOME and VODKA_CONFIGFILE
. /path/to/new/vodka-instance/setenv.sh

#### edit vodka config
vim $VODKA_HOME/etc/$VODKA_CONFIGFILE

#### finalze vodka setup (ignore document conflicts, when the user for couchdb already exists)
bartender setup

#### install vodka modules managed within the vodka instance structure
checkout/copy any vodka modules into $VODKA_HOME/modules
bartender install_modules

#### install vodka module from external location
bartender install_module --path=/path/to/module

#### run vodka instance
. $VODKA_HOME/runserver.sh

