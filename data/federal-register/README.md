# Chunk 2 Federal Register demo source

PolicyTrace's first real source is Federal Register document **2024-20529**:

**Establishment of Reporting Requirements for the Development of Advanced Artificial Intelligence Models and Computing Clusters**

Key identifiers:

- Federal Register document: `2024-20529`
- Published: `2024-09-11`
- Citation: `89 FR 73612`
- Agency: Bureau of Industry and Security, Department of Commerce
- Docket: `240905-0231`
- RIN: `0694-AJ55`
- Regulations.gov docket: `BIS-2024-0047`

This is an AI-focused **proposed rule**, which is useful for the hackathon because it has both authoritative policy text and a public-comment docket. It should be treated as a historical proposed-rule demo source, not represented as a currently operative final rule.

## Fetch and normalize

From the repository root:

```bash
python backend/ingest_federal_register.py
```

The script uses the public Federal Register API and does not require an API key.

For a network-independent demo/CI run, use the checked-in fixture:

```bash
python backend/ingest_federal_register.py --offline
```

The offline fixture is intentionally a compact, curated excerpt of the same official document. It is for reliability testing and demo fallback; the normal live path still fetches the full Federal Register source.

Default output:

```text
data/federal-register/2024-20529.normalized.json
```

The normalized file contains:

- document metadata
- agency, citation, docket, RIN, dates, and source URLs when supplied by the API
- normalized full text
- stable chunks
- exact character offsets for every chunk

Those offsets let later PolicyTrace evidence records point back to exact source text instead of relying on generated citation text.

## Source URLs

Federal Register:

https://www.federalregister.gov/d/2024-20529

Federal Register API:

https://www.federalregister.gov/api/v1/documents/2024-20529.json

Regulations.gov:

https://www.regulations.gov/docket/BIS-2024-0047


## Locator and docket reliability

Chunking now carries the nearest recognizable Federal Register heading into each chunk so evidence locators have a human-readable section label instead of only a character range.

If the Federal Register API does not supply a Regulations.gov URL, the normalizer looks for a Regulations.gov docket ID in the official document text and builds the docket URL from that identifier.
