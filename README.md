# GovContractTweets

Automatically fetch and tweet new federal contract opportunities from SAM.gov.

## Project Overview
This project aims to automate the process of fetching federal contract opportunities from SAM.gov and posting them on Twitter. It helps users stay informed about new contracts that may be relevant to them.

## Features
- Fetches new contract opportunities from SAM.gov API
- Posts contract alerts to Twitter
- Prevents duplicate posts using SQLite database
- Runs automatically every 6 hours via GitHub Actions

## Installation and Setup Guide
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

## Usage Instructions
The script will run automatically every 6 hours via GitHub Actions. To run manually:

```bash
python contract_tweets.py
```

## Contribution Guidelines
We welcome contributions! Please fork the repository and submit a pull request with your changes. Ensure that your code adheres to the project's coding standards and includes appropriate tests.

## API Key Setup and Security Best Practices
- Never hardcode API keys in your source code.
- Store API keys in the `.env` file and use `dotenv` for management.
- Ensure the `.env` file is included in `.gitignore` to prevent accidental exposure.

## License
MIT
