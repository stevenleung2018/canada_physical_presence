# canada_physical_presence

Calculator of physical presence for the purpose of Canadian citizenship, built with
[Shiny for Python](https://shiny.posit.co/py/). It mirrors the
[official IRCC physical presence calculator](https://eservices.cic.gc.ca/rescalc/resCalcStartNew.do?lang=en).

> Unofficial tool. Always confirm your numbers with the official IRCC calculator before applying.

## Features

- Eligibility window computed as the 5 years immediately before the application date
- Absences (trips outside Canada), with Crown-servant trips counted as presence
- Pre-PR time as a temporary resident or protected person at ½ day credit, capped at 365 days
- Excluded periods (prison, parole, probation, pending refugee claim)
- Earliest eligible application date, assuming no further trips
- Day-by-day breakdown, input validation (overlapping trips, bad dates)
- CSV import / export for each list

## Rules implemented

Based on [IRCC: Who can apply](https://www.canada.ca/en/immigration-refugees-citizenship/services/canadian-citizenship/become-canadian-citizen/eligibility.html):

| Rule | Value |
| --- | --- |
| Required physical presence | 1,095 days in the 5 years before signing |
| Day in Canada as a PR | 1 day |
| Day in Canada before PR (temporary resident / protected person) | 0.5 day, max 365 days credit |
| Day abroad as a Crown servant (or family member) while a PR | 1 day |
| Prison, parole, probation | 0 days |
| Departure and return days | Counted as days in Canada |

## Project layout

```
app.py                          # Shiny UI + server (presentation only)
physical_presence/
  calculator.py                 # Pure calculation logic, no Shiny dependency
  period_editor.py              # Reusable Shiny module for date-period lists
tests/test_calculator.py        # pytest unit tests
canada_physical_presence.ipynb  # Original notebook prototype
```

## Getting started

```bash
python -m venv .venv && source .venv/bin/activate   # or: uv venv && source .venv/bin/activate
pip install -e ".[dev]"
shiny run --reload app.py
```

Then open <http://127.0.0.1:8000>.

### CSV format

Each list (absences, pre-PR periods, excluded periods) can be imported from a CSV:

```csv
start,end,category,note
2024-12-07,2024-12-21,,Hong Kong
```

`category` and `note` are optional; a blank category uses the list's default.

## Development

```bash
pytest -q             # run tests
ruff check .          # lint
ruff format .         # format
```

## License

MIT, see [LICENSE](LICENSE).
