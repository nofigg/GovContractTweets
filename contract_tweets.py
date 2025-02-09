import os
import sqlite3
import requests
import tweepy
import time
from datetime import datetime, timedelta
from datetime import timezone, tzinfo
import pytz
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

    # Get date range for the last 24 hours in UTC
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=1)
    
    # Format dates as MM/dd/yyyy for SAM.gov API
    posted_from = start_date.strftime('%m/%d/%Y')
    posted_to = end_date.strftime('%m/%d/%Y')
    
    headers = {
        'X-Api-Key': api_key,
        'Content-Type': 'application/json'
    }

    url = "https://api.sam.gov/opportunities/v2/search"
    params = {
        'api_version': 'v2',
        'postedFrom': posted_from,
        'postedTo': posted_to,
        'limit': 10,
        'sortBy': 'relevance',
        'setAsideType': ['SBA', 'SDVOSB', '8A', 'HUBZone', 'VOSB'],
        'active': 'true',
        'responseFormat': 'json'
    }
    
    logging.info('Searching for contracts between %s and %s', 
                 posted_from, posted_to)

    try:
        logging.info('Fetching new contract opportunities from SAM.gov')
        response = requests.get(url, headers=headers, params=params)
        
        # Log response details for debugging
        logging.info('SAM.gov API Response Status: %d', response.status_code)
        logging.info('SAM.gov API Response Headers: %s', response.headers)
        
        if response.status_code != 200:
            logging.error('SAM.gov API Error Response: %s', response.text)
            return []
            
        try:
            data = response.json()
            logging.debug('SAM.gov API Response Data: %s', data)
        except ValueError as e:
            logging.error('Error parsing SAM.gov API response: %s', str(e))
            return []
        
        if 'opportunitiesData' in data:
            opportunities = data['opportunitiesData']
            logging.info('Found %d total contract opportunities', len(opportunities))
            
            # Filter for relevant opportunities
            filtered_opportunities = [
                opp for opp in opportunities
                if opp['active'] == 'Yes' and
                opp['type'] not in ['Award Notice'] and  # Exclude already awarded contracts
                any(setaside in ['SBA', 'SDVOSB', '8A', 'HUBZone', 'VOSB', 'WOSB']
                    for setaside in ([opp.get('typeOfSetAside')] if opp.get('typeOfSetAside') else []))
            ]
            
            logging.info('Found %d relevant small business opportunities', len(filtered_opportunities))
            return filtered_opportunities
        else:
            logging.warning('No opportunities found in response')
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
    """Rank contracts based on response deadline and small business relevance."""
    valid_contracts = []
    now = datetime.now(timezone.utc)
    
    for contract in contracts:
        try:
            # Parse response deadline
            deadline_str = contract.get('responseDeadLine')
            if not deadline_str:
                continue
                
            # Convert deadline to datetime (format: 2025-02-17T13:00:00-07:00)
            deadline = datetime.fromisoformat(deadline_str)
            # Convert to UTC for comparison
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            else:
                deadline = deadline.astimezone(timezone.utc)
                
            days_until_due = (deadline - now).days
            
            # Skip if deadline has passed
            if days_until_due < 0:
                continue
            
            # Calculate base score (prioritize urgency)
            base_score = 100 / (days_until_due + 1)  # Add 1 to avoid division by zero
            
            # Bonus points for specific set-asides
            set_aside = contract.get('typeOfSetAside', '')
            set_aside_bonus = {
                'SDVOSB': 50,  # Service Disabled Veteran Owned
                'WOSB': 40,   # Women Owned
                '8A': 30,     # 8(a) Program
                'HUBZone': 20,# HUBZone
                'VOSB': 20,   # Veteran Owned
                'SBA': 10     # Small Business
            }.get(set_aside, 0)
            
            final_score = base_score + set_aside_bonus
            
            # Generate a unique ID from title and date if no ID exists
            contract_id = contract.get('id') or contract.get('noticeId') or f"{contract['title']}_{deadline.strftime('%Y%m%d')}"
            
            valid_contracts.append({
                'id': contract_id,
                'title': contract['title'],
                'deadline': deadline.strftime('%Y-%m-%d %H:%M %Z'),
                'agency': contract['fullParentPathName'].split('.')[-1],  # Take last part of path
                'url': contract['uiLink'],
                'set_aside': contract.get('typeOfSetAsideDescription', 'Small Business'),
                'score': final_score
            })
            
        except (ValueError, KeyError) as e:
            logging.warning('Error processing contract %s: %s', 
                          contract.get('title', 'Unknown'), str(e))
            logging.debug('Contract data: %s', contract)
            continue
    
    if not valid_contracts:
        logging.warning('No valid contracts to rank')
        return []
    
    # Sort by score (descending)
    ranked_contracts = sorted(valid_contracts, key=lambda x: x['score'], reverse=True)
    logging.info('Ranked %d contracts, returning top 5', len(ranked_contracts))
    return ranked_contracts[:5]  # Return top 5 contracts

def setup_twitter():
    """Initialize Twitter API v2 client with error handling and verification."""
    try:
        client = tweepy.Client(
            consumer_key=os.getenv('TWITTER_API_KEY'),
            consumer_secret=os.getenv('TWITTER_API_SECRET'),
            access_token=os.getenv('TWITTER_ACCESS_TOKEN'),
            access_token_secret=os.getenv('TWITTER_ACCESS_SECRET')
        )
        
        # Test the client by getting the authenticated user
        client.get_me()
        logging.info('✅ Twitter authentication successful!')
        return client
    except Exception as e:
        logging.error('❌ Twitter authentication failed: %s', str(e))
        raise

def format_tweet(contract):
    """Format contract details into an engaging tweet under 280 characters."""
    # Get hashtags based on set-aside type
    set_aside_hashtags = {
        'SDVOSB': '#SDVOSB #VeteranOwned',
        'WOSB': '#WOSB #WomenOwned',
        '8A': '#8a #SmallBusiness',
        'HUBZone': '#HUBZone #SmallBusiness',
        'VOSB': '#VOSB #VeteranOwned',
        'SBA': '#SmallBusiness'
    }

    # Get set-aside type from description
    set_aside = contract.get('set_aside', '')
    hashtags = set_aside_hashtags.get(
        next((k for k in set_aside_hashtags.keys() if k in set_aside.upper()), 'SBA')
    )
    
    tweet = (
        f"🚨 NEW FEDERAL CONTRACT\n\n"
        f"📋 {contract['title']}\n"
        f"⏳ Due: {contract['deadline']}\n"
        f"🏢 {contract['agency']}\n"
        f"💼 {contract['set_aside']}\n"
        f"🔗 Details: {contract['url']}\n\n"
        f"#GovContracts {hashtags}"
    )
    
    # Ensure tweet is under 280 characters
    if len(tweet) > 280:
        # Truncate title if needed
        title = contract['title']
        if len(title) > 50:
            title = title[:47] + "..."
            
        tweet = (
            f"🚨 FEDERAL CONTRACT\n"
            f"📋 {title}\n"
            f"⏳ {contract['deadline']}\n"
            f"🏢 {contract['agency']}\n"
            f"🔗 {contract['url']}\n"
            f"#GovContracts {hashtags}"
        )
    
    return tweet

def post_contract_tweet(twitter_client, contract):
    """Post a contract opportunity to Twitter with retries."""
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            tweet_text = format_tweet(contract)
            logging.info('Attempting to post tweet: %s', tweet_text)
            response = twitter_client.create_tweet(text=tweet_text)
            
            if response.data:
                logging.info('Successfully posted tweet with ID: %s', response.data['id'])
                return True
            else:
                raise Exception('No tweet data in response')
                
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
        twitter_client = setup_twitter()
        
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
                # Validate required fields
                required_fields = ['id', 'title', 'agency', 'url', 'deadline', 'set_aside']
                missing_fields = [field for field in required_fields if not contract.get(field)]
                
                if missing_fields:
                    logging.error(f"Contract missing required fields: {', '.join(missing_fields)}")
                    logging.debug(f"Contract data: {contract}")
                    continue
                
                # Check if contract already exists
                cursor.execute('SELECT id FROM contracts WHERE contract_id = ?', (contract['id'],))
                if cursor.fetchone() is not None:
                    logging.info('Contract %s already posted', contract['id'])
                    continue
                
                # Post tweet
                if post_contract_tweet(twitter_client, contract):
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
