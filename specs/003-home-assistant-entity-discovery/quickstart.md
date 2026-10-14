# Quickstart: Home Assistant Entity Discovery and UI Alignment

## Prerequisites

- Run the service using the repository's existing setup.
- In **Real world measurements**, add a Home Assistant instance with its URL and long-lived token.
- For public deployments, configure and enter the service API key as usual.

## Validate entity discovery

1. Open **Real world measurements → Home Assistant instances** and save a configured instance.
2. In the measurement form, choose that instance and a location.
3. Search for part of an entity display name, for example `Garten`.
4. Confirm currently available matching entity names and IDs appear. Only results with a numeric state, temperature device class, and Celsius unit can be selected.
5. Select an eligible result, choose the location and outdoor scope, save it, and confirm it appears in the measurement list.
6. Confirm manual entry remains available and that an invalid/unreachable instance displays an understandable error without showing its token.

Discovery reads current Home Assistant states, not the full entity registry. Redirects and URLs containing embedded credentials are rejected; local/private Home Assistant URLs remain supported.

## Validate responsive alignment

1. Open the dashboard at a wide desktop viewport and compare the location selector and toolbar buttons.
2. Resize to a narrow mobile viewport and verify the controls remain aligned, usable, and free of horizontal scrolling.

## Automated checks

Run the existing test suite:

```sh
pytest
```

The API tests use the repository's offline Home Assistant mock response; no live Home Assistant installation is needed.
