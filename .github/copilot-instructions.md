# D&D AI Project Instructions

## Project Overview
This is an AI-powered D&D world management system that integrates AWS cloud infrastructure with OpenAI's ChatGPT to create an intelligent campaign management toolkit. The system allows DMs and players to interact with NPCs, query world information, and manage campaigns through Discord Bot and FoundryVTT integrations.

## Core Objectives
- Process D&D source books, world documents, and NPC records into a searchable AI knowledge base
- Provide real-time AI interactions through Discord Bot and FoundryVTT
- Maintain persistent world state and character progression
- Enable easy content updates and knowledge base expansion
- Create reusable Terraform modules for community deployment

## System Architecture Components

### 1. Document Processing Pipeline
- **AWS Services**: S3, Lambda, SQS, EventBridge
- **Function**: Automatically process uploaded PDFs into OpenAI embeddings
- **Flow**: PDF Upload → S3 Event → Lambda Processor → OpenAI Embeddings → Vector DB

### 2. AI Knowledge Base & Query Engine
- **AWS Services**: OpenSearch, Lambda, API Gateway
- **Function**: Semantic search and RAG (Retrieval-Augmented Generation) pipeline
- **Features**: Vector search, context assembly, response generation, caching

### 3. Discord Bot
- **Technology**: Discord.py, AWS Lambda, API Gateway
- **Commands**:
  - `/ask [question]` - Query knowledge base
  - `/npc [name] [message]` - Interact with NPCs
  - `/roll [dice]` - Enhanced dice rolling
  - `/character [action]` - Character management
- **Features**: NPC personality persistence, player authentication, campaign management

### 4. FoundryVTT Module
- **Technology**: JavaScript ES6, FoundryVTT API
- **Features**: AI assistant panel, NPC dialog system, world state sync

### 5. API Gateway & Orchestration
- **AWS Services**: API Gateway, Lambda, Cognito
- **Function**: Unified interface, authentication, rate limiting, request routing

### 6. Database Layer
- **AWS Services**: DynamoDB, RDS (PostgreSQL)
- **Data**: Character data, NPC records, world state, campaign data, user management

### 7. Infrastructure Management
- **Technology**: Terraform, GitHub Actions
- **Features**: Modular design, environment management, secrets management, monitoring

## Lambda Functions and Layers

### Language
- Python 3.11 on AWS Lambda (Go support can be added later). Each function is designed to be callable from API Gateway and usable as an MCP tool.

### Repository Layout
- Functions: `src/lambda-functions/<function_name>/app.py` exposing `handler(event, context)`
- Function-local Python deps for layers: `src/lambda-functions/<function_name>/layer/requirements.txt`
- Legacy shared layers (optional): `package/layers/<layer_name>/requirements.txt`
- Build output: `dist/lambdas/*.zip`, `dist/layers/*.zip`

### Build Scripts (PowerShell)
- Build a function zip:
  - `scripts/build_lambda.ps1 -FunctionName <name>`
- Build a Python layer zip (site-packages under `python/`):
  - Colocated requirements: `scripts/build_layer.ps1 -FunctionName <name> [-Python python]`
  - Shared layer: `scripts/build_layer.ps1 -LayerName <layer_name> [-Python python]`
  - Custom path: `scripts/build_layer.ps1 -RequirementsPath <path-to-requirements.txt> [-Python python]`

### Attach Layers
- Terraform should publish `dist/layers/<layer>.zip` as `aws_lambda_layer_version` and attach to functions via `layers` attribute.

### Environment Variables Convention
- DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, DB_SCHEMAS (optional)
- OPENAI_API_KEY, AWS_REGION, ENVIRONMENT as applicable

### Function: db_schema_introspect
- Purpose: Return JSON describing all tables in configured PostgreSQL RDS, including columns and comments. Useful for MCP schema discovery.
- Input: HTTP event, env vars as above
- Output example:
  - `{ "ok": true, "engine": "postgres", "schemas": ["public"], "tables": [ { "schema": "public", "name": "npcs", "comment": "...", "columns": [ { "name": "id", "data_type": "uuid", "is_nullable": false, "default": "gen_random_uuid()", "comment": null } ] } ] }`
- Errors: `{ "ok": false, "error": "<Class>: <message>" }` (HTTP 500)

### Local Testing
- Set env vars and run module directly: `python src/lambda-functions/db_schema_introspect/app.py`
- Or create a quick test event via console/API Gateway.

### Terraform Integration
 DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_SCHEMAS (optional)
 DB_PASSWORD is optional; preferred pattern is IAM DB authentication (Lambda generates a short‑lived token via AWS SDK)
 OPENAI_API_KEY, AWS_REGION, ENVIRONMENT as applicable
- Expose via API Gateway with: API key required, Basic Auth (custom Lambda authorizer), usage plan, and stage.
- Store API key and Basic Auth credentials in AWS Secrets Manager. Terraform should read and wire them (without storing values in state).
 Point `aws_lambda_function.filename` to `dist/lambdas/<function>.zip`.
 Create/publish layer from `dist/layers/<layer>.zip` and attach ARNs to functions.
- Include `layer/requirements.txt` next to the function. Build layer with `scripts/build_layer.ps1 -FunctionName <name>`.
- Build function zip with `scripts/build_lambda.ps1 -FunctionName <name>`.
- Use the reusable Terraform module `terraform/modules/lambda-api` to configure REST API, authorizer, API key, and throttling.
- Configure secrets as:
  - API key secret: `{ "api_key": "<key>" }`
 Builds a Python dependencies Layer (pip install -r requirements.txt into python/ and zips to dist/layers/<function>-python-deps.zip)
 Publishes the Layer (aws_lambda_layer_version) with content hashing so changes are detected
 Rebuilds the Lambda zips on source changes using existing PowerShell scripts (scripts/build_lambda.ps1)
 Wraps the `lambda-api` module to attach the layer, API Gateway, authorizer, API key/plan, VPC, and optional IAM DB auth
  - Basic auth secret: `{ "username": "<user>", "password": "<pass>" }`

 repo_root: abspath to repo root (e.g., ${abspath(path.root)}/../../../)
 requirements_path: path to layer requirements.txt
 function_trigger_files / authorizer_trigger_files: source file(s) to watch; change triggers rebuild
 build_function_name / build_authorizer_function_name: names passed to scripts/build_lambda.ps1
 name_prefix, region, function_name, lambda_zip, handler, runtime, timeout, memory_size
 environment: map of env vars
 vpc_subnet_ids, vpc_security_group_ids
 api_path, http_method, stage_name, api_key_value, throttle_* limits
 authorizer_zip, authorizer_handler, secret_id_basic_auth
 allow_rds_iam_auth, rds_dbuser_arns (for rds-db:connect)
### API Gateway and Auth Guidelines (for each Lambda)
- REST API with a resource and `ANY` or specific method (e.g., `POST`).
- API key required; create Usage Plan and API Key, link to stage. The key payload should be sourced from Secrets Manager at apply-time.
- Basic Auth via a Lambda Request Authorizer: compares `Authorization: Basic <base64>` header to credentials retrieved from Secrets Manager.
- CORS as needed for clients.
- Enforce throttling via Usage Plan.

### Secrets Management
- Store API Key under a Secrets Manager secret as JSON, e.g. `{ "api_key": "<key>" }`.
- Store Basic Auth credentials under another secret as JSON, e.g. `{ "username": "<user>", "password": "<pass>" }`.
- Terraform should look up these secrets at apply-time (data sources) and wire values without persisting secrets in state.

## Database Schema Design

### Design Principles
- **World-building focus**: Excludes D&D mechanics/stats, focuses on narrative elements
- **AI integration ready**: Fields for ChatGPT personality and interaction data
- **Flexible relationships**: JSONB fields for complex data structures
- **Search optimized**: Full-text search indexes for names and descriptions
- **Player knowledge tracking**: Separate DM notes from player-discovered information

### Current Tables

#### 1. NPCs (`npcs.sql`)
- **Focus**: Personality, roleplay, social connections
- **Key Fields**: 
  - Basic identity (name, race, age_category, gender)
  - Personality (summary, speech_pattern, mannerisms, motivations)
  - Social connections (occupation, reputation, relationships)
  - AI data (conversation_style, personality_prompt, interaction_history)
  - Location and organization ties
- **AI Integration**: Custom prompts for roleplay, conversation history logging

#### 2. Settlements (`settlements.sql`)
- **Focus**: Cities, towns, villages with world-building detail
- **Key Fields**:
  - Classification (type, size, population)
  - Geography (region, terrain, climate, landmarks)
  - Government (type, leader, laws)
  - Economy (industries, wealth level, trade)
  - Culture (races, languages, religions, customs)
  - Adventure hooks (current events, problems, opportunities)

#### 3. Nations (`nations.sql`)
- **Focus**: Political entities, kingdoms, empires
- **Key Fields**:
  - Government structure and leadership
  - Geography and resources
  - Demographics and culture
  - Military and economy
  - International relations and conflicts
  - History and current events

#### 4. Organizations (`organizations.sql`)
- **Focus**: Guilds, factions, religious orders, secret societies
 Any change to the requirements.txt triggers a pip rebuild, new Layer publish, and Lambda update.
 Any change to listed source files triggers a zip rebuild and Lambda update.
- **Key Fields**:
  - Structure and leadership
 Input: HTTP event, env vars as above (with IAM DB token generation; DB_PASSWORD not required)
  - Membership requirements and benefits
  - Geographic presence
  - Relationships with other groups
  - Adventure opportunities

#### 5. Businesses (`businesses.sql`)
- **Focus**: Individual establishments and government offices
- **Key Fields**:
  - Business operations and services
  - Ownership and management
  - Location and premises
  - Economic information
  - Social aspects and atmosphere
  - Adventure relevance

#### 6. World Entities (`world_entities.sql`)
- **Focus**: Landmarks, artifacts, events, legends, prophecies
- **Key Fields**:
  - Classification and significance
  - Physical and temporal aspects
  - Historical and cultural context
  - Special properties and rules
  - Knowledge accessibility
  - Adventure potential

## Project Structure
```
dnd_ai/
├── README.md                     # Main project documentation
├── PROJECT_INSTRUCTIONS.md       # This file
├── Database/                     # Database schema files
│   ├── npcs.sql
│   ├── settlements.sql
│   ├── nations.sql
│   ├── organizations.sql
│   ├── businesses.sql
│   └── world_entities.sql
├── terraform/                    # Infrastructure as Code
│   ├── modules/                  # Reusable Terraform modules
│   │   ├── document-processing/
│   │   ├── ai-engine/
│   │   ├── discord-bot/
│   │   ├── api-gateway/
│   │   ├── database/
│   │   └── monitoring/
│   ├── environments/             # Environment-specific configs
│   │   ├── dev/
│   │   ├── staging/
│   │   └── production/
│   └── examples/                 # Example configurations
├── src/                          # Application source code
│   ├── lambda-functions/         # AWS Lambda functions
│   ├── discord-bot/             # Discord bot implementation
│   ├── foundry-module/          # FoundryVTT module
│   └── shared/                  # Shared utilities
├── docs/                        # Additional documentation
├── tests/                       # Test files
└── scripts/                     # Deployment and utility scripts
```

## Current Development Status

### Completed
✅ System architecture design and documentation
✅ Complete database schema for world-building entities
✅ Project structure planning
✅ README.md with comprehensive system overview

### Next Steps (Prioritized)
1. **Terraform Infrastructure Modules**
   - Document processing pipeline (S3, Lambda, SQS)
   - AI query engine (OpenSearch, Lambda)
   - Database setup (RDS PostgreSQL)
   - API Gateway configuration

2. **Discord Bot Development**
   - Basic slash commands implementation
   - NPC interaction system
   - Knowledge base query integration

3. **FoundryVTT Module**
   - AI assistant panel UI
   - NPC dialog system integration
   - API communication layer

4. **Lambda Functions**
   - PDF processing and embedding generation
   - AI query and response handling
   - Discord webhook processing

## Key Design Decisions

### Database Design
- **PostgreSQL over DynamoDB** for primary data due to complex relationships
- **UUID primary keys** for better distributed system support
- **JSONB for flexible data** (relationships, interaction logs, configuration)
- **Separate player/DM knowledge** to maintain information asymmetry
- **Full-text search indexing** for natural language queries

### AI Integration Strategy
- **RAG (Retrieval-Augmented Generation)** approach for knowledge queries
- **Individual NPC personality prompts** for consistent roleplay
- **Interaction history logging** to maintain conversation context
- **Embedding-based semantic search** for relevant information retrieval

### Infrastructure Philosophy
- **Modular Terraform design** for reusability and community sharing
- **Event-driven architecture** for scalability and cost efficiency
- **Multi-environment support** (dev/staging/production)
- **Cost optimization** through auto-scaling and scheduled shutdowns

## Configuration Requirements

### Required Credentials
- **AWS Account** with appropriate IAM permissions
- **OpenAI API Key** for ChatGPT integration
- **Discord Bot Token** and application setup
- **Terraform** installed for infrastructure deployment

### Environment Variables
- `OPENAI_API_KEY`: OpenAI API access
- `DISCORD_TOKEN`: Discord bot authentication
- `AWS_REGION`: Deployment region
- `ENVIRONMENT`: dev/staging/production

## Integration Points

### Discord Bot Features
- Natural language queries to knowledge base
- NPC personality-driven conversations
- Campaign state management
- Player authentication and permissions

### FoundryVTT Module Features
- In-game AI assistant panel for DMs
- Click-to-talk NPC interactions
- Real-time world state synchronization
- Character sheet integration for rule lookups

### API Endpoints (Planned)
- `POST /api/v1/query` - Knowledge base queries
- `POST /api/v1/npc/interact` - NPC interactions
- `POST /api/v1/documents/upload` - Content updates
- `GET /api/v1/campaign/state` - World state retrieval

## Development Guidelines

### Code Organization
- Keep world-building data separate from game mechanics
- Design for modularity and reusability
- Include comprehensive documentation and examples
- Plan for community contribution and customization

### AI Prompt Engineering
- Create consistent personality prompts for NPCs
- Design context-aware query responses
- Implement conversation memory and continuity
- Balance helpfulness with maintaining mystery/discovery

### Performance Considerations
- Implement caching for frequently accessed data
- Optimize embedding searches for speed
- Design for horizontal scaling
- Monitor and manage API costs

## Community Sharing Strategy
- Publish Terraform modules on GitHub for reuse
- Provide example configurations and documentation
- Design for easy customization with personal credentials
- Include sample data and setup guides
- Support multiple campaign/world configurations

## Security Considerations
- Implement proper authentication and authorization
- Use AWS Secrets Manager for sensitive data
- Design rate limiting to prevent abuse
- Separate player-accessible and DM-only information
- Implement audit logging for sensitive operations

---

**Last Updated**: September 27, 2025
**Current Phase**: Database design completed, ready for infrastructure development
**Repository**: github.com/NemesisGhost/dnd_ai