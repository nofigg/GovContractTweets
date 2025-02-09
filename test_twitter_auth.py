import tweepy
import os
from dotenv import load_dotenv
import logging

# Set up logging
logging.basicConfig(
    filename='logs/contract_tweets.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Load environment variables
load_dotenv()

def test_twitter_auth():
    try:
        auth = tweepy.OAuth1UserHandler(
            os.getenv("TWITTER_API_KEY"), 
            os.getenv("TWITTER_API_SECRET"), 
            os.getenv("TWITTER_ACCESS_TOKEN"), 
            os.getenv("TWITTER_ACCESS_SECRET")
        )
        twitter_api = tweepy.API(auth)
        twitter_api.verify_credentials()
        logging.info("✅ Twitter authentication successful!")
        print("✅ Twitter authentication successful!")
        return True
    except Exception as e:
        logging.error("❌ Authentication failed: %s", str(e))
        print("❌ Authentication failed:", str(e))
        return False

if __name__ == "__main__":
    test_twitter_auth()
