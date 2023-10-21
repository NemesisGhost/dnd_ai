import psycopg2, json, openai

openai.api_key = "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"
openai_model = "gpt-3.5-turbo-0613"
token_totals = {'prompt': 0, 'response': 0}

def call_chat_completion(prompts, functions):
    chat_completion = openai.ChatCompletion.create(
            model=openai_model,
            functions=functions,
            messages=prompts)
    token_totals['prompt'] += chat_completion['usage']['prompt_tokens']
    token_totals['response'] += chat_completion['usage']['completion_tokens']
    print(chat_completion)
    print(token_totals)
    if((token_totals['prompt']+token_totals['response']) > 10000):
        exit(1)
    return chat_completion

def call_function(funcName, funcArgs):
    available_functions = {
        "create_npc": create_npc,
        }
    if not funcName in available_functions:
        return None
    fuction_to_call = available_functions[funcName]  
    return {
                "role": "function",
                "name": funcName,
                "content": fuction_to_call(funcArgs),
            }

def call_chat_function(func_name, prompts, functions):
    chat_done = False
    while(not(chat_done)):
        chat_completion = call_chat_completion(prompts, functions)
        chat_done = (chat_completion['choices'][0]['finish_reason'] == 'function_call') and (chat_completion['choices'][0]['message']['function_call']['name'] == func_name)
    return chat_completion['choices'][0]['message']['function_call']['arguments']

def get_id(cur, table_name, id_name, value_name, value):
    query = 'SELECT {id_name} FROM {table_name} WHERE {value_name}=%(name)s'.format(id_name=id_name, table_name=table_name, value_name=value_name)
    cur.execute(query, {'name': value})
    row = cur.fetchone()
    if(row is None):
        return None
    return row[0];

def generate_skills(npc_id, directions, details, cur):
    prompts = [{"role":"user", "content": "Provide the skills for the described character to the save_skills function"}]
    for p in directions:
        prompts.append(p)
    for p in details:
        prompts.append(p)
    functions=[
            {
                "name" : "save_skills",
                "description" : "Saves the character's skills to a database",
                "parameters" : {
                    "type" : "object",
                    "properties" : {
                        "skills" : {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties":{
                                    "name":{
                                        "type" : "string",
                                        "description":"Name of the skill"
                                    }
                                }
                            },
                            "description": "A list of skills the character is proficient in."
                        },
                    },
                    "required": ["skills"],
                },
            }
        ]
    skills = json.loads(call_chat_function("save_skills", prompts, functions))
    for skill in skills['skills']:
        skill_id = get_id(cur, 'skill', 'skill_id', 'name', skill['name'])
        if(skill_id is None):
            print("NPC Skill({skill}) Not Found".format(skill=skill['name']))
        else:
            cur.execute("INSERT INTO npc_skill(npc_id, skill_id) VALUES(%(npc_id)s, %(skill_id)s, %(proficiency_bonus)s)",
                        {'npc_id':npc_id,'skill_id':skill_id})

def generate_characterizations(npc_id, directions, details, cur):
    characterizations = [
        {'id':1, 'name':'flaw',  'description':'A character’s flaw represents some vice, compulsion, fear, or weakness that can be exploited.'},
        {'id':2, 'name':'ideal', 'description':'Ideals are the things that a character believes in most strongly, the fundamental moral and ethical principles that compel them to act as they do.'},
        {'id':3, 'name':'bond',  'description':'Bonds represent a character’s connections to people, places, and events in the world'}]
    for c in characterizations:
        prompts = [
            {"role":"user", "content": "Provide the {char}s for the described character to the save_{char}s function".format(char=c['name'])},
            {"role":"system", "content": "Use the provided functions to complete the task"},
            {"role":"user", "content": c['description']}]
        for p in directions:
            prompts.append(p)
        for p in details:
            prompts.append(p)
        functions=[
            {
                "name" : "save_{char}s".format(char=c['name']),
                "description" : "Saves the character's {char}s to a database".format(char=c['name']),
                "parameters" : {
                    "type" : "object",
                    "properties" : {
                        "characterizations" : {
                            "type": "array",
                            "items": {
                                "type": "string"
                            },
                            "description": "A list of {char}s for the character.".format(char=c['name'])
                        },
                    },
                    "required": ["characterizations"],
                },
            }
        ]
        chars = json.loads(call_chat_function("save_{char}s".format(char=c['name']), prompts, functions))
        for char in chars['characterizations']:
            cur.execute("INSERT INTO npc_characterization(npc_id, characterization_type_id, description) VALUES(%(npc_id)s, %(characterization_type_id)s, %(description)s)",
                {'npc_id':npc_id, 'characterization_type_id':c['id'], 'description':char})
    
def generate_attributes(npc_id, directions, details, cur):
    functions=[
        {
            "name" : "save_attributes",
            "description" : "Saves the character's attributes to a database",
            "parameters" : {
                "type" : "object",
                    "properties" : {
                        "strength" : {
                            "type" : "number"},
                        "dexterity" : {
                            "type" : "number"},
                        "constitution" : {
                            "type" : "number"},
                        "intelligence" : {
                            "type" : "number"},
                        "wisdom" : {
                            "type" : "number"},
                        "charisma" : {
                            "type" : "number"},
                    },
                "required": ["name", "class", "race", "background", "personality", "description", "speech_pattern"],
            },
        }
    ]
    prompts = [{"role":"user", "content": "Provide the attributes for the described character to the save_attributes function"}]
    char_attributes = [(1, "strength"), (2, "dexterity"), (3, "constitution"), (4, "intelligence"), (5, "wisdom"), (6, "charisma")]
    for p in directions:
        prompts.append(p)
    for p in details:
        prompts.append(p)
    attributes = json.loads(call_chat_function("save_attributes", prompts, functions))
    for attribute in char_attributes:
        cur.execute("INSERT INTO npc_attribute(npc_id, attribute_id, value) VALUES(%(npc_id)s, %(attribute_id)s, %(value)s)",
            {'npc_id':npc_id, 'attribute_id':attribute[0], 'value':attributes[attribute[1]]})

def create_npc(details):
    npc = json.loads(details)
    npc_directions = [
        {"role": "system", "content": "You are creating a character for a Dungeon and Dragons campaign."},
    ]
    npc_details = [
        {"role": "assistant", "content": "Name: {name}".format(name=npc['name'])},
        {"role": "assistant", "content": "Class: {char_class}".format(char_class=npc['class'])},
        {"role": "assistant", "content": "Level: {level}".format(level=npc['level'])},
        {"role": "assistant", "content": "Race: {race}".format(race=npc['race'])},
        {"role": "assistant", "content": "Background: {background}".format(background=npc['background'])},
        {"role": "assistant", "content": "Personality: {personality}".format(personality=npc['personality'])},
        {"role": "assistant", "content": "Description: {description}".format(description=npc['description'])},
    ]
    INSERT_NPC = 'INSERT INTO npc(name, race_id, class_id, level, background, personality, description, speech_pattern) VALUES(%(name)s, %(race_id)s, %(class_id)s, %(level)s, %(background)s, %(personality)s, %(description)s, %(speech_pattern)s) RETURNING npc_id;'
    try:
        conn = psycopg2.connect(
            host="localhost",
            database="postgres",
            user="postgres",
            password="Mag1cL3g0")

        cur = conn.cursor()
        
        class_id = get_id(cur, 'class', 'class_id', 'name', npc['class'])  
        if(class_id is None):
            return "{not_class} is not a Class".format(not_class=npc['class'])
        
        race_id = get_id(cur, 'race', 'race_id', 'name', npc['race'])
        if(race_id is None):
            return "{not_race} is not a Race".format(not_class=npc['race'])
        
        cur.execute(INSERT_NPC, {'name': npc['name'], 'race_id': race_id, 'class_id': class_id, 'level': npc['level'], 'background': npc['background'],
                                 'personality': npc['personality'], 'description': npc['description'], 'speech_pattern': npc['speech_pattern']})
        row = cur.fetchone()
        if(row is None):
            return "NPC not INSERTed"
        npc_id = row[0]
        
        generate_attributes(npc_id, npc_directions, npc_details, cur)
        generate_characterizations(npc_id, npc_directions, npc_details, cur)
        generate_skills(npc_id, npc_directions, npc_details, cur)
        
        conn.commit()
        cur.close()
        npc_info = {
            "name" : npc['name'],
            "race" : npc['race'],
            "class" : npc['class'],
            "description" : npc['description'],
            "npc_id" : npc_id
        }
        return json.dumps(npc_info)
    except (Exception, psycopg2.DatabaseError) as error:
        print ("Error: {error}".format(error=error))
        return "Error: {error}".format(error=error)
    finally:
        if conn is not None:
            conn.close()

system_prompts = [
    {"role": "system", "content": "You are describing a city for a Dungeon and Dragons campaign."},
    {"role": "system", "content": "Businesses created must have a character created who is the owner and details that include any employees created as characters, a description the building they are in, a detailed list of what goods they have for sale that includes the cost & quantity available, and a detailed list of services offered with their cost & befefits to the players(s)."},
    {"role": "system", "content": "Only use official Dungeon and Dragon 5th edition character classes, subclasses, races, skills, and abilities.  Do not use homebrew classes.  Merchant is not a class."},
]

assistant_prompts = [
    {"role": "assistant", "content": "Stormreach is the primary port of a penal continent named Gaol. Stormreach is the home of the hunter guilds.  They supply most the magical components and items for the entire world and Stormreach is the port they ship their good out from."},
    {"role": "assistant", "content": "Gaol is known for its magical storms that make most of it unsuitable for long term settlements and are believed to be the reason magical creatures are larger & more prolific there.  Gaol is surrounded by a massive wall designed primarily to contain the magical storms, but also those sent there.  Due to the magical creatures on Gaol most of those sent to Gaol are forced to work as monster hunters."},
]

user_prompts = [
            {"role": "user", "content": "I need general goods store for a level 8 party."}
]

functions=[
    {
        "name" : "create_npc",
        "description" : "creates a D&D character from the provided race, class, background, personality, description, and speech pattern",
        "parameters" : {
            "type" : "object",
            "properties" : {
                "name" : {
                    "type" : "string",
                    "description" : "Name of the NPC"},
                "class" : {
                    "type" : "string",
                    "description" : "D&D 5e Class of the NPC"},
                "level" : {
                    "type" : "number",
                    "description" : "Level of the NPC"},
                "race" : {
                    "type" : "string",
                    "description" : "D&D 5e Race of the NPC"},
                "background" : {
                    "type" : "string",
                    "description" : "a brief story of how they arrived in Gaol & at Stormreach"},
                "personality": { "type": "string", "description" : "how the character acts & behaves" },
                "description": { "type": "string", "description" : "how the players should preceive the character" },
                "speech_pattern": { "type": "string", "description" : "how the character speaks" },
            },
            "required": ["name", "class", "level", "race", "background", "personality", "description", "speech_pattern"],
        },
    },
    {
        "name" : "create_shop",
        "description" : "creates a shop in a city for a D&D campaign from the provided details",
        "parameters" : {
            "type" : "object",
            "properties" : {
                "name" : {
                    "type" : "string",
                    "description" : "Name of the shop"
                },
                "description" : {
                    "type" : "string",
                    "description" : "Description of the shop, including the building and overall atmosphere"
                },
                "owner_id" : {
                    "type" : "number",
                    "description" : "NPC ID of the owner"
                },
                "employees" : {
                    "type": "array",
                    "items": {
                        "type": "number"
                    },
                    "description": "A list of NPC IDs for the employees"
                },
            },
            "required": ["name", "description", "owner_id", "employees"],
        }
    }
]

prompts = []
for p in system_prompts:
    prompts.append(p)
for p in assistant_prompts:
    prompts.append(p)
for p in user_prompts:
    prompts.append(p)

done = False
while(not(done)):
    chat_completion = call_chat_completion(prompts, functions)
    done = not(chat_completion['choices'][0]['finish_reason'] == 'function_call') or (chat_completion['choices'][0]['message']['function_call']['name'] == 'create_shop')
    if(not(done)):
        prompts.append(call_function(chat_completion['choices'][0]['message']['function_call']['name'], chat_completion['choices'][0]['message']['function_call']['arguments']))
        
print(chat_completion)

