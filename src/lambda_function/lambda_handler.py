import json
import boto3
import redis
import logging
from datetime import datetime

# Initialize logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Constants for SNS and Redis
SNS_TOPIC_ARN = 'arn:aws:sns:us-east-2:867344449800:FraudAlerts'
ELASTICACHE_REDIS_ENDPOINT = 'alex-fraud-jtv6hb.serverless.use2.cache.amazonaws.com'

# Initialize AWS services
dynamodb = boto3.resource('dynamodb')
transaction_table = dynamodb.Table('transaction_history')
flagged_table = dynamodb.Table('flagged_transactions')
sns = boto3.client('sns')
    
# Lazy Redis connection
redis_client = None

def get_redis_connection():
    global redis_client
    if not redis_client:
        redis_client = redis.StrictRedis(host=ELASTICACHE_REDIS_ENDPOINT, port=6379, db=0, decode_responses=True)
    return redis_client

def send_fraud_alert(transaction):
    """
    Publishes a fraud alert to SNS when a suspicious transaction is detected.
    """
    response = sns.publish(
        TopicArn=SNS_TOPIC_ARN,
        Message=json.dumps(transaction),
        Subject='Fraud Alert: Suspicious Transaction Detected'
    )
    logger.info(f"Fraud alert sent for transaction: {transaction['transaction_id']}")
    return response

def is_fraudulent(transaction):
    """
    Checks for suspicious transaction behavior. Flags if the amount is high or location is unusual.
    """
    amount_threshold = 10000  # Example threshold for high transaction amounts
    redis_client = get_redis_connection()

    # Check transaction amount threshold
    if transaction['amount'] > amount_threshold:
        logger.warning(f"Transaction flagged due to high amount: {transaction['amount']}")
        return True

    # Check location consistency
    recent_location = redis_client.get(f"user:{transaction['user_id']}:location")
    if recent_location and recent_location != transaction['location']:
        logger.warning(f"Transaction flagged due to location inconsistency: {transaction['location']} != {recent_location}")
        return True

    # Update Redis with the latest location (with a TTL of 1 hour)
    redis_client.set(f"user:{transaction['user_id']}:location", transaction['location'], ex=3600)
    return False

def lambda_handler(event, context):
    """
    Main handler for processing transaction data, detecting fraud, and handling notifications.
    """
    redis_client = get_redis_connection()  # Ensure Redis connection is available
    
    for record in event['Records']:
        try:
            # Parse transaction from Kafka record
            transaction = json.loads(record['value'])
            transaction['timestamp'] = datetime.utcnow().isoformat()  # Add processing timestamp
            
            # Log the incoming transaction
            logger.info(f"Processing transaction: {transaction}")

            # Perform fraud detection
            if is_fraudulent(transaction):
                # Log and store flagged transaction
                flagged_table.put_item(Item=transaction)
                logger.warning(f"Suspicious transaction detected and stored: {transaction}")
                
                # Send alert via SNS
                send_fraud_alert(transaction)

            # Store transaction in transaction history table
            transaction_table.put_item(Item=transaction)
        
        except Exception as e:
            # Log error if processing fails
            logger.error(f"Error processing transaction {record}. Error: {str(e)}")
    
    return {
        'statusCode': 200,
        'body': json.dumps('Processed transactions with fraud detection')
    }
