-- Sample data is appended by simulate.py. Normal addon events create the recording.
H.now = assert(tonumber(os.getenv("ALLOYROUTE_TEST_EPOCH")))
H.character({name="Vesper Ashvale", guid="Player-Fixture-Vesper", realm="Fixture", regionId=3,
    raceFile="Scourge", classFile="PRIEST", faction="Horde", map=1420, zone="Tirisfal Glades",
    powerType=0, powerToken="MANA"})
local S, vest, totalArmor = H.state, 0, 0
function UnitArmor() return totalArmor, totalArmor end
function GetInventoryItemID(_, slot) if slot == 5 and vest > 0 then return 1000 + vest end end
function GetInventoryItemTexture(_, slot) return GetInventoryItemID("player", slot) end
function GetInventoryItemLink(_, slot)
    local id = GetInventoryItemID("player", slot)
    if id then return "|Hitem:" .. id .. "|h[Training Robe " .. vest .. "]|h" end
end
local fighting = false
function UnitAffectingCombat() return fighting end
local function sample(r)
    local previous = S.level
    if previous then H.advance(30) end
    S.level, S.xp, S.xpMax = r.level, r.xp, r.next_xp
    S.hp, S.hpMax, S.power, S.powerMax = r.hp, r.max_hp, r.mana, r.max_mana
    S.money, S.x, S.y = r.copper, r.x / 100, r.y / 100
    if r.level ~= previous then
        vest, totalArmor = r.level, 12 + r.level * 7
        if previous then
            H.fire("PLAYER_EQUIPMENT_CHANGED", 5, true)
            H.fire("PLAYER_LEVEL_UP", r.level)
        else
            H.slash("start")
        end
    end
    if fighting ~= (r.activity == "Fighting") then
        fighting = not fighting
        H.fire(fighting and "PLAYER_REGEN_DISABLED" or "PLAYER_REGEN_ENABLED")
    end
    if r.quest_id and r.quest_id > 0 and (r.complete or r.event:match("^Accepted ") or r.minute == 0) then
        S.npc = {name=r.who, guid="Creature-0-0-0-0-100-1"}
        local title = r.minute == 0 and "Rude Awakening" or r.event:gsub("^Accepted ", "")
        S.window, S.questLog = {id=r.quest_id, title=title}, {[r.quest_id]=title}
        H.fire("QUEST_DETAIL")
        if r.complete then H.fire("QUEST_TURNED_IN", r.quest_id) else H.fire("QUEST_ACCEPTED", r.quest_id) end
        H.fire("QUEST_FINISHED")
    end
end
