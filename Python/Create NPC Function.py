import openai
import json

openai.api_key = ""
directions = [
    {"role": "system", "content": "You are describing a city for a Dungeon and Dragons campaign."},
]
context = [
    {"role": "assistant", "content": "Stormreach is the primary port of a penal continent named Gaol. Stormreach is the home of the hunter guilds.  They supply most the magical components and items for the entire world and Stormreach is the port they ship their good out from."},
    {"role": "assistant", "content": "Gaol is known for its magical storms that make most of it unsuitable for long term settlements and are believed to be the reason magical creatures are larger & more prolific there.  Gaol is surrounded by a massive wall designed primarily to contain the magical storms, but also those sent there.  Due to the magical creatures on Gaol most of those sent to Gaol are forced to work as monster hunters."},
]

def call_function(funcName, funcArgs):
    available_functions = {
        "create_npc": create_npc,
        }
    if not funcName in available_functions:
        return
    fuction_to_call = available_functions[funcName]
    
    return {
                "role": "function",
                "name": funcName,
                "content": fuction_to_call(funcArgs),
            }

def create_npc(details):
    npc_directions = [
        {"role": "system", "content": "You are creating a character for a Dungeon and Dragons campaign."},
        {"role": "system", "content": "Only use official Dungeon and Dragon 5th edition character classes, subclasses, races, skills, and abilities.  Do not use homebrew classes.  Merchant is not a class."},
        {"role": "system", "content": """Output the following JSON object ONLY:
{
  "title": "NPC Format",
  "type": "object",
  "properties": {
    "name": { "type": "string", "description" : "Name of the character" },
    "race": { "type": "string", "description" : "D&D 5th edition character race" },
    "class": { "type": "string", "description" : "D&D 5th edition character class" },
    "level": { "type": "number", "description" : "character level" },
    "backstory": { "type": "string", "description" :  "a brief story of how they arrived in Gaol & at Stormreach"},
    "personality": { "type": "string", "description" : "how the character acts & behaves" },
    "description": { "type": "string", "description" : "how the players should preceive the character" },
    "speech_pattern": { "type": "string", "description" : "how the character speaks" },
    "Strength": { "type": "number" },
    "Dexterity": { "type": "number" },
    "Constitution": { "type": "number" },
    "Intelligence": { "type": "number" },
    "Wisdom": { "type": "number" },
    "Charisma": { "type": "number" },
    }
  },
  "required": [
    "name",
    "race",
    "class",
    "level",
    "backstory",
    "personality",
    "description",
    "speech_pattern",
    "Strength",
    "Dexterity",
    "Constitution",
    "Intelligence",
    "Wisdom",
    "Charisma"
  ]
}"""},
    ]
    prompts = [{"role" : "user", "content":"Create an NPC using the following details:{prompt}".format(prompt=details)}]
    for p in npc_directions:
        prompts.append(p)
    for p in context:
        prompts.append(p)
    chat_completion = openai.ChatCompletion.create(
        model="gpt-3.5-turbo-0613",
        messages=prompts)
    print(chat_completion['choices'][0]['message']['content'])
    print(chat_completion)
    return ""
call_function("create_npc", "{\"name\": \"Bob Ironstrike\",\"shopname\": \"Bob\'s General Goods\",\"shoptype\": \"General Store\",\"level\":\"10\"}")