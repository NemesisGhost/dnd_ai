import { fetchLocationParentOptions } from "../../api/locationAuthoring"
import type { LocationCategoryOption } from "../../types/locationAuthoring"
import { DESCRIPTION_MAX, NAME_MAX } from "../../utils/authoringValidation"
import { FIELD_IDS, applicableFields, statusDetail } from "../../utils/locationForm"
import type { LocationFormValues } from "../../utils/locationForm"
import { SelectField, TextAreaField, TextField } from "./fields"
import { ReferenceCombobox } from "./ReferenceCombobox"
import type { ReferenceOption } from "./ReferenceCombobox"

interface LocationFieldsProps {
    campaignId: string
    // Present when editing: the location is excluded from its own parent options
    // (with everything it contains) and the category is fixed.
    locationId: string | null
    categories: readonly LocationCategoryOption[]
    values: LocationFormValues
    onChange: (values: LocationFormValues) => void
    errorFor: (fieldId: string) => string | null
}

// The typed Location fields. Only the fields the chosen category carries are
// rendered, taken from the server's catalog (never hard-coded per category).
export function LocationFields({
    campaignId,
    locationId,
    categories,
    values,
    onChange,
    errorFor,
}: LocationFieldsProps) {
    const category = categories.find((c) => c.code === values.category)
    const applicable = applicableFields(category)
    const editing = locationId !== null

    async function searchParents(query: string, signal: AbortSignal): Promise<ReferenceOption[]> {
        const page = await fetchLocationParentOptions(campaignId, query, locationId, signal)
        return page.items.map((item) => ({
            id: item.location_id,
            label: item.name,
            detail: `${item.category.label}, ${statusDetail(item.canon_status, "active")}`,
        }))
    }

    return (
        <>
            {editing ? (
                <div className="authoring-field">
                    <span className="authoring-field__label">Category</span>
                    <p id={FIELD_IDS.category}>{category?.label ?? values.category}</p>
                    <p className="authoring-field__hint">
                        A location&apos;s category cannot change. To change it, create a replacement
                        and supersede this one.
                    </p>
                </div>
            ) : (
                <SelectField
                    id={FIELD_IDS.category}
                    label="Category"
                    value={values.category}
                    placeholder="Choose a category"
                    required
                    options={categories.map((c) => ({ value: c.code, label: c.label }))}
                    error={errorFor(FIELD_IDS.category)}
                    onChange={(next) => {
                        const nextCategory = categories.find((c) => c.code === next)
                        const keep = applicableFields(nextCategory)
                        onChange({
                            ...values,
                            category: next,
                            population: keep.has("population") ? values.population : "",
                            buildingUse: keep.has("building_use") ? values.buildingUse : "",
                        })
                    }}
                />
            )}
            <TextField
                id={FIELD_IDS.name}
                label="Name"
                value={values.name}
                onChange={(name) => onChange({ ...values, name })}
                required
                maxLength={NAME_MAX}
                error={errorFor(FIELD_IDS.name)}
            />
            <TextAreaField
                id={FIELD_IDS.summary}
                label="Summary"
                value={values.summary}
                onChange={(summary) => onChange({ ...values, summary })}
                maxLength={DESCRIPTION_MAX}
                error={errorFor(FIELD_IDS.summary)}
            />
            <ReferenceCombobox
                id={FIELD_IDS.parent}
                label="Contained in"
                hint="The larger place this location sits within. Leave empty for a top-level place."
                value={values.parent}
                onChange={(parent) => onChange({ ...values, parent })}
                search={searchParents}
                error={errorFor(FIELD_IDS.parent)}
                placeholder="Search locations"
            />
            {applicable.has("population") ? (
                <TextField
                    id={FIELD_IDS.population}
                    label="Population"
                    value={values.population}
                    onChange={(population) => onChange({ ...values, population })}
                    hint="A whole number. Leave empty if unknown."
                    error={errorFor(FIELD_IDS.population)}
                />
            ) : null}
            {applicable.has("building_use") ? (
                <TextField
                    id={FIELD_IDS.buildingUse}
                    label="Use"
                    value={values.buildingUse}
                    onChange={(buildingUse) => onChange({ ...values, buildingUse })}
                    hint="What the building is used for, for example tavern or temple."
                    maxLength={200}
                    error={errorFor(FIELD_IDS.buildingUse)}
                />
            ) : null}
        </>
    )
}
