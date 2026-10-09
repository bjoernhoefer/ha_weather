# Quickstart: Implementation verification

Use the existing development environment and service startup instructions in
README.md. These are planned checks, not already executed results.

1. Start the service normally. Open General settings; Logging immediately below
   it is initially collapsed. Open Logging and confirm an explicit empty state.
2. Refresh a configured forecast, then manually refresh Logging. Confirm newest
   entries show UTC time, severity, component and a completion summary.
3. Change a provider setting successfully. Confirm a fixed change summary with
   no submitted value. Cached forecast/log reads must not add entries.
4. Use pytest mocked provider/observation failures (not live credential-bearing
   requests) to verify safe cause categories and healthy-source fallback.
5. Select WARNING and ERROR. Confirm filtering precedes the result limit and a
   no-match response displays the empty state. Simulate failed log retrieval:
   display a generic error while forecast controls remain usable.
6. Check keyboard navigation and desktop/390px mobile layout; inspect DOM/network
   behavior to ensure text-only rendering and no requests while collapsed.

Local-mode example:

```sh
curl -i 'http://127.0.0.1:8080/api/logs?level=WARNING&limit=100'
```

Expect a JSON array and `Cache-Control: no-store`. Public-mode access uses the
existing API key setup; test absent/invalid/valid X-API-Key and Authorization headers
with fixtures rather than putting real secrets in shell history.

Planned focused validation:

```sh
pytest -q tests/test_activity.py tests/test_activity_backend.py tests/test_activity_ui.py tests/test_service.py tests/test_api.py tests/test_observations.py tests/test_providers.py tests/test_agro.py tests/test_azure_foundry.py
```

Run broader relevant regression checks after focused tests and record exact
outcomes. Confirm 501 entries evict the oldest, service isolation, restart-empty
behavior and sentinel absence from every serialized field. History is capped at
500 per service process, defaults to 100 visible entries, and is neither durable
nor shared across workers.
