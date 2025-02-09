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
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/contract_tweets.log'),
        logging.StreamHandler()
    ]
)

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
        'limit': 100,  # Maximum allowed per page
        'offset': 0,
        'sortBy': 'relevance',
        'setAsideType': ['SBA', 'SDVOSB', '8A', 'HUBZone', 'VOSB', 'WOSB'],
        'active': 'true',
        'responseFormat': 'json',
        'status': 'active',
        'type': ['o', 'p', 'k'],  # Opportunity, Presolicitation, Combined
        'excludeFields': ['description', 'award']  # Reduce response size
    }
    
    logging.info('Searching for contracts between %s and %s', 
                 posted_from, posted_to)

    try:
        all_opportunities = []
        total_fetched = 0
        max_results = 1000  # Set a reasonable limit
        
        while total_fetched < max_results:
            logging.info('Fetching page %d of contract opportunities from SAM.gov', (total_fetched // 100) + 1)
            params['offset'] = total_fetched
            
            response = requests.get(url, headers=headers, params=params)
            
            # Log response details for debugging
            logging.info('SAM.gov API Response Status: %d', response.status_code)
            
            if response.status_code != 200:
                logging.error('SAM.gov API Error Response: %s', response.text)
                break
                
            try:
                data = response.json()
                if 'opportunitiesData' not in data:
                    break
                    
                opportunities = data['opportunitiesData']
                if not opportunities:
                    break
                    
                # Log raw opportunity data for debugging
                logging.debug('Raw opportunities data: %s', opportunities)
                
                # Filter for relevant opportunities
                filtered_opportunities = []
                for opp in opportunities:
                    logging.debug('Processing opportunity: %s', opp)
                    
                    if opp.get('active') == 'Yes' and \
                       opp.get('type') not in ['Award Notice'] and \
                       any(setaside in ['SBA', 'SDVOSB', '8A', 'HUBZone', 'VOSB', 'WOSB']
                           for setaside in ([opp.get('typeOfSetAside')] if opp.get('typeOfSetAside') else [])):
                        filtered_opportunities.append(opp)
                        logging.debug('Added opportunity to filtered list: %s', opp.get('title'))
                
                all_opportunities.extend(filtered_opportunities)
                total_fetched += len(opportunities)
                
                logging.info('Fetched %d opportunities, %d relevant (total: %d, relevant: %d)', 
                             len(opportunities), len(filtered_opportunities), 
                             total_fetched, len(all_opportunities))
                
                # If we got less than the limit, we've reached the end
                if len(opportunities) < params['limit']:
                    break
                    
                # Rate limiting
                time.sleep(1)
                
            except ValueError as e:
                logging.error('Error parsing SAM.gov API response: %s', str(e))
                break
        
        logging.info('Found %d total contract opportunities', total_fetched)
        logging.info('Found %d relevant small business opportunities', len(all_opportunities))
        return all_opportunities
            
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
    now = datetime.now(timezone.utc)
    
    for contract in contracts:
        try:
            # Track missing fields for debugging
            missing_fields = []
            
            # Get contract value (try multiple sources)
            value = None
            if contract.get('award') and contract['award'].get('amount'):
                value = float(contract['award']['amount'])
                logging.debug(f"Using award.amount: ${value:,.2f}")
            elif contract.get('fundingCeiling'):
                value = float(contract['fundingCeiling'])
                logging.debug(f"Using fundingCeiling: ${value:,.2f}")
            elif contract.get('estimatedTotalContractValue'):
                value = float(contract['estimatedTotalContractValue'])
                logging.debug(f"Using estimatedTotalContractValue: ${value:,.2f}")
            else:
                missing_fields.append('contract_value')
                logging.debug("No contract value found in any field")
            
            # Parse response deadline
            deadline_str = contract.get('responseDeadLine')
            deadline = None
            days_until_due = None
            if deadline_str:
                try:
                    deadline = datetime.fromisoformat(deadline_str)
                    if deadline.tzinfo is None:
                        deadline = deadline.replace(tzinfo=timezone.utc)
                    else:
                        deadline = deadline.astimezone(timezone.utc)
                    days_until_due = (deadline - now).days
                except ValueError:
                    logging.warning(f"Could not parse deadline: {deadline_str}")

            # Skip if deadline has passed
            if days_until_due is not None and days_until_due < 0:
                continue
            
            # Value score (0-50 points) - Now weighted more heavily
            value_score = 0
            if value:
                value_score = min(50, value / 100000)  # 0.5 point per $100k up to 50 points
            
            # Urgency score (0-30 points) - Still important but less weight
            urgency_score = 0
            if days_until_due is not None:
                urgency_score = 30 * (1 - (days_until_due / 30))  # Linear scale over 30 days
                urgency_score = max(0, min(30, urgency_score))
            
            # Set-aside score (0-20 points) - Adjusted weights
            set_aside = contract.get('typeOfSetAside', '')
            set_aside_score = {
                'SDVOSB': 20,  # Service Disabled Veteran Owned
                'WOSB': 20,   # Women Owned
                '8A': 15,     # 8(a) Program
                'HUBZone': 15,# HUBZone
                'VOSB': 15,   # Veteran Owned
                'SBA': 10     # Small Business
            }.get(set_aside, 0)
            
            final_score = value_score + urgency_score + set_aside_score
            
            # Generate a unique ID from title and date if no ID exists
            contract_id = contract.get('id') or contract.get('noticeId') or f"{contract['title']}_{deadline.strftime('%Y%m%d')}"
            
            # Format deadline for display
            deadline_display = 'Pending'
            if deadline:
                deadline_display = deadline.strftime('%B %d, %Y, %I:%M %p %Z')
            
            # Format value for display
            value_display = 'Pending Award Estimate'
            if value:
                value_display = '${:,.2f}'.format(value)
            
            # Get set-aside description
            set_aside_desc = contract.get('typeOfSetAsideDescription') or contract.get('typeOfSetAside', 'Open Competition')
            if set_aside_desc == '':
                set_aside_desc = 'Open Competition'
                missing_fields.append('set_aside')
            
            # Get agency name
            agency_path = contract.get('fullParentPathName', '').split('.')
            agency = agency_path[-1] if agency_path else 'Federal Government'
            if not agency_path:
                missing_fields.append('agency')
                
            # Get NAICS code
            naics_code = contract.get('naicsCode', 'Not Specified')
            if not naics_code:
                missing_fields.append('naics_code')
                
            # Get place of performance
            pop = contract.get('placeOfPerformance', {})
            location = 'Multiple Locations'
            if pop:
                state = pop.get('state', '')
                city = pop.get('city', '')
                if city and state:
                    location = f"{city}, {state}"
                elif state:
                    location = state
            else:
                missing_fields.append('place_of_performance')
            
            # Log any missing fields
            if missing_fields:
                logging.warning(f"Missing fields for contract {contract.get('noticeId', 'Unknown')}: {', '.join(missing_fields)}")

            valid_contracts.append({
                'id': contract.get('noticeId', f"{contract['title']}_{int(time.time())}"),
                'title': contract['title'],
                'deadline': deadline_display,
                'agency': agency,
                'url': contract.get('uiLink', ''),
                'set_aside': set_aside_desc,
                'value': value_display,
                'naics': naics_code,
                'location': location,
                'score': final_score,
                'value_raw': value or 0,  # Store raw value for sorting
                'missing_fields': missing_fields
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
    """Main function to fetch and rank contracts (without posting to Twitter)."""
    try:
        # Fetch and rank contracts
        logging.info('Fetching contracts from SAM.gov')
        contracts = fetch_sam_contracts()
        
        if not contracts:
            logging.warning('No contracts found')
            return
        
        # Rank contracts
        logging.info('Ranking contracts')
        ranked_contracts = rank_contracts(contracts)
        
        if not ranked_contracts:
            logging.warning('No contracts met ranking criteria')
            return
            
        logging.info('Found %d ranked contracts', len(ranked_contracts))
        
        # Display top 5 contracts
        logging.info('Top 5 Contracts:')
        for i, contract in enumerate(ranked_contracts[:5], 1):
            # Extract agency from fullParentPathName or department
            agency_path = contract.get('fullParentPathName', '').split('/')
            agency = agency_path[-1] if agency_path else contract.get('department', 'N/A')
            
            # Format response date
            response_date = contract.get('responseDate')
            if response_date:
                try:
                    date_obj = datetime.strptime(response_date, '%Y-%m-%dT%H:%M:%S.%f%z')
                    formatted_date = date_obj.strftime('%Y-%m-%d %H:%M %Z')
                except ValueError:
                    formatted_date = response_date
            else:
                formatted_date = 'N/A'
            
            # Format contract value
            value = contract.get('estimatedTotalContractValue')
            if value:
                try:
                    value_float = float(value)
                    formatted_value = '${:,.2f}'.format(value_float)
                except ValueError:
                    formatted_value = f'${value}'
            else:
                formatted_value = 'N/A'
            
            # Get set-aside description or type
            set_aside = contract.get('typeOfSetAsideDescription') or contract.get('typeOfSetAside', 'None')
            
            # Get contract value
            value = contract.get('estimatedTotalContractValue')
            if not value and contract.get('award'):
                value = contract['award'].get('amount')
            if value:
                try:
                    value_float = float(value)
                    formatted_value = '${:,.2f}'.format(value_float)
                except ValueError:
                    formatted_value = f'${value}'
            else:
                formatted_value = 'N/A'
            
            # Format response date
            response_date = contract.get('responseDeadLine')
            if response_date:
                try:
                    date_obj = datetime.strptime(response_date, '%Y-%m-%dT%H:%M:%S%z')
                    formatted_date = date_obj.strftime('%Y-%m-%d %H:%M %Z')
                except ValueError:
                    formatted_date = response_date
            else:
                formatted_date = 'N/A'
            
            # Get agency name
            agency_path = contract.get('fullParentPathName', '').split('.')
            agency = agency_path[-1] if agency_path else contract.get('department', 'N/A')
            
            # Get notice ID
            notice_id = contract.get('noticeId', 'N/A')
            
            logging.info('\n%d. %s', i, contract['title'])
            logging.info('   💰 Contract Value: %s', contract['value'])
            logging.info('   📅 Response Due: %s', contract['deadline'])
            logging.info('   🏢 Agency: %s', contract['agency'])
            logging.info('   🎯 Set-Aside: %s', contract['set_aside'])
            logging.info('   📊 Score: %.2f', contract['score'])
            logging.info('   🔗 URL: %s', contract['url'])
            
    except Exception as e:
        logging.error('Error in main function: %s', str(e))
    finally:
        logging.info('Finished processing contracts')






if __name__ == "__main__":
    main()
