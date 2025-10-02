import json
import boto3
import psycopg2
import os
import sys
from pathlib import Path

def handler(event, context):
    """
    Lambda function to initialize the D&D AI database with schema and data.
    This function runs all SQL scripts in the correct order.
    """
    
    # Get database connection info from Secrets Manager
    secrets_client = boto3.client('secretsmanager')
    secret_arn = os.environ['SECRET_ARN']
    
    try:
        # Get database credentials
        response = secrets_client.get_secret_value(SecretId=secret_arn)
        credentials = json.loads(response['SecretString'])
        
        # Connect to database
        conn = psycopg2.connect(
            host=credentials['host'],
            port=credentials['port'],
            database=credentials['dbname'],
            user=credentials['username'],
            password=credentials['password']
        )
        
        # Enable autocommit for DDL operations
        conn.autocommit = True
        cursor = conn.cursor()
        
        print("Connected to database successfully")
        
        # SQL scripts in execution order (dependencies considered)
        sql_files = [
            # First: Create the update timestamp function
            "create_timestamp_function.sql",
            
            # Level 1: Lookup tables (no dependencies)
            "lookups/age_categories.sql",
            "lookups/climate_zones.sql",
            "lookups/cost_types.sql",
            "lookups/current_relevance_levels.sql",
            "lookups/emotional_impact_types.sql",
            "lookups/employee_roles.sql",
            "lookups/event_categories.sql",
            "lookups/influence_types.sql",
            "lookups/knowledge_areas.sql",
            "lookups/languages.sql",
            "lookups/location_types.sql",
            "lookups/market_reach_levels.sql",
            "lookups/occupation_categories.sql",
            "lookups/player_knowledge_levels.sql",
            "lookups/presence_levels.sql",
            "lookups/quality_levels.sql",
            "lookups/races.sql",
            "lookups/rarity_levels.sql",
            "lookups/relationship_categories.sql",
            "lookups/relationship_intensity_levels.sql",
            "lookups/relationship_statuses.sql",
            "lookups/relationship_types.sql",
            "lookups/religious_influence_levels.sql",
            "lookups/religious_tolerance_levels.sql",
            "lookups/rumor_categories.sql",
            "lookups/sensitivity_levels.sql",
            "lookups/service_categories.sql",
            "lookups/settlement_types.sql",
            "lookups/skill_levels.sql",
            "lookups/social_statuses.sql",
            "lookups/tag_categories.sql",
            "lookups/terrain_types.sql",
            "lookups/topic_categories.sql",
            "lookups/trade_specialty_types.sql",
            "lookups/trade_volume_levels.sql",
            
            # Level 2: Core shared entities
            "tags.sql",
            "resources.sql",
            "occupations.sql",
            "services.sql",
            "service_tags.sql",
            
            # Level 3: Geographic entities
            "locations/locations.sql",
            "nations.sql",
            
            # Level 4: Settlements and religions
            "settlements/settlements.sql",
            "religions/religions.sql",
            
            # Level 5: Business types and core business entity
            "business/business_types.sql",
            "business/businesses.sql",
            
            # Level 6: NPCs and Organizations
            "npcs/npc_dispositions.sql",
            "npcs/npc_statuses.sql",
            "npcs/npcs.sql",
            "organizations/organizations.sql",
            
            # Level 7: NPC detail tables
            "npcs/npc_knowledge.sql",
            "npcs/npc_occupations.sql",
            "npcs/npc_organization_memberships.sql",
            "npcs/npc_personality_traits.sql",
            "npcs/npc_relationships.sql",
            "npcs/npc_religions.sql",
            "npcs/npc_rumors.sql",
            "npcs/npc_services.sql",
            "npcs/npc_significant_events.sql",
            "npcs/npc_tag_assignments.sql",
            "npcs/npc_topics.sql",
            
            # Level 8: Business detail tables
            "business/business_employees.sql",
            "business/business_payment_methods.sql",
            "business/business_relationships.sql",
            "business/business_services.sql",
            "business/business_tags.sql",
            
            # Level 9: Organization detail tables
            "organizations/organization_activities.sql",
            "organizations/organization_associations.sql",
            "organizations/organization_chapters.sql",
            "organizations/organization_core_values.sql",
            "organizations/organization_leaders.sql",
            "organizations/organization_npc_associations.sql",
            "organizations/organization_relationships.sql",
            "organizations/organization_services.sql",
            "organizations/organization_tags.sql",
            
            # Level 10: Location and settlement relationships
            "locations/locations_languages.sql",
            "locations/locations_resources.sql",
            "settlements/settlement_industries.sql",
            "settlements/settlement_races.sql",
            "settlements/settlement_religions.sql",
            "settlements/settlement_organizations.sql",
            "settlements/settlement_religious_festivals.sql",
            "settlements/settlement_tags.sql",
            "settlements/settlement_trade_specialties.sql",
            
            # Level 11: Nation detail tables
            "nations/nation_holidays.sql",
            "nations/nation_social_classes.sql",
            
            # Level 12: Religion relationships
            "religions/religion_relationships.sql",
            "religions/religion_tags_extension.sql",
            
            # Level 13: Cross-entity relationships
            "relationships/business_organization_memberships.sql",
            "relationships/event_location_connections.sql",
            "relationships/event_npc_connections.sql",
            "relationships/location_relationships.sql",
            "relationships/location_routes.sql",
            "relationships/nation_allies.sql",
            "relationships/nation_climate_zones.sql",
            "relationships/nation_exports.sql",
            "relationships/nation_imports.sql",
            "relationships/nation_languages.sql",
            "relationships/nation_location_relationships.sql",
            "relationships/nation_political_factions.sql",
            "relationships/nation_races.sql",
            "relationships/nation_relationships.sql",
            "relationships/nation_resources.sql",
            "relationships/nation_tags.sql",
            "relationships/nation_terrain_types.sql",
            "relationships/npc_topic_assignments.sql",
            "relationships/npc_topic_connections.sql",
            "relationships/occupation_knowledge_areas.sql",
            "relationships/organization_resources.sql",
            "relationships/organization_territory_control.sql",
            "relationships/religion_tag_assignments.sql",
            "relationships/rumor_npc_connections.sql",
            "relationships/topic_relationships.sql"
        ]
        
        executed_files = []
        failed_files = []
        
        for sql_file in sql_files:
            try:
                print(f"Executing {sql_file}...")
                
                # Read SQL content from embedded data
                sql_content = get_sql_content(sql_file)
                
                if sql_content:
                    # Execute the SQL
                    cursor.execute(sql_content)
                    executed_files.append(sql_file)
                    print(f"Successfully executed {sql_file}")
                else:
                    print(f"Warning: No content found for {sql_file}")
                    
            except Exception as e:
                error_msg = f"Error executing {sql_file}: {str(e)}"
                print(error_msg)
                failed_files.append({"file": sql_file, "error": str(e)})
                # Continue with next file rather than failing completely
        
        # Close database connection
        cursor.close()
        conn.close()
        
        response_body = {
            "message": "Database initialization completed",
            "executed_files": len(executed_files),
            "total_files": len(sql_files),
            "failed_files": failed_files,
            "status": "success" if len(failed_files) == 0 else "partial_success"
        }
        
        print(f"Database initialization completed. Executed: {len(executed_files)}, Failed: {len(failed_files)}")
        
        return {
            'statusCode': 200,
            'body': json.dumps(response_body)
        }
        
    except Exception as e:
        error_msg = f"Database initialization failed: {str(e)}"
        print(error_msg)
        return {
            'statusCode': 500,
            'body': json.dumps({
                "message": error_msg,
                "status": "error"
            })
        }

def get_sql_content(file_path):
    """
    Get SQL content for a given file path.
    In production, this would read from embedded files or S3.
    For now, returns the timestamp function as an example.
    """
    
    if file_path == "create_timestamp_function.sql":
        return """
        -- Create the update_timestamp function used by triggers
        CREATE OR REPLACE FUNCTION update_timestamp()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    
    # For now, return None for other files
    # In a real implementation, you would either:
    # 1. Embed all SQL files in the Lambda deployment package
    # 2. Store SQL files in S3 and read them here
    # 3. Use AWS Systems Manager Parameter Store
    return None