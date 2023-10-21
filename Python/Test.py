import json

token_totals = {'prompt': 0, 'response': 0}
print(token_totals)
usage = json.loads('{"completion_tokens": 17,"prompt_tokens": 57,"total_tokens": 74}')

token_totals['prompt'] += usage['prompt_tokens']
token_totals['response'] += usage['completion_tokens']

print(token_totals)