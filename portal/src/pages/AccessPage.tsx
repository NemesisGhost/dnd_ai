import { useId, useMemo } from "react"
import { AddAccessGroupMember } from "../components/AddAccessGroupMember"
import { AddCampaignMember } from "../components/AddCampaignMember"
import { AddCharacterRelationship } from "../components/AddCharacterRelationship"
import { AddGroupResourceGrant } from "../components/AddGroupResourceGrant"
import { AddMemberRole } from "../components/AddMemberRole"
import { AddResourceGrant } from "../components/AddResourceGrant"
import { CharacterRelationshipEditor } from "../components/CharacterRelationshipEditor"
import { CreateAccessGroup } from "../components/CreateAccessGroup"
import { DeactivateAccessGroup } from "../components/DeactivateAccessGroup"
import { EditAccessGroup } from "../components/EditAccessGroup"
import { EffectiveAccessPanel } from "../components/EffectiveAccessPanel"
import { MemberRoleEditor } from "../components/MemberRoleEditor"
import { ReactivateAccessGroup } from "../components/ReactivateAccessGroup"
import { RemoveAccessGroupMember } from "../components/RemoveAccessGroupMember"
import { RemoveCampaignMember } from "../components/RemoveCampaignMember"
import { RevokeCharacterRelationship } from "../components/RevokeCharacterRelationship"
import { RevokeMemberRole } from "../components/RevokeMemberRole"
import { RevokeResourceGrant } from "../components/RevokeResourceGrant"
import { useSession } from "../context/SessionContext"
import { useAccessDisclosure } from "../hooks/useAccessDisclosure"
import { AccessWriteScopeContext } from "../hooks/useAccessWriteCompletion"
import type { AccessDisclosure } from "../hooks/useAccessDisclosure"
import { humanizeCode } from "../utils/humanize"
import type {
    AccessGroupSummary,
    AssignableCharacter,
    AssignableCharacterRelationshipType,
    AssignableRole,
    CampaignAccessMember,
    CampaignAccessOverview,
    GrantableResourceCapability,
} from "../types/accessOverview"

// A scope for controls whose write cannot change the caller's own authority.
const NOT_THE_CALLER = { affectsCaller: false }

function formatTimestamp(timestamp: string): string {
    return new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
    }).format(new Date(timestamp))
}

interface MemberAccessCardProps {
    member: CampaignAccessMember
    campaignId: string
    campaignName: string
    assignableRoles: AssignableRole[]
    assignableCharacters: AssignableCharacter[]
    assignableRelationshipTypes: AssignableCharacterRelationshipType[]
    grantableResourceCapabilities: GrantableResourceCapability[]
    preselectCharacterId: string | null
    onChanged: (message: string) => void
    onMutationStart: () => void
    disclosure: AccessDisclosure
    onRefreshAccess: (campaignMembershipId: string) => void
    // Whether a write made from this card can change the CALLER's own authority: the card is the caller's
    // own membership. Any other member's card cannot (see hooks/useAccessWriteCompletion).
    isCallerMember: boolean
}

function MemberAccessCard({
    member,
    campaignId,
    campaignName,
    assignableRoles,
    assignableCharacters,
    assignableRelationshipTypes,
    grantableResourceCapabilities,
    preselectCharacterId,
    onChanged,
    onMutationStart,
    disclosure,
    onRefreshAccess,
    isCallerMember,
}: MemberAccessCardProps) {
    const rolesHeadingId = useId()
    const relationshipsHeadingId = useId()
    const grantsHeadingId = useId()
    const revelationsHeadingId = useId()
    const membershipId = member.campaign_membership_id
    const writeScope = useMemo(() => ({ affectsCaller: isCallerMember }), [isCallerMember])

    const roleSummary = member.roles
        .map((role) => role.display_name)
        .join(", ")

    // Presentation only, never authorization: the server independently
    // revalidates every add-role request regardless of what this list
    // offers (dnd_ai.commands.memberships.assign_membership_role).
    const heldRoleIds = new Set(
        member.roles.map((role) => role.role_id),
    )
    const rolesAvailableToAdd = assignableRoles.filter(
        (role) => !heldRoleIds.has(role.role_id),
    )

    return (
        <AccessWriteScopeContext.Provider value={writeScope}>
        <details
            className="access-member-card"
            open={disclosure.isCardOpen(membershipId)}
            onToggle={(event) => disclosure.setCardOpen(membershipId, event.currentTarget.open)}
        >
            <summary>
                <strong>{member.display_name}</strong>
                <span>{member.status_display_name}</span>
                {roleSummary !== "" && <span>{roleSummary}</span>}
                <span
                    className="access-member-card__indicator"
                    aria-hidden="true"
                />
            </summary>

            <div className="access-member-card__body">
                <section aria-labelledby={rolesHeadingId}>
                    <h3 id={rolesHeadingId}>Roles</h3>

                    {member.roles.length > 0 ? (
                        <ul>
                            {member.roles.map((role) => (
                                <li key={role.role_id}>
                                    {role.display_name}
                                    <MemberRoleEditor
                                        campaignId={campaignId}
                                        campaignName={campaignName}
                                        memberDisplayName={member.display_name}
                                        role={role}
                                        assignableRoles={assignableRoles}
                                        onChanged={onChanged}
                                        onMutationStart={onMutationStart}
                                    />
                                    <RevokeMemberRole
                                        campaignId={campaignId}
                                        memberDisplayName={member.display_name}
                                        role={role}
                                        onChanged={onChanged}
                                        onMutationStart={onMutationStart}
                                    />
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <p>No roles assigned.</p>
                    )}

                    <AddMemberRole
                        campaignId={campaignId}
                        campaignName={campaignName}
                        campaignMembershipId={member.campaign_membership_id}
                        memberDisplayName={member.display_name}
                        assignableRoles={rolesAvailableToAdd}
                        onChanged={onChanged}
                        onMutationStart={onMutationStart}
                    />
                </section>

                <section aria-labelledby={relationshipsHeadingId}>
                    <h3 id={relationshipsHeadingId}>
                        Character access
                    </h3>

                    {member.character_relationships.length > 0 ? (
                        <ul>
                            {member.character_relationships.map(
                                (relationship) => (
                                    <li
                                        key={
                                            relationship
                                                .membership_character_relationship_id
                                        }
                                    >
                                        {
                                            relationship.character_display_name
                                        }{" "}
                                        —{" "}
                                        {
                                            relationship.relationship_type_display_name
                                        }
                                        <CharacterRelationshipEditor
                                            campaignId={campaignId}
                                            campaignName={campaignName}
                                            memberDisplayName={
                                                member.display_name
                                            }
                                            relationship={relationship}
                                            assignableRelationshipTypes={
                                                assignableRelationshipTypes
                                            }
                                            onChanged={onChanged}
                                            onMutationStart={
                                                onMutationStart
                                            }
                                        />
                                        <RevokeCharacterRelationship
                                            campaignId={campaignId}
                                            memberDisplayName={
                                                member.display_name
                                            }
                                            relationship={relationship}
                                            onChanged={onChanged}
                                            onMutationStart={
                                                onMutationStart
                                            }
                                        />
                                    </li>
                                ),
                            )}
                        </ul>
                    ) : (
                        <p>No character access.</p>
                    )}

                    <AddCharacterRelationship
                        campaignId={campaignId}
                        campaignName={campaignName}
                        campaignMembershipId={
                            member.campaign_membership_id
                        }
                        memberDisplayName={member.display_name}
                        assignableCharacters={assignableCharacters}
                        preselectCharacterId={preselectCharacterId}
                        assignableRelationshipTypes={
                            assignableRelationshipTypes
                        }
                        existingRelationships={
                            member.character_relationships
                        }
                        onChanged={onChanged}
                        onMutationStart={onMutationStart}
                    />
                </section>

                <section aria-labelledby={grantsHeadingId}>
                    <h3 id={grantsHeadingId}>Direct resource access</h3>

                    {member.grants.length > 0 ? (
                        <ul>
                            {member.grants.map((grant) => (
                                <li key={grant.resource_grant_id}>
                                    <strong>
                                        {grant.capability_display_name}
                                    </strong>{" "}
                                    ({humanizeCode(grant.effect)}) on{" "}
                                    {grant.target_display_name ??
                                        humanizeCode(grant.target_type)}
                                    {grant.reason !== null &&
                                        ` · ${grant.reason}`}
                                    <RevokeResourceGrant
                                        campaignId={campaignId}
                                        memberDisplayName={
                                            member.display_name
                                        }
                                        grant={grant}
                                        onChanged={onChanged}
                                        onMutationStart={onMutationStart}
                                    />
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <p>No direct resource access.</p>
                    )}

                    <AddResourceGrant
                        campaignId={campaignId}
                        campaignName={campaignName}
                        campaignMembershipId={
                            member.campaign_membership_id
                        }
                        memberDisplayName={member.display_name}
                        assignableCharacters={assignableCharacters}
                        grantableCapabilities={
                            grantableResourceCapabilities
                        }
                        existingGrants={member.grants}
                        onChanged={onChanged}
                        onMutationStart={onMutationStart}
                    />
                </section>

                <section aria-labelledby={revelationsHeadingId}>
                    <h3 id={revelationsHeadingId}>Revealed characters</h3>

                    {(member.revelations ?? []).length > 0 ? (
                        <ul>
                            {(member.revelations ?? []).map((revelation, index) => (
                                <li
                                    key={`${revelation.character_id}:${revelation.audience_kind_code}:${index}`}
                                >
                                    {revelation.character_display_name} —{" "}
                                    {revelation.audience_kind_display_name}
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <p>No revealed characters.</p>
                    )}
                </section>

                <EffectiveAccessPanel
                    campaignId={campaignId}
                    campaignMembershipId={membershipId}
                    memberDisplayName={member.display_name}
                    isOpen={disclosure.isExplanationOpen(membershipId)}
                    onToggle={() => disclosure.toggleExplanation(membershipId)}
                    onRefresh={() => onRefreshAccess(membershipId)}
                />

                <p className="access-member-card__joined">
                    Joined {formatTimestamp(member.joined_at)}
                </p>

                <RemoveCampaignMember
                    campaignId={campaignId}
                    campaignMembershipId={
                        member.campaign_membership_id
                    }
                    memberUserId={member.user_id}
                    memberDisplayName={member.display_name}
                    onChanged={onChanged}
                    onMutationStart={onMutationStart}
                />
            </div>
        </details>
        </AccessWriteScopeContext.Provider>
    )
}

interface AccessGroupCardProps {
    group: AccessGroupSummary
    campaignId: string
    activeMembers: CampaignAccessMember[]
    assignableCharacters: AssignableCharacter[]
    grantableResourceCapabilities: GrantableResourceCapability[]
    onChanged: (message: string) => void
    onMutationStart: () => void
    // The caller is in this group (or is not known to be a member at all): a write to the group can change
    // the caller's own capabilities. Adding a member can, too, if the caller is one of the members offered.
    callerAffectedByGroup: boolean
    callerOfferedToAdd: boolean
}

// One card per access group (never nested inside a member card — a group
// is a campaign-level concept, distinct from any one member's own access).
// Mirrors MemberAccessCard's own <details>/<summary> panel language.
function AccessGroupCard({
    group,
    campaignId,
    activeMembers,
    assignableCharacters,
    grantableResourceCapabilities,
    onChanged,
    onMutationStart,
    callerAffectedByGroup,
    callerOfferedToAdd,
}: AccessGroupCardProps) {
    const groupScope = useMemo(() => ({ affectsCaller: callerAffectedByGroup }), [callerAffectedByGroup])
    const addMemberScope = useMemo(
        () => ({ affectsCaller: callerAffectedByGroup || callerOfferedToAdd }),
        [callerAffectedByGroup, callerOfferedToAdd],
    )
    const membersHeadingId = useId()
    const grantsHeadingId = useId()

    const isActive = group.status_code === "active"

    // Presentation only, never authorization: the server independently
    // revalidates every add-member request regardless of what this list
    // offers (dnd_ai.commands.access_groups.add_access_group_member).
    const groupMembershipIds = new Set(
        group.members.map((member) => member.campaign_membership_id),
    )
    const eligibleMembers = activeMembers
        .filter(
            (member) =>
                member.status_code === "active" &&
                member.account_is_active &&
                !groupMembershipIds.has(member.campaign_membership_id),
        )
        .map((member) => ({
            campaign_membership_id: member.campaign_membership_id,
            display_name: member.display_name,
        }))


    return (
        <AccessWriteScopeContext.Provider value={groupScope}>
        <details className="access-member-card">
            <summary>
                <strong>{group.name}</strong>
                <span>{group.status_display_name}</span>
                <span
                    className="access-member-card__indicator"
                    aria-hidden="true"
                />
            </summary>

            <div className="access-member-card__body">
                {group.description !== null && (
                    <p className="access-group-card__description">
                        {group.description}
                    </p>
                )}

                <div className="access-role-editor__actions">
                    {isActive ? (
                        <>
                            <EditAccessGroup
                                campaignId={campaignId}
                                accessGroupId={group.access_group_id}
                                currentName={group.name}
                                currentDescription={group.description}
                                onChanged={onChanged}
                                onMutationStart={onMutationStart}
                            />
                            <DeactivateAccessGroup
                                campaignId={campaignId}
                                accessGroupId={group.access_group_id}
                                groupName={group.name}
                                onChanged={onChanged}
                                onMutationStart={onMutationStart}
                            />
                        </>
                    ) : (
                        <ReactivateAccessGroup
                            campaignId={campaignId}
                            accessGroupId={group.access_group_id}
                            groupName={group.name}
                            onChanged={onChanged}
                            onMutationStart={onMutationStart}
                        />
                    )}
                </div>

                <section aria-labelledby={membersHeadingId}>
                    <h3 id={membersHeadingId}>Members</h3>

                    {group.members.length > 0 ? (
                        <ul>
                            {group.members.map((member) => (
                                <li key={member.access_group_membership_id}>
                                    {member.display_name}
                                    <RemoveAccessGroupMember
                                        campaignId={campaignId}
                                        accessGroupMembershipId={
                                            member.access_group_membership_id
                                        }
                                        memberDisplayName={member.display_name}
                                        groupName={group.name}
                                        onChanged={onChanged}
                                        onMutationStart={onMutationStart}
                                    />
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <p>No members in this group.</p>
                    )}

                    {isActive && (
                        <AccessWriteScopeContext.Provider value={addMemberScope}>
                            <AddAccessGroupMember
                                campaignId={campaignId}
                                accessGroupId={group.access_group_id}
                                groupName={group.name}
                                eligibleMembers={eligibleMembers}
                                onChanged={onChanged}
                                onMutationStart={onMutationStart}
                            />
                        </AccessWriteScopeContext.Provider>
                    )}
                </section>

                <section aria-labelledby={grantsHeadingId}>
                    <h3 id={grantsHeadingId}>Resource access</h3>

                    {group.grants.length > 0 ? (
                        <ul>
                            {group.grants.map((grant) => (
                                <li key={grant.resource_grant_id}>
                                    <strong>
                                        {grant.capability_display_name}
                                    </strong>{" "}
                                    ({humanizeCode(grant.effect)}) on{" "}
                                    {grant.target_display_name ??
                                        humanizeCode(grant.target_type)}
                                    <RevokeResourceGrant
                                        campaignId={campaignId}
                                        memberDisplayName={group.name}
                                        grant={grant}
                                        onChanged={onChanged}
                                        onMutationStart={onMutationStart}
                                    />
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <p>No resource access granted to this group.</p>
                    )}

                    {isActive && (
                        <AddGroupResourceGrant
                            campaignId={campaignId}
                            accessGroupId={group.access_group_id}
                            groupName={group.name}
                            assignableCharacters={assignableCharacters}
                            grantableCapabilities={grantableResourceCapabilities}
                            existingGrants={group.grants}
                            onChanged={onChanged}
                            onMutationStart={onMutationStart}
                        />
                    )}
                </section>
            </div>
        </details>
        </AccessWriteScopeContext.Provider>
    )
}

interface AccessPageProps {
    campaignId: string
    overview: CampaignAccessOverview
    // A character the relationship control starts on (from `?character=<id>` on
    // a player character's page); the server still validates everything.
    preselectCharacterId?: string | null
    onChanged: (message: string) => void
    onMutationStart: () => void
    // Which member cards and explanations are open, held above the overview boundary so they survive
    // a reload of this list. A page rendered without them (a test) keeps its own.
    disclosure?: AccessDisclosure
    // Reloads this list and every open explanation together, for the member whose control asked.
    onRefreshAccess?: (campaignMembershipId: string) => void
}

export function AccessPage({
    campaignId,
    overview,
    preselectCharacterId = null,
    onChanged,
    onMutationStart,
    disclosure: heldDisclosure,
    onRefreshAccess,
}: AccessPageProps) {
    const ownDisclosure = useAccessDisclosure(campaignId)
    const disclosure = heldDisclosure ?? ownDisclosure
    const refreshAccess = onRefreshAccess ?? (() => onChanged("Access information refreshed."))
    const { state: sessionState } = useSession()
    // Who the caller is among the members, to tell a write that can change their own authority from one
    // that cannot. Unknown (not listed) is treated as the caller being affected by every group.
    const callerUserId = sessionState.status === "authenticated" ? sessionState.bootstrap.user.user_id : null
    const callerMembership = overview.members.find((member) => member.user_id === callerUserId)
    const callerMembershipId = callerMembership?.campaign_membership_id ?? null
    const campaignName =
        sessionState.status === "authenticated"
            ? (sessionState.bootstrap.campaigns.find(
                  (campaign) =>
                      campaign.campaign_id === campaignId,
              )?.campaign_name ?? "this campaign")
            : "this campaign"

    return (
        <section aria-labelledby="access-heading">
            <h1 id="access-heading">Access</h1>

            <p className="access-page__description">
                Current members, roles, character access, and direct
                resource access for this campaign. Adding an existing
                account as a member, changing and removing an existing
                member's roles, adding/changing/revoking a member's
                character access, adding/revoking a member's direct
                resource access, and removing an existing member are
                available below; other access changes are not available
                here yet.
            </p>

            <AddCampaignMember
                campaignId={campaignId}
                campaignName={campaignName}
                assignableRoles={overview.assignable_roles}
                onChanged={onChanged}
                onMutationStart={onMutationStart}
            />

            {overview.members.length > 0 ? (
                <ul className="access-page__member-list">
                    {overview.members.map((member) => (
                        <li key={member.campaign_membership_id}>
                            <MemberAccessCard
                                member={member}
                                campaignId={campaignId}
                                campaignName={campaignName}
                                assignableRoles={
                                    overview.assignable_roles
                                }
                                assignableCharacters={
                                    overview.assignable_characters
                                }
                                assignableRelationshipTypes={
                                    overview.assignable_relationship_types
                                }
                                grantableResourceCapabilities={
                                    overview.grantable_resource_capabilities
                                }
                                preselectCharacterId={preselectCharacterId}
                                onChanged={onChanged}
                                onMutationStart={onMutationStart}
                                disclosure={disclosure}
                                onRefreshAccess={refreshAccess}
                                isCallerMember={member.user_id === callerUserId}
                            />
                        </li>
                    ))}
                </ul>
            ) : (
                <p>No campaign members are currently recorded.</p>
            )}

            <section
                aria-labelledby="access-groups-heading"
                className="access-page__groups"
            >
                <h2 id="access-groups-heading">Access groups</h2>

                <p className="access-page__description">
                    Named sets of members that can be granted resource
                    access together. Adding a member to a group, or granting
                    the group access to a character, does not create an
                    in-world party or reveal any in-world knowledge.
                </p>

                {/* A new group has no members: creating it cannot change the caller's authority. */}
                <AccessWriteScopeContext.Provider value={NOT_THE_CALLER}>
                    <CreateAccessGroup
                        campaignId={campaignId}
                        campaignName={campaignName}
                        onChanged={onChanged}
                        onMutationStart={onMutationStart}
                    />
                </AccessWriteScopeContext.Provider>

                {overview.access_groups.length > 0 ? (
                    <ul className="access-page__member-list">
                        {overview.access_groups.map((group) => (
                            <li key={group.access_group_id}>
                                <AccessGroupCard
                                    group={group}
                                    campaignId={campaignId}
                                    activeMembers={overview.members}
                                    assignableCharacters={
                                        overview.assignable_characters
                                    }
                                    grantableResourceCapabilities={
                                        overview.grantable_resource_capabilities
                                    }
                                    onChanged={onChanged}
                                    onMutationStart={onMutationStart}
                                    callerAffectedByGroup={
                                        callerMembershipId === null ||
                                        group.members.some(
                                            (groupMember) =>
                                                groupMember.campaign_membership_id === callerMembershipId,
                                        )
                                    }
                                    callerOfferedToAdd={
                                        callerMembership !== undefined &&
                                        callerMembership.status_code === "active" &&
                                        callerMembership.account_is_active
                                    }
                                />
                            </li>
                        ))}
                    </ul>
                ) : (
                    <p>No access groups exist yet for this campaign.</p>
                )}
            </section>
        </section>
    )
}
