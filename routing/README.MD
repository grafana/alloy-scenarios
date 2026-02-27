# Example scenario for grafana alloy routing

Simple example for cases where a singular source [e.g. OCP cluster log forwarder] is sending logs from multiple applications, and you need to route it to different loki instances [or in the example case, same loki instance, but different tenants].

The example covers an if-else scenario, where looking at the logs contents, the `tenantKey` loki request metadata is populated, for the logs to be stored in the appropriate tenant.

In this setup, alloy is a single instance that receives logs from multiple OCP clusters [test and prod].

It checks the origin of the log [via the `hostname` field in the request] and afterwards checks the type of log [via the custom `message.logger` field].



Diagram:
```
									- - - Loki tenant test app
	OCP - - -						|
	[test]	|						| - - Loki tenant test audit
			---> Alloy ---> Loki ---
			|						| - - Loki tenant prod app
	OCP - - - 						|
	[prod]							- - - Loki tenant prod audit
```	


## Testing
The provided docker compose has a local promtail-alloy-loki-grafana setup to mimick a real env [using promtail to mimick an OCP log forwarder]. Logs are stored in a local minio s3 bucket.

use `docker compose up` to bring the system up. [note, if minio has errors starting up, create a `.customData` dir]

Put your log entries [with newline endings] inside the `support/promtail/myCustomLog.log` file. They will be automatically pushed to loki via alloy.

Open grafana [localhost:3000], login with default admin [`admin/admin`] and go to `Explore`.

You will have multiple loki datasources; use the query `{job="myApp"}`. 

Depending on the log content you put in the custom log file, the log will be stored in the appropriate loki tenant and is fetchable using the correct datasource.


## Message examples

Test app message [goes to test app tenant]

`{"@timestamp":"2025-10-31T09:40:25.229103272Z","hostname":"tos-worker-002.tos.example.come","level":"info","log_source":"container","log_type":"application","message":"{\"timestamp\":\"2025-10-31 10:40:25.229\",\"level\":\"INFO\",\"thread\":\"http-nio-8080-exec-5\",\"mdc\":{\"correlationId\":\"test\",\"uniqueTrackingId\":\"test\"},\"logger\":\"app\",\"message\":\"[START] msisdn=38763383706\",\"context\":\"default\"}"}`

Test audit message [goes to test audit tenant]

`{"@timestamp":"2025-10-31T09:40:25.229103272Z","hostname":"tos-worker-002.tos.example.come","level":"info","log_source":"container","log_type":"application","message":"{\"timestamp\":\"2025-10-31 10:40:25.229\",\"level\":\"INFO\",\"thread\":\"http-nio-8080-exec-5\",\"mdc\":{\"correlationId\":\"test\",\"uniqueTrackingId\":\"test\"},\"logger\":\"audit\",\"message\":\"[START] msisdn=38763383706\",\"context\":\"default\"}"}`

Prod app message [goes to app tenant]

`{"@timestamp":"2025-10-31T09:40:25.229103272Z","hostname":"pos-worker-001.pos.example.come","level":"info","log_source":"container","log_type":"application","message":"{\"timestamp\":\"2025-10-31 10:40:25.229\",\"level\":\"INFO\",\"thread\":\"http-nio-8080-exec-5\",\"mdc\":{\"correlationId\":\"test\",\"uniqueTrackingId\":\"test\"},\"logger\":\"app\",\"message\":\"[START] msisdn=38763383706\",\"context\":\"default\"}"}`

Prod audit message [goes to audit tenant]

`{"@timestamp":"2025-10-31T09:40:25.229103272Z","hostname":"pos-worker-001.pos.example.come","level":"info","log_source":"container","log_type":"application","message":"{\"timestamp\":\"2025-10-31 10:40:25.229\",\"level\":\"INFO\",\"thread\":\"http-nio-8080-exec-5\",\"mdc\":{\"correlationId\":\"test\",\"uniqueTrackingId\":\"test\"},\"logger\":\"audit\",\"message\":\"[START] msisdn=38763383706\",\"context\":\"default\"}"}`

