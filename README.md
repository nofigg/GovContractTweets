# GovContractTweets

Automatically fetch and tweet new federal contract opportunities from SAM.gov.

## Features

- Fetches new contract opportunities from SAM.gov API
- Posts contract alerts to Twitter
- Prevents duplicate posts using SQLite database
- Runs automatically every 6 hours via GitHub Actions

## Setup

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up environment variables in `.env` file:
   - SAM_API_KEY
   - TWITTER_API_KEY
   - TWITTER_API_SECRET
   - TWITTER_ACCESS_TOKEN
   - TWITTER_ACCESS_SECRET

4. Set up GitHub Secrets:
   Add the same environment variables as GitHub Secrets for the Actions workflow.

## Usage

The script will run automatically every 6 hours via GitHub Actions. To run manually:

```bash
python contract_tweets.py
```

## License

MIT
