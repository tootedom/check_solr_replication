# Overview

Nagios check script for checking replication/indexing issues on solr nodes, on a solr 4.2+ node (really should be a 4.3+
node due to: https://issues.apache.org/jira/browse/SOLR-4661).

The script has 3 functions:

- Checking a slave node to compare the indexVersion of its local index and the last known masters index version. (-R)
- Checking a that the index on the master has currently been updated (-A)
- Ping request to check that the solr is up, and the core is present (-P)

# Options:

The nagios check has the following options

```
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

```

# Available Checks

The three checks are:

## Index Age Check

-A  : Check age of the index on the given host, to the time on the local server (where the script is running).  Note it checks the indexVersion
      timestamp, to the current time on the server which is running the script.  Therefore if you specify -s value that isn't the current localhost,
      then you could be affected by timescew (NTP). The -c and -w are the number of seconds old the index can be.

### Example

Check that on the master that index has been updated in the last 60 seconds or a warning is issued, and issue a critical alert if the
index is over 5 mins old (no indexing in past 5 mins):

```
./check_solr_index_version_age.py -i core1,core2 -A -H localhost -p 8080 -u solr -w 60 -c 300
```

### Example Output

```
CRITICAL: Index Age Check.| { "status": "CRITICAL", "critical_cores": ["core1"], "warning_cores": [], "ok_cores": [],"num_cores_checked" : "1" , "num_ok_cores" : "0", "details": [ {"core":"core1","age(s)":"-1", "msg":"exception calling http://localhost:80/solr/core1/replication?wt=json&command=indexversion"} ] }

WARNING: Index Age Check.| { "status": "WARNING", "critical_cores": [], "warning_cores": ["core2"], "ok_cores": ["core1"],"num_cores_checked" : "2" , "num_ok_cores" : "1", "details": [ {"core":"core2","age(s)":"1388794731"},{"core":"core1","age(s)":"22"} ] }

OK: Index Age Check.| { "status": "OK", "critical_cores": [], "warning_cores": [], "ok_cores": ["core2","core1"],"num_cores_checked" : "2" , "num_ok_cores" : "2", "details": [ {"core":"core2","age(s)":"10104"},{"core":"core1","age(s)":"104"} ] }

```

## Slave replication version Check

-R  : Calls the slave's replication details endpoint. And obtains the "indexVersion" of the slave and master, and compares these two values against
      each other.  The -c and -w are the number of seconds difference there can be between the master and slave index

### Example
Check that the replication on this slave node, is less than 5 mins (300seconds) behind the index on the master or issue a warning.
Or if more than 10 mins behind issue a critical alert. (/replication?command=details&wt=json)

```
./check_solr_index_version_age.py -i core1,core2 -R -H localhost -p 8080 -u solr -w 300 -c 600
```

### Example Output

```
CRITICAL: Index Replication Version Age Check.| { "status": "CRITICAL", "critical_cores": ["core2"], "warning_cores": [], "ok_cores": ["core1"],"num_cores_checked" : "2" , "num_ok_cores" : "1", "details": [ {"core":"core2","age(s)":"198"},{"core":"core1","age(s)":"68"} ] }

CRITICAL: Index Replication Version Age Check.| { "status": "CRITICAL", "critical_cores": ["core2"], "warning_cores": [], "ok_cores": ["core1"],"num_cores_checked" : "2" , "num_ok_cores" : "1", "details": [ {"core":"core2","age(s)":"-1", "msg":"Slave index version information not available. Is this replicating? http://localhost:80/solr/core2/replication?wt=json&command=details"},{"core":"core1","age(s)":"68"} ] }

WARNING: Index Replication Version Age Check.| { "status": "WARNING", "critical_cores": [], "warning_cores": ["core2"], "ok_cores": ["core1"],"num_cores_checked" : "2" , "num_ok_cores" : "1", "details": [ {"core":"core2","age(s)":"198"},{"core":"core1","age(s)":"68"} ] }

OK: Index Replication Version Age Check.| { "status": "OK", "critical_cores": [], "warning_cores": [], "ok_cores": ["core2","core1"],"num_cores_checked" : "2" , "num_ok_cores" : "2", "details": [ {"core":"core2","age(s)":"198"},{"core":"core1","age(s)":"68"} ] }

```

## Ping Check
-P  : Just calls the ping endpoint on the solr admin, to check the core is available


### Example
Check that core1, and core2 are available on the current node

```
./check_solr_index_version_age.py -i core1,core2 -P -H localhost -p 8080 -u solr
```

### Example Output

```
CRITICAL: Error pinging cores(s)| { "status": "CRITICAL", "critical_cores": ["core1"], "warning_cores": [], "ok_cores": [],"num_cores_checked" : "1" , "num_ok_cores" : "0", "details": [ {"core":"core1","age(s)":"-1", "msg":"exception calling http://localhost:80/solr/core1/admin/ping?wt=json"} ] }

OK. Tested core(s) | { "status": "OK", "critical_cores": [], "warning_cores": [], "ok_cores": ["core1"],"num_cores_checked" : "1" , "num_ok_cores" : "1", "details": [ {"core":"core1","age(s)":"-1"} ] }

```

## Disable

You can run the plugin with the -d parameter, and this will just stop the plugin from running any checks.  It will
just output success:

```
OK: plugin is disabled, doing nothing | { "status":"ok" }
```

## Json Data

The -R, -A and -P return data (delimited by |) that is json data.  That will provide more information on why a core may have failed:

```
check_solr_index_version_age.py' -i core1 -R -H localhost -p 8080 -u solr -w 10 -c 300 -t 5 | cut -d'|' -f2 | python -mjson.tool
```

Sample Output:
```json
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
```