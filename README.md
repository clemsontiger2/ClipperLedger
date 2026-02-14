# ClipperLedger

ClipperLedger is a Streamlit app for tracking barber shop transactions, reviewing monthly analytics, and projecting owner profit.

## Features

- Add and validate transactions with warning-based confirmation for unusual entries.
- View, download, and delete ledger records.
- Merge multiple barber CSV files with ID deduplication.
- Analytics dashboard with revenue, service mix, and busiest-hour charts.
- Owner dashboard with password gate, commission model, and 30-day projection.
- Automatic CSV backup before write operations.

## Data files

The app stores data in the project directory:

- `shop_data.csv` — primary ledger
- `shop_data_backup.csv` — automatic backup

## Run locally

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Start the app:

```bash
streamlit run streamlit_app.py
```
