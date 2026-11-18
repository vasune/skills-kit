# Contract checks for staged data pipelines

Concrete mismatch list for a pipeline split into a PRODUCER (formatter/extractor that writes spreadsheet or table files) and a CONSUMER (enricher/loader that reads them). Work down the list when studying one; each item is a silent failure mode, not a crash.

## Naming and structure between stages

- Sheet/table name matching: consumer may look names up case-insensitively while also requiring an exact set of sheets. List which sheets the consumer needs and which the producer actually writes.
- Schema equality assumptions: consumer may demand the working sheet mirror the output sheet (same columns, no service extras). Compare header lists, not column counts.
- Output-file naming: check the consumer's suffix handling (e.g. strips a `_format` suffix before writing `<name>_filled`) so copied producer files do not overwrite or double-suffix each other.
- Column-name comparison used as identity: it may ignore case and `ё`, or may split on `.`, or strip a trailing `.digits`. Two stages of the same repo sometimes disagree (one strips only trailing numeric suffixes, another truncates at the first dot) — that yields a key mismatch for columns whose names contain dots (units like `кг/пог.м`, `Вт/м•°К`, `л.с.`, `мм вод. ст.`).

## Service columns vs data columns

- Unit/flag columns (`Единица E-com`, activity flags, "filled" flags, "hide on site" style columns) are metadata, but the consumer's service-column filter is a substring list that was written against older headers. Any header missing from that list is promoted to a fillable characteristic and gets sent to the model as a field to fill.
- Test: diff the actual header set against the exclusion hints; report each header that slips through.

## Required-field derivation

- Required set usually = template/parameter columns, but with a fallback to "all data columns" when the template is absent or empty. With an empty template the fallback can select nothing meaningful (only the unit/flag columns), so no characteristic is ever collected while every row still reports as incomplete.
- Count how many input files/records have an empty template or zero parameter columns, and how many records that covers — that is the size of the hole, and it belongs in the report with a number.
- Default/skip markers (`пропуск`, `skip`, blank) that the consumer understands but the producer never emits make the completeness gate unreachable: with N required fields a record essentially never reaches the "complete" state. Report the reachable-set implication, not just the marker's absence.

## Reference/dictionary sheets

- The values/dictionary sheet is used for canonicalisation and for the "value not in reference" highlight. Consumer key building may truncate names (see dots above), silently disabling that check for the affected columns.
- Example/reference rows (the "filled cards" sheet used for few-shot naming or canonical spelling) are empty in producer-generated files while populated in hand-made ones — so naming standardisation and canonicalisation behave differently for the two input populations. State that explicitly; it is a behavioural difference, not a cosmetic one.

## Cheap verification recipe

- Empty offline fixture (`{"results": []}` or equivalent) + fake/stub model + dry-run + single record limit: exercises every fallback path, writes nothing, spends nothing.
- Then count what the run reported (processed / complete / needs-review) and compare with the derivation in the code — the mismatch usually points straight at the deciding branch.
- Verify doc-asserted totals (records in the feed, files produced, categories covered) against the regenerated artifacts; report both numbers.
