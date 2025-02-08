# GovContractTweets Prompt Sheet

## 1. API Usage Limits & Handling
- Ensure SAM.gov API requests comply with rate limits.
- Implement exponential backoff for failed requests.
- Cache results temporarily to avoid redundant API calls.

## 2. Tweet Formatting & Compliance
- Keep tweets under 280 characters while including:
  - "NEW CONTRACT ALERT"
  - Contract Title
  - Deadline Date
  - Contract Total
  - Shortened Link to the contract
- Ensure no spammy or excessive posting (limit to 5 per run).
- Avoid duplicate posts by checking against the database.

## 3. Error Handling & Logging
- Log failed API requests and Twitter posting errors for debugging.
- Send email/slack notifications if failures persist.
- Maintain a fallback system (e.g., retry mechanism or logging for manual review).

## 4. Deployment & Security
- Store API keys as GitHub Secrets (never hardcoded).
- Use GitHub Actions to run the script every 6 hours.
- Ensure the repo has restricted write access to prevent unintended modifications.

## 5. Future Enhancements (Optional)
- Add keyword filters (e.g., only contracts relevant to small businesses).
- Implement multi-platform support (e.g., LinkedIn, Telegram).
- Optimize tweet generation with AI-driven summaries.

---
This document serves as a living guide for maintaining proper functionality and compliance within the GovContractTweets project. Please update it as needed.
