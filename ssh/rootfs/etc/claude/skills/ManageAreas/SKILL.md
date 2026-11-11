---
name: ManageAreas
description: Areas, floors and labels through ha-areas. USE WHEN the user asks which floors or labels exist, what is in an area, on a floor or carries a label, or wants an area, floor or label created, renamed, changed (icon, colour, floor, aliases) or deleted. NOT FOR putting an entity or device into an area or labelling it (UpdateEntity, `ha-entities update`), or listing the entities of an area (FindEntities).
---

# ManageAreas

`ha-areas` lists, creates, renames and deletes areas, floors and labels through Home Assistant's registry API, which applies changes live. It is on `PATH`. Never write `.storage` for this, and never send these through `ha-service`.

Putting things into them is `ha-entities update` (UpdateEntity): `--area` for an entity or device, `--add-label`/`--remove-label` for one or several entities or devices.

## Commands

```bash
ha-areas list [areas|floors|labels]
ha-areas show <area|floor|label> <name|id>
ha-areas create area  <name> [--floor F] [--icon I] [--alias A ...] [--label L ...]
ha-areas create floor <name> [--level N] [--icon I] [--alias A ...]
ha-areas create label <name> [--color C] [--icon I] [--description D]
ha-areas update area  <name|id> [--name N] [--no-keep-alias] [--icon I | --no-icon]
                      [--floor F | --no-floor] [--add-alias A] [--remove-alias A]
                      [--add-label L] [--remove-label L] [--dry-run]
ha-areas update floor <name|id> [--name N] [--no-keep-alias] [--icon I | --no-icon]
                      [--level N] [--add-alias A] [--remove-alias A] [--dry-run]
ha-areas update label <name|id> [--name N] [--icon I | --no-icon]
                      [--color C] [--description D] [--dry-run]
ha-areas delete <area|floor|label> <name|id> [--dry-run]
```

Output is YAML by default (`--format json` after the kind for JSON). Wherever a name or id is expected, any of them works, with case and spaces ignored the way Home Assistant compares names; area and floor aliases count too. An unknown one errors with the existing names and nothing is sent.

## Examples

```bash
# "Create a Guest Room on the first floor"
ha-areas list floors
ha-areas create area "Guest Room" --floor "First Floor" --icon mdi:bed

# "Label the hallway lights 'night'": find them, then one call
ha-entities list --area Hallway --domain light
ha-entities update light.hallway_ceiling light.hallway_spots --add-label Night

# A new label, then what carries it
ha-areas create label Night --color indigo --icon mdi:weather-night
ha-areas show label Night

# "Delete the Storage area": preview, show the user, then delete
ha-areas delete area Storage --dry-run
ha-areas delete area Storage
```

## Workflow

1. **Check before creating.** `ha-areas list` first: the user's "Guest Room" may already exist as "Guestroom" or as an alias. `create` refuses a name Home Assistant would treat as the same (case and spaces ignored; a hyphen makes it different) and a floor or label that doesn't exist.
2. **Ids.** Home Assistant makes the id from the name at creation (`Guest Room` → `guest_room`, `Büro` → `buro`, `_2` if taken) and never changes it. Use the id the output prints, never one you predicted.
3. **Renaming** keeps the id, so automations and dashboards that target the id keep working. Templates that look an area or floor up by name (`area_entities('Kitchen')`) would break, so the old name stays as an alias and they keep finding it; `notes` says so, and `templates_using_old_name` lists them. `--no-keep-alias` only when the user wants the old name gone, and then fix the listed templates. Labels have no aliases: after a label rename, update the listed templates to the new name or the id.
4. **Deleting** always goes `--dry-run` first, and the user sees what it reports before the real run. A real delete asks the user through the add-on's hook; `--dry-run` doesn't. The preview has:
   - `members`: what loses it (devices and entities in the area, `entities_via_device` among them; areas on the floor; entities, devices and areas with the label).
   - `targets`: config that names it (`area_id:`, `floor_id:`, `label_id:`, dashboard area cards, template calls). These stop doing anything after the delete, with no error. Offer to fix them.
   - `related`: automations, scripts and scenes Home Assistant relates to it, mostly because they use something inside it. They keep working.

   Re-creating the same name gives back the same id if it is free, so `targets` work again, but the memberships are gone for good.

## Gotchas

- `update` changes aliases and labels one at a time; everything else the area or floor had stays. `changes` shows each field before and after, `verified: false` (exit 1) means the read-back differed.
- Label colours: `#RRGGBB` or a theme name (`red`, `indigo`, `light-blue`, `blue-grey`, ...); the error lists all 26. Icons need their prefix (`mdi:sofa`).
- Floor `--level` is an integer: 0 ground, 1 first, -1 basement. `list` sorts floors by it.
- Assigning an area is `ha-entities update --area`, also for devices (`--device`). An entity with its own area ignores its device's; `show area` lists those under `entities`, inherited ones under `entities_via_device`.
- Categories (the folders for automations, scripts and helpers in the UI) are a different thing and not covered; they stay in the UI.
- Writes need an administrator's token; `list` and `show` work without one.
