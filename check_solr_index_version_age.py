#!/usr/bin/env python
# encoding: utf-8
"""
check_solr_index_version_age.py


Nagios check script for checking replication/indexing issues on solr nodes, on a solr 4.2+ node (really should be a 4.3+
node due to: https://issues.apache.org/jira/browse/SOLR-4661).

The script has 3 functions:

- Checking a slave node to compare the indexVersion of its local index and the last known masters index version. (-R)
- Checking a that the index on the master has currently been updated (-A)
- Ping request to check that the solr is up, and the core is present (-P)

OPTIONS:

Options:
  --version             show program's version number and exit
  -h, --help            show this help message and exit
  -H SOLR_SERVER, --host=SOLR_SERVER
                        SOLR Server address to connect to
  -p SOLR_SERVER_PORT, --port=SOLR_SERVER_PORT
                        SOLR Server port to connector
  -u SOLR_SERVER_PATH, --contextpath=SOLR_SERVER_PATH
                        SOLR Server's context path i.e. solr
  -P, --pingcheck       Monitroing Check: simple url ping that checks the solr
                        instance is running the given cores (indexes)
  -A, --agecheck        Monitoring Check: checking the age of the index given
                        cores is within the given values
  -R, --replicationcheck
                        Monitoring Check: checking the age of the index is
                        within a certain replication time lag
  -w THRESHOLD_WARN, --warn=THRESHOLD_WARN
                        WARN threshold for replication check (number of seconds)
  -c THRESHOLD_CRIT, --critical=THRESHOLD_CRIT
                        CRIT threshold for replication check (number of seconds)
  -i CORENAMES, --core=CORENAMES
                        The comma separated list of solr cores to be checked
  -t TIMEOUT, --timeout=TIMEOUT
                        The timeout for the request to solr
  -d, --disabled        The monitoring check is disabled

The three checks are:

-A  : Check age of the index on the given host, to the time on the local server (where the script is running).  Note it checks the indexVersion
      timestamp, to the current time on the server which is running the script.  Therefore if you specify -s value that isn't the current localhost,
      then you could be affected by timescew (NTP). The -c and -w are the number of seconds old the index can be.

-R  : Calls the slave's replication details endpoint. And obtains the "indexVersion" of the slave and master, and compares these two values against 
      each other.  The -c and -w are the number of seconds difference there can be between the master and slave index

-P  : Just calls the ping endpoint on the solr admin, to check the core is available

Examples:

Check that the replication on this slave node, is less than 5 mins (300seconds) behind the index on the master or issue a warning.
Or if more than 10 mins behind issue a critical alert. (/replication?command=details&wt=json) 

./solr-replication.py -i core1,core2 -R -H localhost -p 8080 -u solr -w 300 -c 600

Check that on the master that index has been updated in the last 60 seconds or a warning is issued, and issue a critical alert if the
index is over 5 mins old (no indexing in past 5 mins):

./solr-replication.py -i core1,core2 -A -H localhost -p 8080 -u solr -w 60 -c 300


Check that core1, and core2 are available on the current node

./solr-replication.py -i core1,core2 -P -H localhost -p 8080 -u solr


The -R, -A and -P return data (delimited by |) that is json data.  That will provide more information on why a core may have failed:

solr-replication.py' -i core1 -R -H localhost -p 8080 -u solr -w 10 -c 300 -t 5 | cut -d'|' -f2 | python -mjson.tool
{
    "critical_cores": [
        "core1"
    ], 
    "details": [
        {
            "age(s)": "-1", 
            "core": "core1", 
            "msg": "timeout calling http://localhost:8080/solr/core1/replication?wt=json&command=details"
        }
    ], 
    "num_cores_checked": "1", 
    "num_ok_cores": "0", 
    "ok_cores": [], 
    "status": "CRITICAL", 
    "warning_cores": []
}


"""

import contextlib
import datetime
import urllib
import socket
import urllib2, json
from optparse import OptionParser

def repstatus(core,timeout,corestatuschecks):
    """ calls <core>/replication?command=details&wt=json
    
    Obtaining the slave and master index version from the json output, and returns the difference in
    seconds between the two for the given core
    
    core -- the name of the core to check the index difference for
    timeout -- the time to wait for the http request to solr before returning with -1
    corestatuschecks -- the dict() object to record the time difference in, and any error message

    """
    replicationUrl     = baseurl + core + '/replication?' + urllib.urlencode({'command':'details','wt':'json'})
    
    diff = 0  
    rdata = callUrl(replicationUrl,timeout,corestatuschecks,core)

    if(len(rdata)==0):
        diff=-1

    slaveindexversion = None
    masterindexversion = None
    if(rdata.get('details') == None or rdata['details'].get('slave') == None):
        if diff!=-1:
            diff = -1
            recordCheckMsg(core,'All Slave index version information not available. Host ok? '+replicationUrl,corestatuschecks)
        
    else:
        slaveindexversion  = rdata['details'].get('indexVersion')
        if rdata['details']['slave'].get('masterDetails') == None:
            diff = -1
            recordCheckMsg(core,'Slave unable to retrieve master index version information. Host able to contact master? '+replicationUrl,corestatuschecks)
        else: 
            masterindexversion = rdata['details']['slave']['masterDetails'].get('indexVersion')

    if slaveindexversion == None:
        if diff!=-1:
            diff = -1
            recordCheckMsg(core,'Slave index version information not available. Is this replicating? '+replicationUrl,corestatuschecks)
    elif masterindexversion == None:
        if diff!=-1:
            diff = -1
            recordCheckMsg(core,'Master index version information not available. Is the master avaialable? '+replicationUrl,corestatuschecks)
    else:
        diff = indexDiffInSeconds(masterindexversion,slaveindexversion)

    recordAge(core,diff,corestatuschecks)

    return diff


def solrping(core,timeout,corestatuschecks):
    """ calls <core>/admin/ping?wt=json
    
    parses the json output for the 'status' json response
    
    core -- the name of the core to check for existence
    timeout -- the amount of time to wait on the request to solr for the ping, before stopping
     
    """
    ping_cmd = baseurl + core + '/admin/ping?' + urllib.urlencode({'wt':'json'})

    data = callUrl(ping_cmd,timeout,corestatuschecks,core)

    # try:
    #     with(contextlib.closing(urllib2.urlopen(ping_cmd,timeout = timeout))) as res:
    #         data = json.loads(res.read())
    # except urllib2.URLError, e:
    #     return 'ERROR'
    # except socket.timeout, e:
    #     # For Python 2.7
    #     return 'TIMEOUT'
    # except socket.error, e:
    #     return 'ERROR'
    if(len(data))==0:
        return 'CRITICAL'

    status = data.get('status')

    if(status == 'OK'):
        return 'OK'
    else:
        return 'CRITICAL'


def indexAgeInSeconds(core,timeout,corestatuschecks):
    """ calls <core>/replication?command=indexversion&wt=json
    
    Obtains the indexversion for the current core/index.  The indexversion is the milliseconds
    since epoch of the last time a commit was done on the core.
    
    This epoch is converted to seconds and compared to now() time on the current server where the script
    is executing.  It returns the difference in seconds between the two values.
    
    core -- the name of the core to obtain the index version for
    timeout -- the amount of time to wait on the request to solr
    corestatuschecks -- the dict object to store the index seconds diff from now() and any associated error msg

    """

    replicationUrl = baseurl + core + '/replication?' + urllib.urlencode({'wt':'json', 'command' : 'indexversion'})
  
    diff = 0
    data = callUrl(replicationUrl,timeout,corestatuschecks,core)
    if(len(data)==0):
        diff = -1

    if(data.get('indexversion') != None):
        ts = datetime.datetime.fromtimestamp(int(data.get('indexversion'))/1000)
        today = datetime.datetime.today()    
        diff = diffInSeconds(today,ts)
    else:
        recordCheckMsg(core,'index version information not available. Is the node avaialable? '+replicationUrl,corestatuschecks)
        diff = -1

    recordAge(core,diff,corestatuschecks)
    return diff


def callUrl(url,timeout,corestatuschecks,core):
    """ calls the given url, waiting for max timeout

    url -- The url to call
    timeout -- the number of seconds max for the url request to take
    corestatuschecks -- the dict object to store the status of the url call for the given core
    core -- the core name the url is being executed for

    """

    data = dict()
    try:
        with(contextlib.closing(urllib2.urlopen(url,timeout = timeout))) as res:
            data = json.loads(res.read())
    except urllib2.URLError, e:
        if hasattr(e,'reason') and isinstance(e.reason, socket.timeout):
            # For Python 2.6
            recordCheckMsg(core,'timeout calling '+url,corestatuschecks)
        else:
            recordCheckMsg(core,'exception calling '+url,corestatuschecks)
    except socket.timeout, e:
        # For Python 2.7
        recordCheckMsg(core,'timeout calling:'+url,corestatuschecks)
    except socket.error, e:
        recordCheckMsg(core,'socket error calling:'+url,corestatuschecks)

    return data
    
def recordAge(core,age,corestatuschecks):
    """  record the index age for the given core for later reporting
    
    core -- the name of the core to save the age
    age -- the number in seconds for age of the index in that core
    corestatuschecks - the dict object to save the age in associated to the core
     
    """
    corestatuschecks[core]['age'] = age
    

def recordCheckMsg(core,msg,corestatuschecks):
    """ record a message against for the given core for later reporting
    
    core -- the name of the core
    msg -- the string message to save
    corestatuschecks -- the dict object to save the message in
    
    """

    corestatuschecks[core]['msg'] = msg

    
def diffInSeconds(date1,date2):
    """ returns the difference in seconds between the two dates
    
    date1 -- date 1 to compare 
    date2 -- date 2 to compare
    
    """

    if(date1>date2) :
        td = (date1 - date2)
    else:
        td = (date2 - date1)

    return (td.microseconds + (td.seconds + td.days * 24 * 3600) * 10**6) / 10**6


def indexDiffInSeconds(indexversion1,indexversion2):
    """ compares the milliseconds that the solr indexversion represent against each other
    
    Returns the difference in seconds, between the two millisecond values the index version 
    numbers represent
    
    indexversion1 -- the milliseconds index version number for index 1
    indexversion2 -- the milliseconds index version number for index 2

    """

    date1 = datetime.datetime.fromtimestamp(int(indexversion1)/1000)
    date2 = datetime.datetime.fromtimestamp(int(indexversion2)/1000)
    return diffInSeconds(date1,date2)

def checkIndexLagAgainstThresholds(lag,warningThreshold,criticalThreshold):
    """ Checks the given lag against the thresholds

    lag -- the number of seconds to check against the given thresholds.  if -1 'ERROR' is returned
    warningThreshold -- The number of seconds, of which if the lag is greater 'WARNING' is returned
    criticalThreshold -- The number of seconds, of which if the lag is greater 'CRITICAL' is returned
    
    'OK' is returned if lag is less than warning threshold and critical threshold and not -1

    """
    
    if lag == -1:
        return "ERROR"
    
    if lag > criticalThreshold:
        return "CRITICAL"
    elif lag > warningThreshold:
        return "WARNING"
    else:
        return "OK"


def recordCheckStatus(core,status,statusMap):
    """ Records (increments) warning or critial errors in given statusMap
    
    core -- The name of the core for which the status was returned
    status -- The status of the check for the given core "CRITICAL", "ERROR", "WARNING"
    
    """

    if status == 'CRITICAL' or status == 'ERROR':
        statusMap['errors']+=1
        statusMap[core]['critical']+=1
    elif status == 'WARNING':
        statusMap['errors']+=1
        statusMap[core]['warning']+=1


def checkCommandLineOptions(cmd_options,cmd_parser):
    """ Checks that the command line arguments passed to the script are correct
    
    cmd_options from the OptionParser parser
    
    """

    if not cmd_options.plugin_enabled:
        print "OK: plugin is disabled, doing nothing | { \"status\":\"ok\" }"
        exit(0)

    if not (cmd_options.corenames) :
        print "Usage: you must specify a core/index (-i)"
        cmd_parser.print_help()
        exit(3)

    if not (cmd_options.solr_server and cmd_options.solr_server_port and cmd_options.solr_server_path):
        cmd_parser.print_help()
        exit(3)

    if not cmd_options.check_replication and not cmd_options.check_ping and not cmd_options.check_index_age:
        print "Usage: Please specify either of the following -R (replication checking), -P (ping check), or -A (index age checking)"
        exit(3)

    if not cmd_options.check_ping:
        if ((cmd_options.threshold_warn and not cmd_options.threshold_crit) or (cmd_options.threshold_crit and not cmd_options.threshold_warn)):
            print "Usage: Please specify the warning and critical values."
            exit(3)

        if cmd_options.threshold_crit <= cmd_options.threshold_warn:
            print "Usage: the value for (-c|--critical) must be greater than (-w|--warn)"
            exit(3)


def checkStatusOfCores(corestatuschecks,corenames, warningMsg, criticalMsg, okMsg):
    """ Checks the status of the core checks.
    
    The dict() object is populated for the core checking is populated as follows:
    
    (
    'errors' : 1,
    'core1' : (
               'critical' : 1
               'warning'  : 0,
               'msg'      : 'very old'
               'age'      : 600
              ),
    'core2' : (
               'critical' : 1
               'warning'  : 0,
               'msg'      : 'very old'
               'age'      : 600
              ),
    )
    
    The list of given corenames is looped through to create a list of cores that are in warning state, critical state, or ok state.
    A status message is then output detailing the information in json format.  This method exits the script with either 0 = ok, 1 = warning,
    2 == critical.
    
    corestatuschecks -- the built up list of cores, and their status 
    corenames -- the list of cores that have been checked
    warningMsg -- the warning message to output
    criticalMsg -- the critial message to output
    okMsg -- the ok message to output
    """

    statusmsg=''
    criticalCores = set()
    warningCores = set()
    okCores = set()
    i = 0
    for core in corenames:
        if (i > 0):
            statusmsg+=','
        if corestatuschecks[core]['warning']>0:
            warningCores.add(core)
        elif corestatuschecks[core]['critical']>0:
            criticalCores.add(core)
        else:
            okCores.add(core)
        statusmsg+="{{\"core\":\"{0}\",\"age(s)\":\"{1}\"".format(core,str(corestatuschecks[core]['age']))
        if len(corestatuschecks[core]['msg']) >0:
            statusmsg+=", \"msg\":\"{0}\"".format(corestatuschecks[core]['msg'])
        statusmsg+='}'
        i+=1

    criticalCoreString= ""
    warningCoreString= ""
    okCoreString= ""
    
    if len(criticalCores)>0:
        criticalCoreString="\""+ "\",\"".join(criticalCores) + "\""

    if len(warningCores)>0:
        warningCoreString="\""+ "\",\"".join(warningCores) + "\""

    if len(okCores)>0:
        okCoreString="\""+ "\",\"".join(okCores) + "\""
    

    statusmsg = " \"critical_cores\": [{0}], \"warning_cores\": [{1}], \"ok_cores\": [{2}],\"num_cores_checked\" : \"{3}\" , \"num_ok_cores\" : \"{4}\", \"details\": [ {5} ] }}".format(criticalCoreString, warningCoreString,okCoreString,len(corenames),len(corenames)-corestatuschecks['errors'],statusmsg)


    if corestatuschecks['errors'] > 0:        
        if len(criticalCores)>0:
            print criticalMsg+"| { \"status\": \"CRITICAL\","+statusmsg
            exit(2)
        elif len(warningCores)>0:
            print warningMsg+"| { \"status\": \"WARNING\","+statusmsg
            exit(1)
    else:               
        print okMsg+"| { \"status\": \"OK\","+statusmsg
        exit(0)


def prepareCoreStatusDataStructure(corenames,corestatuschecks):
    for core in corenames:
        corestatuschecks['errors']=0
        corestatuschecks[core] = dict()
        corestatuschecks[core]['critical']=0
        corestatuschecks[core]['warning']=0
        corestatuschecks[core]['msg']=''
        corestatuschecks[core]['age']=-1


def main():
    global baseurl, threshold_warn, threshold_crit, corenames
    corenames=set()

    cmd_parser = OptionParser(version="%prog 1.0.0")
    cmd_parser.add_option("-H", "--host", type="string", action="store", dest="solr_server", default="localhost", help="SOLR Server address")
    cmd_parser.add_option("-p", "--port", type="string", action="store", dest="solr_server_port", default="8080", help="SOLR Server port")
    cmd_parser.add_option("-u", "--contextpath", type="string", action="store", dest="solr_server_path", help="SOLR Server's context path i.e. solr", default="solr")
    cmd_parser.add_option("-P", "--pingcheck", action="store_true", dest="check_ping", help="Monitroing Check: simple url ping that checks the solr instance is running the given cores (indexes)", default=False)
    cmd_parser.add_option("-A", "--agecheck", action="store_true", dest="check_index_age", help="Monitoring Check: checking the age of the index given cores is within the given values", default=False)
    cmd_parser.add_option("-R", "--replicationcheck", action="store_true", dest="check_replication", help="Monitoring Check: checking the age of the index is within a certain replication time lag", default=False)
    cmd_parser.add_option("-w", "--warn", type="int", action="store", dest="threshold_warn", help="WARN threshold for replication check", default=300)
    cmd_parser.add_option("-c", "--critical", type="int", action="store", dest="threshold_crit", help="CRIT threshold for replication check", default=600)
    cmd_parser.add_option("-i", "--core", type="string", action="store",dest="corenames",help="The comma separated list of solr cores to be checked")
    cmd_parser.add_option("-t", "--timeout", type="string", action="store",dest="timeout", help="The timeout for the request to solr", default="30")
    cmd_parser.add_option("-d", "--disabled", action="store_false", dest="plugin_enabled",default=True)

    (cmd_options, cmd_args) = cmd_parser.parse_args()
    checkCommandLineOptions(cmd_options,cmd_parser)


    solr_server         = cmd_options.solr_server
    solr_server_port    = cmd_options.solr_server_port
    solr_server_path    = cmd_options.solr_server_path
    check_ping          = cmd_options.check_ping
    check_replication   = cmd_options.check_replication
    check_age           = cmd_options.check_index_age
    threshold_warn      = cmd_options.threshold_warn
    threshold_crit      = cmd_options.threshold_crit
    timeout             = int(cmd_options.timeout)
    corenames           = list(set(cmd_options.corenames.split(','))) 

    corestatuschecks    = dict()

    prepareCoreStatusDataStructure(corenames,corestatuschecks)

    baseurl = 'http://' + solr_server + ':' + solr_server_port + '/' +  solr_server_path + '/'


    for core in corenames:
        if check_replication:
            status = checkIndexLagAgainstThresholds(repstatus(core,timeout,corestatuschecks),threshold_warn,threshold_crit)
            recordCheckStatus(core,status,corestatuschecks)
        elif check_ping:
            status = solrping(core,timeout,corestatuschecks)
            recordCheckStatus(core,status,corestatuschecks)
        elif check_age:
            status = checkIndexLagAgainstThresholds(indexAgeInSeconds(core,timeout,corestatuschecks),threshold_warn,threshold_crit)
            recordCheckStatus(core,status,corestatuschecks)


    if check_ping:
        checkStatusOfCores(corestatuschecks,corenames,
                        "WARNING: Error pinging cores(s)",
                        "CRITICAL: Error pinging cores(s)",
                        "OK. Tested core(s) ")
    elif check_age:
        checkStatusOfCores(corestatuschecks,corenames,
                       "WARNING: Index Age Check.",
                       "CRITICAL: Index Age Check.",
                       "OK: Index Age Check.")
    elif check_replication:
        checkStatusOfCores(corestatuschecks,corenames,
                       "WARNING: Index Replication Version Age Check.",
                       "CRITICAL: Index Replication Version Age Check.",
                       "OK: Index Replication Version Age Check.")

if __name__ == '__main__':
    main()
