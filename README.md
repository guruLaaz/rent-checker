# Rent Checker

A Python script that checks your Gmail for Interac e-Transfer notifications and matches them against a list of expected renters. Quickly see who has paid and who hasn't.

## How It Works

1. Connects to your Gmail account via the Gmail API (OAuth2)
2. Searches for emails in the `Transfers Interac` Gmail label that are from `notify@payments.interac.ca`
3. Verifies each email's `From` header matches `@payments.interac.ca` to prevent false positives
4. Parses sender names and amounts from the email subjects/bodies
5. Compares against your list of renters and expected amounts
6. Prints a summary showing who has paid and flags any mismatches

## Setup

### Prerequisites

- Python 3.10+
- A Gmail account with Interac e-Transfer notifications filtered into a label called `Transfers Interac`

### 1. Install Dependencies

```bash
pip install google-auth google-auth-oauthlib google-api-python-client
```

### 2. Set Up Google OAuth2 Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use an existing one)
3. Enable the **Gmail API** (APIs & Services > Library > search "Gmail API")
4. Configure the **OAuth consent screen** (APIs & Services > OAuth consent screen):
   - Choose "External" user type
   - Add the scope `https://www.googleapis.com/auth/gmail.readonly`
   - Add your Gmail address as a test user
5. Create **OAuth credentials** (APIs & Services > Credentials > Create Credentials > OAuth client ID):
   - Application type: **Desktop app**
   - Download the JSON file and save it as `credentials.json` in the project folder

### 3. Configure Your Renters

Edit `renters.json` with your renter details:

```json
{
  "renters": [
    { "name": "John Smith", "expected_amount": 1200.00 },
    { "name": "Jane Doe", "expected_amount": 950.00 }
  ]
}
```

- **name**: The renter's name as it appears on their Interac transfers (case-insensitive matching, hyphens and spaces are treated as equivalent)
- **expected_amount**: The rent amount you expect. If the transfer amount differs, it will be flagged. This field is optional.

### 4. First Run (Authorization)

```bash
python check_rent.py
```

On the first run, your browser will open asking you to authorize the app to read your Gmail. After authorizing, a `token.json` file is saved. The access token expires after 1 hour, but the script automatically refreshes it using the stored refresh token, so you should never need to re-authorize unless you revoke access from your Google account.

## Usage

```bash
# Check the last 5 days (default)
python check_rent.py

# Check the last 30 days
python check_rent.py --days 30

# Check from a specific date to now
python check_rent.py --after 2026/03/01

# Check a specific date range
python check_rent.py --after 2026/02/01 --before 2026/03/01
```

### Example Output

```
Connecting to Gmail...
Found 10 Interac transfer(s) (last 5 days).

  Rent Transfers (last 5 days)
  ───────────────────────────────────────
  John Smith        $1,200.00   YES
  Jane Doe              -       NO

  Some transfers are MISSING.
```

## File Structure

```
rent-checker/
├── check_rent.py       # Main script
├── renters.json        # Your renter list (edit this)
├── credentials.json    # Google OAuth credentials (not tracked by git)
├── token.json          # OAuth token, auto-generated on first run (not tracked by git)
├── .env.example        # Example env file (legacy, not needed with OAuth2)
├── .gitignore
└── README.md
```

## Security

The following files contain sensitive data and are excluded from git via `.gitignore`:

- `credentials.json` - Your Google OAuth client secret
- `token.json` - Your OAuth access/refresh token
- `.env` - Legacy credentials file (not needed with OAuth2)
