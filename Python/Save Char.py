import psycopg2

def get_id(cur, table_name, id_name, value_name, value):
    query = 'SELECT {id_name} FROM {table_name} WHERE {value_name}=%(name)s'.format(id_name=id_name, table_name=table_name, value_name=value_name)
    cur.execute(query, {'name': value})
    row = cur.fetchone()
    if(row is None):
        return None
    return row[0];

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
    
    save_attributes(npc_id, strg, dex, con, intr, wis, chrm, cur)
    save_skills(npc_id, skills, cur)
    conn.commit()
    cur.close()
except (Exception, psycopg2.DatabaseError) as error:
    print ("Error: {error}".format(error=error))
finally:
    if conn is not None:
        conn.close()
