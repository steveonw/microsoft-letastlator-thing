# Frontend Request Pattern

Use one request helper for workflow actions.

The goal is to avoid:
- duplicated fetch/error code
- overlapping model calls
- double-click request storms
- inconsistent state updates
- generic "HTTP 502" messages with no useful detail

## Suggested pattern

```javascript
const state = {
  analysis: null,
  busy: false,
};

async function api(path, payload = undefined) {
  const options = payload === undefined
    ? {}
    : {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      };

  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    const message =
      data.detail ??
      data.error ??
      `HTTP ${response.status}`;
    throw new Error(message);
  }

  return data;
}

function setBusy(value) {
  state.busy = value;
  document.querySelectorAll("button").forEach((button) => {
    button.disabled = value;
  });
}

async function analysisAction(path, payload, successMessage) {
  if (state.busy) return;

  setBusy(true);
  showMessage("Working…");

  try {
    state.analysis = await api(path, payload);
    render();
    showMessage(successMessage);
  } catch (error) {
    showMessage(String(error), true);
  } finally {
    state.busy = false;
    render();
  }
}
```

Adjust button disabling in `render()` so invalid workflow actions remain disabled after the global busy state ends.

## Example

```javascript
loadPolicyButton.onclick = () => {
  const documentNumber = documentNumberInput.value.trim();

  if (!documentNumber) {
    showMessage("Enter a Federal Register document number.", true);
    return;
  }

  analysisAction(
    "/api/source/load",
    {document_number: documentNumber},
    `Loaded ${documentNumber}.`,
  );
};
```

## Long-running calls

Model calls and Regulations.gov attachment ingestion can take time.

Show explicit states such as:

```text
Loading Federal Register source…
Analyzing policy with Microsoft Foundry…
Loading 12 public comments…
Verifying claims…
Building final brief…
```

The first implementation can use a generic `Working…` message.

Progress counts can come later.

## Error handling

Present server error messages to the user, but do not dump Python tracebacks into the UI.

Examples:

Good:

```text
Microsoft Foundry request timed out. The claim remains for human review.
```

Good:

```text
Load a Federal Register policy before loading comments.
```

Less useful:

```text
HTTP 400
```

## State replacement

After successful workflow actions:

```text
state.analysis = serverResponse
render()
```

Do not independently recreate workflow transitions in JavaScript.

The Python backend is the authority.

## Secrets

Provider keys must not be stored in `localStorage`.

If a browser form submits credentials for local demo configuration:
- send them to localhost FastAPI
- clear password inputs after successful submission
- return only booleans such as `has_api_key`
- keep the secret server-side/in process memory
