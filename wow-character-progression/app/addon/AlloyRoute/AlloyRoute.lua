-- Azeroth Chronicle v2: records the logged-in character's session for later export.
-- The saved string uses ASCII delimiters and percent-encoded UTF-8 text, so
-- readers never need to evaluate Lua. companion/FORMAT.md documents every row.
local MAX_ROWS, MAX_BYTES = 4096, 1000000
local FOOTER_RESERVE = 32 -- ";e|<10-digit time>|<row count>" plus margin
local TICK_SECONDS = 10
local regions = { [1] = "us", [2] = "kr", [3] = "eu", [4] = "tw", [5] = "cn" }

local pending = {}     -- rows written this UI session, joined into the save at logout
local pendingBytes = 0 -- bytes those rows add to the saved string, separators included
local savedBytes, savedRows = 0, 0
local loadedRows = 0 -- rows already written to disk before this UI session
local segment          -- the active recording segment, or nil
local timer, lastZone, lastBody, reminder, exportRequested = nil, nil, nil, 0, false
local full = false -- the last segment stopped because the next row did not fit
local openNpc, lastNpcKey, lastNpcAt = nil, nil, 0
local quests, recent = {}, {}
local interactionNames = {}

local function say(message)
    print("|cffe7c58bAzeroth Chronicle|r " .. message)
end

-- Restricted values are secret on this client; never compare or concatenate them.
local function readable(value)
    return not (issecretvalue and issecretvalue(value)) and value ~= nil
end

local function text(value)
    if not readable(value) or type(value) ~= "string" or value == "" then return "" end
    if #value > 200 then
        local boundary = 201
        while value:byte(boundary) and value:byte(boundary) >= 128 and value:byte(boundary) < 192 do
            boundary = boundary - 1
        end
        value = value:sub(1, boundary - 1)
    end
    value = value:gsub("[%c]", " ")
    return (value:gsub("([^A-Za-z0-9_.%-])", function(byte)
        return string.format("%%%02X", string.byte(byte))
    end))
end

local function int(value)
    if not readable(value) or type(value) ~= "number" or value ~= value then return "" end
    return string.format("%.0f", value)
end

local function usedBytes()
    return savedBytes + pendingBytes
end

local function usedRows()
    return savedRows + (segment and segment.count or 0)
end

-- Visible while this character has a recording to save or export.
local panel = CreateFrame("Frame", nil, UIParent)
panel:SetSize(237, 68)
panel:SetPoint("LEFT", UIParent, "LEFT", 12, 0)
panel:SetClampedToScreen(true)
panel:SetMovable(true)
panel:EnableMouse(true)
panel:RegisterForDrag("LeftButton")
panel:SetScript("OnDragStart", function(self) self:StartMoving() end)
panel:SetScript("OnDragStop", function(self)
    self:StopMovingOrSizing()
    AlloyRoutePanelPosition = { self:GetLeft() / UIParent:GetWidth(), self:GetBottom() / UIParent:GetHeight() }
end)
local background = panel:CreateTexture(nil, "BACKGROUND")
background:SetAllPoints()
background:SetColorTexture(0.13, 0.095, 0.06, 0.92)
local brass = panel:CreateTexture(nil, "BORDER")
brass:SetPoint("TOPLEFT")
brass:SetPoint("TOPRIGHT")
brass:SetHeight(2)
brass:SetColorTexture(0.76, 0.59, 0.31, 1)
local title = panel:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
title:SetPoint("TOPLEFT", 8, -5)
local details = panel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
details:SetPoint("TOPLEFT", 8, -22)
local save = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
save:SetSize(113, 22)
save:SetPoint("BOTTOMLEFT", 5, 3)
local clear = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
clear:SetSize(88, 22)
clear:SetPoint("BOTTOMRIGHT", -5, 3)
clear:SetText("Clear…")
-- A paused older save needs both normal start and explicit export actions.
local resume = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
resume:SetSize(92, 22)
resume:SetPoint("LEFT", save, "RIGHT", 2, 0)
resume:SetText("Start recording")
resume:Hide()
resume:SetEnabled(false)
panel:Hide()

-- Only the saved buffer covered by an explicit Save & Reload is eligible.
local function canClearSaved()
    return savedBytes > 0 and AlloyRouteExportedBytes == savedBytes
end

local function needsExport()
    return segment or #pending > 0 or (savedBytes > 0 and not canClearSaved())
end

local function refreshPanel()
    local rows, bytes = usedRows(), usedBytes()
    local fraction = math.max(rows / MAX_ROWS, bytes / MAX_BYTES)
    local stage = 0
    if fraction >= 1 or full then
        stage = 3
    elseif fraction >= 0.8 then
        stage = 2
    elseif rows >= 500 or bytes >= 100000 then
        stage = 1
    end
    if stage > reminder then
        reminder = stage
        if stage == 3 then
            say("Recording full. Recording stopped. Click Save & Reload to write it to disk.")
        elseif stage == 2 then
            say("Recording is at least 80% full. Click Save & Reload when convenient.")
        else
            say("You have a sizeable recording. Click Save & Reload when convenient.")
        end
    end
    local state = segment and "Recording" or (#pending > 0 and "Ready to save" or "Paused")
    if stage == 3 then state = "Full" end
    title:SetText("Azeroth Chronicle - " .. state)
    local percent = math.min(100, math.floor(fraction * 100))
    local unit = rows == 1 and "row" or "rows"
    local usage = string.format("%d %s  ·  %.1f KiB  ·  %d%% full", rows, unit, bytes / 1024, percent)
    if exportRequested then usage = "If still here, type /reload to save." end
    details:SetText(usage)
    if stage >= 2 then details:SetTextColor(1, 0.72, 0.25) else details:SetTextColor(1, 1, 1) end
    save:SetText(needsExport() and "Save & Reload" or "Start recording")
    local pausedWithUnexportedSave = not segment and #pending == 0 and savedBytes > 0 and not canClearSaved()
    if pausedWithUnexportedSave then
        panel:SetWidth(309)
        resume:Show()
    else
        panel:SetWidth(237)
        resume:Hide()
    end
    resume:SetEnabled(pausedWithUnexportedSave)
    clear:SetEnabled(canClearSaved())
    panel:Show()
end

-- Appends one row if it fits. Data rows count toward MAX_ROWS; every row
-- leaves room for the footer so a full recording can still be closed.
local function append(row, isData)
    local cost = #row + 1
    if isData and usedRows() + 1 > MAX_ROWS then return false end
    if usedBytes() + cost + FOOTER_RESERVE > MAX_BYTES then return false end
    pending[#pending + 1] = row
    pendingBytes = pendingBytes + cost
    return true
end

local finish

local function record(kind, ...)
    if not segment or segment.full then return false end
    segment.seq = segment.seq + 1
    local fields = { kind, int(GetServerTime()), int(segment.seq), ... }
    if not append(table.concat(fields, "|"), true) then
        segment.seq = segment.seq - 1
        segment.full, full = true, true
        finish()
        return false
    end
    segment.count = segment.count + 1
    refreshPanel()
    return true
end

-- Slot IDs follow WoW's equipped inventory slots, excluding bags.
local slots = { "Head", "Neck", "Shoulders", "Shirt", "Chest", "Waist", "Legs", "Feet",
    "Wrists", "Hands", "Ring 1", "Ring 2", "Trinket 1", "Trinket 2", "Back",
    "Main hand", "Off hand", "Ranged", "Tabard" }

local function equipped(slot, hasCurrent)
    local id = GetInventoryItemID("player", slot)
    if issecretvalue and issecretvalue(id) then return nil end
    if not id then
        local texture = GetInventoryItemTexture("player", slot)
        if (issecretvalue and (issecretvalue(texture) or issecretvalue(hasCurrent))) or hasCurrent or texture then
            return nil
        end
        return { id = 0, name = "Empty" }
    end
    local link = GetInventoryItemLink("player", slot)
    if not readable(link) then link = "" end
    local name = link:match("%[(.-)%]") or ("Item #" .. id)
    local guid
    if C_Item and C_Item.GetItemGUID and ItemLocation then
        guid = C_Item.GetItemGUID(ItemLocation:CreateFromEquipmentSlot(slot))
        if not readable(guid) then guid = nil end
    end
    return { id = id, name = name, guid = guid }
end

local function gearFields(item)
    return int(item and item.id) .. "|" .. text(item and item.name or "Unavailable")
end

local function gearChange(slot, hasCurrent)
    if not segment.gear or not readable(slot) or not slots[slot] then return end
    local item = equipped(slot, hasCurrent)
    if not item then
        segment.retryGear[slot] = readable(hasCurrent) and hasCurrent or false
        return
    end
    segment.retryGear[slot] = nil
    local old = segment.gear[slot]
    segment.gear[slot] = item
    if old and item.id == old.id and not (old.guid and item.guid and old.guid ~= item.guid) then return end
    record("c", text(slots[slot]), gearFields(old), gearFields(item))
end

local function armor(force)
    if not segment or not UnitArmor then return end
    local _, effective = UnitArmor("player")
    if not readable(effective) then return end
    local now = GetServerTime()
    if effective ~= segment.armor or (force and now ~= segment.armorAt) then
        segment.armor, segment.armorAt = effective, now
        record("a", int(effective))
    end
end

local function place()
    local map = C_Map.GetBestMapForUnit("player")
    if not readable(map) then map = nil end
    local zone = GetRealZoneText()
    if not readable(zone) or zone == "" then zone = nil end
    local x, y
    if map then
        local position = C_Map.GetPlayerMapPosition(map, "player")
        if readable(position) and position then
            local px, py = position:GetXY()
            if readable(px) and readable(py) and px >= 0 and px <= 1 and py >= 0 and py <= 1 then
                -- Hundredths of a map percent, stored as locale-independent integers.
                x, y = math.floor(px * 10000 + 0.5), math.floor(py * 10000 + 0.5)
            end
        end
    end
    return map, zone, x, y
end

-- One measured snapshot. Unchanged ticks are skipped; forced snapshots are not.
local function snapshot(force, levelOverride)
    if not segment then return end
    armor(force)
    if not segment then return end
    local map, zone, x, y = place()
    local zoneKey = int(map) .. "|" .. text(zone)
    if (map or zone) and zoneKey ~= lastZone then
        if lastZone then record("z", int(map), text(zone)) end
        lastZone = zoneKey
        force = true
    end
    local powerType, powerToken = UnitPowerType("player")
    -- Addon code may not pass a secret value back into the API.
    if not readable(powerType) then powerType, powerToken = nil, nil end
    local level = levelOverride or UnitLevel("player")
    local body = table.concat({
        int(level), int(UnitXP("player")), int(UnitXPMax("player")),
        int(UnitHealth("player")), int(UnitHealthMax("player")),
        int(powerType), text(powerToken), int(UnitPower("player", powerType)),
        int(UnitPowerMax("player", powerType)), int(GetMoney()),
        int(map), text(zone), int(x), int(y),
    }, "|")
    if not force and body == lastBody then return end
    lastBody = body
    record("s", body)
end

finish = function()
    if not segment then return end
    if timer then
        timer:Cancel()
        timer = nil
    end
    -- The footer always fits: append() kept FOOTER_RESERVE bytes free.
    local footer = "e|" .. int(GetServerTime()) .. "|" .. segment.count
    pending[#pending + 1] = footer
    pendingBytes = pendingBytes + #footer + 1
    savedRows = savedRows + segment.count
    segment = nil
    refreshPanel()
end

local function commit()
    if #pending == 0 then return end
    local prior = AlloyRouteRecording
    if prior and prior ~= "" then
        AlloyRouteRecording = prior .. ";" .. table.concat(pending, ";")
    else
        AlloyRouteRecording = table.concat(pending, ";")
    end
    pending, pendingBytes = {}, 0
end

-- A boundary records player combat state and the position exposed by the client.
local function combat(active, initial)
    if not segment or segment.inCombat == active then return end
    segment.inCombat = active
    local map, zone, x, y = place()
    local state = initial and (active and "already_active" or "idle") or (active and "entered" or "left")
    record("f", state, int(map), text(zone), int(x), int(y))
end

-- Record readable observations once per change. Every new segment starts with baselines.
local function observe(kind, key, ...)
    if not segment then return end
    local body = table.concat({...}, "|")
    local previous = segment.observations[key]
    if body == previous then return end
    segment.observations[key] = body
    record(kind, previous and "change" or "baseline", body)
end

local function questObjectives(index, id)
    if C_QuestLog and C_QuestLog.GetQuestObjectives then
        local items = C_QuestLog.GetQuestObjectives(id)
        if readable(items) then return items end
    end
    if not (GetNumQuestLeaderBoards and GetQuestLogLeaderBoard) then return end
    local count = GetNumQuestLeaderBoards(index)
    if not readable(count) then return end
    local items = {}
    for j = 1, count do
        local label, _, done = GetQuestLogLeaderBoard(j, index)
        if readable(label) then
            local have, need = label:match("(%d+)%s*/%s*(%d+)")
            items[j] = {text=label, finished=done, numFulfilled=tonumber(have), numRequired=tonumber(need)}
        end
    end
    return items
end

local function objectives()
    local modern = C_QuestLog and C_QuestLog.GetNumQuestLogEntries and C_QuestLog.GetInfo
    if not modern and not (GetNumQuestLogEntries and GetQuestLogTitle) then return end
    local count
    if modern then count = C_QuestLog.GetNumQuestLogEntries() else count = GetNumQuestLogEntries() end
    if not readable(count) then return end
    local present = {}
    for i = 1, count do
        local id
        if modern then
            local info = C_QuestLog.GetInfo(i)
            if readable(info) then id = info.questID end
        else
            id = select(8, GetQuestLogTitle(i))
        end
        if readable(id) and id > 0 then
            local items = questObjectives(i, id)
            if readable(items) then
                for index, obj in ipairs(items) do
                    if readable(obj) then
                        local key = "q/" .. id .. "/" .. index
                        present[key] = true
                        local done = readable(obj.finished) and (obj.finished and "1" or "0") or ""
                        if done ~= "" or int(obj.numFulfilled) ~= "" then
                            observe("o", key, int(id), int(index), text(obj.text), int(obj.numFulfilled),
                                int(obj.numRequired), done)
                        end
                    end
                end
            end
        end
    end
    if segment then
        for key in pairs(segment.observations) do
            if key:sub(1,2) == "q/" and not present[key] then segment.observations[key] = nil end
        end
    end
end

local function ranks()
    if C_SkillInfo and C_SkillInfo.GetNumSkillLines and C_SkillInfo.GetSkillLineInfo then
        local count = C_SkillInfo.GetNumSkillLines()
        for i = 1, readable(count) and count or 0 do
            local r = C_SkillInfo.GetSkillLineInfo(i)
            if readable(r) and readable(r.isHeader) and not r.isHeader and readable(r.skillID)
                    and readable(r.rank) then
                local category = readable(r.skillLineCategoryID) and r.skillLineCategoryID
                -- SkillLineCategory 9 and 11 are primary and secondary professions.
                local kind = (category == 9 or category == 11) and "profession" or "skill"
                observe("k", "s/" .. r.skillID, kind, int(r.skillID), text(r.name), int(r.rank), int(r.maxRank))
            end
        end
    end
end

local function reputation()
    if not (C_Reputation and C_Reputation.GetNumFactions and C_Reputation.GetFactionDataByIndex) then return end
    local count = C_Reputation.GetNumFactions()
    for i = 1, readable(count) and count or 0 do
        local r = C_Reputation.GetFactionDataByIndex(i)
        if readable(r) and readable(r.factionID) and r.factionID > 0 and readable(r.currentStanding)
                and readable(r.isHeader) and (not r.isHeader or (readable(r.isHeaderWithRep) and r.isHeaderWithRep)) then
            observe("r", "r/" .. r.factionID, int(r.factionID), text(r.name), int(r.currentStanding), int(r.reaction))
        end
    end
end

local function subzone()
    if not segment then return end
    local name = GetSubZoneText and GetSubZoneText()
    if readable(name) then observe("u", "subzone", text(name)) end
end

local function target()
    if not segment then return end
    if not UnitExists("target") then segment.observations.target = nil; return end
    local guid = UnitGUID("target")
    if not readable(guid) then return end
    local kind, _, _, _, _, id = strsplit("-", guid)
    if kind == "Creature" or kind == "Vehicle" then
        observe("t", "target", text(kind), int(tonumber(id)), text(UnitName("target")))
    else
        segment.observations.target = nil
    end
end

local function life()
    local dead = UnitIsDeadOrGhost and UnitIsDeadOrGhost("player")
    if readable(dead) then observe("d", "life", dead and "dead" or "alive") end
end

-- Localised self-loot messages confirm receipt. Other players' chat never enters the save.
local function loot(message, lineID)
    if not readable(message) then return end
    local id, name = message:match("|Hitem:(%d+)[^|]*|h%[(.-)%]|h")
    if not id then return end
    for _, template in ipairs({LOOT_ITEM_SELF_MULTIPLE or "", LOOT_ITEM_SELF or ""}) do
        local pattern = template:gsub("([^%w])", "%%%1")
        pattern = pattern:gsub("%%%%s", ".-"):gsub("%%%%d", "(%%d+)")
        local match = message:match("^" .. pattern .. "$")
        if match then
            local line = int(lineID)
            if line ~= "" and segment.lootLine == line then return end
            segment.lootLine = line
            record("i", id, text(name), int(tonumber(match) or 1))
            return
        end
    end
end

local function start()
    if segment then return say("Already recording.") end
    local saved = AlloyRouteRecording
    if saved and saved ~= "" and saved:sub(1, 3) ~= "v2|" then
        return say("This character has an older v1 route. Import it, then use /chronicle clear.")
    end
    local name = UnitName("player")
    local region = regions[GetCurrentRegion()]
    local guid = UnitGUID("player")
    local realm = GetNormalizedRealmName and GetNormalizedRealmName() or nil
    if not readable(realm) or realm == "" then realm = GetRealmName() end
    if not readable(name) or name == "" or not region or not readable(guid) or not readable(realm) then
        return say("Character identity unavailable. Try again after entering the world.")
    end
    local now = GetServerTime()
    local version, build = GetBuildInfo()
    local _, raceFile, raceId = UnitRace("player")
    local _, classFile, classId = UnitClass("player")
    local faction = UnitFactionGroup("player")
    local id = string.format("%x%04x", now, math.random(0, 65535))
    local header = table.concat({
        "v2", id, int(now), text(version .. "." .. build), region, text(realm), text(name),
        text(guid), text(raceFile), int(raceId), text(classFile), int(classId), text(faction),
    }, "|")
    -- Reserve the entire starting loadout before opening a session near the cap.
    local gear, baseline = {}, {}
    local requiredBytes = #header + 1 + 400 + FOOTER_RESERVE
    if GetInventoryItemID then
        for slot, label in ipairs(slots) do
            gear[slot] = equipped(slot)
            baseline[slot] = text(label) .. "|" .. gearFields(gear[slot])
            requiredBytes = requiredBytes + #baseline[slot] + 24
        end
    end
    if usedRows() + #baseline + 3 > MAX_ROWS or usedBytes() + requiredBytes > MAX_BYTES then
        full = true
        refreshPanel()
        return say("This character's recording is full. Export it, then use /chronicle clear.")
    end
    AlloyRouteAutoRecord = true
    append(header, false)
    segment = { id = id, seq = 0, count = 0, gear = GetInventoryItemID and gear, retryGear = {}, observations = {} }
    lastZone, lastBody, reminder, exportRequested, full = nil, nil, 0, false, false
    for slot, body in ipairs(baseline) do
        if not gear[slot] then segment.retryGear[slot] = false end
        record("b", body)
    end
    snapshot(true)
    if UnitAffectingCombat then
        local active = UnitAffectingCombat("player")
        if readable(active) then combat(active, true) end
    end
    if not segment then return end
    objectives(); ranks(); reputation(); subzone(); life(); target()
    if not segment then return end
    timer = C_Timer.NewTicker(TICK_SECONDS, function()
        if not segment then return end
        for slot, hasCurrent in pairs(segment.retryGear) do
            gearChange(slot, hasCurrent)
            if not segment then return end
        end
        snapshot(false)
    end)
    refreshPanel()
    if savedRows > 0 then
        say("Recording a new session after the saved ones. Click Save & Reload when finished.")
    else
        say("Recording this character. Click Save & Reload when finished.")
    end
end

resume:SetScript("OnClick", start)
save:SetScript("OnClick", function()
    if not needsExport() then start(); return end
    snapshot(true)
    exportRequested = true
    refreshPanel()
    -- PLAYER_LOGOUT finalizes the segment when the client actually reloads.
    -- A denied click leaves an active recording running.
    if not (C_UI and C_UI.Reload and pcall(C_UI.Reload)) then
        say("Type /reload to save your recording.")
    end
end)

-- Interactions ---------------------------------------------------------------

local function npcIdentity()
    if not UnitExists("npc") then return "", "", "" end
    local guid, name = UnitGUID("npc"), UnitName("npc")
    local unitType, npcId = "", ""
    if readable(guid) then
        local kind, _, _, _, _, id = strsplit("-", guid)
        if kind == "Player" then return "Player", "", "" end
        if kind ~= "Creature" and kind ~= "Vehicle" then return "", "", "" end
        unitType, npcId = text(kind), int(tonumber(id))
    end
    return unitType, npcId, unitType ~= "" and text(name) or ""
end

-- Several UI events describe the same NPC window; keep the first for each opening.
local function noteNpc(kind)
    if not segment then return end
    local unitType, npcId, name = npcIdentity()
    if unitType == "Player" then return end
    local key = unitType .. npcId .. name
    if key == "" then key = kind end
    local now = GetTime()
    if key == openNpc or (key == lastNpcKey and now - lastNpcAt < 5) then return end
    openNpc, lastNpcKey, lastNpcAt = key, key, now
    record("n", text(kind), unitType, npcId, name)
end

local function rememberQuest()
    local id = GetQuestID and GetQuestID()
    if not readable(id) or not id or id == 0 then return end
    local unitType, npcId, name = npcIdentity()
    quests[id] = { title = GetTitleText and GetTitleText(), unitType = unitType, npcId = npcId, name = name }
end

local function quest(kind, id, xpReward, moneyReward)
    if not segment or not readable(id) or type(id) ~= "number" then return end
    local key = kind .. id
    local now = GetTime()
    if recent[key] and now - recent[key] < 10 then return end
    recent[key] = now
    local cached = quests[id] or {}
    local questTitle = C_QuestLog and C_QuestLog.GetTitleForQuestID and C_QuestLog.GetTitleForQuestID(id)
    if not readable(questTitle) or questTitle == "" then questTitle = cached.title end
    record("q", kind, int(id), text(questTitle), int(xpReward), int(moneyReward),
        cached.unitType or "", cached.npcId or "", cached.name or "")
end

local function clearRecording()
    if not canClearSaved() then
        return say(savedBytes > 0 and "Click Save & Reload before clearing these recordings." or "Nothing to clear.")
    end
    AlloyRouteRecording, AlloyRouteExportedBytes, savedBytes = nil, nil, 0
    savedRows = savedRows - loadedRows
    loadedRows, reminder, exportRequested, full = 0, 0, false, false
    say("Cleared the previously saved sessions for this character.")
    if AlloyRouteAutoRecord and not segment and #pending == 0 then start() end
    refreshPanel()
end

StaticPopupDialogs.ALLOYROUTE_CLEAR = {
    text = "Clear the sessions saved before this login or reload? Check Grafana first. Your current recording will continue.",
    button1 = "Clear recordings", button2 = CANCEL,
    OnAccept = clearRecording, timeout = 0, whileDead = true, hideOnEscape = true,
}
clear:SetScript("OnClick", function()
    if canClearSaved() then StaticPopup_Show("ALLOYROUTE_CLEAR") end
end)

SLASH_ALLOYROUTE1 = "/chronicle"
SLASH_ALLOYROUTE2 = "/alloyroute"
SlashCmdList.ALLOYROUTE = function(input)
    local cmd = strtrim(input):lower()
    if cmd == "start" then
        start()
    elseif cmd == "stop" then
        AlloyRouteAutoRecord = false
        if segment then snapshot(true); finish() end
        refreshPanel()
        say("Stopped. Click Save & Reload or log out to write your recording to disk.")
    elseif cmd == "clear" then
        if canClearSaved() then
            say("Check delivery in the companion, then type /chronicle clear confirm.")
        elseif savedBytes > 0 then
            say("Click Save & Reload before clearing these recordings.")
        else
            say("Nothing to clear.")
        end
    elseif cmd == "clear confirm" then
        clearRecording()
    elseif cmd == "status" then
        say(string.format("%s. %d rows, %.1f KiB of %d KiB.", segment and "Recording" or "Stopped",
            usedRows(), usedBytes() / 1024, MAX_BYTES / 1024))
    else
        say((segment and "Recording. " or "") .. "Commands: /chronicle start, stop, status, clear.")
    end
end

local events = CreateFrame("Frame")
for _, name in ipairs({
    "PLAYER_REGEN_DISABLED", "PLAYER_REGEN_ENABLED", "PLAYER_EQUIPMENT_CHANGED", "UNIT_RESISTANCES", "UNIT_STATS",
    "ADDON_LOADED", "PLAYER_LOGOUT", "PLAYER_ENTERING_WORLD", "ZONE_CHANGED_NEW_AREA",
    "PLAYER_LEVEL_UP", "PLAYER_INTERACTION_MANAGER_FRAME_SHOW", "PLAYER_INTERACTION_MANAGER_FRAME_HIDE",
    "QUEST_LOG_UPDATE", "SKILL_LINES_CHANGED", "UPDATE_FACTION", "ZONE_CHANGED", "ZONE_CHANGED_INDOORS",
    "PLAYER_DEAD", "PLAYER_ALIVE", "PLAYER_UNGHOST", "PLAYER_TARGET_CHANGED", "CHAT_MSG_LOOT",
    "GOSSIP_SHOW", "GOSSIP_CLOSED", "QUEST_GREETING", "QUEST_DETAIL", "QUEST_PROGRESS",
    "QUEST_COMPLETE", "QUEST_FINISHED", "QUEST_ACCEPTED", "QUEST_TURNED_IN",
}) do
    events:RegisterEvent(name)
end

events:SetScript("OnEvent", function(_, event, ...)
    if event == "ADDON_LOADED" then
        if ... ~= "AlloyRoute" then return end
        local pos = AlloyRoutePanelPosition
        if type(pos) == "table" and type(pos[1]) == "number" and type(pos[2]) == "number" then
            panel:ClearAllPoints()
            panel:SetPoint("BOTTOMLEFT", UIParent, "BOTTOMLEFT", pos[1] * UIParent:GetWidth(), pos[2] * UIParent:GetHeight())
        end
        local saved = AlloyRouteRecording
        if type(saved) ~= "string" then AlloyRouteRecording, saved = nil, "" end
        savedBytes = #saved
        for row in saved:gmatch("[^;]+") do
            local kind = row:sub(1, 2)
            if kind ~= "v1" and kind ~= "v2" and kind ~= "e|" then
                savedRows = savedRows + 1
            end
        end
        loadedRows = savedRows
        if AlloyRouteAutoRecord == nil and saved:sub(1, 3) == "v2|" then AlloyRouteAutoRecord = true end
        if Enum and Enum.PlayerInteractionType then
            for key, value in pairs(Enum.PlayerInteractionType) do interactionNames[value] = key end
        end
        if savedBytes > 0 then
            reminder = 3 -- capacity warnings are for the session being recorded
            refreshPanel()
            local hint = canClearSaved() and "Check delivery in the companion before clearing." or "Click Save & Reload to unlock Clear."
            say(string.format("%d previously saved rows. %s", savedRows, hint))
        end
        return
    elseif event == "PLAYER_ENTERING_WORLD" and not segment then
        if AlloyRouteAutoRecord then start() else refreshPanel() end
        return
    elseif event == "PLAYER_LOGOUT" then
        if segment then
            armor(true)
            snapshot(false)
            finish()
        end
        if #pending > 0 then AlloyRouteExportedBytes = nil end
        commit()
        if exportRequested and AlloyRouteRecording then
            AlloyRouteExportedBytes = #AlloyRouteRecording
        end
        return
    end
    if not segment then return end
    if event == "QUEST_LOG_UPDATE" then objectives()
    elseif event == "SKILL_LINES_CHANGED" then ranks()
    elseif event == "UPDATE_FACTION" then reputation()
    elseif event == "ZONE_CHANGED" or event == "ZONE_CHANGED_INDOORS" then subzone()
    elseif event == "PLAYER_DEAD" or event == "PLAYER_ALIVE" or event == "PLAYER_UNGHOST" then life()
    elseif event == "PLAYER_TARGET_CHANGED" then target()
    elseif event == "CHAT_MSG_LOOT" then loot((...), select(11, ...))
    elseif event == "PLAYER_REGEN_DISABLED" or event == "PLAYER_REGEN_ENABLED" then
        combat(event == "PLAYER_REGEN_DISABLED", false)
    elseif event == "PLAYER_EQUIPMENT_CHANGED" then
        gearChange(...)
        armor(false)
    elseif event == "UNIT_RESISTANCES" or event == "UNIT_STATS" then
        if ... == "player" then armor(false) end
    elseif event == "PLAYER_ENTERING_WORLD" or event == "ZONE_CHANGED_NEW_AREA" then
        snapshot(false)
        subzone()
    elseif event == "PLAYER_LEVEL_UP" then
        local level = ...
        record("l", int(level))
        -- UnitLevel and UnitXPMax can lag the event; take a second look shortly after.
        snapshot(true, level)
        C_Timer.After(2, function() snapshot(false) end)
    elseif event == "PLAYER_INTERACTION_MANAGER_FRAME_SHOW" then
        local kind = interactionNames[...]
        if kind and kind ~= "None" and kind ~= "TradePartner" then noteNpc(kind) end
    elseif event == "GOSSIP_SHOW" then
        noteNpc("Gossip")
    elseif event == "QUEST_GREETING" or event == "QUEST_PROGRESS" then
        noteNpc("QuestGiver")
    elseif event == "QUEST_DETAIL" or event == "QUEST_COMPLETE" then
        noteNpc("QuestGiver")
        rememberQuest()
    elseif event == "QUEST_ACCEPTED" then
        local first, second = ...
        -- Some client versions pass the quest-log index before the quest ID.
        quest("accepted", type(second) == "number" and second or first)
    elseif event == "QUEST_TURNED_IN" then
        quest("turned_in", ...)
    elseif event == "PLAYER_INTERACTION_MANAGER_FRAME_HIDE" or event == "QUEST_FINISHED" then
        openNpc = nil
    elseif event == "GOSSIP_CLOSED" then
        if not ... then openNpc = nil end
    end
end)
