import json
import os
#import requests

from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

SECRETS_HEADERS = {"X-Aws-Parameters-Secrets-Token": os.environ.get('AWS_SESSION_TOKEN')}
SECRETS_PORT = os.environ.get('PARAMETERS_SECRETS_EXTENSION_HTTP_PORT')

def lambda_handler(event, context):
  try:
    body = json.loads(event['body'])
        
    signature = event['headers']['x-signature-ed25519']
    timestamp = event['headers']['x-signature-timestamp']
    bot_key = get_secret('discord_bot_token')

    # validate the interaction
    verify_key = VerifyKey(bytes.fromhex(bot_key))

    message = timestamp + json.dumps(body, separators=(',', ':'))
    
    try:
      verify_key.verify(message.encode(), signature=bytes.fromhex(signature))
    except BadSignatureError:
      return {
        'statusCode': 401,
        'body': json.dumps('invalid request signature')
      }
    
    # handle the interaction

    t = body['type']

    if t == 1:
      return {
        'statusCode': 200,
        'body': json.dumps({
          'type': 1
        })
      }
    elif t == 2:
      return command_handler(body)
    else:
      return {
        'statusCode': 400,
        'body': json.dumps('unhandled request type')
      }
  except:
    raise

def command_handler(body):
  command = body['data']['name']

  if command == 'bleb':
    return {
      'statusCode': 200,
      'body': json.dumps({
        'type': 4,
        'data': {
          'content': 'Hello, World.',
        }
      })
    }
  else:
    return {
      'statusCode': 400,
      'body': json.dumps('unhandled command')
    }

def get_secret(secret_id):
  secrets_extension_endpoint = "http://localhost:" + SECRETS_PORT + "/secretsmanager/get?secretId=" + secret_id
  
  r = requests.get(secrets_extension_endpoint, headers=SECRETS_HEADERS)
  
  return json.loads(r.text)["SecretString"] # load the Secrets Manager response into a Python dictionary, access the secret