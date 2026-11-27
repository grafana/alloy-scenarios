-- Synthetic session. Passing an epoch lets the same example exercise a live Loki time range.
H.now = tonumber(os.getenv("ALLOYROUTE_TEST_EPOCH")) or 1790000000
H.character({
    name = "AlloyGearDemo", guid = "Player-Test-Gear", regionId = 3, realm = "Fixture",
    raceFile = "Human", classFile = "WARRIOR", faction = "Alliance", level = 10,
    map = 10, zone = "Test zone", x = 0.5, y = 0.5,
})
local gear = { [5] = { id = 1001, name = "Training Vest", guid = "A" } }
local total = 42
function UnitArmor() return 40, total end
function GetInventoryItemID(_, slot) return gear[slot] and gear[slot].id end
function GetInventoryItemLink(_, slot)
    local item = gear[slot]
    return item and "|Hitem:" .. item.id .. "|h[" .. item.name .. "]|h"
end
function GetInventoryItemTexture(_, slot) return gear[slot] and 1 end
ItemLocation = { CreateFromEquipmentSlot = function(_, slot) return slot end }
C_Item = { GetItemGUID = function(slot) return gear[slot].guid end }
H.slash("start")
H.advance(60)
gear[5] = { id = 1002, name = "Reinforced Vest", guid = "B" }
total = 55
H.fire("PLAYER_EQUIPMENT_CHANGED", 5, true)
H.fire("PLAYER_EQUIPMENT_CHANGED", 5, true)
H.advance(40)
total = SECRET
H.fire("UNIT_STATS", "player")
H.advance(20)
total = 60
H.fire("UNIT_RESISTANCES", "player")
H.advance(60)
gear[5], total = nil, 20
H.fire("PLAYER_EQUIPMENT_CHANGED", 5, false)
H.advance(30)
H.logout()
