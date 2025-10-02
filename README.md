# **D&D AI - Intelligent Campaign Management System**

A comprehensive AI-powered toolkit for D&D Dungeon Masters that leverages AWS cloud infrastructure and OpenAI's ChatGPT to create an intelligent, interactive campaign management system. Players can interact with NPCs, query world information, and get real-time assistance through Discord and FoundryVTT integrations.

## **System Architecture**

### **Overview**
This system creates an intelligent D&D world by:
- Processing D&D source books, world documents, and NPC records into a searchable knowledge base
- Providing real-time AI-powered interactions through Discord Bot and FoundryVTT
- Maintaining persistent world state and character progression
- Enabling easy content updates and knowledge base expansion

### **Core Components**

#### **1. Document Processing Pipeline**
**AWS Services**: S3, Lambda, SQS, EventBridge
- **Document Ingestion**: S3 bucket with event-driven processing
- **PDF Processing**: Lambda functions using PyPDF2/pdfplumber for text extraction
- **Content Chunking**: Intelligent text segmentation for optimal embedding
- **Embedding Generation**: OpenAI API integration for vector embeddings
- **Vector Storage**: Amazon OpenSearch/Pinecone for similarity search

```
PDF Upload → S3 Event → Lambda Processor → OpenAI Embeddings → Vector DB
```

#### **2. AI Knowledge Base & Query Engine**
**AWS Services**: OpenSearch, Lambda, API Gateway
- **Vector Search**: Semantic search across all ingested content
- **Context Assembly**: Retrieval-Augmented Generation (RAG) pipeline
- **Response Generation**: OpenAI GPT integration with custom prompts
- **Caching Layer**: ElastiCache for frequently accessed content

#### **3. Discord Bot**
**Technology**: Discord.py, AWS Lambda, API Gateway
- **Slash Commands**: 
  - `/ask [question]` - Query the knowledge base
  - `/npc [name] [message]` - Interact with specific NPCs
  - `/roll [dice]` - Enhanced dice rolling with context
  - `/character [action]` - Character sheet management
- **NPC Interactions**: Context-aware conversations with personality persistence
- **Campaign Management**: Session notes, world state updates
- **Player Authentication**: Discord OAuth integration

#### **4. FoundryVTT Module**
**Technology**: JavaScript ES6, FoundryVTT API
- **AI Assistant Panel**: In-game interface for DM queries
- **NPC Dialog System**: Click-to-talk AI NPC interactions
- **World State Sync**: Real-time synchronization with knowledge base
- **Combat Integration**: AI-powered tactical suggestions
- **Character Sheet Integration**: Automatic stat queries and rule lookups

#### **5. API Gateway & Orchestration**
**AWS Services**: API Gateway, Lambda, Cognito
- **REST API**: Unified interface for all system interactions
- **Authentication**: JWT tokens with role-based access
- **Rate Limiting**: Per-user API quotas to manage OpenAI costs
- **Request Routing**: Intelligent routing to appropriate services
- **Webhook Support**: Real-time updates to connected clients

#### **6. Database Layer**
**AWS Services**: RDS (PostgreSQL)
- **NPC System**: Comprehensive character profiles with personality, relationships, and knowledge
- **World Building**: Settlements, nations, organizations, businesses, and landmarks
- **Knowledge Management**: Topic categories, conversation systems, and information tracking
- **Event System**: Significant events with complex relationships and player knowledge tracking
- **Occupational Framework**: Job categories and skill associations
- **Campaign Data**: Sessions, notes, important decisions
- **User Management**: Player profiles, permissions, preferences

#### **7. Infrastructure Management**
**Technology**: Terraform, GitHub Actions
- **Modular Design**: Reusable Terraform modules
- **Environment Management**: Dev/staging/production deployments
- **Secrets Management**: AWS Secrets Manager integration
- **Monitoring**: CloudWatch, X-Ray tracing
- **Cost Optimization**: Auto-scaling, scheduled shutdowns

## **Database Schema**

The D&D AI system uses a comprehensive PostgreSQL database designed specifically for world-building and AI integration. The schema emphasizes narrative elements over mechanical D&D stats, creating a rich knowledge base for intelligent storytelling.

### **Key Features**
- **228 SQL tables** with normalized, 3NF-compliant design
- **AI-friendly structure** with JSONB fields for flexible data
- **Complex relationship modeling** for realistic NPC interactions
- **Full-text search optimization** for natural language queries
- **Player knowledge management** with information asymmetry support

### **Core Entity Types**
- **NPCs**: Detailed personality profiles with conversation styles and AI prompts
- **World Entities**: Settlements, nations, organizations, businesses, landmarks
- **Knowledge System**: Topics, conversation flows, and information networks
- **Relationships**: Complex social connections and event histories
- **Lookup Tables**: 25+ reference tables for consistent data

### **AI Integration Points**
- **Personality Prompts**: Custom ChatGPT instructions per NPC
- **Interaction History**: JSONB logs of AI conversations for continuity
- **Knowledge Confidence**: Tracking how certain NPCs are about information
- **Conversation Triggers**: Automatic topic transitions and dialogue hooks

**📋 For complete database documentation, see [Database/DATABASE_SCHEMA.md](Database/DATABASE_SCHEMA.md)**

## **Infrastructure Architecture**

### **Terraform Organization**

The infrastructure follows a **modular Terraform architecture** with clear separation between reusable components and environment-specific deployments:

#### **modules/ - Reusable Infrastructure Components**
- **Purpose**: Define infrastructure patterns that can be used across multiple environments
- **Reusability**: One module can be instantiated by multiple environments with different configurations
- **Versioning**: Modules can be tagged and versioned for stability across deployments
- **Example**: `modules/database/` defines RDS, VPC, security groups, and initialization logic

#### **environments/ - Environment-Specific Deployments**
- **Purpose**: Deploy modules with specific configurations for different environments (dev/staging/prod)
- **Isolation**: Each environment has independent Terraform state and AWS resources
- **Configuration**: Environment-specific variables, instance sizes, backup policies, etc.
- **Example**: `environments/dev/` uses the database module with development-friendly settings

#### **How They Work Together**
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

## **Project Structure**

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
├── terraform/                 # Infrastructure as Code (Terraform only)
│   ├── modules/               # Reusable infrastructure modules
│   │   └── database/         # PostgreSQL RDS module (reusable)
│   ├── environments/         # Environment-specific deployments  
│   │   └── dev/              # Development environment config
│   └── README.md             # Infrastructure overview
├── scripts/                   # Deployment and utility scripts
│   ├── deploy.ps1             # Infrastructure deployment
│   ├── destroy.ps1            # Infrastructure cleanup
│   ├── test-deployment.ps1    # Automated testing
│   ├── prepare_lambda.py      # Lambda packaging
│   └── build_lambda.*         # Lambda build scripts
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

## **Current Development Status**

### ✅ **Completed**
- **Database Schema**: Complete 228-table PostgreSQL schema for D&D world-building
- **Terraform Infrastructure**: Production-ready AWS RDS deployment with automation
- **Database Module**: Reusable Terraform module with encryption, monitoring, and initialization
- **Documentation**: Comprehensive setup guides and database documentation
- **Deployment Scripts**: Automated deployment and management tools

### 🚧 **In Progress**
- **Lambda Functions**: Document processing and AI query engine
- **Discord Bot**: Slash commands and NPC interaction system
- **API Gateway**: RESTful interface for system integration

### 📋 **Planned**
- **FoundryVTT Module**: In-game AI assistant and NPC dialog system
- **Document Processing Pipeline**: PDF ingestion and embedding generation
- **Vector Database**: OpenSearch integration for semantic search
- **Frontend Interface**: Web-based campaign management tools

## **Quick Start**

### **Prerequisites**
- **AWS Account** with appropriate IAM permissions
- **AWS CLI** configured with credentials
- **Terraform** >= 1.5 installed
- **Python 3.x** for Lambda packaging
- **PowerShell** (Windows) or Bash (Linux/Mac)

### **1. Deploy Database Infrastructure**

```powershell
# Clone the repository
git clone https://github.com/NemesisGhost/dnd_ai.git
cd dnd_ai

# Deploy the database infrastructure
cd terraform
.\scripts\deploy.ps1 -Environment dev

# Or manually:
cd environments\dev
terraform init
terraform plan
terraform apply
```

### **2. Verify Database Setup**

```powershell
# Check deployment outputs
terraform output

# Get database credentials
aws secretsmanager get-secret-value --secret-id "dnd-ai/dev/database/credentials"

# Connect to database (requires psql)
# Use connection details from Secrets Manager
psql -h your-db-endpoint -p 5432 -U dnd_admin -d dnd_ai_dev
```

### **3. Verify Database Schema**

```sql
-- Check that tables were created
\dt

-- Verify sample data
SELECT * FROM races LIMIT 5;
SELECT * FROM tags WHERE category_id = (SELECT category_id FROM tag_categories WHERE name = 'Role') LIMIT 5;
```

### **Next Steps**

1. **API Development**: Build Lambda functions for AI integration
2. **Discord Bot**: Implement slash commands and NPC interactions
3. **FoundryVTT Module**: Create in-game AI assistant
4. **Content Loading**: Add your campaign data to the database

## **Key Features**

### **For Dungeon Masters**
- **Intelligent Rule Lookup**: Instant access to any D&D rule or mechanic
- **Dynamic NPC Interactions**: AI-powered NPCs with consistent personalities and detailed backgrounds
- **World State Management**: Automatic tracking of campaign events and changes
- **Content Integration**: Easy addition of custom world documents and house rules
- **Session Planning**: AI-assisted encounter and story suggestions
- **Relationship Tracking**: Complex NPC networks with realistic information flow
- **Event Management**: Sophisticated tracking of significant events and their ongoing impact

### **For Players**
- **Natural Language Queries**: Ask questions in plain English about rules, lore, or characters
- **Character Assistance**: Rules clarification and optimization suggestions
- **NPC Conversations**: Engaging interactions with world characters who remember past conversations
- **Lore Discovery**: Deep dive into world history with intelligent information management
- **Relationship Building**: Meaningful connections with NPCs based on shared experiences and knowledge

### **System Administration**
- **Easy Deployment**: One-command infrastructure setup
- **Cost Management**: Usage monitoring and budget alerts
- **Content Updates**: Hot-swappable knowledge base updates
- **Multi-Campaign Support**: Isolated environments per campaign

## **Infrastructure Costs**

### **Current Implementation (PostgreSQL Database)**

#### **Development Environment**
- **RDS PostgreSQL (db.t3.micro)**: ~$15/month
- **Storage (20GB GP3, auto-scaling to 100GB)**: ~$2-10/month
- **KMS Key**: ~$1/month
- **Secrets Manager**: ~$0.40/month
- **Lambda Functions**: Free tier covers initialization
- **CloudWatch Logs**: ~$1/month
- **Total**: ~$20/month

#### **Future Production Environment (Estimated)**
- **RDS PostgreSQL (db.r5.large, Multi-AZ)**: ~$180/month
- **Lambda Functions**: ~$20/month
- **API Gateway**: ~$15/month
- **OpenSearch (for vector search)**: ~$200/month
- **S3 Storage**: ~$10/month
- **CloudWatch**: ~$15/month
- **Total**: ~$440/month

### **External Service Costs**
- **OpenAI API**: Variable based on usage (~$20-100/month typical)
- **Discord**: Free
- **FoundryVTT**: One-time $50 license fee

### **Cost Optimization Features**
- **Auto-scaling storage**: Pay only for what you use
- **Development lifecycle**: Easy teardown/rebuild for cost control
- **Resource tagging**: Track costs by environment and feature
- **Terraform automation**: Consistent deployments reduce waste

## **Getting Started**

### **For Dungeon Masters**
1. **Deploy the database infrastructure** using the provided Terraform modules
2. **Explore the pre-loaded schema** with D&D races, tags, and lookup tables
3. **Add your campaign data** using the normalized database structure
4. **Plan Discord bot integration** for player interactions
5. **Design FoundryVTT integration** for in-game AI assistance

### **For Developers**
1. **Review the database schema** in `Database/DATABASE_SCHEMA.md`
2. **Deploy the development environment** using Terraform
3. **Explore the infrastructure code** in `terraform/modules/database/`
4. **Contribute to Lambda functions** and API development
5. **Help build Discord bot** and FoundryVTT integrations

### **For Infrastructure Engineers**
1. **Study the Terraform modules** for AWS best practices
2. **Customize the database configuration** for your requirements
3. **Extend the infrastructure** with additional AWS services
4. **Implement monitoring** and alerting solutions
5. **Optimize costs** and performance for your use case

## **Deployment Guide**

### **Quick Deployment**
Use the automated deployment scripts:
```powershell
cd terraform
.\scripts\deploy.ps1 -Environment dev
```

### **Manual Deployment**
For step-by-step control:
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

**📋 See [terraform/DEPLOYMENT_GUIDE.md](terraform/DEPLOYMENT_GUIDE.md) for detailed instructions**

## **Configuration**

### **Environment Variables**
- `TF_VAR_owner_name`: Your name for resource tagging
- `TF_VAR_aws_region`: AWS deployment region (default: us-east-1)
- `TF_VAR_my_ip_cidr`: Your IP address for database access
- `TF_VAR_enable_public_access`: Enable public database access (dev only)

### **Customization Options**
- **Database Configuration**: Modify instance sizes, storage, and backup settings
- **Security Settings**: Configure access controls and encryption
- **Monitoring Levels**: Adjust CloudWatch logging and Performance Insights
- **Cost Controls**: Set up budget alerts and auto-scaling policies

## **API Documentation**

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

## **Contributing**

We welcome contributions! Please see our contributing guidelines and submit pull requests for:
- Additional Terraform modules
- Database schema enhancements
- Lambda function implementations
- Discord bot commands
- FoundryVTT feature enhancements
- Documentation improvements

## **License**

MIT License - See LICENSE file for details

## **Support**

- **Documentation**: Check the `/docs` folder and `Database/DATABASE_SCHEMA.md` for detailed guides
- **Issues**: Report bugs via GitHub Issues
- **Discussions**: Join our community discussions
- **Infrastructure**: See `terraform/README.md` for deployment help

---

*Built with ❤️ for the D&D community*