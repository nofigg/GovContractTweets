import os
import sqlite3
import requests
import tweepy
import time
from datetime import datetime, timedelta
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
    
    # Drop existing table to update schema
    c.execute('DROP TABLE IF EXISTS contracts')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS contracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_id TEXT UNIQUE,
            title TEXT,
            posted_at TEXT,
            value REAL,
            score REAL,
            agency TEXT,
            due_date TEXT,
            url TEXT
        )
    ''')
    conn.commit()
    return conn

def fetch_sam_contracts():
    """Fetch and filter contract opportunities from SAM.gov API."""
    api_key = os.getenv('SAM_API_KEY')
    if not api_key:
        raise ValueError("SAM API key not found in environment variables")

    # Get date range for the last 24 hours
    end_date = datetime.now()
    start_date = end_date - timedelta(days=1)
    
    headers = {
        'X-Api-Key': api_key,
        'Content-Type': 'application/json'
    }

    url = "https://api.sam.gov/opportunities/v2/search"
    params = {
        'api_version': 'v2',
        'postedFrom': start_date.strftime('%Y-%m-%d'),
        'postedTo': end_date.strftime('%Y-%m-%d'),
        'limit': 10,
        'sortBy': 'relevance',
        'setAsideType': ['SBA', 'SDVOSB', '8A', 'HUBZone', 'VOSB'],
        'active': 'true',
        'responseFormat': 'json'
    }
    
    logging.info('Searching for contracts between %s and %s', 
                 params['postedFrom'], params['postedTo'])

    try:
        logging.info('Fetching new contract opportunities from SAM.gov')
        response = requests.get(url, headers=headers, params=params)
        
        # Log response details for debugging
        logging.info('SAM.gov API Response Status: %d', response.status_code)
        logging.info('SAM.gov API Response Headers: %s', response.headers)
        
        response.raise_for_status()
        data = response.json()
        
        if 'opportunityData' in data:
            opportunities = data['opportunityData']
            logging.info('Found %d contract opportunities', len(opportunities))
            return opportunities
        else:
            logging.warning('No opportunities found in response: %s', data)
            return []
            
    except requests.exceptions.RequestException as e:
        logging.error('Error fetching contracts: %s', str(e))
        if hasattr(e.response, 'text'):
            logging.error('Response content: %s', e.response.text)
        return []
    except Exception as e:
        logging.error('Unexpected error fetching contracts: %s', str(e))
        return []

def rank_contracts(contracts):
    """Rank contracts based on value, deadline, and small business relevance."""
    valid_contracts = []
    
    for contract in contracts:
        # Skip contracts without required information
        if not all(k in contract for k in ['title', 'dueDate', 'value', 'agency']):
            continue
            
        # Convert contract value to float
        try:
            value = float(contract['value'])
        except (ValueError, TypeError):
            value = 0.0
            
        # Calculate days until deadline
        try:
            due_date = datetime.strptime(contract['dueDate'], '%Y-%m-%d')
            days_until_due = (due_date - datetime.now()).days
        except (ValueError, TypeError):
            days_until_due = float('inf')
            
        # Add ranking score
        contract['score'] = value / (days_until_due + 1)  # Avoid division by zero
        valid_contracts.append(contract)
    
    # Sort by score (descending)
    ranked_contracts = sorted(valid_contracts, key=lambda x: x['score'], reverse=True)
    return ranked_contracts[:5]  # Return top 5 contracts

def setup_twitter():
    """Initialize Twitter API client with error handling and verification."""
    try:
        auth = tweepy.OAuth1UserHandler(
            os.getenv('TWITTER_API_KEY'),
            os.getenv('TWITTER_API_SECRET'),
            os.getenv('TWITTER_ACCESS_TOKEN'),
            os.getenv('TWITTER_ACCESS_SECRET')
        )
        api = tweepy.API(auth)
        
        # Verify credentials
        api.verify_credentials()
        logging.info('✅ Twitter authentication successful!')
        return api
    except Exception as e:
        logging.error('❌ Twitter authentication failed: %s', str(e))
        raise

def format_tweet(contract):
    """Format contract details into an engaging tweet under 280 characters."""
    # Format contract value
    value = float(contract.get('value', 0))
    if value >= 1_000_000:
        value_str = f"${value/1_000_000:.1f}M"
    else:
        value_str = f"${value/1_000:.0f}K"

    # Format deadline
    due_date = datetime.strptime(contract['dueDate'], '%Y-%m-%d')
    days_until_due = (due_date - datetime.now()).days
    if days_until_due <= 7:
        deadline_str = f"⚠️ DUE SOON: {due_date.strftime('%b %d')}"
    else:
        deadline_str = f"Due: {due_date.strftime('%b %d')}"

    # Truncate title if needed
    title = contract['title']
    if len(title) > 100:
        title = title[:97] + '...'

    # Create tweet with emojis and hashtags
    tweet = (
        f"🚨 NEW FEDERAL CONTRACT\n\n"
        f"📋 {title}\n"
        f"💰 {value_str}\n"
        f"⏳ {deadline_str}\n"
        f"🏢 {contract['agency']}\n"
        f"🔗 {contract['url']}\n\n"
        f"#GovContracts #SmallBiz"
    )

    # Ensure tweet is within character limit
    if len(tweet) > 280:
        tweet = tweet[:277] + '...'

    return tweet

def post_contract_tweet(twitter_api, contract):
    """Post a contract opportunity to Twitter with retries."""
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            tweet_text = format_tweet(contract)
            logging.info('Attempting to post tweet: %s', tweet_text)
            twitter_api.update_status(tweet_text)
            logging.info('Successfully posted tweet')
            return True
        except Exception as e:
            retry_count += 1
            if retry_count < max_retries:
                logging.warning('Tweet attempt %d failed: %s. Retrying...', retry_count, str(e))
                time.sleep(5)  # Wait 5 seconds before retrying
            else:
                logging.error('Failed to post tweet after %d attempts: %s', max_retries, str(e))
                return False

def main():
    """Main function to fetch, rank, and post top contracts to Twitter."""
    conn = None
    try:
        conn = setup_database()
        twitter_api = setup_twitter()
        
        # Fetch and rank contracts
        logging.info('Fetching contracts from SAM.gov')
        contracts = fetch_sam_contracts()
        
        if not contracts:
            logging.warning('No contracts found')
            return
            
        logging.info('Ranking contracts')
        ranked_contracts = rank_contracts(contracts)
        
        if not ranked_contracts:
            logging.warning('No valid contracts after ranking')
            return
            
        logging.info('Found %d ranked contracts', len(ranked_contracts))
        
        # Process each ranked contract
        cursor = conn.cursor()
        for contract in ranked_contracts:
            try:
                # Check if contract already exists
                cursor.execute('SELECT id FROM contracts WHERE contract_id = ?', (contract['id'],))
                if cursor.fetchone() is not None:
                    logging.info('Contract %s already posted', contract['id'])
                    continue
                
                # Post tweet
                if post_contract_tweet(twitter_api, contract):
                    # Save contract to database
                    cursor.execute(
                        'INSERT INTO contracts (contract_id, title, posted_at, value, score) VALUES (?, ?, ?, ?, ?)',
                        (contract['id'], contract['title'], datetime.now().isoformat(), 
                         contract.get('value', 0), contract.get('score', 0))
                    )
                    conn.commit()
                    logging.info('Contract %s saved to database', contract['id'])
                    
                    # Wait between tweets to avoid rate limits
                    time.sleep(5)
            except Exception as e:
                logging.error('Error processing contract %s: %s', contract.get('id'), str(e))
                continue
                
        logging.info('Finished processing contracts')
        
    except Exception as e:
        logging.error('Error in main function: %s', str(e))
    finally:
        if conn:
            conn.close()






if __name__ == "__main__":
    main()
