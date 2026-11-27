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
local objective, faction, skill, profession = nil, 100, 4, 1
C_QuestLog.GetNumQuestLogEntries = function() return objective and 1 or 0 end
C_QuestLog.GetInfo = function() return {questID=380} end
C_QuestLog.GetQuestObjectives = function()
    return {{text="Night web spiders", numFulfilled=objective, numRequired=2, finished=objective==2}}
end
C_Reputation = {
    GetNumFactions=function() return 1 end,
    GetFactionDataByIndex=function() return {name="Undercity", factionID=68, currentStanding=faction, reaction=4, isHeader=false} end,
}
C_SkillInfo = {
    GetNumSkillLines=function() return 2 end,
    GetSkillLineInfo=function(i)
        if i==1 then return {name="Staves", skillID=136, skillLineCategoryID=6, rank=skill, maxRank=50, isHeader=false} end
        return {name="Herbalism", skillID=182, skillLineCategoryID=11, rank=profession, maxRank=75, isHeader=false}
    end,
}
LOOT_ITEM_SELF, LOOT_ITEM_SELF_MULTIPLE = "You receive loot: %s.", "You receive loot: %sx%d."
function GetSubZoneText() return S.subzone end
function UnitIsDeadOrGhost() return S.dead or false end
local exists, guid, name = UnitExists, UnitGUID, UnitName
function UnitExists(unit) return (unit=="target" and fighting) or exists(unit) end
function UnitGUID(unit) if unit=="target" and fighting then return "Creature-0-0-0-0-1500-1" end return guid(unit) end
function UnitName(unit) if unit=="target" and fighting then return "Young Night Web Spider" end return name(unit) end
local function sample(r)
    local previous = S.level
    if previous then H.advance(r.minute == 35.5 and 25 or 30) end
    S.subzone=r.place
    H.fire("ZONE_CHANGED")
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
        H.fire("PLAYER_TARGET_CHANGED")
        H.fire(fighting and "PLAYER_REGEN_DISABLED" or "PLAYER_REGEN_ENABLED")
    end
    if r.minute == 25 or r.minute == 32 or r.minute == 37 then
        objective = r.minute == 25 and 0 or (r.minute == 32 and 1 or 2)
        H.fire("QUEST_LOG_UPDATE")
        H.fire("QUEST_LOG_UPDATE")
    end
    if r.minute == 33 or r.minute == 34 then
        fighting = r.minute == 34
        H.fire(fighting and "PLAYER_REGEN_DISABLED" or "PLAYER_REGEN_ENABLED")
    end
    if r.minute == 35 then H.reload() end
    if r.minute == 37 then
        skill = skill+1
        H.fire("SKILL_LINES_CHANGED")
        H.fire("CHAT_MSG_LOOT","You receive loot: |Hitem:1005|h[Training Robe 5]|h.")
    end
    if r.minute == 45 then
        faction = faction+50
        H.fire("UPDATE_FACTION")
        objective=nil
        H.fire("QUEST_LOG_UPDATE")
    end
    if r.minute == 78 then profession = profession+1; H.fire("SKILL_LINES_CHANGED") end
    if r.minute == 80 or r.minute == 81 then
        S.dead = r.minute == 80
        H.fire(S.dead and "PLAYER_DEAD" or "PLAYER_UNGHOST")
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
