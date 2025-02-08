import os
import sqlite3
import requests
import tweepy
from datetime import datetime
from dotenv import load_dotenv
import logging

# Set up logging
logging.basicConfig(filename='logs/contract_tweets.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables
load_dotenv()

def setup_database():
    """Create SQLite database and contracts table if they don't exist."""
    conn = sqlite3.connect('contracts.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS contracts
        (notice_id TEXT PRIMARY KEY,
         title TEXT,
         due_date TEXT,
         url TEXT,
         posted_to_twitter INTEGER DEFAULT 0)
    ''')
    conn.commit()
    return conn

def fetch_sam_contracts():
    """Fetch today's contract opportunities from SAM.gov API."""
    api_key = os.getenv('SAM_API_KEY')
    if not api_key:
        raise ValueError("SAM API key not found in environment variables")

    today = datetime.now().strftime('%Y-%m-%d')
    
    headers = {
        'api_key': api_key,
        'Content-Type': 'application/json'
    }

    # SAM.gov API endpoint (you'll need to verify the exact endpoint and parameters)
    url = "https://api.sam.gov/opportunities/v2/search"
    params = {
        'postedFrom': today,
        'postedTo': today,
        'limit': 100
    }

    try:
        logging.info('Fetching new contract opportunities from SAM.gov')
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        logging.info('Received response from SAM.gov API')
        return response.json()['opportunityData']
    except Exception as e:
        logging.error('Error fetching contracts: %s', e)
        return []

def setup_twitter():
    """Initialize Twitter API client."""
    auth = tweepy.OAuthHandler(
        os.getenv('TWITTER_API_KEY'),
        os.getenv('TWITTER_API_SECRET')
    )
    auth.set_access_token(
        os.getenv('TWITTER_ACCESS_TOKEN'),
        os.getenv('TWITTER_ACCESS_SECRET')
    )
    return tweepy.API(auth)

def post_contract_tweet(twitter_api, contract):
    """Post a contract opportunity to Twitter."""
    tweet_text = f"""NEW CONTRACT ALERT 🚨
{contract['title']}
Deadline: {contract['due_date']}
More info: {contract['url']}"""

    try:
        logging.info('Posting tweet: %s', tweet_text)
        twitter_api.update_status(tweet_text)
        logging.info('Posted tweet: %s', tweet_text)
        return True
    except Exception as e:
        logging.error('Error posting tweet: %s', e)
        return False

def main():
    """Main function to fetch contracts and post to Twitter."""
    conn = setup_database()
    twitter_api = setup_twitter()
    
    # Fetch new contracts
    contracts = fetch_sam_contracts()
    
    for contract in contracts:
        cursor = conn.cursor()
        
        # Check if contract already exists
        cursor.execute('SELECT * FROM contracts WHERE notice_id = ?', 
                      (contract['notice_id'],))
        
        if not cursor.fetchone():
            # Store new contract
            cursor.execute('''
                INSERT INTO contracts (notice_id, title, due_date, url)
                VALUES (?, ?, ?, ?)
            ''', (
                contract['notice_id'],
                contract['title'],
                contract['due_date'],
                contract['url']
            ))
            
            # Post to Twitter
            if post_contract_tweet(twitter_api, contract):
                cursor.execute('''
                    UPDATE contracts 
                    SET posted_to_twitter = 1 
                    WHERE notice_id = ?
                ''', (contract['notice_id'],))
            
            conn.commit()
    
    conn.close()

if __name__ == "__main__":
    main()
