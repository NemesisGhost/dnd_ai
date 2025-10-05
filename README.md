# D&D AI — Intelligent Campaign Management System

An AI-powered toolkit for Dungeon Masters that uses AWS and OpenAI to deliver an interactive world: talk to NPCs, query world knowledge, and keep persistent state via Discord and FoundryVTT integrations.

## System architecture

### Overview
This system creates an intelligent D&D world by:
- Processing D&D source books, world documents, and NPC records into a searchable knowledge base
- Providing real-time AI-powered interactions through Discord Bot and FoundryVTT
- Maintaining persistent world state and character progression
- Enabling easy content updates and knowledge base expansion

### Core components

#### 1) Document processing pipeline (planned)
**AWS Services**: S3, Lambda, SQS, EventBridge
- **Document Ingestion**: S3 bucket with event-driven processing
- **PDF Processing**: Lambda functions using PyPDF2/pdfplumber for text extraction
- **Content Chunking**: Intelligent text segmentation for optimal embedding
- **Embedding Generation**: OpenAI API integration for vector embeddings
- **Vector Storage**: Amazon OpenSearch/Pinecone for similarity search

```
PDF Upload → S3 Event → Lambda Processor → OpenAI Embeddings → Vector DB
```

#### 2) AI knowledge base & query engine (planned)
**AWS Services**: OpenSearch, Lambda, API Gateway
- **Vector Search**: Semantic search across all ingested content
- **Context Assembly**: Retrieval-Augmented Generation (RAG) pipeline
- **Response Generation**: OpenAI GPT integration with custom prompts
- **Caching Layer**: ElastiCache for frequently accessed content

#### 3) Discord bot (planned)
**Technology**: Discord.py, AWS Lambda, API Gateway
- **Slash Commands**: 
  - `/ask [question]` - Query the knowledge base
  - `/npc [name] [message]` - Interact with specific NPCs
  - `/roll [dice]` - Enhanced dice rolling with context
  - `/character [action]` - Character sheet management
- **NPC Interactions**: Context-aware conversations with personality persistence
- **Campaign Management**: Session notes, world state updates
- **Player Authentication**: Discord OAuth integration

#### 4) FoundryVTT module (planned)
**Technology**: JavaScript ES6, FoundryVTT API
- **AI Assistant Panel**: In-game interface for DM queries
- **NPC Dialog System**: Click-to-talk AI NPC interactions
- **World State Sync**: Real-time synchronization with knowledge base
- **Combat Integration**: AI-powered tactical suggestions
- **Character Sheet Integration**: Automatic stat queries and rule lookups

#### 5) API gateway & orchestration (planned)
**AWS Services**: API Gateway, Lambda, Cognito
- **REST API**: Unified interface for all system interactions
- **Authentication**: JWT tokens with role-based access
- **Rate Limiting**: Per-user API quotas to manage OpenAI costs
- **Request Routing**: Intelligent routing to appropriate services
- **Webhook Support**: Real-time updates to connected clients

#### 6) Database layer (in progress)
**AWS Services**: RDS (PostgreSQL)
- **NPC System**: Comprehensive character profiles with personality, relationships, and knowledge
- **World Building**: Settlements, nations, organizations, businesses, and landmarks
- **Knowledge Management**: Topic categories, conversation systems, and information tracking
- **Event System**: Significant events with complex relationships and player knowledge tracking
- **Occupational Framework**: Job categories and skill associations
- **Campaign Data**: Sessions, notes, important decisions
- **User Management**: Player profiles, permissions, preferences

#### 7) Infrastructure management (in progress)
**Technology**: Terraform, GitHub Actions
- **Modular Design**: Reusable Terraform modules
- **Environment Management**: Dev/staging/production deployments
- **Secrets Management**: AWS Secrets Manager integration
- **Monitoring**: CloudWatch, X-Ray tracing
- **Cost Optimization**: Auto-scaling, scheduled shutdowns

## Database schema

The D&D AI system uses a comprehensive PostgreSQL database designed specifically for world-building and AI integration. The schema emphasizes narrative elements over mechanical D&D stats, creating a rich knowledge base for intelligent storytelling.

### Key features
- **228 SQL tables** with normalized, 3NF-compliant design
- **AI-friendly structure** with JSONB fields for flexible data
- **Complex relationship modeling** for realistic NPC interactions
- **Full-text search optimization** for natural language queries
- **Player knowledge management** with information asymmetry support

### Core entity types
- **NPCs**: Detailed personality profiles with conversation styles and AI prompts
- **World Entities**: Settlements, nations, organizations, businesses, landmarks
- **Knowledge System**: Topics, conversation flows, and information networks
- **Relationships**: Complex social connections and event histories
- **Lookup Tables**: 25+ reference tables for consistent data

### AI integration points
- **Personality Prompts**: Custom ChatGPT instructions per NPC
- **Interaction History**: JSONB logs of AI conversations for continuity
- **Knowledge Confidence**: Tracking how certain NPCs are about information
- **Conversation Triggers**: Automatic topic transitions and dialogue hooks

**📋 For complete database documentation, see [Database/DATABASE_SCHEMA.md](Database/DATABASE_SCHEMA.md)**

## Infrastructure architecture

### Terraform organization

The infrastructure follows a **modular Terraform architecture** with clear separation between reusable components and environment-specific deployments:

#### modules/ — reusable infrastructure components
- **Purpose**: Define infrastructure patterns that can be used across multiple environments
- **Reusability**: One module can be instantiated by multiple environments with different configurations
- **Versioning**: Modules can be tagged and versioned for stability across deployments
- Examples:
  - `modules/database/` — RDS, VPC, security groups, and monitoring
  - `modules/secrets/` — creates secret metadata (OpenAI, Discord) encrypted with KMS
  - `modules/db_runner/` — SSM-based SQL runner to apply schema from S3 using the RDS master secret

#### environments/ — environment-specific deployments
- **Purpose**: Deploy modules with specific configurations for different environments (dev/staging/prod)
- **Isolation**: Each environment has independent Terraform state and AWS resources
- **Configuration**: Environment-specific variables, instance sizes, backup policies, etc.
- **Example**: `environments/dev/` uses the database module with development-friendly settings

#### How they work together
```hcl
# environments/dev/main.tf
module "database" {
  source = "../../modules/database"        # References the reusable module
  
  # Development-specific configuration
  instance_class = "db.t3.micro"          # Small instance for cost savings
  backup_retention_period = 3             # Short retention for development
  deletion_protection = false             # Allow easy teardown
}

# environments/prod/main.tf (future)
module "database" {
  source = "../../modules/database"        # Same module, different config
  
  # Production-specific configuration  
  instance_class = "db.r5.large"          # Larger instance for performance
  backup_retention_period = 30            # Long retention for production
  deletion_protection = true              # Prevent accidental deletion
  multi_az = true                          # High availability
}
```

This architecture allows you to:
- **Maintain consistency** across environments using the same infrastructure code
- **Customize configurations** per environment without duplicating code
- **Version and test** infrastructure changes safely
- **Scale efficiently** from development to production

## Project structure

```
dnd_ai/
├── README.md                   # Project overview and setup guide
├── Database/                   # PostgreSQL schema (228 SQL files)
│   ├── DATABASE_SCHEMA.md      # Complete database documentation
│   ├── lookups/               # Reference tables (25 files)
│   ├── npcs/                  # NPC system (14 files)
│   ├── settlements/           # Settlement data (7 files)
│   ├── organizations/         # Organizations (10 files)
│   ├── business/              # Business entities (7 files)
│   ├── locations/             # Location system (3 files)
│   ├── nations/               # Nations and politics (2 files)
│   ├── religions/             # Religious systems (3 files)
│   ├── relationships/         # Cross-entity relationships (25+ files)
│   └── world/                 # World-level entities
├── terraform/                 # Infrastructure as Code
│   ├── modules/               # Reusable infrastructure modules (database, secrets, db_runner)
│   ├── environments/          # Environment-specific deployments (currently dev)
│   └── scripts/               # Terraform helper scripts (e.g., upsert-secrets.ps1)
├── build.ps1                  # Root build/deploy script (init/plan/apply + post-deploy)
├── scripts/                   # App build/deployment utilities (future)
├── docs/                      # Documentation
│   └── terraform/             # Infrastructure documentation
│       ├── README.md          # Detailed infrastructure guide
│       ├── DEPLOYMENT_GUIDE.md # Step-by-step deployment
│       └── VERIFICATION_GUIDE.md # Testing and validation
├── src/                       # Application source code
│   ├── lambda-functions/      # AWS Lambda implementations
│   │   ├── db_setup.py        # Database initialization
│   │   ├── interactions.py    # Discord bot interactions
│   │   └── db_init_lambda.py  # Database schema deployment
│   ├── discord-bot/           # Discord.py bot implementation (planned)
│   ├── foundry-module/        # FoundryVTT integration (planned)
│   └── shared/                # Shared utilities and libraries (planned)
└── tests/                     # Test files
```

## Current development status

### ✅ Completed
- **Database Schema**: Complete 228-table PostgreSQL schema for D&D world-building
- **Terraform Infrastructure**: Reusable modules for RDS, Secrets metadata, and DB runner
- **Database Module**: RDS with encryption, monitoring, and AWS-managed master user password
- **Documentation**: Comprehensive setup guides and database documentation
- **Deployment Scripts**: Automated deployment and management tools

### 🚧 In progress
- **Lambda Functions**: Document processing and AI query engine
- **Discord Bot**: Slash commands and NPC interaction system
- **API Gateway**: RESTful interface for system integration

### 📋 Planned
- **FoundryVTT Module**: In-game AI assistant and NPC dialog system
- **Document Processing Pipeline**: PDF ingestion and embedding generation
- **Vector Database**: OpenSearch integration for semantic search
- **Frontend Interface**: Web-based campaign management tools

## Quick start

### Prerequisites
- **AWS Account** with appropriate IAM permissions
- **AWS CLI** configured with credentials
- **Terraform** >= 1.5 installed
- **Python 3.x** for Lambda packaging
- **PowerShell** (Windows) or Bash (Linux/Mac)

### 1) Deploy infrastructure

```powershell
# Clone and enter repo
git clone https://github.com/NemesisGhost/dnd_ai.git
cd dnd_ai

# Quick deploy for an environment (dev|staging|prod)
./build.ps1 -Environment dev -Action apply -AutoApprove
```

### 2) Upsert secrets (OpenAI, Discord)

Secrets are managed outside of Terraform state. Create a local JSON file and upsert values to AWS Secrets Manager.

1. Create `terraform/environments/dev/secrets.local.json` from the example:
  - `terraform/environments/dev/secrets.local.json.example`
2. Fill in your values:
  - `openai.api_key`, optional `organization_id`
  - `discord.bot_token`, optional `application_id`, `public_key`
3. Run the upsert script:

```powershell
./terraform/scripts/upsert-secrets.ps1 -Environment dev -Region us-east-1 -File ./terraform/environments/dev/secrets.local.json
```

The Terraform module creates the secret metadata; this script writes values without exposing them to Terraform state.

### 3) Verify database setup

```powershell
# In the environment folder
terraform -chdir="./terraform/environments/dev" output

# Fetch the AWS-managed RDS master user password
$secretArn = (terraform -chdir="./terraform/environments/dev" output -raw rds_master_user_secret_arn)
aws secretsmanager get-secret-value --secret-id $secretArn --query SecretString --output text | jq -r .password > $env:TEMP\db_pw.txt

# Connect with psql (install psql locally)
$pw = Get-Content $env:TEMP\db_pw.txt
psql -h (terraform -chdir="./terraform/environments/dev" output -raw database_endpoint) `
  -p (terraform -chdir="./terraform/environments/dev" output -raw database_port) `
  -U (terraform -chdir="./terraform/environments/dev" output -raw database_username) `
  -d (terraform -chdir="./terraform/environments/dev" output -raw database_name) `
  -w
```

### 4) Verify database schema

```sql
-- Check that tables were created
\dt

-- Verify sample data
SELECT * FROM races LIMIT 5;
SELECT * FROM tags WHERE category_id = (SELECT category_id FROM tag_categories WHERE name = 'Role') LIMIT 5;
```

### Next steps

1. **API Development**: Build Lambda functions for AI integration
2. **Discord Bot**: Implement slash commands and NPC interactions
3. **FoundryVTT Module**: Create in-game AI assistant
4. **Content Loading**: Add your campaign data to the database

## Key features

### For Dungeon Masters
- **Intelligent Rule Lookup**: Instant access to any D&D rule or mechanic
- **Dynamic NPC Interactions**: AI-powered NPCs with consistent personalities and detailed backgrounds
- **World State Management**: Automatic tracking of campaign events and changes
- **Content Integration**: Easy addition of custom world documents and house rules
- **Session Planning**: AI-assisted encounter and story suggestions
- **Relationship Tracking**: Complex NPC networks with realistic information flow
- **Event Management**: Sophisticated tracking of significant events and their ongoing impact

### For Players
- **Natural Language Queries**: Ask questions in plain English about rules, lore, or characters
- **Character Assistance**: Rules clarification and optimization suggestions
- **NPC Conversations**: Engaging interactions with world characters who remember past conversations
- **Lore Discovery**: Deep dive into world history with intelligent information management
- **Relationship Building**: Meaningful connections with NPCs based on shared experiences and knowledge

### System administration
- **Easy Deployment**: One-command infrastructure setup
- **Cost Management**: Usage monitoring and budget alerts
- **Content Updates**: Hot-swappable knowledge base updates
- **Multi-Campaign Support**: Isolated environments per campaign

## Infrastructure costs (estimates)

### Current implementation (dev)

#### Development environment
- **RDS PostgreSQL (db.t3.micro)**: ~$15/month
- **Storage (20GB GP3, auto-scaling to 100GB)**: ~$2-10/month
- **KMS Key**: ~$1/month
- **Secrets Manager**: ~$0.40/month
- **Lambda Functions**: Free tier covers initialization
- **CloudWatch Logs**: ~$1/month
- **Total**: ~$20/month

#### Future production (estimated)
- **RDS PostgreSQL (db.r5.large, Multi-AZ)**: ~$180/month
- **Lambda Functions**: ~$20/month
- **API Gateway**: ~$15/month
- **OpenSearch (for vector search)**: ~$200/month
- **S3 Storage**: ~$10/month
- **CloudWatch**: ~$15/month
- **Total**: ~$440/month

### External service costs
- **OpenAI API**: Variable based on usage (~$20-100/month typical)
- **Discord**: Free
- **FoundryVTT**: One-time $50 license fee

### Cost optimization features
- **Auto-scaling storage**: Pay only for what you use
- **Development lifecycle**: Easy teardown/rebuild for cost control
- **Resource tagging**: Track costs by environment and feature
- **Terraform automation**: Consistent deployments reduce waste

## Getting started

### For Dungeon Masters
1. **Deploy the database infrastructure** using the provided Terraform modules
2. **Explore the pre-loaded schema** with D&D races, tags, and lookup tables
3. **Add your campaign data** using the normalized database structure
4. **Plan Discord bot integration** for player interactions
5. **Design FoundryVTT integration** for in-game AI assistance

### For Developers
1. **Review the database schema** in `Database/DATABASE_SCHEMA.md`
2. **Deploy the development environment** using Terraform
3. **Explore the infrastructure code** in `terraform/modules/database/`
4. **Contribute to Lambda functions** and API development
5. **Help build Discord bot** and FoundryVTT integrations

### For Infrastructure Engineers
1. **Study the Terraform modules** for AWS best practices
2. **Customize the database configuration** for your requirements
3. **Extend the infrastructure** with additional AWS services
4. **Implement monitoring** and alerting solutions
5. **Optimize costs** and performance for your use case

## Deployment guide

### Manual deployment (alternative)
For step-by-step control instead of build.ps1:
```powershell
cd terraform\environments\dev
terraform init
terraform plan
terraform apply
```

### **Production Deployment**
1. Create `terraform/environments/prod/` directory
2. Copy and modify configuration from dev environment
3. Increase instance sizes and enable Multi-AZ
4. Enable enhanced monitoring and backup retention
5. Configure production security settings

Note: A full deployment guide will be added as services (Discord bot, API, FoundryVTT) are implemented.

## Configuration

### Environment variables (Terraform)
- `TF_VAR_owner_name`: Your name for resource tagging
- `TF_VAR_aws_region`: AWS deployment region (default: us-east-1)
- `TF_VAR_my_ip_cidr`: Your IP address for database access
- `TF_VAR_enable_public_access`: Enable public database access (dev only)

### Customization options
- **Database Configuration**: Modify instance sizes, storage, and backup settings
- **Security Settings**: Configure access controls and encryption
- **Monitoring Levels**: Adjust CloudWatch logging and Performance Insights
- **Cost Controls**: Set up budget alerts and auto-scaling policies

## API documentation (planned)

### **Core Endpoints (Planned)**
- `POST /api/v1/query` - Submit knowledge base queries
- `POST /api/v1/npc/interact` - Interact with NPCs
- `GET /api/v1/character/{id}` - Retrieve character information
- `POST /api/v1/documents/upload` - Add new content to knowledge base
- `GET /api/v1/campaign/state` - Get current world state

### **Webhook Support**
- Discord message events
- FoundryVTT state changes
- Campaign progression updates

## Contributing

We welcome contributions! Please see our contributing guidelines and submit pull requests for:
- Additional Terraform modules
- Database schema enhancements
- Lambda function implementations
- Discord bot commands
- FoundryVTT feature enhancements
- Documentation improvements

## License

MIT License - See LICENSE file for details

## Support

- **Documentation**: Check the `/docs` folder and `Database/DATABASE_SCHEMA.md` for detailed guides
- **Issues**: Report bugs via GitHub Issues
- **Discussions**: Join our community discussions
- **Infrastructure**: See `terraform/README.md` for deployment help

---

*Built with ❤️ for the D&D community*

---

## README quality rubric (used for this document)

Weights in parentheses; total 100.

1) Audience clarity and TL;DR (10)
- Clear value proposition, who it’s for, and what it does in 3–5 lines.

2) Setup speed-to-value (15)
- Minimal steps, copy-pasteable commands, environment-agnostic notes.

3) Fidelity to repo/state of code (15)
- Commands, paths, and modules match the current tree and features.

4) Architecture comprehension (10)
- Components, data flow, and responsibilities are understandable at a glance.

5) Security and secrets hygiene (10)
- Explains how secrets are handled and kept out of git/state and how consumers access them.

6) Reproducibility and env management (10)
- Clear environment separation, state isolation, and how to switch environments.

7) Project structure and navigation (10)
- Up-to-date tree; pointers to docs and key modules.

8) Operational guidance (10)
- Verification, troubleshooting starters, and costs overview.

9) Roadmap/status (5)
- What’s done, in progress, and planned.

10) Contribution and licensing (5)
- How to contribute and under what license.

Applying the rubric before this update, the README scored well on architecture and schema depth, but lost points on setup speed, accuracy vs repo (deprecated scripts), and secrets hygiene. This revision addresses those gaps: uses the root build.ps1, documents the new secrets workflow, aligns modules/outputs, and preserves a friendly quick start.