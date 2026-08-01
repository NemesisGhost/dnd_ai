# Persistent World Domain Model

## 1. Purpose

This document defines the conceptual domain model for the persistent world platform. It describes the major domain objects, their responsibilities, their boundaries, and the relationships between them.

This is not a complete physical database schema. Exact columns, indexes, and migration details are defined elsewhere. The goal here is to establish a stable language and structure before implementation expands.

The model is designed for:

- Persistent game worlds.
- Multiple simultaneous campaigns.
- Shared and branching timelines.
- D&D-compatible character mechanics.
- Rich NPC portrayal and world-management data.
- Dungeon exploration and state changes.
- Quest progression.
- Player and NPC knowledge differences.
- AI-assisted world management.
- Future import of existing campaign material.

---

## 2. Core modeling principles

### 2.1 The world exists independently of a campaign

A campaign is not the owner of the setting. The world contains persistent entities, definitions, history, geography, and lore.

Campaigns operate within timelines of that world.

### 2.2 Timelines own mutable world history

A world may have multiple timelines. Each timeline represents a particular evolving history.

Multiple campaigns may share a timeline. A timeline may branch from another timeline.

### 2.3 Entities identify important things

Anything that requires persistent identity, relationships, history, names, provenance, or cross-domain references should usually be represented as an entity.

Examples:

- characters
- locations
- organizations
- named items
- events
- quests
- religions
- deities
- settlements
- dungeons

Not every lookup or rules definition needs to be a world entity.

### 2.4 Definitions, state, knowledge, and history are separate

For any important object, the model should distinguish:

- **Definition:** What the object fundamentally is.
- **State:** Its current condition in a timeline.
- **Knowledge:** What a character, party, organization, or public group knows or believes.
- **History:** Events that caused change.

### 2.5 Player characters and NPCs share mechanics

Player characters and NPCs derive from the same character model.

NPCs add portrayal, routines, goals, private knowledge, AI assignments, and simulation metadata.

### 2.6 Events cause meaningful change

Events represent significant happenings. They connect actions, state changes, quest progress, discoveries, relationship changes, and world history.

### 2.7 Knowledge is perspective-dependent

Canonical truth and a character's belief are not the same thing.

The model must preserve incomplete, false, outdated, secret, and disputed knowledge.

---

## 3. Top-level domain map

```text
World
├── Timelines
│   ├── Campaigns
│   │   ├── Parties
│   │   └── Sessions
│   ├── Events
│   └── Mutable State
├── Entities
│   ├── Characters
│   ├── Locations
│   ├── Organizations
│   ├── Item Instances
│   ├── Events
│   ├── Quests
│   └── Knowledge Items
├── Rulesets
├── Calendars
├── Relationships
└── Sources and Canon Metadata
```

Supporting domains:

```text
Interaction
Knowledge
Narrative
AI
Audit
Import
Integration
Security
```

---

## 4. World domain

### 4.1 World

A **World** is the persistent setting container.

A world owns:

- entity definitions
- calendars
- default rulesets
- geography
- organizations
- lore
- religions
- named items
- canonical history
- timelines

A world does not directly contain mutable campaign state. Mutable state belongs to timelines.

### 4.2 Entity

An **Entity** is the universal identity record for a significant world object.

Core properties include:

- immutable identifier
- world
- entity type
- canonical name
- display summary
- lifecycle status
- canon status
- provenance
- creation and update metadata

An entity may have:

- aliases
- tags
- relationships
- images or assets
- notes
- embeddings
- external identifiers

### 4.3 Entity type

An **Entity Type** identifies the conceptual subtype of an entity.

Examples:

- character
- NPC
- player character
- location
- settlement
- dungeon
- organization
- business
- item instance
- event
- quest
- knowledge item

Entity types may form a metadata hierarchy, but subtype tables remain the authoritative implementation of inheritance.

### 4.4 Entity name

An **Entity Name** represents an alternate or historical name.

Name types include:

- canonical
- common
- title
- nickname
- alias
- secret identity
- former name
- translated name
- disguise

Names may have visibility and temporal validity.

### 4.5 Source

A **Source** records provenance.

Examples:

- GM-authored entry
- imported campaign document
- player submission
- FoundryVTT actor
- Discord interaction
- rulebook
- AI-generated proposal
- migration seed

### 4.6 Canon status

Canon status describes whether content is accepted into the authoritative world.

Typical states:

- draft
- proposed
- approved
- canon
- superseded
- rejected
- deprecated

---

## 5. Timeline and campaign domain

### 5.1 Timeline

A **Timeline** is one evolving history of a world.

A timeline may:

- be the primary history
- have a parent timeline
- branch at a specific event or world time
- contain one or more campaigns
- contain timeline-specific state and events

A timeline inherits parent history only up to the branch point.

### 5.2 Campaign

A **Campaign** is an organized game running within one timeline.

A campaign includes:

- participants
- parties
- sessions
- campaign-specific configuration
- ruleset configuration
- campaign notes

A campaign does not duplicate world entities.

### 5.3 Party

A **Party** is an organized group of characters.

The party itself is a stable identity within a world. Its membership is mutable timeline state: branches may inherit the same party identity while diverging on who belongs to it.

A party can:

- exist across sessions
- participate in more than one campaign
- change membership over time
- possess shared knowledge
- possess shared inventory or resources
- have faction reputation

### 5.4 Party membership

A **Party Membership** relates a character to a party during a period of time.

Membership is scoped to a timeline. A character's membership change in one branch must not silently change the party in another branch.

It supports:

- joining
- leaving
- temporary guests
- missing characters
- retainers
- companions
- leadership roles

### 5.5 Session

A **Session** is a unit of play within a campaign.

A session records:

- real-world start and end time
- in-world start and end time
- participating characters and users
- events
- interactions
- summaries
- state checkpoints where needed

A session is organizational context; timeline events remain the authority for world changes.

---

## 6. Time domain

### 6.1 Calendar

A **Calendar** defines a fictional time system.

It may include:

- eras
- years
- months
- weeks
- days
- named periods
- leap rules
- display formatting

### 6.2 World time

A **World Time** represents a point or approximate period in fictional chronology.

It supports:

- exact date and time
- partial date
- approximate date
- relative narrative label
- sortable value
- calendar reference

### 6.3 System time versus world time

The platform tracks two types of time:

- **System time:** when a record was created, changed, or observed by the software.
- **World time:** when an event or state was effective in the fictional world.

These must not be conflated.

---

## 7. Rules domain

### 7.1 Ruleset

A **Ruleset** identifies a game system and version.

Examples:

- D&D 5e 2014
- D&D 5e 2024
- homebrew variant

A campaign selects a ruleset configuration. A world may define a default.

### 7.2 Rule definition

Rule definitions are reusable mechanical concepts.

Examples:

- ability
- skill
- class
- subclass
- feature
- feat
- spell
- condition
- damage type
- item definition
- creature type
- language

Rule definitions are not timeline entities unless a particular instance becomes relevant in the world.

### 7.3 Homebrew definition

A **Homebrew Definition** is a rules definition with explicit source and canon metadata.

Homebrew must use the same structures as official rule definitions.

---

## 8. Character domain

### 8.1 Character

A **Character** is a mechanically represented actor.

Characters include:

- player characters
- NPCs
- companions
- retainers
- major monsters
- intelligent creatures

Shared character data includes:

- species or ancestry
- size
- ability scores
- classes and levels
- skills and proficiencies
- features
- spells
- languages
- senses
- movement
- inventory
- conditions
- current resources

### 8.2 Character build

A **Character Build** is a versioned mechanical configuration.

It includes:

- ruleset version
- level
- classes
- ability scores
- features
- proficiencies
- spellcasting

A character may have different builds in different timelines.

### 8.3 Character state

**Character State** is mutable timeline-specific condition.

Examples:

- current hit points
- temporary hit points
- current location
- active conditions
- exhaustion
- expended spell slots
- resource usage
- current transformation

### 8.4 Character controller

A **Character Controller** identifies who currently controls a character.

Controller types include:

- player
- GM
- AI agent
- shared party control
- temporary controller

Control can vary by campaign, session, or time period.

### 8.5 Player character

A **Player Character** is a character with player-ownership and campaign participation metadata.

The PC subtype adds:

- owning user or users
- permissions
- player-facing notes
- campaign preferences

It does not duplicate shared mechanics.

### 8.6 NPC

An **NPC** is a character with additional world-management and portrayal information.

The NPC subtype adds:

- simulation level
- importance
- portrayal profile
- goals
- routines
- preferences
- boundaries
- emotional state
- AI-agent assignments
- private knowledge and disclosure policy

### 8.7 NPC portrayal profile

An **NPC Portrayal Profile** provides versioned performance guidance.

It may include:

- voice
- speech style
- vocabulary
- mannerisms
- emotional baseline
- conversational rhythm
- social behavior
- roleplay instructions
- topics avoided
- disclosure restrictions

### 8.8 NPC characteristic

An **NPC Characteristic** is a structured portrayal or personality element.

Types include:

- personality trait
- ideal
- bond
- flaw
- fear
- motivation
- bias
- preference
- aversion
- habit
- mannerism
- speech pattern

### 8.9 NPC goal

An **NPC Goal** represents a desired outcome.

A goal has:

- priority
- status
- target entities
- progress
- dependencies
- secrecy
- initiating event
- completion or failure event
- world or timeline scope

### 8.10 NPC routine

An **NPC Routine** describes expected activity over time.

A routine may contain:

- schedule
- locations
- activities
- participants
- exceptions
- priority
- active period

A routine is a planning aid, not immutable truth. Events and active goals may override it.

---

## 9. Location and geography domain

### 9.1 Location

A **Location** is a spatial entity.

Location subtypes include:

- plane
- realm
- continent
- nation
- region
- settlement
- district
- building
- dungeon
- dungeon area
- geographic feature

Locations may be nested through containment.

### 9.2 Settlement

A **Settlement** is a populated location.

It may have:

- population
- government
- districts
- economy
- defenses
- services
- factions
- timeline-specific control and damage state

### 9.3 Building

A **Building** is a constructed location.

Examples:

- tavern
- temple
- government hall
- residence
- shop
- warehouse

### 9.4 Dungeon

A **Dungeon** is a location composed of connected areas and stateful gameplay elements.

A dungeon may include:

- areas
- connections
- hazards
- interactables
- mechanisms
- power states
- encounter definitions
- environmental state machines

### 9.5 Dungeon area

A **Dungeon Area** is a room, chamber, corridor, platform, cavern, or similar navigable unit.

An area has:

- parent dungeon
- description
- dimensions
- environmental properties
- features
- hazards
- interactables
- spawn definitions
- connections

### 9.6 Area connection

An **Area Connection** links two areas.

Connection types include:

- door
- secret door
- passage
- portal
- stair
- ladder
- bridge
- pit
- teleportation link

A connection has a definition and timeline-specific state.

### 9.7 Area feature

An **Area Feature** is a notable but not necessarily interactive part of an area.

Examples:

- mural
- blood trail
- altar
- broken machinery
- drag marks
- statue

### 9.8 Hazard

A **Hazard** is a dangerous environmental object or condition.

Examples:

- trap
- collapsing floor
- electrical arc
- poisonous gas
- magical ward

Hazards have timeline state and may produce interactions and events.

### 9.9 Interactable

An **Interactable** is an object or mechanism intended to receive actions.

Examples:

- lever
- control panel
- lock
- pylon
- puzzle component
- sealed hatch

---

## 10. Organization and society domain

### 10.1 Organization

An **Organization** is a persistent group with identity, membership, goals, and relationships.

Organization subtypes include:

- government
- business
- guild
- military unit
- religious organization
- criminal organization
- political faction
- secret society

### 10.2 Organization membership

An **Organization Membership** is a specialized relationship between an entity and an organization.

It supports:

- role
- rank
- status
- influence
- public or secret membership
- joining and leaving
- multiple memberships over time

### 10.3 Business

A **Business** is an organization engaged in trade, services, or production.

It may have:

- business type
- locations
- employees
- owners
- inventory
- prices
- operating status
- reputation

### 10.4 Government

A **Government** is an organization that governs one or more entities or territories.

It may include:

- government form
- jurisdiction
- offices
- leaders
- laws
- agencies
- political relationships

### 10.5 Religion

A **Religion** is a belief system, theology, or doctrine.

It is distinct from a religious organization.

A religion may have:

- deities
- doctrines
- rituals
- sacred texts
- holy sites
- symbols
- traditions

### 10.6 Religious organization

A **Religious Organization** is an organization affiliated with a religion.

Examples:

- church
- temple
- order
- monastery
- cult

### 10.7 Personal religious affiliation

A **Character Religious Affiliation** represents a character's personal relationship with a religion.

It includes:

- devotion
- belief status
- practice
- interpretation
- conflicts
- public display

Clergy office and organizational rank remain organization memberships.

---

## 11. Relationship domain

### 11.1 Relationship

A **Relationship** connects two or more entities through a meaningful association.

Examples:

- family
- employment
- membership
- ownership
- alliance
- rivalry
- war
- control
- worship
- adjacency

### 11.2 Relationship participant

A **Relationship Participant** identifies an entity's role in a relationship.

Participant roles allow asymmetric relationships, such as:

- parent and child
- employer and employee
- owner and property
- ruler and territory

### 11.3 Relationship perspective

A **Relationship Perspective** stores a participant's subjective view.

It may include:

- trust
- affinity
- respect
- fear
- obligation
- emotional tone
- private interpretation

Shared relationship facts and subjective perceptions must remain separate.

### 11.4 Specialized relationship

A specialized relationship extends the base relationship with domain-specific details.

Examples:

- membership
- employment
- ownership
- family
- political control

---

## 12. Item domain

### 12.1 Item definition

An **Item Definition** is a reusable rules concept.

Examples:

- longsword
- healing potion
- rope
- spell scroll

### 12.2 Item instance

An **Item Instance** is a specific object in the world.

Examples:

- a particular healing potion in a chest
- a named legendary sword
- a damaged shield used to repair a machine

### 12.3 Item state

**Item State** is timeline-specific and includes:

- location
- possessor
- container
- quantity
- charges
- condition
- equipped state
- attunement
- destruction status

### 12.4 Ownership versus possession

Ownership and possession are separate.

An item may be:

- owned by a noble
- stolen by a rogue
- stored in a guild vault
- temporarily carried by a party member

### 12.5 Item identification

**Item Identification** is knowledge about an item.

Different characters may know different properties of the same item.

---

## 13. Event domain

### 13.1 Event

An **Event** is a significant occurrence in a timeline.

An event includes:

- timeline
- world time
- optional campaign and session
- type
- title
- summary
- details
- status
- source

### 13.2 Event participant

An **Event Participant** relates an entity to an event.

Roles include:

- actor
- target
- witness
- victim
- beneficiary
- organizer
- location controller

### 13.3 Event location

An **Event Location** identifies where an event occurred or what locations it affected.

### 13.4 Event cause

An **Event Cause** links an event to prior events, interactions, decisions, or conditions.

### 13.5 Event effect

An **Event Effect** describes a change caused by an event.

It identifies:

- target entity
- affected component
- previous value
- new value
- application status
- effective time

### 13.6 Event observation

An **Event Observation** records what an observer perceived.

This is separate from the event's objective facts.

---

## 14. Narrative and quest domain

### 14.1 Story arc

A **Story Arc** groups related quests, events, themes, and outcomes.

### 14.2 Quest

A **Quest** is a structured narrative challenge or objective set.

A quest may be persistent world content, while its active progress is scoped to a timeline, campaign, or party.

### 14.3 Quest stage

A **Quest Stage** groups objectives into a phase.

Stages can be:

- sequential
- optional
- conditional
- mutually exclusive

### 14.4 Quest objective

A **Quest Objective** defines a completion or failure condition.

Types include:

- reach a location
- acquire an item
- defeat or protect an entity
- activate mechanisms
- discover knowledge
- persuade an NPC
- survive a condition
- complete before a deadline

Objectives may be required, optional, or hidden.

### 14.5 Objective dependency

An **Objective Dependency** defines prerequisite, blocking, exclusion, or branching relationships between objectives.

### 14.6 Quest state

**Quest State** tracks active progress for a timeline, campaign, or party.

### 14.7 Objective state

**Objective State** includes:

- hidden
- available
- active
- completed
- failed
- skipped
- superseded

Transitions must reference a triggering event or GM decision.

### 14.8 Quest outcome

A **Quest Outcome** defines meaningful resolutions and downstream effects.

Outcomes may activate new quests, alter relationships, change organizations, reveal knowledge, or update world state.

---

## 15. Knowledge domain

### 15.1 Knowledge item

A **Knowledge Item** is a specific claim, belief, secret, rumor, memory, instruction, or theory.

It includes:

- canonical statement
- knowledge type
- truth status
- sensitivity
- subject entities
- temporal validity
- provenance

### 15.2 Knowledge version

A **Knowledge Version** represents a changed or distorted form of a knowledge item.

This supports rumor mutation and incomplete reports.

### 15.3 Entity knowledge

**Entity Knowledge** records what an entity knows or believes.

It includes:

- knower
- knowledge item or version
- awareness level
- belief strength
- confidence
- interpretation
- source
- learned time
- sharing rules

### 15.4 Party knowledge

**Party Knowledge** records knowledge shared at the party level.

It does not imply every member has identical understanding unless the application explicitly promotes it to individual knowledge.

### 15.5 Discovery

A **Discovery** records the moment knowledge was acquired.

It links:

- recipient
- knowledge
- interaction or event
- source
- world time
- session

### 15.6 Information transfer

An **Information Transfer** records communication between entities.

It supports:

- dialogue
- written messages
- public announcements
- rumors
- telepathy
- magical visions

### 15.7 Expertise

**Expertise** represents knowledge capability in a subject area, not possession of a specific fact.

Examples:

- arcana
- local history
- poison crafting
- Inquisition procedures

---

## 16. Interaction domain

### 16.1 Interaction

An **Interaction** is a structured attempt by one or more actors to affect or examine the world.

Examples:

- move
- search
- persuade
- attack
- cast a spell
- use an item
- activate a mechanism
- pick a lock
- rest

### 16.2 Action

An **Action** is an individual operation within an interaction.

A complex interaction may contain multiple actions.

### 16.3 Target

An **Interaction Target** identifies entities, components, areas, or abstract objectives affected by an action.

### 16.4 Check request

A **Check Request** describes a required rules resolution.

It includes:

- actor
- ability or skill
- difficulty
- advantage or disadvantage
- modifiers
- stakes

### 16.5 Check result

A **Check Result** records:

- roll
- modifiers
- total
- degree of success
- visibility
- external system source

### 16.6 Consequence

A **Consequence** is a proposed or resolved outcome of an interaction.

Consequences may create:

- observations
- events
- state changes
- discoveries
- quest changes
- relationship changes

---

## 17. Encounter domain

### 17.1 Encounter

An **Encounter** is an organized tactical or social conflict.

Examples:

- combat
- chase
- negotiation
- environmental survival sequence

### 17.2 Encounter participant

An **Encounter Participant** is a character, creature, hazard, or faction involved in the encounter.

### 17.3 Round and turn

Rounds and turns organize tactical sequence when required by the ruleset.

### 17.4 Encounter outcome

An **Encounter Outcome** summarizes persistent results such as:

- defeated
- escaped
- surrendered
- captured
- rescued
- mechanism disabled

Detailed tactical logs may remain in FoundryVTT or interaction records. Persistent consequences become events and state changes.

---

## 18. State domain

### 18.1 Typed state

Frequently queried mutable data uses typed state records.

Examples:

- character state
- location state
- connection state
- hazard state
- item state
- organization state
- relationship state
- quest state

### 18.2 Effective state

**Effective State** is the result of resolving:

1. current timeline state
2. inherited parent-timeline state up to the branch point
3. canonical entity definition
4. ruleset defaults

### 18.3 State history

State history is preserved through:

- events
- temporal state rows
- audit records

Current-state rows optimize reads but must retain the event that established them.

### 18.4 Generic overrides

A generic override mechanism may support experimental properties, but typed state is preferred for important or frequently queried data.

---

## 19. AI domain

### 19.1 AI agent

An **AI Agent** is a configured model-backed service with a defined role.

Agent roles may include:

- NPC portrayal
- quest management
- dungeon state
- rules assistance
- world simulation
- lore consistency
- session summarization
- rumor propagation

### 19.2 Agent assignment

An **Agent Assignment** links an agent to an entity, campaign, timeline, or responsibility.

### 19.3 Context request

A **Context Request** records what information an agent requested and why.

### 19.4 Context snapshot

A **Context Snapshot** is the structured and rendered context supplied to an agent.

It should record:

- included entities
- state version
- knowledge filtering
- prompt template
- token estimates

### 19.5 Prompt fragment

A **Prompt Fragment** is a derived or curated text component used during prompt assembly.

Structured records remain authoritative.

### 19.6 Generated output

A **Generated Output** records an agent response before any resulting changes are applied.

### 19.7 Proposed change

A **Proposed Change** is a structured mutation request from an agent.

It includes:

- target
- proposed command or payload
- reason summary
- confidence
- risk classification
- approval status

### 19.8 Change review

A **Change Review** records automatic policy evaluation or human approval.

---

## 20. Audit domain

### 20.1 Change log

The **Change Log** records durable changes to important records.

### 20.2 State transition

A **State Transition** records movement between controlled statuses.

### 20.3 Approval history

**Approval History** records who approved, rejected, or modified proposed content.

### 20.4 Validation failure

A **Validation Failure** records rejected commands, imports, or AI proposals.

### 20.5 Agent activity

**Agent Activity** records agent executions, inputs, outputs, costs, and applied effects.

---

## 21. Import domain

### 21.1 Import job

An **Import Job** represents ingestion of one or more source documents.

### 21.2 Staged entity

A **Staged Entity** is an extracted candidate that has not yet become canon.

### 21.3 Entity match

An **Entity Match** links staged content to a possible existing entity.

### 21.4 Staged relationship, event, and knowledge

These records hold extracted facts for review.

### 21.5 Approval batch

An **Approval Batch** groups reviewed staged records before commands create canonical data.

---

## 22. Integration domain

### 22.1 External identifier

An **External Identifier** maps an internal object to an external system object.

Examples:

- Foundry actor ID
- Foundry scene ID
- Discord channel ID
- Discord message ID
- S3 document key

### 22.2 Sync state

**Sync State** tracks synchronization status, version, timestamps, and conflicts.

### 22.3 Integration event

An **Integration Event** records incoming or outgoing activity with external systems.

---

## 23. Security domain

### 23.1 User

A **User** represents an authenticated person or service identity.

### 23.2 Role

Roles may include:

- administrator
- GM
- assistant GM
- player
- observer
- integration service
- AI service

### 23.3 Permission

Permissions must support:

- world access
- campaign access
- GM-only content
- player-character ownership
- AI proposal approval
- import approval
- source-document access

### 23.4 Visibility policy

A **Visibility Policy** controls who may see a record or field.

Common scopes:

- public
- GM only
- specific campaign
- specific party
- specific character
- specific organization
- conditionally shareable

Visibility is especially important for knowledge, NPC secrets, hidden dungeon features, and quest objectives.

---

## 24. Cross-domain gameplay example

A party searches a dungeon chamber.

```text
Character
    performs Interaction: Search Area
        creates Check Request: Investigation
            produces Check Result: Success
                creates Discovery: Concealed Hatch
                grants Party Knowledge
                updates hidden Objective visibility
```

The party forces the hatch open.

```text
Interaction: Force Hatch
    -> Event: Hatch Forced Open
    -> Connection State: Closed/Locked to Open/Damaged
    -> Noise Event
    -> Item becomes accessible
    -> NPC routine or encounter may react
```

The party retrieves a key and activates a mechanism.

```text
Interaction: Activate Pylon
    -> Event: Pylon Activated
    -> Dungeon Power State changes
    -> Quest Objective progress 1/3 to 2/3
    -> Hazard State changes
    -> AI dungeon agent receives updated context
```

Another campaign on the same timeline later sees the open hatch and activated pylon, but does not automatically receive the first party's private discoveries or interpretations.

---

## 25. Aggregate and transaction boundaries

The domain is relational and interconnected, but write operations should use clear aggregate boundaries.

Suggested command aggregates:

- world and entity creation
- character creation
- dungeon creation
- session lifecycle
- interaction resolution
- event application
- quest advancement
- knowledge revelation
- relationship change
- timeline branching
- AI proposal approval

A single command may update multiple tables atomically.

Do not treat every table as an independently writable API resource.

---

## 26. Domain invariants

Key invariants include:

- An entity belongs to exactly one world.
- A subtype row must match its entity type.
- A timeline belongs to one world.
- Timeline state may reference only entities in its world.
- A campaign belongs to one timeline.
- An event belongs to one timeline.
- A branch timeline must share its parent's world.
- A character's PC or NPC subtype must reuse the character ID.
- A hidden feature's existence is independent of discovery.
- Knowledge truth is independent of belief.
- Quest progress changes must reference a cause.
- Current state must reference the event or command that established it.
- AI-generated proposals cannot silently bypass canon and approval policy.

---

## 27. Intentionally deferred domain areas

The following are recognized but will receive dedicated design later:

- detailed economy and markets
- weather and climate simulation
- law and crime systems
- travel and route planning
- mass combat
- crafting and production
- downtime activities
- procedural generation
- detailed settlement population simulation
- graph-analysis projections
- cross-world travel

These areas must extend the existing entity, relationship, event, state, and knowledge foundations rather than creating incompatible parallel models.
