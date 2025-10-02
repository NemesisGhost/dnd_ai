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
- **Key Fields**:
  - Structure and leadership
  - Purpose and activities
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