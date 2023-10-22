import psycopg2, json

def get_id(cur, table_name, id_name, value_name, value):
    query = 'SELECT {id_name} FROM {table_name} WHERE {value_name}=%(name)s'.format(id_name=id_name, table_name=table_name, value_name=value_name)
    cur.execute(query, {'name': value})
    row = cur.fetchone()
    if(row is None):
        return None
    return row[0];

INSERT_NPC = 'INSERT INTO npc(name, race_id, class_id, level, background, personality, description, speech_pattern) VALUES(%(name)s, %(race_id)s, %(class_id)s, %(level)s, %(background)s, %(personality)s, %(description)s, %(speech_pattern)s) RETURNING npc_id;'
attributes = [(1, "Strength"), (2, "Dexterity"), (3, "Constitution"), (4, "Intelligence"), (5, "Wisdom"), (6, "Charisma")]


npc = json.loads("{\n  \"name\": \"Gideon Ironstrike\",\n  \"race\": \"Dwarf\",\n  \"class\": \"Fighter\",\n  \"level\": 10,\n  \"backstory\": \"Gideon Ironstrike is a skilled fighter hailing from the city of Hammerfast. He learned the art of combat from his father, who was also a renowned warrior. Gideon's passion for adventure led him to leave his hometown and seek his fortune in the bustling city of Stormreach.\",\n  \"personality\": \"Gideon is a stoic and disciplined individual. He carries himself with an air of confidence and is always focused on his goals. He values honor and loyalty above all else and is willing to go to great lengths to protect his friends and loved ones.\",\n  \"description\": \"Gideon is a middle-aged dwarf with a sturdy build and a thick, braided beard. He wears a suit of intricately crafted iron armor, adorned with engravings of ancient dwarven symbols. His weathered face bears the signs of countless battles, but his eyes shine with determination and resilience.\",\n  \"speech_pattern\": \"Gideon speaks with a deep, baritone voice, his words punctuated by the occasional dwarven expletive. He has a no-nonsense attitude and tends to be direct and to the point in his conversations.\",\n  \"Strength\": 16,\n  \"Dexterity\": 14,\n  \"Constitution\": 18,\n  \"Intelligence\": 10,\n  \"Wisdom\": 12,\n  \"Charisma\": 10\n}")

try:
    conn = psycopg2.connect(
        host="localhost",
        database="postgres",
        user="postgres",
        password="Mag1cL3g0")

    cur = conn.cursor()
    
    class_id = get_id(cur, 'class', 'class_id', 'name', npc['class'])
    
    if(class_id is None):
        #return "NPC Class Not Found"
        print("NPC Class Not Found")
        exit()
    
    race_id = get_id(cur, 'race', 'race_id', 'name', npc['race'])
    if(race_id is None):
        print("NPC Race Not Found")
        exit()
       
    cur.execute(INSERT_NPC, {'name': npc['name'], 'race_id': race_id, 'class_id': class_id, 'level': npc['level'], 'background': npc['backstory'],
                             'personality': npc['personality'], 'description': npc['description'], 'speech_pattern': npc['speech_pattern']})
    row = cur.fetchone()
    if(row is None):
        print("NPC not INSERT\'d")
        exit()
    npc_id = row[0]
    for attribute in attributes:
        cur.execute("INSERT INTO npc_attribute(npc_id, attribute_id, value) VALUES(%(npc_id)s, %(attribute_id)s, %(value)s)",
                    {'npc_id':npc_id, 'attribute_id':attribute[0], 'value':npc[attribute[1]]})
    
    conn.commit()
    cur.close()        
except (Exception, psycopg2.DatabaseError) as error:
    print(error)
finally:
    if conn is not None:
        conn.close()
