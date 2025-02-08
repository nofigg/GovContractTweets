import pytest
import requests
from contract_tweets import fetch_contracts, format_tweet, is_duplicate

# Test API connectivity
@pytest.mark.parametrize('url', [
    'https://api.sam.gov/contract-opportunities',
])
def test_api_connectivity(url):
    response = requests.get(url)
    assert response.status_code == 200

# Test duplicate prevention logic
@pytest.mark.parametrize('existing_contracts, new_contract', [
    (['Contract A', 'Contract B'], 'Contract C'),
    (['Contract A', 'Contract B'], 'Contract A'),
])
def test_is_duplicate(existing_contracts, new_contract):
    if new_contract in existing_contracts:
        assert is_duplicate(existing_contracts, new_contract) == True
    else:
        assert is_duplicate(existing_contracts, new_contract) == False

# Test tweet formatting constraints
@pytest.mark.parametrize('contract_title, expected_tweet', [
    ('New Contract Opportunity', '🚨 NEW CONTRACT ALERT: New Contract Opportunity'),
    ('Another Contract', '🚨 NEW CONTRACT ALERT: Another Contract'),
])
def test_format_tweet(contract_title, expected_tweet):
    tweet = format_tweet(contract_title)
    assert tweet == expected_tweet
